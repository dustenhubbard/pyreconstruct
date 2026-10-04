"""The one-time copy of settings from the old ``KHLab`` organization.

Until 2026-10-03 every settings store sat under the organization ``KHLab``.
The stores now sit under ``PyReconstruct``, and the first launch of a build
that reads the new name copies each old store across: a key the new store
lacks is copied, a key it already holds is left alone, the old store is never
written, and a marker in the new store stops the copy from running again.
Per-series stores copy the same way, when a series opens.

Every test runs against the suite's redirected domains, so the real stores on
the machine running the suite are never read or written.
"""

import inspect
import os

import pytest

from PyReconstruct.modules.constants.settings_domain import (
    FOLD_MARKER,
    LEGACY_COPY_MARKER,
    LEGACY_SETTINGS_ORG,
    SETTINGS_ORG,
    SHARED_APP,
    copy_legacy_series_settings_once,
    copy_legacy_settings_once,
    fold_flavor_settings_once,
    fold_series_settings_once,
)

pytestmark = pytest.mark.gui

DEV = "PyReconstruct Dev"
CODE = "LEGACYSER"
PROBE = "legacy_probe"


def _settings(org, app):
    from PySide6.QtCore import QSettings
    return QSettings(org, app)


def _apps():
    return (
        SHARED_APP, DEV, f"{SHARED_APP}-{CODE}", f"{DEV}-{CODE}",
    )


def _wipe():
    """Remove every probe key and marker these tests write, in both orgs."""
    for org in (SETTINGS_ORG, LEGACY_SETTINGS_ORG):
        for app in _apps():
            s = _settings(org, app)
            for key in list(s.allKeys()):
                if key.startswith(PROBE) or key in (
                    LEGACY_COPY_MARKER, FOLD_MARKER,
                ):
                    s.remove(key)
            s.sync()


@pytest.fixture
def clean(qapp, monkeypatch):
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    _wipe()
    yield
    _wipe()


def _legacy(app, **values):
    s = _settings(LEGACY_SETTINGS_ORG, app)
    for key, value in values.items():
        s.setValue(key, value)
    s.sync()
    return s


def _bytes(org, app):
    path = _settings(org, app).fileName()
    with open(path, "rb") as f:
        return f.read()


def test_the_new_organization_is_pyreconstruct():
    assert SETTINGS_ORG == "PyReconstruct"
    assert LEGACY_SETTINGS_ORG == "KHLab"


# --- the global stores ---------------------------------------------------------


def test_old_values_are_copied_on_first_launch(clean):
    _legacy(
        SHARED_APP,
        legacy_probe_name="Ada",
        legacy_probe_flag=True,
        legacy_probe_number=0.25,
    )

    copied = copy_legacy_settings_once()

    new = _settings(SETTINGS_ORG, SHARED_APP)
    assert new.value("legacy_probe_name") == "Ada"
    assert new.value("legacy_probe_flag", type=bool) is True
    assert new.value("legacy_probe_number", type=float) == 0.25
    assert new.value(LEGACY_COPY_MARKER, type=bool) is True
    assert set(copied[SHARED_APP]) >= {
        "legacy_probe_name", "legacy_probe_flag", "legacy_probe_number",
    }


def test_the_old_store_is_left_exactly_as_it_was(clean):
    _legacy(SHARED_APP, legacy_probe_name="Ada")
    before = _bytes(LEGACY_SETTINGS_ORG, SHARED_APP)

    copy_legacy_settings_once()
    _settings(LEGACY_SETTINGS_ORG, SHARED_APP).sync()

    assert _bytes(LEGACY_SETTINGS_ORG, SHARED_APP) == before
    old = _settings(LEGACY_SETTINGS_ORG, SHARED_APP)
    assert old.value("legacy_probe_name") == "Ada"
    assert not old.contains(LEGACY_COPY_MARKER)


def test_a_value_already_in_the_new_store_is_kept(clean):
    _legacy(SHARED_APP, legacy_probe_name="old")
    new = _settings(SETTINGS_ORG, SHARED_APP)
    new.setValue("legacy_probe_name", "new")
    new.sync()

    copy_legacy_settings_once()

    assert _settings(SETTINGS_ORG, SHARED_APP).value("legacy_probe_name") == "new"


