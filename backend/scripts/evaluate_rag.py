import sys
import os
import json
import asyncio
import re
import base64
import time
from datetime import datetime

# Add the backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.rag_service import rag_service

def encode_image(image_path):
    """Mã hóa ảnh sang base64"""
    try:
        if not os.path.isabs(image_path):
            # Giả định path tương đối so với thư mục gốc dự án
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            image_path = os.path.join(root_dir, image_path)
        
        if os.path.exists(image_path):
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        print(f"⚠️ Không thể đọc ảnh {image_path}: {e}")
    return None


async def run_evaluation(input_file, limit=None, exam_filter=None, target_ids=None):
    start_time = time.time()
    """
    Chạy đánh giá độ chính xác của RAG dựa trên file input_file (json)
    """
    if not os.path.exists(input_file):
        print(f"❌ Không tìm thấy file: {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    test_cases = data.get("test_cases", [])

    # 1. Lọc theo danh sách ID cụ thể (ví dụ: ["A-1", "A-36"])
    if target_ids:
        test_cases = [tc for tc in test_cases if tc["id"] in target_ids]

    # 2. Lọc theo đề thi (A, B, C, D)
    if exam_filter:
        test_cases = [tc for tc in test_cases if tc["exam"] == exam_filter]

    # 3. Giới hạn số lượng câu hỏi nếu có tham số limit
    if limit:
        test_cases = test_cases[:limit]

    results = []
    correct_count = 0

    print(
        f"🚀 Bắt đầu đánh giá {len(test_cases)} câu hỏi từ {os.path.basename(input_file)}..."
    )
    print("-" * 50)

    for i, tc in enumerate(test_cases):
        question_id = tc["id"]
        question_text = tc["question"]
        options = tc["options"]
        ground_truth = tc["correct_answer"]
        expected_lo = tc.get("learning_objective", "N/A")

        options_text = "\n".join([f"{k}: {v}" for k, v in options.items()])
        full_query = f"{question_text}\n\nOptions:\n{options_text}"

        print(
            f"[{i + 1}/{len(test_cases)}] Đang kiểm tra câu {question_id}...", end=" "
        )

        ai_response = ""
        error_msg = None
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            # Xử lý ảnh nếu có
            image_path = tc.get("image_path")
            image_base64 = encode_image(image_path) if image_path else None
            if image_base64:
                print(f"🖼️ Đã tìm thấy ảnh kèm theo câu hỏi {question_id}")

            try:
                ai_response = await rag_service.chat(
                    query=full_query, 
                    image_base64=image_base64
                )
                break
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                break

        # Trích xuất đáp án (Hỗ trợ nhiều đáp án: [A, E])
        ai_picked = "N/A"
        is_correct = False

        if ai_response:
            # 1. Tìm dòng chứa "Đáp án:"
            answer_line = ""
            lines = ai_response.split("\n")
            for line in lines:
                if "Đáp án:" in line:
                    answer_line = line
                    break

            # 2. Trích xuất tất cả chữ cái A-Z trong dòng đó
            if answer_line:
                # Ưu tiên tìm nội dung trong ngoặc vuông [...]
                in_brackets = re.search(r"\[(.*?)\]", answer_line)
                if in_brackets:
                    ai_picked_list = re.findall(
                        r"([A-Z])", in_brackets.group(1).upper()
                    )
                else:
                    # Nếu không có ngoặc, lấy phần sau "Đáp án:" nhưng dừng lại trước dấu gạch ngang hoặc dấu hai chấm của giải thích
                    after_label = (
                        answer_line.split("Đáp án:")[-1].split("-")[0].split(":")[0]
                    )
                    ai_picked_list = re.findall(r"([A-Z])", after_label.upper())
            else:
                # Fallback: Tìm chữ cái đơn lẻ trong 2 dòng đầu tiên
                text_to_search = "\n".join(lines[:2])
                ai_picked_list = re.findall(r"\b([A-Z])\b", text_to_search.upper())

            ai_picked = (
                ",".join(sorted(set(ai_picked_list))) if ai_picked_list else "N/A"
            )

            # 3. So sánh với ground_truth (hỗ trợ cả string "A" hoặc list ["A", "E"])
            gt_list = (
                ground_truth if isinstance(ground_truth, list) else list(ground_truth)
            )
            is_correct = (
                set(ai_picked_list) == set(gt_list) if ai_picked_list else False
            )
        elif error_msg:
            ai_picked = "ERROR"

        # Trích xuất nguồn chatbot (các mã số chương như 1.1.1)
        chatbot_sources = []
        if ai_response:
            # Tìm phần nội dung từ "Nguồn tham khảo" cho đến hết
            source_match = re.search(
                r"Nguồn tham khảo.*", ai_response, re.IGNORECASE | re.DOTALL
            )
            # Nếu tìm thấy từ khóa "Nguồn tham khảo", chỉ tìm trong phần đó. Nếu không, quét toàn bộ response làm dự phòng.
            source_text_to_search = (
                source_match.group(0) if source_match else ai_response
            )

            # Tìm tất cả các chuỗi số dạng x.y hoặc x.y.z (ví dụ: 1.1.1, 1.4)
            chatbot_sources = re.findall(r"(\d+\.\d+(?:\.\d+)?)", source_text_to_search)

        chatbot_source_str = (
            ", ".join(sorted(set(chatbot_sources))) if chatbot_sources else "None"
        )

        # Kiểm tra xem mã LO có nằm trong chatbot_sources không
        lo_num = expected_lo.replace("FL-", "")
        has_correct_source = any(lo_num in s for s in chatbot_sources)

        # Kết quả tổng: Đúng cả đáp án và đúng cả nguồn
        total_success = is_correct and has_correct_source

        if is_correct:
            correct_count += 1
            print("✅")
        else:
            print(f"❌ (GT: {ground_truth})")

        # Log full response ra console để debug
        print(f"   [AI]: {ai_picked} | [Source]: {chatbot_source_str}")
        print(f"   [Full Response]:\n{ai_response}")
        print("-" * 50)

        results.append(
            {
                "id": question_id,
                "ground_truth": ",".join(gt_list)
                if isinstance(gt_list, list)
                else gt_list,
                "ai_picked": ai_picked,
                "expected_lo": expected_lo,
                "chatbot_source": chatbot_source_str,
                "is_correct": is_correct,
                "has_correct_source": has_correct_source,
                "total_success": total_success,
                # "ai_response": ai_response or f"Error: {error_msg}",
            }
        )

    accuracy = (correct_count / len(test_cases)) * 100 if test_cases else 0
    source_accuracy = (
        (sum(1 for r in results if r["has_correct_source"]) / len(test_cases)) * 100
        if test_cases
        else 0
    )
    total_accuracy = (
        (sum(1 for r in results if r["total_success"]) / len(test_cases)) * 100
        if test_cases
        else 0
    )
    duration = time.time() - start_time

    # --- HIỂN THỊ BẢNG KẾT QUẢ ---
    print("\n\n" + "=" * 145)
    print(
        f"{'ID':<6} | {'Đáp án':<8} | {'AI Chọn':<8} | {'Kết quả':<10} | {'Nguồn Chuẩn':<15} | {'Nguồn Bot':<15} | {'Nguồn Đúng?':<12} | {'Tổng kết'}"
    )
    print("-" * 145)
    for res in results:
        ans_status = "✅ ĐÚNG" if res["is_correct"] else "❌ SAI"
        src_status = "✅ ĐÚNG" if res["has_correct_source"] else "❌ SAI"
        total_status = "🌟 ĐẠT" if res["total_success"] else "⭕ KHÔNG ĐẠT"

    # --- TẠO THƯ MỤC BÁO CÁO ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    reports_base_dir = os.path.join(backend_dir, "reports")
    current_report_dir = os.path.join(reports_base_dir, f"evaluation_{timestamp}")
    os.makedirs(current_report_dir, exist_ok=True)

    # --- XUẤT FILE MARKDOWN ---
    md_file_path = os.path.join(current_report_dir, "results.md")
    with open(md_file_path, "w", encoding="utf-8") as f:
        f.write("# Báo cáo đánh giá độ chính xác RAG (ISTQB)\n\n")
        f.write(f"- **Thời gian đánh giá:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- **Tổng thời gian thực thi:** `{duration:.2f} giây`\n")
        f.write(f"- **File dữ liệu:** `{os.path.basename(input_file)}`\n")
        f.write(f"- **Tổng số câu hỏi:** {len(test_cases)}\n")
        f.write(f"- **Số câu đúng:** {correct_count}\n")
        f.write(f"- **Độ chính xác:** {accuracy:.2f}%\n")
        f.write(f"- **Tỉ lệ nguồn chuẩn:** {source_accuracy:.2f}%\n")
        f.write(f"- **Tỉ lệ đạt tổng hợp (Đúng cả câu & nguồn):** {total_accuracy:.2f}%\n\n")

        f.write("## Chi tiết kết quả\n\n")
        f.write("| ID | Đáp án | AI Chọn | Kết quả | Nguồn Chuẩn | Nguồn Bot | Nguồn Đúng? | Tổng kết |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for res in results:
            ans_status = "✅" if res["is_correct"] else "❌"
            src_status = "✅" if res["has_correct_source"] else "❌"
            total_status = "🌟" if res["total_success"] else "⭕"
            f.write(
                f"| {res['id']} | {res['ground_truth']} | {res['ai_picked']} | {ans_status} | {res['expected_lo']} | {res['chatbot_source']} | {src_status} | {total_status} |\n"
            )

    print(f"\n📝 Đã lưu báo cáo Markdown tại: {md_file_path}")

    # --- XUẤT FILE JSON ---
    json_file_path = os.path.join(current_report_dir, "report.json")
    with open(json_file_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "duration_seconds": round(duration, 2),
                "input_file": input_file,
                "summary": {
                    "total": len(test_cases),
                    "correct": correct_count,
                    "accuracy": accuracy,
                },
                "details": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=str,
        default="test_data.json",
        help="Đường dẫn file test_data.json",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Số lượng câu hỏi cần test (mặc định: all)",
    )
    parser.add_argument(
        "--exam", type=str, default=None, help="Mã đề (A, B, C, D) (mặc định: all)"
    )
    parser.add_argument(
        "--ids", type=str, default=None, help="Danh sách ID câu hỏi (ví dụ: A-1,A-36)"
    )
    args = parser.parse_args()

    # Xử lý danh sách ID nếu có
    target_ids = None
    if args.ids:
        target_ids = [id.strip() for id in args.ids.split(",")]

    input_path = args.input
    if not os.path.isabs(input_path):
        if not os.path.exists(input_path):
            input_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", args.input)
            )

    asyncio.run(
        run_evaluation(
            input_path, limit=args.limit, exam_filter=args.exam, target_ids=target_ids
        )
    )
