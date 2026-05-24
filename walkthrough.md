# 🎥 리눅스 비디오 인코더 호환성 문제 해결 및 클립 내보내기 기능 검증 완료 보고서 (Walkthrough)

프론트엔드에서 영상의 구간 잘라내기(Export) 및 AI 숏츠(Shorts) 생성 요청 시 백그라운드 태스크가 실패하거나 멈추던 문제를 분석하고 해결한 상세 내용을 디버깅 관점에서 보고합니다.

---

## 1. 디버깅 관점의 문제 분석 (Debugging & Problem Analysis)

### 1.1 최초 발견된 문제 (Symptom)
* **현상 A (클립 생성 실패)**: 프론트엔드(Front-end) UI 상에서 시작/종료 지점을 잡고 내보내기(Export)를 실행했을 때, 작업은 정상 등록되었으나 보관함 목록에 아무런 클립(Clip)도 추가되지 않았습니다.
* **현상 B (숏츠 생성 중 행(Hang) 현상)**: AI 숏츠 생성 중 1단계 숏츠 제작은 완료되었으나, 2단계 숏츠 제작 진행률이 99%에 도달한 후 더 이상 프로세스(Process)가 진행되지 않고 대기 상태로 멈추어 있었습니다.

### 1.2 근본 원인 분석 (Root Cause)
* **원인 A**: 기존 `services/clipper.py`는 윈도우(Windows) 환경을 제외한 모든 환경(`else`)에서 macOS의 하드웨어 가속기(Hardware Accelerator)인 `h264_videotoolbox` 인코더를 강제(Hard-coded)로 사용하고 있었습니다. 현재 실행 환경인 **Linux (Ubuntu)**에서는 해당 전용 코덱을 지원하지 않으므로 FFmpeg 실행이 즉시 에러로 중단되었습니다.
* **원인 B**: 백그라운드 비동기 태스크(Async Task)로 FFmpeg 프로세스를 실행할 때, **표준 입력(stdin)의 차단 및 상호작용 모드 비활성화** 처리가 생략되어 있었습니다. FFmpeg는 백그라운드 구동 시 터미널 상호작용을 처리하거나 입력 버퍼를 확인하기 위해 대기하는 경향이 있어, 인코딩이 거의 끝난 시점(99%)에 행(Hang) 현상이 일어나 무한정 대기하게 되었습니다.

---

## 2. 해결 메커니즘 (Resolution Mechanics)

이 문제를 해결하기 위해 시스템의 운영체제 및 그래픽 리소스를 유연하고 동적으로 판단하고, 백그라운드 서브프로세스 행 현상을 철저히 제어하도록 코드를 리팩토링(Refactoring) 하였습니다.

### 2.1 주요 해결 방법
1. **NVIDIA 가속기 (NVENC) 동적 감지 헬퍼 추가**:
   - `_is_nvenc_available` 메소드를 구현하여 `nvidia-smi` 명령어의 존재 여부 및 `ffmpeg -encoders` 출력 결과를 검사하여 하드웨어 가속 인코더(`h264_nvenc`)의 유효성을 실시간 판별합니다.
2. **최적의 인코더 분기 처리**:
   - **1순위 (NVIDIA NVENC 가속 가능 환경 - Windows/Linux 공통)**: 가속을 위해 `h264_nvenc` 코덱 및 VBR 인코딩 옵션을 적용합니다.
   - **2순위 (macOS 환경 - sys.platform == 'darwin')**: 기존과 동일하게 Apple 가속 인코더인 `h264_videotoolbox`를 사용합니다.
   - **3순위 (일반 Linux 등 기타 환경)**: 하드웨어 가속기가 없으므로 CPU 기반 범용 인코더인 `libx264` 및 품질 지향 CRF 옵션(`-crf 23 -preset medium`)을 활용하여 안전하게 백업합니다.
