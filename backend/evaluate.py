"""
Script đánh giá độ chính xác của chatbot ISTQB
Sử dụng bộ test data để kiểm tra khả năng trả lời đúng của chatbot
"""

import json
import re
import asyncio
import httpx
from typing import Dict, List, Tuple
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Cấu hình
API_URL = os.getenv("API_URL", "http://localhost:8000")
TEST_DATA_PATH = "test_data.json"
RESULTS_PATH = "evaluation_results.json"


class ChatbotEvaluator:
    def __init__(self, api_url: str = API_URL):
        self.api_url = api_url
        self.results = []
        
    def extract_answer_from_response(self, response: str, question_type: str) -> str:
        """
        Trích xuất đáp án từ câu trả lời của chatbot.
        Hỗ trợ nhiều định dạng: A, B, C, D hoặc tên đầy đủ của đáp án.
        """
        if question_type != "multiple_choice":
            return response.strip()
        
        # Tìm đáp án dạng chữ cái (A, B, C, D)
        # Pattern 1: "Đáp án là A" hoặc "Câu trả lời: B"
        patterns = [
            r'(?:đáp án|answer|trả lời|câu trả lời|kết quả|result)[\s:]*là?[\s:]*([A-D])',
            r'^([A-D])[\.\)]\s',  # "A. " hoặc "A) "
            r'\b([A-D])\b',  # Tìm chữ cái đơn lẻ
        ]
        
        for pattern in patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                return match.group(1).upper()
        
        # Nếu không tìm thấy chữ cái, tìm kiếm theo nội dung đáp án
        # (có thể chatbot trả lời bằng cách mô tả đáp án)
        return None
    
    def format_question_with_options(self, test_case: Dict) -> str:
        """
        Format câu hỏi kèm các đáp án để gửi cho chatbot.
        Ví dụ: "Câu hỏi: ...\nA. ...\nB. ...\nC. ...\nD. ...\nHãy chọn đáp án đúng (A, B, C hoặc D)."
        """
        question = test_case['question']
        question_type = test_case.get('type', '')
        
        if question_type == 'multiple_choice' and 'options' in test_case:
            options = test_case['options']
            formatted = f"{question}\n\n"
            formatted += "Các đáp án:\n"
            for key, value in options.items():
                formatted += f"{key}. {value}\n"
            formatted += "\nHãy chọn đáp án đúng (chỉ trả lời bằng chữ cái A, B, C hoặc D)."
            return formatted
        else:
            # Với câu hỏi tự luận, chỉ trả về câu hỏi
            return question
    
    def normalize_answer(self, answer: str) -> str:
        """Chuẩn hóa đáp án để so sánh"""
        if answer:
            return answer.strip().upper()
        return ""
    
    def compare_answers(self, chatbot_answer: str, correct_answer: str, question_type: str) -> Tuple[bool, str]:
        """
        So sánh đáp án của chatbot với đáp án đúng.
        Trả về (is_correct, explanation)
        """
        if question_type == "multiple_choice":
            extracted = self.extract_answer_from_response(chatbot_answer, question_type)
            if extracted:
                is_correct = self.normalize_answer(extracted) == self.normalize_answer(correct_answer)
                explanation = f"Chatbot trả lời: {extracted}, Đáp án đúng: {correct_answer}"
                return is_correct, explanation
            else:
                # Nếu không extract được, kiểm tra xem câu trả lời có chứa đáp án đúng không
                # (trường hợp chatbot trả lời bằng cách mô tả)
                correct_answer_normalized = self.normalize_answer(correct_answer)
                if correct_answer_normalized in chatbot_answer.upper():
                    return True, f"Chatbot đề cập đến đáp án {correct_answer} trong câu trả lời"
                return False, f"Không thể xác định đáp án từ câu trả lời của chatbot"
        else:
            # Với câu hỏi tự luận, cần so sánh ngữ nghĩa (có thể dùng embedding hoặc LLM)
            # Ở đây chỉ so sánh đơn giản
            return chatbot_answer.strip().lower() == correct_answer.strip().lower(), "So sánh trực tiếp"
    
    async def ask_chatbot(self, question: str) -> str:
        """Gửi câu hỏi đến chatbot API và nhận câu trả lời"""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/api/chat",
                    json={"query": question},
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                data = response.json()
                return data.get("answer", "")
        except httpx.TimeoutException:
            return "Lỗi: Timeout khi gọi API"
        except httpx.HTTPStatusError as e:
            return f"Lỗi HTTP: {e.response.status_code}"
        except Exception as e:
            return f"Lỗi: {str(e)}"
    
    async def evaluate_test_case(self, test_case: Dict) -> Dict:
        """Đánh giá một test case"""
        print(f"\n[{test_case['id']}] Đang test: {test_case['question'][:50]}...")
        
        # Format câu hỏi kèm các đáp án (nếu là câu hỏi trắc nghiệm)
        formatted_question = self.format_question_with_options(test_case)
        
        # Gửi câu hỏi đã format đến chatbot
        chatbot_answer = await self.ask_chatbot(formatted_question)
        
        # So sánh đáp án
        is_correct, explanation = self.compare_answers(
            chatbot_answer,
            test_case['correct_answer'],
            test_case['type']
        )
        
        result = {
            "test_id": test_case['id'],
            "question": test_case['question'],
            "formatted_question": formatted_question,  # Lưu câu hỏi đã format để tham khảo
            "correct_answer": test_case['correct_answer'],
            "chatbot_answer": chatbot_answer,
            "extracted_answer": self.extract_answer_from_response(chatbot_answer, test_case['type']),
            "is_correct": is_correct,
            "explanation": explanation,
            "category": test_case.get('category', 'Unknown'),
            "timestamp": datetime.now().isoformat()
        }
        
        status = "✓ ĐÚNG" if is_correct else "✗ SAI"
        print(f"  {status} - {explanation}")
        
        return result
    
    async def evaluate_all(self, test_data_path: str = TEST_DATA_PATH):
        """Đánh giá tất cả test cases"""
        # Đọc test data
        try:
            with open(test_data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            print(f"Lỗi: Không tìm thấy file {test_data_path}")
            return
        except json.JSONDecodeError:
            print(f"Lỗi: File {test_data_path} không phải JSON hợp lệ")
            return
        
        test_cases = data.get('test_cases', [])
        if not test_cases:
            print("Lỗi: Không có test cases trong file")
            return
        
        print(f"Bắt đầu đánh giá {len(test_cases)} test cases...")
        print(f"API URL: {self.api_url}")
        print("=" * 60)
        
        # Đánh giá từng test case
        for test_case in test_cases:
            result = await self.evaluate_test_case(test_case)
            self.results.append(result)
            # Delay nhỏ để tránh rate limit
            await asyncio.sleep(1)
        
        # Tính toán thống kê
        total = len(self.results)
        correct = sum(1 for r in self.results if r['is_correct'])
        accuracy = (correct / total * 100) if total > 0 else 0
        
        # Phân loại theo category
        category_stats = {}
        for result in self.results:
            cat = result['category']
            if cat not in category_stats:
                category_stats[cat] = {'total': 0, 'correct': 0}
            category_stats[cat]['total'] += 1
            if result['is_correct']:
                category_stats[cat]['correct'] += 1
        
        # Tạo báo cáo
        report = {
            "evaluation_date": datetime.now().isoformat(),
            "total_tests": total,
            "correct_answers": correct,
            "incorrect_answers": total - correct,
            "accuracy_percentage": round(accuracy, 2),
            "category_statistics": {
                cat: {
                    "total": stats['total'],
                    "correct": stats['correct'],
                    "accuracy": round(stats['correct'] / stats['total'] * 100, 2) if stats['total'] > 0 else 0
                }
                for cat, stats in category_stats.items()
            },
            "detailed_results": self.results
        }
        
        # Lưu kết quả
        with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # In báo cáo tóm tắt
        print("\n" + "=" * 60)
        print("BÁO CÁO ĐÁNH GIÁ")
        print("=" * 60)
        print(f"Tổng số test: {total}")
        print(f"Đáp án đúng: {correct}")
        print(f"Đáp án sai: {total - correct}")
        print(f"Độ chính xác: {accuracy:.2f}%")
        print("\nThống kê theo danh mục:")
        for cat, stats in category_stats.items():
            acc = stats['correct'] / stats['total'] * 100 if stats['total'] > 0 else 0
            print(f"  {cat}: {stats['correct']}/{stats['total']} ({acc:.2f}%)")
        print(f"\nKết quả chi tiết đã được lưu vào: {RESULTS_PATH}")


async def main():
    """Hàm main"""
    evaluator = ChatbotEvaluator()
    await evaluator.evaluate_all()


if __name__ == "__main__":
    asyncio.run(main())

