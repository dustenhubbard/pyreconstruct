"""Save, close and Export through the local store, in the real MainWindow.

When the .jser is written and when a backup is made, in each Save mode, on
every way the window lets a series go (close, Quit, open another, New series),
what a close does when the .jser cannot be written, and the menu row that
writes the .jser now. With the switch off, the window saves
and closes as today, and the row is not there.
"""
import errno
import os
import shutil
import sqlite3

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import series as series_module
from PyReconstruct.modules.datatypes import hybrid_store, lazy_sections, store_open, store_save
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
    # a working file, so Save As can write out every other section first;
    # changed since the Save, so no source holds the section as saved
    section = window.series.loadSection(other)
    header = _change_in_the_store(kept, other)
    _change_in_the_jser(window.series, other)
    section.thickness = 0.2
    section.save()
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


def test_save_as_with_a_section_in_no_source_moves_nothing(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    other = max(series._lazy)
    # a stub whose store row and .jser range both differ from its key
    header = _change_in_the_store(kept, other)
    _change_in_the_jser(series, other)
    before = kept.read_bytes()
    store_fp = hybrid_store.storePaths(str(kept))[0]
    hidden_dir = series.hidden_dir
    names = sorted(os.listdir(hidden_dir))
    shown = []
    series._surfaceSaveError = lambda fp, err, message=None: shown.append(err)
    new_fp = tmp_path / "moved" / "renamed.jser"
    new_fp.parent.mkdir()
    main_window_dialogs.file_responses.append(str(new_fp))
    try:
        assert window.saveAsToJser() == "cancel"
        assert len(shown) == 1 and f"section {other} " in str(shown[0])
        assert main_window_dialogs.notices == []
        assert window.series is series and not series.closed
        assert series.jser_fp == str(kept) and series.hidden_dir == hidden_dir
        assert kept.read_bytes() == before
        assert sorted(os.listdir(hidden_dir)) == names
        assert store_save.heldStore(series) is not None and os.path.isfile(store_fp)
        assert os.listdir(new_fp.parent) == []
        # the other sections still load at the old path
        snum = min(n for n in series.sections if n != other)
        window.changeSection(snum)
        assert window.field.section.n == snum
    finally:
        # the row as it was saved, so the window can close
        con = sqlite3.connect(store_fp, isolation_level=None)
        try:
            con.execute("UPDATE section SET header=? WHERE snum=?", (header, other))
        finally:
            con.close()
        window.close()


def test_save_as_writes_a_store_section_changed_under_its_key_from_its_working_file(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    snum, _ = _saved_in_the_store(window)
    # the working file holds the section as saved; the .jser does not
    _change_in_the_store(kept, snum)
    shown = []
    window.series._surfaceSaveError = lambda fp, err, message=None: shown.append(err)
    new_fp = tmp_path / "moved" / "renamed.jser"
    new_fp.parent.mkdir()
    main_window_dialogs.file_responses.append(str(new_fp))
    try:
        assert window.saveAsToJser() is None
        assert shown == []
        assert window.series.jser_fp == str(new_fp) and new_fp.exists()
        assert store_save.heldStore(window.series) is None
    finally:
        window.close()
    for fp in (kept, new_fp):
        series = Series.openJser(str(fp), progress=NullProgressReporter)
        try:
            assert series.loadSection(snum).thickness != 0.123
        finally:
            series.close()


class _Notices:
    def __init__(self):
        self.messages = []

    def notify_error(self, message, report):
        self.messages.append(message)
        return True


def _save_as_target(tmp_path, main_window_dialogs):
    new_fp = tmp_path / "moved" / "renamed.jser"
    new_fp.parent.mkdir(exist_ok=True)
    main_window_dialogs.file_responses.append(str(new_fp))
    return new_fp


class _AsItWas:
    """The open series, its .jser, working folder and store, before a Save As."""

    def __init__(self, window, kept):
        self.window = window
        self.series = series = window.series
        self.kept = kept
        self.jser = kept.read_bytes()
        self.hidden_dir = series.hidden_dir
        # less the stub marker, which Save As removes once it fills every stub
        self.names = sorted(set(os.listdir(series.hidden_dir)) - {lazy_sections.MARKER})
        self.store_fp = hybrid_store.storePaths(str(kept))[0]

    def check(self, new_fp):
        window, series = self.window, self.series
        assert window.series is series and not series.closed
        assert series.jser_fp == str(self.kept) and series.hidden_dir == self.hidden_dir
        assert self.kept.read_bytes() == self.jser
        assert sorted(os.listdir(self.hidden_dir)) == self.names
        assert store_save.heldStore(series) is not None and os.path.isfile(self.store_fp)
        assert os.listdir(new_fp.parent) == []
        for snum in sorted(series.sections):
            assert series.loadSection(snum).n == snum
        snum = max(series.sections)
        window.changeSection(snum)
        assert window.field.section.n == snum
        # a section shown writes files of its own
        self.names = sorted(os.listdir(self.hidden_dir))


def test_save_as_that_cannot_write_the_old_jser_keeps_the_series_and_its_save(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    snum, edited = _saved_in_the_store(window)
    notices = _Notices()
    window.series.setNotifier(notices)
    was = _AsItWas(window, kept)
    new_fp = _save_as_target(tmp_path, main_window_dialogs)
    write = series_module._atomicWrite

    def full(fp, data):
        if str(fp) == str(kept):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), str(fp))
        return write(fp, data)

    try:
        with monkeypatch.context() as m:
            m.setattr(series_module, "_atomicWrite", full)
            assert window.saveAsToJser() == "cancel"
        assert len(notices.messages) == 1
        assert os.strerror(errno.ENOSPC) in notices.messages[0]
        assert str(kept) in notices.messages[0]
        assert main_window_dialogs.notices == []
        was.check(new_fp)
        assert store_save.ahead(window.series)
    finally:
        window.close()
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_save_as_that_cannot_rename_a_working_file_keeps_the_series_where_it_was(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    notices = _Notices()
    series.setNotifier(notices)
    was = _AsItWas(window, kept)
    renamed = [
        n for n in was.names
        if series_module.renamedSeriesFile(n, series.name, "renamed") != n
    ]
    assert len(renamed) > 2
    real = os.rename
    try:
        for name in renamed:
            new_fp = _save_as_target(tmp_path, main_window_dialogs)
            new_folder = str(new_fp.parent / ".renamed")

            def refuse(src, dst, *args, name=name, **kwargs):
                if src == os.path.join(new_folder, name):
                    raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), dst)
                return real(src, dst, *args, **kwargs)

            notices.messages.clear()
            with monkeypatch.context() as m:
                m.setattr(os, "rename", refuse)
                assert window.saveAsToJser() == "cancel"
            assert len(notices.messages) == 1, name
            message = notices.messages[0]
            assert os.strerror(errno.EACCES) in message and str(kept) in message
            assert main_window_dialogs.notices == []
            was.check(new_fp)
    finally:
        window.close()


