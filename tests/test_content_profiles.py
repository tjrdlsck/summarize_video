"""Regression tests for content profile defaults and request schema compatibility."""

from app.schemas.requests import ShortsGenerateRequest, SummaryRequest, TranscriptionRequest
from services.content_profiles import get_content_profile, normalize_content_type


def test_normalize_content_type_falls_back_to_sermon():
    assert normalize_content_type(None) == "sermon"
    assert normalize_content_type("") == "sermon"
    assert normalize_content_type("unknown") == "sermon"


def test_get_content_profile_loads_streaming_profile():
    profile = get_content_profile("streaming")
    assert profile.content_type == "streaming"
    assert "Reaction_Highlight" in profile.summary_type_enum
    assert "Banter" in profile.shorts_target_types
    assert len(profile.cot_thinking_guide) > 0
    assert len(profile.impact_criteria) > 0


def test_get_content_profile_preserves_sermon_defaults():
    profile = get_content_profile("sermon")
    assert profile.content_type == "sermon"
    assert profile.summary_type_enum == [
        "Intro_Icebreak",
        "Scripture",
        "Preaching_Main",
        "Illustration",
        "Application",
        "Announcement",
        "Prayer",
    ]
    assert profile.shorts_target_types == ["Illustration", "Preaching_Main", "Application"]
    assert len(profile.cot_thinking_guide) > 0
    assert len(profile.impact_criteria) > 0


def test_request_models_use_sermon_as_default_content_type():
    assert TranscriptionRequest(filename="sample.mp4").content_type == "sermon"
    assert SummaryRequest(filename="sample.mp4").content_type == "sermon"
    shorts_req = ShortsGenerateRequest(filename="sample.mp4")
    assert shorts_req.content_type == "sermon"
    assert shorts_req.style == "funny"
    assert shorts_req.min_duration == 40.0
    assert shorts_req.max_duration == 90.0
    assert shorts_req.humor_weight == 50
    assert shorts_req.keep_original_tone is True
    assert shorts_req.speaker_mode == "pseudo"
