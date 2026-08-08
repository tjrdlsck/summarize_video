import unittest
from unittest.mock import MagicMock, patch
import json
import os
from services.summarizer import VideoSummarizer

class TestMapReduceSummarizer(unittest.TestCase):
    def setUp(self):
        self.segments = [
            {"id": 1, "start": 0.0, "end": 10.0, "text": "안녕하세요, 오늘 말씀 제목은 은혜입니다."},
            {"id": 2, "start": 10.0, "end": 20.0, "text": "성경 본문은 요한복음 3장 16절입니다."},
            {"id": 3, "start": 20.0, "end": 30.0, "text": "하나님이 세상을 이처럼 사랑하사 독생자를 주셨으니."},
            {"id": 4, "start": 30.0, "end": 40.0, "text": "예화로 한 청년의 이야기를 들려드리겠습니다."},
            {"id": 5, "start": 40.0, "end": 50.0, "text": "결론적으로 우리는 늘 기도하며 살아야 합니다. 아멘."}
        ]
        self.output_dir = "static/test_results_temp"
        os.makedirs(self.output_dir, exist_ok=True)
        self.summarizer = VideoSummarizer(output_dir=self.output_dir)
        self.summarizer.api_key = "dummy_key"

    @patch("google.genai.Client")
    def test_summarize_map_reduce_pipeline(self, mock_genai_client):
        # Mock Client 및 Response 구성
        mock_client_instance = MagicMock()
        mock_genai_client.return_value = mock_client_instance

        # Map phase response mock
        map_response_mock = MagicMock()
        map_response_mock.text = "- 핵심 구절: 요한복음 3:16\n- 주요 예화: 청년의 이야기"
        map_response_mock.usage_metadata = MagicMock(prompt_token_count=100, candidates_token_count=50)

        # Reduce phase response mock
        reduce_data = {
            "blog_title": "은혜의 삶과 기도",
            "blog_post": "오늘 말씀은 **은혜**에 관한 메시지입니다. <mark>하나님이 세상을 사랑하사</mark> 독생자를 주셨습니다.",
            "chapters": [
                {
                    "title": "도입 및 성경 본문",
                    "type": "Scripture",
                    "summary": "성경 본문 봉독",
                    "start_id": 1,
                    "end_id": 3
                },
                {
                    "title": "예화 및 설교 본문",
                    "type": "Preaching_Main",
                    "summary": "청년의 예화 및 기도 권면",
                    "start_id": 4,
                    "end_id": 5
                }
            ]
        }
        reduce_response_mock = MagicMock()
        reduce_response_mock.text = json.dumps(reduce_data, ensure_ascii=False)
        reduce_response_mock.usage_metadata = MagicMock(prompt_token_count=300, candidates_token_count=150)

        # Map response 1회, Reduce response 1회 순차 제공
        mock_client_instance.models.generate_content.side_effect = [
            map_response_mock,
            reduce_response_mock
        ]

        result = self.summarizer.summarize_map_reduce(
            segments=self.segments,
            video_filename="test_video.mp4",
            content_type="sermon"
        )

        self.assertNotIn("error", result)
        self.assertEqual(result["blog_title"], "은혜의 삶과 기도")
        self.assertEqual(len(result["chapters"]), 2)
        self.assertEqual(result["analysis_meta"]["mode"], "map_reduce")

    def tearDown(self):
        import shutil
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

if __name__ == "__main__":
    unittest.main()
