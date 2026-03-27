import os
import re
import shutil
import time
from datetime import datetime
from typing import List
from fastapi import UploadFile
import pdfplumber
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from supabase.client import create_client, Client
from app.core.config import settings
from sentence_transformers import CrossEncoder

class RAGService:
    def __init__(self):
        self.embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=settings.GOOGLE_API_KEY, output_dimensionality=768)
        self.llm = ChatGoogleGenerativeAI(model="models/gemini-2.5-flash", temperature=0.7, google_api_key=settings.GOOGLE_API_KEY)
        self.llm_strict = ChatGoogleGenerativeAI(model="models/gemini-2.5-flash", temperature=0.0, google_api_key=settings.GOOGLE_API_KEY)
        
        self.supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
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

    def _clean_text(self, text: str) -> str:
        """Clean PDF text from noise"""
        # Remove page numbers (e.g., "Page 123", "- 23 -")
        text = re.sub(r'Page\s+\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'-\s*\d+\s*-', '', text)
        
        # Remove excessive whitespace and newlines
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Max 2 consecutive newlines
        text = re.sub(r' +', ' ', text)  # Multiple spaces to single
        
        # Remove common PDF artifacts
        text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', text)  # Control characters
        
        return text.strip()

    def _extract_and_convert_to_markdown(self, pdf_path: str) -> tuple[str, int]:
        """
        Extract text từ PDF bằng pdfplumber và chuyển đổi heading số
        thành Markdown (# ## ###) để dùng với MarkdownHeaderTextSplitter.

        Nhận diện heading theo pattern:
          1.2.3 Title  → ### (H3 / subsection)
          1.2 Title    → ## (H2 / section)
          1 Title      → #  (H1 / chapter)

        Returns: (markdown_text, heading_count)
        """
        pages_text = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)

        full_text = "\n".join(pages_text)
        lines = full_text.split("\n")
        md_lines = []
        heading_count = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                md_lines.append("")
                continue

            # Bỏ qua các dòng Table of Contents (có chuỗi "...." kéo dài)
            if re.search(r'\.{4,}', stripped):
                continue

            # H3: "1.2.3. Title" hoặc "1.2.3.4. Title" (dấu chấm sau số cuối bắt buộc)
            if re.match(r'^\d+\.\d+\.\d+\.?\s+[^\s]', stripped):
                md_lines.append(f"### {stripped}")
                heading_count += 1
            # H2: "1.2. Title" (không phải 1.2.3)
            elif re.match(r'^\d+\.\d+\.?\s+[^\s]', stripped) and not re.match(r'^\d+\.\d+\.', stripped):
                # Loại bỏ pattern "1.2.3" bằng cách check có đúng 1 dấu chấm không
                parts = stripped.split(' ')[0].rstrip('.')
                if parts.count('.') == 1:
                    md_lines.append(f"## {stripped}")
                    heading_count += 1
                else:
                    md_lines.append(stripped)
            # H1: "1. Title" hoặc "0. Introduction" (số đơn + dấu chấm)
            elif re.match(r'^\d+\.\s+[^\s]', stripped) and not re.match(r'^\d+\.\d', stripped):
                md_lines.append(f"# {stripped}")
                heading_count += 1
            else:
                md_lines.append(stripped)

        return "\n".join(md_lines), heading_count

    async def process_pdf(self, file: UploadFile):
        # Save temp file
        temp_file_path = f"temp_{file.filename}"
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        try:
            # ── Bước 0: Xóa toàn bộ vector DB cũ ─────────────────────────
            self._clear_all_documents()

            # ── Bước 1: Extract text bằng pdfplumber ──────────────────────
            markdown_text, heading_count = self._extract_and_convert_to_markdown(temp_file_path)
            markdown_text = self._clean_text(markdown_text)

            # ── Bước 2: Chunk theo cấu trúc heading (nếu có) ─────────────
            use_markdown_splitter = heading_count >= 3  # PDF có cấu trúc rõ ràng

            if use_markdown_splitter:
                # Split theo Heading Markdown (#, ##, ###)
                headers_to_split_on = [
                    ("#",   "chapter"),
                    ("##",  "section"),
                    ("###", "subsection"),
                ]
                md_splitter = MarkdownHeaderTextSplitter(
                    headers_to_split_on=headers_to_split_on,
                    strip_headers=False,  # Giữ lại header trong nội dung chunk
                )
                md_splits = md_splitter.split_text(markdown_text)

                # Với các section lớn, tiếp tục chia nhỏ không vượt quá chunk_size
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1200,
                    chunk_overlap=150,
                    separators=["\n\n", "\n", ". ", " ", ""],
                )
                splits = text_splitter.split_documents(md_splits)
            else:
                # Fallback: PDF không có cấu trúc heading (ví dụ: scan/image PDF)
                fallback_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1000,
                    chunk_overlap=200,
                    separators=["\n\n", "\n", ". ", " ", ""],
                )
                splits = fallback_splitter.split_documents(
                    [Document(page_content=markdown_text)]
                )

            # ── Bước 3: Enrich metadata ────────────────────────────────────
            upload_timestamp = datetime.now().isoformat()
            for i, split in enumerate(splits):
                split.metadata.update({
                    "source": file.filename,
                    # Heading metadata từ MarkdownHeaderTextSplitter (nếu có)
                    "chapter":    split.metadata.get("chapter", ""),
                    "section":    split.metadata.get("section", ""),
                    "subsection": split.metadata.get("subsection", ""),
                    # Metadata chung
                    "chunk_index":       i,
                    "total_chunks":      len(splits),
                    "upload_date":       upload_timestamp,
                    "chunking_strategy": "markdown_header" if use_markdown_splitter else "recursive",
                    "content_length":    len(split.page_content),
                })

            # ── Bước 4: Embed & Store theo batch (tránh rate limit 100 req/phút) ──
            # Gemini free tier: 100 embed requests/phút
            # Mỗi batch = 80 chunks, chờ 65 giây giữa các batch
            BATCH_SIZE = 80
            BATCH_DELAY = 65  # giây

            total_batches = (len(splits) + BATCH_SIZE - 1) // BATCH_SIZE
            for batch_idx in range(total_batches):
                batch = splits[batch_idx * BATCH_SIZE : (batch_idx + 1) * BATCH_SIZE]
                print(f"[RAGService] Embedding batch {batch_idx + 1}/{total_batches} ({len(batch)} chunks)...")

                # Retry tối đa 3 lần nếu vẫn gặp 429
                for attempt in range(3):
                    try:
                        self.vector_store.add_documents(batch)
                        break
                    except Exception as e:
                        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                            wait = BATCH_DELAY * (attempt + 1)
                            print(f"[RAGService] Rate limit hit, chờ {wait}s rồi thử lại...")
                            time.sleep(wait)
                        else:
                            raise

                # Chờ giữa các batch (trừ batch cuối)
                if batch_idx < total_batches - 1:
                    print(f"[RAGService] Đã xong batch {batch_idx + 1}, chờ {BATCH_DELAY}s...")
                    time.sleep(BATCH_DELAY)

            return {
                "status": "success",
                "message": f"File processed successfully ({total_batches} batches)",
                "chunks_added": len(splits),
            }
            
        finally:
            # Cleanup
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    async def _bm25_search(self, query: str, k: int) -> List[Document]:
        """Tìm kiếm full-text bằng BM25 qua Supabase"""
        response = self.supabase.rpc(
            "match_documents_fulltext",
            {
                "search_query": query,
                "match_count": k
            }
        ).execute()

        documents = []
        for item in response.data:
            doc = Document(
                page_content=item.get("content"),
                metadata=item.get("metadata")
            )
            doc.metadata["bm25_rank"] = item.get("rank")
            documents.append(doc)

        return documents

    def _rrf_merge(self, semantic_docs: List[Document], bm25_docs: List[Document], k=60) -> List[Document]:
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
        sorted_keys = sorted(doc_scores.keys(), key=lambda x: doc_scores[x], reverse=True)
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
        import re

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
            num_match = re.search(r'^(\d+(?:\.\d+)*)', group_key)
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
                query = self.supabase.table("documents").select("content, metadata").eq("metadata->>source", source)
                
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
                    sorted_chunks = sorted(response.data, key=lambda x: x.get("metadata", {}).get("chunk_index", 0))
                    
                    # Giữa các cục được nối với nhau có thể có khoảng trống
                    full_text = "\n".join([chunk.get("content", "") for chunk in sorted_chunks])
                    
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
                "match_count": k
            }
        ).execute()

        semantic_docs = []
        for item in response.data:
            doc = Document(page_content=item.get("content"), metadata=item.get("metadata"))
            doc.metadata["semantic_similarity"] = item.get("similarity")
            semantic_docs.append(doc)

        final_docs = semantic_docs

        # 2. BM25 Search & RRF Merge
        if use_hybrid:
            bm25_docs = await self._bm25_search(query, k)
            final_docs = self._rrf_merge(semantic_docs, bm25_docs)
            print(f"[RAG] Semantic: {len(semantic_docs)}, BM25: {len(bm25_docs)} -> Merge: {len(final_docs)} chunks")

        # 3. Re-ranking
        final_docs = final_docs[:k]  # Giới hạn đưa vào rerank
        if use_rerank and final_docs:
            import time
            t0 = time.time()
            final_docs = self._rerank(query, final_docs, top_n=final_k)
            print(f"[RAG] Reranking took {time.time()-t0:.2f}s")
        else:
            final_docs = final_docs[:final_k]
            
        # 4. Context Expansion (Mở rộng ngữ cảnh)
        import time
        t1 = time.time()
        final_docs = self._expand_context(final_docs)
        print(f"[RAG] Context Expansion took {time.time()-t1:.2f}s, resulted in {len(final_docs)} super-chunks")
            
        return final_docs

    async def _rewrite_query(self, query: str, history: List[dict]) -> str:
        """Sử dụng LLM độc lập (temp=0) để viết lại câu hỏi hoàn chỉnh từ lịch sử"""
        if not history:
            return query
            
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

        system_msg = SystemMessage(content="Bạn là một AI phân tích ngữ cảnh. Dựa vào lịch sử dưới đây, hãy viết lại câu hỏi mới nhất thành một câu hỏi ĐỘC LẬP (standalone question) đầy đủ ngữ cảnh để tìm kiếm thông tin.\nNếu câu hỏi đã rõ và không chứa đại từ phụ thuộc (\"nó\", \"phần đó\"...), hãy GIỮ NGUYÊN câu hỏi gốc.\nCHỈ TRẢ VỀ CÂU HỎI, KHÔNG GIẢI THÍCH, KHÔNG TRẢ LỜI.")
        
        messages = [system_msg]
        for msg in history:
            role = msg.get("role", "user")
            if role == "user": messages.append(HumanMessage(content=msg.get("content", "")))
            else: messages.append(AIMessage(content=msg.get("content", "")))
            
        messages.append(HumanMessage(content=f"Câu hỏi mới nhất: {query}\n\nCâu hỏi Standalone:"))
        
        response = await self.llm_strict.ainvoke(messages)
        standalone = response.content.strip()
        print(f"\n[RAG] Rewrite query:\n  Original: '{query}'\n  Rewritten: '{standalone}'")
        return standalone

    async def _route_query(self, query: str) -> bool:
        """Định tuyến tin nhắn: Kích hoạt True nếu đây là câu chào hỏi bâng quơ"""
        from langchain_core.messages import HumanMessage
        prompt = f"Phân loại tin nhắn sau. Nếu đây chỉ là câu giao tiếp chào hỏi, cảm ơn, khen ngợi bâng quơ, hãy trả lời 'CHITCHAT'. Nếu là các câu hỏi cần tìm kiếm thông tin/tư vấn chuyên môn, dữ liệu, bài tập, hãy trả lời 'RAG'.\nTin nhắn: '{query}'"
        response = await self.llm_strict.ainvoke([HumanMessage(content=prompt)])
        return "CHITCHAT" in response.content.upper()

    async def chat_stream(self, query: str, history: List[dict] = None):
        """Hàm trò chuyện chính dạng Stream"""
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

        # 1. Định tuyến (Query Router)
        is_chitchat = await self._route_query(query)
        if is_chitchat:
            print("[RAG] Routing: Câu hỏi bâng quơ (CHITCHAT). Xử lý ngay...")
            messages = [SystemMessage(content="Bạn là trợ lý ảo thân thiện do chủ trang web tạo ra. Hãy trả lời ngắn gọn và tự nhiên các câu giao tiếp cơ bản từ người dùng.")]
            for msg in (history or []):
                role = msg.get("role", "user")
                if role == "user": messages.append(HumanMessage(content=msg.get("content", "")))
                else: messages.append(AIMessage(content=msg.get("content", "")))
            messages.append(HumanMessage(content=query))
            
            async for chunk in self.llm.astream(messages):
                if chunk.content:
                    yield chunk.content
            return

        # 2. Xử lý logic theo ngữ cảnh cũ
        search_query = await self._rewrite_query(query, history or [])
        
        # 3. Tìm kiếm
        docs = await self.search_similar(search_query, k=15, final_k=4)
        
        if not docs:
            yield "Xin lỗi, tôi không tìm thấy thông tin liên quan trong tài liệu ISTQB để trả lời câu hỏi của bạn."
            return

        # 4. Gắn Metadata và Nối Context
        context_str = "\n\n".join([doc.page_content for doc in docs])

        # 5. Khởi tạo mảng LLM Native History
        system_msg = SystemMessage(content="Bạn là một trợ lý ảo chuyên nghiệp về kiểm thử phần mềm (ISTQB). Hãy trả lời câu hỏi chi tiết, rõ ràng và mạch lạc dựa trên thông tin (Context) được cung cấp bên dưới.\n\nQUY TẮC BẮT BUỘC: Bạn phải giữ nguyên các thuật ngữ chuyên ngành kiểm thử bằng Tiếng Anh (ví dụ: Error, Defect, Failure, Test Case, Test Suite, Black-box, Equivalence Partitioning...) ở dạng nguyên bản gốc, hoặc dùng định dạng 'Tiếng Việt (Tiếng Anh)'. Tuyệt đối không dịch sai lệch các từ khoá chuyên môn sang tiếng Việt.\n\nĐừng tự ý bịa đặt kiến thức ngoài lề nếu không có trong Context.")
        
        messages = [system_msg]
        for msg in (history or []):
            role = msg.get("role", "user")
            if role == "user": messages.append(HumanMessage(content=msg.get("content", "")))
            else: messages.append(AIMessage(content=msg.get("content", "")))
            
        final_prompt = f"Context:\n{context_str}\n\nQuestion:\n{query}"
        messages.append(HumanMessage(content=final_prompt))

        # 6. Generator sinh chữ từ LLM
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
                
        # 7. Tự động chèn Nguồn tham khảo vào cuối câu trả lời
        yield "\n\n---\n**Nguồn tham khảo:**\n"
        
        import re
        unique_num_mapping = {}
        fallback_sources = set()
        
        for doc in docs:
            ch = doc.metadata.get('chapter', '').strip()
            if not ch:
                continue
                
            # Chuẩn hoá các chuỗi lặp (VD: "1.3" và "1.3." về chung 1 chuẩn "1.3. Testing Principles")
            match = re.search(r'^(\d+(?:\.\d+)*)\.?\s+(.*)$', ch)
            if match:
                num = match.group(1) # Lấy phần số (1.3, 1.2.1)
                text = match.group(2)
                
                # Dọn dẹp thẻ HTML rác
                text = re.sub(r'<[^>]+>', '', text).strip()
                
                if '.' in num:
                    # Dùng num làm ID duy nhất để chống lại lỗi OCR font chữ của LlamaParse (T vs Τ)
                    if num not in unique_num_mapping:
                        unique_num_mapping[num] = text
            else:
                fallback_sources.add(ch)
                
        final_list = []
        if len(unique_num_mapping) > 0:
            # Sắp xếp số học (1.2 < 1.10)
            for num in sorted(unique_num_mapping.keys(), key=lambda s: [int(x) for x in s.split('.')]):
                final_list.append(f"- *{num}. {unique_num_mapping[num]}*")
        else:
            # Fallback
            for ch in fallback_sources:
                ch_clean = re.sub(r'<[^>]+>', '', ch).strip()
                if ch_clean and not any(noise in ch_clean.lower() for noise in ["chapter ", "learning", "level"]):
                    final_list.append(f"- *{ch_clean}*")

        for src in final_list:
            yield src + "\n"

rag_service = RAGService()
