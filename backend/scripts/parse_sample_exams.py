"""
Script parse các file PDF ISTQB CTFL Sample Exams → test_data.json

Xử lý 4 bộ đề (A, B, C, D), mỗi bộ gồm:
  - *-Questions_*.pdf : câu hỏi + options
  - *-Answers_*.pdf  : answer key + rationale chi tiết

Output: backend/test_data.json
"""

import json
import re
from pathlib import Path

import pdfplumber

# ─── Mapping Learning Objective → Category ────────────────────────────────────
LO_CATEGORY_MAP = {
    "FL-1": "Fundamentals of Testing",
    "FL-2": "Testing Throughout the SDLC",
    "FL-3": "Static Testing",
    "FL-4": "Test Analysis and Design",
    "FL-5": "Managing the Test Activities",
    "FL-6": "Test Tools",
}


def lo_to_category(lo: str) -> str:
    for prefix, cat in LO_CATEGORY_MAP.items():
        if lo.startswith(prefix):
            return cat
    return "Unknown"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def extract_full_text(pdf_path: str, start_page: int = 0) -> str:
    """Extract toàn bộ text từ PDF (từ start_page trở đi), nối các trang bằng dấu phân cách."""
    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[start_page:]:
            text = page.extract_text()
            if text:
                pages_text.append(text)
    return "\n".join(pages_text)


def normalize_answer_letters(raw: str) -> list[str]:
    """
    'a, e'  → ['A', 'E']
    'b'     → ['B']
    'c, e'  → ['C', 'E']
    """
    letters = re.findall(r"[a-eA-E]", raw)
    return sorted(set(l.upper() for l in letters))


# ─── Parse Answer Key Table ────────────────────────────────────────────────────


def parse_answer_key(answers_pdf: str) -> dict:
    """
    Parse bảng Answer Key tóm tắt trong Answers PDF.
    Trả về dict: { "1": {...}, "A1": {...}, ... }

    Format mỗi dòng:
      <num> <answer(s)> <LO> <K-level> <points>
    Ví dụ:
      1 c FL-1.1.1 K1 1
      6 a, e FL-1.4.5 K2 1
      A1 b FL-1.1.1 K1 1
    """
    answer_key = {}

    # Regex: không dùng ^ vì bảng Answer Key có 2 cột trên cùng 1 dòng
    # Format: <num> <answer(s)> <LO> <K-level> <points>
    # Ví dụ: "1 c FL-1.1.1 K1 1" hoặc "31 c, e FL-5.1.3 K2 1"
    row_pattern = re.compile(
        r"\b(A?\d+)\s+"  # question number (1, A1, A12, ...)
        r"([a-e](?:,\s*[a-e])*)\s+"  # answer(s): a / a, e / c, e
        r"(FL-[\d.]+)\s+"  # LO: FL-1.1.1
        r"(K\d)\s+"  # K-level: K1, K2, K3
        r"(\d)",  # points: 1
        re.IGNORECASE,
    )

    with pdfplumber.open(answers_pdf) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            # Chỉ xử lý trang có "Answer Key"
            if "Answer Key" not in text and "answer key" not in text.lower():
                continue
            for match in row_pattern.finditer(text):
                q_num_raw, ans_raw, lo, k_level, points = match.groups()
                q_num = q_num_raw.strip()
                # Bỏ qua các số giả (page numbers, version numbers)
                if int(re.sub(r"[^\d]", "", q_num) or 0) > 200:
                    continue
                answer_key[q_num] = {
                    "correct_answer": normalize_answer_letters(ans_raw),
                    "learning_objective": lo.strip(),
                    "k_level": k_level.strip(),
                    "category": lo_to_category(lo.strip()),
                }

    return answer_key


# ─── Parse Detailed Rationale ──────────────────────────────────────────────────


