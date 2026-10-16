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
    """Remove every probe key and marker these tests write, in both orgs, and
    forget what this session learned about which copies are pending."""
    from PyReconstruct.modules.constants import settings_domain

    getattr(settings_domain, "_copy_pending", {}).clear()
    getattr(settings_domain, "_unparsable_legacy", set()).clear()
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
    """Make ``KHLab / <app>`` report a read error, as a store that cannot be
    opened would. A damaged file is test_a_damaged_old_file_*: Qt keeps its
    parse, so it cannot recover within a session the way this one does."""
    import PySide6.QtCore as qtcore

    cls = qtcore.QSettings
    real_status = cls.status

    def status(self):
        if (self.organizationName(), self.applicationName()) == (
            LEGACY_SETTINGS_ORG, app,
        ):
            return cls.AccessError
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
    assert "settings_copied = copy_legacy_settings_once().complete" in source
    assert source.index("if settings_copied:") < source.index(
        "fold_flavor_settings_once()"
    )


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
        from PyReconstruct.modules.constants import settings_domain

        getattr(settings_domain, "_copy_pending", {}).clear()
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


# --- a session between a failed copy and its retry ------------------------------


@pytest.fixture
def real_store_series(main_window):
    """The open series, reading through the QSettings-backed store."""
    from PyReconstruct.modules.backend.settings_store import QSettingsStore

    series = main_window.series
    before = getattr(series, "_settings_store", None)
    series.setSettingsStore(QSettingsStore())
    yield series
    series.setSettingsStore(before)


def _forget(app, key):
    s = _settings(SETTINGS_ORG, app)
    s.remove(key)
    s.sync()


def test_a_session_after_a_failed_copy_does_not_save_defaults(
    real_store_series, clean, monkeypatch,
):
    """Failed copy, then a normal session that reads an option the new store
    lacks, then a successful retry: the old value wins, not the default the
    session read."""
    series = real_store_series
    _forget(SHARED_APP, "left_handed")
    _legacy(SHARED_APP, left_handed=True)
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, SHARED_APP)
            assert _launch().complete is False

        assert series.getOption("left_handed") is False
        assert not _settings(SETTINGS_ORG, SHARED_APP).contains("left_handed")

        assert _launch().complete is True
        assert _settings(SETTINGS_ORG, SHARED_APP).value("left_handed", type=bool) is True
        assert series.getOption("left_handed") is True
    finally:
        _forget(SHARED_APP, "left_handed")
        old = _settings(LEGACY_SETTINGS_ORG, SHARED_APP)
        old.remove("left_handed")
        old.sync()


def test_a_session_after_a_failed_series_copy_does_not_save_defaults(
    real_store_series, window_series, monkeypatch,
):
    series = real_store_series
    window, (shared_app, dev_app) = window_series
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    _forget(shared_app, "autobackup")
    _legacy(shared_app, autobackup=True)
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, shared_app)
            window._foldSeriesSettings()

        assert series.getOption("autobackup") is False
        assert not _settings(SETTINGS_ORG, shared_app).contains("autobackup")

        window._foldSeriesSettings()
        assert _settings(SETTINGS_ORG, shared_app).value("autobackup", type=bool) is True
        assert series.getOption("autobackup") is True
    finally:
        for org in (SETTINGS_ORG, LEGACY_SETTINGS_ORG):
            s = _settings(org, shared_app)
            s.remove("autobackup")
            s.sync()


def test_an_owed_store_takes_only_the_users_own_writes(clean, monkeypatch):
    """One rule for every writer: while a store is owed its copy, a write is
    saved only inside ``user_action``, and a default read there is not."""
    from PyReconstruct.modules.backend.settings_store import QSettingsStore
    from PyReconstruct.modules.constants.settings_domain import (
        settings_for, user_action,
    )

    _legacy(SHARED_APP, legacy_probe_kept="old")
    with monkeypatch.context() as broken:
        _unreadable_legacy(broken, SHARED_APP)
        assert copy_legacy_settings_once().complete is False
    new = _settings(SETTINGS_ORG, SHARED_APP)
    store = QSettingsStore()

    settings_for("username").setValue("legacy_probe_automatic", "no")
    store.set_value(None, "legacy_probe_kept", "automatic")
    assert not new.contains("legacy_probe_automatic")
    assert not new.contains("legacy_probe_kept")

    with user_action():
        settings_for("username").setValue("legacy_probe_chosen", "yes")
        assert store.may_save_defaults(None) is False
    assert new.value("legacy_probe_chosen") == "yes"

    assert copy_legacy_settings_once().complete is True
    assert new.value("legacy_probe_kept") == "old"
    settings_for("username").setValue("legacy_probe_automatic", "now")
    assert new.value("legacy_probe_automatic") == "now"


