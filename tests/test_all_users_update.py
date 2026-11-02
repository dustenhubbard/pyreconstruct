"""Shared installs explain how an administrator completes an update."""

import sys
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.updater import inplace as I
from PyReconstruct.modules.backend.updater import install_info


class MachineRegistry:
    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_READ = 1
    KEY_WOW64_64KEY = 256

    def __init__(self, flavor, location):
        self.key = I.REGISTRY_KEYS[flavor]
        self.location = location

    def OpenKey(self, root, key, reserved, access):
        assert (root, key, reserved, access) == ("HKLM", self.key, 0, 257)
        if self.location is None:
            raise FileNotFoundError(key)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def QueryValueEx(self, key, name):
        assert key is self and name == "InstallLocation"
        return self.location, 1


@pytest.mark.parametrize("flavor", ["stable", "dev"])
@pytest.mark.parametrize("location,expected", [
    ("c:\\program files\\pyreconstruct\\", True),
    ("C:\\Users\\someone\\PyReconstruct", False),
    (None, False),
    (7, False),
])
def test_windows_admin_instruction_matches_this_flavors_machine_install(flavor, location, expected):
    install = I.Install(r"C:\Program Files\PyReconstruct", "PyReconstruct", flavor, "1.25.0")
    assert I.installer_admin_required(install, winreg=MachineRegistry(flavor, location)) is expected


@pytest.mark.parametrize("writable", [True, False])
def test_macos_admin_instruction_follows_permissions_not_the_applications_name(monkeypatch, writable):
    install = I.Install("/Applications/PyReconstruct.app", "PyReconstruct", "stable", "1.25.0",
                        platform="macos-arm64")
    seen = []
    monkeypatch.setattr(I.os, "access", lambda folder, mode: seen.append((folder, mode)) or writable)
    assert I.installer_admin_required(install) is (not writable)
    assert seen == [("/Applications", I.os.W_OK)]


def test_source_run_needs_no_administrator_instruction(monkeypatch):
    monkeypatch.setattr(I, "running_install", lambda: None)
    assert I.installer_admin_required() is False


@pytest.mark.parametrize("folder", [
    "/Volumes/PyReconstruct/PyReconstruct.app",
    "/private/var/folders/x/AppTranslocation/ABC/d/PyReconstruct.app",
])
def test_read_only_macos_download_is_not_a_shared_install(monkeypatch, folder):
    install = I.Install(folder, "PyReconstruct", "stable", "1.25.0", platform="macos-arm64")
    monkeypatch.setattr(I.os, "access", lambda *args: pytest.fail("not an installed copy"))
    assert I.installer_admin_required(install) is False


@pytest.mark.gui
@pytest.mark.parametrize("platform,shared,expected", [
    ("windows", True, "PyReconstruct is installed for all users. An administrator must run "
     "the installer, choose Install for all users, and select the existing installation folder."),
    ("windows", False, None),
    ("macos", True, "An administrator must complete this installation. Open the downloaded "
     "disk image and replace the existing PyReconstruct copy, then approve the administrator prompt."),
    ("macos", False, None),
])
def test_dialog_explains_shared_install_before_downloading(qapp, qtbot, monkeypatch, platform, shared, expected):
    from PySide6.QtWidgets import QLabel
    from PyReconstruct.modules.gui.dialog.update_dialog import UpdateDialog

    install = I.Install("/Applications/PyReconstruct.app", "PyReconstruct", "stable", "1.25.0",
                        platform="macos-arm64") if platform == "macos" else I.Install(
                            r"C:\Program Files\PyReconstruct", "PyReconstruct", "stable", "1.25.0")
    monkeypatch.setattr(I, "running_install", lambda: install)
    monkeypatch.setattr(install_info, "os_key", lambda: platform)
    if platform == "windows":
        monkeypatch.setitem(sys.modules, "winreg", MachineRegistry("stable", install.folder if shared else None))
    else:
        monkeypatch.setattr(I.os, "access", lambda *args: not shared)
    info = {"asset": {"name": "Setup.exe", "size": 1024}, "release": {}, "status": "newer",
            "remote_version": "1.26.0", "local_version": "1.25.0"}
    dlg = UpdateDialog(None, info, "stable")
    qtbot.addWidget(dlg)
    dlg.show()
    notices = [label.text() for label in dlg.findChildren(QLabel) if "administrator" in label.text()]
    assert notices == ([expected] if expected else [])
    if shared:
        monkeypatch.setattr(I, "stage_for_quit", lambda *a, **kw: pytest.fail("needs the installer"))
        assert dlg._try_inplace({}, "1.26.0", lambda p: None) is None


@pytest.mark.gui
def test_admin_update_downloads_and_hands_off_the_verified_installer(qapp, qtbot, monkeypatch):
    from PyReconstruct.modules.gui.dialog import update_dialog as U
    from test_inplace_update_quit import InlinePool

    monkeypatch.setattr(I, "installer_admin_required", lambda: True)
    monkeypatch.setattr(install_info, "os_key", lambda: "windows")
    monkeypatch.setattr(U, "ThreadPool", InlinePool)
    downloaded = []

    def download(url, dest, **kwargs):
        downloaded.append((url, dest))
        return "verified"

    monkeypatch.setattr(U, "download_asset", download)
    monkeypatch.setattr(U, "verified_checksum", lambda *args: ("ok", "verified"))
    monkeypatch.setattr(I, "stage_for_quit", lambda *a, **kw: pytest.fail("needs the installer"))
    info = {"asset": {"name": "Setup.exe", "browser_download_url": "https://example.com/Setup.exe"},
            "release": {}, "status": "newer", "remote_version": "1.26.0", "local_version": "1.25.0"}
    dlg = U.UpdateDialog(None, info, "stable")
    qtbot.addWidget(dlg)
    dlg._parent = SimpleNamespace()
    dlg.show()
    try:
        dlg._start_download()
        assert downloaded == [("https://example.com/Setup.exe", dlg._parent._pending_installer)]
        assert dlg._parent._pending_inplace is None
        assert dlg.result() == 1
    finally:
        import shutil
        shutil.rmtree(dlg._parent._pending_update_dir)
