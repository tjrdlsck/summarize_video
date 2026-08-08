# Task List: Gemma 탈피 & Gemini 3.1 Flash-Lite 기반 블로그 전담 파이프라인 정돈

- [x] 구현 계획서 수립 및 사용자 승인 (`implementation_plan.md`) <!-- id: 0 -->
- [x] `services/system_manager.py`: refiner 및 planner 모델을 `gemini-3.1-flash-lite`로 교체 <!-- id: 1 -->
- [x] `services/summarizer.py`: 요약노트 Stage 2 (Reduce)에서 중복 `blog_post` 키 제거 및 챕터 요약에 경량화 집중 <!-- id: 2 -->
- [x] `services/refiner.py`: Gemma 의존성 완전 제거 및 `gemini-3.1-flash-lite` 윤문 엔진 최적화 <!-- id: 3 -->
- [x] `app/application/pipeline_runner.py`: 요약노트 챕터 재활용 고속 블로그 생성 로직 연결 <!-- id: 4 -->
- [x] 단위/통합 테스트 작성 및 실행 (`tests/test_refiner_gemini.py` 및 전체 pytest 45/45 Passed 통과 검증) <!-- id: 5 -->
