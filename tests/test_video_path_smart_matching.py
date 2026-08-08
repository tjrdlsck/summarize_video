import os
import pytest
from unittest.mock import MagicMock
from app.application.pipeline_runner import PipelineRunner
from app.core.container import AppContainer


def test_resolve_video_path_matches_hashed_filename(tmp_path, monkeypatch):
    """요청 파일명과 달리 디렉터리에 해시가 붙어 있는 실제 파일이 존재하는 경우 스마트 탐색되는지 검증."""
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    # 실물 해시 파일 생성
    hashed_file = video_dir / "28cf4da5_sample_video.mp4"
    hashed_file.write_text("dummy video content")

    # VIDEOS_DIR 패치
    monkeypatch.setattr("app.application.pipeline_runner.VIDEOS_DIR", str(video_dir))

    runner = PipelineRunner(container=MagicMock())
    # 요청 파일명은 'sample_video.mp4' (해시 없음)
    resolved_path = runner._resolve_video_path("sample_video.mp4")

    assert os.path.exists(resolved_path)
    assert os.path.basename(resolved_path) == "28cf4da5_sample_video.mp4"


def test_resolve_video_path_raises_filenotfounderror(tmp_path, monkeypatch):
    """실물 파일이 존재하지 않는 경우 명확한 FileNotFoundError가 발생하는지 검증."""
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    monkeypatch.setattr("app.application.pipeline_runner.VIDEOS_DIR", str(video_dir))

    runner = PipelineRunner(container=MagicMock())

    with pytest.raises(FileNotFoundError) as exc_info:
        runner._resolve_video_path("non_existent_video.mp4")

    assert "찾을 수 없습니다" in str(exc_info.value)