def test_the_copy_runs_once(clean):
    """Once marked, a later change in the new store is never undone: not a
    changed value and not a removed key."""
    _legacy(SHARED_APP, legacy_probe_name="Ada", legacy_probe_flag=True)
    assert copy_legacy_settings_once()

    new = _settings(SETTINGS_ORG, SHARED_APP)
    new.setValue("legacy_probe_name", "changed")
    new.remove("legacy_probe_flag")
    new.sync()
    before = _bytes(SETTINGS_ORG, SHARED_APP)

    assert copy_legacy_settings_once() == {}

    new = _settings(SETTINGS_ORG, SHARED_APP)
    assert new.value("legacy_probe_name") == "changed"
    assert not new.contains("legacy_probe_flag")
    assert _bytes(SETTINGS_ORG, SHARED_APP) == before


def test_a_fresh_install_is_marked_and_nothing_else(clean):
    assert copy_legacy_settings_once() == {}
    new = _settings(SETTINGS_ORG, SHARED_APP)
    assert new.value(LEGACY_COPY_MARKER, type=bool) is True
    assert not any(key.startswith(PROBE) for key in new.allKeys())


def test_a_fresh_dev_install_marks_both_stores(clean, monkeypatch):
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    assert copy_legacy_settings_once() == {}
    for app in (SHARED_APP, DEV):
        new = _settings(SETTINGS_ORG, app)
        assert new.value(LEGACY_COPY_MARKER, type=bool) is True
        assert not any(key.startswith(PROBE) for key in new.allKeys())


def test_a_failed_write_is_not_marked_and_retries(clean, monkeypatch):
    """A marker must never say the copy happened when the new store could not
    be written. The next launch tries again and finishes the job."""
    import PySide6.QtCore as qtcore

    _legacy(SHARED_APP, legacy_probe_name="Ada")
    real_status = qtcore.QSettings.status

    def failing_status(self):
        if self.organizationName() == SETTINGS_ORG:
            return qtcore.QSettings.AccessError
        return real_status(self)

    monkeypatch.setattr(qtcore.QSettings, "status", failing_status)
    assert copy_legacy_settings_once() == {}
    assert not _settings(SETTINGS_ORG, SHARED_APP).contains(LEGACY_COPY_MARKER)

    monkeypatch.setattr(qtcore.QSettings, "status", real_status)
    copy_legacy_settings_once()
    new = _settings(SETTINGS_ORG, SHARED_APP)
    assert new.value("legacy_probe_name") == "Ada"
    assert new.value(LEGACY_COPY_MARKER, type=bool) is True


def test_an_unreadable_old_store_is_not_marked(clean, monkeypatch):
    import PySide6.QtCore as qtcore

    _legacy(SHARED_APP, legacy_probe_name="Ada")
    real_status = qtcore.QSettings.status

    def failing_status(self):
        if self.organizationName() == LEGACY_SETTINGS_ORG:
            return qtcore.QSettings.FormatError
        return real_status(self)

    monkeypatch.setattr(qtcore.QSettings, "status", failing_status)
    assert copy_legacy_settings_once() == {}
    assert not _settings(SETTINGS_ORG, SHARED_APP).contains(LEGACY_COPY_MARKER)


def test_the_copy_never_raises(clean, monkeypatch):
    import PySide6.QtCore as qtcore

    def boom(self):
        raise RuntimeError("store unavailable")

    _legacy(SHARED_APP, legacy_probe_name="Ada")
    with monkeypatch.context() as patch:
        patch.setattr(qtcore.QSettings, "allKeys", boom)
        assert copy_legacy_settings_once() == {}
        assert copy_legacy_series_settings_once(CODE) == {}


def test_only_what_was_stored_for_the_app_is_copied(clean):
    """A value in the old organization-wide store is a fallback the old store
    reads through, not something stored for the app. It stays behind."""
    from PySide6.QtCore import QSettings

    org_wide = QSettings(LEGACY_SETTINGS_ORG)
    org_wide.setValue("legacy_probe_org_wide", "fallback")
    org_wide.sync()
    try:
        _legacy(SHARED_APP, legacy_probe_name="Ada")
        assert _settings(LEGACY_SETTINGS_ORG, SHARED_APP).contains(
            "legacy_probe_org_wide"
        )

        copied = copy_legacy_settings_once()

        assert copied[SHARED_APP] == ["legacy_probe_name"]
        new = _settings(SETTINGS_ORG, SHARED_APP)
        new.setFallbacksEnabled(False)
        assert not new.contains("legacy_probe_org_wide")
    finally:
        org_wide = QSettings(LEGACY_SETTINGS_ORG)
        org_wide.remove("legacy_probe_org_wide")
        org_wide.sync()


