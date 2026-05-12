import sys
import os
import json
import asyncio
import base64
import time
from datetime import datetime
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage

# Thêm thư mục backend vào sys.path để lấy config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.core.config import settings


def encode_image(image_path):
    """Mã hóa ảnh sang base64"""
    try:
        if not os.path.isabs(image_path):
            root_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            image_path = os.path.join(root_dir, image_path)

        if os.path.exists(image_path):
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode("utf-8")
    except Exception as e:
        print(f"⚠️ Không thể đọc ảnh {image_path}: {e}")
    return None


async def test_no_rag(limit=10, ids=None, exam=None):
    start_time = time.time()
    # Khởi tạo model (Dùng cấu hình giống hệt RAG để so sánh công bằng)
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-pro",
        temperature=0.0,
        google_api_key=settings.GOOGLE_API_KEY,
    )

    input_file = os.path.join(os.path.dirname(__file__), "..", "test_data.json")
    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    test_cases = data.get("test_cases", [])

    # 1. Lọc theo ID nếu có
    if ids:
        target_ids = [i.strip() for i in ids.split(",")]
        test_cases = [tc for tc in test_cases if tc["id"] in target_ids]

    # 2. Lọc theo đề thi
    if exam:
        test_cases = [tc for tc in test_cases if tc.get("exam") == exam]

    # 3. Giới hạn số lượng
    if limit and not ids:
        test_cases = test_cases[:limit]

    print(f"🚀 Bắt đầu test trực tiếp LLM (NO RAG) cho {len(test_cases)} câu hỏi...")
    print("-" * 50)

    correct_count = 0
    results = []

    for i, tc in enumerate(test_cases):
        q_id = tc["id"]
        question = tc["question"]
        options = tc["options"]
        ground_truth = tc["correct_answer"]

        options_text = "\n".join([f"{k}: {v}" for k, v in options.items()])
        prompt = f"{question}\n\nOptions:\n{options_text}\n\nTrả lời ngắn gọn theo format:\nĐáp án: [X]"

        # Xử lý ảnh nếu có
        image_path = tc.get("image_path")
        image_base64 = encode_image(image_path) if image_path else None

        human_content = [{"type": "text", "text": prompt}]
        if image_base64:
            print(f"🖼️ Đã tìm thấy ảnh kèm theo câu hỏi {q_id}")
            human_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                }
            )

        messages = [
            SystemMessage(
                content="Bạn là chuyên gia ISTQB. Hãy trả lời câu hỏi trắc nghiệm dựa trên kiến thức của bạn. Nếu có hình ảnh đính kèm, hãy quan sát kỹ hình ảnh để trả lời."
            ),
            HumanMessage(content=human_content),
        ]

        try:
            response = await llm.ainvoke(messages)
            ai_text = response.content
            print(ai_text)

            # Trích xuất đáp án (Linh hoạt: hỗ trợ cả [D], D, A,B,...)
            ai_picked = []
            ans_match = re.search(r"Đáp án:\s*(.*)", ai_text, re.IGNORECASE)
            if ans_match:
                raw_ans = ans_match.group(1).upper()
                # Trích xuất tất cả các chữ cái A, B, C, D, E
                ai_picked = re.findall(r"[A-E]", raw_ans)

            is_correct = set(ai_picked) == set(ground_truth)
            if is_correct:
                correct_count += 1

            status = "✅ ĐÚNG" if is_correct else "❌ SAI"
            print(
                f"[{i + 1}/{len(test_cases)}] {q_id}: {status} | AI: {ai_picked} | GT: {ground_truth}"
            )

            # Lưu kết quả để xuất file
            results.append(
                {
                    "id": q_id,
                    "ground_truth": ground_truth,
                    "ai_picked": ai_picked,
                    "is_correct": is_correct,
                    "full_response": ai_text,
                }
            )

        except Exception as e:
            print(f"Lỗi câu {q_id}: {e}")

    accuracy = (correct_count / len(test_cases)) * 100 if test_cases else 0
    duration = time.time() - start_time
    print("-" * 50)
    print(f"📊 KẾT QUẢ NO RAG: {correct_count}/{len(test_cases)} ({accuracy:.2f}%)")
    print(f"⏱️ Tổng thời gian: {duration:.2f} giây")

    # --- TẠO THƯ MỤC BÁO CÁO ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_name = llm.model.replace("models/", "").replace("-", "_")
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    reports_base_dir = os.path.join(backend_dir, "reports")
    current_report_dir = os.path.join(
        reports_base_dir, f"no_rag_{model_name}_{timestamp}"
    )
    os.makedirs(current_report_dir, exist_ok=True)

    # --- XUẤT FILE MARKDOWN ---
    md_path = os.path.join(current_report_dir, "results.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(
            f"# Báo cáo đánh giá LLM trực tiếp ({llm.model.upper()} - KHÔNG RAG)\n\n"
        )
        f.write(f"- **Thời gian:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- **Tổng thời gian thực thi:** `{duration:.2f} giây`\n")
        f.write(f"- **Model:** `{llm.model}`\n")
        f.write(f"- **Tổng số câu:** {len(test_cases)}\n")
        f.write(f"- **Số câu đúng:** {correct_count}\n")
        f.write(f"- **Độ chính xác:** {accuracy:.2f}%\n\n")

        f.write("| ID | Đáp án chuẩn | AI chọn | Kết quả |\n")
        f.write("| :--- | :--- | :--- | :--- |\n")
        for res in results:
            status = "✅ ĐÚNG" if res["is_correct"] else "❌ SAI"
            f.write(
                f"| {res['id']} | {res['ground_truth']} | {res['ai_picked']} | {status} |\n"
            )

    print(f"📝 Báo cáo Markdown: {md_path}")

    # --- XUẤT FILE JSON ---
    json_path = os.path.join(current_report_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "duration_seconds": round(duration, 2),
                "model": llm.model,
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
    print(f"📂 Dữ liệu JSON: {json_path}")


if __name__ == "__main__":
    import argparse
    import re

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", type=str, default=None)
    parser.add_argument("--exam", type=str, default=None, help="Mã đề (A, B, C, D)")
    args = parser.parse_args()

    asyncio.run(test_no_rag(limit=args.limit, ids=args.ids, exam=args.exam))
