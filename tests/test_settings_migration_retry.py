from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants import settings_domain as SD
from PyReconstruct.modules.datatypes.series import Series


@pytest.fixture
def domain(monkeypatch, tmp_path):
    from PyReconstruct.modules.gui.dialog import whats_new  # noqa: F401

    app = "PyReconstruct-" + tmp_path.name
    monkeypatch.setattr(SD, "SHARED_APP", app)
    monkeypatch.setenv("PYRECON_APP_NAME", app)

    def make(org, name=app):
        store = QSettings(org, name)
        store.setFallbacksEnabled(False)
        return store

    return app, make


def fail_legacy(monkeypatch, app):
    state = {"fail": True}
    status = QSettings.status

    def injected(self):
        if (
            state["fail"]
            and self.organizationName() == "KHLab"
            and self.applicationName() == app
        ):
            return QSettings.AccessError
        return status(self)

    monkeypatch.setattr(QSettings, "status", injected)
    return state


@pytest.mark.parametrize(
    "code,key,legacy_value",
    [(None, "theme", "qdark"), ("SER1", "backup_dir", "/legacy/backups")],
)
@pytest.mark.parametrize("failed_copy", [False, True])
def test_default_read_preserves_recoverable_legacy_value(
    domain, monkeypatch, tmp_path, code, key, legacy_value, failed_copy
):
    app, make = domain
    name = app if code is None else SD.series_app(app, code)
    old = make("KHLab", name)
    old.setValue(key, legacy_value)
    old.sync()
    before = Path(old.fileName()).read_bytes()
    state = fail_legacy(monkeypatch, name)
    state["fail"] = failed_copy
    series = Series.__new__(Series)
    series.options = {}
    series.code = "SER1"
    series.filepath = str(tmp_path / "absent.ser")
    series.setSettingsStore(QSettingsStore())
    initial = series.getOption(key)
    state["fail"] = False
    assert (
        SD.migrate_settings_once(name)
        if failed_copy
        else not SD.migrate_settings_once(name)
    )
    recovered = series.getOption(key)
    assert Path(old.fileName()).read_bytes() == before
    print(
        f"default route={code!r} failed_copy={failed_copy} first={initial!r} recovered={recovered!r} expected={legacy_value!r}"
    )
    assert recovered == legacy_value


@pytest.mark.parametrize("code", [None, "SER1"])
@pytest.mark.parametrize("failed_side", ["stable", "dev"])
def test_fold_waits_for_organization_copy(domain, monkeypatch, code, failed_side):
    app, make = domain
    monkeypatch.setenv("PYRECON_APP_NAME", app + " Dev")
    stable = app if code is None else SD.series_app(app, code)
    dev = app + " Dev" if code is None else SD.series_app(app + " Dev", code)
    old_stable, old_dev = make("KHLab", stable), make("KHLab", dev)
    old_stable.setValue("backup_dir", "/stable/backups")
    old_dev.setValue("backup_dir", "/dev/backups")
    old_dev.setValue("autobackup", False)
    old_stable.sync()
    old_dev.sync()
    state = fail_legacy(monkeypatch, stable if failed_side == "stable" else dev)
    fold = (
        SD.fold_flavor_settings_once
        if code is None
        else lambda: SD.fold_series_settings_once(code)
    )
    fold()
    state["fail"] = False
    SD.migrate_settings_once(stable)
    SD.migrate_settings_once(dev)
    fold()
    recovered = make("PyReconstruct", stable)
    print(
        f"fold route={code!r} failed_side={failed_side} backup_dir={recovered.value('backup_dir')!r} autobackup={recovered.value('autobackup')!r}"
    )
    assert recovered.value("backup_dir") == "/stable/backups"
    assert recovered.contains("autobackup")
    assert recovered.value("autobackup", type=bool) is False


def test_one_transient_failure_does_not_overwrite_the_recovered_choice(
    domain, monkeypatch, tmp_path
):
    app, make = domain
    old = make("KHLab")
    old.setValue("theme", "qdark")
    old.sync()
    original_status = QSettings.status
    state = {"remaining": 1}

    def once(self):
        if (
            self.organizationName() == "KHLab"
            and self.applicationName() == app
            and state["remaining"]
        ):
            state["remaining"] -= 1
            return QSettings.AccessError
        return original_status(self)

    monkeypatch.setattr(QSettings, "status", once)
    series = Series.__new__(Series)
    series.options = {}
    series.setSettingsStore(QSettingsStore())
    initial = series.getOption("theme")
    destination = make("PyReconstruct")
    print(
        f"transient first={initial!r} marker={destination.contains(SD.ORG_MIGRATION_MARKER)} stored={destination.value('theme')!r}"
    )
    assert series.getOption("theme") == "qdark"
    assert destination.contains(SD.ORG_MIGRATION_MARKER)
    assert destination.value("theme") == "qdark"


