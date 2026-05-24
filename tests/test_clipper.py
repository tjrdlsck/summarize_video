import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.clipper import VideoClipper

# pytest mark for asyncio
pytestmark = pytest.mark.anyio

@pytest.fixture
def clipper():
    return VideoClipper(temp_dir="static/temp_test")

async def test_encoder_selection_nvenc(clipper):
    """
    NVIDIA NVENC 가속(Hardware Acceleration)이 사용 가능한 환경에서 
    h264_nvenc 인코더가 올바르게 선택되는지 검증합니다.
    """
    # 1. nvidia-smi 명령어 실행 성공 모킹
    mock_nvidia_smi = MagicMock()
    mock_nvidia_smi.returncode = 0
    
    # 2. ffmpeg -encoders 명령어 실행 성공 모킹 (h264_nvenc 포함)
    mock_ffmpeg_encoders = MagicMock()
    mock_ffmpeg_encoders.returncode = 0
    mock_ffmpeg_encoders.stdout = "V..... h264_nvenc            NVIDIA NVENC H.264 encoder (codec h264)"
    
    def side_effect(cmd, *args, **kwargs):
        if "nvidia-smi" in cmd[0]:
            return mock_nvidia_smi
        elif "ffmpeg" in cmd[0] and "-encoders" in cmd:
            return mock_ffmpeg_encoders
        raise FileNotFoundError()

    # asyncio.create_subprocess_exec 비동기 실행 모킹
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.stderr = AsyncMock()
    
    # FFmpeg 스트림 파싱 루프 강제 종료를 위해 IncompleteReadError 유도
    import asyncio
    mock_process.stderr.readuntil.side_effect = asyncio.IncompleteReadError(b"", 0)
    mock_process.stderr.readline.return_value = b""

    with patch("subprocess.run", side_effect=side_effect), \
         patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        
        # 1) cut_video 검사
        await clipper.cut_video("dummy.mp4", 10.0, 20.0, output_filename="clip_nvenc.mp4")
        called_args = mock_exec.call_args[0]
        assert "h264_nvenc" in called_args
        assert "-rc" in called_args
        assert "vbr" in called_args

        # 2) merge_segments 검사
        mock_process.wait.return_value = 0
        await clipper.merge_segments("dummy.mp4", [{"start": 10.0, "end": 20.0}], output_filename="merged_nvenc.mp4")
        called_args_merge = mock_exec.call_args[0]
        assert "h264_nvenc" in called_args_merge
        assert "-rc" in called_args_merge

async def test_encoder_selection_darwin_no_nvenc(clipper, monkeypatch):
    """
    NVIDIA 가속이 불가능하고 macOS(Darwin) 환경인 경우,
    h264_videotoolbox 하드웨어 가속 인코더가 선택되는지 검증합니다.
    """
    # 1. nvidia-smi 실행 불가 모킹
    mock_nvidia_smi = MagicMock()
    mock_nvidia_smi.returncode = 127
    
    # 2. 운영체제를 macOS(darwin)로 가상 모킹
    monkeypatch.setattr(sys, "platform", "darwin")

    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.stderr = AsyncMock()
    
    import asyncio
    mock_process.stderr.readuntil.side_effect = asyncio.IncompleteReadError(b"", 0)
    mock_process.stderr.readline.return_value = b""

    with patch("subprocess.run", return_value=mock_nvidia_smi), \
         patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        
        # 1) cut_video 검사
        await clipper.cut_video("dummy.mp4", 10.0, 20.0, output_filename="clip_mac.mp4")
        called_args = mock_exec.call_args[0]
        assert "h264_videotoolbox" in called_args
        assert "-q:v" in called_args

        # 2) merge_segments 검사
        await clipper.merge_segments("dummy.mp4", [{"start": 10.0, "end": 20.0}], output_filename="merged_mac.mp4")
        called_args_merge = mock_exec.call_args[0]
        assert "h264_videotoolbox" in called_args_merge
        assert "-q:v" in called_args_merge

async def test_encoder_selection_linux_no_nvenc(clipper, monkeypatch):
    """
    NVIDIA 가속이 불가능하고 일반 Linux 환경인 경우,
    libx264 범용 소프트웨어 인코더가 자동 선택되는지 검증합니다.
    """
    # 1. nvidia-smi 실행 불가 모킹
    mock_nvidia_smi = MagicMock()
    mock_nvidia_smi.returncode = 127
    
    # 2. 운영체제를 Linux(linux)로 가상 모킹
    monkeypatch.setattr(sys, "platform", "linux")

    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.stderr = AsyncMock()
    
    import asyncio
    mock_process.stderr.readuntil.side_effect = asyncio.IncompleteReadError(b"", 0)
    mock_process.stderr.readline.return_value = b""

    with patch("subprocess.run", return_value=mock_nvidia_smi), \
         patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        
        # 1) cut_video 검사
        await clipper.cut_video("dummy.mp4", 10.0, 20.0, output_filename="clip_linux.mp4")
        called_args = mock_exec.call_args[0]
        assert "libx264" in called_args
        assert "-crf" in called_args

        # 2) merge_segments 검사
        await clipper.merge_segments("dummy.mp4", [{"start": 10.0, "end": 20.0}], output_filename="merged_linux.mp4")
        called_args_merge = mock_exec.call_args[0]
        assert "libx264" in called_args_merge
        assert "-crf" in called_args_merge
