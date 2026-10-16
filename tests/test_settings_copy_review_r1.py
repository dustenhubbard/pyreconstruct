"""Round 1 review of the settings move: values the program saved on its own
during a session whose copy from ``KHLab`` failed (the theme applied at
startup, the recent list rebuilt for the File menu, the What's new seen
version, an unmoved window's position) must not win over the stored ones when
the copy is retried. Plus the controls: a plain copy, a user's own change, a
per-series copy, and a damaged old file.

The concurrent-copy probe of that round is not kept: the race between two
copies of the app starting at the same moment was accepted.
"""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QByteArray, QSettings

from PyReconstruct.modules.constants import settings_domain as D
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.whats_new import maybe_show_whats_new
from PyReconstruct.modules.gui.main.main_window import MainWindow
from PyReconstruct.modules.gui.utils import getOpenRecentMenu

from settings_copy_review import DEV, DAMAGED, fail_copy, review_store

pytestmark = pytest.mark.gui


@pytest.fixture
def setup_store(qapp, monkeypatch):
    yield from review_store(monkeypatch)


def _old_store(monkeypatch, old, dev_only):
    """The old store the test seeds and fails: the shared one, or only the
    Dev app's own."""
    if not dev_only:
        return D.SHARED_APP, old
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    return DEV, QSettings(D.LEGACY_SETTINGS_ORG, DEV)


@pytest.mark.parametrize("dev_only", [False, True])
def test_theme_survives_retry(setup_store, monkeypatch, dev_only):
    series, old, new = setup_store
    app, old = _old_store(monkeypatch, old, dev_only)
    old.setValue("theme", "qdark")
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken, app)
        assert D.copy_legacy_settings_once().complete is False
    MainWindow.applyTheme(
        SimpleNamespace(series=series, field=None), series.getOption("theme")
    )
    assert D.copy_legacy_settings_once().complete is True
    D.fold_flavor_settings_once()
    assert new.value("theme") == "qdark"


@pytest.mark.parametrize("dev_only", [False, True])
def test_menu_preserves_recents(setup_store, monkeypatch, dev_only, tmp_path):
    series, old, new = setup_store
    app, old = _old_store(monkeypatch, old, dev_only)
    legacy_file = tmp_path / "existing-legacy.jser"
    legacy_file.touch()
    old.setValue("recently_opened_series", json.dumps([str(legacy_file)]))
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken, app)
        assert D.copy_legacy_settings_once().complete is False
    getOpenRecentMenu(series, lambda **kw: None)
    assert D.copy_legacy_settings_once().complete is True
    D.fold_flavor_settings_once()
    assert json.loads(new.value("recently_opened_series")) == [str(legacy_file)]


def test_whats_new_seen_version_survives_retry(setup_store, monkeypatch):
    series, old, new = setup_store
    old.setValue("suppress_whatsnew", True)
    old.setValue("last_whatsnew_version", "1.24.0")
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken)
        assert D.copy_legacy_settings_once().complete is False
    shown = []
    maybe_show_whats_new(
        None, settings=new, current="1.24.1", show=lambda *a: shown.append(a)
    )
    assert D.copy_legacy_settings_once().complete is True
    assert new.value("last_whatsnew_version") == "1.24.0"


@pytest.mark.parametrize("dev_only", [False, True])
def test_happy_copy_and_user_change(setup_store, monkeypatch, dev_only):
    series, old, new = setup_store
    old.setValue("left_handed", True)
    old.setValue("theme", "qdark")
    old.sync()
    if dev_only:
        monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    assert D.copy_legacy_settings_once().complete
    assert series.getOption("left_handed") is True
    assert series.getOption("theme") == "qdark"
    series.setOption("left_handed", False)
    assert D.copy_legacy_settings_once().complete
    assert series.getOption("left_handed") is False


