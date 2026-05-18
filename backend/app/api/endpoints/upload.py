import tempfile
import time
import uuid
from datetime import datetime
from typing import Dict

import nest_asyncio
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from app.core.config import settings
from app.core.custom_embeddings import NativeGoogleEmbeddings
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from supabase import create_client

# Enable nested asyncio for LlamaParse (required when running inside uvicorn event loop)
nest_asyncio.apply()

router = APIRouter()

# -----------------------------------------------------------------------
# In-memory job store – đủ dùng cho single-process deployment
# -----------------------------------------------------------------------
_jobs: Dict[str, dict] = {}


def _get_job(job_id: str) -> dict:
    return _jobs.get(job_id, {})


# -----------------------------------------------------------------------
# Core ingestion logic (tái sử dụng logic từ parse_syllabus + ingest_markdown)
# -----------------------------------------------------------------------
def _run_ingestion(job_id: str, pdf_bytes: bytes, filename: str):
    """
    Pipeline: PDF bytes → LlamaParse (Markdown) → Chunking → Embedding → Supabase
    Áp dụng Atomic Swap Pattern để đảm bảo tính toàn vẹn dữ liệu:
    - Upload vào staging source trước
    - Chỉ xóa dữ liệu cũ và rename SAU KHI upload 100% thành công
    - Nếu lỗi giữa chừng: rollback staging, dữ liệu cũ vẫn nguyên vẹn
    """

    def _update(status: str, message: str, progress: int = None):
        _jobs[job_id]["status"] = status
        _jobs[job_id]["message"] = message
        if progress is not None:
            _jobs[job_id]["progress"] = progress
        print(f"[Upload Job {job_id}] [{status}] {message}")

    try:
        # ── Bước 1: LlamaParse PDF → Markdown ───────────────────────────
        _update("parsing", "Đang phân tích PDF bằng LlamaParse...", progress=5)

        from llama_parse import LlamaParse  # lazy import (optional dependency)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        parser = LlamaParse(
            api_key=settings.LLAMA_CLOUD_API_KEY,
            result_type="markdown",
            verbose=False,
            num_workers=4,
        )
        documents = parser.load_data(tmp_path)

        if not documents:
            _update("error", "LlamaParse không trả về kết quả. Vui lòng kiểm tra file PDF.")
            return

        full_markdown = "\n\n".join([doc.text for doc in documents])
        _update("parsing", f"✅ LlamaParse xong. Độ dài Markdown: {len(full_markdown)} ký tự.", progress=25)

        # ── Bước 2: Chunking theo Markdown Headers ───────────────────────
        _update("chunking", "Đang chia tách văn bản theo cấu trúc mục lục...", progress=30)

        headers_to_split_on = [
            ("#", "chapter"),
            ("##", "section"),
            ("###", "subsection"),
        ]
        md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False,
        )
        md_splits = md_splitter.split_text(full_markdown)

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=150,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        splits = text_splitter.split_documents(md_splits)
        _update("chunking", f"✅ Chunking xong. Tổng số chunks: {len(splits)}", progress=40)

        # ── Bước 3: Gắn Metadata với STAGING source ─────────────────────
        # Atomic Swap Pattern:
        # - Ghi vào tên tạm (staging_source), KHÔNG xóa dữ liệu cũ ngay
        # - Chỉ swap khi toàn bộ upload thành công → zero downtime
        upload_time = datetime.now().isoformat()
        source_name = filename                      # Tên thật (dữ liệu cũ đang dùng)
        staging_source = f"__staging__{job_id}"    # Tên tạm thời, duy nhất theo job

        for i, split in enumerate(splits):
            split.metadata.update(
                {
                    "source": staging_source,   # Ghi vào staging, không đụng dữ liệu cũ
                    "upload_date": upload_time,
                    "chunk_index": i,
                    "total_chunks": len(splits),
                    "chunking_strategy": "llamaparse_markdown_header",
                }
            )

        # ── Bước 4: Khởi tạo Supabase & VectorStore ─────────────────────
        supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        embeddings = NativeGoogleEmbeddings(
            model="models/gemini-embedding-001",
            api_key=settings.GOOGLE_API_KEY,
            output_dimensionality=768,
        )
        vector_store = SupabaseVectorStore(
            client=supabase_client,
            embedding=embeddings,
            table_name="documents",
            query_name="match_documents_v2",
        )

        # ── Bước 5: Upload vào STAGING (dữ liệu cũ vẫn còn nguyên) ──────
        batch_size = 500   # Paid API: RPM 2,000 → tối đa 500 chunks/batch
        delay_seconds = 0  # Không cần delay, paid API không giới hạn RPD
        total_batches = (len(splits) + batch_size - 1) // batch_size

        _update("uploading", "Đang nhúng vào staging (dữ liệu cũ vẫn được bảo toàn)...", progress=45)

        for i in range(0, len(splits), batch_size):
            batch = splits[i : i + batch_size]
            batch_num = i // batch_size + 1

            progress = 45 + int((batch_num / total_batches) * 45)  # 45% → 90%
            _update(
                "uploading",
                f"Đang upload batch {batch_num}/{total_batches} ({len(batch)} chunks)...",
                progress=progress,
            )

            try:
                vector_store.add_documents(batch)
            except Exception as e:
                # ── ROLLBACK: xóa staging đã upload, giữ nguyên dữ liệu cũ ──
                _update("uploading", "❌ Lỗi! Đang rollback staging...", progress=progress)
                try:
                    supabase_client.table("documents").delete().eq(
                        "metadata->>source", staging_source
                    ).execute()
                    print(f"[Upload Job {job_id}] ✅ Rollback thành công. Dữ liệu cũ nguyên vẹn.")
                except Exception as rb_err:
                    print(f"[Upload Job {job_id}] ⚠️ Rollback warning: {rb_err}")
                _update(
                    "error",
                    f"Lỗi batch {batch_num}: {e}. Đã rollback, dữ liệu cũ '{source_name}' vẫn được bảo toàn.",
                )
                return

            if delay_seconds > 0 and i + batch_size < len(splits):
                time.sleep(delay_seconds)

        # ── Bước 6: ATOMIC SWAP ──────────────────────────────────────────
        # Chỉ thực hiện khi upload 100% staging thành công
        _update("uploading", "✅ Upload xong! Đang hoán đổi dữ liệu (atomic swap)...", progress=92)
        try:
            # 6a. Xóa dữ liệu CŨ — staging đã sẵn sàng thay thế
            supabase_client.table("documents").delete().eq(
                "metadata->>source", source_name
            ).execute()
            print(f"[Upload Job {job_id}] Đã xóa dữ liệu cũ '{source_name}'.")

            # 6b. Rename staging records → source_name thật
            staging_records = (
                supabase_client.table("documents")
                .select("id, metadata")
                .eq("metadata->>source", staging_source)
                .execute()
                .data
            )
            for record in staging_records:
                updated_meta = record["metadata"]
                updated_meta["source"] = source_name
                supabase_client.table("documents").update(
                    {"metadata": updated_meta}
                ).eq("id", record["id"]).execute()

            print(f"[Upload Job {job_id}] ✅ Atomic swap hoàn tất: {len(staging_records)} records → '{source_name}'.")

        except Exception as e:
            _update(
                "error",
                f"Lỗi khi atomic swap: {e}. Staging '{staging_source}' vẫn còn trên DB, liên hệ admin.",
            )
            return

        # ── Hoàn tất ────────────────────────────────────────────────────
        _jobs[job_id]["chunks_total"] = len(splits)
        _update(
            "done",
            f"✅ Hoàn tất! Đã nhúng {len(splits)} chunks lên Supabase an toàn (atomic swap).",
            progress=100,
        )

    except ImportError:
        _update("error", "Thiếu thư viện llama-parse. Chạy: pip install llama-parse")
    except Exception as e:
        _update("error", f"Lỗi không mong đợi: {str(e)}")


