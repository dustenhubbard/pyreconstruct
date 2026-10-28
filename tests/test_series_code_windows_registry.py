"""Series codes that differ only in backslashes keep separate Windows settings.

On Windows the native settings backend is the registry. A series' own
settings live under ``HKEY_CURRENT_USER\\Software\\<org>\\<app>-<code>``, so a
backslash in the code is a registry key separator, and the registry drops an
empty key name: ``existing\\`` opens the key of ``existing``. On Windows such
a code names the domain ``<app> PATH-<SHA-256 of the code>``. Every other
code, and every code on macOS and Linux, names the same domain as before.

Each pair below holds two distinct codes: the first series stores its backup
folder, then the second reads, writes and rereads its own, through the
production `QSettingsStore` with the native format. The registry keys live
under an organization made for one test run, never under ``KHLab``, and are
deleted afterward.
"""
import hashlib
import itertools
import re
import sys
import uuid

import pytest

import qsettings_isolation as qi
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants import settings_domain as SD

on_windows = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the registry settings backend exists only on Windows",
)

APPS = ["PyReconstruct", "PyReconstruct Dev"]

# (existing code, incoming code)
PAIRS = {
    "trailing-backslash": ("existing", "existing\\"),
    "two-trailing-backslashes": ("existing", "existing\\\\"),
    "doubled-inner-backslash": ("a\\b", "a\\\\b"),
    "doubled-leading-backslash": ("\\existing", "\\\\existing"),
    "lone-backslash": ("", "\\"),
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


@on_windows
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


REGISTRY_CODES = [
    "existing\\", "existing\\\\", "a\\\\b", "\\\\existing", "\\\\", "a\\b\\",
    "a/b\\", "a\\\\.", "\\..\\\\PyReconstruct-existing", "\\",
]

PLAIN_CODES = [
    "existing", "a\\b", "\\existing", "a\\b\\c", "existing\\.",
    "existing\\..", "existing/", "a/b", "\\..\\PyReconstruct-existing",
]


def _digest(code):
    return hashlib.sha256(code.encode("utf-8", "surrogatepass")).hexdigest()


def _registry_key(name):
    # the key the registry opens for a path: empty names dropped
    head, *rest = name.split("\\")
    return "\\".join([head] + [part for part in rest if part]).lower()


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(SD, "_native_is_registry", lambda: True)


@pytest.mark.parametrize("code", REGISTRY_CODES)
@pytest.mark.parametrize("app", APPS)
def test_on_windows_a_registry_path_code_names_its_digest(registry, app, code):
    assert SD.series_app(app, code) == f"{app} PATH-{_digest(code)}"


@pytest.mark.parametrize("code", PLAIN_CODES)
@pytest.mark.parametrize("app", APPS)
def test_on_windows_a_plain_code_names_the_same_domain(registry, app, code):
    assert SD.series_app(app, code) == app + "-" + code


@pytest.mark.parametrize("code", REGISTRY_CODES)
@pytest.mark.parametrize("app", APPS)
def test_elsewhere_a_registry_path_code_names_the_same_domain(
    monkeypatch, app, code
):
    monkeypatch.setattr(SD, "_native_is_registry", lambda: False)
    assert SD.series_app(app, code) == app + "-" + code


def test_on_windows_every_short_code_names_a_key_of_its_own(registry):
    # every code up to five characters over a mix of plain, path and NUL
    # characters; the two app-wide domains are in the set too. Registry key
    # names are compared without case, so the alphabet has one case only.
    keys = {_registry_key(app): (app, None) for app in APPS}
    alphabet = ["a", "-", "/", "\\", ".", "\0"]
    for n in range(6):
        for chars in itertools.product(alphabet, repeat=n):
            code = "".join(chars)
            for app in APPS:
                name = SD.series_app(app, code)
                assert re.match(re.escape(app) + "(-| NUL-| PATH-)", name)
                if "\0" in name:
                    continue
                key = _registry_key(name)
                # the registry drops nothing from the name
                assert key == name.lower(), (app, code)
                assert keys.setdefault(key, (app, code)) == (app, code), key