def test_geometry_survives_close_without_a_move(setup_store, monkeypatch, request):
    series, old, new = setup_store
    old.setValue("window/geometry", QByteArray(b"legacy geometry"))
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken)
        assert not D.copy_legacy_settings_once().complete
    window = request.getfixturevalue("main_window")
    window.series.modified = False
    assert window.close()
    assert D.copy_legacy_settings_once().complete
    assert bytes(new.value("window/geometry")) == b"legacy geometry"


@pytest.mark.parametrize("key,value", [("theme", "qdark"), ("left_handed", True)])
def test_user_change_during_failed_copy_wins(setup_store, monkeypatch, key, value):
    series, old, new = setup_store
    old.setValue(key, value)
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken)
        assert not D.copy_legacy_settings_once().complete
    from PyReconstruct.modules.constants.settings_domain import user_action

    changed = "default" if key == "theme" else False
    # a change saved while the copy is owed has to be the user's own
    with user_action():
        series.setOption(key, changed)
    assert D.copy_legacy_settings_once().complete
    assert series.getOption(key) == changed


def test_series_copy_is_independent_and_reopens_once(setup_store, monkeypatch):
    series, old, new = setup_store
    old.setValue("theme", "qdark")
    old.sync()
    shared_app = D.SHARED_APP + "-REVIEW"
    old_series = QSettings(D.LEGACY_SETTINGS_ORG, shared_app)
    old_series.setValue("autobackup", True)
    old_series.setValue("list_layout", '{"trace": []}')
    old_series.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken)
        assert not D.copy_legacy_settings_once().complete
    assert D.copy_legacy_series_settings_once("REVIEW").complete
    assert series.getOption("autobackup") is True
    assert series.getOption("list_layout") == {"trace": []}
    series.setOption("autobackup", False)
    assert D.copy_legacy_series_settings_once("REVIEW").complete
    assert series.getOption("autobackup") is False


def test_v124_shaped_store_copies_every_value_once(setup_store):
    series, old, new = setup_store
    expected = {}
    for k, v in Series.qsettings_defaults.items():
        expected[k] = json.dumps(v) if isinstance(v, (list, dict, tuple)) else v
    expected.update({
        "theme": "qdark", "username": "legacy-review", "left_handed": True,
        "window/geometry": QByteArray(b"geometry"), "palette/mode_x": 0.72,
        "last_whatsnew_version": "1.24.0", "suppress_whatsnew": True,
    })
    for k, v in expected.items():
        old.setValue(k, v)
    old.sync()
    before = {k: old.value(k) for k in old.allKeys()}
    assert D.copy_legacy_settings_once().complete
    assert {k: new.value(k) for k in before} == before
    assert {k: old.value(k) for k in old.allKeys()} == before
    assert not D.copy_legacy_settings_once()


def test_corrupt_ini_keeps_copy_pending(setup_store):
    from pathlib import Path

    app = "PyReconstruct-CORRUPT_REVIEW"
    target = Path(QSettings(D.LEGACY_SETTINGS_ORG, app).fileName())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DAMAGED)
    assert D.copy_legacy_series_settings_once("CORRUPT_REVIEW").complete is False
    assert D.copy_legacy_series_settings_once("CORRUPT_REVIEW").complete is False


def test_a_script_sees_defaults_until_copy(setup_store):
    series, old, new = setup_store
    old.setValue("left_handed", True)
    old.sync()
    assert series.getOption("left_handed") is False
    assert not new.contains("left_handed")
    assert D.copy_legacy_settings_once().complete
    assert series.getOption("left_handed") is True


@pytest.mark.parametrize("key", ["theme", "recently_opened_series"])
def test_real_window_startup_preserves_old_values(
    setup_store, monkeypatch, request, tmp_path, key,
):
    series, old, new = setup_store
    existing = tmp_path / "legacy-existing.jser"
    existing.touch()
    value = "qdark" if key == "theme" else json.dumps([str(existing)])
    old.setValue(key, value)
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken)
        assert not D.copy_legacy_settings_once().complete
    request.getfixturevalue("main_window")
    assert D.copy_legacy_settings_once().complete
    assert new.value(key) == value
