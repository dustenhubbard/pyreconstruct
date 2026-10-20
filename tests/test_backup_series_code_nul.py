"""A NUL character in the series code gives a notice on every backup path.

With the default backup folder set to a template holding {series}, the code
goes into the folder name. Making that folder raised ValueError, before the
file name check, so Backup now and File ▸ Export series let it reach the
exception hook, and Save, close and turn-off showed "embedded null byte".
The backup is now refused first, with a notice that names the series code.
Set series code and All Options refuse a newly typed NUL, and a series that
already holds one still opens.

Every test gives the series its own settings store, and store paths go under
tmp_path.
"""
import sys

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series, store_open, store_save
from PyReconstruct.modules.gui.dialog import all_options
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog, SERIES_CODE_NUL
from PyReconstruct.modules.gui.main import main_window as main_window_module

from test_hybrid_store import store_root  # noqa: F401  (fixture)
from test_local_store_option import (
    _section_in_the_jser, _setting_on_and_saved, _untick,
)
from test_store_save_gui import (
    _move_a_trace, _saved_in_the_store, _store_mode, _window,
    kept,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.gui

CODE = "ab\0c"

NOTICE = (
    "The backup folder name holds a NUL character, so no backup was made.\n"
    "Check the series code in Series ▸ Series code ▸ Set series code."
)


@pytest.fixture(autouse=True)
def _no_backup_settings(monkeypatch):
    """Fail, rather than wait on a dialog, if a backup opens Backup Settings."""
    def opened(self):
        raise AssertionError("Backup Settings opened")

    monkeypatch.setattr(main_window_module.MainWindow, "setBackup", opened)


def _nul_in_the_code(series, tmp_path):
    """Back up on every save into a {series} default folder, with a NUL in the code.

    Returns the folder that holds the {series} subfolders.
    """
    parent = tmp_path / "backups"
    parent.mkdir(parents=True)
    # the code first: the backup settings of a series are kept under its code
    series.code = CODE
    series.setBackupUsesDefaults(True)
    series.setOption("default_backup_dir", str(parent / "{series}"))
    series.setOption("default_autobackup", True)
    return parent


def _told(monkeypatch):
    """The notices the window shows, and the errors that reached the exception hook."""
    told = []
    monkeypatch.setattr(main_window_module, "notify", told.append)
    hooked = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: hooked.append(exc))
    return told, hooked


def _no_comment(monkeypatch):
    """Answer the Backup now dialog with no comment."""
    class Dialog:
        def __init__(self, *args):
            pass

        def exec(self):
            return ("", False), True

    monkeypatch.setattr(main_window_module, "BackupCommentDialog", Dialog)


def test_backup_folder_with_a_nul_code_does_not_raise(tmp_path):
    series = Series.__new__(Series)
    series.options = {}
    series.name = "ABC"
    series.filepath = "/nonexistent/definitely-not-welcome.ser"
    series.setSettingsStore(DictSettingsStore())
    parent = _nul_in_the_code(series, tmp_path)

    assert series.backupFolder(create=True) == str(parent / CODE)
    assert list(parent.iterdir()) == []


def test_backup_now_with_a_nul_in_the_code_tells(
    main_window, main_window_dialogs, local_series_settings, store_root, tmp_path, monkeypatch,  # noqa: F811
):
    local_series_settings(main_window)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    parent = _nul_in_the_code(main_window.series, tmp_path)
    _no_comment(monkeypatch)
    told, hooked = _told(monkeypatch)

    main_window.manualBackup()

    assert told == [NOTICE]
    assert hooked == []
    assert list(parent.iterdir()) == []


def test_export_series_with_a_nul_in_the_code_writes_the_jser_and_tells(
    main_window, main_window_dialogs, local_series_settings, series_jser, store_root, tmp_path, monkeypatch,  # noqa: F811
):
    local_series_settings(main_window)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    parent = _nul_in_the_code(main_window.series, tmp_path)
    snum, edited = _move_a_trace(main_window)
    told, hooked = _told(monkeypatch)

    main_window.exportJserNow()

    assert told == [NOTICE + f"\nThe last Save is in {series_jser}."]
    assert hooked == []
    assert main_window.series.modified is False
    assert list(parent.iterdir()) == []
    assert _section_in_the_jser(series_jser, snum) == edited


def test_export_series_whose_backup_raises_value_error_tells(
    main_window, main_window_dialogs, local_series_settings, series_jser, store_root, tmp_path, monkeypatch,  # noqa: F811
):
    """Export series takes the backup step Save and close take."""
    local_series_settings(main_window)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    backups = tmp_path / "backups"
    backups.mkdir()
    main_window.series.setBackupUsesDefaults(False)
    main_window.series.setOption("backup_dir", str(backups))
    main_window.series.setOption("autobackup", True)
    _move_a_trace(main_window)
    told, hooked = _told(monkeypatch)

    def bad(src, dst, *args, **kwargs):
        raise ValueError("stat: embedded null character in path")

    monkeypatch.setattr(main_window_module.shutil, "copyfile", bad)

    main_window.exportJserNow()

    assert told == [
        "The backup could not be written: stat: embedded null character in path\n"
        f"The last Save is in {series_jser}."
    ]
    assert hooked == []
    assert main_window.series.modified is False


