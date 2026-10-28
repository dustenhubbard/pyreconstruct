"""Series codes that differ only in backslashes keep separate Windows settings.

On Windows the native settings backend is the registry. A series' own
settings live under ``HKEY_CURRENT_USER\\Software\\<org>\\<app>-<code>``, so a
backslash in the code is a registry key separator. Each pair below holds two
distinct codes: the first series stores its backup folder, then the second
reads, writes and rereads its own, through the production `QSettingsStore`
with the native format.

The registry keys live under an organization made for one test run, never
under ``KHLab``, and are deleted afterward.
"""
import sys
import uuid

import pytest

import qsettings_isolation as qi
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants import settings_domain as SD

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the registry settings backend exists only on Windows",
)

# (existing code, incoming code)
PAIRS = {
    "trailing-backslash": ("existing", "existing\\"),
    "two-trailing-backslashes": ("existing", "existing\\\\"),
    "doubled-inner-backslash": ("a\\b", "a\\\\b"),
    "trailing-backslash-dot": ("existing", "existing\\."),
    "trailing-backslash-dotdot": ("existing", "existing\\.."),
    "trailing-slash": ("existing", "existing/"),
    "slash-for-backslash": ("a\\b", "a/b"),
}

EXISTING_DIR = "C:/existing-series-backups"
INCOMING_DIR = "C:/incoming-series-backups"


def _delete_tree(root, path):
    import winreg

    try:
        key = winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return
    with key:
        while True:
            try:
                child = winreg.EnumKey(key, 0)
            except OSError:
                break
            _delete_tree(root, path + "\\" + child)
    winreg.DeleteKey(root, path)


def _key_exists(root, path):
    import winreg

    try:
        winreg.OpenKey(root, path).Close()
    except FileNotFoundError:
        return False
    return True


@pytest.fixture
def native_store(monkeypatch):
    """A production `QSettingsStore` on the native backend, under a test
    organization whose registry tree is removed afterward."""
    import winreg
    import PySide6.QtCore as qtcore

    org = f"PyReconstructRegistryTest-{uuid.uuid4().hex}"
    tree = f"Software\\{org}"
    real = qi._real_qsettings
    native = real.Format.NativeFormat
    user_scope = real.Scope.UserScope

    class NativeQSettings(real):
        def __init__(self, organization, application):
            if organization != org:
                raise AssertionError(
                    f"settings opened for {organization!r}, not {org!r}"
                )
            super().__init__(native, user_scope, organization, application)

    monkeypatch.setattr(SD, "SETTINGS_ORG", org)
    monkeypatch.setattr(qtcore, "QSettings", NativeQSettings)
    assert not _key_exists(winreg.HKEY_CURRENT_USER, tree)
    try:
        with qi.deliberate_bypass() as recorded:
            yield QSettingsStore()
        assert recorded
        assert all(org in bypass.path for bypass in recorded)
    finally:
        _delete_tree(winreg.HKEY_CURRENT_USER, tree)
    assert not _key_exists(winreg.HKEY_CURRENT_USER, tree)


@pytest.mark.parametrize("pair", PAIRS.values(), ids=PAIRS.keys())
def test_a_backslash_code_keeps_its_own_backups(native_store, pair):
    existing, incoming = pair
    native_store.set_value(existing, "backup_dir", EXISTING_DIR)
    assert native_store.value(existing, "backup_dir", str) == EXISTING_DIR

    before = native_store.value(incoming, "backup_dir", str)
    native_store.set_value(incoming, "backup_dir", INCOMING_DIR)

    assert (
        before,
        native_store.value(existing, "backup_dir", str),
        native_store.value(incoming, "backup_dir", str),
    ) == ("", EXISTING_DIR, INCOMING_DIR)