def test_a_store_with_old_values_and_no_marker_is_pending(clean):
    """Before the copy has run at all, the same rule holds."""
    from PyReconstruct.modules.backend.settings_store import QSettingsStore

    _legacy(SHARED_APP, legacy_probe_name="Ada")
    assert QSettingsStore().may_save_defaults(None) is False
    assert copy_legacy_settings_once().complete is True
    assert QSettingsStore().may_save_defaults(None) is True


def test_the_update_check_default_waits_for_the_copy(clean, monkeypatch):
    from PyReconstruct.modules.backend.settings_migrations import (
        UPDATE_CHECK_DEFAULT_APPLIED_KEY,
        apply_update_check_on_startup_default,
    )
    from PyReconstruct.modules.backend.settings_store import QSettingsStore

    _legacy(SHARED_APP, legacy_probe_name="Ada")
    new = _settings(SETTINGS_ORG, SHARED_APP)
    had = new.contains(UPDATE_CHECK_DEFAULT_APPLIED_KEY)
    marker = new.value(UPDATE_CHECK_DEFAULT_APPLIED_KEY)
    new.remove(UPDATE_CHECK_DEFAULT_APPLIED_KEY)
    new.sync()
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, SHARED_APP)
            assert _launch().complete is False
        apply_update_check_on_startup_default(QSettingsStore())
        assert not _settings(SETTINGS_ORG, SHARED_APP).contains(
            UPDATE_CHECK_DEFAULT_APPLIED_KEY
        )
    finally:
        new = _settings(SETTINGS_ORG, SHARED_APP)
        if had:
            new.setValue(UPDATE_CHECK_DEFAULT_APPLIED_KEY, marker)
        else:
            new.remove(UPDATE_CHECK_DEFAULT_APPLIED_KEY)
        new.sync()


def test_a_marker_that_failed_to_sync_is_not_trusted_on_reopen(
    window_series, monkeypatch,
):
    """The marker write fails, the series is opened again in the same
    session: the marker visible in memory does not count, so the fold still
    waits. Once a sync succeeds the fold runs."""
    import PySide6.QtCore as qtcore

    window, (shared_app, dev_app) = window_series
    _legacy(dev_app, legacy_probe_dev_only="dev")
    cls = qtcore.QSettings
    real_status = cls.status

    def status(self):
        if (
            (self.organizationName(), self.applicationName())
            == (SETTINGS_ORG, dev_app)
            and self.contains(LEGACY_COPY_MARKER)
        ):
            return cls.AccessError
        return real_status(self)

    with monkeypatch.context() as broken:
        broken.setattr(cls, "status", status)
        window._foldSeriesSettings()
        window._foldSeriesSettings()
        assert not copy_legacy_series_settings_once(window.series.code).complete

    assert not _settings(SETTINGS_ORG, shared_app).contains("legacy_probe_dev_only")
    assert not _settings(SETTINGS_ORG, dev_app).contains(FOLD_MARKER)

    window._foldSeriesSettings()
    assert _settings(SETTINGS_ORG, shared_app).value("legacy_probe_dev_only") == "dev"


# --- what the program writes on its own waits for the copy ------------------------


def test_a_failed_dev_copy_keeps_defaults_out_of_the_shared_store(
    real_store_series, clean, monkeypatch,
):
    """Only the Dev store's copy fails. The shared store's own copy finished,
    but the fold into it is still owed, so a default read meanwhile is not
    saved there: after the retry the Dev value arrives through the fold."""
    series = real_store_series
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    _forget(SHARED_APP, "left_handed")
    _legacy(DEV, left_handed=True)
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, DEV)
            assert _launch().complete is False

        assert series.getOption("left_handed") is False
        assert not _settings(SETTINGS_ORG, SHARED_APP).contains("left_handed")

        assert _launch().complete is True
        assert _settings(SETTINGS_ORG, SHARED_APP).value("left_handed", type=bool) is True
    finally:
        _forget(SHARED_APP, "left_handed")
        for app in (DEV,):
            for org in (SETTINGS_ORG, LEGACY_SETTINGS_ORG):
                s = _settings(org, app)
                s.remove("left_handed")
                s.sync()


