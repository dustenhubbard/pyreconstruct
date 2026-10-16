"""A store that is owed its copy from ``KHLab`` takes only the user's own
writes.

When a copy fails, the values PyReconstruct saves on its own in that session
(the theme applied at startup, the recent list rebuilt for the File menu, the
What's new seen version, an unmoved window's position, the palette's increment
mode, a series' list layout, the backup fallback after a canceled Backup
Settings dialog) must not win over the stored ones when the copy is retried.
A change the user makes is saved at once and wins. The rest are controls: a
plain copy, a per-series copy, and a script that reads settings without
opening the app.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QByteArray, QSettings

from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants import settings_domain as D
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.whats_new import maybe_show_whats_new
from PyReconstruct.modules.gui.main.main_window import MainWindow
from PyReconstruct.modules.gui.utils import getOpenRecentMenu

from settings_copy_helpers import DEV, bare_series_store, empty_stores, fail_copy

pytestmark = pytest.mark.gui


@pytest.fixture
def setup_store(qapp, monkeypatch):
    yield from bare_series_store(monkeypatch)

def _old_store(monkeypatch, old, dev_only):
    """The old store the test seeds and fails: the shared one, or only the
    Dev app's own."""
    if not dev_only:
        return D.SHARED_APP, old
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    return DEV, QSettings(D.LEGACY_SETTINGS_ORG, DEV)

@pytest.fixture
def series_code(series_jser):
    """The fixture series' code, with its per-series stores emptied before and
    after. Left behind, an old ``autobackup`` would be copied into every later
    window on this series, and its Save would stop on Backup Settings."""
    data = json.loads(Path(series_jser).read_text())
    raw = next(value for key, value in data.items() if key.endswith(".ser"))
    code = raw.get("code") or Path(series_jser).stem
    apps = (D.SHARED_APP + "-" + code, DEV + "-" + code)
    empty_stores(*apps)
    yield code
    empty_stores(*apps)
    defaults = QSettings(D.SETTINGS_ORG, D.SHARED_APP)
    defaults.remove("default_autobackup")
    defaults.remove("default_backup_dir")
    defaults.sync()

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
    shared_app = D.SHARED_APP + "-COPYTEST"
    old_series = QSettings(D.LEGACY_SETTINGS_ORG, shared_app)
    old_series.setValue("autobackup", True)
    old_series.setValue("list_layout", '{"trace": []}')
    old_series.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken)
        assert not D.copy_legacy_settings_once().complete
    assert D.copy_legacy_series_settings_once("COPYTEST").complete
    assert series.getOption("autobackup") is True
    assert series.getOption("list_layout") == {"trace": []}
    series.setOption("autobackup", False)
    assert D.copy_legacy_series_settings_once("COPYTEST").complete
    assert series.getOption("autobackup") is False

def test_v124_shaped_store_copies_every_value_once(setup_store):
    series, old, new = setup_store
    expected = {}
    for k, v in Series.qsettings_defaults.items():
        expected[k] = json.dumps(v) if isinstance(v, (list, dict, tuple)) else v
    expected.update({
        "theme": "qdark", "username": "legacy-name", "left_handed": True,
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

@pytest.mark.parametrize("dev_only", [False, True])
def test_startup_and_unmoved_close_do_not_fill_pending_preferences(
    setup_store, monkeypatch, request, dev_only,
):
    series, old, new = setup_store
    app, old = _old_store(monkeypatch, old, dev_only)
    old.setValue("theme", "qdark")
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken, app)
        assert not D.copy_legacy_settings_once().complete
    window = request.getfixturevalue("main_window")
    window.series.modified = False
    assert window.close()
    # The fixture itself seeds last_whatsnew_version. A successful shared copy
    # during a failed Dev copy records its marker. Nothing else may be there.
    allowed = {"last_whatsnew_version", D.LEGACY_COPY_MARKER}
    assert set(new.allKeys()) <= allowed
    assert D.copy_legacy_settings_once().complete
    D.fold_flavor_settings_once()
    assert new.value("theme") == "qdark"

@pytest.mark.parametrize("dev_only", [False, True])
def test_palette_increment_choice_survives_failed_copy_and_startup(
    setup_store, monkeypatch, request, dev_only,
):
    series, old, new = setup_store
    app, old = _old_store(monkeypatch, old, dev_only)
    old.setValue("palette_inc_all", False)
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken, app)
        assert not D.copy_legacy_settings_once().complete
    request.getfixturevalue("main_window")
    assert D.copy_legacy_settings_once().complete
    D.fold_flavor_settings_once()
    assert new.value("palette_inc_all", type=bool) is False

@pytest.mark.parametrize("copy_fails", [False, True])
def test_cancelled_auto_backup_must_not_replace_owed_series_preferences(
    series_code, main_window, tmp_path, monkeypatch, copy_fails,
):
    from PyReconstruct.modules.gui.dialog.backup import BackupDialog

    series = main_window.series
    series.setSettingsStore(QSettingsStore())
    app = D.SHARED_APP + "-" + series.code
    empty_stores(app)
    old = QSettings(D.LEGACY_SETTINGS_ORG, app)
    new = QSettings(D.SETTINGS_ORG, app)
    valid = tmp_path / "real-legacy-backups"
    valid.mkdir()
    old.setValue("autobackup", True)
    old.setValue("backup_dir", str(valid))
    old.sync()
    # the global defaults pick auto-backup, but their folder is gone
    series.setOption("default_autobackup", True)
    series.setOption("default_backup_dir", str(tmp_path / "missing-default"))
    with monkeypatch.context() as broken:
        if copy_fails:
            fail_copy(broken, app)
        assert D.copy_legacy_series_settings_once(series.code).complete is (not copy_fails)
    assert D.shared_copy_pending("-" + series.code) is copy_fails
    # the real dialog is built; its exec stands for Cancel, without a modal loop
    rejected = []
    monkeypatch.setattr(BackupDialog, "exec", lambda dialog: rejected.append(True) or False)
    main_window.saveToJser()
    assert rejected == ([True] if copy_fails else [])
    if not copy_fails:
        assert len(list(valid.glob("*.jser"))) == 1
    assert D.copy_legacy_series_settings_once(series.code).complete
    assert new.value("autobackup", type=bool) is True
    assert new.value("backup_dir") == str(valid)

@pytest.mark.parametrize("dev_only", [False, True])
def test_pending_series_store_has_no_startup_or_unmoved_close_defaults(
    qapp, series_code, monkeypatch, request, dev_only,
):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    code = series_code
    source_app = (DEV if dev_only else D.SHARED_APP) + "-" + code
    if dev_only:
        monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    else:
        monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    old = QSettings(D.LEGACY_SETTINGS_ORG, source_app)
    old.setValue("list_layout", '{"trace": []}')
    old.setValue("autobackup", True)
    old.sync()
    fail_copy(monkeypatch, source_app)
    window = request.getfixturevalue("main_window")
    assert window.series.code == code
    assert D.shared_copy_pending("-" + code)
    new = QSettings(D.SETTINGS_ORG, D.SHARED_APP + "-" + code)
    before = set(new.allKeys())
    assert before <= {D.LEGACY_COPY_MARKER}
    # the fixture turns layout capture off for test hygiene; the real method
    # is the close-time writer this checks
    MainWindow._captureListLayout(window)
    window.series.modified = False
    assert window.close()
    assert set(new.allKeys()) == before
