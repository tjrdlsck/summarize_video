# 🎥 리눅스 비디오 인코더 호환성 문제 해결 및 클립 내보내기 기능 검증 완료 보고서 (Walkthrough)

프론트엔드에서 영상의 구간 잘라내기(Export) 요청 시 백그라운드 태스크가 실패하여 클립 보관함에 결과가 노출되지 않던 문제를 분석하고 해결한 상세 내용을 디버깅 관점에서 보고합니다.

---

## 1. 디버깅 관점의 문제 분석 (Debugging & Problem Analysis)

### 1.1 최초 발견된 문제 (Symptom)
* 프론트엔드(Front-end) UI 상에서 시작/종료 지점을 잡고 내보내기(Export)를 실행했을 때, 작업은 정상 등록되었으나 보관함 목록에 아무런 클립(Clip)도 추가되지 않았습니다.
* 백엔드(Back-end) 서버의 로그 추적 결과, `QueueWorker`에 의해 트리거된 `run_clip_pipeline` 연산 중 `clipper.cut_video` 내부에서 FFmpeg 서브프로세스가 비정상 종료(Exit Code != 0)되며 예외(Exception)를 전파한 것이 확인되었습니다.

### 1.2 근본 원인 분석 (Root Cause)
* 기존 `services/clipper.py`는 윈도우(Windows) 환경을 제외한 모든 환경(`else`)에서 macOS의 하드웨어 가속기(Hardware Accelerator)인 `h264_videotoolbox` 인코더를 강제(Hard-coded)로 사용하고 있었습니다.
* 하지만 사용자 환경은 **Linux (Ubuntu)**였으며, 리눅스 커널 및 설치된 FFmpeg는 해당 애플 실리콘 전용 코덱을 인지하지 못합니다. 이에 따라 `Unknown encoder 'h264_videotoolbox'` 에러가 발생하며 비디오 자르기 작업이 최종 실패하게 되었습니다.

---

## 2. 해결 메커니즘 (Resolution Mechanics)

이 문제를 해결하기 위해 시스템의 운영체제 및 그래픽 리소스를 유연하고 동적으로 판단하도록 코드를 리팩토링(Refactoring) 하였습니다.

### 2.1 주요 해결 방법
1. **NVIDIA 가속기 (NVENC) 동적 감지 헬퍼 추가**:
   - `_is_nvenc_available` 메소드를 구현하여 `nvidia-smi` 명령어의 존재 여부 및 `ffmpeg -encoders` 출력 결과를 검사하여 하드웨어 가속 인코더(`h264_nvenc`)의 유효성을 실시간 판별합니다.
2. **최적의 인코더 분기 처리**:
   - **1순위 (NVIDIA NVENC 가속 가능 환경 - Windows/Linux 공통)**: 가속을 위해 `h264_nvenc` 코덱 및 VBR 인코딩 옵션을 적용합니다.
   - **2순위 (macOS 환경 - sys.platform == 'darwin')**: 기존과 동일하게 Apple 가속 인코더인 `h264_videotoolbox`를 사용합니다.
   - **3순위 (일반 Linux 등 기타 환경)**: 하드웨어 가속기가 없으므로 CPU 기반 범용 인코더인 `libx264` 및 품질 지향 CRF 옵션(`-crf 23 -preset medium`)을 활용하여 안전하게 백업합니다.

### 2.2 코드 변경 요약

#### [services/clipper.py](file:///home/radi/cli/summarize_video/services/clipper.py)
* `sys` 모듈을 가져와 환경 판별을 지원합니다.
* `_is_nvenc_available` 함수를 구현하여 하드웨어 상태를 런타임에 체크하도록 보완하였습니다.
* `cut_video` 및 `merge_segments` 내부의 인코더 선택 코드를 삼항 분기(`NVENC` -> `Darwin` -> `libx264`) 구조로 안전하게 마이그레이션(Migration) 하였습니다.

---

## 3. 검증 결과 (Verification Results)

### 3.1 유닛 테스트 수행 (`tests/test_clipper.py`)
운영체제 및 가속 장치 가용 환경을 모킹(Mocking)한 3개의 핵심 유닛 테스트를 신규 작성하여 검증하였습니다.
* **`test_encoder_selection_nvenc`**: NVIDIA 장치가 활성화된 경우 `h264_nvenc` 사용 여부 검증 (통과)
* **`test_encoder_selection_darwin_no_nvenc`**: Darwin 환경에서 `h264_videotoolbox` 사용 여부 검증 (통과)
* **`test_encoder_selection_linux_no_nvenc`**: 일반 리눅스 환경에서 `libx264` 사용 여부 검증 (통과)

```bash
$ ./venv/bin/pytest tests/test_clipper.py
============================== 3 passed in 0.03s ===============================
```

### 3.2 전체 테스트 회귀 검사 (`pytest`)
* 기존 설교 요약, 청크 정리, 자막 처리 로직 등 총 34개의 전체 테스트 스위트를 수행하여 아무런 부작용(Side Effect)이 발생하지 않았음을 확인하였습니다.

```bash
$ ./venv/bin/pytest
======================== 34 passed, 2 warnings in 5.71s ========================
```

---

## 4. 교훈 및 예방 조치 (Lessons Learned)

* **하드웨어 디펜던시의 유연한 바인딩**: 특정 하드웨어 벤더(Apple, NVIDIA)의 전용 API 및 코덱을 이용할 때는 환경 판별(`sys.platform` 또는 기능 가용성 테스트)을 선행하여 범용 소프트웨어 대체(Fallback) 로직을 갖추는 것이 강력한 크로스플랫폼(Cross-platform) 설계임을 재확인하였습니다.

---
### 📚 참고 자료 (References)
* [FFmpeg NVIDIA NVENC Encoding Guide](https://trac.ffmpeg.org/wiki/HWAccelIntro#NVENC)
* [FFmpeg H.264 Video Encoding Guide](https://trac.ffmpeg.org/wiki/Encode/H.264)
* [Python sys Module Documentation](https://docs.python.org/3/library/sys.html)