def test_save_as_that_cannot_undo_a_rename_says_where_the_working_folder_is(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    from PyReconstruct.modules.backend.func import atomic_io

    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    name = series.name
    notices = _Notices()
    series.setNotifier(notices)
    old_folder = series.hidden_dir
    new_fp = _save_as_target(tmp_path, main_window_dialogs)
    new_folder = str(new_fp.parent / ".renamed")
    rename = os.rename
    done = []

    def third_refused(src, dst, *args, **kwargs):
        if os.path.dirname(src) == new_folder:
            if len(done) == 2:
                raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), dst)
            done.append(dst)
        return rename(src, dst, *args, **kwargs)

    replace = atomic_io.replace_with_retry

    def locked(src, dst, *args, **kwargs):
        if os.path.dirname(src) == new_folder:
            raise PermissionError(errno.EPERM, os.strerror(errno.EPERM), src)
        return replace(src, dst, *args, **kwargs)

    try:
        with monkeypatch.context() as m:
            m.setattr(os, "rename", third_refused)
            m.setattr(atomic_io, "replace_with_retry", locked)
            assert window.saveAsToJser() == "cancel"
        assert len(notices.messages) == 1
        message = notices.messages[0]
        assert os.strerror(errno.EACCES) in message and os.strerror(errno.EPERM) in message
        assert message.endswith(f"It is at:\n{new_folder}")
        assert not os.path.exists(old_folder) and os.path.isdir(new_folder)
    finally:
        for f in os.listdir(new_folder):
            rename(
                os.path.join(new_folder, f),
                os.path.join(new_folder, series_module.renamedSeriesFile(f, "renamed", name)),
            )
        rename(new_folder, old_folder)
        window.close()


