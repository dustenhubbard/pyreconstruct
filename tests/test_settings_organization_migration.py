"""Existing preferences survive the change of QSettings organization."""
import pytest

from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants import settings_domain as SD

pytestmark = pytest.mark.gui


@pytest.fixture
def domains(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    app = "PyReconstruct-" + tmp_path.name
    monkeypatch.setattr(SD, "SHARED_APP", app)
    monkeypatch.setenv("PYRECON_APP_NAME", app)

    def make(organization, name=app):
        settings = QSettings(organization, name)
        settings.setFallbacksEnabled(False)
        return settings

    return app, make


@pytest.mark.parametrize("flavor", ["stable", "dev"])
@pytest.mark.parametrize("route", ["global", "per-app", "series"])
def test_first_use_preserves_settings(domains, monkeypatch, flavor, route):
    from PySide6.QtCore import QByteArray

    app, make = domains
    if flavor == "dev":
        monkeypatch.setenv("PYRECON_APP_NAME", app + " Dev")
    name = SD.settings_app() if route == "per-app" else app
    if route == "series":
        name = SD.series_app(name, "SER1")
    old = make("KHLab", name)
    new = make("PyReconstruct", name)
    values = {
        "username": "previous-user", "auto_merge": False,
        "recently_opened_series": ["one.jser", "two.jser"],
        "window/geometry": QByteArray(b"geometry"),
        "backup_dir": "/previous/backups",
        "list_layout": '{"objects": "floating"}',
        "meta/settings_seeded": True,
    }
    for key, value in values.items():
        old.setValue(key, value)
    old.sync()
    new.setValue("username", "current-user")
    new.sync()
    before = open(old.fileName(), "rb").read()

    if route == "series":
        actual = QSettingsStore()._settings("SER1")
    else:
        route_key = "window/geometry" if route == "per-app" else "username"
        actual = SD.settings_for(route_key)

    assert actual.organizationName() == "PyReconstruct"
    assert actual.value("username") == "current-user"
    for key, value in values.items():
        if key != "username":
            assert actual.value(key) == value, key
    assert open(old.fileName(), "rb").read() == before

    actual.remove("backup_dir")
    actual.sync()
    old.setValue("added_later", "ignore")
    old.sync()
    if route == "series":
        again = QSettingsStore()._settings("SER1")
    else:
        again = SD.settings_for(route_key)
    assert not again.contains("backup_dir")
    assert not again.contains("added_later")


@pytest.mark.parametrize("code", [None, "SER1"])
def test_dev_fold_runs_after_both_organizations_migrate(domains, monkeypatch, code):
    app, make = domains
    monkeypatch.setenv("PYRECON_APP_NAME", app + " Dev")
    stable_name = app if code is None else SD.series_app(app, code)
    dev_name = app + " Dev" if code is None else SD.series_app(app + " Dev", code)
    old_stable = make("KHLab", stable_name)
    old_dev = make("KHLab", dev_name)
    old_stable.setValue("backup_dir", "/stable/backups")
    old_dev.setValue("backup_dir", "/dev/backups")
    old_dev.setValue("autobackup", False)
    old_dev.setValue("window/geometry", b"dev")
    old_stable.sync()
    old_dev.sync()
    before = [open(s.fileName(), "rb").read() for s in (old_stable, old_dev)]

    if code is None:
        SD.fold_flavor_settings_once()
    else:
        SD.fold_series_settings_once(code)

    shared = make("PyReconstruct", stable_name)
    dev = make("PyReconstruct", dev_name)
    assert shared.value("backup_dir") == "/stable/backups"
    assert shared.value("autobackup", type=bool) is False
    assert shared.contains("autobackup")
    assert not shared.contains("window/geometry")
    assert dev.value("window/geometry") == b"dev"
    assert [open(s.fileName(), "rb").read() for s in (old_stable, old_dev)] == before


@pytest.mark.parametrize("code", [None, "SER1"])
def test_an_already_folded_dev_store_keeps_its_shared_values(domains, monkeypatch, code):
    app, make = domains
    monkeypatch.setenv("PYRECON_APP_NAME", app + " Dev")
    stable_name = app if code is None else SD.series_app(app, code)
    dev_name = app + " Dev" if code is None else SD.series_app(app + " Dev", code)
    old = make("KHLab", stable_name)
    old.setValue("backup_dir", "/folded/backups")
    old.sync()
    dev = make("KHLab", dev_name)
    dev.setValue(SD.FOLD_MARKER, True)
    dev.setValue("backup_dir", "/outdated/backups")
    dev.sync()
    if code is None:
        SD.fold_flavor_settings_once()
    else:
        SD.fold_series_settings_once(code)
    assert make("PyReconstruct", stable_name).value("backup_dir") == "/folded/backups"
    assert make("PyReconstruct", dev_name).value(SD.FOLD_MARKER, type=bool)


@pytest.mark.parametrize("value", [False, 0, ""])
def test_existing_false_zero_and_empty_values_win(domains, value):
    app, make = domains
    old = make("KHLab")
    old.setValue("choice", "old-value")
    old.sync()
    new = make("PyReconstruct")
    new.setValue("choice", value)
    new.sync()
    SD.migrate_settings_once(app)
    assert make("PyReconstruct").value("choice") == value


def test_only_store_owned_values_migrate(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    old_org, new_org = "Old-" + tmp_path.name, "New-" + tmp_path.name
    monkeypatch.setattr(SD, "LEGACY_SETTINGS_ORG", old_org)
    monkeypatch.setattr(SD, "SETTINGS_ORG", new_org)
    old_defaults = QSettings(old_org, "")
    old_defaults.setValue("inherited", "not-a-user-preference")
    old_defaults.sync()
    new_defaults = QSettings(new_org, "")
    new_defaults.setValue("username", "inherited-name")
    new_defaults.sync()
    old = QSettings(old_org, "example")
    assert old.contains("inherited")
    old.setValue("username", "stored-name")
    old.setValue(SD.ORG_MIGRATION_MARKER, True)
    old.sync()

    SD.migrate_settings_once("example")
    destination = QSettings(new_org, "example")
    destination.setFallbacksEnabled(False)
    assert destination.value("username") == "stored-name"
    assert not destination.contains("inherited")


def test_a_fresh_install_leaves_the_legacy_store_absent(domains):
    from pathlib import Path

    app, make = domains
    assert SD.migrate_settings_once(app)
    assert not Path(make("KHLab").fileName()).exists()
    assert not SD.migrate_settings_once(app)


def test_a_failed_write_retries_in_a_new_process(tmp_path):
    import json
    import subprocess
    import sys

    script = '''
import json
import sys
from PySide6.QtCore import QSettings
from PyReconstruct.modules.constants.settings_domain import (
    ORG_MIGRATION_MARKER, migrate_settings_once,
)
old = QSettings(sys.argv[1], QSettings.IniFormat)
new = QSettings(sys.argv[2], QSettings.IniFormat)
if not old.contains("backup_dir"):
    old.setValue("backup_dir", "/old/backups")
    old.sync()
done = migrate_settings_once("unused", legacy=old, destination=new)
print(json.dumps({
    "done": done,
    "marked": new.contains(ORG_MIGRATION_MARKER),
    "status": new.status().value,
    "backup_dir": new.value("backup_dir"),
    "old_backup_dir": old.value("backup_dir"),
}))
'''
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    args = [sys.executable, "-c", script, str(tmp_path / "old.ini"),
            str(blocked / "new.ini")]
    failed = json.loads(subprocess.check_output(args, text=True))
    assert not failed["done"]
    assert not failed["marked"]
    assert failed["status"] != 0
    blocked.unlink()
    blocked.mkdir()
    retried = json.loads(subprocess.check_output(args, text=True))
    assert retried == {
        "done": True, "marked": True, "status": 0,
        "backup_dir": "/old/backups", "old_backup_dir": "/old/backups",
    }
