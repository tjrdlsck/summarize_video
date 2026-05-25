# 백엔드 예외 처리 강화 및 프론트엔드 에러 로그 뷰어 구현

현재 백엔드 서비스의 예외 상황(Exception)에 대한 방어 코드가 부족하여 장애 발생 시 디버깅이 어렵습니다. 
모든 주요 모듈에 방어 코드를 추가하고, 상세 에러 로그(Traceback 포함)를 파일 및 콘솔에 기록합니다.
또한 프론트엔드에서 이러한 서버 로그를 손쉽게 수집하고 모아볼 수 있는 로그 뷰어 기능을 구현합니다.

## User Review Required

> [!IMPORTANT]
> - **API 키 마스킹 기능이 추가되었습니다.** `services/logger.py`에서 로그를 기록하기 전에 정규표현식(Regex)을 사용하여 OpenAI API 키(`sk-...`)나 Bearer 토큰 등 민감한 정보를 `***MASKED_API_KEY***`로 치환하는 로직을 적용할 예정입니다.
> 
> - 로그 파일은 하루 단위로 갱신되며(`app_YYYY-MM-DD.log`), 에러가 발생한 태스크의 경우 `task_{id}.log` 형태로 저장됩니다. 프론트엔드 뷰어에서는 이 두 가지 형태의 로그 목록을 모두 불러와 선택해서 볼 수 있도록 설계했습니다. 이 구조가 적합한지 최종 확인 부탁드립니다.

## Proposed Changes

### Backend - Defensive Logging & API

#### [MODIFY] [services/logger.py](file:///home/radi/cli/summarize_video/services/logger.py)
- **민감 정보 마스킹 (Data Masking):** 정규식을 기반으로 로깅 문자열을 사전 검사하여, API 키나 민감한 인증 토큰을 마스킹(`***MASKED***`)하는 유틸리티 함수(`mask_sensitive_info`)를 추가합니다.
- 예외 로깅 함수(`log_error_with_traceback`, `log_task_error`) 내부에 이 마스킹 로직을 연동하여, 로그 파일에 민감 정보가 기록되는 것을 원천 차단합니다.

#### [MODIFY] [services/transcriber.py](file:///home/radi/cli/summarize_video/services/transcriber.py)
#### [MODIFY] [services/summarizer.py](file:///home/radi/cli/summarize_video/services/summarizer.py)
#### [MODIFY] [services/downloader.py](file:///home/radi/cli/summarize_video/services/downloader.py)
- 각 서비스 모듈의 주요 처리 함수 내에 `try-except Exception as e` 블록을 추가합니다.
- 예외 발생 시 `services.logger`를 활용하여 오류 원인과 Traceback을 상세히 남기고, 적절한 HTTP 예외를 발생시키거나 안전하게 실패 처리하도록 수정합니다.

#### [MODIFY] [app/api/routers/system.py](file:///home/radi/cli/summarize_video/app/api/routers/system.py)
- 프론트엔드에서 로그를 조회할 수 있도록 2개의 API 엔드포인트를 추가합니다.
  - `GET /api/system/logs`: `static/logs/` 디렉토리에 있는 로그 파일 목록 반환.
  - `GET /api/system/logs/{filename}`: 특정 로그 파일의 내용 반환.

### Frontend - Error Log Viewer

#### [MODIFY] [templates/index.html](file:///home/radi/cli/summarize_video/templates/index.html)
- 화면 우측 상단(또는 설정 메뉴 근처)에 **[오류 로그 보기]** 버튼을 추가합니다.
- 로그 목록과 내용을 표시할 수 있는 **로그 뷰어 모달(Modal)** 구조를 추가합니다.

#### [MODIFY] [static/js/app.js](file:///home/radi/cli/summarize_video/static/js/app.js)
#### [MODIFY] [static/js/components.js](file:///home/radi/cli/summarize_video/static/js/components.js)
- **로그 보기 버튼 이벤트**: 클릭 시 `/api/system/logs` API를 호출하여 로그 파일 목록을 가져오고 모달을 띄웁니다.
- **파일 선택 이벤트**: 목록에서 특정 파일을 클릭하면 `/api/system/logs/{filename}` API를 호출하여 로그 상세 내용을 우측 또는 아래 영역에 출력합니다.

---
## Verification Plan

### Manual Verification
1. 임의로 백엔드 코드(`transcriber.py` 등)에 에러를 발생시키는 코드를 삽입하며, 에러 메시지에 임의의 가짜 API 키(`sk-1234567890abcdef1234567890abcdef`)를 포함시킵니다.
2. 프론트엔드에서 작업을 수행하여 에러를 유발합니다.
3. 메인 화면에서 "오류 로그 보기" 버튼을 클릭합니다.
4. 모달 창에서 최신 로그 파일을 선택합니다.
5. 로그 내용에 Traceback 정보가 출력되며, 해당 가짜 API 키가 `***MASKED_API_KEY***` 등으로 안전하게 치환되어 출력되는지 확인합니다.
