# 작업 추적 (Task Tracker)

- [x] `services/system_manager.py` 수정
  - `ConfigManager` 클래스에 플랫폼별 Whisper 모델 추천 목록(`DARWIN_WHISPER_MODELS`, `OTHER_WHISPER_MODELS`) 추가
  - `ConfigManager`에 `get_gemini_models()` 추가하여 Google GenAI API로 동적 모델 조회 기능 구현 (캐싱 및 예외 처리 포함)
- [x] `app/api/routers/settings.py` 수정
  - `get_settings()` 함수에서 추가 메타 정보(`platform`, `whisper_models`, `gemini_models`) 반환하도록 확장
- [x] `static/js/components.js` 수정
  - 정적 `WHISPER_MODELS`, `GEMINI_MODELS` 배열 제거
  - `fetchSettings` 시 추가된 정보(`platform`, 모델 리스트)를 React State에 설정
  - 드롭다운 `suggestions`에 동적 리스트 바인딩
  - `platform` 에 따른 캡션 문구 분기 처리
  - `handleSave` 동작 시 API 스키마에 맞게 `{ models: settings.models }` 객체로 감싸서 POST
- [x] `tests/test_cross_platform.py` 작성/보완
  - OS 모킹 상황과 모델 목록 모킹 상태에서 `/api/settings`의 구조가 올바른지 검증
- [x] 수동 테스트 및 검증
  - 웹브라우저 동작 확인 및 API 호출 검증
- [x] `walkthrough.md` 작성 및 최종 PR 가이드라인 정리
