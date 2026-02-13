"""Regression tests for streaming-oriented shorts scoring helpers."""

import pytest

from services.shorts_maker import ShortsMaker


def _sample_transcripts():
    return [
        {"id": 1, "start": 0.0, "end": 1.1, "text": "뭐야 지금"},
        {"id": 2, "start": 1.35, "end": 2.0, "text": "진짜야?"},
        {"id": 3, "start": 2.35, "end": 3.0, "text": "ㅋㅋㅋ 이게 맞아"},
        {"id": 4, "start": 3.4, "end": 4.2, "text": "와 레전드다"},
    ]


def test_resolve_duration_bounds_defaults_and_guard():
    maker = ShortsMaker()
    assert maker._resolve_duration_bounds(40, 90) == (40.0, 90.0)
    assert maker._resolve_duration_bounds(90, 40) == (90.0, 100.0)


def test_streaming_turn_attachment_creates_multiple_turns():
    maker = ShortsMaker()
    annotated = maker._attach_turn_ids(_sample_transcripts(), speaker_mode="pseudo")

    switches = sum(
        1
        for idx in range(1, len(annotated))
        if annotated[idx]["pseudo_turn_id"] != annotated[idx - 1]["pseudo_turn_id"]
    )
    assert switches >= 2


def test_weights_respect_humor_priority_50_percent():
    maker = ShortsMaker()
    weights = maker._build_weights(50)

    assert weights["funniness"] == pytest.approx(0.5)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_tikkitaka_score_uses_turn_switches():
    maker = ShortsMaker()
    annotated = maker._attach_turn_ids(_sample_transcripts(), speaker_mode="pseudo")
    score, switches = maker._estimate_tikkitaka_score(annotated, duration=45.0)

    assert switches >= 2
    assert score > 0.1


def test_topic_match_rewards_focus_keyword():
    maker = ShortsMaker()
    overlap_segments = [{"text": "오늘 다윗 이야기에서 진짜 웃긴 장면 나옴"}]
    score = maker._estimate_topic_match("다윗", "다윗 레전드", "핵심 장면", overlap_segments)

    assert score >= 0.8
