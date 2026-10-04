"""The one-time fold of a Dev app's old private settings into the shared store.

Until 2026-09-27 the Dev flavor kept its own QSettings domain, seeded once
from the stable app and edited on its own afterwards. Both apps now share one
store, so the first Dev launch on the new build offers what its old domain
holds to the shared one: a key the shared store lacks is copied in, a key
both hold keeps the stable value, per-app keys and ``meta/`` stay put, and a
marker in the Dev domain stops it running again. Per-series domains fold the
same way, lazily, when a series opens.

Every test runs against ini-backed QSettings in a temp directory or against
the suite's redirected domains: the real stores on the machine running the
suite are never read or written.
"""

import inspect
import os

import pytest

from PyReconstruct.modules.constants.settings_domain import (
    FOLD_MARKER,
    SEED_MARKER,
    fold_flavor_settings_once,
    fold_series_settings_once,
)

pytestmark = pytest.mark.gui

DEV = "PyReconstruct Dev"


@pytest.fixture
def ini_settings(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    def make(name):
        # tmp_path.name in the basename: the suite's QSettings isolation
        # redirects explicit-file settings into one shared folder BY BASENAME,
        # so a plain "dev.ini" would be the same store in every test here
        return QSettings(
            str(tmp_path / f"{name}-{tmp_path.name}.ini"), QSettings.IniFormat
        )

    return make


# --- the global fold ------------------------------------------------------------


def test_a_dev_only_key_is_copied_into_the_shared_store(ini_settings):
    dev = ini_settings("dev")
    dev.setValue("auto_merge", True)
    dev.setValue("palette/mode_x", 0.42)
    dev.sync()
    shared = ini_settings("shared")

    assert fold_flavor_settings_once(flavored=dev, shared=shared) is True
    assert shared.value("auto_merge") == dev.value("auto_merge")
    assert shared.value("palette/mode_x") == dev.value("palette/mode_x")
    assert dev.value(FOLD_MARKER, type=bool) is True


def test_on_a_conflict_the_stable_value_wins(ini_settings):
    """Where both apps hold a key the stable app's value stays: the user set
    most things twice to the same value, and where they differ, stable is
    the app for real work (his call, 2026-09-27)."""
    dev = ini_settings("dev")
    dev.setValue("username", "dev-name")
    dev.setValue("roll_average", True)
    dev.sync()
    shared = ini_settings("shared")
    shared.setValue("username", "stable-name")
    shared.sync()

    fold_flavor_settings_once(flavored=dev, shared=shared)
    assert shared.value("username") == "stable-name"      # kept
    assert shared.value("roll_average") == dev.value("roll_average")  # filled


def test_per_app_keys_stay_in_the_dev_store(ini_settings):
    """The What's new state, the update throttle and the window position are
    each app's own; the fold leaves them where they are and the shared store
    never learns them."""
    dev = ini_settings("dev")
    dev.setValue("suppress_whatsnew", False)
    dev.setValue("last_whatsnew_version", "1.24.0.dev20260927")
    dev.setValue("last_update_check_epoch", 1234567.0)
    dev.setValue("window/geometry", b"devblob")
    dev.setValue("auto_merge", True)
    dev.sync()
    shared = ini_settings("shared")

    fold_flavor_settings_once(flavored=dev, shared=shared)
    for key in ("suppress_whatsnew", "last_whatsnew_version",
                "last_update_check_epoch", "window/geometry"):
        assert not shared.contains(key), key
        assert dev.contains(key), key
    assert shared.contains("auto_merge")


def test_meta_keys_are_never_copied(ini_settings):
    dev = ini_settings("dev")
    dev.setValue(SEED_MARKER, True)
    dev.setValue("meta/anything", "x")
    dev.setValue("auto_merge", True)
    dev.sync()
    shared = ini_settings("shared")

    fold_flavor_settings_once(flavored=dev, shared=shared)
    assert not shared.contains(SEED_MARKER)
    assert not shared.contains("meta/anything")
    assert not shared.contains(FOLD_MARKER)
    assert shared.contains("auto_merge")


def test_the_fold_runs_exactly_once(ini_settings):
    dev = ini_settings("dev")
    dev.setValue("auto_merge", True)
    dev.sync()
    shared = ini_settings("shared")
    assert fold_flavor_settings_once(flavored=dev, shared=shared) is True

    # the user later clears the shared choice; a later launch must not put
    # the Dev copy back behind their back
    shared.remove("auto_merge")
    shared.sync()
    assert fold_flavor_settings_once(flavored=dev, shared=shared) is False
    assert not shared.contains("auto_merge")


def test_a_second_call_changes_nothing_on_disk(ini_settings):
    dev = ini_settings("dev")
    dev.setValue("auto_merge", True)
    dev.sync()
    shared = ini_settings("shared")
    fold_flavor_settings_once(flavored=dev, shared=shared)
    shared.sync(); dev.sync()
    before = (open(shared.fileName(), "rb").read(), open(dev.fileName(), "rb").read())

    assert fold_flavor_settings_once(flavored=dev, shared=shared) is False
    shared.sync(); dev.sync()
    after = (open(shared.fileName(), "rb").read(), open(dev.fileName(), "rb").read())
    assert after == before


def test_an_empty_dev_store_still_marks_and_stops(ini_settings):
    """A fresh Dev install on the new build: nothing to fold, but the marker
    is written so later launches skip the scan."""
    dev = ini_settings("dev")
    assert fold_flavor_settings_once(flavored=dev, shared=ini_settings("shared")) is True
    assert dev.value(FOLD_MARKER, type=bool) is True


def test_an_unseeded_dev_store_folds_too(ini_settings):
    """The fold does not depend on the old seed marker: a Dev domain written
    by a source run with the variable set never had one and folds the same."""
    dev = ini_settings("dev")
    dev.setValue("auto_merge", True)
    dev.sync()
    assert not dev.contains(SEED_MARKER)
    shared = ini_settings("shared")
    fold_flavor_settings_once(flavored=dev, shared=shared)
    assert shared.contains("auto_merge")


# --- the stable app -------------------------------------------------------------


class _Constructions:
    """Count every QSettings the code under test builds on its own."""

    def __init__(self, monkeypatch):
        import PySide6.QtCore as qtcore
        self.calls = []
        real = qtcore.QSettings
        counter = self

        class Recording(real):
            def __init__(self, *args, **kwargs):
                counter.calls.append(args)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(qtcore, "QSettings", Recording)


def test_the_stable_app_never_folds_and_never_opens_a_dev_domain(monkeypatch):
    """Resolved from the environment: the stable app is a no-op for both
    folds and does not even construct a settings handle to look."""
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    built = _Constructions(monkeypatch)
    assert fold_flavor_settings_once() is False
    assert fold_series_settings_once("SER1") is False
    assert built.calls == []


def test_a_stable_app_with_no_dev_present_is_byte_identical(monkeypatch, qapp):
    """The whole point of option A for the stable app: same domain, same
    keys, same values. Run the startup fold and a series fold as the stable
    app against a populated store and the file does not change by a byte."""
    from PySide6.QtCore import QSettings

    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    shared = QSettings("PyReconstruct", "PyReconstruct")
    per_series = QSettings("PyReconstruct", "PyReconstruct-FOLDPROBE")
    shared.setValue("fold_probe_global", "kept")
    per_series.setValue("fold_probe_series", "kept")
    shared.sync(); per_series.sync()
    try:
        before = (open(shared.fileName(), "rb").read(),
                  open(per_series.fileName(), "rb").read())
        assert fold_flavor_settings_once() is False
        assert fold_series_settings_once("FOLDPROBE") is False
        QSettings("PyReconstruct", "PyReconstruct").sync()
        QSettings("PyReconstruct", "PyReconstruct-FOLDPROBE").sync()
        after = (open(shared.fileName(), "rb").read(),
                 open(per_series.fileName(), "rb").read())
        assert after == before
        assert not os.path.exists(QSettings("PyReconstruct", DEV).fileName()) or \
            not QSettings("PyReconstruct", DEV).contains(FOLD_MARKER)
    finally:
        for s in (QSettings("PyReconstruct", "PyReconstruct"),
                  QSettings("PyReconstruct", "PyReconstruct-FOLDPROBE")):
            s.remove("fold_probe_global")
            s.remove("fold_probe_series")
            s.sync()


# --- resolved from the real (redirected) domains ---------------------------------


def _clean(*domains):
    from PySide6.QtCore import QSettings
    for org, app in domains:
        s = QSettings(org, app)
        for key in list(s.allKeys()):
            if key.startswith("fold_probe") or key == FOLD_MARKER:
                s.remove(key)
        s.sync()


def test_the_dev_app_resolves_both_domains_from_the_environment(monkeypatch, qapp):
    """No injection: under the Dev variable the fold reads
    ``PyReconstruct / PyReconstruct Dev`` and writes ``PyReconstruct / PyReconstruct``."""
    from PySide6.QtCore import QSettings

    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    _clean(("PyReconstruct", DEV), ("PyReconstruct", "PyReconstruct"))
    try:
        dev = QSettings("PyReconstruct", DEV)
        dev.setValue("fold_probe_a", "from-dev")
        dev.setValue("fold_probe_b", "from-dev")
        dev.sync()
        shared = QSettings("PyReconstruct", "PyReconstruct")
        shared.setValue("fold_probe_b", "from-stable")
        shared.sync()

        assert fold_flavor_settings_once() is True
        shared = QSettings("PyReconstruct", "PyReconstruct")
        assert shared.value("fold_probe_a") == "from-dev"
        assert shared.value("fold_probe_b") == "from-stable"
        assert QSettings("PyReconstruct", DEV).value(FOLD_MARKER, type=bool) is True
        assert not shared.contains(FOLD_MARKER)
        assert fold_flavor_settings_once() is False
    finally:
        _clean(("PyReconstruct", DEV), ("PyReconstruct", "PyReconstruct"))


# --- per-series ----------------------------------------------------------------------


def test_per_series_settings_fold_with_the_same_rule(ini_settings):
    dev = ini_settings("dev-ser")
    dev.setValue("autobackup", True)
    dev.setValue("backup_dir", "/dev/backups")
    dev.setValue("list_layout", '{"objects": "floating"}')
    dev.sync()
    shared = ini_settings("shared-ser")
    shared.setValue("autobackup", False)
    shared.sync()

    assert fold_series_settings_once("SER1", flavored=dev, shared=shared) is True
    assert shared.value("autobackup") in (False, "false")   # stable's stays
    assert shared.value("backup_dir") == "/dev/backups"
    assert shared.value("list_layout") == '{"objects": "floating"}'
    assert dev.value(FOLD_MARKER, type=bool) is True
    assert fold_series_settings_once("SER1", flavored=dev, shared=shared) is False


def test_per_series_fold_writes_no_marker_when_there_was_nothing_to_give(ini_settings):
    """Opening a series in Dev must not create a ``PyReconstruct Dev-<code>``
    store holding nothing but a marker; a domain with nothing to offer is
    simply looked at again next time."""
    dev = ini_settings("dev-ser")
    shared = ini_settings("shared-ser")
    shared.setValue("autobackup", True)
    shared.sync()
    assert fold_series_settings_once("SER1", flavored=dev, shared=shared) is False
    dev.sync()
    assert not dev.contains(FOLD_MARKER)

    # every key already present in shared: same answer
    dev.setValue("autobackup", False)
    dev.sync()
    assert fold_series_settings_once("SER1", flavored=dev, shared=shared) is False
    assert not dev.contains(FOLD_MARKER)
    assert shared.value("autobackup") in (True, "true")


def test_per_series_fold_needs_a_code(monkeypatch):
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    built = _Constructions(monkeypatch)
    assert fold_series_settings_once("") is False
    assert fold_series_settings_once(None) is False
    assert built.calls == []


def test_per_series_fold_resolves_the_flavored_domains(monkeypatch, qapp):
    from PySide6.QtCore import QSettings

    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    domains = (("PyReconstruct", f"{DEV}-FOLDSER"), ("PyReconstruct", "PyReconstruct-FOLDSER"))
    _clean(*domains)
    try:
        QSettings("PyReconstruct", f"{DEV}-FOLDSER").setValue("fold_probe_layout", "dev")
        QSettings("PyReconstruct", f"{DEV}-FOLDSER").sync()
        assert fold_series_settings_once("FOLDSER") is True
        assert QSettings("PyReconstruct", "PyReconstruct-FOLDSER").value("fold_probe_layout") == "dev"
        assert QSettings("PyReconstruct", f"{DEV}-FOLDSER").value(FOLD_MARKER, type=bool) is True
    finally:
        _clean(*domains)


# --- the window hook ----------------------------------------------------------------


def test_open_series_folds_after_the_code_is_settled_and_before_the_first_read():
    """`_restoreListLayout` is the first per-series read on the open path and
    `_ensureSeriesCode` is what settles the code the domain is named by; the
    fold must sit between them."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    source = inspect.getsource(MainWindow.openSeries)
    code = source.index("self._ensureSeriesCode()")
    fold = source.index("self._foldSeriesSettings()")
    layout = source.index("self._restoreListLayout()")
    assert code < fold < layout


def test_the_window_folds_the_open_series_under_the_dev_flavor(main_window, monkeypatch):
    """End to end on a live window: the series' old Dev per-series domain is
    offered to the shared one when the window runs as the Dev app."""
    from PySide6.QtCore import QSettings

    code = main_window.series.code
    assert code, "the fixture series carries a code"
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    domains = (("PyReconstruct", f"{DEV}-{code}"), ("PyReconstruct", f"PyReconstruct-{code}"))
    _clean(*domains)
    try:
        QSettings("PyReconstruct", f"{DEV}-{code}").setValue("fold_probe_window", "dev")
        QSettings("PyReconstruct", f"{DEV}-{code}").sync()
        main_window._foldSeriesSettings()
        assert QSettings("PyReconstruct", f"PyReconstruct-{code}").value("fold_probe_window") == "dev"
    finally:
        _clean(*domains)


def test_the_window_hook_never_raises(main_window, monkeypatch):
    """A settings carry-over must not stop a series opening."""
    from PyReconstruct.modules.gui.main import main_window as MW

    def boom(code):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(MW, "fold_series_settings_once", boom)
    main_window._foldSeriesSettings()   # no exception


@pytest.mark.parametrize("layout", ["not json", "[]", "null", "42", '"text"'])
def test_per_series_fold_skips_invalid_layouts(ini_settings, layout):
    dev = ini_settings("dev-invalid-layout")
    shared = ini_settings("shared-invalid-layout")
    dev.setValue("list_layout", layout)
    dev.setValue("backup_dir", "/dev/backups")
    dev.sync()

    assert fold_series_settings_once("SER1", flavored=dev, shared=shared) is True
    assert not shared.contains("list_layout")
    assert shared.value("backup_dir") == "/dev/backups"
    assert dev.value("list_layout") == layout
    assert dev.value(FOLD_MARKER, type=bool) is True


def test_per_series_fold_preserves_existing_layout(ini_settings):
    dev = ini_settings("dev-layout-conflict")
    shared = ini_settings("shared-layout-conflict")
    dev.setValue("list_layout", '{"objects": "floating"}')
    shared.setValue("list_layout", '{}')
    dev.sync()
    shared.sync()

    assert fold_series_settings_once("SER1", flavored=dev, shared=shared) is False
    assert shared.value("list_layout") == '{}'


@pytest.mark.parametrize("scope", ["global", "series"])
def test_failed_shared_write_retries_on_next_process(tmp_path, scope):
    """A durable Dev marker must never outlive a failed shared-store write."""
    import json
    import subprocess
    import sys

    # These subprocesses use only explicit INI files inside tmp_path. They
    # cannot touch the application's native preference stores.
    script = '''
import json
import sys
from PySide6.QtCore import QSettings
from PyReconstruct.modules.constants.settings_domain import (
    FOLD_MARKER, fold_flavor_settings_once, fold_series_settings_once,
)
dev = QSettings(sys.argv[1], QSettings.IniFormat)
shared = QSettings(sys.argv[2], QSettings.IniFormat)
if not dev.contains("backup_dir"):
    dev.setValue("backup_dir", "/dev/backups")
    dev.sync()
if sys.argv[3] == "global":
    fold_flavor_settings_once(flavored=dev, shared=shared)
else:
    fold_series_settings_once("SER1", flavored=dev, shared=shared)
print(json.dumps({
    "marked": dev.contains(FOLD_MARKER),
    "status": shared.status().value,
    "backup_dir": shared.value("backup_dir"),
}))
'''
    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("not a directory")
    args = [sys.executable, "-c", script, str(tmp_path / "dev.ini"),
            str(blocked_parent / "shared.ini"), scope]
    failed = json.loads(subprocess.check_output(args, text=True))
    assert failed["status"] != 0
    assert failed["marked"] is False

    blocked_parent.unlink()
    blocked_parent.mkdir()
    retried = json.loads(subprocess.check_output(args, text=True))
    assert retried == {"marked": True, "status": 0, "backup_dir": "/dev/backups"}