def test_save_as_that_cannot_move_the_working_folder_keeps_the_series_where_it_was(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    notices = _Notices()
    series.setNotifier(notices)
    was = _AsItWas(window, kept)
    new_fp = _save_as_target(tmp_path, main_window_dialogs)
    rename, copyfile = os.rename, shutil.copyfile
    copied = []

    def other_drive(src, dst, *args, **kwargs):
        if src == was.hidden_dir:
            raise OSError(errno.EXDEV, os.strerror(errno.EXDEV), dst)
        return rename(src, dst, *args, **kwargs)

    def full(src, dst, *args, **kwargs):
        if len(copied) == 2:
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), dst)
        copied.append(dst)
        return copyfile(src, dst, *args, **kwargs)

    try:
        with monkeypatch.context() as m:
            m.setattr(os, "rename", other_drive)
            m.setattr(shutil, "copyfile", full)
            assert window.saveAsToJser() == "cancel"
        assert len(copied) == 2
        assert len(notices.messages) == 1
        message = notices.messages[0]
        assert message.count(os.strerror(errno.ENOSPC)) == 1 and str(kept) in message
        assert main_window_dialogs.notices == []
        was.check(new_fp)
    finally:
        window.close()


def test_save_as_to_another_drive_copies_the_working_folder_and_removes_the_old_one(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    old_folder = series.hidden_dir
    before = kept.read_bytes()
    new_fp = _save_as_target(tmp_path, main_window_dialogs)
    rename = os.rename

    def other_drive(src, dst, *args, **kwargs):
        if src == old_folder:
            raise OSError(errno.EXDEV, os.strerror(errno.EXDEV), dst)
        return rename(src, dst, *args, **kwargs)

    try:
        with monkeypatch.context() as m:
            m.setattr(os, "rename", other_drive)
            assert window.saveAsToJser() is None
        assert series.jser_fp == str(new_fp) and new_fp.exists()
        assert series.hidden_dir == str(new_fp.parent / ".renamed")
        assert not os.path.exists(old_folder)
        assert kept.read_bytes() == before
        assert store_save.heldStore(series) is None
        for snum in sorted(series.sections):
            assert series.loadSection(snum).n == snum
    finally:
        window.close()


def _new_jser_full(new_fp):
    """An _atomicWrite that fails for new_fp as a full disk does."""
    write = series_module._atomicWrite

    def full(fp, data):
        if str(fp) == str(new_fp):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), str(fp))
        return write(fp, data)

    return full


def _back_where_it_was(message, kept, new_fp, hidden_dir):
    assert os.strerror(errno.ENOSPC) in message
    assert f"not saved to:\n{new_fp}" in message
    assert f"open from:\n{kept}" in message and hidden_dir in message
    assert "left unchanged" not in message


def test_save_as_that_cannot_write_the_new_jser_moves_the_series_back(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    snum, saved = _saved_in_the_store(window)
    again, working = _move_a_trace(window)
    assert again == snum and working != saved
    notices = _Notices()
    series.setNotifier(notices)
    hidden_dir = series.hidden_dir
    new_fp = _save_as_target(tmp_path, main_window_dialogs)
    retry_fp = tmp_path / "retry" / "retried.jser"
    retry_fp.parent.mkdir()
    try:
        with monkeypatch.context() as m:
            m.setattr(series_module, "_atomicWrite", _new_jser_full(new_fp))
            assert window.saveAsToJser() == "cancel"
        assert len(notices.messages) == 1
        _back_where_it_was(notices.messages[0], kept, new_fp, hidden_dir)
        assert main_window_dialogs.notices == []
        assert window.series is series and not series.closed
        assert series.jser_fp == str(kept) and series.hidden_dir == hidden_dir
        assert store_save.heldStore(series) is not None
        assert not store_save.ahead(series)
        assert os.listdir(new_fp.parent) == []
        assert window.field.section.filepath.startswith(hidden_dir)
        assert series.loadSection(snum).getDict() == working

        main_window_dialogs.file_responses.append(str(retry_fp))
        assert window.saveAsToJser() is None
        assert series.jser_fp == str(retry_fp)
    finally:
        window.close()
    _opened_as_today(kept, snum, saved, monkeypatch)
    _opened_as_today(retry_fp, snum, working, monkeypatch)


def test_save_as_to_another_drive_that_cannot_write_the_new_jser_keeps_the_original(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    notices = _Notices()
    series.setNotifier(notices)
    was = _AsItWas(window, kept)
    new_fp = _save_as_target(tmp_path, main_window_dialogs)
    rename = os.rename

    def other_drive(src, dst, *args, **kwargs):
        if src == was.hidden_dir:
            raise OSError(errno.EXDEV, os.strerror(errno.EXDEV), dst)
        return rename(src, dst, *args, **kwargs)

    try:
        with monkeypatch.context() as m:
            m.setattr(os, "rename", other_drive)
            m.setattr(series_module, "_atomicWrite", _new_jser_full(new_fp))
            assert window.saveAsToJser() == "cancel"
        assert len(notices.messages) == 1
        _back_where_it_was(notices.messages[0], kept, new_fp, was.hidden_dir)
        was.check(new_fp)
    finally:
        window.close()


def test_save_as_that_cannot_move_the_working_folder_back_says_where_it_is(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    notices = _Notices()
    series.setNotifier(notices)
    old_folder = series.hidden_dir
    new_fp = _save_as_target(tmp_path, main_window_dialogs)
    new_folder = str(new_fp.parent / ".renamed")
    rename = os.rename

    def no_way_back(src, dst, *args, **kwargs):
        if src == new_folder:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), dst)
        return rename(src, dst, *args, **kwargs)

    def no_copy(src, dst, *args, **kwargs):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), dst)

    try:
        with monkeypatch.context() as m:
            m.setattr(series_module, "_atomicWrite", _new_jser_full(new_fp))
            m.setattr(os, "rename", no_way_back)
            m.setattr(shutil, "copytree", no_copy)
            assert window.saveAsToJser() == "cancel"
        assert len(notices.messages) == 1
        message = notices.messages[0]
        assert os.strerror(errno.ENOSPC) in message and os.strerror(errno.EACCES) in message
        assert f"It is at:\n{new_folder}" in message
        assert message.endswith(f"The last Save is in:\n{kept}")
        assert not os.path.exists(old_folder) and os.path.isdir(new_folder)
        assert series.hidden_dir == new_folder
        assert store_save.heldStore(series) is None
        for snum in sorted(series.sections):
            assert series.loadSection(snum).n == snum
    finally:
        window.close()


