#!/bin/bash

# --- [Portable Mac App Generator v5 (Modular)] ---
APP_NAME="AI Video Analyst"
APP_DIR="${APP_NAME}.app"

# 1. 디렉토리 생성 (기존 폴더가 있으면 유지하여 바로가기 보호)
# rm -rf "$APP_DIR"  <-- 가상본(Alias) 보존을 위해 삭제하지 않습니다.
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 2. Info.plist 생성
cat > "$APP_DIR/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.student.aivideoanalyst</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
EOF

# 3. 런처 스크립트 작성 (start.sh 호출 전용)
cat > "$APP_DIR/Contents/MacOS/launcher" <<'EOF'
#!/bin/bash

# 1. 경로 계산 (런처 위치 -> 프로젝트 루트)
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(cd "$DIR/../../.." && pwd)"

# 2. start.sh 유효성 검사
if [ ! -f "$PROJECT_ROOT/start.sh" ]; then
    osascript -e "display alert \"Critical Error\" message \"Missing start.sh in project folder.\\nPath: $PROJECT_ROOT\""
    exit 1
fi

# 3. 터미널 실행 (단순하고 안전한 명령어)
# 'bash start.sh'만 실행하면 됨. 복잡한 로직은 start.sh에 다 있음.
osascript <<END
tell application "Terminal"
    if not (exists window 1) then reopen
    activate
    do script "cd \"$PROJECT_ROOT\" && bash start.sh"
end tell
END
EOF

# 4. 실행 권한 부여
chmod +x "$APP_DIR/Contents/MacOS/launcher"

echo "✅ [심플 앱 생성 완료] '$APP_DIR'이 업데이트되었습니다."
echo "👉 이 앱은 단순히 'start.sh'를 호출하는 역할만 합니다."
echo "👉 실행 로직을 수정하려면 'start.sh' 파일을 열어서 수정하세요."
