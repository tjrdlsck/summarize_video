#!/bin/bash

APP_NAME="AI Video Analyst"
APP_DIR="${APP_NAME}.app"
ICON_SOURCE="static/app_icon.png" # 아이콘으로 쓸 이미지가 있다면 여기 지정 (없으면 기본 아이콘)

# 1. 기존 앱 제거
if [ -d "$APP_DIR" ]; then
    rm -rf "$APP_DIR"
fi

# 2. 디렉토리 구조 생성
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 3. Info.plist 생성 (앱 메타데이터)
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

# 4. 실행 스크립트(launcher) 생성
# 이 스크립트는 앱 내부에서 상위 폴더의 'One-Click-Start.command'를 찾아 실행합니다.
cat > "$APP_DIR/Contents/MacOS/launcher" <<EOF
#!/bin/bash

# 앱 번들 내부 경로에서 프로젝트 루트 경로를 역추적
# Contents/MacOS -> ../../.. -> Project Root
DIR=\$(cd "\$(dirname "\$0")/../../.." && pwd)

# One-Click-Start.command 실행 (터미널 창을 띄워서 로그를 보여줌)
open -a Terminal "\$DIR/One-Click-Start.command"
EOF

# 5. 실행 권한 부여
chmod +x "$APP_DIR/Contents/MacOS/launcher"

echo "✅ '$APP_DIR' 생성이 완료되었습니다!"
echo "이제 이 아이콘을 더블 클릭하면 앱이 실행됩니다."
echo "(참고: 이 앱 파일은 프로젝트 폴더 밖으로 이동시키면 작동하지 않습니다. 바로가기처럼 사용하세요.)"