def test_the_username_waits_for_a_failed_copy(
    real_store_series, main_window, clean, monkeypatch,
):
    """The launch saves the OS login as the username when none is stored.
    After a failed copy it must not: the retry brings the stored name back."""
    new = _settings(SETTINGS_ORG, SHARED_APP)
    had = new.value("username")
    _forget(SHARED_APP, "username")
    _legacy(SHARED_APP, username="legacy_probe_user")
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, SHARED_APP)
            assert _launch().complete is False

        main_window.resolveUsernameStartup()
        assert not _settings(SETTINGS_ORG, SHARED_APP).contains("username")

        assert _launch().complete is True
        assert _settings(SETTINGS_ORG, SHARED_APP).value("username") == "legacy_probe_user"
    finally:
        old = _settings(LEGACY_SETTINGS_ORG, SHARED_APP)
        old.remove("username")
        old.sync()
        new = _settings(SETTINGS_ORG, SHARED_APP)
        if had is not None:
            new.setValue("username", had)
        else:
            new.remove("username")
        new.sync()


def test_recent_series_wait_for_a_failed_copy(
    real_store_series, main_window, clean, monkeypatch,
):
    """Opening a series rewrites the recent list from what it reads. After a
    failed copy that list is empty, and saving it would drop the old one."""
    _forget(SHARED_APP, "recently_opened_series")
    _legacy(SHARED_APP, recently_opened_series='["/legacy/probe.jser"]')
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, SHARED_APP)
            assert _launch().complete is False

        main_window.addToRecentSeries("/new/probe.jser")
        assert not _settings(SETTINGS_ORG, SHARED_APP).contains(
            "recently_opened_series"
        )

        assert _launch().complete is True
        assert real_store_series.getOption("recently_opened_series") == [
            "/legacy/probe.jser"
        ]
    finally:
        for org in (SETTINGS_ORG, LEGACY_SETTINGS_ORG):
            s = _settings(org, SHARED_APP)
            s.remove("recently_opened_series")
            s.sync()


def test_the_list_layout_waits_for_a_failed_series_copy(
    real_store_series, window_series, monkeypatch,
):
    """Closing a series saves its open lists. After the series' copy failed,
    that would save the layout it opened with and hide the old one."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    window, (shared_app, dev_app) = window_series
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    _forget(shared_app, "list_layout")
    _legacy(shared_app, list_layout='{"legacy_probe": []}')
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, shared_app)
            window._foldSeriesSettings()

        MainWindow._captureListLayout(window)
        assert not _settings(SETTINGS_ORG, shared_app).contains("list_layout")

        window._foldSeriesSettings()
        assert _settings(SETTINGS_ORG, shared_app).value("list_layout") == (
            '{"legacy_probe": []}'
        )
    finally:
        for org in (SETTINGS_ORG, LEGACY_SETTINGS_ORG):
            s = _settings(org, shared_app)
            s.remove("list_layout")
            s.sync()


def test_startup_resets_the_whats_new_popup_only_after_a_complete_copy():
    """The reset decides from the stored keys whether this is a fresh
    install, and the keys are not there yet while the copy is owed."""
    from PyReconstruct import run

    source = inspect.getsource(run.runPyReconstruct)
    assert source.index("if settings_copied:") < source.index(
        "reset_whats_new_popup_startup()"
    )


def test_an_old_store_that_cannot_be_read_is_still_owed(clean, monkeypatch):
    """A read error is a copy to retry, the same as in the copy itself, even
    when the error leaves the old store looking empty."""
    import PySide6.QtCore as qtcore

    from PyReconstruct.modules.backend.settings_store import QSettingsStore
    from PyReconstruct.modules.constants.settings_domain import (
        legacy_copy_pending,
    )

    _unreadable_legacy(monkeypatch, SHARED_APP)
    monkeypatch.setattr(qtcore.QSettings, "allKeys", lambda self: [])

    assert legacy_copy_pending(SHARED_APP) is True
    assert QSettingsStore().may_save_defaults(None) is False


def _keep(*keys, apps=(SHARED_APP,)):
    """Remove ``keys`` from both organizations' ``apps`` stores."""
    for org in (SETTINGS_ORG, LEGACY_SETTINGS_ORG):
        for app in apps:
            s = _settings(org, app)
            for key in keys:
                s.remove(key)
            s.sync()


