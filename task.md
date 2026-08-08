# Task List: 스마트 비디오 탐색 및 파일 부재 시 즉시 오류 알림 구현

- [x] 구현 계획서 수립 및 사용자 승인 (`implementation_plan.md`) <!-- id: 0 -->
- [x] `app/application/pipeline_runner.py`: 스마트 비디오 탐색(Smart Matching) 및 비디오 부재 시 명확한 예외(`FileNotFoundError`) 및 `fail_task` 처리 <!-- id: 1 -->
- [x] `static/js/app.js`: 작업 폴링 중 실패(`failed`) 상태 전환 감지 시 사용자 알림 및 무기한 대기 차단 <!-- id: 2 -->
- [x] `static/js/components.js`: `TaskMonitor` 실패 상태 시 로그 보기 및 에러 메시지 툴팁 명확화 <!-- id: 3 -->
- [x] 단위/통합 테스트 작성 및 검증 (`tests/test_video_path_smart_matching.py` 및 전체 pytest 55/55 Passed 통과) <!-- id: 4 -->
