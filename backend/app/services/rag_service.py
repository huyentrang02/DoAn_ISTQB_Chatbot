import asyncio
import os
import shutil
import time
from datetime import datetime
from typing import List

from app.core.config import settings
from app.core.custom_embeddings import NativeGoogleEmbeddings
from fastapi import UploadFile
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_community.retrievers import BM25Retriever

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

# pyrefly: ignore [missing-import]
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
            model="models/gemini-2.5-pro",
            temperature=0.1,
            google_api_key=settings.GOOGLE_API_KEY,
        )
        self.llm_strict = ChatGoogleGenerativeAI(
            model="models/gemini-2.5-pro",
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
        self.bm25_retriever = None


    def _clear_all_documents(self):
        """Xóa toàn bộ documents trong vector DB trước khi insert mới"""
        try:
            # id là UUID — dùng nil UUID làm điều kiện để xóa tất cả rows thật
            self.supabase.from_("documents").delete().neq(
                "id", "00000000-0000-0000-0000-000000000000"
            ).execute()
            print("[RAGService] Đã xóa toàn bộ documents cũ.")
            self.bm25_retriever = None

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
        finally:
            self.bm25_retriever = None


    async def _init_bm25_retriever(self):
        """Khởi tạo BM25Retriever từ tất cả tài liệu trong Supabase"""
        try:
            print("[RAGService] Đang tải tất cả tài liệu từ Supabase để tạo chỉ mục BM25...")
            def fetch_docs():
                return self.supabase.table("documents").select("content, metadata").execute()
                
            response = await asyncio.to_thread(fetch_docs)
            
            docs = []
            for item in response.data:
                docs.append(Document(
                    page_content=item.get("content"),
                    metadata=item.get("metadata") or {}
                ))
            
            if docs:
                self.bm25_retriever = BM25Retriever.from_documents(docs)
                print(f"[RAGService] Đã tạo xong BM25Retriever với {len(docs)} tài liệu.")
            else:
                self.bm25_retriever = None
                print("[RAGService] Không có tài liệu nào để tạo BM25Retriever.")
        except Exception as e:
            print(f"[RAGService] Lỗi khi tạo BM25Retriever: {e}")
            self.bm25_retriever = None

    async def _bm25_search(self, query: str, k: int) -> List[Document]:
        """Tìm kiếm full-text bằng BM25 thực tế thông qua BM25Retriever"""
        if not self.bm25_retriever:
            await self._init_bm25_retriever()

        if not self.bm25_retriever:
            return []

        # Đặt k kết quả mong muốn
        self.bm25_retriever.k = k

        # BM25Retriever.invoke là đồng bộ, chạy trong thread pool để tránh block event loop
        docs = await asyncio.to_thread(self.bm25_retriever.invoke, query)

        # Gán nhãn rank cho tài liệu
        for i, doc in enumerate(docs):
            doc.metadata["bm25_rank"] = float(i + 1)

        return docs


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
        """
        Mở rộng ngữ cảnh: Nối tất cả các chunk cùng section/chapter để tạo thành văn bản hoàn chỉnh.
        Hiện tại đang comment để tiết kiệm token.
        """
        # if not docs:
        #     return []
        #
        # expanded_docs = []
        # processed_sections = set()
        #
        # for doc in docs:
        #     meta = doc.metadata
        #     source = meta.get("source", "")
        #     chapter = meta.get("chapter", "")
        #     section = meta.get("section", "")
        #
        #     group_key = section if section else chapter
        #
        #     if not group_key:
        #         expanded_docs.append(doc)
        #         continue
        #
        #     num_match = re.search(r"^(\d+(?:\.\d+)*)", group_key)
        #     if num_match:
        #         search_prefix = num_match.group(1)
        #     else:
        #         search_prefix = group_key
        #
        #     sec_key = f"{source}_{search_prefix}"
        #
        #     if sec_key in processed_sections:
        #         continue
        #
        #     processed_sections.add(sec_key)
        #
        #     try:
        #         query = (
        #             self.supabase.table("documents")
        #             .select("content, metadata")
        #             .eq("metadata->>source", source)
        #         )
        #
        #         if num_match:
        #             if section:
        #                 query = query.ilike("metadata->>section", f"{search_prefix}%")
        #             else:
        #                 query = query.ilike("metadata->>chapter", f"{search_prefix}%")
        #         else:
        #             if section:
        #                 query = query.eq("metadata->>section", section)
        #             else:
        #                 query = query.eq("metadata->>chapter", chapter)
        #
        #         response = query.execute()
        #
        #         if response.data:
        #             sorted_chunks = sorted(
        #                 response.data,
        #                 key=lambda x: x.get("metadata", {}).get("chunk_index", 0),
        #             )
        #             full_text = "\n".join(
        #                 [chunk.get("content", "") for chunk in sorted_chunks]
        #             )
        #             new_meta = meta.copy()
        #             new_meta["expanded"] = True
        #             new_meta["total_expanded_chunks"] = len(sorted_chunks)
        #
        #             super_doc = Document(page_content=full_text, metadata=new_meta)
        #             expanded_docs.append(super_doc)
        #         else:
        #             expanded_docs.append(doc)
        #     except Exception as e:
        #         print(f"[RAGService] Lỗi khi mở rộng context cho {sec_key}: {e}")
        #         expanded_docs.append(doc)
        #
        # return expanded_docs
        return docs

    async def search_similar(
        self,
        query: str,
        k: int = 15,
        final_k: int = 5,
        match_threshold: float = 0.5,
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

        # 4. Context Expansion (Mở rộng ngữ cảnh) - Tạm thời comment để tiết kiệm token
        # t1 = time.time()
        # final_docs = self._expand_context(final_docs)
        # print(
        #     f"[RAG] Context Expansion took {time.time() - t1:.2f}s, resulted in {len(final_docs)} super-chunks"
        # )

        return final_docs

    async def chat(
        self,
        query: str,
        image_base64: str = None,
        image_mime: str = "image/png",
    ) -> str:
        """Hàm trò chuyện chính dạng Stream"""
        # 1. Nhận diện câu hỏi phủ định (Negative Question Detection)
        negative_keywords = [" NOT ", " EXCEPT ", " INCORRECT "]
        is_negative = any(kw.lower() in query.lower() for kw in negative_keywords)

        if is_negative:
            extra_rule = (
                "\nIMPORTANT:\n"
                "- This is a negative question (NOT/EXCEPT/INCORRECT).\n"
                "- Your task is to identify the WRONG statement among the options.\n"
                "- Carefully check for incorrect terminology (e.g., using 'failure' instead of 'defect' in review context).\n"
            )
            print(f"[RAG] Negative question detected: {is_negative}")
        else:
            extra_rule = ""

        # 2. Xử lý Query cho RAG (Nếu có ảnh, trích xuất nội dung ảnh để tìm kiếm chính xác hơn)
        search_query = query
        if image_base64:
            print("[RAG] Đang trích xuất nội dung từ ảnh để tìm kiếm...")
            extract_prompt = "Hãy trích xuất nội dung câu hỏi hoặc các thuật ngữ ISTQB chính từ ảnh này để dùng làm từ khóa tìm kiếm tài liệu. Chỉ trả về văn bản trích xuất."
            extract_msg = HumanMessage(
                content=[
                    {"type": "text", "text": extract_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_mime or 'image/png'};base64,{image_base64}"
                        },
                    },
                ]
            )
            try:
                extraction = await self.llm.ainvoke([extract_msg])
                search_query = f"{query} {extraction.content}"
                print(f"[RAG] Search Query mở rộng: '{search_query}'")
            except Exception as e:
                print(f"[RAG] Lỗi trích xuất nội dung ảnh: {e}")

        # 3. Tìm kiếm
        docs = await self.search_similar(search_query, k=8, final_k=3)

        if not docs:
            return "Xin lỗi, tôi không tìm thấy thông tin liên quan trong tài liệu ISTQB để trả lời câu hỏi của bạn."

        # 4. Gắn Metadata vào Context để LLM tự trích dẫn
        context_parts = []
        for doc in docs:
            meta = doc.metadata
            context_parts.append(f"""
            [METADATA]
            Chapter: {meta.get("chapter", "")}
            [CONTENT]
            {doc.page_content}
            """)

        context_str = "\n\n".join(context_parts)

        system_msg = SystemMessage(
            content=(
                "Bạn là trợ lý luyện thi chứng chỉ ISTQB.\n"
                "Chỉ trả lời dựa trên ngữ cảnh được cung cấp.\n\n"
                "Quy tắc:\n"
                "- Trả lời bằng tiếng Việt.\n"
                "- Chỉ sử dụng thông tin từ ngữ cảnh được cung cấp.\n"
                "- Phân tích từng đáp án độc lập trước khi kết luận.\n"
                "- Kiểm tra kỹ thuật ngữ ISTQB cẩn thận.\n"
                "- Các đáp án có wording tương tự chưa chắc đúng.\n"
                "- Phát hiện thuật ngữ sai, không chính xác hoặc không nhất quán.\n"
                "- Không suy luận theo kiến thức bên ngoài hoặc trực giác.\n"
                "- Với câu hỏi chứa NOT/EXCEPT/INCORRECT, hãy chọn đáp án sai.\n"
                "- Trả về tất cả đáp án đúng nếu câu hỏi cho phép nhiều lựa chọn.\n"
                "- Giải thích ngắn gọn, tối đa 20 từ mỗi đáp án.\n"
                "- Nếu ngữ cảnh không đủ thông tin, hãy nói rõ.\n"
                "- Không trích dẫn nguồn cho từng đáp án.\n"
                "- Liệt kê tất cả nguồn tham khảo liên quan ở cuối.\n"
                "Định dạng trả lời:\n"
                "Đáp án: [X] hoặc [X, Y]\n\n"
                "- A: <giải thích ngắn>\n"
                "- B: <giải thích ngắn>\n"
                "- C: <giải thích ngắn>\n"
                "- D: <giải thích ngắn>\n\n"
                "***Nguồn tham khảo***:\n"
                "- [Chapter/Section]"
                f"{extra_rule}"
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

        # 6. Gọi LLM lấy kết quả cuối cùng
        response = await self.llm_strict.ainvoke(messages)
        return response.content


rag_service = RAGService()
