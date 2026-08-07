# 🛠️ Implementation Plan: LLM 환각 방지를 위한 레거시 문서 격리 및 컨벤션(OS/아키텍처/브랜치 수칙) 명시

## 1. 개요 및 목적
LLM을 활용한 바이브코딩(Vibe Coding) 시 구버전 마크다운 파일들의 지식 드라이빙(Knowledge Drift) 및 OS/디렉터리/브랜치 스코프 모호성으로 발생하는 환각(Hallucination) 현상을 차단하고자 함.

## 2. 세부 변경 사항
- **구버전 문서 아카이빙**: `docs/archive/` 폴더를 생성하고 `PRD.md`, `PROJECT_ANALYSIS.md`, `version_compatibility_analysis.md`, `frontend_version_compatibility_analysis.md`, `pr_body.md` 이동.
- **AI 탐색 노이즈 차단**: `.ignore`에 `docs/archive/` 등록.
- **컨벤션 보완**: [`CONVENTION.md`](file:///home/radi/cli/summarize_video/CONVENTION.md)에 Primary OS (Linux/macOS), Path Separator 표준, Multiprocessing 스폰 모드 주의 사항, `app/` vs `services/` 계층 명세 및 **브랜치 작업 수칙(현재 브랜치 전용, 임의 병합 금지, Commit & Push까지 진행)** 구체화.
- **검증**: `tests/test_convention_and_architecture.py`를 통한 구조 검증 단위 테스트 수행.