@pytest.fixture
def failed_copy(clean, monkeypatch, request):
    """A launch whose copy of ``request.param``'s old store failed: the shared
    store's own (``SHARED_APP``) or only the Dev store's (``DEV``).

    Yields the app whose old store to seed; call the returned function once it
    is seeded to run the failed launch."""
    app = request.param
    if app == DEV:
        monkeypatch.setenv("PYRECON_APP_NAME", DEV)

    def launch():
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, app)
            assert _launch().complete is False

    return app, launch


def _retry():
    assert _launch().complete is True
    return _settings(SETTINGS_ORG, SHARED_APP)


@pytest.mark.parametrize(
    "failed_copy", [SHARED_APP, DEV], indirect=True, ids=["shared", "dev"],
)
def test_building_the_file_menu_keeps_the_old_recent_list(
    failed_copy, real_store_series, tmp_path,
):
    """The File menu prunes missing paths from the recent list it reads, and
    saved that list every time it was built. After a failed copy the list
    read is empty, and saving it kept the old one from ever coming back."""
    from PyReconstruct.modules.gui.utils import getOpenRecentMenu

    app, launch = failed_copy
    recent = str(tmp_path / "recent.jser")
    open(recent, "w").close()
    _keep("recently_opened_series", apps=(SHARED_APP, app))
    _legacy(app, recently_opened_series=f'["{recent}"]')
    try:
        launch()
        getOpenRecentMenu(real_store_series, lambda **kw: None)
        assert not _settings(SETTINGS_ORG, SHARED_APP).contains(
            "recently_opened_series"
        )
        assert _retry().value("recently_opened_series") == f'["{recent}"]'
    finally:
        _keep("recently_opened_series", apps=(SHARED_APP, app))


def test_clear_recents_empties_the_list_while_the_copy_is_owed(
    real_store_series, main_window, clean, monkeypatch,
):
    _keep("recently_opened_series")
    _legacy(SHARED_APP, recently_opened_series='["/legacy/probe.jser"]')
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, SHARED_APP)
            assert _launch().complete is False

        main_window.clearRecentSeries()

        assert _retry().value("recently_opened_series") == "[]"
    finally:
        _keep("recently_opened_series")


def test_the_menu_still_prunes_missing_paths_once_copied(real_store_series, clean):
    from PyReconstruct.modules.gui.utils import getOpenRecentMenu

    _keep("recently_opened_series")
    try:
        assert copy_legacy_settings_once().complete is True
        real_store_series.setOption(
            "recently_opened_series", ["/no/such/probe.jser"]
        )
        getOpenRecentMenu(real_store_series, lambda **kw: None)
        assert real_store_series.getOption("recently_opened_series") == []
    finally:
        _keep("recently_opened_series")


@pytest.mark.parametrize(
    "failed_copy", [SHARED_APP, DEV], indirect=True, ids=["shared", "dev"],
)
@pytest.mark.parametrize("key", ["theme", "recently_opened_series"])
def test_a_window_opened_after_a_failed_copy_keeps_the_old_value(
    failed_copy, request, tmp_path, key,
):
    """Opening the window applies the theme and builds the File menu. Neither
    may save what it read while the old value is still to come."""
    app, launch = failed_copy
    recent = tmp_path / "recent.jser"
    recent.touch()
    value = "qdark" if key == "theme" else f'["{recent}"]'
    _keep(key, apps=(SHARED_APP, app))
    _legacy(app, **{key: value})
    try:
        launch()
        request.getfixturevalue("main_window")
        assert not _settings(SETTINGS_ORG, SHARED_APP).contains(key)
        assert _retry().value(key) == value
    finally:
        _keep(key, apps=(SHARED_APP, app))


