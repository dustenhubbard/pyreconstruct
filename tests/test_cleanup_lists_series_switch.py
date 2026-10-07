"""The clean-up review lists close when another series opens.

Each list (pixel dust, Duplicates, traces skipped during smoothing, and the
repaired and skipped self-crossing lists) is modeless and keeps its buttons
bound to the FieldWidget. Opening another series reuses that FieldWidget with
the new series in it, so a list left open from series A deleted or combined
the matching trace in series B. Here A and B are byte copies, so every row of
A's list names a trace that also exists in B.

A Delete or Combine can also be waiting on its confirmation when B opens:
the confirmation is modal, so the menus wait, but a .jser opened from the
Finder still reaches the window. Answering it afterwards resumed the action
against B, on a list that was already closed and deleted.

What is pinned here:

  * Delete all in a pixel-dust list opened in A leaves B unchanged
  * Combine all in a Duplicates list opened in A leaves B unchanged
  * every kind of clean-up list is closed once B is open
  * a Delete (pixel dust, smoothing list) or Combine confirmed after B opened
    from the Finder leaves B unchanged
  * a notice from a Delete or Combine that B opens under ends the action
    without touching the closed list
"""
import shutil

import pytest
from shiboken6 import isValid

pytestmark = pytest.mark.gui

DUST = [(0.0, 0.0), (0.001, 0.0), (0.001, 0.001), (0.0, 0.001)]
SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
# two points cannot be smoothed, so the smoothing list names the trace
TWO_POINTS = [(1.0, 1.0), (1.5, 1.0)]
# smoothing walks the sections the series has an object on, so the smoothing
# list needs an object the fixture series has on the section it opens on
ON_OPEN_SECTION = "d03sp14"


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


@pytest.fixture
def finder(qapp, main_window):
    """Route a .jser opened from the Finder to the window, as the app does."""
    from PyReconstruct.run import FileOpenWatcher
    watcher = FileOpenWatcher()
    watcher.main_window = main_window
    qapp.installEventFilter(watcher)
    yield watcher
    qapp.removeEventFilter(watcher)


def _open_copy(window, tmp_path, qtbot, from_finder=False):
    """Open a byte copy of the current series as series B.

    from_finder sends the file-open event the Finder sends (needs the
    finder fixture) instead of calling openSeries.
    """
    first = window.series
    copy_fp = tmp_path / "series_b" / "series_b.jser"
    copy_fp.parent.mkdir()
    shutil.copyfile(first.jser_fp, copy_fp)
    if from_finder:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QFileOpenEvent
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        app.sendEvent(app, QFileOpenEvent(QUrl.fromLocalFile(str(copy_fp))))
    else:
        window.openSeries(jser_fp=str(copy_fp), query_prev=False)
    assert window.series is not first
    assert window.series.jser_fp == str(copy_fp)
    # a closed list is deleted on the next event-loop pass (WA_DeleteOnClose)
    qtbot.wait(10)


def _counts(series, snum):
    """How many traces each object has on one section, read from disk."""
    section = series.loadSection(snum)
    return {name: len(traces) for name, traces in section.contours.items()}


@pytest.fixture
def confirmed_after_b_opens(monkeypatch, main_window, finder, tmp_path, qtbot):
    """Accept a Delete or Combine confirmation only after B opens under it.

    The wait inside stands in for the confirmation's own event loop, which
    deletes the list that closed before the answer comes back. Returns the
    confirmations asked.
    """
    from PyReconstruct.modules.gui.dialog import malformed_contours
    asked = []

    def confirm(message, *args, **kwargs):
        asked.append(message)
        _open_copy(main_window, tmp_path, qtbot, from_finder=True)
        return True

    monkeypatch.setattr(malformed_contours, "notifyConfirm", confirm)
    return asked


def _b_opens_on_the_next_notice(monkeypatch, window, tmp_path, qtbot):
    """Open B from the Finder while the field's next notice is up.

    Returns the notices shown.
    """
    from PyReconstruct.modules.gui.main import field_widget_3_object
    notices = []

    def notice(message, *args, **kwargs):
        notices.append(message)
        if len(notices) == 1:
            _open_copy(window, tmp_path, qtbot, from_finder=True)

    monkeypatch.setattr(field_widget_3_object, "notify", notice)
    return notices


