"""Save, close and Export through the local store, in the real MainWindow.

When the .jser is written and when a backup is made, in each Save mode, on
every way the window lets a series go (close, Quit, open another, New series),
what a close does when the .jser cannot be written, and the menu row that
writes the .jser now. With the switch off, the window saves
and closes as today, and the row is not there.
"""
import os
import shutil
import sqlite3

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import series as series_module
from PyReconstruct.modules.datatypes import hybrid_store, store_open, store_save
from PyReconstruct.modules.datatypes.series import Series

from test_hybrid_store import store_root  # noqa: F401  (fixture)
from test_store_save import _change_in_the_jser, _change_in_the_store

pytestmark = pytest.mark.gui


def _window(path):
    """A MainWindow on path, built as the main_window fixture builds it."""
    from PySide6.QtCore import QSettings
    from PyReconstruct.modules.gui.dialog.whats_new import APP, ORG, current_version_str
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
    window = MainWindow(str(path))
    window._captureListLayout = lambda: None
    return window


def _move_a_trace(window):
    for snum in sorted(window.series.sections):
        window.changeSection(snum)
        section = window.field.section
        traces = section.tracesAsList()
        if traces:
            section.selected_traces = [traces[0]]
            section.translateTraces(4.0, 2.0)
            window.series.modified = True
            return snum, section.getDict()
    raise AssertionError("no traces")


def _backups(window):
    calls = []
    window.backup = lambda *a, **k: calls.append(k)
    return calls


@pytest.fixture
def kept(qapp, series_jser, store_root, qsettings_snapshot, main_window_dialogs, monkeypatch):  # noqa: F811
    """series_jser with the switch on and its store made (the first open imports it)."""
    monkeypatch.setenv(store_open.ENV_SWITCH, "1")
    _window(series_jser).close()
    # that first close asks to save the fixture, with the switch off as well
    main_window_dialogs.save_prompts = 0
    return series_jser


def _store_mode(monkeypatch):
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_STORE)


def _saved_in_the_store(window):
    """An edit, saved to the store alone: the .jser lacks it."""
    snum, edited = _move_a_trace(window)
    window.saveToJser()
    assert store_save.ahead(window.series)
    return snum, edited


def _disk_full(window, monkeypatch):
    """Make every .jser write fail as a full disk does; return the errors the user is shown."""
    shown = []
    window.series._surfaceSaveError = lambda fp, err, message=None: shown.append(err)

    write = series_module._atomicWrite

    def full(fp, data):
        if str(fp) == window.series.jser_fp:
            raise OSError(28, "No space left on device")
        return write(fp, data)

    monkeypatch.setattr(series_module, "_atomicWrite", full)
    return shown


def _image(folder):
    fp = os.path.join(folder, "img0.png")
    open(fp, "wb").close()
    return fp


def _new_series(window, folder):
    window.newSeries(image_locations=[_image(folder)], series_name="other", mag=0.00254, thickness=0.05)


def _other_jser(kept, tmp_path):
    other = tmp_path / "other" / "other.jser"
    other.parent.mkdir()
    shutil.copyfile(kept, other)
    return other


def _opened_as_today(fp, snum, edited, monkeypatch):
    with monkeypatch.context() as m:
        m.delenv(store_open.ENV_SWITCH)
        plain = Series.openJser(str(fp), progress=NullProgressReporter)
        try:
            assert plain.loadSection(snum).getDict() == edited
        finally:
            plain.close()


