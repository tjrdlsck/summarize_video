# Task List: FFmpeg GPU (NVIDIA CUDA/NVENC) 디코딩 및 렌더링 고속화 최적화

- [x] 구현 계획서 수립 및 사용자 승인 (`implementation_plan.md`) <!-- id: 0 -->
- [x] `services/clipper.py`: GPU 가속 감지 헬퍼 보완 (`cuda` hwaccel 지원 확인) <!-- id: 1 -->
- [x] `services/clipper.py`: `merge_segments` FFmpeg 입력 단에 `-hwaccel cuda` 디코딩 가속 및 `-preset p2`/`superfast` 프리셋 최적화 적용 <!-- id: 2 -->
- [x] `services/clipper.py`: `cut_video` 등 단일 클립 커팅 함수에도 GPU 가속 옵션 연동 <!-- id: 3 -->
- [x] 단위/통합 테스트 작성 및 검증 (`tests/test_clipper_gpu_acceleration.py` 및 전체 pytest 53/53 Passed 통과) <!-- id: 4 -->
