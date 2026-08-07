# 📝 Walkthrough: 레거시 문서 아카이빙 및 개발 OS/아키텍처 컨벤션 명시

## 💡 문제 정의 (Root Cause & Background)
- **증상**: LLM 기반 Vibe Coding 진행 시 루트 디렉터리의 대량 파편화된 기획/분석 문서(`PRD.md`, `PROJECT_ANALYSIS.md` 등)를 읽고 구 버전 아키텍처 코드를 제안하는 환각(Hallucination) 발상.
- **원인**: 컨텍스트 윈도우(Context Window) 내 지식 충돌(Knowledge Drift) 및 개발 대상 OS/디렉터리 계층 분리 가이드 부재.

## 🛠️ 해결 메커니즘 및 로직 수정
1. **문서 아카이빙**:
   - `docs/archive/` 경로 생성 후 구버전 마크다운 파일 5종 이동.
   - `.ignore` 파일에 `docs/archive/`를 명시하여 AI 지식 탐색 노이즈 제거.
2. **컨벤션 재정립 ([`CONVENTION.md`](file:///home/radi/cli/summarize_video/CONVENTION.md))**:
   - **`0. Development & Target Environment`**: Linux (POSIX) & macOS 타깃, `pathlib.Path` 표준화, PyTorch/Whisper Multiprocessing(`fork` vs `spawn`) 주의점 기재.
   - **`0.1 Directory Structure & Architectural Blueprint`**: `app/` (FastAPI Layered Architecture) vs `services/` (Domain Services) 분리 명세 및 계층별 개발 원칙 추가.
3. **검증**:
   - `tests/test_convention_and_architecture.py` 신규 작성 및 pytest 검증 통과.

## 🧪 테스트 결과
- Pytest 로컬 실행: `tests/test_convention_and_architecture.py` 2/2 PASSED.
