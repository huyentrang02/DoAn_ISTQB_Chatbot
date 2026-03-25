# Danh sách công việc (TODO): Cải thiện hệ thống RAG

File này theo dõi các hạng mục cần khắc phục và nâng cấp cho hệ thống ISTQB RAG Tester, dựa trên phân tích nhược điểm hiện tại.

## 1. Cải thiện Data Ingestion & Chunking
- [ ] **Thay thế PyPDFLoader**: Sử dụng các thư viện extract PDF xịn hơn (như `pdfplumber`, `Unstructured`, hoặc `LlamaParse`) để giữ được cấu trúc bảng biểu, danh sách và định dạng phức tạp của ISTQB Syllabus.
- [ ] **Áp dụng Semantic Chunking**: Thay vì chia chunk số lượng chữ cố định bằng `RecursiveCharacterTextSplitter`, hãy cài đặt chia chunk theo ngữ nghĩa (Semantic Chunking) hoặc chia dựa trên cấu trúc Header/Chapter của sách để tránh cắt làm đứt gãy các định nghĩa.

## 2. Nâng cấp Truy xuất dữ liệu (Retrieval)
- [ ] **Triển khai Hybrid Search**: Tích hợp thuật toán tìm kiếm từ khóa chéo (BM25/Sparse Vector) kết hợp với Semantic Search hiện tại để tìm kiếm các thuật ngữ chuyên môn ISTQB chính xác hơn (ví dụ: "Equivalence Partitioning").
- [ ] **Bổ sung Re-ranking**: Cài đặt một model Cross-Encoder (như BGE-Reranker hoặc Cohere Rerank) để xếp hạng lại top-k kết quả trước khi truyền vào LLM, giúp lược bỏ các chunk nhiễu.
- [ ] **Cấu hình động cho Retrieval**: Loại bỏ hardcode `k=4` và `match_threshold=0.5` trong `rag_service.search_similar()`. Xây dựng kịch bản điều chỉnh tham số tương thích với loại câu hỏi.

## 3. Hoàn thiện Logic Chatbot & Prompting
- [ ] **Gán Metadata vào Context**: Khi nối các đoạn chunk, bổ sung thêm metadata (`[Nguồn: Chương X, section Y]`) để cung cấp bối cảnh cho LLM.
- [ ] **Bổ sung Chat Memory**: Cập nhật endpoint `/api/chat` để lưu và xử lý lịch sử tin nhắn (VD: Dùng `ConversationalRetrievalChain` hoặc prompt tái tạo/làm rõ câu hỏi phụ thuộc) để hệ thống hiểu được các câu hỏi đại từ như "Nó là gì?".

## 4. Fix lỗi Hệ thống Đánh giá (Evaluation)
- [x] **Sửa Ground Truth Data**: Đã thay thế hoàn toàn bằng `test_data.json` mới được parse tự động từ PDF (186 câu: 160 main + 26 additional). `evaluation_results.json` không còn dùng nữa.

## 5. Security & Deployment
- [ ] **Bảo mật API**: Bảo vệ các endpoint `/api/upload` và `/api/chat` trong FastAPI bằng cách tạo Auth Middleware kiểm tra Supabase Token hoặc JWT Token người dùng (tránh bị gọi / spam API trái phép API key của Google).

## 6. Xử lý tài liệu (Syllabus & Exams)
- [ ] **Data Ingestion (Syllabus)**: Parse file `backend/materials/Syllabus/ISTQB_CTFL_Syllabus_v4.0.1.pdf` thành định dạng Markdown (khuyến nghị dùng LlamaParse hoặc Unstructured) để giữ nguyên cấu trúc phân cấp (Heading, Table). Áp dụng `MarkdownHeaderTextSplitter` chia chunk và đẩy vào Supabase.
- [x] **Data Preparation (Sample Exams)**: Đã parse tự động 4 bộ đề (A/B/C/D) từ PDF bằng script `backend/scripts/parse_sample_exams.py`. Output: `backend/test_data.json` với 160 main questions (ground truth) + 26 additional, đầy đủ `correct_answer`, `rationale_per_option`, `learning_objective`, `category`.
- [ ] **Evaluation Pipeline**: Cập nhật lại script `backend/evaluate.py` để lấy dữ liệu từ file `test_data.json` mới, tự động chấm 160 câu trắc nghiệm trên Chatbot và xuất report tổng quan về độ chính xác.
