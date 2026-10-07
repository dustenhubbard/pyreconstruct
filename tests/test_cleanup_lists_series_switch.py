"""The clean-up review lists close when another series opens.

Each list (pixel dust, Duplicates, traces skipped during smoothing, and the
repaired and skipped self-crossing lists) is modeless and keeps its buttons
bound to the FieldWidget. Opening another series reuses that FieldWidget with
the new series in it, so a list left open from series A deleted or combined
the matching trace in series B. Here A and B are byte copies, so every row of
A's list names a trace that also exists in B.

What is pinned here:

  * Delete all in a pixel-dust list opened in A leaves B unchanged
  * Combine all in a Duplicates list opened in A leaves B unchanged
  * every kind of clean-up list is closed once B is open
"""
import shutil

import pytest
from shiboken6 import isValid

pytestmark = pytest.mark.gui

DUST = [(0.0, 0.0), (0.001, 0.0), (0.001, 0.001), (0.0, 0.001)]
SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


@pytest.fixture
def confirmed(monkeypatch):
    """Accept the lists' own Delete and Combine confirmations."""
    from PyReconstruct.modules.gui.dialog import malformed_contours
    monkeypatch.setattr(
        malformed_contours, "notifyConfirm", lambda *a, **k: True
    )


def _plant(window, name, points, copies=1):
    """Add closed traces to the current section and save the series."""
    from PyReconstruct.modules.datatypes.trace import Trace
    section = window.field.section
    for _ in range(copies):
        trace = Trace(name, (255, 0, 0), closed=True)
        trace.points = list(points)
        section.addTrace(trace, log_event=False)
    window.saveAllData()
    window.series.saveJser()
    return section.n


def _open_copy(window, tmp_path, qtbot):
    """Open a byte copy of the current series as series B."""
    first = window.series
    copy_fp = tmp_path / "series_b" / "series_b.jser"
    copy_fp.parent.mkdir()
    shutil.copyfile(first.jser_fp, copy_fp)
    window.openSeries(jser_fp=str(copy_fp), query_prev=False)
    assert window.series is not first
    assert window.series.jser_fp == str(copy_fp)
    # a closed list is deleted on the next event-loop pass (WA_DeleteOnClose)
    qtbot.wait(10)


def _counts(series, snum):
    """How many traces each object has on one section, read from disk."""
    section = series.loadSection(snum)
    return {name: len(traces) for name, traces in section.contours.items()}


def _press_if_open(dialog, method):
    """Press a list's button the way a user still could, if it is open."""
    if isValid(dialog) and dialog.isVisible():
        getattr(dialog, method)()


def test_a_pixel_dust_list_from_a_cannot_delete_in_b(
    main_window, main_window_dialogs, confirmed, tmp_path, qtbot
):
    window = main_window
    snum = _plant(window, "SWITCH_DUST", DUST)
    main_window_dialogs.responses = [([10.0], True)]
    window.removePixelDustTraces()
    dialog = window.pixel_dust_dialog
    assert any(
        r["name"] == "SWITCH_DUST" and r["section"] == snum
        for r in dialog.records
    )

    _open_copy(window, tmp_path, qtbot)
    before = _counts(window.series, snum)
    assert before["SWITCH_DUST"] == 1

    _press_if_open(dialog, "deleteAllContours")

    assert _counts(window.series, snum) == before
    assert not window.series.modified


def test_a_duplicates_list_from_a_cannot_combine_in_b(
    main_window, main_window_dialogs, confirmed, tmp_path, qtbot
):
    window = main_window
    snum = _plant(window, "SWITCH_DUP", SQUARE, copies=2)
    main_window_dialogs.responses = [
        ([0.95, [("check locked traces", False)]], True)
    ]
    window.reviewDuplicateTraces()
    dialog = window.duplicate_traces_dialog
    # one name in the row, so it is picked and Combine all would act on it
    assert any(
        g["names"] == ["SWITCH_DUP"] and g["section"] == snum
        for g, _keep in dialog.choices()
    )

    _open_copy(window, tmp_path, qtbot)
    before = _counts(window.series, snum)
    assert before["SWITCH_DUP"] == 2

    _press_if_open(dialog, "combineAll")

    assert _counts(window.series, snum) == before
    assert not window.series.modified


def test_every_clean_up_list_closes_when_another_series_opens(
    main_window, tmp_path, qtbot
):
    from PyReconstruct.modules.gui.dialog.malformed_contours import (
        DuplicateTracesDialog,
        MalformedContoursDialog,
        PixelDustDialog,
        RepairedCrossingsDialog,
        SkippedCrossingsDialog,
    )
    window = main_window
    field = window.field
    record = {
        "name": "SWITCH_ROW", "section": field.section.n, "index": 0,
        "points": 4, "location": (0.5, 0.5), "reason": "", "area": 0.01,
        "area_px": 1.0,
    }
    group = {
        "section": field.section.n, "members": [dict(record), dict(record)],
        "names": ["SWITCH_ROW"], "count": 2, "ratio": 1.0,
        "location": (0.5, 0.5),
    }
    nav = field.focusMalformedContour
    dialogs = [
        MalformedContoursDialog(
            window, [dict(record)], navigate=nav,
            delete=field.deleteMalformedContours,
        ),
        PixelDustDialog(
            window, [dict(record)], navigate=nav,
            delete=field.deleteMalformedContours,
        ),
        DuplicateTracesDialog(
            window, [group], navigate=nav,
            combine=field.combineDuplicateTraces,
        ),
        RepairedCrossingsDialog(window, [dict(record)], navigate=nav),
        SkippedCrossingsDialog(window, [dict(record)], navigate=nav),
    ]
    for dialog in dialogs:
        dialog.show()

    _open_copy(window, tmp_path, qtbot)

    still_open = [
        type(d).__name__ for d in dialogs if isValid(d) and d.isVisible()
    ]
    assert still_open == []
