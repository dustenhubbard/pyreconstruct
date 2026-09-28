#!/usr/bin/env bash
# Sign a frozen .app with a Developer ID and the hardened runtime, as
# notarization requires. Signs from the inside out: every loose Mach-O file,
# then every nested .framework as a bundle, then the app itself with the
# entitlements. codesign --deep is not used because it cannot give nested
# code its own flags and Apple advises against it for distribution.
#   IDENTITY=<sha1 or name> bash packaging/macos/sign_app.sh "dist/PyReconstruct.app"
set -euo pipefail

APP="${1:?usage: sign_app.sh <path to .app>}"
: "${IDENTITY:?set IDENTITY to the Developer ID Application identity}"
ENTITLEMENTS="$(dirname "$0")/entitlements.plist"
TIMESTAMP="${TIMESTAMP---timestamp}"   # TIMESTAMP=--timestamp=none for an offline test

sign() { codesign --force --options runtime $TIMESTAMP --sign "$IDENTITY" "$@"; }

# Deepest paths first, so a parent is always signed after what it holds.
by_depth() { awk -F/ '{ print NF "\t" $0 }' | sort -rn | cut -f2-; }

# Every nested Mach-O file is independent of the others, and each signature
# waits on Apple's timestamp server, so they are signed 8 at a time.
MACHO="$(mktemp)"
find "$APP/Contents" -type f ! -path "$APP/Contents/MacOS/*" -print0 \
    | xargs -0 file --no-pad -0 \
    | perl -ne 'print "$1\0" if /^(.*)\0: .*Mach-O/' > "$MACHO"
COUNT="$(tr -cd '\0' < "$MACHO" | wc -c | tr -d ' ')"
xargs -0 -P 8 -n 16 codesign --force --options runtime $TIMESTAMP --sign "$IDENTITY" < "$MACHO"
rm -f "$MACHO"
echo "signed $COUNT nested Mach-O files"

COUNT=0
while IFS= read -r fw; do
    sign "$fw"
    COUNT=$((COUNT + 1))
done < <(find "$APP/Contents" -type d -name '*.framework' | by_depth)
echo "signed $COUNT frameworks"

sign --entitlements "$ENTITLEMENTS" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
echo "signed $APP"
