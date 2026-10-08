"""Opening a series when a held working file refuses the close of the last one.

Closing a series moves its working files aside before deleting anything. When
that move fails (on Windows, a working file held open by another program or a
sync client can refuse it), the open stops there. What is pinned here:

  * the app's error window opens: the failed close is not quiet
  * the window keeps the series it had, with every working file in place,
    and a pass over it reads every section

A close keeps a folder inside the working folder (a backup folder set
there). Also pinned: File > Open on the same file opens it again, and a
cancelled File > Open puts the series back, both with the folder kept.

A folder that cannot go back is named in a notice once the next series is
open. A notice runs its own event loop, so a Finder open can run under it:
one that does keeps the unsaved work of the series it opens.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.gui


def test_an_open_a_held_file_stops_keeps_the_series_and_says_so(
    main_window, monkeypatch, tmp_path
):
    from PyReconstruct.modules.backend.func import logging_setup
    from PyReconstruct.modules.gui.utils import errors
    window = main_window
    first = window.series
    hidden_dir = first.hidden_dir
    before = sorted(os.listdir(hidden_dir))

    rename = os.rename

    def held(src, dst, *args, **kwargs):
        if os.path.normpath(src) == hidden_dir:
            raise PermissionError(13, "Permission denied", src)
        return rename(src, dst, *args, **kwargs)

    shown = []
    monkeypatch.setattr(
        errors, "show_error_report",
        lambda summary, report, *a, **k: shown.append(report) or True,
    )
    monkeypatch.setattr(errors, "_reported_signatures", set())
    monkeypatch.setattr(
        logging_setup, "log_file_path", lambda: str(tmp_path / "log.txt")
    )
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: None)
    # set in the test body: pytest-qt puts its own hook in for the call
    monkeypatch.setattr(sys, "excepthook", errors.customExcepthook)
    monkeypatch.setattr(os, "rename", held)
    try:
        # File > Open closes the series before it asks for the next one
        window.open_act.trigger()
    finally:
        monkeypatch.setattr(os, "rename", rename)

    assert len(shown) == 1 and "PermissionError" in shown[0]
    assert window.series is first and not first.closed
    assert sorted(os.listdir(hidden_dir)) == before
    visited = [
        snum for snum, _section
        in first.enumerateSections(message="Scanning...")
    ]
    assert visited == sorted(first.sections)


def _backup_folder(series):
    """A backup folder set inside the working folder, with one snapshot."""
    backups = os.path.join(series.hidden_dir, "series-backups")
    os.mkdir(backups)
    snapshot = os.path.join(backups, "series-snapshot.jser")
    with open(snapshot, "w") as f:
        f.write("snapshot")
    return snapshot


def _holds_snapshot(snapshot):
    with open(snapshot) as f:
        return f.read() == "snapshot"


def _records_errors(monkeypatch):
    """The errors the app's error window would show, without the window."""
    from PyReconstruct.modules.gui.utils import errors
    shown = []
    monkeypatch.setattr(
        errors, "show_error_report",
        lambda summary, report, *a, **k: shown.append(report) or True,
    )
    monkeypatch.setattr(errors, "_reported_signatures", set())
    return shown


def test_a_series_closed_beside_a_folder_opens_again(main_window, monkeypatch):
    window = main_window
    first = window.series
    snapshot = _backup_folder(first)
    _records_errors(monkeypatch)

    # File > Open on the same file: the close leaves the backup folder in
    # the working folder the open then looks in for unsaved work
    window.openSeries(jser_fp=first.jser_fp)

    assert window.series is not first and not window.series.closed
    assert window.series.hidden_dir == first.hidden_dir
    assert sorted(window.series.sections) == sorted(first.sections)
    assert _holds_snapshot(snapshot)


def test_a_cancelled_open_puts_back_a_series_closed_beside_a_folder(
    main_window, monkeypatch, tmp_path
):
    from PyReconstruct.modules.backend.func import logging_setup
    window = main_window
    first = window.series
    snapshot = _backup_folder(first)
    shown = _records_errors(monkeypatch)
    monkeypatch.setattr(
        logging_setup, "log_file_path", lambda: str(tmp_path / "log.txt")
    )
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: None)

    # the file dialog is cancelled after the close: the window reopens the
    # series it had from its file
    window.open_act.trigger()

    assert shown == []
    assert window.series is not first and not window.series.closed
    assert window.series.jser_fp == first.jser_fp
    assert sorted(window.series.sections) == sorted(first.sections)
    assert _holds_snapshot(snapshot)


def _two_more_series(window, tmp_path):
    """Series B, and series C with work left unsaved in its working folder.

    Returns B's file, C's file, and C's unsaved section file with its bytes.
    """
    import shutil

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


@pytest.fixture
def finder(qapp, main_window, monkeypatch):
    """Send the event a Finder open sends, routed as the app routes it.

    Opening C takes its unsaved work.
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


def _holds(fp, data):
    if not os.path.isfile(fp):
        return False
    with open(fp, "rb") as f:
        return f.read() == data


def test_a_finder_open_under_the_kept_folder_notice_keeps_its_unsaved_work(
    main_window, finder, monkeypatch, tmp_path
):
    from PyReconstruct.modules.backend import notifier
    from PyReconstruct.modules.gui.main import main_window as mw
    window = main_window
    first = window.series
    _backup_folder(first)
    hidden_dir = first.hidden_dir
    b_fp, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)

    rename = os.rename

    def held(src, dst, *args, **kwargs):
        # the backup folder cannot go back as the first series closes
        if (
            os.path.basename(src) == "series-backups"
            and os.path.dirname(os.path.normpath(dst)) == hidden_dir
        ):
            raise PermissionError(13, "Permission denied", src)
        return rename(src, dst, *args, **kwargs)

    notices = []

    def notice(message, *args, **kwargs):
        # a notice runs its own event loop: C is opened from the Finder
        # while the one naming the kept folder is up
        notices.append(message)
        if "series-backups" in message and len(notices) == 1:
            finder(c_fp)
        return True

    monkeypatch.setattr(mw, "notify", notice)
    monkeypatch.setattr(notifier.QtNotifier, "notify", lambda self, m: notice(m))
    monkeypatch.setattr(os, "rename", held)
    try:
        window.openSeries(jser_fp=b_fp)
    finally:
        monkeypatch.setattr(os, "rename", rename)

    assert _holds(unsaved_fp, unsaved)
    assert any("series-backups" in n for n in notices)
    assert window.series.jser_fp == c_fp and not window.series.closed


def test_a_finder_open_under_the_open_dialog_keeps_its_unsaved_work(
    main_window, finder, monkeypatch, tmp_path
):
    from PyReconstruct.modules.gui.dialog import FileDialog
    window = main_window
    snapshot = _backup_folder(window.series)
    b_fp, c_fp, unsaved_fp, unsaved = _two_more_series(window, tmp_path)

    def choose_b(*args, **kwargs):
        # the file dialog runs its own event loop, after the first series
        # closed and before B opens: C is opened from the Finder in it
        finder(c_fp)
        return b_fp

    monkeypatch.setattr(FileDialog, "get", staticmethod(choose_b))
    window.open_act.trigger()

    assert _holds(unsaved_fp, unsaved)
    assert _holds_snapshot(snapshot)
    # C opens once the open of B is over
    assert window.series.jser_fp == c_fp and not window.series.closed
