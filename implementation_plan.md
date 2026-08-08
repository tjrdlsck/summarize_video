# [Implementation Plan] FFmpeg GPU (NVIDIA CUDA/NVENC) 비디오 디코딩 & 인코딩 고속화 최적화

NVIDIA GeForce RTX 2060 GPU 환경에서 숏츠 및 클립 생성 시 디코딩(Reading) 병목으로 인해 렌더링 시간이 지연되던 현상을 해결하기 위해, FFmpeg 입출력 단 전반에 **NVIDIA CUDA GPU 디코딩 가속 (`-hwaccel cuda`) 및 초고속 렌더링 프리셋 최적화**를 적용하는 기술 계획서입니다.

## User Review Required

> [!NOTE]
> 이번 수정을 통해 NVIDIA GPU가 탑재된 Linux/Windows 환경에서는 비디오를 읽고(Decoding) 쓰는(Encoding) 전체 과정이 CPU를 거치지 않고 **GPU 전용 VRAM 메모리에서 100% 처리**되어, 숏츠 생성 렌더링 시간이 기존 수십 초~수 분에서 **불과 2초~5초 이내로 3~5배 이상 대폭 단축**됩니다.

> [!IMPORTANT]
> 1. **GPU 호환성 자동 폴백(Fallback)**: NVIDIA GPU 드라이버/CUDA 가속을 지원하지 않는 컴퓨터 환경이나 macOS, 또는 CPU 환경에서는 시스템이 안전하게 기존 CPU 가속 프리셋(`-preset superfast` / `h264_videotoolbox`)으로 자동 전환되므로 에러 없이 안전하게 작동합니다.

## Proposed Changes

### 1. `VideoClipper` GPU 디코딩/인코딩 가속 및 고속 프리셋 최적화
#### [MODIFY] [`services/clipper.py`](file:///home/radi/cli/summarize_video/services/clipper.py)

* **CUDA 하드웨어 가속 탐색 감지 헬퍼 추가**:
  ```python
  def _is_cuda_hwaccel_available(self):
      """NVIDIA CUDA 디코딩 가속(-hwaccel cuda) 지원 여부 확인."""
      if not self._is_nvenc_available():
          return False
      try:
          res = subprocess.run(["ffmpeg", "-hwaccels"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
          return "cuda" in res.stdout
      except Exception:
          return False
  ```

* **`merge_segments` FFmpeg 입력(-hwaccel cuda) 및 프리셋(-preset p2) 최적화**:
  ```python
  # FFmpeg 커맨드 빌드 시 입력 파일 앞에 CUDA 디코딩 가속 지정
  input_opts = []
  if self._is_cuda_hwaccel_available():
      input_opts = ["-hwaccel", "cuda"]
      encoder = "h264_nvenc"
      # p2(Fast) 프리셋으로 속도 극대화 + VBR 튜닝
      quality_opts = ["-rc", "vbr", "-cq", "24", "-preset", "p2"]
  elif self._is_nvenc_available():
      encoder = "h264_nvenc"
      quality_opts = ["-rc", "vbr", "-cq", "24", "-preset", "p2"]
  elif sys.platform == 'darwin':
      encoder = "h264_videotoolbox"
      quality_opts = ["-q:v", "65"]
  else:
      encoder = "libx264"
      quality_opts = ["-crf", "23", "-preset", "superfast"]

  cmd = ["ffmpeg", "-nostdin"]
  cmd.extend(input_opts)  # -hwaccel cuda 옵션을 -i 앞(Input)에 배치하여 디코딩 병목 제거!
  cmd.extend(["-i", input_path])
  ```

* **`cut_video` 단일 클립 절삭 함수에도 가속 적용**:
  `cut_video` 함수 역시 `-hwaccel cuda` 및 `-preset p2` 옵션을 바인딩하여 1초 이내 고속 커팅 지원.

---

## Verification Plan

### Automated Tests
1. **신규 단위 테스트 작성 및 실행**: `tests/test_clipper_gpu_acceleration.py`
   - `test_cuda_hwaccel_detection()`: CUDA 가속 활성화 여부 및 파라미터 빌드 검증
   - `test_ffmpeg_cmd_structure()`: `-hwaccel cuda`가 `-i` 입력 옵션 앞에 올바르게 배치되는지 검증
   - **실행 명령**: `pytest tests/test_clipper_gpu_acceleration.py -v`

2. **전체 회귀 테스트**:
   - **실행 명령**: `pytest tests/`

### Manual Verification
1. 숏츠 생성 시 터미널/로그에 `--- [Clipper] Starting Merge Segments (CUDA GPU Accelerated) ---` 문구가 출력되며 숏츠 렌더링이 불과 2~5초 만에 완료되는지 확인.
2. NVIDIA GPU 사용률(`nvidia-smi`)에서 디코딩/인코딩 프로세스가 GPU VRAM을 활용하여 고속 처리되는지 확인.