def parse_rationale(answers_pdf: str) -> dict:
    """
    Parse phần giải thích chi tiết (rationale) cho từng câu hỏi.
    Trả về dict: { "1": {"summary": "...", "per_option": {"A": "...", ...}}, ... }

    Format mỗi block (1 câu/trang hoặc nhiều câu/trang):
      <num>  <correct>  <explanation text>  <LO>  <K-level>  <points>
    """
    rationale = {}

    # Tập hợp toàn bộ text từ trang "Answers" (bỏ ToC và trang Answer Key)
    with pdfplumber.open(answers_pdf) as pdf:
        all_pages_text = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            # Bỏ qua trang ToC và trang Answer Key
            if "Answer Key" in text:
                continue
            if "Table of Contents" in text or "table of contents" in text.lower():
                continue
            # Chỉ lấy trang có section "Answers" hoặc "Explanation"
            if (
                "Explanation" in text
                or "Is correct" in text
                or "Is not correct" in text
            ):
                all_pages_text.append(text)

    full_text = "\n".join(all_pages_text)

    # Split theo block câu hỏi
    # Pattern: dòng bắt đầu bằng số câu (1, A1) + khoảng trắng + đáp án (a-e hoặc "a, e")
    block_pattern = re.compile(
        r"(?m)^(A?\d+)\s+([a-e](?:,\s*[a-e])*)\s+(.+?)(?=\n(?:A?\d+)\s+[a-e]|\Z)",
        re.DOTALL,
    )

    for match in block_pattern.finditer(full_text):
        q_num, ans_raw, body = match.groups()
        q_num = q_num.strip()
        body = body.strip()

        # Loại bỏ footer lines (Version, ©, Page X of Y)
        body = re.sub(r"Version[\s\S]*?© International Software.*?\n", "", body)
        body = re.sub(r"Certified Tester.*?\n", "", body)
        body = re.sub(r"Sample Exam.*?Answers\n", "", body)
        body = re.sub(r"Question.*?Objective.*?\n", "", body)
        body = re.sub(r"\(#\)\s*\(LO\).*?\n", "", body)
        body = re.sub(r"FL-[\d.]+\s+K\d\s+\d\s*$", "", body, flags=re.MULTILINE)
        body = body.strip()

        # Extract rationale per option: "a) Is correct/not correct..."
        per_option = {}
        option_pattern = re.compile(
            r"([a-e])\)\s+(.*?)(?=\n[a-e]\)|Thus:|Therefore:|$)",
            re.DOTALL | re.IGNORECASE,
        )
        footer_noise = re.compile(
            r"\n?(?:Version|Certified Tester|Sample Exam|Question\s+Correct|Number|\(#\)|© International).*",
            re.DOTALL | re.IGNORECASE,
        )
        for opt_match in option_pattern.finditer(body):
            opt_letter, opt_text = opt_match.groups()
            clean = footer_noise.sub("", opt_text).strip()
            per_option[opt_letter.upper()] = clean

        # Summary: lấy phần đầu trước option a) nếu có, hoặc toàn bộ body
        summary_match = re.split(r"\n[a-e]\)", body, maxsplit=1)
        summary = summary_match[0].strip() if len(summary_match) > 1 else body[:300]

        rationale[q_num] = {
            "summary": summary,
            "per_option": per_option,
        }

    return rationale


# ─── Parse Questions ───────────────────────────────────────────────────────────


def parse_questions(questions_pdf: str) -> list[dict]:
    """
    Parse file Questions PDF.
    Trả về list các dict câu hỏi chưa có đáp án.
    """
    questions = []

    # Bỏ qua các trang đầu (cover + ToC, thường là 6 trang đầu)
    # Dùng text để tự động phát hiện
    with pdfplumber.open(questions_pdf) as pdf:
        content_pages = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            # Trang ToC có "....." (chấm chấm dẫn số trang)
            if text.count("....") > 5:
                continue
            # Trang cover/intro có tiêu đề nhưng không có câu hỏi
            if "Question #" not in text:
                continue
            content_pages.append(text)

    full_text = "\n".join(content_pages)

    # Split theo header câu hỏi
    # "Question #1 (1 Point)" hoặc "Question #A3 (1 Point)"
    q_header = re.compile(r"Question #(A?\d+)\s+\(\d+ Point\w*\)", re.IGNORECASE)
    splits = q_header.split(full_text)

    # splits = [text_before_q1, "1", q1_body, "2", q2_body, ...]
    i = 1
    while i < len(splits) - 1:
        q_num_raw = splits[i].strip()
        body = splits[i + 1].strip()
        i += 2

        is_additional = q_num_raw.startswith("A")

        # Loại bỏ footer/header noise
        body = re.sub(r"Version[\s\S]*?© International Software.*?\n", "", body)
        body = re.sub(r"Certified Tester.*?\n", "", body)
        body = re.sub(r"Sample Exam.*?\n", "", body)
        body = body.strip()

        # Xác định select_count
        select_count = 2 if re.search(r"Select TWO", body, re.IGNORECASE) else 1

        # Tách body thành question_text và options
        # Options bắt đầu bằng "a)" hoặc "a. " ở đầu dòng
        options_start = re.search(r"\n[a-e][).]\s", body)
        if options_start:
            question_text = body[: options_start.start()].strip()
            options_block = body[options_start.start() :]
        else:
            question_text = body
            options_block = ""

        # Loại bỏ "Select ONE/TWO options." khỏi question_text
        question_text = re.sub(
            r"\s*Select (ONE|TWO) options?\.\s*$",
            "",
            question_text,
            flags=re.IGNORECASE,
        ).strip()

        # Parse từng option
        options = {}
        opt_matches = re.findall(
            r"([a-e])[).]\s+(.*?)(?=\n[a-e][).]|\nSelect|\Z)",
            options_block,
            re.DOTALL | re.IGNORECASE,
        )
        for opt_letter, opt_text in opt_matches:
            clean_text = opt_text.strip()
            clean_text = re.sub(
                r"\s*Select (ONE|TWO) options?\.\s*$",
                "",
                clean_text,
                flags=re.IGNORECASE,
            ).strip()
            options[opt_letter.upper()] = clean_text

        questions.append(
            {
                "q_num": q_num_raw,
                "is_additional": is_additional,
                "question": question_text,
                "options": options,
                "select_count": select_count,
            }
        )

    return questions


