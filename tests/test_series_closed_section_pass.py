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
  * the app's exception hook shows and logs nothing for SeriesClosedError
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


def test_the_error_hook_passes_over_a_stopped_pass(monkeypatch, tmp_path):
    import sys
    from PyReconstruct.modules.backend.func import logging_setup
    from PyReconstruct.modules.datatypes.series import SeriesClosedError
    from PyReconstruct.modules.gui.utils import errors
    shown, printed = [], []
    monkeypatch.setattr(
        errors, "show_error_report",
        lambda *a, **k: shown.append(a) or True,
    )
    monkeypatch.setattr(errors, "_reported_signatures", set())
    log = tmp_path / "log.txt"
    monkeypatch.setattr(logging_setup, "log_file_path", lambda: str(log))
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: printed.append(a))

    try:
        raise SeriesClosedError("series was closed during: Scanning...")
    except SeriesClosedError:
        errors.customExcepthook(*sys.exc_info())

    assert shown == [] and printed == []
    assert not log.exists()