def test_save_as_that_stops_part_way_back_uses_the_folder_where_it_is(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    from PyReconstruct.modules.backend.func import atomic_io

    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    snum, edited = _move_a_trace(window)
    notices = _Notices()
    series.setNotifier(notices)
    old_folder = series.hidden_dir
    new_fp = _save_as_target(tmp_path, main_window_dialogs)
    write = series_module._atomicWrite
    rename = os.rename
    replace = atomic_io.replace_with_retry
    back = []

    def full(fp, data):
        if str(fp) == str(new_fp):
            back.append("write failed")
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), str(fp))
        return write(fp, data)

    def second_refused(src, dst, *args, **kwargs):
        if back and os.path.dirname(src) == old_folder:
            if len(back) == 2:
                raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), dst)
            back.append(dst)
        return rename(src, dst, *args, **kwargs)

    def locked(src, dst, *args, **kwargs):
        if back and os.path.dirname(src) == old_folder:
            raise PermissionError(errno.EPERM, os.strerror(errno.EPERM), src)
        return replace(src, dst, *args, **kwargs)

    try:
        with monkeypatch.context() as m:
            m.setattr(series_module, "_atomicWrite", full)
            m.setattr(os, "rename", second_refused)
            m.setattr(atomic_io, "replace_with_retry", locked)
            assert window.saveAsToJser() == "cancel"
        assert len(back) == 2
        assert len(notices.messages) == 1
        message = notices.messages[0]
        assert os.strerror(errno.ENOSPC) in message and os.strerror(errno.EPERM) in message
        assert f"It is at:\n{old_folder}" in message and str(kept) in message
        names = os.listdir(old_folder)
        assert any(f.startswith("renamed.") for f in names)
        assert not os.path.exists(new_fp.parent / ".renamed")
        assert series.jser_fp == str(kept) and series.hidden_dir == old_folder
        assert os.path.isfile(series.filepath)
        assert store_save.heldStore(series) is not None
        for n in sorted(series.sections):
            assert os.path.isfile(os.path.join(old_folder, series.sections[n]))
            assert series.loadSection(n).n == n
        assert series.loadSection(snum).getDict() == edited
        window.saveToJser()
        assert store_save.ahead(series)
    finally:
        window.close()
    _opened_as_today(kept, snum, edited, monkeypatch)


def test_save_as_that_cannot_write_the_new_series_file_shows_one_notice(
    kept, tmp_path, main_window_dialogs, monkeypatch,
):
    _store_mode(monkeypatch)
    window = _window(kept)
    series = window.series
    notices = _Notices()
    series.setNotifier(notices)
    was = _AsItWas(window, kept)
    new_fp = _save_as_target(tmp_path, main_window_dialogs)
    new_ser = str(new_fp.parent / ".renamed" / "renamed.ser")
    write = series_module._atomicWrite

    def full(fp, data):
        if str(fp) == new_ser:
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), str(fp))
        return write(fp, data)

    try:
        with monkeypatch.context() as m:
            m.setattr(series_module, "_atomicWrite", full)
            assert window.saveAsToJser() == "cancel"
        assert len(notices.messages) == 1
        _back_where_it_was(notices.messages[0], kept, new_fp, was.hidden_dir)
        was.check(new_fp)
    finally:
        window.close()
