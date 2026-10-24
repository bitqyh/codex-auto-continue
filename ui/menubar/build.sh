#!/bin/bash
# Build the Codex Auto Continue menu bar app (macOS, native AppKit).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
cli="$repo/bin/codex-continue"
build="$here/build"
app="$build/CodexContinue.app"

rm -rf "$build"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$build/modulecache" "$build/tmp"
export TMPDIR="$build/tmp"

swiftc -O -swift-version 5 -disable-sandbox -framework AppKit \
  -module-cache-path "$build/modulecache" \
  -o "$app/Contents/MacOS/CodexContinue" "$here/main.swift"

cp "$here/assets/AppIcon.icns" "$app/Contents/Resources/AppIcon.icns"
cp "$here/assets/"statusTemplate*.png "$app/Contents/Resources/"

cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>CodexContinue</string>
  <key>CFBundleDisplayName</key><string>Codex Auto Continue</string>
  <key>CFBundleIdentifier</key><string>local.qyh.codex-auto-continue.menubar</string>
  <key>CFBundleExecutable</key><string>CodexContinue</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.4.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>CLIPath</key><string>$cli</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

codesign --force --sign - "$app" >/dev/null 2>&1 || true
rm -rf "$build/modulecache" "$build/tmp"
echo "built: $app"

if [ "${1:-}" = "--install" ]; then
  target="$HOME/Applications/CodexContinue.app"
  mkdir -p "$HOME/Applications"
  rm -rf "$target"
  /usr/bin/ditto "$app" "$target"
  echo "installed: $target"
  open "$target"
fi
