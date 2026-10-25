"""No removal of a working folder leaves a series file beside files already gone.

An open writes a working folder's ``.ser`` last, and both scans that decide
whether a folder is unsaved work (the fast path in ``Series.openJser`` and the
window's recovery prompt) look for it. A removal that stops partway (a crash,
the app killed) must therefore never leave a ``.ser`` beside a folder that has
already lost sections or ``existing_log.csv``: that folder was offered as
unsaved work, and a save from it wrote the missing sections as ``null`` and
dropped the history.

A close moves the whole folder aside in one step (to a ``.closing-<hex>``
sibling) and deletes it there, so under the series' own name there is either
every file or nothing. Every removal in place (``Save As`` over an old folder,
a failed open, declined unsaved work) takes the series file first; each of
those tests lists the ``.ser`` last, as the folder listing on macOS does, so
the old listing-order removal reaches it last. ``tests/test_save_kill_reopen.py``
kills a real Save and close.
"""

import os
import re
import shutil

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants import createHiddenDir, removeSeriesFiles
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes import series as series_mod


class Stopped(Exception):
    """The removal stopped here, as a kill would stop it."""


def _open(jser_fp):
    series = Series.openJser(
        str(jser_fp), progress=NullProgressReporter, notifier=NullNotifier()
    )
    assert series is not None
    return series


def _ser_files(folder):
    return [f for f in os.listdir(folder) if f.endswith(".ser")]


@pytest.fixture
def ser_listed_last(monkeypatch):
    """List every folder with its .ser last, the order that loses the history."""
    real_listdir = os.listdir

    def listdir(path="."):
        return sorted(real_listdir(path), key=lambda n: (n.endswith(".ser"), n))

    monkeypatch.setattr(os, "listdir", listdir)


@pytest.fixture
def stop_after_first_remove(monkeypatch):
    """Let one file be removed, then stop, leaving the rest where it is."""
    real_remove = os.remove
    removed = []

    def remove(path, *args, **kwargs):
        if removed:
            raise Stopped(path)
        real_remove(path, *args, **kwargs)
        removed.append(os.path.basename(path))

    monkeypatch.setattr(os, "remove", remove)
    return removed


def _working_folder(tmp_path, sections=(0, 1, 2)):
    folder = tmp_path / ".series"
    folder.mkdir()
    for snum in sections:
        (folder / f"series.{snum}").write_text("{}")
    (folder / "existing_log.csv").write_text("log")
    (folder / "series.ser").write_text("{}")
    return folder


def test_removeSeriesFiles_takes_only_series_files(tmp_path):
    folder = _working_folder(tmp_path)
    (folder / "other.SER").write_text("{}")
    (folder / "nested.ser").mkdir()
    removeSeriesFiles(str(folder))
    assert sorted(os.listdir(folder)) == [
        "existing_log.csv", "nested.ser", "series.0", "series.1", "series.2",
    ]


def _closing_dirs(parent):
    """The folders a close moved aside in `parent`."""
    return sorted(
        n for n in os.listdir(parent) if re.fullmatch(r"\.closing-[0-9a-f]{8}", n)
    )


def test_close_stopped_during_the_delete_leaves_nothing_under_the_series_name(
    series_jser, monkeypatch
):
    """The folder is moved aside whole first, so the open takes the .jser, every section."""
    series = _open(series_jser)
    hidden = series.hidden_dir
    sections = dict(series.sections)
    real_unlink = os.unlink
    removed = []

    def unlink(path, *args, **kwargs):
        if len(removed) == 2:
            raise Stopped(path)
        real_unlink(path, *args, **kwargs)
        removed.append(path)

    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(Stopped):
        series.close()
    monkeypatch.setattr(os, "unlink", real_unlink)
    assert series.closed
    assert not os.path.exists(hidden)
    aside = _closing_dirs(os.path.dirname(hidden))
    assert len(aside) == 1

    reopened = _open(series_jser)
    try:
        assert not reopened.leave_open  # not taken as unsaved work
        assert reopened.sections == sections
        for snum in reopened.sections:
            reopened.loadSection(snum)
        assert os.path.isfile(os.path.join(reopened.hidden_dir, "existing_log.csv"))
    finally:
        reopened.close()