# -----------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------


@router.post("/upload", summary="Upload tài liệu PDF và nhúng vào Vector DB")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Nhận file PDF, chạy pipeline LlamaParse → Chunking → Embedding → Supabase
    trong nền. Trả về job_id để client poll tiến độ qua /upload/status/{job_id}.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file PDF.")

    if not settings.LLAMA_CLOUD_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="LLAMA_CLOUD_API_KEY chưa được cấu hình trên server.",
        )

    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="File rỗng.")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "filename": file.filename,
        "status": "queued",
        "message": "Đã thêm vào hàng chờ xử lý.",
        "progress": 0,
        "chunks_total": None,
        "created_at": datetime.now().isoformat(),
    }

    background_tasks.add_task(_run_ingestion, job_id, pdf_bytes, file.filename)

    return {
        "job_id": job_id,
        "filename": file.filename,
        "message": "Đã nhận file. Đang xử lý trong nền...",
        "status_url": f"/api/upload/status/{job_id}",
    }


@router.get("/upload/status/{job_id}", summary="Kiểm tra tiến độ xử lý tài liệu")
async def get_upload_status(job_id: str):
    """
    Trả về trạng thái hiện tại của job upload.
    - status: queued | parsing | chunking | uploading | done | error
    - progress: 0-100 (%)
    """
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy job: {job_id}")
    return job
