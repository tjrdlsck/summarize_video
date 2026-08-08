import os
import pytest
from services.downloader import VideoDownloader

# pytest mark for anyio
pytestmark = pytest.mark.anyio


async def test_finalize_upload_success(tmp_path):
    """비동기 finalize_upload 가 임시 청크 파트 파일을 정상적으로 최종 파일로 결합하는지 검증."""
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    downloader = VideoDownloader(download_dir=str(video_dir))

    # 임시 part 파일 생성
    identifier = "test_chunk_123"
    part_file = video_dir / f"{identifier}.part"
    part_file.write_text("chunk content data")

    # finalize_upload 비동기 호출
    res = await downloader.finalize_upload(identifier, "sample_video.mp4")

    assert res["status"] == "success"
    assert os.path.exists(res["file_path"])
    assert res["filename"] == "sample_video.mp4"
    assert not os.path.exists(str(part_file))


async def test_finalize_upload_missing_part(tmp_path):
    """임시 part 파일이 미존재할 때 에러 dict가 반환되는지 검증."""
    video_dir = tmp_path / "videos"
    video_dir.mkdir()

    downloader = VideoDownloader(download_dir=str(video_dir))

    res = await downloader.finalize_upload("missing_id", "sample.mp4")

    assert res["status"] == "error"
    assert "찾을 수 없습니다" in res["message"]