def test_move_onto_a_stale_working_folder_takes_its_series_file_first(
    series_jser, tmp_path, monkeypatch
):
    """Save As over a .jser whose working folder is still there."""
    series = _open(series_jser)
    dest = tmp_path / "dest"
    dest.mkdir()
    stale = dest / ".other"
    stale.mkdir()
    for name in ("other.0", "existing_log.csv", "other.ser"):
        (stale / name).write_text("x")
    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if os.path.abspath(path) == str(stale):
            assert not _ser_files(path), "a stopped Save As would leave this offered"
            raise Stopped(path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(series_mod.shutil, "rmtree", rmtree)
    try:
        with pytest.raises(Stopped):
            series.move(str(dest / "other.jser"), None, None)
    finally:
        series.close()


def test_failed_open_takes_its_series_file_first(series_jser, monkeypatch):
    """An open that fails after placing its folder removes the .ser before the rest."""
    hidden = os.path.join(os.path.dirname(series_jser), ".series")
    seen = []
    real_rmtree = shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if os.path.abspath(path) == hidden:
            seen.append(_ser_files(path))
        return real_rmtree(path, *args, **kwargs)

    def broken_init(self, *args, **kwargs):
        raise Stopped("build")

    monkeypatch.setattr(series_mod.shutil, "rmtree", rmtree)
    monkeypatch.setattr(Series, "__init__", broken_init)
    with pytest.raises(Stopped):
        _open(series_jser)
    assert seen == [[]]
    assert not os.path.exists(hidden)


def test_failed_open_keeps_its_folder_whole_if_the_series_file_stays(
    series_jser, monkeypatch
):
    """A .ser that cannot be removed (held open on Windows) keeps every file beside it."""
    hidden = os.path.join(os.path.dirname(series_jser), ".series")
    series = _open(series_jser)
    sections = sorted(series.sections.values())
    series.close()
    real_remove, real_unlink = os.remove, os.unlink

    def held(real):
        def remove(path, *args, **kwargs):
            if str(path).endswith(".ser"):
                raise PermissionError(path)
            return real(path, *args, **kwargs)
        return remove

    def broken_init(self, *args, **kwargs):
        raise Stopped("build")

    # os.unlink as well: shutil.rmtree removes files with it
    monkeypatch.setattr(os, "remove", held(real_remove))
    monkeypatch.setattr(os, "unlink", held(real_unlink))
    monkeypatch.setattr(Series, "__init__", broken_init)
    with pytest.raises(Stopped):
        _open(series_jser)
    names = os.listdir(hidden)
    assert "series.ser" in names and "existing_log.csv" in names
    assert sorted(n for n in names if n[len("series."):].isdigit()) == sections


def test_createHiddenDir_empties_a_folder_series_file_first(
    tmp_path, ser_listed_last, stop_after_first_remove
):
    folder = _working_folder(tmp_path)
    with pytest.raises(Stopped):
        createHiddenDir(str(tmp_path), "series")
    assert stop_after_first_remove == ["series.ser"]
    assert not _ser_files(folder)


@pytest.mark.gui
def test_declined_unsaved_work_is_cleared_series_file_first(
    qapp, tmp_path, ser_listed_last, stop_after_first_remove
):
    """Answering No to the unsaved-work prompt deletes the folder the same way."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    folder = _working_folder(tmp_path)
    with pytest.raises(Stopped):
        MainWindow._clearHiddenSeriesDir(str(folder))
    assert stop_after_first_remove == ["series.ser"]
    assert not _ser_files(folder)


@pytest.fixture
def log_held(monkeypatch):
    """existing_log.csv cannot be removed, as when another program holds it on Windows."""
    def held(real):
        def remove(path, *args, **kwargs):
            if os.path.basename(str(path)) == "existing_log.csv":
                raise PermissionError(13, "Permission denied", path)
            return real(path, *args, **kwargs)
        return remove

    monkeypatch.setattr(os, "remove", held(os.remove))
    monkeypatch.setattr(os, "unlink", held(os.unlink))


def test_close_finishes_once_its_folder_is_moved_aside(series_jser, log_held):
    """A file the delete cannot remove stays in the moved folder, under no series name."""
    series = _open(series_jser)
    hidden = series.hidden_dir
    sections = dict(series.sections)
    series.close()  # does not raise
    assert series.closed
    assert not os.path.isdir(hidden)
    aside = _closing_dirs(os.path.dirname(hidden))
    assert len(aside) == 1
    assert os.listdir(os.path.join(os.path.dirname(hidden), aside[0])) == ["existing_log.csv"]

    reopened = _open(series_jser)
    try:
        assert not reopened.leave_open
        assert reopened.sections == sections
    finally:
        reopened.close()


@pytest.mark.gui
def test_opening_another_series_with_a_held_file_moves_the_window_on(
    main_window, series_jser, tmp_path, log_held
):
    """The window never keeps editing a series whose folder lost its .ser."""
    old = main_window.series
    other = tmp_path / "other" / "other.jser"
    other.parent.mkdir()
    shutil.copy(series_jser, other)
    main_window.openSeries(jser_fp=str(other), query_prev=False)
    assert main_window.series is not old
    assert main_window.series.jser_fp == str(other)
    assert old.closed and not os.path.isdir(old.hidden_dir)


def test_a_closed_series_refuses_to_write(series_jser, log_held):
    """What a close leaves behind is never written to: no open offers it back."""
    from PyReconstruct.modules.datatypes.series import SeriesClosedError

    series = _open(series_jser)
    section = series.loadSection(min(series.sections))
    series.close()
    with pytest.raises(SeriesClosedError):
        section.save()
    with pytest.raises(SeriesClosedError):
        series.save()
    with pytest.raises(SeriesClosedError):
        series.saveJser()
    assert not os.path.isdir(series.hidden_dir)


@pytest.mark.gui
def test_reopening_the_series_with_a_held_file_puts_a_whole_series_back(
    main_window, main_window_dialogs, series_jser, log_held
):
    """The held file goes aside with the old folder; the open writes a whole new one."""
    old = main_window.series
    snum = main_window.field.section.n
    main_window.field.section.thickness = 0.123
    main_window.seriesModified(True)
    main_window_dialogs.save_response = "yes"

    main_window.openSeries(jser_fp=str(series_jser))

    series = main_window.series
    assert series is not old and old.closed
    assert not series.closed and not series.isWelcomeSeries()
    names = set(os.listdir(series.hidden_dir))
    assert f"{series.name}.ser" in names and "existing_log.csv" in names
    assert {series.sections[n] for n in series.sections} <= names
    assert series.loadSection(snum).thickness == 0.123
    main_window.field.section.thickness = 0.2
    main_window.seriesModified(True)
    main_window.saveAllData()  # the series in the window takes edits again


@pytest.mark.gui
def test_a_closed_series_gets_no_heartbeat(main_window, log_held):
    """The open-elsewhere marker is not written beside what a close left."""
    series = main_window.series
    hidden = series.hidden_dir
    series.close()
    assert not os.path.isdir(hidden)
    main_window.field.markTime()
    assert not os.path.isdir(hidden)
    series.closed = False  # for the window's own close at teardown
    series.leave_open = True
