#!/bin/bash

# start.sh: 앱 실행의 진입점
# 이 스크립트는 프로젝트 루트에서 실행되어야 합니다.

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=== AI Video Analyst Launcher ==="

# 1. 가상환경이 없으면 설치 진행
if [ ! -d "venv" ]; then
    echo "⚠️  가상환경(venv)이 없습니다. 초기 설치를 시작합니다..."
    
    # setup.sh 실행 권한 확인
    if [ ! -x "./setup.sh" ]; then
        chmod +x ./setup.sh
    fi
    
    ./setup.sh
    # setup.sh 마지막에 run.py가 실행되므로 여기서 종료
    exit 0
fi

# 2. 가상환경이 있으면 바로 실행
echo "✅  가상환경 발견! 서버를 시작합니다..."
source venv/bin/activate

# run.py가 있는지 확인
if [ ! -f "run.py" ]; then
    echo "❌  오류: run.py 파일을 찾을 수 없습니다."
    read -p "엔터를 누르면 종료합니다..."
    exit 1
fi

python run.py
