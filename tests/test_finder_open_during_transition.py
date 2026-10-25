"""A .jser opened from the Finder while an open or a quit is running.

An open, a new series, an import, a Save As and a quit each show dialogs, and
every dialog runs the event loop, where macOS delivers a Finder open
(run.FileOpenWatcher). Opening that series there changed which series the
window held under the running transition. What is pinned here, against a real
window and the watcher as the app installs it:

  * the Finder open is refused with a notice naming the file, not queued
  * the running transition finishes on the series it started with
  * the unsaved work of the series the Finder asked for is still on disk
"""
import os
import shutil

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture
def finder(qapp, main_window, monkeypatch):
    """Send the event a Finder open sends, routed as the app routes it.

    Opening C would take its unsaved work.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFileOpenEvent

    from PyReconstruct.modules.gui.main import main_window as mw
    from PyReconstruct.run import FileOpenWatcher
    watcher = FileOpenWatcher()
    watcher.main_window = main_window
    qapp.installEventFilter(watcher)
    monkeypatch.setattr(mw, "unsavedNotify", lambda *a, **k: True)
    yield lambda fp: qapp.sendEvent(qapp, QFileOpenEvent(QUrl.fromLocalFile(fp)))
    qapp.removeEventFilter(watcher)


def _two_more_series(window, tmp_path):
    """Series B, and series C with work left unsaved in its working folder.

    Returns B's file, C's file, and C's unsaved section file with its bytes.
    """
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.trace import Trace
    first = window.series

    def copy(name):
        fp = tmp_path / name / f"{name}.jser"
        fp.parent.mkdir()
        shutil.copyfile(first.jser_fp, fp)
        return str(fp)

    b_fp, c_fp = copy("series_b"), copy("series_c")
    # as a crash leaves it
    c = Series.openJser(c_fp, progress=NullProgressReporter)
    snum = sorted(c.sections)[0]
    section = c.loadSection(snum)
    trace = Trace("unsaved", (255, 0, 0), closed=True)
    trace.points = [(0, 0), (1, 0), (1, 1)]
    section.addTrace(trace, log_event=False)
    section.save()
    unsaved_fp = os.path.join(c.hidden_dir, c.sections[snum])
    with open(unsaved_fp, "rb") as f:
        return b_fp, c_fp, unsaved_fp, f.read()


def _holds(fp, data):
    if not os.path.isfile(fp):
        return False
    with open(fp, "rb") as f:
        return f.read() == data


def test_a_finder_open_under_the_open_dialog_keeps_its_unsaved_work(
    main_window, main_window_dialogs, finder, monkeypatch, tmp_path
):
    from PyReconstruct.modules.gui.dialog import FileDialog
    window = main_window
    b_fp, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)

    def choose_b(*args, **kwargs):
        # the file dialog runs its own event loop, after the first series
        # closed and before B opens: C is opened from the Finder in it
        finder(c_fp)
        return b_fp

    monkeypatch.setattr(FileDialog, "get", staticmethod(choose_b))
    window.open_act.trigger()

    assert _holds(unsaved_fp, unsaved)
    assert window.series.jser_fp == b_fp and not window.series.closed
    assert any(c_fp in n for n in main_window_dialogs.notices)
    # refused, not queued: nothing opens C once the open of B is over
    assert not window.seriesTransitionRunning()


def test_a_finder_open_under_the_quit_prompt_keeps_its_unsaved_work(
    main_window, main_window_dialogs, finder, monkeypatch, tmp_path
):
    from PySide6.QtGui import QCloseEvent

    from PyReconstruct.modules.gui.main import main_window as mw
    window = main_window
    first = window.series
    _, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)
    window.seriesModified(True)

    def dont_save(*args, **kwargs):
        # the save prompt runs its own event loop: C is opened from the
        # Finder while it is up, then the first series is not saved
        main_window_dialogs.save_prompts += 1
        if main_window_dialogs.save_prompts == 1:
            finder(c_fp)
        return "no"

    monkeypatch.setattr(mw, "saveNotify", dont_save)
    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert _holds(unsaved_fp, unsaved)
    # the quit closed the series it was asked about, and asked only once
    assert window.series is first and first.closed
    assert main_window_dialogs.save_prompts == 1
    assert any(c_fp in n for n in main_window_dialogs.notices)
