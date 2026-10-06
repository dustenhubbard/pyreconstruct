"""Auto-backup and the backup folder have user-level defaults (#782).

`autobackup` and `backup_dir` are per series. A series with no backup
settings of its own takes `default_autobackup` and `default_backup_dir`,
where `{series}` in the folder becomes the series code. A series that set
its own folder keeps it.

The trap: `Series.getOption` stores the default (off, no folder) the first
time it reads a per-series key, so a series opened once has stored values
whether or not anyone set them. `backup_use_defaults` records the choice
explicitly; without it, a series with a folder or with auto-backup on keeps
its own settings and any other series takes the defaults.

Every test injects a `DictSettingsStore`; none reads or writes `QSettings`.
"""

import os
import re
from types import SimpleNamespace

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series


def _series(code="ABC", store=None):
    series = Series.__new__(Series)
    series.options = {}
    series.code = code
    series.name = "ABC_copy_2026-10-06"
    series.filepath = "/nonexistent/definitely-not-welcome.ser"
    series.setSettingsStore(store if store is not None else DictSettingsStore())
    return series


def _set_defaults(series, folder, auto=True):
    series.setOption("default_backup_dir", folder)
    series.setOption("default_autobackup", auto)


## Which settings a series uses

def test_nothing_set_anywhere_behaves_as_before():
    series = _series()
    assert series.autobackupOn() is False
    assert series.backupFolder() == ""


def test_a_series_with_nothing_stored_uses_the_defaults(tmp_path):
    series = _series()
    _set_defaults(series, str(tmp_path / "{series}"))
    assert series.usesBackupDefaults()
    assert series.autobackupOn() is True
    assert series.backupFolder() == str(tmp_path / "ABC")


def test_a_series_already_opened_with_backups_off_uses_the_defaults(tmp_path):
    """The write-back trap: reading stores off and no folder for the series."""
    store = DictSettingsStore()
    series = _series(store=store)
    series.getOption("autobackup")
    series.getOption("backup_dir")
    assert store.contains("ABC", "autobackup")
    assert store.contains("ABC", "backup_dir")

    _set_defaults(series, str(tmp_path / "{series}"))
    assert series.autobackupOn() is True
    assert series.backupFolder() == str(tmp_path / "ABC")


@pytest.mark.parametrize("auto, folder", [(True, "/own/folder"), (False, "/own/folder"), (True, "")])
def test_a_series_with_settings_of_its_own_keeps_them(tmp_path, auto, folder):
    series = _series()
    series.setOption("autobackup", auto)
    series.setOption("backup_dir", folder)
    _set_defaults(series, str(tmp_path / "{series}"), auto=not auto)

    assert not series.usesBackupDefaults()
    assert series.autobackupOn() is auto
    assert series.backupFolder() == folder


def test_turning_the_defaults_off_for_one_series_sticks(tmp_path):
    series = _series()
    series.setBackupUsesDefaults(False)
    _set_defaults(series, str(tmp_path / "{series}"))
    assert series.autobackupOn() is False
    assert series.backupFolder() == ""


def test_turning_the_defaults_on_overrides_a_series_folder(tmp_path):
    series = _series()
    series.setOption("autobackup", False)
    series.setOption("backup_dir", "/own/folder")
    series.setBackupUsesDefaults(True)
    _set_defaults(series, str(tmp_path / "{series}"))
    assert series.autobackupOn() is True
    assert series.backupFolder() == str(tmp_path / "ABC")


def test_the_defaults_are_shared_and_the_folder_differs_per_series(tmp_path):
    store = DictSettingsStore()
    abc, xyz = _series("ABC", store), _series("XYZ", store)
    _set_defaults(abc, str(tmp_path / "{series}"))
    assert xyz.autobackupOn() is True
    assert abc.backupFolder() == str(tmp_path / "ABC")
    assert xyz.backupFolder() == str(tmp_path / "XYZ")


def test_the_backup_file_goes_in_the_default_folder(tmp_path):
    series = _series()
    _set_defaults(series, str(tmp_path / "{series}"))
    fp = series.getBackupPath(check_existing=False)
    assert os.path.dirname(fp) == str(tmp_path / "ABC")


def test_a_path_separator_in_the_code_cannot_leave_the_folder(tmp_path):
    series = _series("A/../B")
    assert series.expandBackupFolder(str(tmp_path / "{series}")) == str(tmp_path / "A_.._B")


## Making the folder

def test_the_series_folder_is_made_when_its_parent_exists(tmp_path):
    series = _series()
    _set_defaults(series, str(tmp_path / "backups" / "{series}" / "jser"))
    (tmp_path / "backups").mkdir()
    assert series.backupFolder() == str(tmp_path / "backups" / "ABC" / "jser")
    assert not os.path.exists(tmp_path / "backups" / "ABC")
    folder = series.backupFolder(create=True)
    assert os.path.isdir(folder)


def test_nothing_is_made_when_the_part_before_series_is_missing(tmp_path):
    series = _series()
    _set_defaults(series, str(tmp_path / "unmounted" / "{series}"))
    series.backupFolder(create=True)
    assert not os.path.exists(tmp_path / "unmounted")


def test_a_default_folder_without_series_is_never_made(tmp_path):
    series = _series()
    _set_defaults(series, str(tmp_path / "fixed"))
    series.backupFolder(create=True)
    assert not os.path.exists(tmp_path / "fixed")


def test_a_series_folder_of_its_own_is_never_made(tmp_path):
    series = _series()
    series.setOption("backup_dir", str(tmp_path / "own"))
    series.backupFolder(create=True)
    assert not os.path.exists(tmp_path / "own")


## Real series: pulled from another machine, and newly made

