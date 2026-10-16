"""While a store is owed its copy from ``KHLab``, every call that can change it
waits unless it is a user action.

``GuardedSettings`` checks each such call: ``setValue``, ``remove``,
``clear`` and an array write. An automatic writer of any of these, including
one the app does not have yet, must leave the store as the copy will expect
it. The user's own changes save at once and win over the retry.
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
