## 💡 변경 사항
- 쇼츠 클립 고아 파일 완전 삭제(Deep Cleanup) 메커니즘 도입 (`app/api/routers/history.py`, `app/application/cleanup.py`)
- 프론트엔드 Babel 로드 에러 방지를 위한 7.x 버전 고정 (`templates/index.html`)
- 요약 노트 `<mark>` 마크다운 렌더링 버그 수정 (`services/refiner.py`, `services/summarizer.py`)

## 🧪 테스트 및 CI
- [x] 로컬 테스트 통과 (`tests/` 실행)
- [ ] CI 파이프라인 통과 여부 (Github Actions)
- (참고: `test_results/` 폴더는 .gitignore 처리됨)

Closes #108
