"""Every removal of a working folder takes the series file first.

An open writes a working folder's ``.ser`` last, and both scans that decide
whether a folder is unsaved work (the fast path in ``Series.openJser`` and the
window's recovery prompt) look for it. A removal that stops partway (a crash,
the app killed) must therefore never leave a ``.ser`` beside a folder that has
already lost sections or ``existing_log.csv``: that folder was offered as
unsaved work, and a save from it wrote the missing sections as ``null`` and
dropped the history.

Each test lists the ``.ser`` last, as the folder listing on macOS does, so the
old listing-order removal reaches it last. ``tests/test_save_kill_reopen.py``
kills a real Save and close; these cover every other path that removes a
working folder, and what an open does with the folder a stopped close leaves.
"""

import os
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


def test_close_stopped_partway_leaves_no_series_file(
    series_jser, ser_listed_last, stop_after_first_remove
):
    series = _open(series_jser)
    hidden = series.hidden_dir
    with pytest.raises(Stopped):
        series.close()
    assert stop_after_first_remove == [f"{series.name}.ser"]
    assert not _ser_files(hidden)
    assert "existing_log.csv" in os.listdir(hidden)


def test_folder_a_stopped_close_left_opens_the_jser_whole(
    series_jser, ser_listed_last, monkeypatch
):
    """No series file: the open replaces the folder from the .jser, every section."""
    series = _open(series_jser)
    hidden = series.hidden_dir
    sections = dict(series.sections)
    real_remove = os.remove
    removed = []

    def remove(path, *args, **kwargs):
        if len(removed) == 2:
            raise Stopped(path)
        real_remove(path, *args, **kwargs)
        removed.append(path)

    monkeypatch.setattr(os, "remove", remove)
    with pytest.raises(Stopped):
        series.close()
    monkeypatch.setattr(os, "remove", real_remove)
    assert os.path.isdir(hidden) and not _ser_files(hidden)

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

    def rmtree(path, *args, **kwargs):
        if os.path.abspath(path) == str(stale):
            assert not _ser_files(path), "a stopped Save As would leave this offered"
            raise Stopped(path)
        return shutil.rmtree(path, *args, **kwargs)

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
