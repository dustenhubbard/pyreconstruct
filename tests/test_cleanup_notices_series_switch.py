"""A clean-up action's notices about series A stop once series B is open.

Combine, Delete and Repair in the clean-up lists can end on more than one
notice, one after another. Each notice is modal, and a .jser opened from the
Finder still reaches the window inside its event loop, so B could open while
the first one was up. The notices after it then still named A's rows, over B.
The same happened when B opened at the last progress update of a Delete or a
Repair: the pass had finished, and its notices came up over B.

What is pinned here:

  * B opening under a Combine's locked-object notice shows no later notice
  * B opening under a Delete's identical-traces notice shows no later notice
  * a Delete or Repair that B opens under at the last progress update shows
    no notice, and leaves B unmodified
  * a self-crossing or empty-trace scan that B opens under at the last
    progress update asks nothing and lists nothing on B
  * a self-crossing repair that B opens under at the last progress update
    opens no list of A's figure 8s on B
"""
import pytest

from tests.test_cleanup_lists_series_switch import (  # noqa: F401  (fixture)
    DUST,
    SQUARE,
    _b_opens_on_the_next_notice,
    _counts,
    _plant,
    confirmed,
    finder,
)
from tests.test_combine_duplicates_series_switch import (
    _b_opens_during_the_combine,
)

pytestmark = pytest.mark.gui

# a closed square with a one-point spike doubling back along its top edge
SPIKED_SQUARE = [
    (0.0, 0.0), (10.0, 0.0), (10.0, 10.0),
    (5.0, 10.0), (5.0, 10.5), (5.0, 10.0),
    (0.0, 10.0),
]
# two equal loops: a figure 8, never repaired on its own
EQUAL_BOWTIE = [(0.0, 0.0), (10.0, 0.0), (0.0, 8.0), (10.0, 8.0)]


def _notices(monkeypatch):
    """Record the field's notices instead of showing them."""
    from PyReconstruct.modules.gui.main import field_widget_3_object
    notices = []
    monkeypatch.setattr(
        field_widget_3_object, "notify",
        lambda message, *a, **k: notices.append(message),
    )
    return notices


def test_b_opening_under_a_combines_lock_notice_drops_the_rest(
    main_window, main_window_dialogs, monkeypatch, tmp_path, qtbot,
    confirmed, finder,  # noqa: F811
):
    window = main_window
    snum = _plant(window, "SWITCH_LOCKED", SQUARE, copies=2)
    _plant(window, "SWITCH_MOVED", [(x + 3.0, y) for x, y in SQUARE], copies=2)
    main_window_dialogs.responses = [
        ([0.95, [("check locked traces", False)]], True)
    ]
    window.reviewDuplicateTraces()
    dialog = window.duplicate_traces_dialog
    picked = {g["names"][0] for g, _keep in dialog.choices()}
    assert {"SWITCH_LOCKED", "SWITCH_MOVED"} <= picked
    # one row is refused for its lock, and one row's traces change, so the
    # combine has a notice for each
    window.series.setAttr("SWITCH_LOCKED", "locked", True)
    moved = window.field.section.contours["SWITCH_MOVED"][0]
    window.field.section.removeTrace(moved, log_event=False)
    window.saveAllData()
    notices = _b_opens_on_the_next_notice(monkeypatch, window, tmp_path, qtbot)
    first = window.series

    dialog.combineAll()

    assert len(notices) == 1 and "locked" in notices[0]
    assert window.series is not first
    assert _counts(window.series, snum)["SWITCH_MOVED"] == 2
    assert not window.series.modified


def test_b_opening_under_a_deletes_identical_traces_notice_drops_the_rest(
    main_window, main_window_dialogs, monkeypatch, tmp_path, qtbot,
    finder,  # noqa: F811
):
    window = main_window
    snum = _plant(window, "SWITCH_DUST", DUST, copies=2)
    _plant(window, "SWITCH_GONE", [(x + 2.0, y) for x, y in DUST])
    records = [
        r for r in window.series.findPixelDustTraces(10.0)
        if r["section"] == snum
    ]
    dust = next(r for r in records if r["name"] == "SWITCH_DUST")
    gone = next(r for r in records if r["name"] == "SWITCH_GONE")
    # a row from before rows carried a place, listed twice: neither of the
    # two identical traces can be told to be it
    unplaced = {
        k: v for k, v in dust.items()
        if k not in ("index", "lookalikes", "lookalike_ordinal")
    }
    trace = window.field.section.contours["SWITCH_GONE"][0]
    window.field.section.removeTrace(trace, log_event=False)
    window.saveAllData()
    notices = _b_opens_on_the_next_notice(monkeypatch, window, tmp_path, qtbot)
    first = window.series

    window.field.deleteMalformedContours([unplaced, unplaced, gone])

    assert len(notices) == 1 and "identical" in notices[0]
    assert window.series is not first
    assert _counts(window.series, snum)["SWITCH_DUST"] == 2
    assert not window.series.modified


