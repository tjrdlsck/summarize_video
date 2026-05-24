# 크로스 플랫폼 및 동적 AI 모델 설정 구현 계획서

윈도우(Windows) 및 리눅스(Linux) 환경에서 크로스 플랫폼(Cross-platform) 지원이 강화됨에 따라, 프론트엔드 설정 창에서 맥 전용(MLX) 모델로 하드코딩(Hard-coded)되어 있는 Whisper 모델 목록과 권장 설명 문구를 현재 OS 환경에 맞춰 동적으로 노출되도록 보완하고, Google Gemini API를 직접 조회하여 최신 Gemini 및 Gemma 추천 모델 목록을 실시간으로 동적 갱신할 수 있도록 구조를 개선하는 구현 계획서입니다.

---

## 1. 문제 정의 (Problem Definition)

### 1.1 현상 분석
* **하드코딩된 Whisper 모델**: 시스템 설정 창을 열면 '🎙️ 음성 인식 (STT)' 모델 설정 목록에 Apple Silicon 전용 가속 라이브러리인 `mlx-community/...` 형태의 모델만 노출되며, 설명 부분 역시 OS 플랫폼에 무관하게 항상 `(MLX 최적화 모델 권장)`이라고 고정되어 있습니다.
* **하드코딩된 Gemini 모델**: Gemini 및 Gemma 모델 추천 목록(`GEMINI_MODELS`) 또한 프론트엔드 코드 내에 수동으로 하드코딩되어 있어, Google 측에서 새로운 모델(예: 최신 버전 출시 등)을 업데이트하더라도 코드 수정 없이는 사용자가 최신 모델을 설정 화면에서 선택할 수 없습니다.

### 1.2 원인 분석
* **프론트엔드 정적 배열 선언**: `static/js/components.js` 내에 `WHISPER_MODELS` 및 `GEMINI_MODELS` 배열이 특정 모델 리스트로 하드코딩되어 있습니다.
* **플랫폼 및 최신 API 모델 식별 정보 누락**: 프론트엔드 단에서 현재 동작하고 있는 서버의 운영체제(OS) 정보 및 Google API 측에서 실시간으로 제공하는 사용 가능한 모델 목록을 전달받지 못하고 있습니다.
* **설정 저장 인터페이스 결합도**: 프론트엔드의 `handleSave` 함수가 API로부터 전달받은 설정 객체 전체(`settings` 상태)를 `/api/settings`에 그대로 `POST` 전송하므로, 백엔드 GET API의 응답 포맷 확장 시 Pydantic 검증 오류가 발생할 우려가 있습니다.

---

## 2. 제안하는 변경 사항 (Proposed Changes)

문제를 해결하기 위해 백엔드 설정 조회 API가 현재 시스템의 플랫폼 정보, 플랫폼별 권장 Whisper 모델 목록, 그리고 Google API 조회를 통해 얻은 최신 Gemini 및 Gemma 모델 목록을 함께 반환하도록 구조를 확장하고, 프론트엔드가 이를 받아 동적으로 렌더링하고 유연하게 저장하도록 수정합니다.

### 2.1 [MODIFY] [system_manager.py](file:///home/radi/cli/summarize_video/services/system_manager.py)
* `ConfigManager` 클래스에 각 플랫폼에 맞는 권장 Whisper 모델 목록을 정의합니다:
  ```python
  # macOS (darwin) 추천 모델 목록
  DARWIN_WHISPER_MODELS = [
      "mlx-community/whisper-large-v3-turbo-q4",
      "mlx-community/whisper-large-v3-mlx-4bit"
  ]
  # Windows/Linux (Faster-Whisper) 추천 모델 목록
  OTHER_WHISPER_MODELS = [
      "large-v3-turbo",
      "large-v3",
      "medium",
      "small"
  ]
  ```
* Google GenAI API를 사용하여 사용 가능한 Gemini 및 Gemma 모델 목록을 동적으로 조회하는 `get_gemini_models()` 클래스 메서드를 추가합니다:
  - `google.genai` SDK의 `client.models.list()`를 호출합니다.
  - 응답 데이터에서 `models/` 접두사를 정제하고, `gemini` 또는 `gemma` 키워드가 들어간 모델만 필터링합니다.
  - **인메모리 캐싱(In-memory Caching)**: 매번 네트워크 호출을 방지하기 위해 간단한 클래스 수준 캐시 기법을 적용합니다.
  - **예외 처리 및 안전 장치(Fallback)**: API Key가 없거나 네트워크 오류가 발생한 경우 미리 지정한 기본 모델 목록(기존 `GEMINI_MODELS` 배열과 동일 구성)을 즉시 반환하여 UI 지연이나 에러를 차단합니다.