# ─── Build Test Cases ──────────────────────────────────────────────────────────


def build_test_cases(
    exam_label: str, questions: list, answer_key: dict, rationale: dict
) -> list[dict]:
    """Kết hợp questions + answer_key + rationale thành final test cases."""
    test_cases = []

    for q in questions:
        q_num = q["q_num"]
        ans_info = answer_key.get(q_num, {})
        rat_info = rationale.get(q_num, {})

        test_case = {
            "id": f"{exam_label}-{q_num}",
            "exam": exam_label,
            "question_number": q_num,
            "is_additional": q["is_additional"],
            "question": q["question"],
            "options": q["options"],
            "select_count": q["select_count"],
            "correct_answer": ans_info.get("correct_answer", []),
            "learning_objective": ans_info.get("learning_objective", ""),
            "k_level": ans_info.get("k_level", ""),
            "category": ans_info.get("category", "Unknown"),
            "rationale_summary": rat_info.get("summary", ""),
            "rationale_per_option": rat_info.get("per_option", {}),
        }
        test_cases.append(test_case)

    return test_cases


# ─── Main ──────────────────────────────────────────────────────────────────────


def main():
    materials_dir = Path(__file__).parent.parent / "materials" / "Sample Exams"
    output_path = Path(__file__).parent.parent / "test_data.json"

    # Tìm các bộ đề tự động
    exam_labels = ["A", "B", "C", "D"]
    all_test_cases = []
    exam_stats = []

    for label in exam_labels:
        # Tìm file Questions và Answers tương ứng
        q_files = list(materials_dir.glob(f"*Exam-{label}-Questions*.pdf"))
        a_files = list(materials_dir.glob(f"*Exam-{label}-Answers*.pdf"))

        if not q_files or not a_files:
            print(f"[WARN] Không tìm thấy file cho Exam {label}, bỏ qua.")
            continue

        q_path = str(q_files[0])
        a_path = str(a_files[0])

        print(f"\n{'=' * 60}")
        print(f"[Exam {label}] Parsing...")
        print(f"  Questions: {Path(q_path).name}")
        print(f"  Answers:   {Path(a_path).name}")

        # Parse
        answer_key = parse_answer_key(a_path)
        print(f"  → Answer key: {len(answer_key)} câu")

        rat = parse_rationale(a_path)
        print(f"  → Rationale: {len(rat)} câu")

        questions = parse_questions(q_path)
        print(f"  → Questions: {len(questions)} câu")

        # Build
        test_cases = build_test_cases(label, questions, answer_key, rat)
        all_test_cases.extend(test_cases)

        main_count = sum(1 for tc in test_cases if not tc["is_additional"])
        add_count = sum(1 for tc in test_cases if tc["is_additional"])
        exam_stats.append(
            {
                "exam": label,
                "main_questions": main_count,
                "additional_questions": add_count,
                "total": len(test_cases),
            }
        )
        print(
            f"  → Built: {main_count} main + {add_count} additional = {len(test_cases)} test cases"
        )

    # Phân loại
    main_cases = [tc for tc in all_test_cases if not tc["is_additional"]]
    additional_cases = [tc for tc in all_test_cases if tc["is_additional"]]

    output = {
        "metadata": {
            "version": "1.0",
            "description": "ISTQB CTFL v4.0 Sample Exam Ground Truth Dataset",
            "exams": exam_labels,
            "total_main_questions": len(main_cases),
            "total_additional_questions": len(additional_cases),
            "total_questions": len(all_test_cases),
            "exam_stats": exam_stats,
        },
        "test_cases": main_cases,
        "additional_test_cases": additional_cases,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"✅ Xuất thành công: {output_path}")
    print(f"   Main questions    : {len(main_cases)}")
    print(f"   Additional        : {len(additional_cases)}")
    print(f"   Tổng              : {len(all_test_cases)}")


if __name__ == "__main__":
    main()
