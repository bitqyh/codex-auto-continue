#!/bin/bash
# Build the macOS release artifact (ad-hoc signed universal app inside a dmg).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
version=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$repo/pyproject.toml" | head -1)
if [ -z "$version" ]; then
  echo "cannot read version from pyproject.toml" >&2
  exit 1
fi

"$repo/ui/menubar/build.sh" --release

app="$repo/ui/menubar/build/CodexContinue.app"
if [ ! -d "$app" ]; then
  echo "missing app bundle: $app" >&2
  exit 1
fi

arch=$(lipo -info "$app/Contents/MacOS/CodexContinue")
echo "$arch"
case "$arch" in
  *arm64*) ;;
  *) echo "warning: arm64 missing from release build" >&2 ;;
esac
case "$arch" in
  *x86_64*) ;;
  *) echo "warning: x86_64 missing from release build" >&2 ;;
esac

codesign --verify --deep --strict "$app"
echo "codesign: ok (ad-hoc)"

mkdir -p "$repo/dist"
dmg="$repo/dist/CodexContinue-$version-macOS.dmg"
rm -f "$dmg"
hdiutil create -volname "Codex Auto Continue" -srcfolder "$app" -ov -format UDZO "$dmg" >/dev/null
hdiutil verify "$dmg" >/dev/null
echo "built: $dmg"
shasum -a 256 "$dmg" | sed 's/^/sha256: /'
