#!/bin/bash

# start.sh: 앱 실행의 진입점
# 이 스크립트는 프로젝트 루트에서 실행되어야 합니다.

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=== AI Video Analyst Launcher ==="

# 1. 가상환경 및 필수 라이브러리 체크
IS_READY=true
if [ ! -d "venv" ]; then
    IS_READY=false
else
    source venv/bin/activate
    # fastapi가 설치되어 있는지 확인
    if ! python3 -c "import fastapi" &> /dev/null; then
        echo "⚠️  가상환경은 있으나 라이브러리(fastapi)가 설치되지 않았습니다."
        IS_READY=false
    fi
fi

if [ "$IS_READY" = false ]; then
    echo "⚠️  초기 설정이 필요합니다. setup.sh를 실행합니다..."
    
    # setup.sh 실행 권한 확인
    if [ ! -x "./setup.sh" ]; then
        chmod +x ./setup.sh
    fi
    
    ./setup.sh
    exit 0
fi

# 2. 가상환경이 완벽하면 실행
echo "✅  실행 환경 확인 완료! 서버를 시작합니다..."
source venv/bin/activate

# run.py가 있는지 확인
if [ ! -f "run.py" ]; then
    echo "❌  오류: run.py 파일을 찾을 수 없습니다."
    read -p "엔터를 누르면 종료합니다..."
    exit 1
fi

python run.py
