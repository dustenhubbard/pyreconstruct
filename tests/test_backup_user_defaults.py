"""Auto-backup and the backup folder have user-level defaults (#782).

`autobackup` and `backup_dir` are per series. A series with no backup
settings of its own takes `default_autobackup` and `default_backup_dir`.
`{series}` in the folder becomes the series code; the Backup Settings
checkbox for a subfolder per series stands for a folder ending in `{series}`,
so v1.24.0, which shares these settings, reads the same folder. A series
that set its own folder keeps it.

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


@pytest.mark.parametrize("code, safe", [(".", "_"), ("..", "__"), ("...", "___")])
def test_a_dot_only_code_cannot_leave_the_folder(tmp_path, code, safe):
    """The series code dialog accepts any text, so a code can be `..`."""
    series = _series(code)
    folder = series.expandBackupFolder(str(tmp_path / "backups" / "{series}"))
    assert folder == str(tmp_path / "backups" / safe)
    assert os.path.dirname(os.path.normpath(folder)) == str(tmp_path / "backups")


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


def test_canceling_after_a_missing_folder_of_its_own_keeps_it_off_the_defaults(tmp_path, notes):
    """Clearing the folder must not turn a series with auto-backup off into
    one with nothing of its own, which the defaults would then claim."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    store = DictSettingsStore()
    series = _series(store=store)
    series.setOption("autobackup", False)
    series.setOption("backup_dir", str(tmp_path / "gone"))
    (tmp_path / "backups").mkdir()
    _set_defaults(series, str(tmp_path / "backups" / "{series}"))
    series.saveJser = lambda *a, **k: pytest.fail("no backup expected")
    window = _window(series)  # its setBackup is the dialog, canceled

    MainWindow.backup(window, check_auto=False)

    assert window.dialogs == 1
    assert not series.usesBackupDefaults()
    assert series.autobackupOn() is False
    assert not os.path.exists(tmp_path / "backups" / "ABC")


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


## A subfolder per series, without typing {series}

def _stable_folder(store, series):
    """The default backup folder as v1.24.0 resolves it from the shared store.

    `Series.expandBackupFolder` and the template read in `backupFolder` at
    tag v1.24.0 (dc5b3199): that version knows nothing newer, so whatever
    this one stores must mean the same folder to it.
    """
    template = ""
    if store.contains(None, "default_backup_dir"):
        template = store.value(None, "default_backup_dir", str)
    code = (series.code or series.name).replace("/", "_").replace("\\", "_")
    if not code.strip("."):
        code = "_" * max(len(code), 1)
    return template.replace("{series}", code)


def _dialog(series):
    from PyReconstruct.modules.gui.dialog.backup import BackupDialog
    return BackupDialog(None, series)


@pytest.mark.parametrize("folder, split", [
    ("/b/{series}", ("/b", True)),
    ("/b/{series}/", ("/b", True)),
    ("/b//{series}", ("/b", True)),
    ("C:\\B\\{series}", ("C:\\B", True)),
    ("C:/B/{series}", ("C:/B", True)),
    ("/{series}", ("/", True)),
    ("C:\\{series}", ("C:\\", True)),
    ("/b/{series}/jser", ("/b/{series}/jser", False)),
    ("/b/x{series}", ("/b/x{series}", False)),
    ("/{series}/{series}", ("/{series}/{series}", False)),
    ("{series}", ("{series}", False)),
    ("/b", ("/b", False)),
    ("", ("", False)),
])
def test_a_folder_ending_in_series_splits_into_its_base(folder, split):
    assert Series.splitSeriesFolderTemplate(folder) == split


@pytest.mark.parametrize("base, on, stored", [
    ("/b", True, "/b/{series}"),
    ("/b", False, "/b"),
    ("/", True, "/{series}"),
    ("C:\\B", True, "C:\\B\\{series}"),
    ("C:\\", True, "C:\\{series}"),
    ("C:/B", True, "C:/B/{series}"),
    ("/b/{series}/jser", True, "/b/{series}/jser"),
    ("", True, ""),
])
def test_the_box_is_stored_as_a_folder_ending_in_series(base, on, stored):
    assert Series.joinSeriesFolderTemplate(base, on) == stored
    if on and "{series}" not in base and base:
        assert Series.splitSeriesFolderTemplate(stored) == (base, True)


@pytest.mark.parametrize("code, name", [("C:ABC", "C_ABC"), ("A:B:C", "A_B_C")])
def test_a_drive_in_the_code_stays_inside_the_picked_folder(code, name):
    """With Windows paths, "C:ABC" after a separator still names a folder
    under the picked one once the colon is replaced."""
    import ntpath

    series = _series(code)
    folder = series.expandBackupFolder(
        Series.joinSeriesFolderTemplate("D:\\Backups", True)
    )
    assert folder == "D:\\Backups\\" + name
    assert ntpath.dirname(folder) == "D:\\Backups"
    assert ntpath.splitdrive(ntpath.join("D:\\Backups", series.backupFolderName()))[0] == "D:"


@pytest.mark.gui
def test_the_dialog_checkbox_keeps_a_windows_drive_code_inside_the_folder(qapp):
    import ntpath

    series = _series("C:ABC")
    dialog = _dialog(series)
    dialog.default_dir_widget.le.setText("D:\\Backups")
    dialog.default_series_cb.setChecked(True)
    dialog.set()
    assert ntpath.dirname(series.backupFolder()) == "D:\\Backups"


