# 📜 AI Video Analyst Project Coding Convention

본 문서는 프로젝트의 유지보수성, 가독성, 확장성 및 **LLM 바이브코딩(Vibe Coding) 시 발생 가능한 환각(Hallucination) 방지**를 위해 Google과 Meta의 엔지니어링 표준을 바탕으로 작성된 코드 및 아키텍처 규칙입니다. 모든 기여자와 AI 에이전트는 본 규칙을 엄격히 준수해야 합니다.

---

## 0. Development & Target Environment (개발 및 타깃 환경)

본 프로젝트의 개발 및 배포 표준 타깃 환경은 다음과 같습니다. OS 관련 구문 작성 시 호환성에 각별히 유의해야 합니다.

- **Primary OS**: **Linux (Ubuntu / POSIX compliant)** 및 **macOS (Apple Silicon)**
- **Python Version**: Python 3.12+
- **Path Separation**: 파일 경로 처리 시 항상 `pathlib.Path` 또는 POSIX 스타일 (`/`)을 사용합니다. (Windows 전용 `\\` 하드코딩 또는 OS 특정 종속 구문 금지)
- **Multiprocessing**: Linux 환경에서는 `fork`, macOS/Windows 환경에서는 `spawn` 모드가 적용되므로 CUDA context 생성 및 sub-process 관리에 주의해야 합니다.

---

## 0.1 Directory Structure & Architectural Blueprint (디렉터리 구조 및 아키텍처 명세)

프로젝트 내 코드와 모듈은 아래 계층 분리 원칙(Separation of Concerns, SoC)을 반드시 준수하여 배치해야 합니다.

```
summarize_video/
├── app/                      # [Core App] FastAPI 웹 애플리케이션 및 계층형 아키텍처
│   ├── api/routers/          # HTTP REST API 엔드포인트 라우터 (Media, Tasks, History 등)
│   ├── application/          # 비즈니스 오케스트레이션 및 파이프라인 (pipeline_runner.py, worker.py 등)
│   └── core/                 # 의존성 주입(DI Container), 경로 설정(paths.py), 시스템 바인딩
├── services/                 # [Domain Services] 순수 비즈니스 로직 / 단일 기능 수행 전용 모듈
│   ├── transcriber.py        # STT (Whisper) 자막 추출 로직
│   ├── summarizer.py         # LLM (Gemini/Claude) 요약 로직
│   ├── clipper.py            # FFmpeg 하이라이트 영상 클리핑 로직
│   └── ...
├── tests/                    # [Testing Protocol] Pytest 기반 자동화 테스트 코드 (Git 수록 필수)
├── docs/archive/             # [Archived Docs] 아카이빙된 레거시 분석/기획 마크다운 문서
└── static/                   # [Static Assets] 정적 파일 및 로그/결과 산출물 (Git 추적 제외)
```

### 계층별 개발 규칙:
1. **API 계층 (`app/api/routers/`)**: HTTP 요청 처리 및 입력 검증(`app/schemas/`)만 담당하며, 직접 비즈니스 로직을 구현하지 않고 Application/Service 계층을 호출합니다.
2. **파이프라인 계층 (`app/application/`)**: 여러 Domain Service들을 순차적/비동기적으로 연결하여 전체 영상 요약 작업을 실행하고 진행 상황(`progress.py`)을 추적합니다.
3. **도메인 서비스 계층 (`services/`)**: 외부에 의존하지 않는 독립적인 단일 비즈니스 로직(STT, 요약, 클리핑 등)을 제공합니다.
4. **아카이브 문서 (`docs/archive/`)**: 레거시 PRD, 기획서, 호환성 분석 문서는 이 폴더에 격리하여 LLM 탐색 시 지식 오염을 방지합니다.

---

## 0.2 Branch Scope & Execution Workflow (브랜치 스코프 및 작업 수칙)

개발자 및 AI 에이전트는 코드 수정 및 작업 진행 시 아래 수칙을 엄격히 준수해야 합니다.

