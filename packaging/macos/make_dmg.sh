#!/usr/bin/env bash
# Build dist/PyReconstruct.app into a .dmg whose Finder window shows the app,
# a chevron, and an Applications alias to drag it onto.
# dmgbuild writes the window layout (dmg_settings.py) straight into the image's
# .DS_Store, with no AppleScript, so it works on headless CI runners
# (create-dmg's window-styling step times out there).
#   python -m pip install --require-hashes --only-binary :all: -r packaging/macos/dmg-requirements.txt
#   PYR_PUBLIC=<version> ARCH=arm64 bash packaging/macos/make_dmg.sh
set -euo pipefail

: "${PYR_PUBLIC:?set PYR_PUBLIC to the public version string}"
ARCH="${ARCH:-x86_64}"
# The Dev flavor bundles as "PyReconstruct Dev.app" and its dmg carries a
# -Dev suffix AFTER the platform tag: the in-app updater parses the version
# out of "PyReconstruct-<ver>-<platform>", so the suffix must trail both.
FLAVOR="$(cat packaging/FLAVOR 2>/dev/null | tr -d '[:space:]' || true)"
if [ "$FLAVOR" = "dev" ]; then
    APP_NAME="PyReconstruct Dev"
    GUIDE="dev"
    ICON="PyReconstruct/assets/img/PyReconstructDev.png"
    OUT="PyReconstruct-${PYR_PUBLIC}-macOS-${ARCH}-Dev.dmg"
else
    APP_NAME="PyReconstruct"
    GUIDE="stable"
    ICON="PyReconstruct/assets/img/PyReconstruct.png"
    OUT="PyReconstruct-${PYR_PUBLIC}-macOS-${ARCH}.dmg"
fi
APP="dist/${APP_NAME}.app"

[ -d "$APP" ] || { echo "error: $APP not found (build with PyInstaller first)" >&2; exit 1; }
rm -f "$OUT"

HERE="$(cd "$(dirname "$0")" && pwd)"
STAGE="$(mktemp -d)"
DEFINES=(-D "app=$APP" -D "background=$HERE/dmg-background.png")
# Render the first-launch help for the app actually included in this image.
# Only an unsigned app needs it: the guide walks users past Gatekeeper, and a
# Developer ID app opens with no extra steps once it is notarized.
SIGNATURE="$(codesign -dvv "$APP" 2>&1 || true)"
if [[ "$SIGNATURE" == *"Authority=Developer ID Application"* ]]; then
    echo "app is signed with a Developer ID; leaving out the first-launch guide"
else
    "${PYTHON:-python3}" "$HERE/render_first_launch.py" "$APP_NAME" "$GUIDE" "$ICON" \
        "$STAGE/Read Before First Launch.html"
    DEFINES+=(-D "guide=$STAGE/Read Before First Launch.html")
fi

# hdiutil create intermittently fails with "Resource busy" on CI runners when a
# stale diskimages-helper still holds a disk image. dmgbuild retries only the
# detach, so retry the whole build with cleanup + backoff.
# The volume name leaves out the version: it is the window's title.
make_dmg() {
    dmgbuild -s "$HERE/dmg_settings.py" "${DEFINES[@]}" "$APP_NAME" "$OUT"
}
for attempt in 1 2 3 4 5; do
    if make_dmg; then break; fi
    [ "$attempt" -eq 5 ] && { echo "error: dmgbuild failed after 5 attempts" >&2; exit 1; }
    echo "dmgbuild failed (attempt $attempt; likely 'Resource busy') -- cleaning up and retrying" >&2
    rm -f "$OUT"
    killall diskimages-helper 2>/dev/null || true   # release a stale helper holding the image
    sleep $((attempt * 5))
done

[ -f "$OUT" ] || { echo "error: dmgbuild did not produce $OUT" >&2; exit 1; }
echo "wrote $OUT (with drag-to-Applications alias)"
