"""A Duplicates combine on series A leaves alone a series B opened during it.

The combine runs under a progress dialog, and the dialog runs the event loop on
each update, so a .jser opened from the Finder reaches the window there. B
opens, and A's combine carries on to its end. When it returned, the field
refreshed the object tables and the canvas and marked the series modified, and
by then the series open was B. The list's own guard
(MalformedContoursDialog._forOpenSeries) only stops it pruning rows afterwards.

B opens here at the last progress update. At an earlier one the pass goes on
to load a section of A, whose working folder the switch has already deleted.

What is pinned here:

  * B is not marked modified
  * B's traces on the section are unchanged
  * B's object table is not refreshed
"""
import pytest

from tests.test_cleanup_lists_series_switch import (  # noqa: F401  (fixture)
    SQUARE,
    _counts,
    _open_copy,
    _plant,
    confirmed,
    finder,
)

pytestmark = pytest.mark.gui


def _b_opens_as_the_combine_finishes(window, tmp_path, qtbot):
    """Open B from the Finder at the last progress update of A's next pass.

    Returns the progress values A reported.
    """
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    reported = []
    first = window.series

    class OpensB(NullProgressReporter):
        def set_progress(self, percent):
            reported.append(percent)
            if percent >= 100 and window.series is first:
                _open_copy(window, tmp_path, qtbot, from_finder=True)

    first.setProgressReporter(OpensB)
    return reported


def test_a_combine_b_opens_under_leaves_b_alone(
    main_window, main_window_dialogs, monkeypatch, tmp_path, qtbot,
    confirmed, finder,  # noqa: F811
):
    from PyReconstruct.modules.backend.table.manager import TableManager
    window = main_window
    snum = _plant(window, "SWITCH_DUP", SQUARE, copies=2)
    main_window_dialogs.responses = [
        ([0.95, [("check locked traces", False)]], True)
    ]
    window.reviewDuplicateTraces()
    dialog = window.duplicate_traces_dialog
    assert any(g["names"] == ["SWITCH_DUP"] for g, _keep in dialog.choices())
    first = window.series
    saved = _counts(first, snum)
    assert saved["SWITCH_DUP"] == 2
    reported = _b_opens_as_the_combine_finishes(window, tmp_path, qtbot)
    # the field builds a new table manager for B, so watch the class
    refreshed = []
    monkeypatch.setattr(
        TableManager, "updateObjects",
        lambda manager, *a, **k: refreshed.append(manager.series),
    )

    dialog.combineAll()

    assert 100 in reported
    assert window.series is not first
    assert _counts(window.series, snum) == saved
    assert not window.series.modified
    assert window.series not in refreshed
