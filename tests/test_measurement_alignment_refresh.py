"""Alignment edits refresh measurements and the open trace list."""

import pytest

from PyReconstruct.modules.datatypes import Trace, Transform

pytestmark = pytest.mark.gui


@pytest.fixture
def measured_window(main_window):
    field = main_window.field
    section = field.section
    section.align_locked = False
    section.tform = Transform.identity()
    section.thickness = 0.05
    trace = Trace("measurement_line", (255, 0, 0), False)
    trace.points = [(0, 0), (3, 4)]
    section.addTrace(trace, log_event=False)
    field.saveState()
    field.table_manager.newTable("trace", section)
    return main_window


def _listed_length(window):
    widget = window.field.table_manager.tables["trace"][-1]
    row, found = widget.table.getRowIndex("measurement_line")
    assert found
    column = next(i for i, name in enumerate(widget.getHeaders()) if name.startswith("Length"))
    return float(widget.table.item(row, column).text())


@pytest.mark.parametrize("matrix,length,center,radius", [
    ([2, 0, 10, 0, 0.5, 5], 6.324555320336759, (13, 6), 3.1622776601683795),
    ([1, 0, 10, 0, 1, 5], 5, (11.5, 7), 2.5),
    ([0, -1, 0, 1, 0, 0], 5, (-2, 1.5), 2.5),
    ([1, 1, 0, 0, 1, 0], 8.06225774829855, (3.5, 2), 4.031128874149275),
], ids=["anisotropic", "translation", "rotation", "shear"])
def test_committed_alignment_updates_measurements(measured_window, matrix, length, center, radius):
    window = measured_window
    field = window.field
    data = window.series.data
    assert data.getFlatArea("measurement_line") == pytest.approx(0.25)
    assert _listed_length(window) == 5

    field.changeTform(Transform(matrix))

    trace_data = data.getTraceData("measurement_line", field.section.n)[0]
    assert trace_data.getLength() == pytest.approx(length)
    assert trace_data.getCentroid() == pytest.approx(center)
    assert trace_data.getRadius() == pytest.approx(radius)
    assert data.getFlatArea("measurement_line") == pytest.approx(length * 0.05)
    assert _listed_length(window) == pytest.approx(length, abs=0.000005)

    field.undoState()
    restored = data.getTraceData("measurement_line", field.section.n)[0]
    assert restored.getLength() == 5
    assert restored.getCentroid() == (1.5, 2)
    assert _listed_length(window) == 5

    field.undoState(redo=True)
    redone = data.getTraceData("measurement_line", field.section.n)[0]
    assert redone.getLength() == pytest.approx(length)
    assert redone.getCentroid() == pytest.approx(center)
    assert _listed_length(window) == pytest.approx(length, abs=0.000005)


def test_saved_alignment_refreshes_the_open_trace_list(measured_window):
    window = measured_window
    section = window.field.section
    assert _listed_length(window) == 5
    section.tform = Transform([2, 0, 10, 0, 0.5, 5])
    section.save()
    assert window.series.data.getFlatArea("measurement_line") == pytest.approx(0.316227766016838)

    window.field.table_manager.updateObjects()

    assert _listed_length(window) == pytest.approx(6.32456)


def test_closed_trace_remeasures_length_radius_and_cached_feret(measured_window):
    window = measured_window
    field = window.field
    trace = Trace("measurement_square", (0, 255, 0), True)
    trace.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
    field.section.addTrace(trace, log_event=False)
    field.saveState()
    data = window.series.data
    original = data.getTraceData(trace.name, field.section.n)[0]
    assert original.getFeret(field.section, trace.name) == pytest.approx((1, 1.4142135623730951))

    field.changeTform(Transform([2, 0, 10, 0, 0.5, 5]))

    measured = data.getTraceData(trace.name, field.section.n)[0]
    assert measured.getLength() == pytest.approx(5)
    assert measured.getCentroid() == pytest.approx((11, 5.25))
    assert measured.getRadius() == pytest.approx(1.0307764064044151)
    assert measured.getFeret(field.section, trace.name) == pytest.approx((0.5, 2.0615528128088303))
    assert measured.getArea() == pytest.approx(1)
    assert data.getVolume(trace.name) == pytest.approx(0.05)
