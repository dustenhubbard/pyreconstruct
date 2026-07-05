"""Tests for the SettingsStore seam (M11 PR 1).

`Series` reads/writes user options through a `SettingsStore` instead of
touching `QSettings` directly. These tests prove the seam:

  - `DictSettingsStore` round-trips values in both the per-series (keyed by
    series code) and global (code=None) scopes, and keeps the scopes isolated;
  - the seam works with NO Qt involved (verified in a subprocess where any
    `PySide6` import is blocked), while the `QSettingsStore` adapter is the only
    piece that requires Qt;
  - `Series.getOption`/`setOption` actually route through an injected store,
    preserving the per-series vs global scoping, the persist-default-on-miss
    behavior, and the JSON encoding for container-valued options.
"""
import os
import sys
import json
import subprocess

from PyReconstruct.modules.backend.settings_store import DictSettingsStore


def test_dict_store_global_roundtrip():
    store = DictSettingsStore()
    assert store.contains(None, "username") is False
    store.set_value(None, "username", "alice")
    assert store.contains(None, "username") is True
    assert store.value(None, "username", str) == "alice"


def test_dict_store_per_series_roundtrip():
    store = DictSettingsStore()
    assert store.contains("ABC", "autobackup") is False
    store.set_value("ABC", "autobackup", True)
    assert store.contains("ABC", "autobackup") is True
    assert store.value("ABC", "autobackup", bool) is True


def test_dict_store_scopes_isolated():
    store = DictSettingsStore()
    store.set_value("ABC", "backup_dir", "/tmp/abc")
    # not visible in another series' scope, nor in the global scope
    assert store.contains("XYZ", "backup_dir") is False
    assert store.contains(None, "backup_dir") is False
    store.set_value(None, "backup_dir", "/tmp/global")
    assert store.value("ABC", "backup_dir", str) == "/tmp/abc"
    assert store.value(None, "backup_dir", str) == "/tmp/global"


def test_settings_store_needs_no_qt():
    """The seam is Qt-free: DictSettingsStore round-trips with PySide6 blocked.

    Runs in a subprocess that makes any `PySide6` import raise, then imports the
    store module and exercises DictSettingsStore. Confirms Qt is never pulled in
    and that the QSettingsStore adapter is the only piece that requires it.
    """
    script = r"""
import sys

# drop any pre-loaded PySide6 (e.g. a dev-env sitecustomize) so the block
# governs the (re)import and this is a genuine proof in any environment
for _m in list(sys.modules):
    if _m == "PySide6" or _m.startswith("PySide6."):
        del sys.modules[_m]

class _BlockPySide6:
    def find_spec(self, name, path=None, target=None):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("PySide6 blocked for headless proof")
        return None

sys.meta_path.insert(0, _BlockPySide6())

from PyReconstruct.modules.backend.settings_store import (
    DictSettingsStore, QSettingsStore
)

s = DictSettingsStore()
assert not s.contains(None, "k")
s.set_value(None, "k", 7)
assert s.value(None, "k", int) == 7
s.set_value("CODE", "k", "v")
assert s.value("CODE", "k", str) == "v"
assert not s.contains("OTHER", "k")

# no Qt was imported to build/use the pure-Python store
assert "PySide6" not in sys.modules
assert "PySide6.QtCore" not in sys.modules

# the Qt adapter is the sole piece that needs Qt: it must fail fast when blocked
try:
    QSettingsStore().contains(None, "k")
except ImportError:
    pass
else:
    raise AssertionError("QSettingsStore should require PySide6")

print("HEADLESS_OK")
"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "HEADLESS_OK" in result.stdout


def test_series_options_route_through_injected_store():
    """getOption/setOption go through the injected store, scoping preserved."""
    from PyReconstruct.modules.datatypes.series import Series

    series = Series.__new__(Series)
    series.options = {}
    series.code = "TESTCODE"
    series.filepath = "/nonexistent/definitely-not-welcome.ser"
    store = DictSettingsStore()
    series.setSettingsStore(store)

    assert series._settingsStore() is store

    # unset global option returns its default AND persists it via the store
    assert series.getOption("cpu_max") == 100
    assert store.contains(None, "cpu_max")

    # global scalar round-trip (code=None)
    series.setOption("cpu_max", 42)
    assert store.value(None, "cpu_max", int) == 42
    assert series.getOption("cpu_max") == 42

    series.setOption("backup_series", False)
    assert series.getOption("backup_series") is False

    # global container option is JSON-encoded into the store, decoded on read
    series.setOption("grid", [2, 2, 2, 2, 2, 2])
    assert store.value(None, "grid", str) == json.dumps([2, 2, 2, 2, 2, 2])
    assert series.getOption("grid") == [2, 2, 2, 2, 2, 2]

    # per-series option lands in the code-keyed scope, not the global one
    series.setOption("backup_dir", "/tmp/backups")
    assert store.value("TESTCODE", "backup_dir", str) == "/tmp/backups"
    assert store.contains(None, "backup_dir") is False
    assert series.getOption("backup_dir") == "/tmp/backups"

    series.setOption("autobackup", True)
    assert store.contains("TESTCODE", "autobackup")
    assert series.getOption("autobackup") is True
