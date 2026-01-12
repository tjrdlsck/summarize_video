# 🎥 AI Video Analyst (Mac Optimized)

유튜브 영상이나 로컬 비디오 파일을 심층 분석하여 **자막(STT), 요약, 블로그 포스팅, 그리고 AI 숏츠(Shorts)**까지 자동으로 생성해주는 올인원 도구입니다.

이 프로젝트는 **Apple Silicon (M1/M2/M3)** 칩셋의 강력한 성능을 활용하도록 최적화되어 있습니다. (MLX Whisper & Hardware Acceleration)

---

## 🚀 새로운 Mac에서 시작하기 (Getting Started)

새로운 컴퓨터(또는 동료의 컴퓨터)에서 이 프로젝트를 처음 실행하신다면, 아래 단계를 순서대로 따라주세요.

### 1. 사전 준비 (Prerequisites)
이 프로그램은 macOS 전용입니다. 터미널에 아래 명령어를 입력하여 필수 도구를 설치하세요.
(이미 설치되어 있다면 건너뛰셔도 됩니다.)

```bash
# Homebrew 설치 (Mac용 패키지 관리자)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Git 설치
brew install git
```

### 2. 프로젝트 다운로드
```bash
git clone https://github.com/tjrdlsck/summarize_video.git
cd summarize_video
```

### 3. 설치 및 실행 (자동화)

복잡한 명령어 없이, **아래 명령어 하나만 입력하면 끝입니다.**
(가상환경 생성, 패키지 설치, 서버 실행을 모두 자동으로 처리합니다.)

```bash
./start.sh
```
*   처음 실행 시: 필요한 라이브러리를 설치하느라 시간이 조금 걸릴 수 있습니다.
*   설치 도중 **Google Gemini API Key**를 입력하라는 메시지가 나오면 키를 붙여넣어 주세요.

---

## 🖥️ 'Mac 앱'으로 만들어서 사용하기 (GUI)

매번 터미널을 열기 귀찮으시다면, 진짜 앱처럼 아이콘을 더블 클릭해서 실행할 수 있습니다.

1.  앱 생성 스크립트 실행:
    ```bash
    ./make_portable_app.sh
    ```
2.  폴더 안에 생성된 **`AI Video Analyst.app`** 아이콘을 더블 클릭하세요.
3.  터미널 창이 열리면서 서버가 실행됩니다.

> **꿀팁:** 바탕화면에 아이콘을 두고 싶다면?
> 앱을 직접 옮기지 마세요! (경로가 꼬일 수 있습니다.)
> 대신 앱을 **우클릭 -> '가상본 만들기(Make Alias)'**를 한 뒤, 만들어진 가상본(화살표 아이콘)만 바탕화면으로 옮기세요.

---

## 🔑 API Key 설정 (Google Gemini)

이 프로그램은 Google의 최신 AI 모델을 사용합니다.
1.  [Google AI Studio](https://aistudio.google.com/)에서 무료 API Key를 발급받으세요.
2.  설치 과정에서 입력하지 못했다면, 프로젝트 폴더 내의 `.env` 파일을 열어 직접 수정하세요.
    ```env
    GOOGLE_API_KEY="여기에_키를_붙여넣으세요"
    ```

---

## ✨ 주요 기능 (Key Features)

*   **초고속 음성 인식 (Whisper MLX):** Apple Neural Engine을 활용하여 CPU 대비 수 배 빠른 속도로 자막을 생성합니다. (환각 제거 및 구간 보정 기술 적용)
*   **AI 챕터 분석:** Gemini 1.5 모델이 영상의 핵심 내용을 논리적으로 요약하고 구조화합니다.
*   **AI 숏츠 자동 제작:** 영상의 하이라이트 구간을 AI가 스스로 판단하여 추출하고, 모바일 비율에 맞춰 크롭합니다.
*   **블로그 포스팅:** 개발자 블로그 스타일의 기술적인 아티클을 자동으로 작성합니다.
*   **스마트 런처:** 폴더의 위치가 바뀌어도 스스로 경로를 추적하여 작동하는 지능형 실행 구조를 갖추고 있습니다.

---

## 👨‍💻 수동 설치 가이드 (Manual Setup)

자동 스크립트(`setup.sh`)가 작동하지 않거나, 직접 환경을 구성하고 싶은 개발자를 위한 가이드입니다.

1.  **FFmpeg 설치:**
    ```bash
    brew install ffmpeg
    ```
2.  **가상환경(venv) 생성 및 활성화:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  **필수 라이브러리 설치:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **환경 변수 설정:**
    `.env.example` 파일을 복사하여 `.env`로 만들고 API Key를 입력합니다.
5.  **서버 실행:**
    ```bash
    python run.py
    ```

---

## 🛠️ 기술 스택 (Tech Stack)

*   **Language:** Python 3.10+
*   **Web Framework:** FastAPI
*   **AI Model:** 
    *   STT: [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (Large-v3 Turbo)
    *   LLM: Google Gemini 1.5 Pro / Flash-Lite / Gemma 2
*   **Media Processing:** FFmpeg (Apple Videotoolbox Hardware Acceleration)