- **현재 브랜치 작업 원칙 (Current Branch Only)**: 사용자의 별도 명시적 요청이 없는 한, 모든 기능 개발, 문서 수정 및 리팩토링은 **현재 활성화된 Feature 브랜치 내에서만** 수행합니다.
- **임의 병합 금지 (No Autonomous Merging)**: 작업이 완료되더라도 상위 브랜치(`develop`, `main`)로의 **Merge(병합) 작업을 임의로 진행하지 않습니다.**
- **작업 완료 기준 (Completion Criteria)**: 
  1. 현재 브랜치 상에서 로컬 테스트(`pytest`) 통과 검증
  2. 규격에 맞는 **Commit** 작성
  3. 원격 리포지토리로 **Push** 및 PR 등록까지만 완료하고 최종 병합은 사용자의 지시를 기다립니다.

---

## 1. Python Style Guide (PEP 8 & Google Style)

Python 코드는 가독성이 최우선입니다. $O(1)$의 가독성을 목표로 합니다.

### 1.1 명명 규칙 (Naming Convention)
- **Classes**: `PascalCase` (예: `VideoSummarizer`)
- **Functions & Variables**: `snake_case` (예: `run_analysis_pipeline`, `video_path`)
- **Constants**: `UPPER_SNAKE_CASE` (예: `MAX_RETRIES`, `DEFAULT_MODEL_NAME`)
- **Private Members**: Leading underscore 사용 (예: `_internal_process`)

### 1.2 타입 힌팅 (Type Hinting)
모든 함수 정의에는 반드시 Python 3.9+의 Type Hinting을 적용합니다. 이는 정적 분석을 통해 버그를 사전에 방지하기 위함입니다.
```python
def process_data(input_path: str, threshold: float = 0.5) -> dict[str, Any]:
    ...
```

### 1.3 문서화 (Docstrings)
함수와 클래스에는 **Google Style Docstring**을 작성합니다.
```python
def summarize(self, segments: list[dict], video_filename: str) -> dict:
    """Gemini API를 사용하여 영상 자막을 요약합니다.

    Args:
        segments: 분석된 자막 세그먼트 리스트.
        video_filename: 원본 영상 파일명.

    Returns:
        요약 결과와 챕터 정보가 담긴 딕셔너리.
    """
```

---

## 2. JavaScript & Frontend Convention

웹 프론트엔드는 모던 ES6+ 문법을 따르며, 선언적인(Declarative) 코드 작성을 지향합니다.

- **Variable Declarations**: `var` 사용 금지. `const`를 기본으로 하되, 재할당이 필요한 경우에만 `let` 사용.
- **Arrow Functions**: 익명 함수나 콜백에서는 화살표 함수(`=>`) 사용 권장.
- **DOM Access**: Direct DOM 조작을 최소화하고, 데이터 중심의 렌더링을 지향.
- **Naming**: `camelCase` 사용 (예: `videoPlayer`, `handleButtonClick`).

---

## 3. Asynchronous Programming (Async/Await)

FastAPI와 현대적 JS의 핵심은 비동기 처리입니다.
- **Non-blocking**: I/O 바운드 작업(API 호출, 파일 읽기/쓰기)은 반드시 `async`와 `await`를 사용합니다.
- **Error Handling**: 모든 비동기 호출은 `try...except` (Python) 또는 `try...catch` (JS) 블록으로 감싸서 예외 상황에 대비합니다.

---

## 4. Git Commit Message (Conventional Commits)

커밋 메시지는 작업의 의도를 명확히 전달해야 합니다. 아래의 형식을 따릅니다.

`type: description`

- **feat**: 새로운 기능 추가
- **fix**: 버그 수정
- **docs**: 문서 수정 (CONVENTION.md, README.md 등)
- **style**: 코드 포맷팅, 세미콜론 누락 등 (로직 변경 없음)
- **refactor**: 코드 리팩토링
- **test**: 테스트 코드 추가
- **chore**: 빌드 업무, 패키지 매니저 설정 등

---

## 5. Software Engineering Principles

1.  **DRY (Don't Repeat Yourself)**: 중복되는 로직은 반드시 함수나 클래스로 추상화합니다.
2.  **KISS (Keep It Simple, Stupid)**: 복잡한 로직보다는 명확하고 단순한 로직을 선호합니다.
3.  **Separation of Concerns (SoC)**: 비즈니스 로직(Services), 데이터 접근(Models), 인터페이스(API/UI)를 엄격히 분리합니다.

---
**최종 업데이트**: 2026-08-07
**작성자**: AI Video Analyst Team
