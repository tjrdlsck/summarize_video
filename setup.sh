#!/bin/bash

# --- [AI Video Analyst Setup Script] ---
# 작성자: AI Agent
# 설명: 이 스크립트는 macOS 환경에서 필요한 의존성을 설치하고 서버를 실행합니다.

# 프로젝트 저장소 주소
REPO_URL="https://github.com/tjrdlsck/summarize_video.git"

# 색상 코드
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== AI Video Analyst 설치 및 실행 마법사 ===${NC}"
echo "이 프로그램은 Apple Silicon (M1/M2/M3) Mac에 최적화되어 있습니다."
echo ""

# 1. Python3 및 Homebrew 확인
echo -e "${YELLOW}[1/5] 시스템 도구 확인 중...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[오류] Python3가 설치되어 있지 않습니다.${NC}"
    echo "https://www.python.org/ 에서 Python을 설치하거나 'brew install python'을 실행하세요."
    exit 1
fi

if ! command -v brew &> /dev/null; then
    echo -e "${RED}[오류] Homebrew가 설치되어 있지 않습니다.${NC}"
    echo "터미널에 다음 명령어를 입력하여 Homebrew를 먼저 설치해주세요:"
    echo '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
fi

# Git 확인 및 설치 추가
if ! command -v git &> /dev/null; then
    echo "Git이 없습니다. Homebrew로 설치를 시작합니다..."
    brew install git
else
    echo "Git이 이미 설치되어 있습니다."
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "FFmpeg가 없습니다. Homebrew로 설치를 시작합니다..."
    brew install ffmpeg
else
    echo "FFmpeg가 이미 설치되어 있습니다."
fi

# 2. Python 가상환경 확인 및 생성
echo -e "${YELLOW}[2/5] Python 가상환경 설정 중...${NC}"

# 에러 발생 시 즉시 중단
set -e

if [ ! -d "venv" ]; then
    echo "가상환경(venv)을 생성합니다..."
    python3 -m venv venv
fi

# 가상환경 활성화
source venv/bin/activate

# 3. 의존성 패키지 설치
echo -e "${YELLOW}[3/5] 필요한 Python 라이브러리 설치 중... (시간이 좀 걸릴 수 있습니다)${NC}"
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

# 3.5 AI 모델 사전 다운로드
if [ -f "model_down.py" ]; then
    echo -e "${YELLOW}[3.5/5] AI 모델을 사전에 다운로드 중... (최초 1회)${NC}"
    python3 model_down.py
else
    echo -e "${YELLOW}[경고] model_down.py를 찾을 수 없어 모델 다운로드 단계를 건너뜁니다.${NC}"
fi

# 에러 시 중단 옵션 해제 (이후 단계는 사용자 입력이 있으므로)
set +e

# 4. 환경 변수(.env) 설정
echo -e "${YELLOW}[4/5] 환경 변수 설정 확인...${NC}"

if [ ! -f ".env" ]; then
    echo -e "${GREEN}>>> .env 파일이 없습니다.${NC}"
    echo "Google Gemini API Key가 필요합니다."
    read -p "지금 API Key를 입력하시겠습니까? (y/n): " answer
    if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
        read -p "API Key 붙여넣기: " apikey
        echo "GOOGLE_API_KEY=\"$apikey\"" > .env
        echo "API Key가 .env 파일에 저장되었습니다."
    else
        echo ".env.example을 복사하여 기본 파일을 생성합니다."
        cp .env.example .env
        echo "나중에 .env 파일을 직접 열어서 API Key를 수정해주세요."
    fi
else
    echo ".env 파일이 이미 존재합니다."
fi

# 4.5 Git 저장소 복구 (ZIP 다운로드 사용자용)
# .git 폴더가 없다면 ZIP으로 받은 것이므로, Git 저장소로 변환하여 업데이트가 가능하게 만듭니다.
if [ ! -d ".git" ]; then
    echo -e "${YELLOW}[4.5] Git 저장소 연결 복구 중...${NC}"
    git init
    git remote add origin "$REPO_URL"
    git fetch origin
    
    # 로컬 브랜치를 생성하고 원격 브랜치와 연결 (이미 파일이 있으므로 강제 체크아웃)
    # -f를 사용하여 기존 파일들과의 충돌을 무시하고 Git 인덱스를 초기화합니다.
    git checkout -f -B main origin/main
    
    # 원격 저장소 상태와 강제로 맞춤
    git reset --hard origin/main
    
    echo -e "${GREEN}>>> 이제 이 폴더는 'git pull' 명령어로 업데이트가 가능합니다!${NC}"
fi

# 4.8 macOS 앱 번들 생성
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [ -f "make_portable_app.sh" ]; then
        echo -e "${YELLOW}[4.8/5] macOS 앱 번들(.app) 생성 중...${NC}"
        chmod +x make_portable_app.sh
        ./make_portable_app.sh
    fi
fi

# 5. 서버 실행
echo -e "${GREEN}5/5] 모든 준비 완료! 서버를 시작합니다...${NC}"
echo "서버가 켜지면 브라우저에서 http://localhost:8000 으로 접속하세요."
echo "종료하려면 Ctrl+C를 누르세요."
echo ""

python run.py