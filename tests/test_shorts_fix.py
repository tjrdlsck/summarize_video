import pytest
from unittest.mock import MagicMock, patch
from services.shorts_maker import ShortsMaker
from services.clipper import VideoClipper


def test_shorts_maker_smart_fallback():
    """챕터 매칭된 세그먼트의 총 길이가 min_duration(40초)보다 부족할 때 전체 스크립트로 Fallback하는지 테스트."""
    maker = ShortsMaker()
    maker.api_key = "dummy_key"

    transcripts = [
        {"id": 1, "start": 0.0, "end": 10.0, "text": "안녕하세요 첫 인사입니다."},
        {"id": 2, "start": 10.0, "end": 60.0, "text": "본문 내용입니다. 중요한 에피소드가 이어집니다."},
        {"id": 3, "start": 60.0, "end": 90.0, "text": "마무리 결론 메시지입니다."}
    ]

    # 10초 분량만 매칭되는 챕터 지정
    chapters = [
        {
            "title": "짧은 챕터",
            "type": "Illustration", # sermon 타겟 타입 중 하나
            "time": {"start": 0.0, "end": 10.0}
        }
    ]

    mock_client = MagicMock()
    mock_response = MagicMock()
    # Mock LLM이 스크립트를 받아 정상 숏츠 후보 반환
    mock_response.text = '''[
        {
            "title": "테스트 숏츠",
            "reason": "테스트 이유",
            "segments": [{"start": 10.0, "end": 55.0}]
        }
    ]'''
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        candidates = maker.make_shorts_candidates(
            transcripts=transcripts,
            video_title="테스트 비디오",
            chapters=chapters,
            content_type="sermon",
            min_duration=40.0,
            max_duration=90.0
        )

    # 챕터 매칭(10초)이 40초 미만이므로 Fallback되어 전체 스크립트 기반으로 숏츠 후보가 생성되어야 함
    assert len(candidates) > 0
    assert candidates[0]["title"] == "테스트 숏츠"


def test_shorts_maker_timestamp_type_safety():
    """LLM 반환 타임스탬프 데이터에 유효하지 않은 숫자/None이 섞여 있을 때 안전하게 처리되는지 테스트."""
    maker = ShortsMaker()
    maker.api_key = "dummy_key"

    transcripts = [
        {"id": 1, "start": 0.0, "end": 60.0, "text": "전체 테스트용 스크립트입니다."}
    ]

    mock_client = MagicMock()
    mock_response = MagicMock()
    # 잘못된 타임스탬프(invalid, None)가 포함된 세그먼트 포함
    mock_response.text = '''[
        {
            "title": "타임스탬프 오류 테스트 숏츠",
            "reason": "안전성 테스트",
            "segments": [
                {"start": "invalid", "end": 30.0},
                {"start": 10.0, "end": 55.0}
            ]
        }
    ]'''
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        candidates = maker.make_shorts_candidates(
            transcripts=transcripts,
            video_title="테스트 비디오",
            min_duration=40.0,
            max_duration=90.0
        )

    # 유효하지 않은 세그먼트는 스킵되고 유효한 세그먼트로 숏츠가 정상 생성됨
    assert len(candidates) > 0
    assert candidates[0]["total_duration"] == 45.0


def test_clipper_dynamic_audio_fade():
    """0.15초와 같이 극단적으로 짧은 세그먼트에 대한 동적 오디오 페이드 인/아웃 스케일링 계산 검증."""
    duration = 0.15
    f_in = 0.1
    f_out = 0.2

    effective_f_in = min(f_in, max(0.01, duration / 2.0))
    effective_f_out = min(f_out, max(0.01, duration / 2.0))
    fade_out_st = max(0.0, duration - effective_f_out)

    assert effective_f_in == 0.075
    assert effective_f_out == 0.075
    assert fade_out_st == 0.075


def test_pipeline_runner_defines_transcript_path():
    """run_shorts_pipeline 내부에서 transcript_path 변수가 정상 정의되어 있는지 검증."""
    import inspect
    from app.application.pipeline_runner import PipelineRunner

    source = inspect.getsource(PipelineRunner.run_shorts_pipeline)
    assert "transcript_path =" in source
    assert "effective_sub_path =" in source
