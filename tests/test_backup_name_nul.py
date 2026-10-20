"""A NUL character in the backup file name is told, and never escapes the backup step.

The name joins the prefix, suffix and delimiter from Backup Settings, the
series code, the user name and a comment. A NUL in any of them made the copy
raise ValueError rather than OSError, which escaped the close and the
unticking of "Fast local copy for large series" after the .jser was written.
The backup is now refused with a notice, the Save stays in the .jser, and the
close or the unticking goes on. Backup Settings refuses a NUL at OK.
"""
import sys

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import store_open, store_save
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

NOTICE = (
    "The backup file name holds a NUL character, so no backup was made.\n"
    "Check the name parts in File ▸ Backup ▸ Settings."
)


def _nul_in_the_name(series, folder):
    """Back up on every save into folder, with a NUL in the name's prefix."""
    folder.mkdir()
    series.setBackupUsesDefaults(False)
    series.setOption("backup_dir", str(folder))
    series.setOption("autobackup", True)
    series.setOption("backup_prefix", True)
    series.setOption("backup_prefix_str", "bad\0name")


def _told(monkeypatch):
    """The notices the window shows, and the errors that reached the exception hook."""
    told = []
    monkeypatch.setattr(main_window_module, "notify", told.append)
    hooked = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: hooked.append(exc))
    return told, hooked


def test_a_close_with_a_nul_in_the_backup_name_saves_tells_and_closes(
    main_window, main_window_dialogs, local_series_settings, series_jser, store_root, tmp_path, monkeypatch,  # noqa: F811
):
    local_series_settings(main_window)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    backups = tmp_path / "backups"
    _nul_in_the_name(main_window.series, backups)
    snum, edited = _move_a_trace(main_window)
    main_window_dialogs.save_response = "yes"
    told, hooked = _told(monkeypatch)

    assert main_window.close() is True

    assert told == [NOTICE + f"\nThe last Save is in {series_jser}."]
    assert hooked == []
    assert list(backups.iterdir()) == []
    assert _section_in_the_jser(series_jser, snum) == edited


def test_a_save_with_a_nul_in_the_backup_name_saves_and_tells(
    main_window, main_window_dialogs, local_series_settings, series_jser, store_root, tmp_path, monkeypatch,  # noqa: F811
):
    local_series_settings(main_window)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    backups = tmp_path / "backups"
    _nul_in_the_name(main_window.series, backups)
    snum, edited = _move_a_trace(main_window)
    told, hooked = _told(monkeypatch)

    main_window.saveToJser()

    assert told == [NOTICE + f"\nThe last Save is in {series_jser}."]
    assert hooked == []
    assert main_window.series.modified is False
    assert list(backups.iterdir()) == []
    assert _section_in_the_jser(series_jser, snum) == edited


def test_a_close_from_the_local_copy_with_a_nul_in_the_backup_name_tells_and_closes(
    kept, tmp_path, main_window_dialogs, monkeypatch,  # noqa: F811
):
    _store_mode(monkeypatch)
    window = _window(kept)
    try:
        snum, edited = _saved_in_the_store(window)
        window.series.setSettingsStore(DictSettingsStore())
        backups = tmp_path / "backups"
        _nul_in_the_name(window.series, backups)
        told, hooked = _told(monkeypatch)
        assert window.close() is True
        assert told == [NOTICE + f"\nThe last Save is in {kept}."]
        assert hooked == []
        assert list(backups.iterdir()) == []
    finally:
        window.close()
    assert _section_in_the_jser(kept, snum) == edited


def test_unticking_it_with_a_nul_in_the_backup_name_tells_and_names_the_jser(
    kept, tmp_path, main_window_dialogs, monkeypatch,  # noqa: F811
):
    _store_mode(monkeypatch)
    window = _window(kept)
    try:
        snum, edited, backups = _setting_on_and_saved(window, tmp_path, monkeypatch)
        # from the user name this time: Backup Settings refuses a NUL in
        # its own name parts, and All Options holds it
        window.series.setOption("backup_user", True)
        # All Options writes the user name back on OK; this one stays
        monkeypatch.setattr(
            type(window.series), "user", property(lambda s: "bad\0user", lambda s, v: None)
        )
        backup_told, hooked = _told(monkeypatch)
        told = _untick(window, monkeypatch)
        assert backup_told == [NOTICE + f"\nThe last Save is in {kept}."]
        assert hooked == []
        assert list(backups.iterdir()) == []
        assert told == [
            f"Fast local copy is off. The last Save in the local copy was written to:\n{kept}"
        ]
        assert store_save.heldStore(window.series) is None
    finally:
        window.close()
    assert _section_in_the_jser(kept, snum) == edited


