import os
import sys
import nest_asyncio
from dotenv import load_dotenv

# Enable nested asyncio for LlamaParse
nest_asyncio.apply()

# Add backend directory to path
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(base_dir)

load_dotenv(os.path.join(base_dir, ".env"))

api_key = os.getenv("LLAMA_CLOUD_API_KEY")
if not api_key:
    print("ERROR: LLAMA_CLOUD_API_KEY is not set trong file .env.")
    print("Vui lòng lấy key tại https://cloud.llamaindex.ai/api-key và điền vào .env")
    sys.exit(1)

try:
    from llama_parse import LlamaParse
except ImportError as e:
    print(f"Import Error: {e}")
    print("Chạy lệnh: pip install llama-parse")
    sys.exit(1)

pdf_path = os.path.join(base_dir, "materials", "Syllabus", "ISTQB_CTFL_Syllabus_v4.0.1.pdf")
out_path = os.path.join(base_dir, "materials", "Syllabus", "ISTQB_CTFL_Syllabus_v4.0.1.md")

if not os.path.exists(pdf_path):
    print(f"ERROR: Không tìm thấy file gốc tại {pdf_path}")
    sys.exit(1)

print("=" * 60)
print(f"Bắt đầu parse file: {pdf_path.split('/')[-1]}")
print("Sử dụng LlamaParse (Quá trình này được chạy trên Cloud và có thể tốn ~2-3 phút)...")
print("=" * 60)

# Cấu hình LlamaParse đọc theo Markdown
parser = LlamaParse(
    api_key=api_key,
    result_type="markdown",
    verbose=True,
    num_workers=4
)

documents = parser.load_data(pdf_path)

if not documents:
    print("LlamaParse không trả về kết quả nào.")
    sys.exit(1)

# Gộp Text nếu có nhiều Docs trả về
full_markdown = "\n\n".join([doc.text for doc in documents])

with open(out_path, "w", encoding="utf-8") as f:
    f.write(full_markdown)

print(f"\n✅ Đã lưu kết quả thành công vào: {out_path}")
print(f"📊 Độ dài file Markdown: {len(full_markdown)} ký tự")
print(f"📝 Số documents trả về: {len(documents)}")
