# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the in-place update helper, pyreconstruct-updater.exe.

Windows only. Run from the repository root, in the same environment as the
app's freeze:

    pyinstaller --noconfirm --distpath build/updater-dist --workpath build/updater-work \
        packaging/windows/pyreconstruct-updater.spec

The whole program is apply.py, which imports only the standard library, so
the helper carries no Qt and no third-party packages. The Windows leg of
build-installers.yml copies it into the frozen app's _updater folder, so
Setup.exe installs it and the update payload carries it. The app copies it
into the staging folder and runs it from there, because a program running
from the install folder would keep that folder from being renamed.

One file, so it can be copied as one. No console window, since the app
starts it as it quits. No traceback dialog either: a helper that fails must
exit and leave its log and result.json, never wait on a click nobody sees.
The same program serves both flavors; the plan it reads names the app.
"""

from pathlib import Path

REPO_ROOT = Path(SPECPATH).parents[1]
ENTRY = str(REPO_ROOT / "PyReconstruct" / "modules" / "backend" / "updater" / "apply.py")
ICON = str(REPO_ROOT / "PyReconstruct" / "assets" / "img" / "PyReconstruct.ico")

a = Analysis(
    [ENTRY],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pyreconstruct-updater",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    icon=ICON,
)
