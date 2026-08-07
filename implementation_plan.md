# 🛠️ Implementation Plan: Gemini 3.6 Flash Vibe Coding 맞춤형 컨벤션 재정립

## 1. 개요 및 목적
Gemini 3.6 Flash 모델의 100만 토큰 컨텍스트 및 에이전틱 작업 특성에 맞춰 불필요한 기초 문법 가이드를 슬림화(Token Pruning)하고, 바이브 코딩(Vibe Coding) 시 환각을 차단하는 5대 코어 에이전틱 수칙(Agentic Directives)을 추가함.

## 2. 세부 변경 사항
- **기초 문법 슬림화**: 사전 학습된 PEP 8 및 ES6 기초 명명 규칙을 축소하여 불필요한 어텐션 희석(Attention Dilution) 방지.
- **Section 0.3 신설 (`Gemini 3.6 Agentic Vibe Coding Rules`)**:
  1. *Anti-Lazy Coding Directive* (코드 줄임표 `...` 사용 금지 및 Full Code 작성)
  2. *Log-First Empirical Protocol* (추측 진단 금지 및 로그 기반 수정)
  3. *Empirical Verification* (pytest 실행을 통한 런타임 지표 확인 전 완료 선언 금지)
  4. *Strict Type Safety* (Python 3.12 Type Hinting & Pydantic v2 준수)
  5. *Verbatim Exact Matching* (코드 교체 시 선/후 맥락 유지)
- **검증**: `tests/test_convention_and_architecture.py`를 통한 구조 검증 단위 테스트 가동 (2/2 PASSED).
