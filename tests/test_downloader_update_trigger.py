"""Downloader yt-dlp self-heal trigger tests."""

from yt_dlp.utils import DownloadError

from services.downloader import VideoDownloader


class RaisingYDL:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, *_args, **_kwargs):
        raise DownloadError("ERROR: You should update yt-dlp to a newer version")


class GenericErrorYDL:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, *_args, **_kwargs):
        raise Exception("network timeout")


def test_download_returns_restart_required_when_update_error_detected(monkeypatch, tmp_path):
    downloader = VideoDownloader(download_dir=str(tmp_path))

    monkeypatch.setattr("services.downloader.yt_dlp.YoutubeDL", RaisingYDL)
    monkeypatch.setattr(
        downloader,
        "_attempt_ytdlp_upgrade",
        lambda: {"status": "updated", "current_version": "old", "latest_version": "new"},
    )

    result = downloader.download_from_url("https://example.com/video")

    assert result["status"] == "restart_required"
    assert "재시작" in result["message"]


def test_download_keeps_normal_error_path_for_non_update_errors(monkeypatch, tmp_path):
    downloader = VideoDownloader(download_dir=str(tmp_path))

    monkeypatch.setattr("services.downloader.yt_dlp.YoutubeDL", GenericErrorYDL)

    result = downloader.download_from_url("https://example.com/video")

    assert result["status"] == "error"
    assert "network timeout" in result["message"]
