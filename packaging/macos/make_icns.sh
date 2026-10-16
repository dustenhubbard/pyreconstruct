#!/usr/bin/env bash
# Put the app icon for this build's flavor at packaging/PyReconstruct.icns,
# where the spec reads it. Run from the repo root before PyInstaller.
#
# The .icns files beside this script hold every size macOS asks for. The 16 and
# 32 point slots carry simplified artwork that stays clear in Finder's list
# view and the Dock's smallest size, which scaling one 1024 px image down cannot
# give. Their 1024 px slots match PyReconstruct/assets/img/PyReconstruct.png and
# PyReconstructDev.png (tests/test_macos_icons.py checks).
set -euo pipefail

# The Dev flavor (packaging/FLAVOR says "dev") gets the icon with the DEV badge;
# the output path stays the same either way, since the spec reads one location.
FLAVOR="$(cat packaging/FLAVOR 2>/dev/null | tr -d '[:space:]' || true)"
if [ "$FLAVOR" = "dev" ]; then
    SRC="packaging/macos/PyReconstructDev.icns"
else
    SRC="packaging/macos/PyReconstruct.icns"
fi

mkdir -p packaging
cp "$SRC" packaging/PyReconstruct.icns
echo "wrote packaging/PyReconstruct.icns (from $SRC)"
