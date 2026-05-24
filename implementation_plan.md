# Linux 환경의 비디오 인코더 오류 해결 및 클립 내보내기 기능 정상화 구현 계획서

프론트엔드에서 영상의 특정 구간을 잘라내어 내보내기(Export) 버튼을 눌렀을 때, 백그라운드 태스크가 즉시 에러로 실패하여 보관함에 아무것도 나타나지 않는 문제를 해결하기 위한 구현 계획서입니다.

## 1. 문제 정의 (Problem Definition)

### 1.1 현상 분석
* 사용자가 웹 인터페이스(Web Interface)에서 구간을 설정하고 '내보내기' 버튼을 클릭하면, 서버 측의 `/api/export/clip` API로 요청이 들어갑니다.
* 요청은 백그라운드 작업 큐(Background Job Queue)인 `job_queue`에 등록되며, 비동기 워커(Background Worker)인 `QueueWorker`가 이를 감지하여 `PipelineRunner.run_clip_pipeline`을 실행합니다.
* 파이프라인(Pipeline) 내부에서 `VideoClipper.cut_video`를 호출하여 실제 영상 슬라이싱(Slicing) 및 인코딩(Encoding) 작업을 수행합니다.
* 그러나 내보내기 작업이 완료되지 않고 보관함에 아무것도 나타나지 않습니다.

### 1.2 원인 분석 (Debugging perspective)
* `services/clipper.py`의 `cut_video` 및 `merge_segments` 소스 코드를 분석한 결과, 인코더(Encoder)와 품질 옵션(Quality Options)을 분기하는 로직이 아래와 같이 구현되어 있습니다.
  ```python
  if os.name == 'nt':
      # Windows: NVIDIA NVENC 가속 사용
      encoder = "h264_nvenc"
      # ...
  else:
      # macOS: Apple Silicon 가속 사용
      encoder = "h264_videotoolbox"
      # ...
  ```
* Windows가 아닐 경우(`os.name != 'nt'`), 무조건 macOS 하드웨어 가속 인코더인 `h264_videotoolbox`를 강제로 할당하고 있습니다.
* 하지만 현재 실행 환경은 **Linux(Ubuntu)**입니다. Linux 환경의 `ffmpeg`에는 `h264_videotoolbox` 하드웨어 가속기(Hardware Accelerator)가 탑재되어 있지 않으므로, 아래와 같은 FFmpeg 실행 실패 로그가 발생하며 프로세스가 중단됩니다.
  ```text
  Unknown encoder 'h264_videotoolbox'
  ```
* 이로 인해 예외(Exception)가 발생하여 `cut_video`가 실패하고, 백그라운드 작업 전체가 에러(`Clip Pipeline Failed`) 처리되어 프론트엔드에는 결과물이 노출되지 않는 현상이 발생합니다.

---

## 2. 제안하는 변경 사항 (Proposed Changes)

문제를 해결하기 위해 `sys.platform`을 활용하여 운영체제(OS)를 명확히 구분하고, **NVIDIA 그래픽 카드가 탑재된 Linux 환경** 또는 Windows 환경에서 가속 기능을 동적으로 사용할 수 있도록 NVIDIA 하드웨어 가속(NVENC) 자동 감지 로직을 추가합니다.

### 2.1 [MODIFY] [clipper.py](file:///home/radi/cli/summarize_video/services/clipper.py)
* `sys` 모듈을 임포트합니다.
* `_is_nvenc_available` 헬퍼 메소드(Helper Method)를 추가하여, 런타임에 NVIDIA GPU 가속기(`h264_nvenc`)의 작동 가능 여부를 검증합니다.
  - `nvidia-smi` 명령어가 정상 동작하는지 테스트합니다.
  - `ffmpeg -encoders` 명령어 출력을 파싱하여 `h264_nvenc` 드라이버 지원 여부를 확인합니다.
* `cut_video` 및 `merge_segments` 메소드 내의 인코더 분기 처리를 아래와 같이 수정합니다:
  - **NVIDIA NVENC 가속이 가능한 경우 (`_is_nvenc_available()` 참)**: OS 상관없이 최우선으로 `h264_nvenc` 및 고품질 VBR 인코딩 옵션(`-rc vbr -cq 24 -preset p4`)을 적용합니다.
  - **macOS 환경인 경우 (`sys.platform == 'darwin'`)**: Apple Silicon 가속 인코더인 `h264_videotoolbox` 및 품질 옵션(`-q:v 65`)을 적용합니다.
  - **그 외 일반 Linux 환경 (NVIDIA 무장착 등)**: CPU 기반 범용 인코더인 `libx264` 및 품질 옵션(`-crf 23 -preset medium`)을 적용합니다.

### 2.2 [NEW] [test_clipper.py](file:///home/radi/cli/summarize_video/tests/test_clipper.py)
* 각 환경(NVIDIA NVENC 지원 환경, macOS 환경, 일반 Linux 환경)에 맞게 비디오 인코더 분기 및 FFmpeg 명령어 인자들이 올바르게 구성되는지 검증하기 위한 유닛 테스트(Unit Test)를 작성합니다.
* `subprocess.run` 및 운영체제 관련 속성들을 모킹(Mocking)하여, 논리적 분기가 올바르게 결정되는지 테스트합니다.

### 2.3 [MODIFY] [.gitignore](file:///home/radi/cli/summarize_video/.gitignore)
* 규칙에 의거하여 `.gitignore` 파일의 설정을 점검하고, `venv/`, `__pycache__/`, `.env`, `test_results/`가 확실하게 무시(Ignore) 대상에 등재되어 있는지 확인 및 보완합니다.

---

## 3. 검증 계획 (Verification Plan)

### 3.1 자동화 테스트 (Automated Tests)
* 새로 생성한 유닛 테스트 실행:
  ```bash
  ./venv/bin/pytest tests/test_clipper.py
  ```
* 전체 테스트 스위트 실행:
  ```bash
  ./venv/bin/pytest
  ```

### 3.2 수동 검증 (Manual Verification)
* 로컬 개발 서버 구동 후, 프론트엔드 웹 인터페이스에서 자르기(Cut) 기능 테스트:
  - 브라우저를 열고 영상을 선택하여 특정 구간(예: 10초 ~ 20초)을 설정합니다.
  - '내보내기' 버튼을 클릭한 뒤, 상단 '진행 중인 작업(Active Tasks)'에 진행률(Progress)이 정상적으로 10% ~ 100%까지 변화하는지 확인합니다.
  - 완료 후 '클립 보관함(Clips Library)'에 해당 클립 목록이 정상적으로 업데이트되고, ZIP 다운로드 기능이 동작하는지 검증합니다.

---
### 📚 참고 자료 (References)
* [FFmpeg NVIDIA NVENC Encoding Guide](https://trac.ffmpeg.org/wiki/HWAccelIntro#NVENC)
* [FFmpeg H.264 Video Encoding Guide](https://trac.ffmpeg.org/wiki/Encode/H.264)
* [Python sys Module Documentation](https://docs.python.org/3/library/sys.html)
