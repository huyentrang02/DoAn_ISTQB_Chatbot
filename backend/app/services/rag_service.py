import asyncio
import os
import re
import shutil
import time
from datetime import datetime
from typing import List

from app.core.config import settings
from app.core.custom_embeddings import NativeGoogleEmbeddings
from fastapi import UploadFile
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from sentence_transformers import CrossEncoder
from supabase.client import Client, create_client


class RAGService:
    def __init__(self):
        self.embeddings = NativeGoogleEmbeddings(
            model="models/gemini-embedding-001",
            api_key=settings.GOOGLE_API_KEY,
            output_dimensionality=768,
        )
        self.llm = ChatGoogleGenerativeAI(
            model="models/gemini-2.5-flash",
            temperature=0.7,
            google_api_key=settings.GOOGLE_API_KEY,
        )
        self.llm_strict = ChatGoogleGenerativeAI(
            model="models/gemini-2.5-flash",
            temperature=0.0,
            google_api_key=settings.GOOGLE_API_KEY,
        )

        self.supabase: Client = create_client(
            settings.SUPABASE_URL, settings.SUPABASE_KEY
        )
        # We still keep vector_store for "add_documents" convenience,
        # but we will implement custom search to avoid LangChain RPC issues
        self.vector_store = SupabaseVectorStore(
            client=self.supabase,
            embedding=self.embeddings,
            table_name="documents",
            query_name="match_documents_v2",
        )

        print("[RAGService] Đang tải mô hình CrossEncoder (Re-ranking)...")
        # Load nhỏ, nhanh, ~80MB
        self.reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    def _clear_all_documents(self):
        """Xóa toàn bộ documents trong vector DB trước khi insert mới"""
        try:
            # id là UUID — dùng nil UUID làm điều kiện để xóa tất cả rows thật
            self.supabase.from_("documents").delete().neq(
                "id", "00000000-0000-0000-0000-000000000000"
            ).execute()
            print("[RAGService] Đã xóa toàn bộ documents cũ.")
        except Exception as e:
            print(f"[RAGService] Lỗi khi xóa documents: {e}")
            raise

    async def process_pdf(self, file: UploadFile):
        # Save temp file
        temp_file_path = f"temp_{file.filename}"
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        try:
            # ── Bước 1: Extract text bằng LlamaParse ──────────────────────
            import nest_asyncio

            try:
                from llama_parse import LlamaParse
            except ImportError:
                raise RuntimeError(
                    "Chưa cài đặt llama-parse. Hãy chạy: pip install llama-parse"
                )

            nest_asyncio.apply()

            print(
                f"[RAGService] Đang dùng LlamaParse để phân tích file: {file.filename}"
            )
            parser = LlamaParse(
                api_key=settings.LLAMA_CLOUD_API_KEY,
                result_type="markdown",
                verbose=True,
                num_workers=4,
            )

            # Load_data là hàm đồng bộ (chạy mất vài phút), cần bỏ vào to_thread để không nghẽn Server
            documents = await asyncio.to_thread(parser.load_data, temp_file_path)
            if not documents:
                raise ValueError("LlamaParse không trả về kết quả nào.")

            markdown_text = "\n\n".join([doc.text for doc in documents])

            # ── Bước 2: Chunk theo cấu trúc heading ─────────────
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

            # ── Bước 3: Enrich metadata ────────────────────────────────────
            upload_timestamp = datetime.now().isoformat()
            for i, split in enumerate(splits):
                split.metadata.update(
                    {
                        "source": file.filename,
                        "chapter": split.metadata.get("chapter", ""),
                        "section": split.metadata.get("section", ""),
                        "subsection": split.metadata.get("subsection", ""),
                        "chunk_index": i,
                        "total_chunks": len(splits),
                        "upload_date": upload_timestamp,
                        "chunking_strategy": "llamaparse_markdown_header",
                        "content_length": len(split.page_content),
                    }
                )

            # ── Bước 4: Embed & Store theo batch (rate limit Gemini) ───────
            BATCH_SIZE = 80
            BATCH_DELAY = 65  # giây

            total_batches = (len(splits) + BATCH_SIZE - 1) // BATCH_SIZE
            for batch_idx in range(total_batches):
                batch = splits[batch_idx * BATCH_SIZE : (batch_idx + 1) * BATCH_SIZE]
                print(
                    f"[RAGService] Embedding batch {batch_idx + 1}/{total_batches} ({len(batch)} chunks)..."
                )

                for attempt in range(3):
                    try:
                        # Vector_store add_documents có thể là hàm đồng bộ, an toàn đẩy vào thread
                        await asyncio.to_thread(self.vector_store.add_documents, batch)
                        break
                    except Exception as e:
                        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                            wait = BATCH_DELAY * (attempt + 1)
                            print(
                                f"[RAGService] Rate limit hit, chờ {wait}s rồi thử lại..."
                            )
                            await asyncio.sleep(wait)
                        else:
                            raise

                if batch_idx < total_batches - 1:
                    print(
                        f"[RAGService] Đã xong batch {batch_idx + 1}, chờ {BATCH_DELAY}s..."
                    )
                    await asyncio.sleep(BATCH_DELAY)

            # ── Bước 5: Atomic Swap - Xoá dữ liệu cũ sau khi nạp thành công ──
            print(
                f"[RAGService] Nạp xong {len(splits)} chunks. Đang dọn dẹp dữ liệu cũ..."
            )
            await self._cleanup_old_documents(file.filename, upload_timestamp)

            return {
                "status": "success",
                "message": f"File processed successfully ({total_batches} batches). Old data cleaned.",
                "chunks_added": len(splits),
            }

        finally:
            # Cleanup temp file
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    async def _cleanup_old_documents(self, source_name: str, current_timestamp: str):
        """Xoá các bản ghi cũ của cùng một tài liệu (dựa trên upload_date và source)"""
        try:

            def delete_sync():
                return (
                    self.supabase.table("documents")
                    .delete()
                    .eq("metadata->>source", source_name)
                    .lt("metadata->>upload_date", current_timestamp)
                    .execute()
                )

            # Chạy tác vụ I/O đồng bộ trong thread pool để không block event loop
            res = await asyncio.to_thread(delete_sync)
            deleted_count = len(res.data) if res.data else 0
            print(
                f"[RAGService] Đã xoá {deleted_count} bản ghi cũ lỗi thời của '{source_name}'."
            )
        except Exception as e:
            print(f"[RAGService] Lỗi khi dọn dẹp dữ liệu cũ: {e}")
            # Không raise lỗi ở đây vì dữ liệu mới đã vào rồi, chỉ là chưa dọn được cái cũ (có thể dọn sau)

    async def _bm25_search(self, query: str, k: int) -> List[Document]:
        """Tìm kiếm full-text bằng BM25 qua Supabase"""
        response = self.supabase.rpc(
            "match_documents_fulltext", {"search_query": query, "match_count": k}
        ).execute()

        documents = []
        for item in response.data:
            doc = Document(
                page_content=item.get("content"), metadata=item.get("metadata")
            )
            doc.metadata["bm25_rank"] = item.get("rank")
            documents.append(doc)

        return documents

    def _rrf_merge(
        self, semantic_docs: List[Document], bm25_docs: List[Document], k=60
    ) -> List[Document]:
        """Kết hợp kết quả bằng Reciprocal Rank Fusion"""
        doc_scores = {}
        docs_dict = {}

        for rank, doc in enumerate(semantic_docs):
            doc_key = f"{doc.metadata.get('source', 'unknown')}_{doc.metadata.get('chunk_index', rank)}"
            doc_scores[doc_key] = doc_scores.get(doc_key, 0) + 1 / (k + rank + 1)
            docs_dict[doc_key] = doc

        for rank, doc in enumerate(bm25_docs):
            doc_key = f"{doc.metadata.get('source', 'unknown')}_{doc.metadata.get('chunk_index', rank)}"
            doc_scores[doc_key] = doc_scores.get(doc_key, 0) + 1 / (k + rank + 1)
            docs_dict[doc_key] = doc

        # Sắp xếp theo RRF score giảm dần
        sorted_keys = sorted(
            doc_scores.keys(), key=lambda x: doc_scores[x], reverse=True
        )
        return [docs_dict[key] for key in sorted_keys]

    def _rerank(self, query: str, docs: List[Document], top_n: int) -> List[Document]:
        """Xếp hạng lại Top-K kết quả dùng CrossEncoder"""
        if not docs:
            return []

        pairs = [[query, doc.page_content] for doc in docs]
        scores = self.reranker.predict(pairs)

        for i, doc in enumerate(docs):
            doc.metadata["rerank_score"] = float(scores[i])

        ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
        return [doc for score, doc in ranked[:top_n]]

    def _expand_context(self, docs: List[Document]) -> List[Document]:
        """Mở rộng ngữ cảnh: Nối tất cả các chunk cùng section/chapter để tạo thành văn bản hoàn chỉnh"""
        if not docs:
            return []

        expanded_docs = []
        processed_sections = set()

        for doc in docs:
            meta = doc.metadata
            source = meta.get("source", "")
            chapter = meta.get("chapter", "")
            section = meta.get("section", "")

            group_key = section if section else chapter

            # Bỏ qua nếu không có thông tin section hoặc chapter để nhóm
            if not group_key:
                expanded_docs.append(doc)
                continue

            # Rút trích tiền tố số học (VD: "1.3", "4.2.2") để gom nhóm thông minh hơn
            num_match = re.search(r"^(\d+(?:\.\d+)*)", group_key)
            if num_match:
                search_prefix = num_match.group(1)
            else:
                search_prefix = group_key

            sec_key = f"{source}_{search_prefix}"

            if sec_key in processed_sections:
                continue

            processed_sections.add(sec_key)

            try:
                # Kéo toàn bộ chunk của section/chapter này từ CSDL một cách linh hoạt
                query = (
                    self.supabase.table("documents")
                    .select("content, metadata")
                    .eq("metadata->>source", source)
                )

                if num_match:
                    # Dùng ilike để gom tất tuốt các chunk bị lỗi OCR font (VD: "1.3." vs "1.3") hoặc chunk con
                    if section:
                        query = query.ilike("metadata->>section", f"{search_prefix}%")
                    else:
                        query = query.ilike("metadata->>chapter", f"{search_prefix}%")
                else:
                    if section:
                        query = query.eq("metadata->>section", section)
                    else:
                        query = query.eq("metadata->>chapter", chapter)

                response = query.execute()

                if response.data:
                    # Sắp xếp theo chunk_index để văn bản liền mạch
                    sorted_chunks = sorted(
                        response.data,
                        key=lambda x: x.get("metadata", {}).get("chunk_index", 0),
                    )

                    # Giữa các cục được nối với nhau có thể có khoảng trống
                    full_text = "\n".join(
                        [chunk.get("content", "") for chunk in sorted_chunks]
                    )

                    new_meta = meta.copy()
                    new_meta["expanded"] = True
                    new_meta["total_expanded_chunks"] = len(sorted_chunks)

                    super_doc = Document(page_content=full_text, metadata=new_meta)
                    expanded_docs.append(super_doc)
                else:
                    expanded_docs.append(doc)
            except Exception as e:
                print(f"[RAGService] Lỗi khi mở rộng context cho {sec_key}: {e}")
                expanded_docs.append(doc)

        return expanded_docs

    async def search_similar(
        self,
        query: str,
        k: int = 15,
        final_k: int = 4,
        match_threshold: float = 0.4,
        use_hybrid: bool = True,
        use_rerank: bool = True,
    ) -> List[Document]:
        print(f"\n[RAG] Query: '{query}'")

        # 1. Semantic Search
        query_embedding = self.embeddings.embed_query(query)
        response = self.supabase.rpc(
            "match_documents_v2",
            {
                "query_embedding": query_embedding,
                "match_threshold": match_threshold,
                "match_count": k,
            },
        ).execute()

        semantic_docs = []
        for item in response.data:
            doc = Document(
                page_content=item.get("content"), metadata=item.get("metadata")
            )
            doc.metadata["semantic_similarity"] = item.get("similarity")
            semantic_docs.append(doc)

        final_docs = semantic_docs

        # 2. BM25 Search & RRF Merge
        if use_hybrid:
            bm25_docs = await self._bm25_search(query, k)
            final_docs = self._rrf_merge(semantic_docs, bm25_docs)
            print(
                f"[RAG] Semantic: {len(semantic_docs)}, BM25: {len(bm25_docs)} -> Merge: {len(final_docs)} chunks"
            )

        # 3. Re-ranking
        final_docs = final_docs[:k]  # Giới hạn đưa vào rerank
        if use_rerank and final_docs:
            t0 = time.time()
            final_docs = self._rerank(query, final_docs, top_n=final_k)
            print(f"[RAG] Reranking took {time.time() - t0:.2f}s")
        else:
            final_docs = final_docs[:final_k]

        # 4. Context Expansion (Mở rộng ngữ cảnh)
        t1 = time.time()
        final_docs = self._expand_context(final_docs)
        print(
            f"[RAG] Context Expansion took {time.time() - t1:.2f}s, resulted in {len(final_docs)} super-chunks"
        )

        return final_docs

    async def _route_query(self, query: str) -> bool:
        """Định tuyến tin nhắn: Kích hoạt True nếu đây là câu chào hỏi bâng quơ"""
        prompt = f"Phân loại tin nhắn sau. Nếu đây chỉ là câu giao tiếp chào hỏi, cảm ơn, khen ngợi bâng quơ, hãy trả lời 'CHITCHAT'. Nếu là các câu hỏi cần tìm kiếm thông tin/tư vấn chuyên môn, dữ liệu, bài tập, hãy trả lời 'RAG'.\nTin nhắn: '{query}'"
        response = await self.llm_strict.ainvoke([HumanMessage(content=prompt)])
        return "CHITCHAT" in response.content.upper()

    async def chat_stream(
        self,
        query: str,
        skip_routing: bool = False,
        image_base64: str = None,
        image_mime: str = "image/png",
    ):
        """Hàm trò chuyện chính dạng Stream"""
        # 1. Định tuyến (Query Router)
        if not skip_routing:
            is_chitchat = await self._route_query(query)
            if is_chitchat:
                print("[RAG] Routing: Câu hỏi bâng quơ (CHITCHAT). Xử lý ngay...")
                messages = [
                    SystemMessage(
                        content="Bạn là trợ lý ảo thân thiện do chủ trang web tạo ra. Hãy trả lời ngắn gọn và tự nhiên các câu giao tiếp cơ bản từ người dùng."
                    ),
                    HumanMessage(content=query),
                ]

                async for chunk in self.llm.astream(messages):
                    if chunk.content:
                        yield chunk.content
                return

        # 2. Tìm kiếm
        docs = await self.search_similar(query, k=15, final_k=4)

        if not docs:
            yield "Xin lỗi, tôi không tìm thấy thông tin liên quan trong tài liệu ISTQB để trả lời câu hỏi của bạn."
            return

        # 4. Gắn Metadata và Nối Context
        context_str = "\n\n".join([doc.page_content for doc in docs])

        # 5. Khởi tạo mảng LLM Native History
        system_msg = SystemMessage(
            content=(
                "Bạn là một trợ lý ảo chuyên nghiệp về kiểm thử phần mềm (ISTQB). "
                "Hãy trả lời dựa trên thông tin (Context) được cung cấp bên dưới.\n\n"
                "QUY TẮC BẮT BUỘC:\n"
                "1. Câu hỏi thường: Trả lời NGẮN GỌN, SÚC TÍCH. Dùng gạch đầu dòng nếu cần liệt kê.\n"
                "2. Thuật ngữ Tiếng Anh: Giữ nguyên thuật ngữ chuyên ngành "
                "(Error, Defect, Failure, Test Case...) hoặc dùng 'Tiếng Việt (Tiếng Anh)'.\n"
                "3. Câu hỏi trắc nghiệm — BẮT BUỘC theo đúng 2 bước sau:\n"
                "   Bước 1 - Phân tích từng đáp án theo format:\n"
                "   [A]: ĐÚNG/SAI — <lý do 1 câu dựa trên Context>\n"
                "   [B]: ĐÚNG/SAI — <lý do 1 câu dựa trên Context>\n"
                "   [C]: ĐÚNG/SAI — <lý do 1 câu dựa trên Context>\n"
                "   [D]: ĐÚNG/SAI — <lý do 1 câu dựa trên Context>\n"
                "   Bước 2 - Kết luận: **ĐÁP ÁN ĐÚNG: [X]**\n"
                "   Lưu ý: Với câu hỏi NOT/EXCEPT — đáp án nào ĐÚNG theo câu hỏi là đáp án chứa thông tin SAI/không có trong Context. "
                "Phải đọc kỹ từng từ, không được suy luận 'gần đúng'.\n"
                "4. Trích dẫn: Lồng ghép mã chương vào lý do (ví dụ: 'Theo mục 3.2.5...'). "
                "TUYỆT ĐỐI KHÔNG tạo danh sách trích dẫn cuối bài.\n"
                "5. Tính trung thực: Không bịa đặt kiến thức ngoài Context."
            )
        )

        messages = [system_msg]

        final_prompt = f"Context:\n{context_str}\n\nQuestion:\n{query}"

        # Nếu có ảnh đính kèm → dùng multimodal content (Gemini Vision)
        if image_base64:
            mime = image_mime or "image/png"
            messages.append(
                HumanMessage(
                    content=[
                        {"type": "text", "text": final_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{image_base64}"},
                        },
                    ]
                )
            )
        else:
            messages.append(HumanMessage(content=final_prompt))

        full_ai_response = ""
        # 6. Generator sinh chữ từ LLM
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                full_ai_response += chunk.content
                yield chunk.content

        # 7. Tự động chèn Nguồn tham khảo vào cuối câu trả lời
        # Tìm xem đây có phải câu hỏi trắc nghiệm và có ĐÁP ÁN ĐÚNG không
        correct_match = re.search(
            r"ĐÁP ÁN ĐÚNG:\s*(?:\*\*)?\[?([A-D])\]?(?:\*\*)?",
            full_ai_response,
            re.IGNORECASE,
        )
        referenced_chapters = set()

        if correct_match:
            correct_opt = correct_match.group(1).upper()
            # Lấy đoạn giải thích của đáp án đúng (từ [X]: đến đáp án tiếp theo hoặc Bước 2)
            pattern = rf"\[{correct_opt}\]:.*?(?=\n\s*\[[A-D]\]:|\n\s*Bước 2|$)"
            explanation_match = re.search(
                pattern, full_ai_response, re.IGNORECASE | re.DOTALL
            )
            if explanation_match:
                referenced_chapters = set(
                    re.findall(r"(\d+(?:\.\d+)+)", explanation_match.group(0))
                )

        # Nếu không phải câu trắc nghiệm, hoặc đoạn giải thích đáp án đúng không chứa mã chương nào
        if not referenced_chapters:
            referenced_chapters = set(re.findall(r"(\d+(?:\.\d+)+)", full_ai_response))

        unique_num_mapping = {}
        fallback_sources = []

        for doc in docs:
            meta = doc.metadata
            # Ưu tiên lấy tiêu đề chi tiết nhất: subsection (###) > section (##) > chapter (#)
            headings = [
                meta.get("subsection", ""),
                meta.get("section", ""),
                meta.get("chapter", ""),
            ]
            ch = next((h.strip() for h in headings if h and h.strip()), "")

            if not ch:
                continue

            # Chuẩn hoá (VD: "1.2.1." -> "1.2.1")
            match = re.search(r"^(\d+(?:\.\d+)*)\.?\s+(.*)$", ch)
            if match:
                num = match.group(1)  # Lấy phần số (1.3, 1.2.1)
                text = match.group(2)
                text = re.sub(r"<[^>]+>", "", text).strip()

                if not referenced_chapters or any(
                    ref in num for ref in referenced_chapters
                ):
                    if num not in unique_num_mapping:
                        unique_num_mapping[num] = text
            else:
                if ch not in fallback_sources:
                    fallback_sources.append(ch)

        final_list = []
        if len(unique_num_mapping) > 0:
            # Lọc các nguồn có dạng x.y.z (có ít nhất 2 dấu chấm)
            xyz_keys = [k for k in unique_num_mapping.keys() if k.count(".") >= 2]
            # Nếu có dạng x.y.z thì ưu tiên cái đầu tiên (liên quan nhất), nếu không thì lấy cái đầu tiên của mapping
            best_num = xyz_keys[0] if xyz_keys else list(unique_num_mapping.keys())[0]
            final_list.append(f"- *{best_num}. {unique_num_mapping[best_num]}*")

        # Nếu vẫn không có mã chương nào trùng khớp, lấy nguồn fallback đầu tiên (liên quan nhất)
        if not final_list and fallback_sources:
            for ch in fallback_sources:
                ch_clean = re.sub(r"<[^>]+>", "", ch).strip()
                if ch_clean and not any(
                    noise in ch_clean.lower()
                    for noise in ["chapter ", "learning", "level"]
                ):
                    final_list.append(f"- *{ch_clean}*")
                    break  # Chỉ lấy 1 nguồn

        if final_list:
            yield "\n\n---\n**Nguồn tham khảo:**\n"
            for src in final_list:
                yield src + "\n"


rag_service = RAGService()
