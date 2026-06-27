#!/usr/bin/env bash
# Build dist/PyReconstruct.app into a .dmg with a drag-to-Applications alias.
# Uses hdiutil (built into macOS) on a staging folder that holds the app plus an
# /Applications symlink -- no AppleScript, so it works on headless CI runners
# (create-dmg's window-styling step times out there).
#   PYR_PUBLIC=<version> ARCH=arm64 bash packaging/macos/make_dmg.sh
set -euo pipefail

: "${PYR_PUBLIC:?set PYR_PUBLIC to the public version string}"
ARCH="${ARCH:-x86_64}"
APP="dist/PyReconstruct.app"
OUT="PyReconstruct-${PYR_PUBLIC}-macOS-${ARCH}.dmg"

[ -d "$APP" ] || { echo "error: $APP not found (build with PyInstaller first)" >&2; exit 1; }
rm -f "$OUT"

STAGE="$(mktemp -d)/PyReconstruct"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"   # drag-and-drop target in the mounted dmg
cp "$(dirname "$0")/dmg-readme.txt" "$STAGE/How to open PyReconstruct.txt"  # unsigned-app first-launch help

hdiutil create -volname "PyReconstruct ${PYR_PUBLIC}" -srcfolder "$STAGE" \
    -fs HFS+ -format UDZO -ov "$OUT"

[ -f "$OUT" ] || { echo "error: hdiutil did not produce $OUT" >&2; exit 1; }
echo "wrote $OUT (with drag-to-Applications alias)"