def test_a_malformed_source_stays_unmigrated_after_reopen(domain):
    app, make = domain
    old_path = Path(make("KHLab").fileName())
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text("[broken\nentry=value\n")
    first = SD.migrate_settings_once(app)
    second = SD.migrate_settings_once(app)
    print(
        f"malformed first={first} second={second} marker={make('PyReconstruct').contains(SD.ORG_MIGRATION_MARKER)}"
    )
    old_path.write_text("[General]\ntheme=qdark\n")
    third = SD.migrate_settings_once(app)
    recovered = make("PyReconstruct").value("theme")
    print(f"repaired third={third} recovered={recovered!r} expected=qdark")
    assert not first
    assert not second
    assert not third
    assert not make("PyReconstruct").contains(SD.ORG_MIGRATION_MARKER)
    assert recovered is None


@pytest.mark.parametrize("code", [None, "SER1"])
def test_user_choice_and_removal_survive_pending_copy(domain, monkeypatch, code):
    app, make = domain
    name = app if code is None else SD.series_app(app, code)
    old = make("KHLab", name)
    old.setValue("choice", "legacy")
    old.setValue("palette/mode_x", 0.25)
    old.sync()
    before = Path(old.fileName()).read_bytes()
    state = fail_legacy(monkeypatch, name)
    store = QSettingsStore()
    handle = store._settings(code)
    handle.setValue("automatic", "fallback")
    handle.remove("choice")
    assert not make("PyReconstruct", name).contains("automatic")
    with SD.user_action():
        handle.setValue("choice", "user")
        handle.remove("palette/mode_x")
    assert make("PyReconstruct", name).value("choice") == "user"
    state["fail"] = False
    assert SD.migrate_settings_once(name)
    recovered = store._settings(code)
    assert recovered.value("choice") == "user"
    assert not recovered.contains("palette/mode_x")
    assert not recovered.contains("automatic")
    assert Path(old.fileName()).read_bytes() == before
    recovered.setValue("automatic", "after recovery")
    assert recovered.value("automatic") == "after recovery"


@pytest.mark.parametrize("key", ["username", "window/geometry"])
def test_routed_raw_writes_wait_for_their_copy(domain, monkeypatch, key):
    app, make = domain
    monkeypatch.setenv("PYRECON_APP_NAME", app + " Dev")
    name = app + " Dev" if SD.is_per_app_key(key) else app
    old = make("KHLab", name)
    old.setValue(key, "legacy")
    old.sync()
    state = fail_legacy(monkeypatch, name)
    handle = SD.settings_for(key)
    handle.setValue(key, "fallback")
    assert not make("PyReconstruct", name).contains(key)
    state["fail"] = False
    assert SD.migrate_settings_once(name)
    handle.setValue(key, "stale fallback")
    assert make("PyReconstruct", name).value(key) == "legacy"
    with SD.user_action():
        handle.setValue(key, "user")
    assert make("PyReconstruct", name).value(key) == "user"


def test_default_reads_inside_a_user_action_still_wait(domain, monkeypatch, tmp_path):
    app, make = domain
    old = make("KHLab")
    old.setValue("theme", "qdark")
    old.sync()
    fail_legacy(monkeypatch, app)
    series = Series.__new__(Series)
    series.options = {}
    series.setSettingsStore(QSettingsStore())
    with SD.user_action():
        assert series.getOption("theme") == "default"
    assert not make("PyReconstruct").contains("theme")


def test_user_action_does_not_authorize_another_thread_or_later_writes(
    domain, monkeypatch
):
    import threading

    app, make = domain
    old = make("KHLab")
    old.setValue("theme", "qdark")
    old.sync()
    fail_legacy(monkeypatch, app)
    handle = SD.settings_for("theme")
    with pytest.raises(RuntimeError), SD.user_action():
        worker = threading.Thread(
            target=lambda: QSettingsStore().set_value(None, "theme", "default")
        )
        worker.start()
        worker.join()
        handle.setValue("choice", "user")
        raise RuntimeError("leave the user action")
    handle.setValue("theme", "default")
    destination = make("PyReconstruct")
    assert not destination.contains("theme")
    assert destination.value("choice") == "user"
    with pytest.raises(AttributeError):
        handle.beginWriteArray("unavailable")


