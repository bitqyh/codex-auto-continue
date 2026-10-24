#!/bin/bash
# Build the Codex Auto Continue menu bar app (macOS, native AppKit).
#
# Usage:
#   ./build.sh                # host architecture, ad-hoc signed, CLI embedded
#   ./build.sh --install      # build + copy to ~/Applications + open
#   ./build.sh --release      # universal (arm64 + x86_64) app for distribution
#
# The CLI (src/ + bin/codex-continue) is embedded in Contents/Resources/cli and
# CLIPath is bundle-relative, so the installed app does not depend on the repo
# location. Distribute the resulting .app with scripts/build_macos_release.sh.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
build="$here/build"
app="$build/CodexContinue.app"

install=0
universal=0
for arg in "$@"; do
  case "$arg" in
    --install) install=1 ;;
    --release|--universal) universal=1 ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$repo/pyproject.toml" | head -1)
if [ -z "$version" ]; then
  echo "cannot read version from pyproject.toml" >&2
  exit 1
fi

rm -rf "$build"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$build/modulecache" "$build/tmp"
export TMPDIR="$build/tmp"

compile() {
  local target=$1
  local output=$2
  swiftc -O -swift-version 5 -disable-sandbox -framework AppKit \
    -target "$target" \
    -module-cache-path "$build/modulecache" \
    -o "$output" "$here/main.swift"
}

if [ "$universal" = 1 ]; then
  echo "building universal binary for arm64 + x86_64"
  compile "arm64-apple-macos13.0" "$build/CodexContinue-arm64"
  compile "x86_64-apple-macos13.0" "$build/CodexContinue-x86_64"
  lipo -create "$build/CodexContinue-arm64" "$build/CodexContinue-x86_64" \
    -output "$app/Contents/MacOS/CodexContinue"
else
  host_arch=$(uname -m)
  compile "${host_arch}-apple-macos13.0" "$app/Contents/MacOS/CodexContinue"
fi

cp "$here/assets/AppIcon.icns" "$app/Contents/Resources/AppIcon.icns"
cp "$here/assets/"statusTemplate*.png "$app/Contents/Resources/"

# Embed the CLI so the app keeps working after the repo is moved or deleted.
mkdir -p "$app/Contents/Resources/cli/bin" "$app/Contents/Resources/cli/src"
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$repo/src/" "$app/Contents/Resources/cli/src/"
cp "$repo/bin/codex-continue" "$app/Contents/Resources/cli/bin/codex-continue"
chmod +x "$app/Contents/Resources/cli/bin/codex-continue"

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
  <key>CFBundleShortVersionString</key><string>$version</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>CLIPath</key><string>cli/bin/codex-continue</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

codesign --force --sign - "$app" >/dev/null 2>&1 || true
rm -rf "$build/modulecache" "$build/tmp"
echo "built: $app (version $version)"
if [ "$universal" = 1 ]; then
  lipo -info "$app/Contents/MacOS/CodexContinue" | sed 's/^/arch: /'
fi

if [ "$install" = 1 ]; then
  target="$HOME/Applications/CodexContinue.app"
  mkdir -p "$HOME/Applications"
  pkill -f "$target/Contents/MacOS/CodexContinue" 2>/dev/null || true
  rm -rf "$target"
  /usr/bin/ditto "$app" "$target"
  echo "installed: $target"
  open "$target"
fi
