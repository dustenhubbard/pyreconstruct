"""Backspacing a scissors cut down to one point puts the trace back.

The scissors pickup removes the clicked trace from the section and hands its
points to a line trace. Backspace takes points off that line, and at one point
it ends the line. Before the fix that last Backspace left `is_scissoring` set
and never put the trace back. The pickup is not logged and saves no undo state,
so undo could not bring it back either and the trace was gone.

Driven through the live `MainWindow`: a real left click on the trace with the
Scissors tool, then `MainWindow.backspace`, the slot behind the shortcut.
"""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from PyReconstruct.modules.gui.main.field_widget_5_mouse import SCISSORS

pytestmark = pytest.mark.gui


def _pick_trace(field, closed):
    """An unlocked trace of at least three points, opened if asked.

    The fixture section has closed traces only, so the open case opens one.
    The series is a per-test copy.
    """
    for name, contour in field.section.contours.items():
        if field.series.getAttr(name, "locked"):
            continue
        for trace in contour.getTraces():
            if trace.closed and len(trace.points) >= 3:
                trace.closed = closed
                field.generateView()
                return trace
    raise AssertionError("fixture section has no unlocked closed trace")


def _count(field, name):
    contour = field.section.contours.get(name)
    return len(contour.getTraces()) if contour else 0


def _pickup(main_window, qapp, trace):
    field = main_window.field
    main_window.mouse_palette.activateModeButton("Scissors")
    qapp.processEvents()
    assert field.mouse_mode == SCISSORS
    x, y = [int(round(v)) for v in field.section_layer.traceToPix(trace)[0]]
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    qapp.processEvents()


def _backspace_to_the_end(main_window):
    field = main_window.field
    for _ in range(len(field.current_trace) + 1):
        main_window.backspace()
        if not field.is_scissoring:
            return
    raise AssertionError("Backspace never ended the scissors cut")


@pytest.mark.parametrize("closed", [True, False])
def test_backspace_out_of_a_scissors_cut_restores_the_trace(main_window, qapp, closed):
    field = main_window.field
    trace = _pick_trace(field, closed)
    name = trace.name
    points = list(trace.points)
    before = _count(field, name)
    states = field.series_states[field.series.current_section]
    undo_before = len(states.undo_states)
    log_before = len(field.series.log_set.all_logs)

    _pickup(main_window, qapp, trace)
    assert field.is_scissoring
    assert _count(field, name) == before - 1

    _backspace_to_the_end(main_window)

    assert not field.is_scissoring
    assert not field.is_line_tracing
    assert field.current_trace == []
    assert field.mouse_mode == SCISSORS
    assert _count(field, name) == before
    restored = [t for t in field.section.contours[name].getTraces() if t.points == points]
    assert len(restored) == 1
    assert restored[0].closed == closed
    # backing out is not an edit: no undo state and no log entry
    assert len(states.undo_states) == undo_before
    assert len(field.series.log_set.all_logs) == log_before


@pytest.mark.parametrize("closed", [True, False])
def test_a_held_backspace_does_not_delete_the_restored_trace(main_window, qapp, closed):
    """Key repeat keeps calling backspace after the cancel. The restored trace
    is not selected, so the next repeat has nothing to delete."""
    field = main_window.field
    trace = _pick_trace(field, closed)
    name = trace.name
    before = _count(field, name)
    log_before = len(field.series.log_set.all_logs)

    _pickup(main_window, qapp, trace)
    _backspace_to_the_end(main_window)

    main_window.backspace()
    main_window.backspace()
    qapp.processEvents()

    assert _count(field, name) == before
    assert len(field.series.log_set.all_logs) == log_before
    assert trace not in field.section.selected_traces


def test_repeated_cancels_draw_the_trace_once(main_window, qapp):
    field = main_window.field
    trace = _pick_trace(field, True)
    added_before = list(field.section.added_traces)
    removed_before = list(field.section.removed_traces)

    for _ in range(2):
        _pickup(main_window, qapp, trace)
        assert field.is_scissoring
        _backspace_to_the_end(main_window)

    field.generateView(generate_image=False)
    qapp.processEvents()
    in_view = field.section_layer.traces_in_view
    assert sum(1 for t in in_view if t is trace) == 1

    assert field.section.added_traces == added_before
    assert field.section.removed_traces == removed_before


@pytest.mark.parametrize("closed", [True, False])
def test_undo_after_backing_out_undoes_the_earlier_edit(main_window, qapp, closed):
    """Undo after a cancel undoes the edit before the cut and keeps the trace."""
    field = main_window.field
    trace = _pick_trace(field, closed)
    name = trace.name
    points = list(trace.points)
    before = _count(field, name)

    # a real edit first, so the undo stack has something on it
    template = field.tracing_trace.copy()
    template.name = "undo_probe"
    new_name = template.name
    assert new_name != name
    new_before = _count(field, new_name)
    field.newTrace([(10, 10), (40, 10), (40, 40), (10, 40)], template, closed=True)
    qapp.processEvents()
    assert _count(field, new_name) == new_before + 1

    _pickup(main_window, qapp, trace)
    assert field.is_scissoring
    _backspace_to_the_end(main_window)
    main_window.undo()
    qapp.processEvents()

    assert _count(field, new_name) == new_before
    assert _count(field, name) == before
    assert any(t.points == points for t in field.section.contours[name].getTraces())


def test_the_scissors_work_again_after_backing_out(main_window, qapp):
    """A second pickup starts a fresh cut and finishes normally."""
    field = main_window.field
    trace = _pick_trace(field, True)
    name = trace.name
    before = _count(field, name)

    _pickup(main_window, qapp, trace)
    _backspace_to_the_end(main_window)

    restored = [t for t in field.section.contours[name].getTraces() if t.points == trace.points][0]
    _pickup(main_window, qapp, restored)
    assert field.is_scissoring
    assert field.is_line_tracing

    field.lineRelease(override=True)
    qapp.processEvents()

    assert not field.is_scissoring
    assert _count(field, name) == before


def test_a_cancel_keeps_the_trace_in_its_place_for_the_trace_list(main_window, qapp):
    """Trace List rows are (name, index) into the contour, and nothing
    refreshes them on a cancel. The restored trace has to go back to its old
    index, or the row that showed it would now select another trace."""
    field = main_window.field
    first = _pick_trace(field, True)
    name = first.name

    # a second trace of the same object, beside the first
    second = first.copy()
    xs = [x for x, _ in first.points]
    shift = (max(xs) - min(xs)) * 2 + 1
    second.points = [(x + shift, y) for x, y in first.points]
    field.section.addTrace(second, log_event=False)
    field.saveState()
    field.generateView()
    contour = field.section.contours[name]
    assert contour.getTraces() == [first, second]

    field.table_manager.newTable("trace", field.section)
    qapp.processEvents()
    table = field.table_manager.tables["trace"][-1]
    def row_items():
        return [
            (table.table.item(r, 0).text(), table.rows[r].index)
            for r in range(len(table.rows))
        ]

    assert (name, 0) in row_items()
    assert table.getTraces([(name, 0)]) == [first]

    _pickup(main_window, qapp, first)
    assert field.is_scissoring
    assert field.tracing_trace is first
    _backspace_to_the_end(main_window)
    qapp.processEvents()

    traces = field.section.contours[name].getTraces()
    assert len(traces) == 2
    assert traces[0] is first
    assert traces[1] is second
    assert (name, 0) in row_items()
    assert table.getTraces([(name, 0)])[0] is first