### 2.2 [MODIFY] [settings.py](file:///home/radi/cli/summarize_video/app/api/routers/settings.py)
* `GET /api/settings` 라우터의 응답 데이터를 확장하여 기존 설정(`models` 딕셔너리)뿐만 아니라 현재 구동 서버의 OS 종류(`platform`), 권장 Whisper 모델 목록(`whisper_models`), 그리고 실시간 조회된 `gemini_models`를 추가 메타 정보로 응답하도록 수정합니다.
  ```json
  {
    "models": {
      "summarizer": "gemini-3.1-flash",
      "planner": "gemini-3.1-flash-lite",
      "refiner": "gemma-4-31b-it",
      "shorts": "gemini-3.1-flash-lite",
      "whisper": "large-v3-turbo"
    },
    "platform": "linux",
    "whisper_models": [
      "large-v3-turbo",
      "large-v3",
      "medium",
      "small"
    ],
    "gemini_models": [
      "gemini-2.5-flash",
      "gemini-2.5-flash-lite",
      "gemini-2.5-pro",
      "gemini-3-flash",
      "gemini-3-pro",
      "gemini-3-deep-think",
      "gemma-3-27b-it",
      "gemma-3-4b-it",
      "gemma-3-12b-it"
    ]
  }
  ```

### 2.3 [MODIFY] [components.js](file:///home/radi/cli/summarize_video/static/js/components.js)
* **동적 모델 리스트 바인딩**: 하드코딩된 `WHISPER_MODELS` 및 `GEMINI_MODELS` 배열을 제거하고, `fetchSettings` 실행 시 API 결과물에서 추출한 `whisper_models` 및 `gemini_models` 배열을 React State로 관리하여 드롭다운의 추천 리스트로 동적 바인딩합니다.
* **설명 문구 동적화**: 백엔드에서 전달받은 `platform` 값이 `"darwin"`인 경우 `(MLX 최적화 모델 권장)`, 그 외의 경우 `(Faster-Whisper 가속 모델 권장)` 등 플랫폼 특이적 설명이 렌더링되도록 삼항 조건식을 작성합니다.
* **결합도 분리**: `handleSave` 시 설정 데이터 전체를 날리지 않고, 백엔드 요청 스키마(`SettingsUpdateRequest`)에 정합하도록 `{ models: settings.models }` 형태로 가공하여 `POST` 요청을 수행합니다.

### 2.4 [MODIFY] [test_cross_platform.py](file:///home/radi/cli/summarize_video/tests/test_cross_platform.py)
* `pytest` 테스트 스위트 내에 설정 API(`GET /api/settings`)가 OS 모킹 및 API 클라이언트 모킹 환경 하에서 올바른 `platform` 문자열과 추천 모델 목록(`whisper_models` 및 `gemini_models`)을 통합 반환하는지 유닛 테스트를 보완 및 추가합니다.

---

## 3. 검증 계획 (Verification Plan)

### 3.1 자동화 테스트 (Automated Tests)
* 크로스 플랫폼 시뮬레이션 및 API 응답 스키마 테스트 실행:
  ```bash
  ./venv/bin/pytest tests/test_cross_platform.py
  ```

### 3.2 수동 검증 (Manual Verification)
1. **Linux/Windows 환경 검증**:
   - 로컬 웹 서버를 기동하고 브라우저를 열어 우측 상단 설정을 클릭합니다.
   - Whisper STT 모델 선택 드롭다운에 `large-v3-turbo`, `large-v3`, `medium`, `small` 등이 정상 노출되는지 확인합니다.
   - 드롭다운 하단의 캡션 텍스트에 `(Faster-Whisper 가속 모델 권장)`으로 올바르게 표시되는지 확인합니다.
   - Gemini/Gemma 설정 드롭다운 목록에 실시간 API 조회를 통해 받아온 동적 모델 리스트가 렌더링되는지 확인합니다.
   - 모델을 변경하고 '저장'을 누른 뒤 `data/config.json` 파일에 변경한 모델이 제대로 갱신되는지 확인합니다.
2. **macOS 모킹(또는 실 Mac) 환경 검증**:
   - 백엔드를 `sys.platform == 'darwin'` 조건으로 기동하거나, Mac 장비에서 설정을 띄웁니다.
   - 드롭다운에 `mlx-community/...` 형태의 MLX 전용 모델 리스트가 표시되며, 설명에 `(MLX 최적화 모델 권장)` 문구가 나타나는지 확인합니다.
3. **API Key 미등록/네트워크 단절 환경 검증**:
   - `.env` 파일의 API Key를 주석 처리한 상태 또는 오프라인 상태에서 설정을 띄워도, 설정 조회 API가 안전하게 폴백 모델 목록을 즉각 응답하고 오류 화면이 발생하지 않는지 검증합니다.
