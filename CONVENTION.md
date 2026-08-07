# 📜 AI Video Analyst Project Coding Convention

본 문서는 프로젝트의 유지보수성, 가독성, 확장성 및 **Gemini 3.6 Flash / LLM 에이전트 바이브 코딩(Vibe Coding) 시 발생 가능한 환각(Hallucination) 방지**를 위해 작성된 표준 아키텍처 및 개발 수칙입니다. 모든 기여자와 AI 에이전트는 본 규칙을 엄격히 준수해야 합니다.

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

## 0.3 Gemini 3.6 Agentic Vibe Coding Rules (LLM 에이전트 바이브 코딩 전용 수칙)

Gemini 3.6 Flash 모델 및 AI 에이전트가 코드를 작성하거나 리팩토링할 때 필수 적용되는 강력한 실행 제약 조건(Strict Guardrails)입니다.

1. **축약 및 생략 전면 금지 (Anti-Lazy Coding Directive)**:
   - 코드 생성 시 `...`, `# rest of code`, `# 기존 코드와 동일` 등 임의의 줄임표나 생략 코드를 반환하는 것을 엄격히 금지합니다. 항상 실행 가능한 전체 코드(Full Code)를 제공해야 합니다.
2. **로그 기반 실증 진단 (Log-First Empirical Protocol)**:
   - 오류 발생 시 짐작이나 추측으로 코드를 수정하지 않습니다. 반드시 런타임 로그 및 스택 트레이스(Stack Trace)를 전량 조회하고 근본 원인(Root Cause)을 분석한 후 수정을 진행합니다.
   - 예외 상황을 은폐하는 소극적 처리(Silent `try...except`, Dummy 0-byte/Fallback 데이터 반환)를 금지합니다.
3. **실증적 테스트 기반 완결성 (Empirical Test-Driven Verification)**:
   - 파일 수정 후 반드시 `pytest` 테스트 또는 빌드 검증 명령어를 로컬에서 직접 실행하여 $100\%$ 성공을 확인하기 전까지는 작업을 완료(Done)라 선언할 수 없습니다.
4. **엄격한 타입 안전성 (Strict Type Safety & Pydantic v2)**:
   - Python 3.12+ 명시적 Type Hinting과 Pydantic v2 기반 스키마 검증을 적용하여 런타임 타입 오류 및 JSON 파싱 에러를 사전에 방지합니다.
5. **문자 단위 정확한 매칭 (Verbatim Exact Matching)**:
   - 기존 코드 수정 시 3줄 이상의 변경되지 않는 선/후 맥락을 유지하여 비동기 변경 충돌 및 구문 파괴를 방지합니다.

---

## 1. Core Engineering Principles

1. **비동기 기본 원칙 (Async-First I/O)**: FastAPI 및 I/O 바운드 작업(네트워크 API 호출, 소켓, 파일 IO)은 반드시 `async/await` non-blocking 패턴으로 작성합니다.
2. **단일 책임 원칙 (Separation of Concerns)**: 비즈니스 로직(`services/`), 데이터 스키마 (`app/schemas/`), 라우터 엔드포인트(`app/api/`)의 책임을 엄격히 구분합니다.
3. **Conventional Commits**: 커밋 메시지는 한국어로 `[feat]`, `[fix]`, `[docs]`, `[refactor]`, `[test]`, `[chore]` 커밋 타입을 준수하여 작성합니다.

---
**최종 업데이트**: 2026-08-07
**작성자**: AI Video Analyst Team (Gemini 3.6 Flash Optimization)
