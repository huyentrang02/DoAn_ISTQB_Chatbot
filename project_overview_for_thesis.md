# Phân tích Chi tiết Hệ thống ISTQB RAG Tester
Tài liệu này tổng hợp toàn bộ cấu trúc, kiến trúc kỹ thuật và luồng hoạt động của dự án "ISTQB RAG Tester", phục vụ làm tư liệu cho Đề án Thạc sĩ.

---

## 1. Tổng quan Dự án (Project Overview)
**ISTQB RAG Tester** là một hệ thống Chatbot ứng dụng trí tuệ nhân tạo (AI) giúp tra cứu, học tập và ôn thi chứng chỉ kiểm thử phần mềm ISTQB. Hệ thống sử dụng kiến trúc **RAG (Retrieval-Augmented Generation)** tiên tiến, kết hợp giữa khả năng tìm kiếm ngữ nghĩa độc quyền và mô hình sinh ngữ cảnh lớn (LLM).

### Mục tiêu cốt lõi:
- Xử lý các tài liệu chuyên ngành về Kiểm thử phần mềm (ISTQB Syllabus, Sample Exams).
- Tự động trích xuất, phân mảnh (chunking) thông minh để giữ nguyên cấu trúc ngữ nghĩa ngữ cảnh.
- Cung cấp giao diện trò chuyện cho phép người dùng hỏi đáp và làm bài tập trắc nghiệm với độ chuẩn xác cao, trích dẫn rõ nguồn gốc thông tin.

---

## 2. Công nghệ Sử dụng (Tech Stack)