def test_a_save_with_a_nul_in_the_code_saves_and_tells(
    main_window, main_window_dialogs, local_series_settings, series_jser, store_root, tmp_path, monkeypatch,  # noqa: F811
):
    local_series_settings(main_window)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    parent = _nul_in_the_code(main_window.series, tmp_path)
    snum, edited = _move_a_trace(main_window)
    told, hooked = _told(monkeypatch)

    main_window.saveToJser()

    assert told == [NOTICE + f"\nThe last Save is in {series_jser}."]
    assert hooked == []
    assert main_window.series.modified is False
    assert list(parent.iterdir()) == []
    assert _section_in_the_jser(series_jser, snum) == edited


def test_a_close_with_a_nul_in_the_code_saves_tells_and_closes(
    main_window, main_window_dialogs, local_series_settings, series_jser, store_root, tmp_path, monkeypatch,  # noqa: F811
):
    local_series_settings(main_window)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    parent = _nul_in_the_code(main_window.series, tmp_path)
    snum, edited = _move_a_trace(main_window)
    main_window_dialogs.save_response = "yes"
    told, hooked = _told(monkeypatch)

    assert main_window.close() is True

    assert told == [NOTICE + f"\nThe last Save is in {series_jser}."]
    assert hooked == []
    assert list(parent.iterdir()) == []
    assert _section_in_the_jser(series_jser, snum) == edited


def test_a_close_from_the_local_copy_with_a_nul_in_the_code_tells_and_closes(
    kept, tmp_path, main_window_dialogs, monkeypatch,  # noqa: F811
):
    _store_mode(monkeypatch)
    window = _window(kept)
    try:
        snum, edited = _saved_in_the_store(window)
        window.series.setSettingsStore(DictSettingsStore())
        parent = _nul_in_the_code(window.series, tmp_path)
        told, hooked = _told(monkeypatch)
        assert window.close() is True
        assert told == [NOTICE + f"\nThe last Save is in {kept}."]
        assert hooked == []
        assert list(parent.iterdir()) == []
    finally:
        window.close()
    assert _section_in_the_jser(kept, snum) == edited


def test_unticking_it_with_a_nul_in_the_code_tells_and_names_the_jser(
    kept, tmp_path, main_window_dialogs, monkeypatch,  # noqa: F811
):
    _store_mode(monkeypatch)
    window = _window(kept)
    try:
        snum, edited, _ = _setting_on_and_saved(window, tmp_path, monkeypatch)
        parent = _nul_in_the_code(window.series, tmp_path / "defaults")
        backup_told, hooked = _told(monkeypatch)
        # All Options passes the code it already holds
        told = _untick(window, monkeypatch)
        assert backup_told == [NOTICE + f"\nThe last Save is in {kept}."]
        assert hooked == []
        assert list(parent.iterdir()) == []
        assert told == [
            f"Fast local copy is off. The last Save in the local copy was written to:\n{kept}"
        ]
        assert store_save.heldStore(window.series) is None
    finally:
        window.close()
    assert _section_in_the_jser(kept, snum) == edited


def test_set_series_code_refuses_a_nul(main_window, main_window_dialogs, local_series_settings):
    local_series_settings(main_window)
    before = main_window.series.code
    main_window_dialogs.responses = [((CODE,), True), (("abc",), True)]

    main_window.setSeriesCode()

    assert main_window_dialogs.notices == [SERIES_CODE_NUL]
    assert main_window_dialogs.dialogs == ["Series Code", "Series Code"]
    assert main_window.series.code == "abc" != before


def test_set_series_code_keeps_the_code_when_a_nul_is_canceled(
    main_window, main_window_dialogs, local_series_settings,
):
    local_series_settings(main_window)
    before = main_window.series.code
    # a second dialog with no answer is a cancel
    main_window_dialogs.responses = [((CODE,), True)]

    main_window.setSeriesCode()

    assert main_window_dialogs.notices == [SERIES_CODE_NUL]
    assert main_window.series.code == before


def _options(window, monkeypatch, code):
    told = []
    monkeypatch.setattr(all_options, "notify", told.append)
    dlg = AllOptionsDialog(window, window.series)
    dlg.all_widgets["series_code"].inputs[0].widget.setText(code)
    return dlg, told


def test_all_options_refuses_a_newly_typed_nul_in_the_code(
    main_window, main_window_dialogs, local_series_settings, monkeypatch,
):
    local_series_settings(main_window)
    before = main_window.series.code
    dlg, told = _options(main_window, monkeypatch, CODE)

    assert dlg.accept() is False
    assert told == [SERIES_CODE_NUL]
    assert main_window.series.code == before


def test_all_options_passes_a_nul_the_code_already_holds(
    main_window, main_window_dialogs, local_series_settings, monkeypatch,
):
    local_series_settings(main_window)
    main_window.series.code = CODE
    dlg, told = _options(main_window, monkeypatch, CODE)

    assert dlg.accept() is True
    assert told == []
    assert main_window.series.code == CODE


def test_a_series_whose_code_holds_a_nul_still_opens(
    main_window, main_window_dialogs, local_series_settings, series_jser, store_root, monkeypatch,  # noqa: F811
):
    """The code is kept on a save and read back on an open, and nothing asks for another."""
    local_series_settings(main_window)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    main_window.series.code = CODE
    main_window.saveToJser()

    plain = Series.openJser(str(series_jser))
    try:
        plain.setSettingsStore(DictSettingsStore())
        assert plain.code == CODE
    finally:
        plain.close()
    main_window._ensureSeriesCode()
    assert main_window_dialogs.dialogs == []
    assert main_window.series.code == CODE