def test_the_dev_app_copies_its_own_store_and_the_shared_one(clean, monkeypatch):
    """Then the Dev fold works on the copied stores: a Dev value the shared
    store lacked still reaches it."""
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    _legacy(SHARED_APP, legacy_probe_shared="stable")
    _legacy(DEV, legacy_probe_dev_only="dev")

    copied = copy_legacy_settings_once()
    assert set(copied) == {SHARED_APP, DEV}
    assert _settings(SETTINGS_ORG, DEV).value("legacy_probe_dev_only") == "dev"

    assert fold_flavor_settings_once() is True
    shared = _settings(SETTINGS_ORG, SHARED_APP)
    assert shared.value("legacy_probe_shared") == "stable"
    assert shared.value("legacy_probe_dev_only") == "dev"


def test_an_old_dev_store_that_was_already_folded_stays_folded(clean, monkeypatch):
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    _legacy(DEV, **{FOLD_MARKER: True, "legacy_probe_dev_only": "dev"})

    copy_legacy_settings_once()

    assert _settings(SETTINGS_ORG, DEV).value(FOLD_MARKER, type=bool) is True
    assert fold_flavor_settings_once() is False


def test_the_stable_app_never_opens_a_dev_store(clean):
    _legacy(DEV, legacy_probe_dev_only="dev")
    assert set(copy_legacy_settings_once()) <= {SHARED_APP}
    assert not _settings(SETTINGS_ORG, DEV).contains("legacy_probe_dev_only")


# --- per-series stores ---------------------------------------------------------


def test_a_series_store_is_copied_when_the_series_opens(clean):
    app = f"{SHARED_APP}-{CODE}"
    _legacy(app, legacy_probe_backup_dir="/backups", legacy_probe_layout="{}")
    before = _bytes(LEGACY_SETTINGS_ORG, app)

    copied = copy_legacy_series_settings_once(CODE)

    new = _settings(SETTINGS_ORG, app)
    assert new.value("legacy_probe_backup_dir") == "/backups"
    assert new.value("legacy_probe_layout") == "{}"
    assert new.value(LEGACY_COPY_MARKER, type=bool) is True
    assert set(copied[app]) == {"legacy_probe_backup_dir", "legacy_probe_layout"}
    _settings(LEGACY_SETTINGS_ORG, app).sync()
    assert _bytes(LEGACY_SETTINGS_ORG, app) == before

    new.setValue("legacy_probe_backup_dir", "/elsewhere")
    new.sync()
    assert copy_legacy_series_settings_once(CODE) == {}
    assert _settings(SETTINGS_ORG, app).value("legacy_probe_backup_dir") == "/elsewhere"


def test_a_series_with_no_old_store_gets_no_new_one(clean):
    app = f"{SHARED_APP}-{CODE}"
    path = _settings(SETTINGS_ORG, app).fileName()
    existed = os.path.exists(path)

    assert copy_legacy_series_settings_once(CODE) == {}

    assert not _settings(SETTINGS_ORG, app).contains(LEGACY_COPY_MARKER)
    assert os.path.exists(path) == existed


def test_a_series_store_already_holding_every_old_key_is_marked(clean):
    """Nothing to copy still counts as copied once the old store had values,
    so a key removed from the new store later is not brought back."""
    app = f"{SHARED_APP}-{CODE}"
    _legacy(app, legacy_probe_backup_dir="/old")
    new = _settings(SETTINGS_ORG, app)
    new.setValue("legacy_probe_backup_dir", "/new")
    new.sync()

    assert copy_legacy_series_settings_once(CODE) == {}
    assert _settings(SETTINGS_ORG, app).value(LEGACY_COPY_MARKER, type=bool) is True

    new = _settings(SETTINGS_ORG, app)
    new.remove("legacy_probe_backup_dir")
    new.sync()
    copy_legacy_series_settings_once(CODE)
    assert not _settings(SETTINGS_ORG, app).contains("legacy_probe_backup_dir")


