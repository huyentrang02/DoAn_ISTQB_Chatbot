# ISTQB RAG Tester

Hệ thống RAG (Retrieval-Augmented Generation) để tra cứu kiến thức ISTQB với chatbot AI.

## Công nghệ

### Backend
- **Python FastAPI**: REST API server
- **LangChain**: RAG framework
- **Google Gemini**: LLM và Embedding model
- **Supabase**: PostgreSQL + pgvector cho Vector Database

### Frontend
- **Next.js 15**: React framework với App Router
- **TypeScript**: Type-safe
- **Tailwind CSS + Shadcn/ui**: UI components
- **Supabase Auth**: Authentication

## Cài đặt

### 1. Backend Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Tạo file `backend/.env`:**
```env
GOOGLE_API_KEY=your_google_ai_studio_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_service_role_key
```

**Chạy SQL schema trong Supabase:**
- Mở file `backend/supabase_schema.sql`
- Copy nội dung và chạy trong Supabase SQL Editor

**Khởi động server:**
```bash
uvicorn app.main:app --reload
```
Backend chạy tại: http://localhost:8000

### 2. Frontend Setup

```bash
cd frontend
npm install
```

**Tạo file `frontend/.env.local`:**
```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Khởi động dev server:**
```bash
npm run dev
```
Frontend chạy tại: http://localhost:3000

## Lấy API Keys

### Google AI Studio API Key
1. Truy cập: https://aistudio.google.com/app/apikey
2. Tạo API Key mới
3. Copy và paste vào `GOOGLE_API_KEY`

### Supabase Keys
1. Truy cập Supabase Dashboard: https://supabase.com/dashboard
2. Chọn project → Settings → API
3. Copy:
   - **Project URL** → `SUPABASE_URL`
   - **anon public key** → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - **service_role secret** → `SUPABASE_KEY`

## Tính năng

### Admin (Upload Documents)
- Upload file PDF (tài liệu ISTQB)
- Tự động chunking và embedding
- Lưu vào Vector Database
- Deduplication (tránh trùng lặp)

### Client (Chatbot)
- Hỏi đáp về kiến thức ISTQB
- Trả lời dựa trên RAG (Retrieval-Augmented Generation)
- Hiển thị Markdown formatting
- Lưu lịch sử chat (LocalStorage)

## Kiến trúc RAG

```
Upload: PDF → Clean → Chunk → Embed (Gemini) → Store (Supabase)
Query:  User Question → Embed → Vector Search → Context + LLM → Answer
```

## Lưu ý

- Model sử dụng: `gemini-2.0-flash` (chat), `text-embedding-004` (embedding)
- Gói Free của Google có giới hạn quota, nếu hết hạn mức cần đợi reset hoặc nâng cấp
- Supabase Free tier: 500MB database, đủ cho demo

## License

MIT

