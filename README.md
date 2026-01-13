# 🎥 SermonCutter AI (Mac Optimized)

> **2026년 1월 최신 LLM 스택 대응 완료**

**SermonCutter AI**는 긴 설교 영상이나 유튜브 콘텐츠를 심층 분석하여 **자막(STT), 챕터 요약, 블로그 포스팅, 그리고 AI 숏츠(Shorts)**까지 자동으로 생성해주는 미디어 사역 최적화 올인원 도구입니다. 

본 프로젝트는 **Apple Silicon (M1/M2/M3/M4)** 칩셋의 Neural Engine 및 GPU 가속을 활용하도록 설계되었습니다. (MLX Whisper & Hardware Acceleration)

---

## 🚀 시작하기 (Getting Started)

### 1. 사전 준비 (Prerequisites)
이 프로그램은 macOS 전용입니다. 터미널(Terminal)에서 아래 도구들이 설치되어 있는지 확인하세요.

```bash
# Homebrew 설치 (패키지 관리자)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Git & FFmpeg 설치
brew install git ffmpeg
```

### 2. 설치 및 실행 (자동화)
복잡한 가상환경 설정 없이, 아래 명령어 하나로 모든 준비가 완료됩니다.

```bash
git clone https://github.com/tjrdlsck/summarize_video.git
cd summarize_video
./start.sh
```
*   **최초 실행 시:** 가상환경(`venv`) 구축 및 라이브러리 설치로 인해 수 분이 소요될 수 있습니다.
*   **API Key:** 실행 도중 [Google AI Studio](https://aistudio.google.com/)에서 발급받은 API 키 입력을 요청합니다.

---

## 🖥️ 앱(App)으로 사용하기 (GUI Mode)

터미널 입력 대신 아이콘 클릭만으로 실행하고 싶다면 다음 과정을 따르세요.

1.  **앱 생성:** `./make_portable_app.sh` 실행
2.  **실행:** 폴더 내 생성된 **`AI Video Analyst.app`** 아이콘을 더블 클릭하세요.
3.  **팁:** 앱 아이콘을 우클릭하여 **'가상본 만들기(Alias)'**를 한 후, 그 가상본만 바탕화면으로 옮겨서 사용하세요.

---

## 🛠️ 기술 스택 및 모델 현황 (2026.01)

본 프로젝트는 최신 멀티모달 AI 모델을 작업 성격에 맞게 최적화하여 사용합니다.

*   **Audio Recognition (ASR):** `mlx-whisper` (Large-v3 Turbo) - Apple 가속화 전용
*   **Video Summarizer:** `Gemini 2.5 Flash` - 고속 상황 분석 및 챕터링
*   **Blog Planner:** `Gemini 2.5 Flash-Lite` - 효율적인 구조 설계
*   **Text Refiner:** `Gemma 3 (27B-IT)` - 정교한 문체 및 윤문
*   **Shorts Selector:** `Gemini 2.5 Flash` - 하이라이트 구간 자동 추출
*   **Experimental:** `Gemini 3 Pro / Deep-Think` 모델 연동 지원

---

## ⚙️ 모델 변경 및 유지보수 (Advanced Settings)

AI 기술의 빠른 발전에 대응하기 위해, 설정창이나 설정 파일을 통해 모델을 직접 변경할 수 있습니다.

### 1. 설정 파일을 통한 변경
`data/config.json` 파일을 열어 원하는 모델명으로 수정하세요. 서버 재시작 없이 다음 작업부터 즉시 반영됩니다.

```json
{
  "models": {
    "summarizer": "gemini-3-flash",
    "planner": "gemini-2.5-flash-lite",
    "refiner": "gemma-3-27b-it",
    "shorts": "gemini-2.5-flash"
  }
}
```

### 2. 유지보수 주의사항
*   **Gemini 모델:** `gemini-` 접두사로 시작하는 모델은 Google API Key가 필요합니다.
*   **Gemma 모델:** 로컬 또는 호스팅된 엔드포인트 설정에 따라 성능이 달라질 수 있습니다.

---

## ✨ 주요 핵심 기능

*   **성경 구절 자동 감지:** 설교 중 인용되는 성경 본문을 AI가 인식하여 챕터를 자동 분류합니다.
*   **프리미어 프로(Premiere Pro) 연동:** AI가 나눈 챕터대로 컷이 나뉘어 있는 `XML` 타임라인 파일을 생성합니다.
*   **스토리텔링 블로그:** 단순 요약이 아닌, 독자가 읽기 좋은 '기사 형태'의 글을 인용구와 함께 작성합니다.
*   **지능형 런처:** 폴더 위치가 바뀌어도 스스로 경로를 추적하여 안정적으로 실행됩니다.

---

## 📄 저작권 및 라이선스 (Copyright & License)

© 2026 **SermonCutter AI Contributors**. All rights reserved.

본 프로젝트는 **[MIT License](LICENSE)**에 따라 배포됩니다. 누구나 자유롭게 소프트웨어를 사용, 복제, 수정 및 배포할 수 있으나, 소프트웨어 사용으로 인해 발생하는 결과에 대해 저작자는 어떠한 법적 책임도 지지 않습니다.

---
**Reference:**
- [Google AI Gemini Documentation](https://ai.google.dev/docs)
- [MLX Whisper GitHub](https://github.com/ml-explore/mlx-examples)
- [Apple Machine Learning Research](https://ml-explore.github.io/mlx)
