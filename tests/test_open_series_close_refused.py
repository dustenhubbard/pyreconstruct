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