def test_b_opening_at_the_end_of_a_delete_shows_nothing_on_b(
    main_window, main_window_dialogs, monkeypatch, tmp_path, qtbot,
    confirmed, finder,  # noqa: F811
):
    window = main_window
    snum = _plant(window, "SWITCH_DUST", DUST)
    _plant(window, "SWITCH_GONE", [(x + 2.0, y) for x, y in DUST])
    main_window_dialogs.responses = [([10.0], True)]
    window.removePixelDustTraces()
    dialog = window.pixel_dust_dialog
    # one listed trace goes first, so the delete has a "not found" notice
    gone = window.field.section.contours["SWITCH_GONE"][0]
    window.field.section.removeTrace(gone, log_event=False)
    window.saveAllData()
    notices = _notices(monkeypatch)
    first = window.series
    reported = _b_opens_during_the_combine(
        window, tmp_path, qtbot, "last", "a copy"
    )

    dialog.deleteAllContours()

    assert reported and reported[-1] >= 100
    assert window.series is not first
    assert notices == []
    assert _counts(window.series, snum)["SWITCH_DUST"] == 1
    assert not window.series.modified


def test_b_opening_at_the_end_of_a_repair_shows_nothing_on_b(
    main_window, main_window_dialogs, monkeypatch, tmp_path, qtbot,
    finder,  # noqa: F811
):
    window = main_window
    snum = _plant(window, "SWITCH_CROSS", SPIKED_SQUARE, copies=2)
    records = [
        r for r in window.series.findSelfCrossingTraces()
        if r["name"] == "SWITCH_CROSS" and r["section"] == snum
    ]
    assert [r["lookalikes"] for r in records] == [2, 2]
    # a third identical trace arrives before the repair, so the repair has
    # a notice that it cannot tell which one the row meant
    section = window.field.section
    section.addTrace(section.contours["SWITCH_CROSS"][0].copy(),
                     log_event=False)
    window.saveAllData()
    notices = _notices(monkeypatch)
    first = window.series
    reported = _b_opens_during_the_combine(
        window, tmp_path, qtbot, "last", "a copy"
    )

    window.field.repairSelfCrossingContours([records[1]])

    assert reported and reported[-1] >= 100
    assert window.series is not first
    assert notices == []
    assert not window.series.modified


def _open_crossing_lists(window):
    """The repaired and skipped self-crossing lists still open."""
    from shiboken6 import isValid

    from PyReconstruct.modules.gui.dialog.malformed_contours import (
        RepairedCrossingsDialog,
        SkippedCrossingsDialog,
    )
    return [
        d for kind in (RepairedCrossingsDialog, SkippedCrossingsDialog)
        for d in window.findChildren(kind) if isValid(d) and d.isVisible()
    ]


def test_b_opening_at_the_end_of_a_self_crossing_scan_asks_nothing_on_b(
    main_window, main_window_dialogs, monkeypatch, tmp_path, qtbot,
    finder,  # noqa: F811
):
    window = main_window
    _plant(window, "SWITCH_CROSS", SPIKED_SQUARE)
    _plant(window, "SWITCH_EIGHT", EQUAL_BOWTIE)
    first = window.series
    reported = _b_opens_during_the_combine(
        window, tmp_path, qtbot, "last", "a copy"
    )

    window.repairSelfCrossingTraces()

    assert reported and reported[-1] >= 100
    assert window.series is not first
    assert main_window_dialogs.notices == []
    assert _open_crossing_lists(window) == []
    assert not window.series.modified


def test_b_opening_at_the_end_of_a_self_crossing_repair_lists_nothing_on_b(
    main_window, main_window_dialogs, monkeypatch, tmp_path, qtbot,
    finder,  # noqa: F811
):
    window = main_window
    _plant(window, "SWITCH_CROSS", SPIKED_SQUARE)
    _plant(window, "SWITCH_EIGHT", EQUAL_BOWTIE)
    first = window.series
    repair = window.field.repairSelfCrossingContours

    def b_opens_under(records):
        _b_opens_during_the_combine(window, tmp_path, qtbot, "last", "a copy")
        return repair(records)

    monkeypatch.setattr(
        window.field, "repairSelfCrossingContours", b_opens_under
    )

    window.repairSelfCrossingTraces()

    assert window.series is not first
    assert len(main_window_dialogs.notices) == 1
    assert "Repair" in main_window_dialogs.notices[0]
    assert _open_crossing_lists(window) == []
    assert not window.series.modified


def test_b_opening_at_the_end_of_an_empty_trace_scan_asks_nothing_on_b(
    main_window, main_window_dialogs, monkeypatch, tmp_path, qtbot,
    finder,  # noqa: F811
):
    window = main_window
    # saved, as the other tests' planting leaves it, so B opens unmodified
    window.saveAllData()
    window.series.saveJser()
    first = window.series
    reported = _b_opens_during_the_combine(
        window, tmp_path, qtbot, "last", "a copy"
    )

    window.removeEmptyTraces()

    assert reported and reported[-1] >= 100
    assert window.series is not first
    assert main_window_dialogs.notices == []
    assert not window.series.modified
