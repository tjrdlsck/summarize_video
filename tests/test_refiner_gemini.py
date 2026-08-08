import pytest
from unittest.mock import MagicMock, patch
from services.refiner import TextRefiner

def test_text_refiner_gemini_model_routing():
    refiner = TextRefiner()
    refiner.api_key = "fake_key"
    refiner.client = MagicMock()

    mock_response = MagicMock()
    mock_response.text = "### 도입부\n안녕하세요 [[ID:1]].\n\n### 본문\n<mark>핵심 내용입니다</mark> [[ID:2]]."
    
    with patch.object(refiner, "_call_gemini_with_retry", return_value=mock_response):
        segments = [
            {"id": 1, "start": 0.0, "end": 5.0, "text": "안녕하세요."},
            {"id": 2, "start": 5.0, "end": 10.0, "text": "핵심 내용입니다."}
        ]
        result = refiner.refine_chapter("raw_text", "테스트 챕터", segments=segments)
        
        assert "도입부" in result
        assert "(00:00:00)" in result
        assert "(00:00:05)" in result
        assert "<mark>핵심 내용입니다</mark>" in result

def test_text_refiner_no_segments_fallback():
    refiner = TextRefiner()
    refiner.api_key = "fake_key"
    refiner.client = MagicMock()

    result = refiner.refine_chapter("raw_text", "테스트 챕터", segments=[])
    assert "상세 세그먼트 데이터가 없어" in result


def test_text_refiner_genre_prompt_injection():
    refiner = TextRefiner()
    refiner.api_key = "fake_key"
    refiner.client = MagicMock()

    mock_response = MagicMock()
    mock_response.text = "### 스트리밍 요약 [[ID:1]]"
    
    with patch.object(refiner, "_call_gemini_with_retry", return_value=mock_response) as mock_call:
        segments = [{"id": 1, "start": 0.0, "end": 5.0, "text": "안녕"}]
        refiner.refine_chapter("raw_text", "스트리밍 챕터", segments=segments, content_type="streaming")
        
        # _call_gemini_with_retry에 전달된 contents 프롬프트에 스트리밍 지침이 들어갔는지 검증
        called_contents = mock_call.call_args[1]["contents"]
        assert "스트리밍 윤문 지침" in called_contents
        assert "[[ID:12]][[ID:13]] (쉼표 사용 절대 금지)" in called_contents
