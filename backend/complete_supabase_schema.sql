-- ============================================================================
-- ISTQB CHATBOT - COMPLETE DATABASE SCHEMA
-- ============================================================================
-- File này chứa toàn bộ schema cho hệ thống ISTQB Chatbot
-- Bao gồm: Documents (RAG), User Roles, Chat History
-- 
-- CÁCH SỬ DỤNG:
-- 1. Mở Supabase SQL Editor
-- 2. Copy toàn bộ nội dung file này
-- 3. Paste vào editor và chạy
-- 4. Sau đó chạy phần SETUP ADMIN ở cuối file (thay email của bạn)
--
-- LƯU Ý: File này sẽ XÓA và TẠO LẠI các bảng nếu đã tồn tại
-- ============================================================================


-- ============================================================================
-- PHẦN 1: EXTENSIONS
-- ============================================================================
-- Mục đích: Enable các extension cần thiết cho hệ thống
-- - pgvector: Để lưu trữ và tìm kiếm vector embeddings (dùng cho RAG)
-- ============================================================================

-- Enable pgvector extension để làm việc với embedding vectors
-- Extension này cho phép lưu và tìm kiếm vectors (dùng cho semantic search)
create extension if not exists vector;


-- ============================================================================
-- PHẦN 2: DOCUMENTS TABLE & RAG SYSTEM
-- ============================================================================
-- Mục đích: Lưu trữ tài liệu ISTQB và embeddings để thực hiện RAG
-- - documents: Bảng chính lưu nội dung và embeddings
-- - match_documents_v2: Function tìm kiếm tài liệu tương tự dựa trên vector
-- ============================================================================

-- XÓA bảng cũ nếu tồn tại (CASCADE sẽ xóa cả các objects phụ thuộc)
-- LƯU Ý: Cẩn thận với production data!
drop table if exists documents cascade;

-- Tạo function tìm kiếm documents dựa trên vector similarity
-- Function này so sánh query_embedding với embeddings trong DB
-- Trả về các documents có độ tương đồng > match_threshold
-- Operator <=> là cosine distance trong pgvector
create or replace function match_documents_v2 (
  query_embedding vector(768),    -- Vector của câu hỏi (768 dimensions)
  match_threshold float,          -- Ngưỡng similarity tối thiểu (0.0 - 1.0)
  match_count int                 -- Số lượng kết quả trả về
) returns table (
  id uuid,                        -- ID của document
  content text,                   -- Nội dung text
  metadata jsonb,                 -- Metadata (page, source, etc.)
  similarity float                -- Độ tương đồng (càng cao càng giống)
) language plpgsql stable as $$
begin
  return query
  select
    documents.id,
    documents.content,
    documents.metadata,
    -- Chuyển cosine distance thành similarity score (1 - distance)
    1 - (documents.embedding <=> query_embedding) as similarity
  from documents
  where 1 - (documents.embedding <=> query_embedding) > match_threshold
  order by similarity desc        -- Sắp xếp theo độ tương đồng giảm dần
  limit match_count;              -- Giới hạn số kết quả
end;
$$;

-- Tạo bảng documents để lưu tài liệu và embeddings
-- Mỗi document là một chunk text từ file ISTQB
create table documents (
  id uuid primary key default gen_random_uuid(),  -- ID tự động
  content text,                                   -- Nội dung text của chunk
  metadata jsonb,                                 -- Thông tin bổ sung (file, page, etc.)
  embedding vector(768)                           -- Vector embedding 768 chiều
);

-- Tạo index cho vector column để tăng tốc tìm kiếm
-- HNSW (Hierarchical Navigable Small World) là thuật toán tìm kiếm vector nhanh
create index if not exists documents_embedding_idx 
  on documents using hnsw (embedding vector_cosine_ops);


