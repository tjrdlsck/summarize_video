#!/bin/bash

# --- [AI Video Analyst Setup Script] ---
# 작성자: AI Agent
# 설명: 이 스크립트는 macOS 환경에서 필요한 의존성을 설치하고 서버를 실행합니다.

# 색상 코드
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== AI Video Analyst 설치 및 실행 마법사 ===${NC}"
echo "이 프로그램은 Apple Silicon (M1/M2/M3) Mac에 최적화되어 있습니다."
echo ""

# 1. Homebrew 확인 및 FFmpeg 설치
echo -e "${YELLOW}[1/5] 시스템 도구 확인 중...${NC}"

if ! command -v brew &> /dev/null; then
    echo -e "${RED}[오류] Homebrew가 설치되어 있지 않습니다.${NC}"
    echo "터미널에 다음 명령어를 입력하여 Homebrew를 먼저 설치해주세요:"
    echo '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
fi

if ! command -v ffmpeg &> /dev/null; then
    echo "FFmpeg가 없습니다. Homebrew로 설치를 시작합니다..."
    brew install ffmpeg
else
    echo "FFmpeg가 이미 설치되어 있습니다."
fi

# 2. Python 가상환경 확인 및 생성
echo -e "${YELLOW}[2/5] Python 가상환경 설정 중...${NC}"

if [ ! -d "venv" ]; then
    echo "가상환경(venv)을 생성합니다..."
    python3 -m venv venv
fi

# 가상환경 활성화
source venv/bin/activate

# 3. 의존성 패키지 설치
echo -e "${YELLOW}[3/5] 필요한 Python 라이브러리 설치 중... (시간이 좀 걸릴 수 있습니다)${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# 4. 환경 변수(.env) 설정
echo -e "${YELLOW}[4/5] 환경 변수 설정 확인...${NC}"

if [ ! -f ".env" ]; then
    echo -e "${GREEN}>>> .env 파일이 없어서 .env.example을 복사하여 생성합니다.${NC}"
    cp .env.example .env
    echo -e "${RED}!!! 중요 !!!${NC}"
    echo ".env 파일이 생성되었습니다."
    echo "Google Gemini API Key가 필요합니다."
    read -p "지금 API Key를 입력하시겠습니까? (y/n): " answer
    if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
        read -p "API Key 붙여넣기: " apikey
        # sed 명령어로 GEMINI_API_KEY 값 교체 (macOS 호환 방식)
        sed -i '' "s/GEMINI_API_KEY=.*/GEMINI_API_KEY=$apikey/" .env
        echo "API Key가 저장되었습니다."
    else
        echo "나중에 .env 파일을 직접 열어서 API Key를 수정해주세요."
    fi
else
    echo ".env 파일이 이미 존재합니다."
fi

# 5. 서버 실행
echo -e "${GREEN}[5/5] 모든 준비 완료! 서버를 시작합니다...${NC}"
echo "서버가 켜지면 브라우저에서 http://localhost:8000 으로 접속하세요."
echo "종료하려면 Ctrl+C를 누르세요."
echo ""

python run.py
