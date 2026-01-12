# 📜 AI Video Analyst Project Coding Convention

본 문서는 프로젝트의 유지보수성, 가독성 및 확장성을 극대화하기 위해 Google과 Meta의 엔지니어링 표준을 바탕으로 작성된 코드 규칙입니다. 모든 기여자는 본 규칙을 엄격히 준수해야 합니다.

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
**최종 업데이트**: 2025-12-26
**작성자**: AI Video Analyst Team (Gemini CLI)
