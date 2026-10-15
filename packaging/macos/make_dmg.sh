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
    dmgbuild -s "$HERE/dmg_settings.py" "${DEFINES[@]}" "$APP_NAME" "$OUT" && check_dmg
}

# Every path in an app bundle, sorted, with its type and a file's size or a
# link's target. A directory it cannot read is an error, not an empty one.
app_listing() {
    "${PYTHON:-python3}" - "$1" <<'PY'
import os, sys
root = sys.argv[1]
rows = []
def fail(error):
    raise error
for top, dirs, files in os.walk(root, onerror=fail):
    for name in dirs + files:
        path = os.path.join(top, name)
        rel = os.path.relpath(path, root)
        if os.path.islink(path):
            rows.append(f"link {rel} -> {os.readlink(path)}")
        elif os.path.isdir(path):
            rows.append(f"dir {rel}")
        else:
            rows.append(f"file {rel} {os.path.getsize(path)}")
print("\n".join(sorted(rows)))
PY
}

# dmgbuild copies the app with ditto but ignores its exit status, so a failed
# or partial copy still gives an image. Mount the image and check that the app
# in it has the same files, at the same sizes, as the app it came from.
check_dmg() {
    local mnt status=0
    mnt="$(mktemp -d)"
    hdiutil attach -readonly -nobrowse -noautoopen -mountpoint "$mnt" "$OUT" >/dev/null \
        || { rmdir "$mnt"; return 1; }
    if ! app_listing "$APP" >"$mnt.want" || ! [ -s "$mnt.want" ] \
        || ! app_listing "$mnt/${APP_NAME}.app" >"$mnt.got" || ! [ -s "$mnt.got" ]; then
        echo "error: could not list $APP or ${APP_NAME}.app in $OUT" >&2
        status=1
    elif ! diff "$mnt.want" "$mnt.got" >&2; then
        echo "error: ${APP_NAME}.app in $OUT does not match $APP" >&2
        status=1
    fi
    hdiutil detach "$mnt" >/dev/null || hdiutil detach -force "$mnt" >/dev/null || true
    rmdir "$mnt" 2>/dev/null || true
    rm -f "$mnt.want" "$mnt.got"
    return "$status"
}

for attempt in 1 2 3 4 5; do
    if make_dmg; then break; fi
    rm -f "$OUT"
    [ "$attempt" -eq 5 ] && { echo "error: dmgbuild failed after 5 attempts" >&2; exit 1; }
    echo "dmgbuild failed (attempt $attempt; likely 'Resource busy'). Cleaning up and retrying." >&2
    killall diskimages-helper 2>/dev/null || true   # release a stale helper holding the image
    sleep $((attempt * 5))
done

[ -f "$OUT" ] || { echo "error: dmgbuild did not produce $OUT" >&2; exit 1; }
echo "wrote $OUT (with drag-to-Applications alias)"
