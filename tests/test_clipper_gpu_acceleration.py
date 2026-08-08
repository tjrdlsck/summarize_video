import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.clipper import VideoClipper

# pytest mark for anyio
pytestmark = pytest.mark.anyio

def test_cuda_hwaccel_detection():
    """_is_cuda_hwaccel_available 메서드가 시스템 환경에 따라 정확히 탐색되는지 검증."""
    clipper = VideoClipper()

    # NVENC 미지원 시 CUDA 탐색도 False
    with patch.object(clipper, "_is_nvenc_available", return_value=False):
        assert clipper._is_cuda_hwaccel_available() is False

    # NVENC 지원 + ffmpeg -hwaccels 에 cuda 존재 시 True
    mock_run = MagicMock()
    mock_run.stdout = "Hardware acceleration methods:\ncuda\nvaapi\n"
    with patch.object(clipper, "_is_nvenc_available", return_value=True), \
         patch("subprocess.run", return_value=mock_run):
        assert clipper._is_cuda_hwaccel_available() is True


async def test_merge_segments_cuda_input_opts():
    """CUDA 하드웨어 디코딩 가속이 활성화되었을 때 FFmpeg 명령어에 -hwaccel cuda 가 포함되는지 검증."""
    clipper = VideoClipper()
    segments = [{"start": 10.0, "end": 20.0}]

    with patch.object(clipper, "_is_cuda_hwaccel_available", return_value=True), \
         patch("asyncio.create_subprocess_exec") as mock_exec:
        
        mock_proc = MagicMock()
        mock_proc.stderr.readline = AsyncMock(side_effect=[b"", b""])
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        await clipper.merge_segments("dummy_input.mp4", segments, "output.mp4")

        # subprocess_exec에 전달된 명령어 args 검증
        args = mock_exec.call_args[0]
        cmd_str = " ".join(args)
        assert "-hwaccel cuda" in cmd_str
        assert "-c:v h264_nvenc" in cmd_str
        assert "-preset p2" in cmd_str