-- ============================================================================
-- PHẦN 3: USER ROLES & AUTHENTICATION
-- ============================================================================
-- Mục đích: Quản lý role (admin/user) trong auth.users metadata
-- - Không tạo bảng riêng, lưu role trực tiếp trong auth.users
-- - Trigger tự động set role='user' khi đăng ký mới
-- - Functions để get/update role
-- ============================================================================

-- XÓA bảng public.users cũ nếu đã từng tạo (hệ thống cũ)
-- Hệ thống mới không dùng bảng này nữa, lưu role trong auth.users
drop table if exists public.users cascade;

-- Function xử lý khi có user mới đăng ký
-- Tự động thêm role='user' vào metadata
create or replace function public.handle_new_user()
returns trigger as $$
begin
  -- Thêm field 'role': 'user' vào raw_user_meta_data
  -- coalesce đảm bảo không bị null
  -- || là operator merge JSONB trong PostgreSQL
  new.raw_user_meta_data = 
    coalesce(new.raw_user_meta_data, '{}'::jsonb) || 
    jsonb_build_object('role', 'user');
  return new;
end;
$$ language plpgsql security definer;

-- Xóa trigger cũ nếu có (để tránh duplicate)
drop trigger if exists on_auth_user_created on auth.users;

-- Tạo trigger chạy BEFORE INSERT vào auth.users
-- Trigger này sẽ tự động chạy mỗi khi có user đăng ký
create trigger on_auth_user_created
  before insert on auth.users
  for each row execute procedure public.handle_new_user();

-- Function lấy role của user hiện tại
-- auth.uid() trả về ID của user đang login
create or replace function public.get_user_role()
returns text as $$
declare
  user_role text;
begin
  -- Lấy role từ metadata
  select raw_user_meta_data->>'role'
  into user_role
  from auth.users
  where id = auth.uid();
  
  -- Trả về 'user' nếu không tìm thấy
  return coalesce(user_role, 'user');
end;
$$ language plpgsql security definer;

-- Function để admin update role của user khác
-- Chỉ admin mới có quyền gọi function này
create or replace function public.update_user_role(user_id uuid, new_role text)
returns void as $$
declare
  current_user_role text;
begin
  -- Kiểm tra user hiện tại có phải admin không
  select raw_user_meta_data->>'role'
  into current_user_role
  from auth.users
  where id = auth.uid();
  
  -- Raise exception nếu không phải admin
  if current_user_role != 'admin' then
    raise exception 'Only admins can update user roles';
  end if;
  
  -- Update role trong metadata
  update auth.users
  set raw_user_meta_data = 
    coalesce(raw_user_meta_data, '{}'::jsonb) || 
    jsonb_build_object('role', new_role)
  where id = user_id;
end;
$$ language plpgsql security definer;


-- ============================================================================
-- PHẦN 4: CHAT HISTORY SYSTEM
-- ============================================================================
-- Mục đích: Lưu lịch sử chat của từng user vào database
-- - chat_history: Bảng lưu messages (user & assistant)
-- - RLS policies: Đảm bảo user chỉ thấy chat của mình
-- - Functions: get_chat_history(), clear_chat_history()
-- ============================================================================

-- Tạo bảng chat_history
-- Mỗi row là 1 message (user hoặc assistant)
create table if not exists public.chat_history (
  id uuid primary key default gen_random_uuid(),                      -- ID message
  user_id uuid references auth.users(id) on delete cascade not null,  -- User sở hữu
  role text not null check (role in ('user', 'assistant')),           -- Người gửi
  content text not null,                                              -- Nội dung
  message_timestamp bigint not null,                                  -- Timestamp (milliseconds)
  created_at timestamp with time zone default timezone('utc'::text, now()) not null  -- Thời gian tạo
);

-- Tạo indexes để tăng tốc query
-- Index 1: Tìm theo user_id (dùng cho WHERE user_id = ...)
create index if not exists idx_chat_history_user_id 
  on public.chat_history(user_id);

