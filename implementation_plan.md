# 📐 [Implementation Plan] Gemma 탈피 & Gemini 3.1 Flash-Lite 기반 블로그 파이프라인 정돈 및 중복 생성 제거

## 💡 개요 (Goal Description)
현재 시스템은 **요약노트(`summarize_map_reduce`)**와 **블로그 뷰(`refine_chapter`)**가 각각 스토리텔링 블로그 포스팅을 중복으로 집필하는 구조적인 비효율이 존재합니다. 또한 레거시 오픈소스 소형 모델인 `gemma-4-26b-a4b-it`가 일부 남아있어 처리 속도가 느리고 인용구/HTML 강조 지침 오차가 발생하는 문제가 있습니다.

본 작업은:
1. **Gemma 모델을 완전히 제거**하고, 챕터 세부 윤문/블로그 전담 모델을 **`gemini-3.1-flash-lite`**로 교체합니다.
2. **역할 분담 및 중복 제거**:
   - **요약노트(`summary.json`)**: 영상 타임라인 챕터 구분 및 챕터별 핵심 요약(`summary`) 생성에 집중하여 경량화.
   - **블로그 뷰(`blog_view.json`)**: `gemini-3.1-flash-lite`가 블로그 포스팅 원고 작성을 단독 전담.
3. 기존 요약노트의 챕터 구조를 재활용하여 블로그 생성을 **5배 이상 속도를 향상**시킵니다.

---

## ⚠️ 검토 필요 항목 (User Review Required)

> [!NOTE]
> **하위 호환성 유지**: `{video_name}_summary.json` 내의 챕터 정보(`chapters`) 구조는 기존과 100% 동일하게 보존되며, 스토리텔링 블로그 포스팅 원고는 `{video_name}_blog_view.json`에 전담 배치됩니다.

> [!TIP]
> **API Quota 최적화**: 
> - Reduce(요약) & Shorts: `gemini-3.5-flash-lite` (독립 500 RPD 쿼터)
> - Map & Refine(블로그): `gemini-3.1-flash-lite` (독립 500 RPD 쿼터)
> - 쿼터가 철저히 5:5로 분산되어 하루 100개 이상의 비디오를 무리 없이 처리 가능합니다.

---

## 🛠️ 변경 제안 사항 (Proposed Changes)

### 1. [`services/system_manager.py`](file:///home/radi/cli/summarize_video/services/system_manager.py)
#### [MODIFY] `services/system_manager.py`
- `DEFAULT_CONFIG` 내 `"refiner"` 모델 라우팅을 `"gemma-4-26b-a4b-it"`에서 **`"gemini-3.1-flash-lite"`**로 변경.

```python
# DEFAULT_CONFIG 변경 예시
"models": {
    "transcriber": "whisper-large-v3",
    "summarizer_map": "gemini-3.1-flash-lite",
    "summarizer_reduce": "gemini-3.5-flash-lite",
    "planner": "gemini-3.1-flash-lite",
    "refiner": "gemini-3.1-flash-lite",  # Gemma 탈피 -> Gemini 3.1 Flash-Lite 라우팅
    "shorts": "gemini-3.5-flash-lite"
}
```

---

### 2. [`services/summarizer.py`](file:///home/radi/cli/summarize_video/services/summarizer.py)
#### [MODIFY] `services/summarizer.py`
- `summarize_map_reduce()` 내 Stage 2 Reduce 단계의 `response_schema` 및 프롬프트에서 `blog_post` 항목을 제거하고 챕터 분류 및 요약(`chapters`)에만 경량화 집중.

```python
# Stage 2 Reduce response_schema 경량화 예시
response_schema = {
    "type": "OBJECT",
    "properties": {
        "chapters": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "type": {"type": "STRING", "enum": profile.summary_type_enum},
                    "summary": {"type": "STRING"},
                    "start_id": {"type": "INTEGER"},
                    "end_id": {"type": "INTEGER"}
                },
                "required": ["title", "type", "summary", "start_id", "end_id"]
            }
        }
    },
    "required": ["chapters"]
}
```

---

### 3. [`services/refiner.py`](file:///home/radi/cli/summarize_video/services/refiner.py)
#### [MODIFY] `services/refiner.py`
- `TextRefiner` 클래스의 Gemma 관련 잔재 코드 정리.
- `gemini-3.1-flash-lite` 기반 고속 챕터 윤문 및 블로그 집필 로직 보강.

```python
# TextRefiner 내 모델 호출 및 프롬프트 최적화
response = self._call_gemini_with_retry(
    client=self.client,
    model=self._get_model(), # gemini-3.1-flash-lite
    contents=prompt,
    config=types.GenerateContentConfig(
        temperature=0.2,
        top_p=0.95
    )
)
```

---

### 4. [`app/application/pipeline_runner.py`](file:///home/radi/cli/summarize_video/app/application/pipeline_runner.py)
#### [MODIFY] `app/application/pipeline_runner.py`
- `run_blog_pipeline()` 실행 시, 이미 생성된 `summary.json` 내 챕터가 있으면 중복 구조 기획(`plan_blog_structure`)을 생략하고 곧바로 `refine_chapter`로 고속 병렬 윤문하도록 단축.

---

## 🧪 검증 계획 (Verification Plan)

### 1. 자동화 테스트 (Automated Tests)
- **신규 단위 테스트 작성**: `tests/test_refiner_gemini.py`
  - `TextRefiner`가 `gemini-3.1-flash-lite`를 올바르게 불러와 마크다운/HTML 태그를 올바르게 윤문하는지 Mock 검증.
- **전체 pytest 슈트 실행**:
  ```bash
  ./venv/bin/pytest tests/
  ```
  - 기존 43개 테스트 + 신규 테스트 포함 **전체 Pass (100%)** 확인.

### 2. 수동 검증 (Manual Verification)
- 대시보드 UI에서 영상 요약 실행 시 `summary.json` 및 `blog_view.json` 생성을 각각 확인하여 중복 집필이 제거되고 속도가 5배 이상 향상되었는지 확인.