def test_a_series_needs_a_code(clean):
    assert copy_legacy_series_settings_once("") == {}
    assert copy_legacy_series_settings_once(None) == {}


def test_the_dev_app_copies_both_series_stores(clean, monkeypatch):
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    _legacy(f"{SHARED_APP}-{CODE}", legacy_probe_backup_dir="/stable")
    _legacy(f"{DEV}-{CODE}", legacy_probe_layout="{}")

    copy_legacy_series_settings_once(CODE)
    assert fold_series_settings_once(CODE) is True

    shared = _settings(SETTINGS_ORG, f"{SHARED_APP}-{CODE}")
    assert shared.value("legacy_probe_backup_dir") == "/stable"
    assert shared.value("legacy_probe_layout") == "{}"


# --- where it runs -------------------------------------------------------------


def test_startup_copies_before_the_dev_fold():
    from PyReconstruct import run

    source = inspect.getsource(run.runPyReconstruct)
    copy = source.index("copy_legacy_settings_once()")
    fold = source.index("fold_flavor_settings_once()")
    app = source.index("QApplication(sys.argv)")
    assert copy < fold < app


def test_the_window_copies_the_series_store_before_the_fold():
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    source = inspect.getsource(MainWindow._foldSeriesSettings)
    assert source.index("copy_legacy_series_settings_once(") < source.index(
        "fold_series_settings_once(self.series.code)"
    )


def test_the_window_copies_the_open_series(main_window, clean):
    code = main_window.series.code
    assert code, "the fixture series carries a code"
    app = f"{SHARED_APP}-{code}"
    old = _legacy(app, legacy_probe_window="old")
    try:
        main_window._foldSeriesSettings()
        assert _settings(SETTINGS_ORG, app).value("legacy_probe_window") == "old"
    finally:
        for org in (SETTINGS_ORG, LEGACY_SETTINGS_ORG):
            s = _settings(org, app)
            s.remove("legacy_probe_window")
            s.remove(LEGACY_COPY_MARKER)
            s.sync()
        old.sync()


# --- a copy that fails holds the Dev fold until it succeeds ----------------------


def _unreadable_legacy(monkeypatch, app):
    """Make ``KHLab / <app>`` report a read error, as a damaged store would."""
    import PySide6.QtCore as qtcore

    cls = qtcore.QSettings
    real_status = cls.status

    def status(self):
        if (self.organizationName(), self.applicationName()) == (
            LEGACY_SETTINGS_ORG, app,
        ):
            return cls.FormatError
        return real_status(self)

    monkeypatch.setattr(cls, "status", status)


def _launch():
    """The settings steps of ``run.runPyReconstruct``, in its order."""
    result = copy_legacy_settings_once()
    if result.complete:
        fold_flavor_settings_once()
    return result


def test_startup_folds_only_after_a_complete_copy():
    from PyReconstruct import run

    source = inspect.getsource(run.runPyReconstruct)
    assert "if copy_legacy_settings_once().complete:" in source


def test_a_failed_shared_copy_keeps_the_dev_value_out(clean, monkeypatch):
    """The stable store's copy fails on a Dev launch. The fold waits, so the
    Dev value cannot take the shared key the stable value is still owed."""
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    _legacy(SHARED_APP, legacy_probe_theme="stable")
    _legacy(DEV, legacy_probe_theme="dev", legacy_probe_dev_only="dev")

    with monkeypatch.context() as broken:
        _unreadable_legacy(broken, SHARED_APP)
        assert _launch().complete is False

    shared = _settings(SETTINGS_ORG, SHARED_APP)
    assert not shared.contains("legacy_probe_theme")
    assert not _settings(SETTINGS_ORG, DEV).contains(FOLD_MARKER)

    assert _launch().complete is True

    shared = _settings(SETTINGS_ORG, SHARED_APP)
    assert shared.value("legacy_probe_theme") == "stable"
    assert shared.value("legacy_probe_dev_only") == "dev"
    assert _settings(SETTINGS_ORG, DEV).value(FOLD_MARKER, type=bool) is True


