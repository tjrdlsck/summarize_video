#!/bin/bash

# 현재 스크립트가 있는 디렉토리로 이동 (매우 중요)
cd "$(dirname "$0")"

# setup.sh에 실행 권한 부여 (안전을 위해 한번 더 수행)
chmod +x setup.sh

# 설치 및 실행 스크립트 호출
./setup.sh
