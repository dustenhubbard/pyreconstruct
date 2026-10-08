# Packaging PyReconstruct (PyInstaller)

This directory builds the one-click desktop installers. It produces a frozen
app with PyInstaller, which is then wrapped per platform (Windows: Inno Setup;
macOS: `.dmg`). When the signing secrets exist, CI signs the macOS app with a
Developer ID and the hardened runtime, then signs, notarizes, and staples the
dmg (`macos/sign_app.sh` and the build workflow), so it opens with only the
usual prompt for a download. A build without the secrets, such as a fork's, is
unsigned: macOS refuses it until the quarantine attribute is cleared (see the
macOS section). The Windows installer is unsigned, so users get an "unknown
publisher" SmartScreen warning (click *More info → Run anyway*).

| File | Purpose |
|------|---------|
| `PyReconstruct.spec` | PyInstaller build recipe (one-folder) |
| `rthook_qt.py` | Runtime hook: clears a stale Qt plugin path |
| `smoke_test.py` | Headless import + offscreen VTK render check |
| `windows/PyReconstruct.iss` | Inno Setup installer script *(to be added)* |
| `macos/make_icns.sh`, `macos/make_dmg.sh` | macOS icon + dmg |
| `macos/sign_app.sh`, `macos/entitlements.plist` | Developer ID signing with the hardened runtime |

## Prerequisites

- **Python 3.11**, the version the installers are built and tested on.
- The project installed into that environment, which also generates
  `PyReconstruct/_version.py` (read by the frozen app for its version):

  ```
  pip install -e .          # or: uv sync
  pip install pyinstaller
  ```

## Build

### Windows (do this first for the POC)

```bat
:: from the repo root, in the 3.11 env
set QT_QPA_PLATFORM=offscreen
python packaging\smoke_test.py
pyinstaller --noconfirm packaging\PyReconstruct.spec
:: -> dist\PyReconstruct\PyReconstruct.exe
```

Then sanity-check the build by launching `dist\PyReconstruct\PyReconstruct.exe`:
the welcome series should load (assets), the **3D viewport should render** (VTK),
and "convert to scaled zarr" should run (the frozen subprocess dispatch).

Measure the bundle size before quoting it to anyone:
`du -sh dist/PyReconstruct` (or check folder properties on Windows).

### macOS (after Windows works)

```bash
bash packaging/macos/make_icns.sh        # generates packaging/PyReconstruct.icns
pyinstaller --noconfirm packaging/PyReconstruct.spec
# -> dist/PyReconstruct.app
python -m pip install --require-hashes --only-binary :all: -r packaging/macos/dmg-requirements.txt
bash packaging/macos/make_dmg.sh
```

`make_dmg.sh` lays out the dmg window with `dmgbuild` (`dmg_settings.py`):
the app, a chevron, and the Applications alias. The background images come
from `make_dmg_background.py`; rerun it after changing the layout.

`make_dmg.sh` names the dmg by arch via the `ARCH` env var (defaults to
`x86_64`); set `ARCH=arm64` on Apple Silicon. PyInstaller freezes for the arch
of the running Python, so CI builds both arches natively on their own runners,
now that vtk 9.4.2 ships wheels for both: arm64 on `macos-14` and x86_64 on
`macos-15-intel` (GitHub retired the Intel `macos-13` image in Dec 2025). A
single `universal2` build is intentionally avoided: not all of the
native dependencies (vtk, scipy, scikit-image, opencv, the cloud-volume codecs)
ship universal2 wheels, so a universal2 freeze would force source builds and
likely fail.

**Unsigned macOS first launch (Gatekeeper):** an unsigned, un-notarized `.app`
(a local build, or a CI build without the signing secrets) downloaded from the
Releases page is quarantined, and macOS refuses it. Its dmg carries
`Read Before First Launch.html` with the steps. To run it, drag the app to
`/Applications`, then clear the quarantine flag once:

    xattr -dr com.apple.quarantine /Applications/PyReconstruct.app

A signed dmg leaves the guide out, since a notarized app needs no such step.

## VTK 3D viewport: the main risk

vtk is on **9.4.2**, which `pyinstaller-hooks-contrib` covers; the spec also
forces the OpenGL render modules via `hiddenimports` as belt-and-suspenders. If
the 3D viewport still renders **blank** in the frozen app:

1. Confirm `smoke_test.py` passes inside the frozen env.
2. Add any missing `vtkmodules.*` reported by the failure to the spec's
   `hiddenimports`.
3. If still blank, bump `vtk` to `9.4.x` (gets the official hook + native macOS
   arm64 wheels) and re-verify vedo 2023.4.7 compatibility.
4. Last resort: build that platform via conda `constructor` (conda-forge VTK
   ships a working OpenGL backend); the installer/CI layout is unchanged.

## Release-asset naming (matched by the in-app updater)

```
PyReconstruct-<version>-Windows-x86_64-Setup.exe
PyReconstruct-<version>-macOS-arm64.dmg
PyReconstruct-<version>-macOS-x86_64.dmg
```

`<version>` is the setuptools-scm string: `1.20.0` on a clean `vX.Y.Z` tag, or a
normalized pre-release like `1.21.0rc1` on a pre-release tag. (Installers are
built only for tags now; the former rolling `prerelease` main build was retired
along with the in-app Developer channel.)
