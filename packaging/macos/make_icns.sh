#!/usr/bin/env bash
# Generate packaging/PyReconstruct.icns from the app logo (macOS only; uses the
# system `sips` + `iconutil`). Run from the repo root before PyInstaller.
set -euo pipefail

# The Dev flavor (packaging/FLAVOR says "dev") gets the dark-glass icon; the
# output path stays the same either way, since the spec reads one location.
FLAVOR="$(cat packaging/FLAVOR 2>/dev/null | tr -d '[:space:]' || true)"
if [ "$FLAVOR" = "dev" ]; then
    SRC="PyReconstruct/assets/img/PyReconstructDev.png"
else
    SRC="PyReconstruct/assets/img/PyReconstruct.png"
    [ -f "$SRC" ] || SRC="PyReconstruct/assets/img/logo.png"
fi

WORK="$(mktemp -d)"
ICONSET="$WORK/PyReconstruct.iconset"
mkdir -p "$ICONSET"

for s in 16 32 64 128 256 512; do
    d=$((s * 2))
    sips -z "$s" "$s" "$SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z "$d" "$d" "$SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done

mkdir -p packaging
iconutil -c icns "$ICONSET" -o packaging/PyReconstruct.icns
rm -rf "$WORK"
echo "wrote packaging/PyReconstruct.icns"
