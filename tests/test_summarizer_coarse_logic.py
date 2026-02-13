"""Regression tests for coarse summarization helper logic."""

from services.summarizer import VideoSummarizer


def _make_segments(count: int, start: float = 0.0, step: float = 2.0):
    segments = []
    for idx in range(count):
        seg_id = idx + 1
        seg_start = start + (idx * step)
        seg_end = seg_start + step
        suffix = "." if seg_id % 3 == 0 else ""
        segments.append(
            {
                "id": seg_id,
                "start": seg_start,
                "end": seg_end,
                "text": f"테스트 문장 {seg_id}{suffix}",
            }
        )
    return segments


def test_build_coarse_segments_reduces_lines_and_keeps_source_range(tmp_path):
    summarizer = VideoSummarizer(output_dir=str(tmp_path))
    summarizer.coarse_target_seconds = 10.0
    summarizer.coarse_min_seconds = 8.0
    summarizer.coarse_max_seconds = 14.0

    original = _make_segments(40, step=2.0)
    coarse = summarizer._build_coarse_segments(original)

    assert len(coarse) < len(original)
    assert coarse[0]["source_start_id"] == 1
    assert coarse[-1]["source_end_id"] == 40

    # source 범위가 끊기지 않고 이어지는지 확인
    for idx in range(1, len(coarse)):
        assert coarse[idx]["source_start_id"] == coarse[idx - 1]["source_end_id"] + 1


def test_map_coarse_chapters_to_original_ids(tmp_path):
    summarizer = VideoSummarizer(output_dir=str(tmp_path))
    coarse_segments = [
        {"id": 1, "source_start_id": 1, "source_end_id": 4},
        {"id": 2, "source_start_id": 5, "source_end_id": 9},
        {"id": 3, "source_start_id": 10, "source_end_id": 15},
    ]
    coarse_chapters = [
        {"title": "A", "type": "Preaching_Main", "summary": "a", "start_id": 1, "end_id": 2},
        {"title": "B", "type": "Illustration", "summary": "b", "start_id": 3, "end_id": 3},
    ]

    mapped = summarizer._map_coarse_chapters_to_original(coarse_chapters, coarse_segments, total_lines=15)

    assert mapped[0]["start_id"] == 1
    assert mapped[0]["end_id"] == 9
    assert mapped[1]["start_id"] == 10
    assert mapped[1]["end_id"] == 15


def test_normalize_chapter_ranges_makes_contiguous_ranges(tmp_path):
    summarizer = VideoSummarizer(output_dir=str(tmp_path))
    raw = [
        {"title": "둘째", "type": "Preaching_Main", "summary": "2", "start_id": 8, "end_id": 12},
        {"title": "첫째", "type": "Intro_Icebreak", "summary": "1", "start_id": 1, "end_id": 5},
        {"title": "셋째", "type": "Application", "summary": "3", "start_id": 13, "end_id": 14},
    ]

    normalized = summarizer._normalize_chapter_ranges(raw, total_lines=16)

    assert normalized[0]["start_id"] == 1
    assert normalized[-1]["end_id"] == 16
    for idx in range(1, len(normalized)):
        assert normalized[idx]["start_id"] == normalized[idx - 1]["end_id"] + 1


def test_find_low_confidence_boundaries_picks_ambiguous_boundary(tmp_path):
    summarizer = VideoSummarizer(output_dir=str(tmp_path))
    summarizer.boundary_refine_context_span = 5
    summarizer.boundary_refine_min_score = 2

    segments = [
        {"id": 1, "start": 0.0, "end": 4.0, "text": "오늘 이야기 시작"},
        {"id": 2, "start": 4.0, "end": 8.0, "text": "그리고 계속 이어서"},
        {"id": 3, "start": 8.0, "end": 12.0, "text": "근데 갑자기 전환"},
        {"id": 4, "start": 12.0, "end": 16.0, "text": "또 이어지는 내용"},
    ]
    chapters = [
        {"title": "앞", "type": "Preaching_Main", "summary": "a", "start_id": 1, "end_id": 2},
        {"title": "뒤", "type": "Preaching_Main", "summary": "b", "start_id": 3, "end_id": 4},
    ]

    picked = summarizer._find_low_confidence_boundaries(chapters, segments)

    assert len(picked) == 1
    assert picked[0]["boundary_index"] == 0
    assert picked[0]["min_end_id"] <= picked[0]["current_end_id"] <= picked[0]["max_end_id"]