@pytest.mark.parametrize(
    "failed_copy", [SHARED_APP, DEV], indirect=True, ids=["shared", "dev"],
)
def test_a_window_opened_after_a_failed_copy_keeps_the_old_palette_increment(
    failed_copy, request,
):
    """Building the palette shows the stored increment mode, and it saved
    that mode too. After a failed copy that is the default, and saving it
    kept the old choice from ever coming back."""
    app, launch = failed_copy
    _keep("palette_inc_all", apps=(SHARED_APP, app))
    _legacy(app, palette_inc_all=False)
    try:
        launch()
        request.getfixturevalue("main_window")
        assert not _settings(SETTINGS_ORG, SHARED_APP).contains("palette_inc_all")
        assert _retry().value("palette_inc_all", type=bool) is False
    finally:
        _keep("palette_inc_all", apps=(SHARED_APP, app))


def test_a_palette_increment_clicked_while_the_copy_is_owed_is_saved(
    real_store_series, main_window, clean, monkeypatch,
):
    _keep("palette_inc_all")
    _legacy(SHARED_APP, palette_inc_all=True)
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, SHARED_APP)
            assert _launch().complete is False

        # "Increment active only"
        main_window.mouse_palette.palette_side_buttons[3].click()

        assert _retry().value("palette_inc_all", type=bool) is False
    finally:
        _keep("palette_inc_all")


@pytest.mark.parametrize(
    "failed_copy", [SHARED_APP, DEV], indirect=True, ids=["shared", "dev"],
)
def test_applying_the_stored_theme_saves_nothing(failed_copy, real_store_series):
    from types import SimpleNamespace

    from PyReconstruct.modules.gui.main.main_window import MainWindow

    app, launch = failed_copy
    window = SimpleNamespace(series=real_store_series, field=None)
    _keep("theme", apps=(SHARED_APP, app))
    _legacy(app, theme="qdark")
    try:
        launch()
        MainWindow.applyTheme(window, real_store_series.getOption("theme"))
        assert _retry().value("theme") == "qdark"
    finally:
        _keep("theme", apps=(SHARED_APP, app))
        MainWindow.applyTheme(window, "default")


def test_a_theme_chosen_while_the_copy_is_owed_is_saved(
    real_store_series, main_window, clean, monkeypatch,
):
    from PyReconstruct.modules.gui.main import main_window as main_window_module

    _keep("theme")
    _legacy(SHARED_APP, theme="qdark")
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, SHARED_APP)
            assert _launch().complete is False

        monkeypatch.setattr(
            main_window_module.QuickDialog, "get",
            lambda *a, **kw: ([[("default", True), ("dark", False)]], True),
        )
        main_window.setTheme()

        assert _retry().value("theme") == "default"
    finally:
        _keep("theme")


@pytest.mark.parametrize("moved", [False, True])
def test_closing_the_window_keeps_the_old_position_unless_it_moved(
    request, clean, monkeypatch, moved,
):
    """The close saves the window's position. While the copy is owed, a
    window left where it opened is the default position, not a choice, and
    saving it would hide the one the copy brings."""
    from PySide6.QtCore import QByteArray

    _keep("window/geometry")
    _legacy(SHARED_APP, **{"window/geometry": QByteArray(b"legacy probe")})
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, SHARED_APP)
            assert _launch().complete is False

        window = request.getfixturevalue("main_window")
        if moved:
            window.move(window.x() + 40, window.y() + 30)
        window.series.modified = False
        assert window.close() is True

        stored = _retry().value("window/geometry")
        if moved:
            assert bytes(stored) != b"legacy probe"
        else:
            assert bytes(stored) == b"legacy probe"
    finally:
        _keep("window/geometry")


