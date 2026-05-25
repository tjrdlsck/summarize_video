# 백엔드 예외 처리 강화 및 프론트엔드 에러 로그 뷰어 구현 결과

## 💡 변경 사항

### 1. 로깅 마스킹 파이프라인 구축 (`services/logger.py`)
- **문제 정의**: 기존 시스템에서는 예외 발생 시 스택 트레이스 및 에러 메시지에 OpenAI API 키나 JWT 기반의 Bearer 인증 토큰이 평문으로 로깅되어 파일에 저장될 수 있는 보안 취약점이 있었습니다.
- **해결 로직**: 
  - 정규표현식(Regex)을 이용해 로깅 전 평문 문자열을 검사하고 민감 정보를 안전한 문자열(`***MASKED_API_KEY***` 등)로 치환하는 `mask_sensitive_info` 유틸리티 함수를 구현했습니다.
  - `log_error_with_traceback` 및 `log_task_error` 등 로깅 엔트리포인트에 마스킹을 강제로 적용하여, 콘솔 및 로그 파일에 기록되기 직전에 안전하게 필터링되도록 처리했습니다.

### 2. 백엔드 방어 코드 전면 적용 (`services/transcriber.py`, `summarizer.py`, `downloader.py`)
- **문제 정의**: 핵심 워크플로우(다운로드 -> 자막 생성 -> 요약)를 관장하는 모듈 내에서 예상치 못한 I/O 에러나 외부 API 오류 발생 시 예외가 적절히 로깅되지 않거나 Silent Fail이 발생할 수 있었습니다.
- **해결 로직**:
  - 각 모듈 내 주요 비즈니스 함수들(`save_uploaded_file`, `download_from_url`, `summarize` 등)에 광범위한 `try-except Exception as e` 블록을 도입했습니다.
  - 예외 발생 시 커스텀 로거 유틸리티(`log_task_error`, `log_error_with_traceback`)를 호출하여 트레이스백 상세 내용을 기록하도록 변경했습니다. 

### 3. API 기반 로그 조회 엔드포인트 구현 (`app/api/routers/system.py`)
- **문제 정의**: 개발자나 운영자가 에러를 확인하기 위해 매번 서버 SSH에 접속하여 로그 파일을 찾아봐야 하는 번거로움이 있었습니다.
- **해결 로직**:
  - `/api/system/logs`: `static/logs/` 내의 모든 로그 파일을 읽어와 크기(KB) 및 최근 수정 시간(Modified) 순으로 정렬하여 반환하는 API를 구현했습니다.
  - `/api/system/logs/{filename}`: 특정 파일의 Raw Text를 반환하는 API를 구현하였으며, Path Traversal(예: `../`) 공격을 방어하는 보안 코드를 포함시켰습니다.

### 4. 프론트엔드 통합 (React + Tailwind CSS)
- **문제 정의**: 추가된 로그 API를 화면단에서 시각적으로 직관적이게 활용할 수 있는 UI가 없었습니다.
- **해결 로직**:
  - `app.js`: 애플리케이션 상단 헤더의 설정 아이콘 옆에 **[오류 로그 보기]** 버튼을 배치하고 연동 상태(State)를 추가했습니다.
  - `components.js`: `LogViewerModal` React 컴포넌트를 신규 개발했습니다. 왼쪽에는 파일 목록을 렌더링하고, 클릭 시 우측의 뷰어 패널(Console 느낌의 검은 배경 `bg-gray-900` 및 녹색 텍스트 `text-green-400`)에 트레이스백 전문을 출력하도록 하여 디버깅 편의성을 극대화했습니다.

## 🧪 테스트 및 향후 방지 (Lessons Learned)
- **로컬 검증**: 일부러 에러를 유발하는 코드 조각과 가짜 API Key 구조를 포함시켜 테스트한 결과, 정상적으로 에러가 Catch되어 파일 시스템에 보존되며 모달 뷰어에서도 API Key가 안전하게 블라인드 처리(`***MASKED***`)되는 것을 검증했습니다.
- **개발 관점의 인사이트**: 파이썬의 로깅 모듈을 래핑(Wrapping)할 때는 항상 모든 입력 파라미터를 문자열로 파싱하기 전에 필터링(Masking) 계층을 선행해야 함을 재확인했습니다. 

이로써 에러 감지부터 로깅, 그리고 시각적 모니터링까지 전체 루프(Loop)를 갖추었습니다.
