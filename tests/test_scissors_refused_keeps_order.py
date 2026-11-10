"""A scissors cut that cannot finish puts the trace back in its own place.

The scissors pickup takes the clicked trace out of its contour. While the
trace layer is hidden, newTrace refuses the replacement, so finishing the cut
puts the original back instead. It went back at the end of the contour, which
moved it past the object's other traces: Trace List rows are (name, index)
into the contour, so the row that showed it then selected another trace.

Driven through the live `MainWindow`: a real left click with the Scissors
tool, the real Toggle hide all action, and a real right-click to finish.
"""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from PyReconstruct.modules.gui.main.field_widget_5_mouse import SCISSORS

pytestmark = pytest.mark.gui


def _two_traces(field):
    """An unlocked closed trace of the fixture and a copy of it beside it,
    both in the same contour, in that order."""
    for name, contour in field.section.contours.items():
        if field.series.getAttr(name, "locked"):
            continue
        for first in contour.getTraces():
            if first.closed and len(first.points) >= 3:
                break
        else:
            continue
        # one trace in the contour, so the order below is only these two
        if len(contour.getTraces()) != 1:
            continue
        second = first.copy()
        xs = [x for x, _ in first.points]
        shift = (max(xs) - min(xs)) * 2 + 1
        second.points = [(x + shift, y) for x, y in first.points]
        field.section.addTrace(second, log_event=False)
        field.saveState()
        field.generateView()
        assert field.section.contours[name].getTraces() == [first, second]
        return name, first, second
    raise AssertionError("fixture section has no unlocked single-trace object")


def test_a_refused_cut_keeps_the_trace_in_its_place(
    main_window, qapp, local_series_settings
):
    local_series_settings(main_window)  # trace_mode is written on release
    field = main_window.field
    name, first, second = _two_traces(field)

    field.table_manager.newTable("trace", field.section)
    qapp.processEvents()
    table = field.table_manager.tables["trace"][-1]
    assert table.getTraces([(name, 0)]) == [first]

    main_window.mouse_palette.activateModeButton("Scissors")
    qapp.processEvents()
    assert field.mouse_mode == SCISSORS
    x, y = [int(round(v)) for v in field.section_layer.traceToPix(first)[0]]
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    qapp.processEvents()
    assert field.is_scissoring
    assert field.tracing_trace is first

    main_window.hideall_act.trigger()  # Toggle hide all
    qapp.processEvents()
    assert field.hide_trace_layer
    QTest.mouseClick(field, Qt.RightButton, Qt.NoModifier, QPoint(x + 20, y + 20))
    qapp.processEvents()
    assert not field.is_scissoring

    traces = field.section.contours[name].getTraces()
    assert len(traces) == 2
    assert traces[0] is first, "the refused cut moved the trace in its contour"
    assert traces[1] is second
    assert table.getTraces([(name, 0)])[0] is first
    assert table.getTraces([(name, 1)])[0] is second

    # the columnar store holds its own within-contour order; it has to match
    section = field.section
    assert section._columns is not None
    assert section._columns.rowsForContour(name) == [
        section._column_rows[first], section._column_rows[second]
    ]
    section._assertColumnsMatchObjectModel("refused scissors cut")
