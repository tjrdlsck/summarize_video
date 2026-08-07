# 📝 Walkthrough: Gemini 3.6 Flash Vibe Coding 맞춤형 컨벤션 재정립

## 💡 문제 정의 (Root Cause & Background)
- **증상**: 기존 컨벤션에 LLM이 이미 인지하고 있는 기초 PEP 8 명명 규칙이 포함되어 토큰을 낭비하고 어텐션(Attention)을 희석시킴. 또한 Vibe Coding 중 코드 축약(`...`), 추측 기반 수정, 테스트 미검증 완료 선언 등의 에이전틱 부작용 가능성 존재.
- **원인**: 최신 Gemini 3.6 Flash 모델 특성을 반영한 강한 에이전틱 제약 조건(Strict Agentic Directives)의 부재.

## 🛠️ 해결 메커니즘 및 로직 수정
1. **기초 가이드 슬림화**:
   - 사전 학습된 일반적 명명 규칙을 정제하여 핵심 비즈니스 아키텍처 규칙으로 토큰 경량화.
2. **`0.3 Gemini 3.6 Agentic Vibe Coding Rules` 신설 ([`CONVENTION.md`](file:///home/radi/cli/summarize_video/CONVENTION.md))**:
   - 코드 축약 전면 금지 (Full Code 제공 강제).
   - 실증적 로그 우선 분석 (Log-First Protocol).
   - 로컬 테스트(`pytest`) $100\%$ 통과 전 완료 선언 금지.
   - Pydantic v2 및 Python 3.12 Type Hinting 적용.
3. **검증**:
   - `tests/test_convention_and_architecture.py` 단위 테스트 2/2 PASSED 통과.

## 🧪 테스트 결과
- Pytest 로컬 실행: `tests/test_convention_and_architecture.py` 2/2 PASSED.