-- Index 2: Tìm và sắp xếp theo timestamp (dùng cho ORDER BY)
-- Composite index (user_id, message_timestamp) tối ưu cho cả WHERE và ORDER BY
create index if not exists idx_chat_history_timestamp 
  on public.chat_history(user_id, message_timestamp desc);

-- Enable Row Level Security (RLS)
-- Khi enable, mặc định sẽ DENY tất cả access
-- Phải tạo policies để cho phép access
alter table public.chat_history enable row level security;

-- Policy 1: User chỉ SELECT được messages của mình
-- using clause kiểm tra điều kiện
create policy "Users can view their own chat history"
  on public.chat_history
  for select
  using (auth.uid() = user_id);

-- Policy 2: User chỉ INSERT được messages với user_id của mình
-- with check clause kiểm tra khi insert
create policy "Users can insert their own chat history"
  on public.chat_history
  for insert
  with check (auth.uid() = user_id);

-- Policy 3: User chỉ DELETE được messages của mình
create policy "Users can delete their own chat history"
  on public.chat_history
  for delete
  using (auth.uid() = user_id);

-- Function lấy lịch sử chat của user hiện tại
-- Sắp xếp theo thời gian tăng dần (message cũ → mới)
create or replace function public.get_chat_history(limit_count int default 100)
returns table (
  id uuid,
  role text,
  content text,
  message_timestamp bigint
) language plpgsql security definer as $$
begin
  return query
  select 
    ch.id,
    ch.role,
    ch.content,
    ch.message_timestamp
  from public.chat_history ch
  where ch.user_id = auth.uid()           -- Chỉ lấy của user hiện tại
  order by ch.message_timestamp asc       -- Cũ → mới
  limit limit_count;                      -- Giới hạn số lượng
end;
$$;

-- Function xóa tất cả lịch sử chat của user hiện tại
-- Dùng cho nút "Clear History"
create or replace function public.clear_chat_history()
returns void language plpgsql security definer as $$
begin
  delete from public.chat_history
  where user_id = auth.uid();
end;
$$;


-- ============================================================================
-- PHẦN 5: PERMISSIONS & GRANTS
-- ============================================================================
-- Mục đích: Cấp quyền truy cập cho các roles
-- - authenticated: Users đã login
-- - anon: Users chưa login (nếu cần)
-- - service_role: Backend services
-- ============================================================================

-- Grant quyền sử dụng schema public
grant usage on schema public to postgres, anon, authenticated, service_role;

-- Grant quyền trên tables
grant all privileges on all tables in schema public to postgres, anon, authenticated, service_role;

-- Grant quyền trên sequences (dùng cho auto-increment)
grant all privileges on all sequences in schema public to postgres, anon, authenticated, service_role;

-- Grant quyền execute functions cho authenticated users
grant execute on function public.get_user_role() to authenticated;
grant execute on function public.update_user_role(uuid, text) to authenticated;
grant execute on function public.get_chat_history(int) to authenticated;
grant execute on function public.clear_chat_history() to authenticated;
grant execute on function match_documents_v2(vector(768), float, int) to authenticated, anon;

-- Grant permissions riêng cho chat_history table
grant select, insert, delete on public.chat_history to authenticated;

-- Grant permissions cho documents table
grant select, insert, update, delete on public.documents to authenticated, service_role;


-- ============================================================================
-- PHẦN 6: VERIFICATION & SUCCESS MESSAGE
-- ============================================================================

-- Hiển thị thông báo thành công
select 'Database schema created successfully!' as status;

-- Verification queries (uncomment để test)
-- select 'Extensions:' as check_type, extname from pg_extension where extname = 'vector';
-- select 'Tables:' as check_type, tablename from pg_tables where schemaname = 'public';
-- select 'Functions:' as check_type, proname from pg_proc where pronamespace = 'public'::regnamespace;