def _select_object(field, name):
    """Select every trace of one object on the current section."""
    field.section.selected_traces.clear()
    for trace in field.section.contours[name]:
        field.section.addSelectedTrace(trace)


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


@pytest.mark.parametrize("kind", ["pixel dust", "smoothing"])
def test_a_delete_confirmed_after_b_opens_leaves_b_alone(
    kind, main_window, main_window_dialogs, confirmed_after_b_opens, qtbot
):
    window = main_window
    if kind == "pixel dust":
        name = "SWITCH_DUST"
        snum = _plant(window, name, DUST)
        main_window_dialogs.responses = [([10.0], True)]
        window.removePixelDustTraces()
        dialog = window.pixel_dust_dialog
    else:
        name = ON_OPEN_SECTION
        snum = _plant(window, name, TWO_POINTS)
        _select_object(window.field, name)
        window.field.smoothObject()
        dialog = window.field.malformed_contours_dialog
    assert any(
        r["name"] == name and r["section"] == snum for r in dialog.records
    )
    first = window.series
    # B opens as a byte copy of A as saved
    saved = _counts(first, snum)

    dialog.deleteAllContours()

    assert len(confirmed_after_b_opens) == 1
    assert window.series is not first
    assert _counts(window.series, snum) == saved
    assert not window.series.modified


def test_a_combine_confirmed_after_b_opens_leaves_b_alone(
    main_window, main_window_dialogs, confirmed_after_b_opens, qtbot
):
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

    dialog.combineAll()

    assert len(confirmed_after_b_opens) == 1
    assert window.series is not first
    assert _counts(window.series, snum) == saved
    assert not window.series.modified


def test_b_opening_under_a_notice_from_delete_ends_it_quietly(
    main_window, main_window_dialogs, confirmed, finder, monkeypatch,
    tmp_path, qtbot
):
    window = main_window
    snum = _plant(window, "SWITCH_DUST", DUST)
    _plant(window, "SWITCH_GONE", [(x + 2.0, y) for x, y in DUST])
    main_window_dialogs.responses = [([10.0], True)]
    window.removePixelDustTraces()
    dialog = window.pixel_dust_dialog
    # one listed trace goes first, so the delete ends on a "not found" notice
    gone = window.field.section.contours["SWITCH_GONE"][0]
    window.field.section.removeTrace(gone, log_event=False)
    window.saveAllData()
    notices = _b_opens_on_the_next_notice(monkeypatch, window, tmp_path, qtbot)
    first = window.series

    dialog.deleteAllContours()

    assert len(notices) == 1 and "not found" in notices[0]
    assert window.series is not first
    assert _counts(window.series, snum)["SWITCH_DUST"] == 1
    assert not window.series.modified


def test_b_opening_under_a_notice_from_combine_ends_it_quietly(
    main_window, main_window_dialogs, confirmed, finder, monkeypatch,
    tmp_path, qtbot
):
    window = main_window
    snum = _plant(window, "SWITCH_DUP", SQUARE, copies=2)
    _plant(window, "SWITCH_MOVED", [(x + 3.0, y) for x, y in SQUARE], copies=2)
    main_window_dialogs.responses = [
        ([0.95, [("check locked traces", False)]], True)
    ]
    window.reviewDuplicateTraces()
    dialog = window.duplicate_traces_dialog
    picked = {g["names"][0] for g, _keep in dialog.choices()}
    assert {"SWITCH_DUP", "SWITCH_MOVED"} <= picked
    # one row's traces change first, so the combine ends on a notice
    moved = window.field.section.contours["SWITCH_MOVED"][0]
    window.field.section.removeTrace(moved, log_event=False)
    window.saveAllData()
    notices = _b_opens_on_the_next_notice(monkeypatch, window, tmp_path, qtbot)
    first = window.series

    dialog.combineAll()

    assert len(notices) == 1 and "changed" in notices[0]
    assert window.series is not first
    assert _counts(window.series, snum)["SWITCH_DUP"] == 2
    assert not window.series.modified
