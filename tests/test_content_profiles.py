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


def test_request_models_use_sermon_as_default_content_type():
    assert TranscriptionRequest(filename="sample.mp4").content_type == "sermon"
    assert SummaryRequest(filename="sample.mp4").content_type == "sermon"
    assert ShortsGenerateRequest(filename="sample.mp4").content_type == "sermon"
