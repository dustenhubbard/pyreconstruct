#!/usr/bin/env bash
#
# make_appimage.sh: wrap the frozen Linux build in an AppImage.
#
# Run from the repository root after `pyinstaller packaging/PyReconstruct.spec`
# has produced dist/<app name>/. Reads packaging/FLAVOR the same way the spec
# does, so the Dev flavor gets its own app name, desktop file id, icon name and
# asset name, and installs beside the stable app without touching it.
#
#   PYR_PUBLIC=1.24.0 APPIMAGETOOL=/path/to/appimagetool \
#   APPIMAGE_RUNTIME=/path/to/runtime-x86_64 bash packaging/linux/make_appimage.sh
#
# Output: dist-assets/PyReconstruct-<version>-linux-x86_64[-Dev].AppImage
#
# The platform token is lowercase on purpose. Every updater that has shipped
# matches assets by the case-sensitive substring Windows-x86_64, macOS-arm64,
# macOS-x86_64 or Linux-x86_64, so no released client, and no AppImage built
# from this script, offers these files as an update. Teaching the updater to
# replace an AppImage is a later, deliberate change.

set -euo pipefail

: "${PYR_PUBLIC:?set PYR_PUBLIC to the version for the asset name}"
: "${APPIMAGETOOL:?set APPIMAGETOOL to the appimagetool executable}"
: "${APPIMAGE_RUNTIME:?set APPIMAGE_RUNTIME to the type2 runtime file}"
ARCH="${ARCH:-x86_64}"
OUT_DIR="${OUT_DIR:-dist-assets}"

FLAVOR="$(cat packaging/FLAVOR 2>/dev/null | tr -d '[:space:]' || true)"
if [ "$FLAVOR" = "dev" ]; then
  APP_NAME="PyReconstruct Dev"
  APP_ID="edu.utexas.synapseweb.pyreconstruct.dev"
  COMMAND="pyreconstruct-dev"
  ICON_SRC="PyReconstruct/assets/img/PyReconstructDev.png"
  SUFFIX="-Dev"
else
  APP_NAME="PyReconstruct"
  APP_ID="edu.utexas.synapseweb.pyreconstruct"
  COMMAND="pyreconstruct"
  ICON_SRC="PyReconstruct/assets/img/PyReconstruct.png"
  SUFFIX=""
fi

FROZEN="dist/$APP_NAME"
[ -x "$FROZEN/$APP_NAME" ] || { echo "error: no frozen build at $FROZEN (run PyInstaller first)" >&2; exit 1; }
[ -f "$ICON_SRC" ] || { echo "error: icon missing: $ICON_SRC" >&2; exit 1; }

APPDIR="build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/512x512/apps" \
         "$APPDIR/usr/share/mime/packages"

cp -a "$FROZEN" "$APPDIR/usr/lib/"

# AppRun: the AppImage runtime executes this with the image mounted (or
# extracted, with --appimage-extract-and-run). $APPDIR is set by the runtime;
# fall back to this script's own directory for a hand-extracted tree.
cat > "$APPDIR/AppRun" <<EOF
#!/bin/sh
HERE="\${APPDIR:-\$(dirname "\$(readlink -f "\$0")")}"
exec "\$HERE/usr/lib/$APP_NAME/$APP_NAME" "\$@"
EOF
chmod 0755 "$APPDIR/AppRun"

# The desktop entry. Exec names the launcher the curl installer creates; the
# installer rewrites Exec to that launcher's absolute path, and AppImage
# desktop integrators rewrite it to the image's own path.
DESKTOP="$APPDIR/usr/share/applications/$APP_ID.desktop"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Version=1.4
Name=$APP_NAME
GenericName=Image Reconstruction Tool
Comment=Trace and reconstruct 3D structures from serial images
Exec=$COMMAND %f
Icon=$APP_ID
Terminal=false
Categories=Science;Biology;
Keywords=reconstruct;neuron;segmentation;microscopy;electron;
StartupNotify=true
StartupWMClass=$APP_NAME
MimeType=application/x-pyreconstruct-jser;
X-AppImage-Version=$PYR_PUBLIC
EOF
cp "$DESKTOP" "$APPDIR/$APP_ID.desktop"

# Icon: the same PNG the other installers use, at the AppDir root (required by
# appimagetool), as .DirIcon (file managers' thumbnail), and in hicolor.
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png"
cp "$ICON_SRC" "$APPDIR/$APP_ID.png"
cp "$ICON_SRC" "$APPDIR/.DirIcon"

# Both flavors declare the same .jser type; the file name is per flavor so
# removing one app leaves the other's registration in place.
cp packaging/linux/pyreconstruct-mime.xml "$APPDIR/usr/share/mime/packages/$APP_ID.xml"

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$DESKTOP"
fi

mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/PyReconstruct-${PYR_PUBLIC}-linux-${ARCH}${SUFFIX}.AppImage"
rm -f "$OUT"
# --appimage-extract-and-run: the build container has no FUSE.
ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run \
  --runtime-file "$APPIMAGE_RUNTIME" --no-appstream --comp zstd \
  "$APPDIR" "$OUT"
chmod 0755 "$OUT"
ls -l "$OUT"
echo "unpacked size: $(du -sh "$APPDIR" | cut -f1)"