-- ============================================================================
-- PHẦN 7: SETUP ADMIN USER (CHẠY SAU KHI ĐĂNG KÝ USER)
-- ============================================================================
-- LƯU Ý: Phần này chạy RIÊNG, SAU KHI đã tạo account trong ứng dụng
-- 
-- CÁCH SỬ DỤNG:
-- 1. Đăng ký/đăng nhập account trong ứng dụng web
-- 2. Copy đoạn code dưới đây
-- 3. THAY 'your-admin-email@example.com' BẰNG EMAIL CỦA BẠN
-- 4. Chạy trong Supabase SQL Editor
-- 5. Logout và login lại để refresh session
-- ============================================================================

/*
-- UNCOMMENT VÀ CHỈNH SỬA EMAIL BÊN DƯỚI

-- Cập nhật role thành admin
update auth.users 
set raw_user_meta_data = 
  coalesce(raw_user_meta_data, '{}'::jsonb) || 
  jsonb_build_object('role', 'admin')
where email = 'your-admin-email@example.com';

-- Kiểm tra kết quả
select 
  id, 
  email, 
  raw_user_meta_data->>'role' as role,
  created_at 
from auth.users 
where email = 'your-admin-email@example.com';

-- Xem tất cả admin users
select 
  id, 
  email, 
  raw_user_meta_data->>'role' as role,
  created_at 
from auth.users 
where raw_user_meta_data->>'role' = 'admin';
*/


-- ============================================================================
-- PHẦN 8: USEFUL QUERIES (UNCOMMENT KHI CẦN)
-- ============================================================================
-- Các query hữu ích để debug và quản lý

/*
-- Xem tất cả users và roles
select 
  id, 
  email, 
  raw_user_meta_data->>'role' as role,
  created_at
from auth.users
order by created_at desc;

-- Xem lịch sử chat của tất cả users (admin only)
select 
  ch.id,
  u.email,
  ch.role,
  ch.content,
  to_timestamp(ch.message_timestamp / 1000) as sent_at
from chat_history ch
join auth.users u on u.id = ch.user_id
order by ch.message_timestamp desc
limit 50;

-- Thống kê số messages của từng user
select 
  u.email,
  count(*) as message_count
from chat_history ch
join auth.users u on u.id = ch.user_id
group by u.email
order by message_count desc;

-- Xem documents đã upload
select 
  id,
  left(content, 100) as preview,
  metadata->>'page' as page,
  metadata->>'source' as source
from documents
limit 10;

-- Đếm số documents
select count(*) as total_documents from documents;

-- Kiểm tra RLS policies
select 
  schemaname,
  tablename,
  policyname,
  cmd,
  qual
from pg_policies
where tablename in ('chat_history')
order by tablename, policyname;

-- Xóa tất cả documents (cẩn thận!)
-- truncate table documents;

-- Xóa tất cả chat history (cẩn thận!)
-- truncate table chat_history;

-- Reset role của user về 'user'
-- update auth.users 
-- set raw_user_meta_data = 
--   coalesce(raw_user_meta_data, '{}'::jsonb) || 
--   jsonb_build_object('role', 'user')
-- where email = 'user-email@example.com';
*/


-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
-- 
-- NEXT STEPS:
-- 1. ✅ Schema đã được tạo
-- 2. ⏭️  Đăng ký user trong ứng dụng
-- 3. ⏭️  Chạy phần SETUP ADMIN để cấp quyền
-- 4. ⏭️  Upload documents ISTQB qua trang /admin
-- 5. ⏭️  Bắt đầu sử dụng chatbot!
-- 
-- DOCUMENTATION:
-- - User Roles: backend/MIGRATION_GUIDE.md
-- - Chat History: Tự động lưu vào DB
-- - Documents: Upload qua AdminUpload component
--
-- SUPPORT:
-- - Check browser DevTools Console nếu có lỗi
-- - Verify RLS policies nếu không access được data
-- - Kiểm tra auth.uid() có trả về đúng user không
-- ============================================================================