@pytest.mark.parametrize("reload_module", [False, True])
def test_repaired_source_waits_for_a_new_process(tmp_path, reload_module):
    import json
    import subprocess
    import sys

    old_path, new_path = tmp_path / "old.ini", tmp_path / "new.ini"
    script = r"""
import importlib
import json
import sys
from pathlib import Path
from PySide6.QtCore import QSettings
from PyReconstruct.modules.constants import settings_domain as SD
old_path, new_path = map(Path, sys.argv[1:3])
if sys.argv[3] == "fail":
    old_path.write_text("[broken\nentry=value\n")
    assert SD.migrate_settings_once("unused", QSettings(str(old_path), QSettings.IniFormat),
                                    QSettings(str(new_path), QSettings.IniFormat)) is None
    old_path.write_text("[General]\ntheme=qdark\n")
    if sys.argv[4] == "True":
        importlib.reload(SD)
result = SD.migrate_settings_once("unused", QSettings(str(old_path), QSettings.IniFormat),
                                  QSettings(str(new_path), QSettings.IniFormat))
new = QSettings(str(new_path), QSettings.IniFormat)
print(json.dumps([result, new.contains(SD.ORG_MIGRATION_MARKER), new.value("theme")]))
"""
    args = [sys.executable, "-c", script, str(old_path), str(new_path)]
    failed = json.loads(
        subprocess.check_output(args + ["fail", str(reload_module)], text=True)
    )
    assert failed == [None, False, None]
    recovered = json.loads(
        subprocess.check_output(args + ["retry", str(reload_module)], text=True)
    )
    assert recovered == [True, True, "qdark"]


def test_real_window_automatic_writers_wait_but_a_palette_toggle_saves(
    domain, monkeypatch, request
):
    app, make = domain
    old = make("KHLab")
    old.setValue("username", "legacy-user")
    old.setValue("palette/trace_hidden", True)
    old.setValue("palette/sb_hidden", False)
    old.setValue("palette_inc_all", False)
    old.setValue("recently_opened_series", ["old.jser"])
    old.sync()
    before = Path(old.fileName()).read_bytes()
    state = fail_legacy(monkeypatch, app)
    window = request.getfixturevalue("main_window")
    destination = make("PyReconstruct")
    for key in ("username", "palette_inc_all", "recently_opened_series"):
        assert not destination.contains(key), key
    window.mouse_palette.toggleSB()
    assert destination.value("palette/sb_hidden", type=bool) is True
    assert not destination.contains("palette/trace_hidden")
    state["fail"] = False
    SD.settings_for("username")
    assert destination.value("username") == "legacy-user"
    assert destination.value("palette/trace_hidden", type=bool) is True
    assert destination.value("palette/sb_hidden", type=bool) is True
    assert destination.value("palette_inc_all", type=bool) is False
    assert Path(old.fileName()).read_bytes() == before


@pytest.mark.parametrize(
    "code,key,legacy_value",
    [
        (None, "autoseg_color_seed", 17),
        ("SER1", "autobackup", False),
    ],
)
def test_failed_dev_copy_keeps_defaults_out_of_the_shared_store(
    domain, monkeypatch, tmp_path, code, key, legacy_value
):
    app, make = domain
    monkeypatch.setenv("PYRECON_APP_NAME", app + " Dev")
    name = app + " Dev" if code is None else SD.series_app(app + " Dev", code)
    old = make("KHLab", name)
    old.setValue(key, legacy_value)
    old.sync()
    state = fail_legacy(monkeypatch, name)
    series = Series.__new__(Series)
    series.options = {}
    series.code = "SER1"
    series.filepath = str(tmp_path / "absent.ser")
    series.setSettingsStore(QSettingsStore())
    series.getOption(key)
    destination = make(
        "PyReconstruct", app if code is None else SD.series_app(app, code)
    )
    assert not destination.contains(key)
    state["fail"] = False
    assert series.getOption(key) == legacy_value
    assert destination.contains(key)