def test_a_failed_dev_copy_leaves_the_dev_store_unfolded(clean, monkeypatch):
    """The Dev store's copy fails. The fold waits instead of marking the
    empty Dev store as folded, so its preferences still reach the shared
    store once the copy succeeds."""
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    _legacy(DEV, legacy_probe_dev_only="dev")

    with monkeypatch.context() as broken:
        _unreadable_legacy(broken, DEV)
        assert _launch().complete is False

    assert not _settings(SETTINGS_ORG, DEV).contains(FOLD_MARKER)
    assert not _settings(SETTINGS_ORG, SHARED_APP).contains("legacy_probe_dev_only")

    assert _launch().complete is True

    assert _settings(SETTINGS_ORG, SHARED_APP).value("legacy_probe_dev_only") == "dev"
    assert _settings(SETTINGS_ORG, DEV).value(FOLD_MARKER, type=bool) is True


def test_a_marker_that_does_not_land_is_a_failed_copy(clean, monkeypatch):
    """The last write is the marker. If it fails, the copy is not finished:
    the result says so and the Dev fold waits."""
    import PySide6.QtCore as qtcore

    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    _legacy(SHARED_APP, legacy_probe_theme="stable")
    _legacy(DEV, legacy_probe_dev_only="dev")
    cls = qtcore.QSettings
    real_status = cls.status

    def status(self):
        if (
            (self.organizationName(), self.applicationName())
            == (SETTINGS_ORG, SHARED_APP)
            and self.contains(LEGACY_COPY_MARKER)
        ):
            return cls.AccessError
        return real_status(self)

    with monkeypatch.context() as broken:
        broken.setattr(cls, "status", status)
        result = _launch()
    assert result.complete is False
    assert not _settings(SETTINGS_ORG, DEV).contains(FOLD_MARKER)


@pytest.fixture
def window_series(main_window, clean, monkeypatch):
    """The open series' stores, wiped before and after, in the Dev flavor."""
    code = main_window.series.code
    assert code, "the fixture series carries a code"
    apps = (f"{SHARED_APP}-{code}", f"{DEV}-{code}")

    def wipe():
        for org in (SETTINGS_ORG, LEGACY_SETTINGS_ORG):
            for app in apps:
                s = _settings(org, app)
                for key in list(s.allKeys()):
                    if key.startswith(PROBE) or key in (
                        LEGACY_COPY_MARKER, FOLD_MARKER,
                    ):
                        s.remove(key)
                s.sync()

    wipe()
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    yield main_window, apps
    wipe()


def test_the_window_holds_the_series_fold_after_a_failed_shared_copy(
    window_series, monkeypatch,
):
    window, (shared_app, dev_app) = window_series
    _legacy(shared_app, legacy_probe_backup="stable")
    _legacy(dev_app, legacy_probe_backup="dev")

    with monkeypatch.context() as broken:
        _unreadable_legacy(broken, shared_app)
        window._foldSeriesSettings()

    assert not _settings(SETTINGS_ORG, shared_app).contains("legacy_probe_backup")
    assert not _settings(SETTINGS_ORG, dev_app).contains(FOLD_MARKER)

    window._foldSeriesSettings()

    # the fold ran and the stable value kept its key; a per-series Dev store
    # that gave nothing stays unmarked by design
    assert _settings(SETTINGS_ORG, shared_app).value("legacy_probe_backup") == "stable"


def test_the_window_folds_the_series_dev_store_once_its_copy_succeeds(
    window_series, monkeypatch,
):
    window, (shared_app, dev_app) = window_series
    _legacy(dev_app, legacy_probe_dev_only="dev")

    with monkeypatch.context() as broken:
        _unreadable_legacy(broken, dev_app)
        window._foldSeriesSettings()

    assert not _settings(SETTINGS_ORG, dev_app).contains(FOLD_MARKER)
    assert not _settings(SETTINGS_ORG, shared_app).contains("legacy_probe_dev_only")

    window._foldSeriesSettings()

    assert _settings(SETTINGS_ORG, shared_app).value("legacy_probe_dev_only") == "dev"
    assert _settings(SETTINGS_ORG, dev_app).value(FOLD_MARKER, type=bool) is True
