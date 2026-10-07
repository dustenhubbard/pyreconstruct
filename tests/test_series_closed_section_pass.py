"""A section pass stops once its series is closed under it.

Every pass that shows a progress dialog runs the event loop on each update,
and another series can open there (a .jser opened from the Finder reaches the
window during any of them). Opening it closes this series and deletes its
working files, and the pass then failed on the next section it read, with a
FileNotFoundError and the app's error window.

What is pinned here:

  * a pass whose series closes at a progress update reads no further section
    and raises SeriesClosedError, which is still a FileNotFoundError
  * the progress dialog is finished on the way out
  * a series closed with leave_open set (its files kept for a series opened
    into the same folder) stops the same way
  * a write pass stopped that way is not quiet: the app's exception hook
    shows and logs it, naming the series (only the read-only clean-up scans
    end without a word; see test_cleanup_lists_series_switch.py)
  * a close that fails part-way (a locked working file) leaves the series
    open, and a pass over it reads every section
"""
import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter


@pytest.fixture
def series(series_jser):
    from PyReconstruct.modules.datatypes.series import Series
    opened = Series.openJser(str(series_jser), progress=NullProgressReporter)
    yield opened
    opened.leave_open = False
    opened.close()


def _closes_at(series, update, leave_open=False):
    """Close the series at the given progress update of its next pass.

    Returns the progress values reported and whether the pass finished it.
    """
    seen = {"reported": [], "finished": False}

    class Closes(NullProgressReporter):
        def set_progress(self, percent):
            seen["reported"].append(percent)
            if len(seen["reported"]) == update:
                series.leave_open = leave_open
                series.close()

        def finish(self):
            seen["finished"] = True

    series.setProgressReporter(Closes)
    return seen


@pytest.mark.parametrize("leave_open", [False, True])
def test_a_pass_stops_before_reading_a_closed_series(
    series, monkeypatch, leave_open
):
    from PyReconstruct.modules.datatypes.series import (
        Series,
        SeriesClosedError,
    )
    assert len(series.sections) > 2
    loaded = []
    load = Series.loadSection
    monkeypatch.setattr(
        Series, "loadSection",
        lambda self, n: loaded.append(n) or load(self, n),
    )
    seen = _closes_at(series, update=2, leave_open=leave_open)

    visited = []
    with pytest.raises(SeriesClosedError) as raised:
        for snum, _section in series.enumerateSections(message="Scanning..."):
            visited.append(snum)

    assert isinstance(raised.value, FileNotFoundError)
    assert visited == loaded == sorted(series.sections)[:1]
    assert seen["finished"]


def test_a_write_pass_stopped_part_way_is_reported(
    series, monkeypatch, tmp_path
):
    import sys
    from PyReconstruct.modules.backend.func import logging_setup
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    from PyReconstruct.modules.gui.utils import errors
    shown, printed = [], []
    monkeypatch.setattr(
        errors, "show_error_report",
        lambda summary, report, *a, **k: shown.append(report) or True,
    )
    monkeypatch.setattr(errors, "_reported_signatures", set())
    log = tmp_path / "log.txt"
    monkeypatch.setattr(logging_setup, "log_file_path", lambda: str(log))
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: printed.append(a))
    # an object on several sections, so the copy saves some and not others
    name = "d03p14"
    assert len(series.getObjectSections([name])) > 2
    # leave_open keeps the working files, so the saved part of the copy stays
    _closes_at(series, update=2, leave_open=True)

    try:
        series.copyObjects([name])
    except SeriesClosedError:
        errors.customExcepthook(*sys.exc_info())
    else:
        pytest.fail("the copy ran on after its series closed")

    assert len(shown) == 1 and len(printed) == 1
    assert series.name in shown[0] and "part-way" in shown[0]
    assert log.exists() and "SeriesClosedError" in log.read_text()


def test_a_failed_close_leaves_the_series_usable(series, monkeypatch):
    import os
    removed = []

    def locked(path):
        removed.append(path)
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(os, "remove", locked)
    with pytest.raises(PermissionError):
        series.close()
    monkeypatch.undo()

    assert len(removed) == 1 and os.path.isdir(series.hidden_dir)
    assert not series.closed
    visited = [
        snum for snum, _section
        in series.enumerateSections(message="Scanning...")
    ]
    assert visited == sorted(series.sections)