def test_the_whats_new_popup_waits_for_the_copy(clean, monkeypatch):
    """The popup records the version it shows. Shown after a failed copy, it
    also ignored a stored "don't show", and the version it saved replaced the
    one the copy was to bring."""
    from PyReconstruct.modules.gui.dialog.whats_new import maybe_show_whats_new

    keys = ("suppress_whatsnew", "last_whatsnew_version")
    new = _settings(SETTINGS_ORG, SHARED_APP)
    before = {key: new.value(key) for key in keys if new.contains(key)}
    _keep(*keys)
    _legacy(SHARED_APP, suppress_whatsnew=True, last_whatsnew_version="1.24.0")
    try:
        with monkeypatch.context() as broken:
            _unreadable_legacy(broken, SHARED_APP)
            assert _launch().complete is False

        shown = []
        assert maybe_show_whats_new(
            None, settings=_settings(SETTINGS_ORG, SHARED_APP),
            current="1.24.1", show=lambda *a: shown.append(a),
        ) is False
        assert shown == []

        stored = _retry()
        assert stored.value("last_whatsnew_version") == "1.24.0"
        assert stored.value("suppress_whatsnew", type=bool) is True
    finally:
        _keep(*keys)
        new = _settings(SETTINGS_ORG, SHARED_APP)
        for key, value in before.items():
            new.setValue(key, value)
        new.sync()


def _damaged_series_store(code):
    from pathlib import Path

    path = Path(_settings(LEGACY_SETTINGS_ORG, f"{SHARED_APP}-{code}").fileName())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[broken\nentry=value\n")
    return path


def test_a_damaged_old_file_stays_owed_when_opened_again(clean):
    """Qt keeps the first parse of a file for the session, and a second
    QSettings on it reports no error. The copy did not count that as a
    repaired file."""
    code = "LEGACYDAMAGED"
    path = _damaged_series_store(code)
    try:
        assert copy_legacy_series_settings_once(code).complete is False
        assert copy_legacy_series_settings_once(code).complete is False
        assert not _settings(SETTINGS_ORG, f"{SHARED_APP}-{code}").contains(
            LEGACY_COPY_MARKER
        )
    finally:
        path.unlink()
        new = _settings(SETTINGS_ORG, f"{SHARED_APP}-{code}")
        new.remove(LEGACY_COPY_MARKER)
        new.remove("broken/entry")
        new.sync()


def test_a_damaged_old_file_stays_owed_after_a_touch_qt_cannot_see(clean):
    """Qt parses a file again only when it sees the file change, and it reads
    the time to the millisecond. A touch below that is a change to Python and
    none to Qt, which hands back its first, partial parse."""
    from PySide6.QtCore import QFileInfo

    code = "LEGACYDAMAGED"
    path = _damaged_series_store(code)
    try:
        assert copy_legacy_series_settings_once(code).complete is False
        before = path.stat()
        qt_before = QFileInfo(str(path)).lastModified().toMSecsSinceEpoch()
        ms = before.st_mtime_ns // 1_000_000 * 1_000_000
        touched = ms + (2 if before.st_mtime_ns == ms + 1 else 1)
        os.utime(path, ns=(before.st_atime_ns, touched))
        assert path.stat().st_mtime_ns != before.st_mtime_ns
        assert QFileInfo(str(path)).lastModified().toMSecsSinceEpoch() == qt_before

        assert copy_legacy_series_settings_once(code).complete is False
        assert not _settings(SETTINGS_ORG, f"{SHARED_APP}-{code}").contains(
            LEGACY_COPY_MARKER
        )
    finally:
        path.unlink()
        new = _settings(SETTINGS_ORG, f"{SHARED_APP}-{code}")
        new.remove(LEGACY_COPY_MARKER)
        new.remove("broken/entry")
        new.sync()


def test_a_damaged_old_file_copies_at_the_next_launch_once_it_is_fixed(clean):
    from PyReconstruct.modules.constants import settings_domain

    code = "LEGACYDAMAGED"
    path = _damaged_series_store(code)
    try:
        assert copy_legacy_series_settings_once(code).complete is False
        path.write_text("[General]\nlegacy_probe_fixed=yes\n")
        assert copy_legacy_series_settings_once(code).complete is False

        # what a new launch starts without
        settings_domain._unparsable_legacy.clear()
        settings_domain._copy_pending.clear()
        assert copy_legacy_series_settings_once(code).complete is True
        new = _settings(SETTINGS_ORG, f"{SHARED_APP}-{code}")
        assert new.value("legacy_probe_fixed") == "yes"
    finally:
        path.unlink()
        new = _settings(SETTINGS_ORG, f"{SHARED_APP}-{code}")
        for key in (LEGACY_COPY_MARKER, "legacy_probe_fixed", "broken/entry"):
            new.remove(key)
        new.sync()
