# 🔍 버전 호환성 및 잠재적 장애 지점 분석 보고서 (Version Compatibility Analysis)

본 보고서는 프로젝트의 패키지 종속성(Dependencies), API 버전, 외부 시스템 의존성으로 인해 런타임(Runtime) 시 발생할 수 있는 치명적인 장애 지점을 진단한 결과입니다.

---

## 1. Google Gemini 가상/미지원 모델 버전 지정에 따른 API 오류 위험
*   **위치:** `services/system_manager.py` ([ConfigManager.DEFAULT_CONFIG](file:///home/radi/cli/summarize_video/services/system_manager.py#L14-L22))
*   **근본 원인 (Root Cause):**
    `DEFAULT_CONFIG`에 `"gemini-3.1-flash-lite"`, `"gemma-4-26b-a4b-it"`, `"gemini-2.5-flash"` 등 현재 실질적으로 사용이 불가능하거나 아직 공식 지원되지 않는 미래/가상의 모델 버전이 기본 모델로 등록되어 있습니다.
    `get_gemini_models`가 API 통신 에러로 인해 폴백(Fallback) 모드로 진입할 때 반환하는 `default_models` 목록 또한 `gemini-3-flash`, `gemma-3-*` 등 공식 서비스 여부가 불확실한 모델명을 포함하고 있습니다.
*   **장애 메커니즘 (Failure Mechanism):**
    실제 사용자가 애플리케이션을 구동하여 요약, 기획(Planner), 리파이닝(Refiner) 태스크를 시작할 때, `google-genai` SDK는 구글 서버에 해당 가상 모델명으로 요청을 보냅니다. 이에 구글 API Gateway는 `404 Not Found` 혹은 `APIError`를 반환하며 호출 즉시 파이프라인 전체가 크래시(Crash)를 일으키게 됩니다.

---

## 2. NumPy 2.x 메이저 버전 도입에 따른 라이브러리 바이너리 비호환성 위험
*   **위치:** `requirements.txt` / `requirements_win.txt` ([numpy==2.3.5](file:///home/radi/cli/summarize_video/requirements.txt#L38))
*   **근본 원인 (Root Cause):**
    NumPy 2.x 버전은 NumPy 1.x 버전 대비 C API 수준에서 파괴적인 변경(Breaking Changes)을 포함하고 있습니다. `numba==0.63.1`, `librosa==0.11.0`, `faster-whisper==1.1.0` 등은 C/C++ 기반 컴파일 바인딩(Binary Extension)을 사용하여 사전에 빌드되거나 온더플라이(On-the-fly) 컴파일을 수행합니다.
*   **장애 메커니즘 (Failure Mechanism):**
    사용자가 Whisper 추론 워커(`run_whisper_worker`)를 실행할 때, NumPy 2.x 바이너리 레이아웃이 기존 라이브러리들의 예상 구조와 일치하지 않아 `ValueError: numpy.dtype size changed, may indicate binary incompatibility` 또는 `ImportError`가 발생하며 음성 인식 프로세스가 즉각 비정상 종료될 위험이 상존합니다.

---

## 3. 유튜브 스크레핑 정책 변화 및 `yt-dlp` 권한 부족에 따른 업그레이드 실패 위험
*   **위치:** `services/downloader.py` ([_attempt_ytdlp_upgrade](file:///home/radi/cli/summarize_video/services/downloader.py#L73-L103))
*   **근본 원인 (Root Cause):**
    유튜브는 크롤링 차단 및 서명 생성 알고리즘(JS Challenge)을 수시로 갱신하기 때문에 `yt-dlp` 버전이 노후화되면 즉시 다운로드가 차단됩니다. 코드에 자가 업그레이드 수단(`pip install --upgrade yt-dlp`)이 구현되어 있지만, 이는 파일 시스템 및 런타임 권한 상태에 크게 의존합니다.
*   **장애 메커니즘 (Failure Mechanism):**
    컨테이너 배포 환경(Docker)이나 쓰기 권한이 제한된 공유 가상환경(`venv`)에서 구동될 시, `_attempt_ytdlp_upgrade` 내부의 `subprocess` 명령이 권한 부족(`PermissionError`)으로 실패하게 됩니다. 결과적으로 `yt-dlp` 업그레이드가 차단되어 유튜브 비디오 다운로드 실패 에러를 영구적으로 유발하게 됩니다.

---

## 4. FFmpeg 시스템 의존성 누락에 따른 예외 처리 구조적 한계
*   **위치:** `services/transcriber.py` ([_convert_to_16k_wav](file:///home/radi/cli/summarize_video/services/transcriber.py#L303-L362))
*   **근본 원인 (Root Cause):**
    음성 주파수 인식을 위해 원본 동영상에서 오디오를 16kHz Mono WAV 포맷으로 변환할 때 시스템의 `ffmpeg` 바이너리에 전적으로 의존합니다.
*   **장애 메커니즘 (Failure Mechanism):**
    애플리케이션을 구동하는 호스트 환경(Host Environment)에 FFmpeg가 설치되어 있지 않거나 환경 변수(`PATH`) 설정이 누락된 경우, `subprocess.Popen`이 실행되는 즉시 `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'` 예외를 던지며 자막 변환 파이프라인 전체가 강제 중단됩니다.
