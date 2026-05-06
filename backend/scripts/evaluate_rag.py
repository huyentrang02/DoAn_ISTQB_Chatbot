import sys
import os
import json
import asyncio
import re
from datetime import datetime

# Add the backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.rag_service import rag_service

async def run_evaluation(input_file, limit=10, exam_filter=None):
    """
    Chạy đánh giá độ chính xác của RAG dựa trên file input_file (json)
    """
    if not os.path.exists(input_file):
        print(f"❌ Không tìm thấy file: {input_file}")
        return

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    test_cases = data.get("test_cases", [])
    
    if exam_filter:
        test_cases = [tc for tc in test_cases if tc["exam"] == exam_filter]
        
    test_cases = test_cases[:limit]
    
    results = []
    correct_count = 0
    
    print(f"🚀 Bắt đầu đánh giá {len(test_cases)} câu hỏi từ {os.path.basename(input_file)}...")
    print("-" * 50)

    for i, tc in enumerate(test_cases):
        question_id = tc["id"]
        question_text = tc["question"]
        options = tc["options"]
        ground_truth = tc["correct_answer"]
        expected_lo = tc.get("learning_objective", "N/A")
        
        options_text = "\n".join([f"{k}: {v}" for k, v in options.items()])
        # Tối ưu prompt: Chỉ lấy đáp án để tăng tốc
        full_query = f"{question_text}\n\nOptions:\n{options_text}\n\nLƯU Ý QUAN TRỌNG: CHỈ TRẢ VỀ CHỮ CÁI ĐÁP ÁN ĐÚNG (A, B, C hoặc D). KHÔNG GIẢI THÍCH."
        
        print(f"[{i+1}/{len(test_cases)}] Đang kiểm tra câu {question_id}...", end="\r")
        
        ai_response = ""
        error_msg = None
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                async for chunk in rag_service.chat_stream(full_query, history=[], skip_routing=True, skip_rewrite=True):
                    if chunk:
                        ai_response += chunk
                break
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                break
        
        # Trích xuất đáp án
        ai_picked = "N/A"
        is_correct = False
        
        if ai_response:
            match = re.search(r'\b([A-D])\b', ai_response[:20], re.IGNORECASE)
            ai_picked = match.group(1).upper() if match else "N/A"
            is_correct = ai_picked in ground_truth
        elif error_msg:
            ai_picked = "ERROR"

        # Trích xuất nguồn chatbot (các mã số chương như 1.1.1)
        chatbot_sources = []
        if ai_response:
            # Tìm các chuỗi số dạng 1.1 hoặc 1.1.1 trong phần Nguồn tham khảo
            source_section = ai_response.split("Nguồn tham khảo:")[-1] if "Nguồn tham khảo:" in ai_response else ""
            chatbot_sources = re.findall(r'(\d+(?:\.\d+)+)', source_section)
        
        chatbot_source_str = ", ".join(set(chatbot_sources)) if chatbot_sources else "None"
        
        # Kiểm tra xem mã LO có nằm trong chatbot_sources không
        lo_num = expected_lo.replace("FL-", "")
        has_correct_source = any(lo_num in s for s in chatbot_sources)
        
        # Kết quả tổng: Đúng cả đáp án và đúng cả nguồn
        total_success = is_correct and has_correct_source

        if is_correct:
            correct_count += 1
            
        results.append({
            "id": question_id,
            "ground_truth": ground_truth[0],
            "ai_picked": ai_picked,
            "expected_lo": expected_lo,
            "chatbot_source": chatbot_source_str,
            "is_correct": is_correct,
            "has_correct_source": has_correct_source,
            "total_success": total_success,
            "ai_response": ai_response or f"Error: {error_msg}"
        })

    accuracy = (correct_count / len(test_cases)) * 100 if test_cases else 0
    source_accuracy = (sum(1 for r in results if r["has_correct_source"]) / len(test_cases)) * 100 if test_cases else 0
    total_accuracy = (sum(1 for r in results if r["total_success"]) / len(test_cases)) * 100 if test_cases else 0

    # --- HIỂN THỊ BẢNG KẾT QUẢ ---
    print("\n\n" + "="*145)
    print(f"{'ID':<6} | {'Đáp án':<8} | {'AI Chọn':<8} | {'Kết quả':<10} | {'Nguồn Chuẩn':<15} | {'Nguồn Bot':<15} | {'Nguồn Đúng?':<12} | {'Tổng kết'}")
    print("-" * 145)
    for res in results:
        ans_status = "✅ ĐÚNG" if res["is_correct"] else "❌ SAI"
        src_status = "✅ ĐÚNG" if res["has_correct_source"] else "❌ SAI"
        total_status = "🌟 ĐẠT" if res["total_success"] else "⭕ KHÔNG ĐẠT"
        
        if res["ai_picked"] == "ERROR":
            ans_status = "⚠️ LỖI API"
            total_status = "⚠️ LỖI"
            
        print(f"{res['id']:<6} | {res['ground_truth']:<8} | {res['ai_picked']:<8} | {ans_status:<10} | {res['expected_lo']:<15} | {res['chatbot_source']:<15} | {src_status:<12} | {total_status}")
    
    print("="*145)
    print(f"📊 ĐÁP ÁN: {correct_count}/{len(test_cases)} câu đúng ({accuracy:.2f}%)")
    print(f"📊 NGUỒN:  {sum(1 for r in results if r['has_correct_source'])}/{len(test_cases)} nguồn đúng ({source_accuracy:.2f}%)")
    print(f"📊 TỔNG:   {sum(1 for r in results if r['total_success'])}/{len(test_cases)} câu đạt tuyệt đối ({total_accuracy:.2f}%)")

    # --- XUẤT RA FILE MARKDOWN ---
    md_path = os.path.join(os.path.dirname(__file__), "evaluation_results.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Kết quả Đánh giá RAG - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"- **File nguồn:** `{os.path.basename(input_file)}`\n")
        f.write(f"- **Tổng số câu:** {len(test_cases)}\n")
        f.write(f"- **Độ chính xác đáp án:** {accuracy:.2f}%\n")
        f.write(f"- **Độ chính xác nguồn:** {source_accuracy:.2f}%\n")
        f.write(f"- **Độ chính xác tổng hợp:** {total_accuracy:.2f}%\n\n")
        f.write("| ID | Đáp án | AI Chọn | Kết quả Đáp án | Nguồn Chuẩn | Nguồn Bot | Nguồn Đúng? | Kết quả Tổng |\n")
        f.write("|----|--------|---------|----------------|-------------|-----------|-------------|--------------|\n")
        for res in results:
            ans_status = "✅ ĐÚNG" if res["is_correct"] else "❌ SAI"
            src_status = "✅ ĐÚNG" if res["has_correct_source"] else "❌ SAI"
            total_status = "🌟 ĐẠT" if res["total_success"] else "⭕ KHÔNG ĐẠT"
            if res["ai_picked"] == "ERROR":
                ans_status = "⚠️ LỖI API"
                total_status = "⚠️ LỖI"
            f.write(f"| {res['id']} | {res['ground_truth']} | {res['ai_picked']} | {ans_status} | {res['expected_lo']} | {res['chatbot_source']} | {src_status} | {total_status} |\n")

    
    print(f"📝 Báo cáo Markdown: {md_path}")
    
    # Lưu report JSON (giữ nguyên để hậu xử lý nếu cần)
    report_path = os.path.join(os.path.dirname(__file__), "evaluation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "input_file": input_file,
            "summary": {"total": len(test_cases), "correct": correct_count, "accuracy": accuracy},
            "details": results
        }, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default="test_data.json", help="Đường dẫn file test_data.json")
    parser.add_argument("--limit", type=int, default=None, help="Số lượng câu hỏi cần test (mặc định: all)")
    parser.add_argument("--exam", type=str, default=None, help="Mã đề (A, B, C, D) (mặc định: all)")
    args = parser.parse_args()
    
    input_path = args.input
    if not os.path.isabs(input_path):
        if not os.path.exists(input_path):
            input_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", args.input))

    asyncio.run(run_evaluation(input_path, limit=args.limit, exam_filter=args.exam))
