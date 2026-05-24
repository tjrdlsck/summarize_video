# 동영상 구간 자르기 오디오 유실 버그 수정 작업 목록 (Task List)

- [x] `services/clipper.py` 내의 `cut_video` 메서드 수정 (FFmpeg 옵션 순서 및 시간 표현식 변경)
- [x] `tests/test_clipper_audio_leak.py` 테스트 코드를 완성하여 처음 및 중간 자르기 시 오디오 보존 및 볼륨 검증
- [x] 유닛 테스트 실행 및 검증
  - [x] `tests/test_clipper.py` (기존 인코더 모킹 테스트)
  - [x] `tests/test_clipper_audio_leak.py` (신규 볼륨 검증 테스트)
- [x] `walkthrough.md` 수정 내용 반영 및 디버깅 결과 문서화
- [x] Git 커밋 및 원격 저장소 푸시
- [x] GitHub PR 생성 (`develop` 브랜치 기준)
