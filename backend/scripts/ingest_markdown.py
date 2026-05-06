import asyncio
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(base_dir)
load_dotenv(os.path.join(base_dir, ".env"))
from app.core.config import settings  # noqa: E402
from app.core.custom_embeddings import NativeGoogleEmbeddings  # noqa: E402
from langchain_community.vectorstores import SupabaseVectorStore  # noqa: E402
from langchain_text_splitters import (  # noqa: E402
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from supabase import Client, create_client  # noqa: E402
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
embeddings = NativeGoogleEmbeddings(
    model="models/gemini-embedding-001",
    api_key=settings.GOOGLE_API_KEY,
    output_dimensionality=768,
)

vector_store = SupabaseVectorStore(
    client=supabase,
    embedding=embeddings,
    table_name="documents",
    query_name="match_documents_v2",
)

md_path = os.path.join(
    base_dir, "materials", "Syllabus", "ISTQB_CTFL_Syllabus_v4.0.1.md"
)
# Dummy source name since the app expects PDF source
source_name = "ISTQB_CTFL_Syllabus_v4.0.1.pdf"


async def main():
    if not os.path.exists(md_path):
        print(
            f"ERROR: Không tìm thấy file {md_path}. Vui lòng chạy parse_syllabus.py trước."
        )
        return

    with open(md_path, "r", encoding="utf-8") as f:
        markdown_text = f.read()

    print(
        f"✅ Đã tải nội dung Markdown thành công (Kích thước: {len(markdown_text)} chars)."
    )

    # 1. Clear database
    print("🗑️ Đang xoá dữ liệu cũ trong bảng 'documents'...")
    try:
        supabase.table("documents").delete().neq(
            "id", "00000000-0000-0000-0000-000000000000"
        ).execute()
    except Exception as e:
        print(
            f"Cảnh báo khi xóa dữ liệu (có thể do lỗi UUID cast nhưng data vẫn bị xoá): {e}"
        )

    # 2. Chunking
    print("✂️ Đang chia tách văn bản dựa theo các thẻ H1, H2, H3...")
    headers_to_split_on = [
        ("#", "chapter"),
        ("##", "section"),
        ("###", "subsection"),
    ]
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on,
        strip_headers=False,
    )
    md_splits = md_splitter.split_text(markdown_text)

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=150,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    splits = text_splitter.split_documents(md_splits)

    print(f"📊 Tổng số Chunks được tạo ra: {len(splits)}")

    # 3. Add metadata
    upload_time = datetime.now().isoformat()
    for i, split in enumerate(splits):
        split.metadata.update(
            {
                "source": source_name,
                "upload_date": upload_time,
                "chunk_index": i,
                "total_chunks": len(splits),
                "chunking_strategy": "llamaparse_markdown_header",  # New strategy tag
            }
        )

    # 4. Batch Upload (rate limit handling)
    batch_size = 50
    delay_seconds = 65

    print("🚀 Bắt đầu Push Vector embeddings lên Supabase...")
    print(
        f"   (Lưu ý: API Gemini giới hạn 100 requests/phút, hệ thống chia batch={batch_size} và delay={delay_seconds}s)"
    )

    total_batches = (len(splits) + batch_size - 1) // batch_size

    for i in range(0, len(splits), batch_size):
        batch = splits[i : i + batch_size]
        batch_num = i // batch_size + 1
        print(
            f"   -> Đang upload batch {batch_num}/{total_batches} ({len(batch)} chunks)..."
        )

        try:
            # Sync call for add_documents
            vector_store.add_documents(batch)
            print(f"      ✅ Thành công batch {batch_num}.")
        except Exception as e:
            print(f"      ❌ Lỗi ở batch {batch_num}: {e}")

        if i + batch_size < len(splits):
            print(f"      ⏳ Nghỉ {delay_seconds} giây để tránh Rate Limit Quota...")
            time.sleep(
                delay_seconds
            )  # using time.sleep instead of asyncio.sleep because add_documents is blocking

    print("\n🎉 Hoàn tất quá trình Ingestion! Dữ liệu ISTQB đã lên VectorDB.")


if __name__ == "__main__":
    asyncio.run(main())
