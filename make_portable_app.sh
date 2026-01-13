#!/bin/bash

# --- [Portable Mac App Generator v7 (Robust Icon Builder)] ---
APP_NAME="AI Video Analyst"
APP_DIR="${APP_NAME}.app"

# 1. 디렉토리 구조 최신화 (루트 폴더 Inode 보존을 위해 내부만 삭제)
if [ -d "$APP_DIR/Contents" ]; then
    rm -rf "$APP_DIR/Contents"
fi
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 2. 아이콘 처리 로직 (방어적 설계)
ASSETS_DIR="static/assets"
ICNS_PREMADE="$ASSETS_DIR/AppIcon.icns"
PNG_SOURCE="$ASSETS_DIR/icon.png"
TARGET_ICNS="$APP_DIR/Contents/Resources/AppIcon.icns"

if [ -f "$ICNS_PREMADE" ]; then
    # [우선순위 1] 미리 만들어진 .icns 파일이 있는 경우 (가장 안전)
    echo "💎 [Icon] 미리 제작된 '$ICNS_PREMADE'를 발견했습니다. 바로 적용합니다."
    cp "$ICNS_PREMADE" "$TARGET_ICNS"
elif [ -f "$PNG_SOURCE" ]; then
    # [우선순위 2] PNG만 있고 변환 도구가 있는 경우
    if command -v sips &> /dev/null && command -v iconutil &> /dev/null; then
        echo "🎨 [Icon] '$PNG_SOURCE'를 기반으로 아이콘을 자동 생성합니다..."
        ICONSET="AppIcon.iconset"
        mkdir -p "$ICONSET"
        
        # 변환 시도 (실패 시 우아하게 종료하기 위해 에러 핸들링 추가)
        {
            sips -z 16 16     "$PNG_SOURCE" --out "$ICONSET/icon_16x16.png"
            sips -z 32 32     "$PNG_SOURCE" --out "$ICONSET/icon_16x16@2x.png"
            sips -z 32 32     "$PNG_SOURCE" --out "$ICONSET/icon_32x32.png"
            sips -z 64 64     "$PNG_SOURCE" --out "$ICONSET/icon_32x32@2x.png"
            sips -z 128 128   "$PNG_SOURCE" --out "$ICONSET/icon_128x128.png"
            sips -z 256 256   "$PNG_SOURCE" --out "$ICONSET/icon_128x128@2x.png"
            sips -z 256 256   "$PNG_SOURCE" --out "$ICONSET/icon_256x256.png"
            sips -z 512 512   "$PNG_SOURCE" --out "$ICONSET/icon_256x256@2x.png"
            sips -z 512 512   "$PNG_SOURCE" --out "$ICONSET/icon_512x512.png"
            sips -z 1024 1024 "$PNG_SOURCE" --out "$ICONSET/icon_512x512@2x.png"
            iconutil -c icns "$ICONSET" -o "$TARGET_ICNS"
        } > /dev/null 2>&1
        
        rm -rf "$ICONSET"
        
        if [ -f "$TARGET_ICNS" ]; then
            echo "✅ [Icon] 아이콘 생성이 완료되었습니다."
        else
            echo "❌ [Icon] 아이콘 생성 도중 오류가 발생했습니다. 기본 아이콘을 사용합니다."
        fi
    else
        echo "⚠️  [Icon] 변환 도구(sips, iconutil)가 없어 PNG를 변환할 수 없습니다."
    fi
else
    echo "ℹ️  [Icon] 전용 아이콘 자산이 없어 시스템 기본 아이콘을 사용합니다."
fi

# 3. Info.plist 생성
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

# 4. 런처 스크립트 작성 (start.sh 호출 전용)
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
osascript <<END
tell application "Terminal"
    if not (exists window 1) then reopen
    activate
    do script "cd \"$PROJECT_ROOT\" && bash start.sh"
end tell
END
EOF

# 5. 실행 권한 부여
chmod +x "$APP_DIR/Contents/MacOS/launcher"

# 6. macOS Finder 아이콘 캐시 갱신 강제화 (필요시)
touch "$APP_DIR"

echo "✅ [심플 앱 생성 완료] '$APP_DIR'이 업데이트되었습니다."
echo "👉 'icon.png' 또는 'AppIcon.icns'를 교체하면 아이콘이 자동으로 반영됩니다."
