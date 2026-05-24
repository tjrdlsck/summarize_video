# 대시보드 UI/UX 개편 및 폴더 기능 구현 작업 목록

## 백엔드 (Backend)
- [x] `app/schemas/requests.py`: 폴더 및 재생성 API용 Pydantic 스키마 추가
- [x] `services/downloader.py`: 파일 업로드명 중복 방지 로직 `(1), (2)` 형태로 개선
- [x] `app/api/routers/folder.py`: 폴더 관리 및 이동 API 구현 (신규 라우터)
- [x] `app/api/routers/__init__.py`: `folder_router` 라우터 등록
- [x] `app/api/routers/history.py`: 히스토리에 폴더 정보 연동되게 수정

## 프론트엔드 (Frontend)
- [x] `static/js/components.js`: `RegenerateModal` 컴포넌트 구현
- [x] `static/js/app.js`: 작업 카드 디자인 배지 형태로 변경 및 하단 불필요 버튼 제거
- [x] `static/js/app.js`: 폴더 목록 UI 및 상태 관리 구현
- [x] `static/js/app.js`: 카드 체크박스 및 플로팅 바 (다중 이동) 로직 구현
- [x] `static/js/app.js`: HTML5 Drag & Drop 이벤트 구현으로 폴더 이동 지원
- [x] `static/js/app.js`: 상세 화면(Player View) 상단에 AI 콘텐츠 재생성 버튼 연동

## 테스트 및 마무리
- [x] 로컬 환경 통합 구현 완료 (테스트 대기 중)