def _copy_raises_value_error(monkeypatch):
    def bad(src, dst, *args, **kwargs):
        raise ValueError("stat: embedded null character in path")

    monkeypatch.setattr(main_window_module.shutil, "copyfile", bad)


def test_a_close_whose_backup_raises_value_error_tells_and_closes(
    main_window, main_window_dialogs, local_series_settings, series_jser, store_root, tmp_path, monkeypatch,  # noqa: F811
):
    """Any other ValueError from the copy is told like a failed write, not raised."""
    local_series_settings(main_window)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    backups = tmp_path / "backups"
    backups.mkdir()
    main_window.series.setBackupUsesDefaults(False)
    main_window.series.setOption("backup_dir", str(backups))
    main_window.series.setOption("autobackup", True)
    snum, edited = _move_a_trace(main_window)
    main_window_dialogs.save_response = "yes"
    told, hooked = _told(monkeypatch)
    _copy_raises_value_error(monkeypatch)

    assert main_window.close() is True

    assert told == [
        "The backup could not be written: stat: embedded null character in path\n"
        f"The last Save is in {series_jser}."
    ]
    assert hooked == []
    assert _section_in_the_jser(series_jser, snum) == edited


def test_unticking_it_when_the_backup_raises_value_error_still_names_the_jser(
    kept, tmp_path, main_window_dialogs, monkeypatch,  # noqa: F811
):
    _store_mode(monkeypatch)
    window = _window(kept)
    try:
        _setting_on_and_saved(window, tmp_path, monkeypatch)
        backup_told, hooked = _told(monkeypatch)
        _copy_raises_value_error(monkeypatch)
        told = _untick(window, monkeypatch)
        assert backup_told == [
            "The backup could not be written: stat: embedded null character in path\n"
            f"The last Save is in {kept}."
        ]
        assert hooked == []
        assert told == [
            f"Fast local copy is off. The last Save in the local copy was written to:\n{kept}"
        ]
    finally:
        window.close()


@pytest.mark.parametrize("field", ["prefix", "suffix", "date", "time"])
def test_backup_settings_refuses_a_nul_in_a_name_part(
    main_window, main_window_dialogs, local_series_settings, field, monkeypatch,
):
    local_series_settings(main_window)
    from PyReconstruct.modules.gui.dialog import backup as backup_dialog

    series = main_window.series
    before = series.getOption(f"backup_{field}_str")
    told = []
    monkeypatch.setattr(backup_dialog, "notify", told.append)
    dlg = backup_dialog.BackupDialog(main_window, series)
    dlg.widgets[field][1].setText("bad\0name")

    assert dlg.accept(close=False) is False
    assert told == [
        "A backup name part holds a NUL character. Remove it to save these settings."
    ]
    assert series.getOption(f"backup_{field}_str") == before


def test_backup_settings_refuses_a_nul_in_the_delimiter(main_window, main_window_dialogs, local_series_settings, monkeypatch):
    local_series_settings(main_window)
    from PyReconstruct.modules.gui.dialog import backup as backup_dialog

    told = []
    monkeypatch.setattr(backup_dialog, "notify", told.append)
    dlg = backup_dialog.BackupDialog(main_window, main_window.series)
    dlg.delimiter_le.setText("\0")

    assert dlg.accept(close=False) is False
    assert len(told) == 1


def test_backup_settings_takes_ordinary_name_parts(main_window, main_window_dialogs, local_series_settings, monkeypatch):
    local_series_settings(main_window)
    from PyReconstruct.modules.gui.dialog import backup as backup_dialog

    told = []
    monkeypatch.setattr(backup_dialog, "notify", told.append, raising=False)
    dlg = backup_dialog.BackupDialog(main_window, main_window.series)
    dlg.widgets["prefix"][1].setText("good name")

    assert dlg.accept(close=False) is True
    assert told == []