@pytest.mark.gui
def test_the_dialog_sets_the_subfolder_with_a_checkbox(qapp, tmp_path):
    from PySide6.QtWidgets import QLabel

    store = DictSettingsStore()
    series = _series(store=store)
    dialog = _dialog(series)

    # nothing to type: no {series} hint, and a new user starts with it on
    assert not any("{series}" in lbl.text() for lbl in dialog.findChildren(QLabel))
    assert dialog.default_series_cb.isChecked()

    dialog.default_dir_widget.le.setText(str(tmp_path))
    assert dialog.default_folder_lbl.text() == f"For this series: {tmp_path / 'ABC'}"
    dialog.default_series_cb.setChecked(False)
    assert dialog.default_folder_lbl.text() == f"For this series: {tmp_path}"
    dialog.default_series_cb.setChecked(True)
    dialog.set()

    assert store.value(None, "default_backup_dir", str) == str(tmp_path / "{series}")
    assert series.backupFolder() == str(tmp_path / "ABC")
    assert _stable_folder(store, series) == str(tmp_path / "ABC")

    dialog = _dialog(series)
    assert dialog.default_dir_widget.text() == str(tmp_path)
    assert dialog.default_series_cb.isChecked()
    dialog.default_series_cb.setChecked(False)
    dialog.set()
    assert store.value(None, "default_backup_dir", str) == str(tmp_path)
    assert series.backupFolder() == str(tmp_path)
    assert _stable_folder(store, series) == str(tmp_path)


@pytest.mark.gui
def test_the_dialog_shows_a_v1_24_folder_as_its_base_with_the_box_on(qapp, tmp_path):
    series = _series()
    _set_defaults(series, str(tmp_path / "{series}"))

    dialog = _dialog(series)
    assert dialog.default_dir_widget.text() == str(tmp_path)
    assert dialog.default_series_cb.isChecked()
    assert dialog.default_folder_lbl.text() == f"For this series: {tmp_path / 'ABC'}"


@pytest.mark.gui
def test_the_dialog_keeps_a_plain_folder_with_the_box_off(qapp, tmp_path):
    store = DictSettingsStore()
    series = _series(store=store)
    _set_defaults(series, str(tmp_path))

    dialog = _dialog(series)
    assert not dialog.default_series_cb.isChecked()
    dialog.set()
    assert store.value(None, "default_backup_dir", str) == str(tmp_path)


STORED = ["", "B", "B/{series}", "B/{series}/", "B//{series}", "B/{series}/jser", "B/x{series}"]


@pytest.mark.gui
@pytest.mark.parametrize("stored", STORED)
def test_ok_without_changes_writes_back_the_same_folder_text(qapp, tmp_path, stored):
    store = DictSettingsStore()
    series = _series(store=store)
    template = stored.replace("B", str(tmp_path / "B"))
    _set_defaults(series, template)

    _dialog(series).set()
    assert store.value(None, "default_backup_dir", str) == template


@pytest.mark.gui
@pytest.mark.parametrize("stored", STORED)
@pytest.mark.parametrize("change", ["none", "toggle box", "new folder", "new folder, toggle box"])
def test_v1_24_reads_the_same_folder_after_any_save(qapp, tmp_path, stored, change):
    """Stable v1.24.0 and this version share one settings store."""
    store = DictSettingsStore()
    series = _series(store=store)
    _set_defaults(series, stored.replace("B", str(tmp_path / "B")))

    dialog = _dialog(series)
    if "new folder" in change:
        dialog.default_dir_widget.le.setText(str(tmp_path / "other"))
    if "toggle box" in change:
        dialog.default_series_cb.setChecked(not dialog.default_series_cb.isChecked())
    shown = dialog.default_folder_lbl.text()
    dialog.set()

    assert series.backupFolder() == _stable_folder(store, series)
    if series.backupFolder():
        assert shown == f"For this series: {series.backupFolder()}"


@pytest.mark.gui
def test_the_checked_subfolder_is_made_when_the_folder_exists(qapp, tmp_path):
    series = _series()
    dialog = _dialog(series)
    dialog.default_dir_widget.le.setText(str(tmp_path))
    dialog.set()
    assert not os.path.exists(tmp_path / "ABC")
    folder = series.backupFolder(create=True)
    assert folder == str(tmp_path / "ABC")
    assert os.path.isdir(folder)


@pytest.mark.gui
def test_the_checked_subfolder_is_not_made_when_the_folder_is_missing(qapp, tmp_path):
    series = _series()
    dialog = _dialog(series)
    dialog.default_dir_widget.le.setText(str(tmp_path / "unmounted"))
    dialog.set()
    series.backupFolder(create=True)
    assert not os.path.exists(tmp_path / "unmounted")


@pytest.mark.gui
def test_the_dialog_scrolls_and_keeps_ok_and_cancel_in_view(qapp):
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from PyReconstruct.modules.gui.dialog import backup

    dialog = _dialog(_series())
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons is not None
    assert not dialog.scroll_area.widget().isAncestorOf(buttons)
    avail = QApplication.primaryScreen().availableGeometry().height()
    assert dialog.height() <= int(avail * backup.SCREEN_SHARE)


@pytest.mark.gui
def test_inside_all_options_the_dialog_has_no_scroll_or_buttons_of_its_own(qapp, tmp_path):
    from PySide6.QtWidgets import QDialogButtonBox, QScrollArea

    from PyReconstruct.modules.gui.dialog.backup import BackupDialog

    series = _series()
    dialog = BackupDialog(None, series, include_confirm=False)
    assert dialog.findChild(QScrollArea) is None
    assert dialog.findChild(QDialogButtonBox) is None
    dialog.default_dir_widget.le.setText(str(tmp_path))
    dialog.set()
    assert series.backupFolder() == str(tmp_path / "ABC")
