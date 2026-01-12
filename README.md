# 🎥 AI Video Analyst (Mac Optimized)

유튜브 영상이나 로컬 비디오 파일을 심층 분석하여 **자막(STT), 요약, 블로그 포스팅, 그리고 AI 숏츠(Shorts)**까지 자동으로 생성해주는 올인원 도구입니다.

이 프로젝트는 **Apple Silicon (M1/M2/M3)** 칩셋의 강력한 성능을 활용하도록 최적화되어 있습니다. (MLX Whisper & Hardware Acceleration)

---

## 🚀 10초 만에 시작하기 (Super Easy Mode)

터미널 명령어가 낯설다면 이 방법을 사용하세요!

### 1. 프로젝트 다운로드
```bash
git clone https://github.com/tjrdlsck/summarize_video.git
```
(또는 우측 상단 `Code` -> `Download ZIP` 후 압축 해제)

### 2. 더블 클릭으로 실행
폴더 안에 있는 **`One-Click-Start.command`** 파일을 더블 클릭하세요.
자동으로 설치가 진행되고 서버가 실행됩니다.

> **Tip:** 처음 실행 시 "확인되지 않은 개발자가..." 경고가 뜬다면?
> 파일을 **마우스 우클릭** -> **열기**를 선택한 후, 팝업창에서 **열기**를 누르면 됩니다. (Mac 보안 정책)

---

## 💻 터미널로 실행하기 (Developer Mode)

```bash
cd summarize_video
./setup.sh
```

---

## ✨ 주요 기능 (Key Features)

1.  **초고속 음성 인식 (Whisper MLX):** Apple Neural Engine을 활용하여 기존 Whisper보다 압도적으로 빠른 속도로 자막을 생성합니다. (환각 제거 및 구간 보정 기술 적용)
2.  **AI 영상 분석 및 요약:** Google Gemini 1.5 Pro/Flash 모델을 사용하여 영상의 핵심 내용을 챕터별로 요약합니다.
3.  **블로그 포스팅 자동화:** 분석된 내용을 바탕으로 가독성 좋은 기술 블로그 스타일의 글을 작성해 줍니다.
4.  **AI 숏츠 자동 제작:**
    *   영상의 하이라이트 구간을 AI가 스스로 판단하여 추출합니다.
    *   세로 화면(9:16) 크롭이 아닌, 원본 비율을 유지하며 모바일 친화적인 숏츠 영상을 생성합니다.
    *   자막(.srt/.vtt)까지 자동으로 입혀줍니다.
5.  **클립 편집기:** 사용자가 원하는 구간을 직접 잘라서 저장하거나 다운로드할 수 있습니다.

---

## 🛠️ 기술 스택 (Tech Stack)

*   **Language:** Python 3.10+
*   **Web Framework:** FastAPI
*   **AI Model:** 
    *   STT: [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (Large-v3 Turbo)
    *   LLM: Google Gemini 1.5 Pro / Flash-Lite / Gemma 2
*   **Media Processing:** FFmpeg (with Apple Videotoolbox Hardware Acceleration)

---

## ⚠️ 주의 사항

*   이 프로그램은 **macOS (Apple Silicon)** 환경에서만 정상 작동합니다. (Intel Mac이나 Windows에서는 `mlx` 라이브러리 호환성 문제가 발생할 수 있습니다.)
*   실행을 위해서는 [Google AI Studio](https://aistudio.google.com/)에서 발급받은 API Key가 필요합니다.

---

## 👨‍💻 개발자 가이드 (Manual Setup)

수동으로 설치하고 싶다면 아래 절차를 따르세요.

1. **FFmpeg 설치:** `brew install ffmpeg`
2. **가상환경 생성:** `python3 -m venv venv && source venv/bin/activate`
3. **패키지 설치:** `pip install -r requirements.txt`
4. **환경 변수 설정:** `.env.example`을 `.env`로 변경하고 API Key 입력
5. **실행:** `python run.py`