def test_a_series_pulled_from_another_machine_uses_the_defaults(real_series, tmp_path):
    """Its code has nothing stored on this machine."""
    store = DictSettingsStore()
    real_series.setSettingsStore(store)
    if not real_series.code:
        real_series.code = "PULLED"
    _set_defaults(real_series, str(tmp_path / "{series}"))

    assert real_series.autobackupOn() is True
    assert real_series.backupFolder() == str(tmp_path / real_series.code)


def test_a_new_series_uses_the_defaults(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    img = images / "img0.png"
    img.write_bytes(b"")
    new = Series.new([str(img)], "NEWS01_trace", 0.00254, 0.05)
    try:
        store = DictSettingsStore()
        new.setSettingsStore(store)
        # what MainWindow._ensureSeriesCode does with the series name
        new.code = re.search(new.getOption("series_code_pattern"), new.name).group()
        assert new.code == "NEWS01"
        _set_defaults(new, str(tmp_path / "backups" / "{series}"))

        assert new.autobackupOn() is True
        assert new.backupFolder() == str(tmp_path / "backups" / "NEWS01")
    finally:
        new.close()


## MainWindow.backup

def _window(series):
    """The parts of MainWindow that MainWindow.backup touches."""
    window = SimpleNamespace(series=series, dialogs=0)

    def setBackup():
        window.dialogs += 1

    window.setBackup = setBackup
    return window


@pytest.fixture
def notes(monkeypatch):
    from PyReconstruct.modules.gui.main import main_window
    seen = []
    monkeypatch.setattr(main_window, "notify", lambda msg, *a, **k: seen.append(msg))
    return seen


def test_auto_backup_on_save_writes_into_the_default_folder(tmp_path, notes):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    series = _series()
    (tmp_path / "backups").mkdir()
    _set_defaults(series, str(tmp_path / "backups" / "{series}"))
    saved = []
    series.saveJser = lambda fp=None, **k: saved.append(fp)
    series.jser_fp = ""

    MainWindow.backup(_window(series), check_auto=True)

    assert len(saved) == 1
    assert os.path.dirname(saved[0]) == str(tmp_path / "backups" / "ABC")
    assert notes == []


def test_auto_backup_is_skipped_when_the_defaults_have_it_off(tmp_path, notes):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    series = _series()
    _set_defaults(series, str(tmp_path / "{series}"), auto=False)
    series.saveJser = lambda *a, **k: pytest.fail("no backup expected")

    MainWindow.backup(_window(series), check_auto=True)
    assert notes == []


def test_a_missing_default_folder_turns_off_this_series_only(tmp_path, notes):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    store = DictSettingsStore()
    series = _series(store=store)
    template = str(tmp_path / "unmounted" / "{series}")
    _set_defaults(series, template)
    series.saveJser = lambda *a, **k: pytest.fail("no backup expected")
    window = _window(series)

    MainWindow.backup(window, check_auto=True)

    assert window.dialogs == 1
    assert len(notes) == 2
    # the defaults every series uses are untouched
    assert store.value(None, "default_backup_dir", str) == template
    assert store.value(None, "default_autobackup", bool) is True
    # this series stops backing up, so it does not ask on every save
    assert series.autobackupOn() is False
    assert _series("XYZ", store).autobackupOn() is True


def test_a_failed_manual_backup_leaves_a_series_on_the_defaults(tmp_path, notes):
    """Auto-backup was off, so there is nothing to turn off."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    store = DictSettingsStore()
    series = _series(store=store)
    series.saveJser = lambda *a, **k: pytest.fail("no backup expected")

    MainWindow.backup(_window(series), check_auto=False)

    assert series.usesBackupDefaults()


def test_a_missing_folder_of_its_own_is_cleared_as_before(tmp_path, notes):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    store = DictSettingsStore()
    series = _series(store=store)
    series.setOption("autobackup", True)
    series.setOption("backup_dir", str(tmp_path / "gone"))
    _set_defaults(series, str(tmp_path / "{series}"))
    series.saveJser = lambda *a, **k: pytest.fail("no backup expected")
    window = _window(series)

    MainWindow.backup(window, check_auto=True)

    assert window.dialogs == 1
    assert store.value("ABC", "backup_dir", str) == ""
    assert store.value("ABC", "autobackup", bool) is False
    assert not series.usesBackupDefaults()
    assert store.value(None, "default_backup_dir", str) == str(tmp_path / "{series}")


## The dialog

@pytest.mark.gui
def test_the_dialog_saves_the_defaults_and_the_series_choice(qapp, tmp_path):
    from PyReconstruct.modules.gui.dialog.backup import BackupDialog

    store = DictSettingsStore()
    series = _series(store=store)
    dialog = BackupDialog(None, series)

    assert dialog.use_defaults_cb.isChecked()
    assert not dialog.dir_widget.isEnabled()
    assert not dialog.auto_cb.isEnabled()

    dialog.default_dir_widget.le.setText(str(tmp_path / "{series}"))
    assert dialog.default_folder_lbl.text() == f"For this series: {tmp_path / 'ABC'}"
    dialog.default_auto_cb.setChecked(True)
    dialog.set()

    assert store.value(None, "default_backup_dir", str) == str(tmp_path / "{series}")
    assert store.value(None, "default_autobackup", bool) is True
    assert store.value("ABC", "backup_use_defaults", bool) is True
    assert series.autobackupOn() is True

    dialog = BackupDialog(None, series)
    dialog.use_defaults_cb.setChecked(False)
    assert dialog.dir_widget.isEnabled()
    dialog.set()
    assert series.autobackupOn() is False
    assert series.backupFolder() == ""