3. **FFmpeg 백그라운드 행(Hang) 현상 방지**:
   - FFmpeg 명령어 매개변수 구성 리스트에 `-nostdin` 플래그(Flag)를 명시적으로 삽입하여 상호작용형 터미널 명령 대기 모드를 완전 차단하였습니다.
   - `asyncio.create_subprocess_exec`를 통해 FFmpeg 서브프로세스를 생성하는 모든 호출부에 `stdin=asyncio.subprocess.DEVNULL` 옵션을 적용하여 표준 입력을 강제로 null 장치로 라우팅시켰습니다.

### 2.2 코드 변경 요약

#### [services/clipper.py](file:///home/radi/cli/summarize_video/services/clipper.py)
* `sys` 모듈을 가져와 환경 판별을 지원합니다.
* `_is_nvenc_available` 함수를 구현하여 하드웨어 상태를 런타임에 체크하도록 보완하였습니다.
* `cut_video` 및 `merge_segments` 내부의 인코더 선택 코드를 삼항 분기(`NVENC` -> `Darwin` -> `libx264`) 구조로 안전하게 마이그레이션(Migration) 하였습니다.
* 모든 `ffmpeg` 명령어 및 `create_subprocess_exec` 파라미터에 `-nostdin` 및 `stdin=asyncio.subprocess.DEVNULL` 처리를 완료하였습니다.

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
======================== 34 passed, 2 warnings in 9.30s ========================
```

---

## 4. 교훈 및 예방 조치 (Lessons Learned)

* **하드웨어 디펜던시의 유연한 바인딩**: 특정 하드웨어 벤더(Apple, NVIDIA)의 전용 API 및 코덱을 이용할 때는 환경 판별(`sys.platform` 또는 기능 가용성 테스트)을 선행하여 범용 소프트웨어 대체(Fallback) 로직을 갖추는 것이 강력한 크로스플랫폼(Cross-platform) 설계임을 재확인하였습니다.
* **서브프로세스 표준 입력 관리의 중요성**: 백그라운드 워커 환경에서 외부 실행 파일(CLI)을 호출할 때는 행(Hang) 현상이 일어나지 않도록 `stdin` 및 TTY 상호작용 대기 상태에 대해 예외 처리를 명시적(예: `-nostdin`, `stdin=DEVNULL`)으로 해 주어야 장애(Deadlock)를 방지할 수 있습니다.

---

# ⚙️ 프론트엔드 모델 설정 UI 크로스 플랫폼 동적화 및 최신 Gemini API 연동 완료 보고서

## 1. 디버깅 관점의 문제 분석 (Debugging & Problem Analysis)

### 1.1 최초 발견된 문제 (Symptom)
* 프론트엔드 시스템 설정 창을 열었을 때, 윈도우(Windows)나 리눅스(Linux) 운영체제임에도 불구하고 Whisper STT 모델 선택 드롭다운(Dropdown)에 맥 전용 `mlx-community/...` 모델명만 표시되었으며, 안내 문구 역시 `(MLX 최적화 모델 권장)`으로 하드코딩(Hard-coded)되어 있었습니다.
* Gemini 모델 리스트 또한 수동으로 관리되는 배열(`GEMINI_MODELS`)로 고정되어 있어, Google에서 새로운 모델 버전이 출시될 경우 사용자가 즉각 설정에서 선택할 수 없는 제한적인 상황이었습니다.

### 1.2 근본 원인 분석 (Root Cause)
* **프론트엔드의 정적인 데이터 바인딩**: `static/js/components.js` 파일 내에 `WHISPER_MODELS` 및 `GEMINI_MODELS`가 프론트엔드 코드 내 고정 변수로 선언되어 있었고, 서버 환경의 동적(OS, API) 정보가 주입되지 않았습니다.
* **설정 저장 로직 결합도**: 백엔드의 `GET /api/settings` 라우터가 설정 파일(`config.json`) 데이터만 그대로 반환하고 있었으며, `POST /api/settings` 시 프론트엔드가 상태 객체 전체를 날리므로 응답 포맷을 확장하기 까다로운 구조적 한계(Pydantic 스키마 제약)가 존재했습니다.

---

## 2. 해결 메커니즘 (Resolution Mechanics)

이 문제를 해결하기 위해 백엔드 API에서 서버 측 구동 환경 및 모델 가용성을 파악하여 프론트엔드로 전달하고, 프론트엔드에서는 이를 동적으로 렌더링하도록 완전 분리 구조(Decoupling) 기반으로 리팩토링(Refactoring) 하였습니다.

### 2.1 주요 해결 방법
1. **Google GenAI 기반 동적 Gemini 모델 로딩 (캐싱 포함)**:
   - `services/system_manager.py`의 `ConfigManager` 내에 `get_gemini_models()` 클래스 메서드를 추가하여 Google GenAI SDK를 통해 실시간 가용 모델 리스트를 조회합니다.
   - 불필요한 API 비용 및 지연율(Latency) 증가를 방지하기 위해 조회 결과를 `_cached_gemini_models` 변수에 인메모리 캐싱(In-memory Caching) 하였습니다. API Key 누락이나 네트워크 연결 오류 시 기본(Fallback) 리스트를 즉각 제공하여 안정성을 보장합니다.
2. **OS 기반 크로스 플랫폼 모델 추천**:
   - `sys.platform`을 확인하여 macOS(`darwin`) 환경인 경우 기존처럼 MLX 모델 리스트를, Linux/Windows 등에서는 Faster-Whisper(`large-v3-turbo` 등) 가속 기반 리스트를 분기하여 `get_settings` 라우터 응답 스키마에 포함시킵니다.
3. **프론트엔드 동적 렌더링 도입**:
   - `fetchSettings` 시 추가적인 메타 데이터(`platform`, `whisper_models`, `gemini_models`)를 React 상태로 할당하고 렌더링 컴포넌트에 바인딩하였습니다.
   - 저장(`handleSave`) 시 프론트엔드는 불필요한 메타 데이터를 뺀 순수 환경설정 `{ models: settings.models }` 객체만 `POST`하도록 통신 레이어를 재설계하였습니다.

---

## 3. 검증 결과 (Verification Results)

### 3.1 유닛 테스트 수행 (`tests/test_cross_platform.py`)
운영체제와 환경 변수를 모킹(Mocking)하여 API가 정상적으로 메타 데이터와 함께 안전하게 처리되는지 검증하였습니다.
* **`test_api_settings_cross_platform`**: `sys.platform` 모킹에 따라 알맞은 `platform` 문자열과 `whisper_models` 구성이 내려오는지 검증 (통과)
* **`test_gemini_models_fallback`**: `GOOGLE_API_KEY` 환경변수가 누락된 오프라인 상황에서 예외 처리 후 폴백 배열이 정상 반환되는지 검증 (통과)

---

## 4. 교훈 및 예방 조치 (Lessons Learned)
* **데이터와 뷰의 완전한 분리(Decoupling)**: 뷰(View, 프론트엔드) 내에 고정 상수를 두는 하드코딩 방식은 유지 보수성을 악화시키므로, 설정 리스트나 메타 정보는 항상 컨트롤러(Controller, 백엔드 라우터)로부터 동적으로 주입받도록 통일해야 함을 확인할 수 있었습니다.
* **외부 의존성 결합 시 방어 코드 체계화**: 외부 API(Google GenAI) 연동 로직에는 네트워크 실패나 인증 오류 등을 항시 상정하여 폴백(Fallback)이나 기본값, 메모리 캐시를 결합하여 UI 장애를 차단하는 프랙티스를 정립하였습니다.

---
### 📚 참고 자료 (References)
* [Google GenAI SDK Models List Documentation](https://github.com/google/generative-ai-python)
* [FastAPI Response Models & Pydantic Schemas](https://fastapi.tiangolo.com/tutorial/response-model/)
* [React Hooks API Reference](https://react.dev/reference/react)
* [FFmpeg NVIDIA NVENC Encoding Guide](https://trac.ffmpeg.org/wiki/HWAccelIntro#NVENC)
* [FFmpeg H.264 Video Encoding Guide](https://trac.ffmpeg.org/wiki/Encode/H.264)
* [Python sys Module Documentation](https://docs.python.org/3/library/sys.html)
