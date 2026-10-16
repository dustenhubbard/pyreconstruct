"""While a store is owed its copy from ``KHLab``, every call that can change it
waits unless it is a user action.

``GuardedSettings`` checks each such call when it is made: ``setValue``,
``remove``, ``clear`` and each call of an array write. An automatic writer of
any of these, including one the app does not have yet and one that follows a
user action, must leave the store as the copy will expect it. The user's own
changes save at once and win over the retry.
"""

import pytest
from PySide6.QtCore import QByteArray, QSettings

from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants import settings_domain as D
from PyReconstruct.modules.constants.settings_domain import (
    GuardedSettings, user_action,
)

from settings_copy_helpers import DEV, empty_stores, fail_copy

pytestmark = pytest.mark.gui

GLOBAL = D.SHARED_APP
SERIES_CODE = "GUARDTEST"
SERIES = f"{D.SHARED_APP}-{SERIES_CODE}"


def _copy(code):
    if code:
        return D.copy_legacy_series_settings_once(code)
    return D.copy_legacy_settings_once()


@pytest.fixture
def owed(qapp, monkeypatch, request):
    """A store whose copy failed: the global one (``None``) or a series'.

    Its old store holds one value and a two-entry array. Yields the code, the
    store's application name and the new store, read raw.
    """
    code = request.param
    app = SERIES if code else GLOBAL
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    empty_stores(GLOBAL, DEV, SERIES)
    old = QSettings(D.LEGACY_SETTINGS_ORG, app)
    old.setValue("guard/choice", "legacy")
    old.beginWriteArray("guard/cache", 2)
    old.setArrayIndex(0)
    old.setValue("name", "legacy-a")
    old.setArrayIndex(1)
    old.setValue("name", "legacy-b")
    old.endArray()
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken, app)
        assert not _copy(code).complete
    assert D.store_copy_pending(app)
    yield code, app, QSettings(D.SETTINGS_ORG, app)
    empty_stores(GLOBAL, DEV, SERIES)


def _array_size(settings, prefix):
    size = settings.beginReadArray(prefix)
    settings.endArray()
    return size


SCOPES = pytest.mark.parametrize(
    "owed", [None, SERIES_CODE], indirect=True, ids=["global", "series"],
)


@SCOPES
def test_an_automatic_set_and_remove_wait(owed):
    code, app, new = owed
    guarded = QSettingsStore()._settings(code)
    guarded.setValue("guard/choice", "automatic")
    guarded.setValue("guard/new", "automatic")
    guarded.remove("guard/choice")
    guarded.sync()
    assert not new.contains("guard/choice")
    assert not new.contains("guard/new")
    assert _copy(code).complete
    assert new.value("guard/choice") == "legacy"


@SCOPES
def test_an_automatic_array_write_waits(owed):
    code, app, new = owed
    guarded = QSettingsStore()._settings(code)
    guarded.beginWriteArray("guard/cache", 0)
    guarded.endArray()
    guarded.beginWriteArray("guard/other")
    guarded.setArrayIndex(0)
    guarded.setValue("name", "automatic")
    guarded.endArray()
    guarded.setValue("guard/after", "automatic")
    guarded.sync()
    new.sync()
    assert new.allKeys() == []
    assert guarded.group() == ""
    assert _copy(code).complete
    assert _array_size(new, "guard/cache") == 2
    assert not new.contains("guard/other/size")


@SCOPES
def test_an_automatic_clear_waits(owed):
    code, app, new = owed
    with user_action():
        QSettingsStore()._settings(code).setValue("guard/kept", "chosen")
    guarded = QSettingsStore()._settings(code)
    guarded.clear()
    guarded.sync()
    new.sync()
    assert new.value("guard/kept") == "chosen"
    assert _copy(code).complete
    assert new.value("guard/kept") == "chosen"
    assert new.value("guard/choice") == "legacy"


@SCOPES
def test_a_user_array_write_saves_and_wins(owed):
    code, app, new = owed
    guarded = QSettingsStore()._settings(code)
    with user_action():
        guarded.beginWriteArray("guard/cache", 1)
        guarded.setArrayIndex(0)
        guarded.setValue("name", "chosen")
        guarded.endArray()
    guarded.sync()
    new.sync()
    assert _array_size(new, "guard/cache") == 1
    assert _copy(code).complete
    assert _array_size(new, "guard/cache") == 1


def test_a_call_that_is_not_checked_is_not_offered(qapp):
    guarded = GuardedSettings(QSettings(D.SETTINGS_ORG, GLOBAL))
    for name in ("setPath", "setDefaultFormat", "setFallbacksEnabled",
                 "setAtomicSyncRequired", "setParent", "deleteLater"):
        with pytest.raises(AttributeError):
            getattr(guarded, name)
    assert guarded.organizationName() == D.SETTINGS_ORG


