import unittest
from services.content_profiles import (
    get_content_profile,
    SERMON_PROFILE,
    STREAMING_PROFILE,
    INFORMATIONAL_PROFILE,
)
from services.summarizer import VideoSummarizer
from services.shorts_maker import ShortsMaker


class TestPromptTemplatesAndSchemas(unittest.TestCase):
    """Gemini Flash-Lite 프롬프트 템플릿, 스키마 및 핀포인트 파이프라인 데이터 흐름 단위 테스트."""

    def test_content_profiles_fields(self):
        """3대 프로필의 신규 필드 (CoT 가이드, 퓨샷 예시, 임팩트 기준) 등록 여부 검증."""
        for profile in [SERMON_PROFILE, STREAMING_PROFILE, INFORMATIONAL_PROFILE]:
            self.assertTrue(len(profile.cot_thinking_guide) > 0)
            self.assertIn("<example>", profile.blog_few_shot_example)
            self.assertTrue(len(profile.impact_criteria) > 0)
            self.assertTrue(len(profile.summary_type_enum) >= 6)

    def test_blog_prompt_xml_structure(self):
        """VideoSummarizer._create_blog_prompt XML 구조 태그 포함 여부 검증."""
        summarizer = VideoSummarizer()
        mock_segments = [
            {"id": 1, "start": 0.0, "end": 5.0, "text": "안녕하세요."},
            {"id": 2, "start": 5.0, "end": 10.0, "text": "오늘 나눌 말씀은 마가복음입니다."},
        ]

        prompt = summarizer._create_blog_prompt(mock_segments, content_type="sermon")

        self.assertIn("<system_instructions>", prompt)
        self.assertIn("<persona>", prompt)
        self.assertIn("<thinking>", prompt)
        self.assertIn("<rules>", prompt)
        self.assertIn("<script_data>", prompt)
        self.assertIn("[[ID:숫자]]", prompt)

    def test_normalize_chapter_ranges_preserves_pinpoint_data(self):
        """VideoSummarizer._normalize_chapter_ranges 핀포인트 데이터(key_segment_ids, focus_point) 보존 검증."""
        summarizer = VideoSummarizer()
        raw_chapters = [
            {
                "title": "도입부",
                "type": "Intro_Icebreak",
                "summary": "인사말",
                "start_id": 1,
                "end_id": 5,
                "key_segment_ids": [2, 3],
                "focus_point": "따뜻한 인사 힌트",
            },
            {
                "title": "예화 하이라이트",
                "type": "Illustration",
                "summary": "풍랑 예화",
                "start_id": 6,
                "end_id": 10,
                "key_segment_ids": [8],
                "focus_point": "풍랑 속 기적",
            },
        ]

        normalized = summarizer._normalize_chapter_ranges(raw_chapters, total_lines=10)

        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["key_segment_ids"], [2, 3])
        self.assertEqual(normalized[0]["focus_point"], "따뜻한 인사 힌트")
        self.assertEqual(normalized[1]["key_segment_ids"], [8])
        self.assertEqual(normalized[1]["focus_point"], "풍랑 속 기적")

    def test_shorts_maker_chapter_hints_context(self):
        """ShortsMaker._build_chapter_hints_context 힌트 문자열 동적 조립 검증."""
        shorts_maker = ShortsMaker()
        profile = get_content_profile("sermon")
        mock_chapters = [
            {
                "title": "감동 예화",
                "type": "Illustration",
                "key_segment_ids": [15, 16],
                "focus_point": "인생의 풍랑 속 주님",
            },
            {
                "title": "교회 광고",
                "type": "Announcement",
                "key_segment_ids": [30],
                "focus_point": "광고",
            },
        ]

        hints_text = shorts_maker._build_chapter_hints_context(mock_chapters, profile)

        # Illustration은 target_types에 포함되지만 Announcement는 제외되어야 함
        self.assertIn("감동 예화", hints_text)
        self.assertIn("Illustration", hints_text)
        self.assertIn("[15, 16]", hints_text)
        self.assertNotIn("교회 광고", hints_text)


if __name__ == "__main__":
    unittest.main()