### 2.1. Backend (Logic & AI)
- **Framework**: Python FastAPI (cho REST API).
- **RAG Framework**: LangChain (orchestration, prompting, chaining).
- **Mô hình Ngôn ngữ Lớn (LLM)**: Google Gemini (`gemini-2.5-flash`).
- **Mô hình Embedding**: Google Text Embedding (`models/gemini-embedding-001` - Output: 768 dimensions).
- **Mô hình Re-ranking**: Cross-Encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`) chạy cục bộ.
- **Data Ingestion**: LlamaParse Cloud API (chuyển PDF sang Markdown), PDFPlumber.

### 2.2. Frontend (Giao diện)
- **Framework**: Next.js 15 (React.js) với App Router.
- **Ngôn ngữ**: TypeScript.
- **Styling**: Tailwind CSS kết hợp thư viện Shadcn/UI.
- **Quản lý State & Fetching**: React Hooks, fetch API (streaming response).

### 2.3. Cơ sở Dữ liệu & Storage (Supabase - PostgreSQL)
- **Vector Database**: `pgvector` giúp lưu trữ và tìm kiếm vector (Cosine Similarity distance).
- **Authentication**: Supabase Auth (Quản lý User/Admin Roles).
- **Bảng Dữ liệu Chính**:
  - `documents`: Lưu trữ Text Chunks, Metadata (Source, Chapter) và Embeddings.
  - `chat_history`: Lưu trữ lịch sử hỏi đáp của từng người dùng với Row Level Security (RLS) để đảm bảo quyền riêng tư.
  
---

## 3. Cấu trúc Thư mục (Directory Structure)

### 3.1. Backend
```text
backend/
├── app/
│   ├── api/                 # Các router API (upload tài liệu, chat streaming)
│   ├── core/                # File cấu hình biến môi trường (config.py)
│   ├── services/            # Logic chính
│   │   └── rag_service.py   # Lõi xử lý RAG (Ingestion, Retrieval, Generator, Reranking, Streaming)
│   └── main.py              # File khởi chạy FastAPI server
├── materials/               # Thư mục chứa tài liệu PDF gốc (Syllabus, Exam)
├── scripts/                 # Kịch bản tự động hóa (Data pipeline)
│   ├── evaluate_rag.py      # Script test RAG tự động dựa trên ground_truth
│   ├── ingest_markdown.py   # Cắt tài liệu MD và nhét DB offline
│   └── parse_sample_exams.py# Tự động parse đề thi và tạo JSON test data
├── test_data.json           # Dữ liệu 186 câu hỏi đánh giá chất lượng hệ thống
├── complete_supabase_schema.sql  # Schema CSDL (hàm search, tables, roles, RLS)
└── requirements.txt         # Thư viện Python
```

### 3.2. Frontend
```text
frontend/
├── app/
│   ├── admin/               # Màn hình cho Admin upload PDF
│   ├── login/               # Màn hình xác thực (Authentication)
│   ├── globals.css          # Định dạng CSS tổng thể
│   ├── layout.tsx           # Layout cha của Next.js
│   └── page.tsx             # Màn hình chính (Chatbot)
├── components/              # Các UI Component độc lập 
│   ├── AdminUpload.tsx      # Logic kéo thả file và gọi API Ingestion
│   ├── ChatInterface.tsx    # Giao diện Chatbot, xử lý Streaming text
│   └── Sidebar.tsx          # Thanh điều hướng và lịch sử chat
├── lib/                     # Service logic ở phía Client
│   ├── auth.ts              # Xử lý login, fetch role
│   ├── chatHistory.ts       # Xử lý lưu và tải lịch sử tin nhắn
│   └── supabaseClient.ts    # Khởi tạo Supabase kết nối
└── tailwind.config.ts / next.config.ts # Các tập tin cấu hình hệ thống build
```

---

## 4. Phân tích Các Tính năng Kỹ thuật Chuyên sâu (Core Features)

Hệ thống sở hữu một pipeline RAG được tối ưu hóa cực kỳ chuyên sâu, chia làm 3 giai đoạn chính: **Data Ingestion**, **Retrieval (Tra cứu)**, và **Generation (Sinh văn bản)**.

### 4.1. Giai đoạn Ingestion (Tiền xử lý & Nhúng dữ liệu)
- **Chuyển đổi Định dạng**: Dùng `LlamaParse` để chuyển đổi file PDF phức tạp chứa bảng biểu, hình ảnh sang dạng Markdown nguyên sơ, hạn chế mất mát format.
- **Semantic Chunking (Phân mảnh theo ngữ nghĩa)**: Khác với việc cắt chữ số lượng cố định, hệ thống phân tách văn bản bằng `MarkdownHeaderTextSplitter` dựa trên thẻ heading (H1, H2, H3...). Điều này giúp mỗi chunk mang theo **Metadata cực mạnh** về chương (`chapter`), mục (`section`).
- **Atomic Swap Storage**: Khi nạp lại tài liệu, thay vì ghi đè thô bạo, hệ thống xử lý ghi tuần tự theo các batch song song (tránh Rate Limit API), và dọn dẹp các data rác cũ ngay khi thành công, hạn chế downtime.

### 4.2. Giai đoạn Tối ưu hóa Tra cứu (Advanced Retrieval Pipeline)
Giai đoạn này là cốt lõi làm nên sức mạnh và độ chuẩn xác của hệ thống RAG này. Bao gồm 5 bước tích hợp:
1. **Query Rewriting**: Trước khi tìm kiếm, thông qua mô hình LLM với (Temperature = 0.0), câu hỏi của user sẽ dựa trên hội thoại cũ, dịch chuyển thành câu hỏi độc lập (Standalone question) nhằm tìm kiếm đúng ngữ nghĩa trong CSDL.
2. **Hybrid Search**: Hệ thống không chỉ tìm theo Vector (Semantic - ý nghĩa) mà còn sử dụng phương pháp **Tsvector BM25 Full-text search** do PostgreSQL cung cấp. Điều này giúp các từ khóa cực khó mang tính chuyên môn ISTQB không bị trôi đi.
3. **Reciprocal Rank Fusion (RRF)**: Hợp nhất (Merge) kết quả xếp hạng từ 2 thuật toán Vector và BM25 theo công thức toán học phân bổ đều trọng số, tạo List kết quả tổng quan nhất.
4. **Re-ranking (Xếp hạng lại)**: Các kết quả Top K (15 chunks) tiếp tục qua một cấu trúc Re-ranking Cross-Encoder độc lập để chấm điểm lại gắt gao độ liên quan tương khớp giữa câu hỏi và văn bản phục vụ RAG. Bộ lọc hạn chế lấy dư thừa và lọc xuống chỉ lấy 4 chunk hoàn hảo nhất.
5. **Context Expansion (Parent-Child)**: Dựa trên Metadata được chắt lọc về mục và chương của các chunk top đầu, hệ thống thực hiện query ngược lại CSDL Supabase để gom tất cả các chunk có liên quan tới nội dung đang cần nhằm tạo "trọn vẹn một khung ngữ cảnh thực tế". Điều này tránh việc LLM đọc một mảnh nội dung cụt lủn và phát sinh trả lời ngụy biện (Hallucination).

### 4.3. Giai đoạn Sinh văn bản & Tương tác (Generation)
- **Query Router**: Có một LLM nhẹ phân loại ngay tin nhắn người dùng. Nếu là câu chào thả thính ("Chào em"), nó định tuyến lập tức thành CHITCHAT bypass qua hệ thống RAG nặng nề, giảm độ trễ vòng lặp và tối đa hóa UX.
- **Prompt Engineering Khắt khe**: Cấu hình Role quy định mô hình bắt buộc phải giữ lại Thuật Ngữ Tiếng Anh chuẩn, quy định cách giải thích trắc nghiệm là luôn kết luận Đáp án trước, Giải thích trực diện ngắn gọn ở sau.
- **Trích Xuất Nguồn Tự Động**: Ở cuối luồng, hệ thống tự động dò mã mục (VD: 1.2.1) do LLM trả về để rà soát đối chiếu xuống Metadata gốc của chunks, hiển thị thành danh mục Markdown "Nguồn tham khảo". Điều này tăng tính minh bạch cho tài liệu học thuật.

### 4.4. Hệ thống Tự Đánh Giá (Automated Evaluation)
- Hệ thống hỗ trợ script python `evaluate_rag.py` chuyên dụng. Scripts sử dụng hàng nghìn bộ câu hỏi trắc nghiệm nội dung chuẩn (Ground Truth) chắt lọc từ `test_data.json` lấy từ file đề thi để test RAG tự động. 
- Nó trực tiếp giả lập yêu cầu của học user vào chatbot và ghi nhận đáp án tự động, thống kê độ trễ, báo cáo điểm độ chuẩn xác soán lấy kết quả chất lượng của hệ thống theo từng cấu hình thiết lập RAG.

---

## 5. Kiến trúc Cơ sở Dữ liệu & Bảo mật

File cấu trúc `complete_supabase_schema.sql` sử dụng PostgreSQL thực hiện nhiều chức năng vượt ra ngoài lưu trữ CRUD cơ bản:
- **`pgvector` Extension**: Kích hoạt lưu trữ Embedding `vector(768)`. Tạo cấu trúc Index theo mô hình Hierarchical Navigable Small World (`HNSW`) tối ưu hoá việc so sánh Vector Scale-up lên tận hàng triệu bản ghi trong phần mili-giây thời gian truy xuất thực thời.
- **Row Level Security (RLS)**: Bảng `chat_history` được cài đặt policy chặt chẽ qua biến `auth.uid() = user_id`, ngăn chặn triệt để lỗ hổng một người dùng gọi API trái phép lấy token của bạn thân đọc lịch sử hỏi đáp.
- **Role-based Handling**: Thiết lập Trigger Auth tự động cấp vai trò 'user', kết nối quyền hạ tầng function `update_user_role` cho chức danh `admin`. Ngăn cách Dashboard uploader với user đại trà.

## Kết luận Cho Đề tài Phân Tích
Việc phân tích hệ thống RAG-Tester ở cấp độ này cung cấp đủ tư liệu thực tiễn để phục vụ cho luận chứng thạc sĩ bao vi gồm:
- **Mặt Công Nghệ Chuyên Sâu**: Không dừng lại ở RAG cơ bản Naive mà tích hợp kĩ thuật RAG Nâng cao đỉnh cao trong các luận văn thế giới (Hybrid Search, Re-Ranking Cross-Encoder, Context Expand).
- **Mặt Sản Phẩm Toàn Diện**: Có Front-end Real Time User, có Database Authentication khắt khe, có Data Automation Ingestion và Evaluation cho thấy một dự án khép kín hoàn hảo Enterprise-ready.
- Bạn có thể khai thác các module này thành Chương mục trong Luận Văn của mình. Đơn cử: Chương 3: Ứng dụng Hybrid Search và Cross-Encoder Nâng cao Khả năng Tra cứu Ngữ cảnh. Chương 4: Kết nối Chat LLM Sinh văn bản chuẩn hoá cấu trúc trắc nghiệm.