@pytest.mark.parametrize(
    "kind", ["theme", "clear_recents", "moved_window", "dialog"],
)
def test_user_actions_save_and_win_the_retry(main_window, monkeypatch, tmp_path, kind):
    from PyReconstruct.modules.gui.dialog.file_dialog import FileDialog
    from PyReconstruct.modules.gui.main import main_window as M

    main_window.series.setSettingsStore(QSettingsStore())
    new = QSettings(D.SETTINGS_ORG, GLOBAL)
    old = QSettings(D.LEGACY_SETTINGS_ORG, GLOBAL)
    seed = {
        "theme": "qdark",
        "recently_opened_series": '["/old.jser"]',
        "window/geometry": QByteArray(b"old-geometry"),
        "last_folder": "/old-folder",
    }
    for key, value in seed.items():
        new.remove(key)
        old.setValue(key, value)
    new.remove(D.LEGACY_COPY_MARKER)
    new.sync()
    old.sync()
    monkeypatch.setitem(D._copy_pending, GLOBAL, True)
    if kind == "theme":
        monkeypatch.setattr(
            M.QuickDialog, "get",
            lambda *a, **k: ([[("default", True), ("dark", False)]], True),
        )
        main_window.setTheme()
        key, expected = "theme", "default"
    elif kind == "clear_recents":
        main_window.clearRecentSeries()
        key, expected = "recently_opened_series", "[]"
    elif kind == "moved_window":
        main_window.move(main_window.x() + 40, main_window.y() + 30)
        main_window.series.modified = False
        main_window.close()
        key, expected = "window/geometry", main_window.saveGeometry()
    else:
        FileDialog.updateSettings(str(tmp_path / "chosen.jser"))
        key, expected = "last_folder", str(tmp_path)
    new.sync()
    try:
        assert new.value(key) == expected
        assert D.copy_legacy_settings_once().complete
        assert new.value(key) == expected
    finally:
        for org in (D.SETTINGS_ORG, D.LEGACY_SETTINGS_ORG):
            s = QSettings(org, GLOBAL)
            for k in seed:
                s.remove(k)
            s.remove(D.LEGACY_COPY_MARKER)
            s.sync()
        D._copy_pending.pop(GLOBAL, None)


@SCOPES
def test_an_automatic_end_of_a_user_array_waits(owed):
    code, app, new = owed
    guarded = QSettingsStore()._settings(code)
    with user_action():
        guarded.beginWriteArray("guard/cache")
    guarded.endArray()
    guarded.sync()
    new.sync()
    assert new.allKeys() == []
    assert _copy(code).complete
    assert _array_size(new, "guard/cache") == 2


@SCOPES
def test_an_automatic_array_index_waits(owed):
    code, app, new = owed
    guarded = QSettingsStore()._settings(code)
    with user_action():
        guarded.beginWriteArray("guard/cache")
        guarded.setArrayIndex(0)
        guarded.setValue("name", "chosen")
    guarded.setArrayIndex(8)
    guarded.setValue("name", "automatic")
    with user_action():
        guarded.endArray()
    guarded.sync()
    new.sync()
    assert _array_size(new, "guard/cache") == 1
    assert new.value("guard/cache/1/name") == "chosen"
    assert not new.contains("guard/cache/9/name")
    assert _copy(code).complete
    assert _array_size(new, "guard/cache") == 1


@SCOPES
@pytest.mark.parametrize("group", ["guard/cache", "scratch"])
def test_an_automatic_write_in_a_group_waits(owed, group):
    code, app, new = owed
    guarded = QSettingsStore()._settings(code)
    guarded.beginGroup(group)
    guarded.setValue("size", 0)
    guarded.remove("1")
    guarded.endGroup()
    guarded.beginReadArray("missing")
    guarded.setArrayIndex(6)
    guarded.endArray()
    guarded.sync()
    new.sync()
    assert new.allKeys() == []
    assert _copy(code).complete
    assert _array_size(new, "guard/cache") == 2


@pytest.mark.parametrize("size", [-1, 3])
def test_a_guarded_array_write_stores_what_qt_stores(qapp, size):
    empty_stores(GLOBAL, SERIES)
    plain = QSettings(D.SETTINGS_ORG, GLOBAL)
    guarded = QSettingsStore()._settings(SERIES_CODE)
    assert not D.store_copy_pending(SERIES)
    for settings in (plain, guarded):
        settings.setValue("guard/cache/size", 7)
        settings.beginGroup("outer")
        settings.beginWriteArray("list", size)
        settings.setValue("before", "first")
        for i, name in ((0, "a"), (2, "c")):
            settings.setArrayIndex(i)
            settings.setValue("name", name)
        settings.endArray()
        settings.endGroup()
        settings.beginWriteArray("guard/cache", size)
        settings.endArray()
        settings.sync()
    stored = QSettings(D.SETTINGS_ORG, SERIES)
    assert {k: stored.value(k) for k in stored.allKeys()} == {
        k: plain.value(k) for k in plain.allKeys()
    }
    assert stored.allKeys()
    empty_stores(GLOBAL, SERIES)


def test_reading_or_grouping_inside_an_array_write_is_refused(qapp):
    guarded = QSettingsStore()._settings(SERIES_CODE)
    guarded.beginWriteArray("guard/cache")
    for call in (
        lambda: guarded.value("name"), lambda: guarded.beginGroup("g"),
        lambda: guarded.beginReadArray("r"), guarded.clear,
    ):
        with pytest.raises(RuntimeError):
            call()
    guarded.endArray()
    assert guarded.group() == ""


def test_every_public_qsettings_call_is_checked_or_not_offered(qapp):
    import qsettings_isolation

    guarded = GuardedSettings(QSettings(D.SETTINGS_ORG, GLOBAL))
    checked = {
        "setValue", "remove", "clear", "beginReadArray", "beginWriteArray",
        "setArrayIndex", "endArray",
    }
    for name in dir(qsettings_isolation._real_qsettings):
        if name.startswith("_"):
            continue
        if name in checked:
            assert name in GuardedSettings.__dict__, name
        elif name in GuardedSettings.READS:
            getattr(guarded, name)
        else:
            with pytest.raises(AttributeError):
                getattr(guarded, name)
