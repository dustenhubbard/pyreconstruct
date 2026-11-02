"""Compile and run both installer modes on a disposable Windows CI runner."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true",
    reason="installs test products and edits PATH on disposable Windows CI only",
)

SYSTEM_ENV = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"


def _run(argv):
    result = subprocess.run([str(arg) for arg in argv], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def _path(root, subkey):
    import winreg
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as key:
            return winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        return None


@pytest.mark.parametrize("dev", [False, True], ids=["stable", "dev"])
@pytest.mark.parametrize("all_users", [False, True], ids=["current-user", "all-users"])
@pytest.mark.parametrize("trailing_separator", [False, True], ids=["plain-path", "trailing-semicolon"])
def test_installer_adds_once_and_uninstalls_from_the_selected_path(tmp_path, dev, all_users, trailing_separator):
    import winreg

    compiler = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
    assert compiler.is_file(), "Windows CI must provide Inno Setup 6"
    # Unique product names, associations, and AppIds isolate this from real installs.
    name = "PyReconstructPathTest" + uuid.uuid4().hex
    extension = "." + name.lower()
    source = Path(__file__).resolve().parents[1] / "packaging/windows/PyReconstruct.iss"
    text = source.read_text(encoding="utf-8").replace("PyReconstruct", name).replace(".jser", extension)
    for app_id in ("A1B2C3D4-E5F6-47A8-9B0C-1D2E3F4A5B6C", "0C76AF3D-BB20-4EDB-99FC-2B9244E213F7"):
        text = text.replace(app_id, str(uuid.uuid4()).upper())
    script = tmp_path / "packaging/windows/test.iss"
    script.parent.mkdir(parents=True)
    script.write_text(text, encoding="utf-8")
    product = name + (" Dev" if dev else "")
    payload = tmp_path / "dist" / product
    (payload / "bin").mkdir(parents=True)
    (payload / f"{product}.exe").write_bytes(b"test payload")
    (payload / "bin/pyrecon.cmd").write_text("@echo off\n")
    args = [compiler, "/DPYR_VERSION=0.0.1"]
    if dev:
        args.append("/DPYR_FLAVOR=dev")
    _run([*args, script])
    setup, = (script.parent / "Output").glob("*.exe")
    install = tmp_path / "installed" / product
    mode = "/ALLUSERS" if all_users else "/CURRENTUSER"
    command = [setup, mode, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={install}"]
    scopes = [(winreg.HKEY_CURRENT_USER, "Environment"), (winreg.HKEY_LOCAL_MACHINE, SYSTEM_ENV)]
    original = [_path(*scope) for scope in scopes]
    selected = int(all_users)
    uninstaller = install / "unins000.exe"
    uninstalled = False
    try:
        if trailing_separator:
            root, subkey = scopes[selected]
            with winreg.CreateKey(root, subkey) as key:
                old = original[selected][0] if original[selected] else ""
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, old + ";")
        before = [_path(*scope) for scope in scopes]
        _run(command)
        for index, scope in enumerate(scopes):
            value = _path(*scope)
            if index != selected:
                assert value == before[index]
                continue
            old = before[index][0] if before[index] else ""
            expected = old + (";" if old else "") + str(install / "bin")
            assert value == (expected, winreg.REG_EXPAND_SZ)
        once = [_path(*scope) for scope in scopes]
        _run(command)
        assert [_path(*scope) for scope in scopes] == once
        _run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        uninstalled = True
        assert [_path(*scope)[0] if _path(*scope) else "" for scope in scopes] == [
            value[0] if value else "" for value in before]
    finally:
        try:
            if not uninstalled and uninstaller.exists():
                _run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        finally:
            for (root, subkey), value in zip(scopes, original):
                with winreg.CreateKey(root, subkey) as key:
                    if value is not None:
                        winreg.SetValueEx(key, "Path", 0, value[1], value[0])
                    else:
                        try:
                            winreg.DeleteValue(key, "Path")
                        except FileNotFoundError:
                            pass
            # Inno preserves the extension's default association on uninstall.
            classes = winreg.HKEY_LOCAL_MACHINE if all_users else winreg.HKEY_CURRENT_USER
            try:
                winreg.DeleteKey(classes, "Software\\Classes\\" + extension)
            except FileNotFoundError:
                pass