def test_jser_mode_saves_and_backs_up_as_today(kept, main_window_dialogs, monkeypatch):
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_JSER)
    before = kept.read_bytes()
    window = _window(kept)
    backups = _backups(window)
    try:
        assert store_save.heldStore(window.series) is not None
        snum, edited = _move_a_trace(window)
        window.saveToJser()
        assert kept.read_bytes() != before
        assert backups == [{"check_auto": True, "from_saved": True}]
        assert not store_save.ahead(window.series)
        saved = kept.read_bytes()
    finally:
        window.close()
    assert backups == [{"check_auto": True, "from_saved": True}]
    assert kept.read_bytes() == saved
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_a_store_only_save_makes_no_backup_and_close_writes_the_jser_and_one(kept, main_window_dialogs, monkeypatch):
    _store_mode(monkeypatch)
    before = kept.read_bytes()
    window = _window(kept)
    backups = _backups(window)
    try:
        snum, edited = _move_a_trace(window)
        window.saveToJser()
        assert kept.read_bytes() == before
        assert backups == []
        assert not window.series.modified
        assert store_save.ahead(window.series)
    finally:
        window.close()
    assert main_window_dialogs.save_prompts == 0
    assert backups == [{"check_auto": True, "from_saved": True}]
    assert kept.read_bytes() != before
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_export_now_writes_the_jser_and_a_backup_and_close_then_writes_nothing(kept, main_window_dialogs, monkeypatch):
    _store_mode(monkeypatch)
    window = _window(kept)
    backups = _backups(window)
    try:
        snum, edited = _move_a_trace(window)
        window.exportjsernow_act.trigger()
        assert len(backups) == 1
        assert not window.series.modified
        assert not store_save.ahead(window.series)
        exported = (kept.read_bytes(), kept.stat().st_mtime_ns)
    finally:
        window.close()
    assert len(backups) == 1
    assert (kept.read_bytes(), kept.stat().st_mtime_ns) == exported
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_close_with_nothing_saved_writes_no_jser_and_no_backup(kept, main_window_dialogs, monkeypatch):
    _store_mode(monkeypatch)
    first = (kept.read_bytes(), kept.stat().st_mtime_ns)
    window = _window(kept)
    backups = _backups(window)
    window.changeSection(sorted(window.series.sections)[1])
    window.close()
    assert backups == []
    assert (kept.read_bytes(), kept.stat().st_mtime_ns) == first


def test_no_at_the_close_prompt_writes_the_last_save_and_a_backup(kept, main_window_dialogs, monkeypatch):
    _store_mode(monkeypatch)
    window = _window(kept)
    backups = _backups(window)
    try:
        snum, edited = _move_a_trace(window)
        window.saveToJser()
        _move_a_trace(window)  # not saved
        main_window_dialogs.save_response = "no"
    finally:
        window.close()
    assert main_window_dialogs.save_prompts == 1
    assert backups == [{"check_auto": True, "from_saved": True}]
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_the_export_row_is_there_only_when_save_writes_the_store_alone(kept, main_window_dialogs, monkeypatch):
    for mode, expected in ((store_save.MODE_JSER, False), (store_save.MODE_STORE, True)):
        monkeypatch.setenv(store_save.ENV_MODE, mode)
        window = _window(kept)
        try:
            assert hasattr(window, "exportjsernow_act") is expected, mode
        finally:
            window.close()


def test_with_the_switch_off_the_window_saves_and_closes_as_today(
    qapp, series_jser, store_root, qsettings_snapshot, main_window_dialogs, monkeypatch,  # noqa: F811
):
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_STORE)
    before = series_jser.read_bytes()
    window = _window(series_jser)
    backups = _backups(window)
    try:
        assert store_save.heldStore(window.series) is None
        assert not hasattr(window, "exportjsernow_act")
        _move_a_trace(window)
        window.saveToJser()
        assert series_jser.read_bytes() != before
        assert backups == [{"check_auto": True, "from_saved": True}]
    finally:
        window.close()
    assert len(backups) == 1
    assert not store_root.exists()


def test_save_writes_the_store_alone_by_default(kept, main_window_dialogs, monkeypatch):
    monkeypatch.delenv(store_save.ENV_MODE, raising=False)
    before = kept.read_bytes()
    window = _window(kept)
    backups = _backups(window)
    try:
        assert hasattr(window, "exportjsernow_act")
        _saved_in_the_store(window)
        assert kept.read_bytes() == before
        assert backups == []
    finally:
        window.close()
    assert len(backups) == 1
    assert kept.read_bytes() != before


