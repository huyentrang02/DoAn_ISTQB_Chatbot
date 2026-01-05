# Backend - ISTQB Chatbot

## 📁 Cấu Trúc Thư Mục

```
backend/
├── app/                              # FastAPI application
│   ├── api/endpoints/               # API endpoints
│   ├── core/                        # Config & settings
│   └── services/                    # Business logic
│
├── complete_supabase_schema.sql     # ⭐ MASTER SQL FILE
├── DATABASE_SETUP.md                # 📖 Hướng dẫn setup database
├── SQL_FILES_README.md              # 📋 Overview SQL files
│
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment variables template
└── README.md                        # File này
```

## 🚀 Quick Start

### 1. Setup Database

```bash
# Chỉ cần 1 file duy nhất:
1. Mở Supabase SQL Editor
2. Copy file: complete_supabase_schema.sql
3. Paste và Run
4. Setup admin (xem hướng dẫn trong file SQL)
```

📖 **Chi tiết**: Xem `DATABASE_SETUP.md`

### 2. Setup Backend Server

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env với credentials của bạn:
# - GOOGLE_API_KEY
# - SUPABASE_URL
# - SUPABASE_KEY

# Run server
uvicorn app.main:app --reload

# Server chạy tại: http://localhost:8000
```

### 3. Test API

```bash
# Health check
curl http://localhost:8000

# Chat endpoint
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What is ISTQB?"}'

# Upload endpoint (multipart/form-data)
# Dùng qua frontend /admin page
```

## 📊 Database Schema

### Tables

| Table | Purpose |
|-------|---------|
| `documents` | Lưu tài liệu ISTQB và embeddings (RAG) |
| `chat_history` | Lưu lịch sử chat theo user |

### Auth

- User roles lưu trong `auth.users.raw_user_meta_data`
- Không có bảng users riêng
- RLS policies bảo vệ data

### Functions

| Function | Purpose |
|----------|---------|
| `match_documents_v2()` | Tìm kiếm documents bằng vector similarity |
| `get_user_role()` | Lấy role của user hiện tại |
| `update_user_role()` | Admin update role (admin only) |
| `get_chat_history()` | Lấy lịch sử chat của user |
| `clear_chat_history()` | Xóa lịch sử chat của user |

## 📁 Files Quan Trọng

### SQL Files

| File | Mục đích | Khi nào cần |
|------|----------|-------------|
| **`complete_supabase_schema.sql`** | **Master schema - Toàn bộ database** | **Setup lần đầu** |
| `DATABASE_SETUP.md` | Hướng dẫn setup chi tiết | Đọc khi setup |
| `SQL_FILES_README.md` | Overview SQL files | Quick reference |

### Python Files

| File | Mục đích |
|------|----------|
| `app/main.py` | FastAPI entry point |
| `app/core/config.py` | Configuration & env vars |
| `app/services/rag_service.py` | RAG logic (embedding + search) |
| `app/api/endpoints/chat.py` | Chat endpoint |
| `app/api/endpoints/upload.py` | Upload documents endpoint |
| `evaluate.py` | Evaluation script |
| `requirements.txt` | Dependencies |

## 🔑 Environment Variables

Tạo file `.env` trong thư mục backend:

```env
# Google AI (để tạo embeddings và chat)
GOOGLE_API_KEY=your_google_api_key_here

# Supabase (database)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key_here
```

## 🛠️ Development

### Run Server

```bash
# Development mode (auto-reload)
uvicorn app.main:app --reload --port 8000

# Production mode
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Test Evaluation

```bash
# Đánh giá độ chính xác của chatbot
python evaluate.py

# Kết quả lưu vào: evaluation_results.json
```

### Upload Documents

Có 2 cách:

**Option 1: Qua Web UI (Recommended)**
```
1. Login với admin account
2. Vào /admin
3. Upload file PDF
4. Hệ thống tự động chunk và embedding
```

**Option 2: Script Python (Manual)**
```python
# Tạo script riêng nếu cần
from app.services.rag_service import RAGService

service = RAGService()
service.process_document("path/to/document.pdf")
```

## 📚 API Endpoints

### GET /
Health check endpoint
```bash
curl http://localhost:8000
# Response: {"message": "Welcome to ISTQB RAG System API"}
```

### POST /api/chat
Chat với bot
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What is ISTQB?"}'

# Response: {"answer": "ISTQB is..."}
```

### POST /api/upload
Upload document (admin only)
```bash
# Dùng multipart/form-data
# Frontend tự động gọi khi upload file
```

## 🔒 Security

### Database
- ✅ RLS (Row Level Security) enabled
- ✅ User chỉ access data của mình
- ✅ Admin functions có permission check

### API
- ⚠️ CORS: Hiện tại allow all (development)
- 🔧 TODO: Restrict origins cho production
- 🔧 TODO: Add rate limiting

### Authentication
- Frontend handle auth (Supabase Auth)
- Backend chỉ validate token nếu cần
- RLS tự động kiểm tra `auth.uid()`

## 🐛 Troubleshooting

### Lỗi: "Extension vector does not exist"
```sql
-- Chạy trong Supabase SQL Editor:
create extension if not exists vector;
```

### Lỗi: "Missing environment variables"
```bash
# Check file .env tồn tại
# Check các biến đã điền đủ
cat .env
```

### Lỗi: "Connection refused" khi gọi API
```bash
# Check backend server đang chạy
# Check port 8000 không bị chiếm
lsof -i :8000  # Mac/Linux
netstat -ano | findstr :8000  # Windows
```

### Lỗi: "No documents found"
```bash
# Check đã upload documents chưa
# Login vào Supabase → Table Editor → documents
# Hoặc query:
# select count(*) from documents;
```

## 📖 Documentation

Xem thêm:
- **Database Setup**: `DATABASE_SETUP.md` - Chi tiết setup database
- **SQL Overview**: `SQL_FILES_README.md` - Tổng quan các files SQL
- **Frontend**: `../frontend/README.md` - Frontend documentation

## 🎯 Workflow

```
1. User gửi câu hỏi
   ↓
2. Frontend gọi POST /api/chat
   ↓
3. Backend:
   - Tạo embedding từ question
   - Search documents bằng match_documents_v2()
   - Lấy top K documents có similarity cao
   - Gửi context + question cho Google AI
   - Trả về answer
   ↓
4. Frontend hiển thị answer
   ↓
5. Frontend lưu vào chat_history table
```

## 📊 Database Diagram

```
┌─────────────────────────────────────────────┐
│           auth.users (Supabase)             │
│  ┌─────────────────────────────────────┐   │
│  │ raw_user_meta_data: {"role": "..."}│   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
         ↓ user_id                    ↑ auth.uid()
┌──────────────────────┐      ┌─────────────────────┐
│   chat_history       │      │     documents       │
│  ├─ user_id (FK)     │      │  ├─ id              │
│  ├─ role             │      │  ├─ content         │
│  ├─ content          │      │  ├─ metadata        │
│  └─ message_timestamp│      │  └─ embedding       │
└──────────────────────┘      └─────────────────────┘
   RLS: user only              No RLS: all can read
```

## 🚀 Next Steps

Sau khi setup backend:

1. ✅ Verify database schema đã chạy
2. ✅ Backend server chạy thành công
3. ✅ Upload documents qua admin page
4. ✅ Test chat với câu hỏi mẫu
5. ✅ Check chat history được lưu vào DB

---

**Version**: 1.0  
**Last Updated**: Jan 2026  
**Status**: ✅ Production Ready

