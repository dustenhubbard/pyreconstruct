"""Undo after a scissors cut that auto-merges gives back the traces before the cut.

The scissors pickup takes the trace out of the section and saves no undo state,
and the finished cut used to record its state only at the very end of
`lineRelease`. `autoMerge` runs before that end, and it folds the merge's undo
state into the one the draw saved: it counts the states, merges, and drops the
states the merge added. A pencil draw has saved its state by then, but a cut
had not, so the state the merge pushed was the one holding the section before
the cut, and dropping it lost that. The cut's own state, saved after the merge,
held the merged trace, so Undo gave back the merged trace instead of the two
traces the cut started from.

The cut now records its state as soon as the trace is back, the way a draw
does, so the merge folds into it and one Undo takes back cut and merge alike.

Driven through the live `MainWindow`: a real left click with the Scissors tool,
then each way a cut can be finished: a right click, Cmd+Z in the middle of the
cut, and a change of tool.
"""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.gui.main.field_widget_5_mouse import SCISSORS

pytestmark = pytest.mark.gui

NAME = "scissors_automerge_obj"

# pixel-space squares; the second overlaps the first, the third is far away
SQ_ORIGINAL = [(100, 300), (200, 300), (200, 200), (100, 200)]
SQ_OVERLAP = [(150, 350), (250, 350), (250, 250), (150, 250)]
SQ_DISJOINT = [(500, 800), (600, 800), (600, 700), (500, 700)]

# the corner of SQ_ORIGINAL farthest from the other squares, so the scissors
# pick it and not its neighbor
CLICK = (100, 200)


def _traces(field):
    """The object's traces, as sorted point lists."""
    return sorted(list(t.points) for t in field.section.contours.get(NAME, []))


def _setup(main_window, second):
    """Draw two same-name closed traces, unmerged, then turn auto-merge on."""
    field = main_window.field
    field.series.setOption("auto_merge", False)
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(SQ_ORIGINAL, field.tracing_trace, closed=True)
    field.newTrace(second, field.tracing_trace, closed=True)
    field.section.selected_traces = []
    field.series.setOption("auto_merge", True)
    field.series.setOption("auto_merge_selected_only", False)
    field.generateView()
    return field


def _pickup(main_window, qapp):
    field = main_window.field
    main_window.mouse_palette.activateModeButton("Scissors")
    qapp.processEvents()
    assert field.mouse_mode == SCISSORS
    pix = field.section_layer.traceToPix
    original = min(
        (t for t in field.section.contours[NAME]),
        key=lambda t: min(
            (x - CLICK[0]) ** 2 + (y - CLICK[1]) ** 2 for x, y in pix(t)
        ),
    )
    x, y = min(
        pix(original),
        key=lambda p: (p[0] - CLICK[0]) ** 2 + (p[1] - CLICK[1]) ** 2,
    )
    point = QPoint(int(round(x)), int(round(y)))
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, point)
    qapp.processEvents()
    assert field.is_scissoring
    assert field.is_line_tracing
    assert len(field.section.contours[NAME]) == 1


def _right_click(main_window, qapp):
    field = main_window.field
    QTest.mouseClick(field, Qt.RightButton, Qt.NoModifier, QPoint(400, 400))
    qapp.processEvents()


def _change_tool(main_window, qapp):
    main_window.mouse_palette.activateModeButton("Pointer")
    qapp.processEvents()


def _cut_ends(field):
    assert not field.is_scissoring
    assert not field.is_line_tracing


@pytest.mark.parametrize("finish", [_right_click, _change_tool])
def test_one_undo_takes_back_a_cut_that_merges(main_window, qapp, finish):
    field = _setup(main_window, SQ_OVERLAP)
    before = _traces(field)
    assert len(before) == 2

    main_window.show()
    _pickup(main_window, qapp)
    finish(main_window, qapp)
    _cut_ends(field)
    merged = _traces(field)
    assert len(merged) == 1, "the finished cut did not auto-merge"

    main_window.undo()
    assert _traces(field) == before, (
        "Undo after a scissors cut that auto-merged gave back "
        f"{len(_traces(field))} trace(s), not the two from before the cut"
    )

    main_window.undo(redo=True)
    assert _traces(field) == merged


def test_undo_in_the_middle_of_a_cut_that_merges(main_window, qapp):
    """Cmd+Z finishes the cut and takes it back, merge included."""
    field = _setup(main_window, SQ_OVERLAP)
    before = _traces(field)

    main_window.show()
    _pickup(main_window, qapp)
    QTest.keySequence(main_window, QKeySequence(main_window.undo_act.shortcut()))
    qapp.processEvents()

    _cut_ends(field)
    assert _traces(field) == before

    # Redo brings back the finished cut, merged
    main_window.undo(redo=True)
    assert len(_traces(field)) == 1


def test_a_cut_finished_from_a_focused_trace_list_still_merges(
    main_window, qapp, local_series_settings
):
    """The cut's undo state refreshes the Trace List, which drops its row
    selection; the merge must still run on the overlapping traces it found."""
    local_series_settings(main_window)
    field = _setup(main_window, SQ_OVERLAP)
    before = _traces(field)

    main_window.show()
    main_window.activateWindow()
    field.openList(list_type="trace")
    table = field.table_manager.tables["trace"][0]
    qapp.processEvents()
    _pickup(main_window, qapp)

    # click the remaining same-name row, so the list has focus and a selection
    row, found = table.table.getRowIndex(NAME)
    assert found
    rect = table.table.visualItemRect(table.table.item(row, 0))
    QTest.mouseClick(table.table.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    qapp.processEvents()
    assert field.table_manager.hasFocus() is table
    assert table.getSelected()
    assert field.is_scissoring

    # finish the cut with the Pointer shortcut, the list still focused
    QTest.keySequence(
        main_window, QKeySequence(main_window.usepointer_act.shortcut())
    )
    qapp.processEvents()
    _cut_ends(field)
    merged = _traces(field)
    assert len(merged) == 1, (
        "a cut finished with the Trace List focused did not auto-merge"
    )

    main_window.undo()
    assert _traces(field) == before
    main_window.undo(redo=True)
    assert _traces(field) == merged


def test_a_cut_that_does_not_merge_is_one_undo_step(main_window, qapp):
    """With nothing to merge into, the cut is still one step each way."""
    field = _setup(main_window, SQ_DISJOINT)
    before = _traces(field)
    states = field.series_states[field.section.n]
    undo_before = len(states.undo_states)

    main_window.show()
    _pickup(main_window, qapp)
    _right_click(main_window, qapp)
    _cut_ends(field)
    after = _traces(field)
    assert len(after) == 2
    assert len(states.undo_states) == undo_before + 1

    main_window.undo()
    assert _traces(field) == before
    assert len(states.undo_states) == undo_before

    main_window.undo(redo=True)
    assert _traces(field) == after