@pytest.mark.parametrize("leave", ["close", "quit", "open another", "new series"])
def test_each_way_out_writes_the_store_save_and_one_backup(
    leave, kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    before = kept.read_bytes()
    window = _window(kept)
    backups = _backups(window)
    try:
        snum, edited = _saved_in_the_store(window)
        outgoing = window.series
        if leave == "close":
            assert window.close()
        elif leave == "quit":
            window.quit_act.trigger()
        elif leave == "open another":
            window.openSeries(jser_fp=str(_other_jser(kept, tmp_path)))
        else:
            _new_series(window, str(tmp_path))
        assert outgoing.closed
        assert window.series is not outgoing or leave in ("close", "quit")
        assert backups == [{"check_auto": True, "from_saved": True}]
        assert main_window_dialogs.save_prompts == 0
    finally:
        window.close()
    assert kept.read_bytes() != before
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_new_series_after_an_edit_saves_it_and_makes_one_backup(kept, tmp_path, main_window_dialogs, monkeypatch):
    _store_mode(monkeypatch)
    window = _window(kept)
    backups = _backups(window)
    try:
        snum, edited = _move_a_trace(window)
        main_window_dialogs.save_response = "yes"
        _new_series(window, str(tmp_path))
        assert main_window_dialogs.save_prompts == 1
        assert window.series.name == "other"
        assert len(backups) == 1
        main_window_dialogs.save_response = "no"
    finally:
        window.close()
    _opened_as_today(kept, snum, edited, monkeypatch)


@pytest.mark.parametrize("answer", [None, "no"])
def test_a_close_that_cannot_write_the_jser_leaves_the_window_open(
    answer, kept, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    before = kept.read_bytes()
    window = _window(kept)
    backups = _backups(window)
    snum, edited = _saved_in_the_store(window)
    if answer:
        _move_a_trace(window)  # not saved
        main_window_dialogs.save_response = answer
    with monkeypatch.context() as m:
        shown = _disk_full(window, m)
        assert not window.close()
    assert len(shown) == 1
    assert not window.series.closed
    assert os.path.isdir(window.series.hidden_dir)
    assert store_save.ahead(window.series)
    assert kept.read_bytes() == before
    assert backups == []
    assert window.close()
    assert len(backups) == 1
    _opened_as_today(kept, snum, edited, monkeypatch)


@pytest.mark.parametrize("leave", ["open another", "new series"])
def test_leaving_for_another_series_keeps_this_one_when_the_jser_cannot_be_written(
    leave, kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    before = kept.read_bytes()
    window = _window(kept)
    backups = _backups(window)
    try:
        snum, edited = _saved_in_the_store(window)
        outgoing = window.series
        with monkeypatch.context() as m:
            shown = _disk_full(window, m)
            if leave == "open another":
                window.openSeries(jser_fp=str(_other_jser(kept, tmp_path)))
            else:
                _new_series(window, str(tmp_path))
        assert len(shown) == 1
        assert window.series is outgoing and not outgoing.closed
        assert store_save.ahead(outgoing)
        assert kept.read_bytes() == before
        assert backups == []
    finally:
        window.close()
    assert len(backups) == 1
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_save_as_over_a_store_section_changed_under_its_key_moves_nothing(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    snum, _ = _saved_in_the_store(window)
    other = max(n for n in window.series.sections if n != snum)
    # a working file, so Save As can write out every other section first
    window.series.loadSection(other)
    header = _change_in_the_store(kept, other)
    _change_in_the_jser(window.series, other)
    before = kept.read_bytes()
    shown = []
    window.series._surfaceSaveError = lambda fp, err, message=None: shown.append(err)
    new_fp = tmp_path / "moved" / "renamed.jser"
    new_fp.parent.mkdir()
    main_window_dialogs.file_responses.append(str(new_fp))
    try:
        assert window.saveAsToJser() == "cancel"
        assert len(shown) == 1
        assert window.series.jser_fp == str(kept)
        assert kept.read_bytes() == before
        assert os.listdir(new_fp.parent) == []
        assert store_save.ahead(window.series)
    finally:
        # the row as it was saved, so the window can close
        con = sqlite3.connect(hybrid_store.storePaths(str(kept))[0], isolation_level=None)
        try:
            con.execute("UPDATE section SET header=? WHERE snum=?", (header, other))
        finally:
            con.close()
        window.close()
