# Danh sách công việc (TODO): Cải thiện hệ thống RAG

File này theo dõi các hạng mục cần khắc phục và nâng cấp cho hệ thống ISTQB RAG Tester, dựa trên phân tích nhược điểm hiện tại.

## 1. Cải thiện Data Ingestion & Chunking
- [x] **Thay thế PyPDFLoader**: Đã thay bằng `pdfplumber` trong `rag_service.py`. Extract text tốt hơn, giữ được cấu trúc bảng biểu và danh sách.
- [x] **Áp dụng Semantic Chunking**: Đã implement `MarkdownHeaderTextSplitter` — tự động detect heading (`1.`, `1.1.`, `1.1.1.`) và chunk theo ranh giới section. Mỗi chunk có metadata `chapter`/`section`/`subsection`. Fallback về `RecursiveCharacterTextSplitter` nếu PDF không có heading.

## 2. Nâng cấp Truy xuất dữ liệu (Retrieval)
- [x] **Triển khai Hybrid Search**: Tích hợp thuật toán tìm kiếm từ khóa chéo (BM25/Sparse Vector) kết hợp với Semantic Search hiện tại để tìm kiếm các thuật ngữ chuyên môn ISTQB chính xác hơn (ví dụ: "Equivalence Partitioning"). (Đã dùng hàm `match_documents_fulltext` và `RRF`)
- [x] **Bổ sung Re-ranking**: Cài đặt model `cross-encoder/ms-marco-MiniLM-L-6-v2` để xếp hạng lại top-k kết quả trước khi truyền vào LLM, giúp lược bỏ các chunk nhiễu.
- [x] **Cấu hình động cho Retrieval**: Loại bỏ hardcode trong `rag_service.search_similar()`. Thêm các config `k=15`, `final_k=4`, `use_hybrid`, `use_rerank`.
- [x] **Mở rộng Ngữ cảnh (Context Expansion / Parent-Child Retrieval)**: Kéo toàn bộ các chunk có chung metadata (`chapter`, `section`) từ kết quả Top-K và gộp lại để tạo nguyên vẹn khối văn bản hoàn chỉnh cho LLM.

## 3. Hoàn thiện Logic Chatbot & Prompting
- [x] **Gán Metadata vào Context**: Khi nối các đoạn chunk, bổ sung thêm metadata (`[Nguồn: Chapter X > Section Y]`) để cung cấp bối cảnh cho LLM. (Đã xử lý trong Prompt Template)
- [x] **Bổ sung Chat Memory & Native History**: Tận dụng mảng `[HumanMessage, AIMessage]` thay vì nội dung string thuần túy để mô hình hiểu bối cảnh hội thoại tự nhiên hơn.
- [x] **Tốc độ Phản hồi (Streaming)**: Dùng `StreamingResponse` và `.astream()` để sinh từng chữ trả về UI, tránh bắt người dùng phải đợi quá lâu.
- [x] **Định tuyến Truy vấn (Query Router)**: Thêm 1 chain siêu nhanh để chuyển hướng trả lời nếu người dùng chỉ nói chuyện giao tiếp thông thường ("Xin chào", "Cảm ơn"), giảm tải gọi RAG.
- [x] **Tối ưu Sinh Câu hỏi (Rewrite Query)**: Dùng 1 LLM riêng biệt với `temperature=0.0` để viết lại câu hỏi ổn định, tránh "sáng tạo".
- [x] **Bổ sung Trích dẫn Nguồn**: Buộc LLM bằng Prompt Template phải trích dẫn chép theo đúng cấu trúc `[Source: ...]` vào cuối câu trả lời.

## 4. Fix lỗi Hệ thống Đánh giá (Evaluation)
- [x] **Sửa Ground Truth Data**: Đã thay thế hoàn toàn bằng `test_data.json` mới được parse tự động từ PDF (186 câu: 160 main + 26 additional). `evaluation_results.json` không còn dùng nữa.

## 5. Security & Deployment
- [ ] **Bảo mật API**: Bảo vệ các endpoint `/api/upload` và `/api/chat` trong FastAPI bằng cách tạo Auth Middleware kiểm tra Supabase Token hoặc JWT Token người dùng (tránh bị gọi / spam API trái phép API key của Google).

## 6. Xử lý tài liệu (Syllabus & Exams)
- [x] **Data Ingestion (Syllabus)**: Đã kết hợp LlamaParse Cloud API bóc tách file `backend/materials/Syllabus/ISTQB_CTFL_Syllabus_v4.0.1.pdf` thành file Markdown nguyên vẹn cấu trúc (Table, Heading). Chia 413 chunks chèn vào DB bằng file script `ingest_markdown.py`. Update hoàn toàn offline.
- [x] **Data Preparation (Sample Exams)**: Đã parse tự động 4 bộ đề (A/B/C/D) từ PDF bằng script `backend/scripts/parse_sample_exams.py`. Output: `backend/test_data.json` với 160 main questions (ground truth) + 26 additional, đầy đủ `correct_answer`, `rationale_per_option`, `learning_objective`, `category`.
- [ ] **Evaluation Pipeline**: Cập nhật lại script `backend/evaluate.py` để lấy dữ liệu từ file `test_data.json` mới, tự động chấm 160 câu trắc nghiệm trên Chatbot và xuất report tổng quan về độ chính xác.
