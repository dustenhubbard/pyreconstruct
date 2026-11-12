"""Field gestures must preserve trace geometry, attributes, and selection."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from PyReconstruct.modules.datatypes import Trace, Transform
from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    CLOSEDTRACE,
    GRID,
    OPENTRACE,
    POINTER,
    STAMP,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def tool_field(main_window, local_series_settings):
    series = local_series_settings(main_window)
    field = main_window.field
    for trace in field.section.tracesAsList():
        field.section.removeTrace(trace, log_event=False)
    field.section.selected_traces = []
    field.section.tform = Transform.identity()
    width, height = field.pixmap_dim
    # One screen pixel is 0.01 field units, with (0, 0) at the top left.
    series.window = [0, -height / 100, width / 100, height / 100]
    series.setOption("trace_mode", "scribble")
    series.setOption("roll_average", False)
    series.setOption("auto_merge", False)
    field.setTracingTrace(Trace("gesture", (20, 120, 220), closed=True))
    field.tracing_trace.points = [(-0.1, 0), (0, 0.1), (0.1, 0), (0, -0.1)]
    field.tracing_trace.tags = {"keep"}
    field.generateView()
    return field


def _mouse(field, kind, point, button=Qt.NoButton, buttons=Qt.NoButton):
    event = QMouseEvent(
        kind, QPointF(*point), QPointF(*point), button, buttons, Qt.NoModifier
    )
    QCoreApplication.sendEvent(field, event)


def _press(field, point):
    _mouse(field, QEvent.MouseButtonPress, point, Qt.LeftButton, Qt.LeftButton)


def _move(field, point):
    field.click_time = 0
    _mouse(field, QEvent.MouseMove, point, buttons=Qt.LeftButton)


def _release(field, point):
    _mouse(field, QEvent.MouseButtonRelease, point, Qt.LeftButton)


def _draw(field, points):
    _press(field, points[0])
    for point in points[1:]:
        _move(field, point)
    _release(field, points[-1])


def _add(field, name, points):
    field.newTrace(points, Trace(name, (20, 120, 220)), reduce_points=False)
    return field.section.contours[name][-1]


@pytest.mark.parametrize("refusal", ["empty-rectangle", "hidden-layer"])
@pytest.mark.parametrize("pending_redo", [False, True], ids=["undo", "redo"])
def test_rejected_scribble_preserves_existing_traces_and_history(
    tool_field, refusal, pending_redo
):
    field = tool_field
    _add(field, "gesture", [(100, 100), (200, 100), (200, 200), (100, 200)])
    _add(field, "gesture", [(150, 150), (250, 150), (250, 250), (150, 250)])
    expected_points = [
        [(1, -1), (2, -1), (2, -2), (1, -2)],
        [(1.5, -1.5), (2.5, -1.5), (2.5, -2.5), (1.5, -2.5)],
    ]
    if pending_redo:
        field.undoState()
    originals = list(field.section.contours["gesture"])
    field.section.selected_traces = originals.copy()
    points_before = [list(t.points) for t in originals]
    field.series.setOption("auto_merge", True)
    field.setMouseMode(CLOSEDTRACE)
    field.closed_trace_shape = "rect"
    field.hide_trace_layer = refusal == "hidden-layer"

    path = [(100, 100), (180, 180)]
    if refusal == "empty-rectangle":
        path.append((100, 100))
    _draw(field, path)

    assert list(field.section.contours["gesture"]) == originals
    assert [list(t.points) for t in originals] == points_before
    assert field.section.selected_traces == originals
    assert field.current_trace == []

    field.hide_trace_layer = False
    if not pending_redo:
        field.undoState()
        remaining = list(field.section.contours["gesture"])
        assert len(remaining) == 1
        assert len(remaining[0].points) == 4
        for point, expected in zip(remaining[0].points, expected_points[0]):
            assert point == pytest.approx(expected)

    field.undoState(redo=True)
    restored = list(field.section.contours["gesture"])
    assert len(restored) == 2
    for trace, points in zip(restored, expected_points):
        assert len(trace.points) == 4
        for point, expected in zip(trace.points, points):
            assert point == pytest.approx(expected)


@pytest.mark.parametrize("mode", [CLOSEDTRACE, OPENTRACE], ids=["closed", "open"])
def test_scribble_stores_the_drawn_geometry_and_palette_attributes(tool_field, mode):
    field = tool_field
    field.setMouseMode(mode)
    _draw(field, [(100, 100), (200, 100), (200, 200), (100, 200)])

    trace, = field.section.contours["gesture"]
    assert len(trace.points) == 4
    for point, expected in zip(sorted(trace.points), [(1, -2), (1, -1), (2, -2), (2, -1)]):
        assert point == pytest.approx(expected)
    assert trace.closed is (mode == CLOSEDTRACE)
    assert trace.color == (20, 120, 220)
    assert trace.tags == {"keep"}
    assert field.section.selected_traces == [trace]


def test_ellipse_drag_fills_the_dragged_bounds(tool_field):
    field = tool_field
    field.setMouseMode(CLOSEDTRACE)
    field.closed_trace_shape = "circle"
    _draw(field, [(100, 100), (200, 160)])

    trace, = field.section.contours["gesture"]
    assert trace.closed is True
    assert trace.getBounds() == pytest.approx((1, -1.6, 2, -1), abs=0.01)
    assert trace.getCentroid() == pytest.approx((1.5, -1.3), abs=0.01)


def test_stamp_click_centers_a_copy_without_changing_the_palette_shape(tool_field):
    field = tool_field
    field.setMouseMode(STAMP)
    palette_points = list(field.tracing_trace.points)
    _press(field, (100, 120))
    _release(field, (100, 120))

    trace, = field.section.contours["gesture"]
    assert len(trace.points) == 4
    for point, expected in zip(trace.points, [(0.9, -1.2), (1, -1.1), (1.1, -1.2), (1, -1.3)]):
        assert point == pytest.approx(expected)
    assert trace.tags == {"keep"}
    assert field.tracing_trace.points == palette_points


def test_stamp_drag_uses_the_diameter_and_midpoint(tool_field):
    field = tool_field
    field.setMouseMode(STAMP)
    _draw(field, [(100, 100), (140, 100)])

    trace, = field.section.contours["gesture"]
    assert trace.getCentroid() == pytest.approx((1.2, -1))
    assert trace.getRadius() == pytest.approx(0.2)
    assert trace.closed is True
    assert trace.tags == {"keep"}
    assert field.tracing_trace.getRadius() == pytest.approx(0.1)
    assert field.current_trace == []
    assert field.is_drawing_rad is False


@pytest.mark.parametrize("sampling", [False, True], ids=["regular", "sampling-frame"])
def test_grid_click_places_rows_columns_and_sampling_edges(tool_field, sampling):
    field = tool_field
    field.series.setOption("sampling_frame_grid", sampling)
    field.series.setOption("grid", [0.4, 0.2, 0.6, 0.5, 2, 2])
    field.setMouseMode(GRID)
    _press(field, (100, 100))
    _release(field, (100, 100))

    traces = list(field.section.contours["gesture"])
    if sampling:
        assert len(traces) == 8
        assert [t.closed for t in traces] == [False] * 8
        assert [t.color for t in traces] == [(255, 0, 0), (0, 255, 0)] * 4
        red_points = [
            (1, -0.9), (1, -1), (1, -1.2), (1.4, -1.2), (1.4, -1.3)
        ]
        green_points = [(1, -1), (1.4, -1), (1.4, -1.2)]
        for trace, points in zip(traces[:2], [red_points, green_points]):
            assert len(trace.points) == len(points)
            for point, expected in zip(trace.points, points):
                assert point == pytest.approx(expected)
        expected_bounds = [
            (1, -1.3, 1.4, -0.9), (1, -1.2, 1.4, -1),
            (1, -1.8, 1.4, -1.4), (1, -1.7, 1.4, -1.5),
            (1.6, -1.3, 2, -0.9), (1.6, -1.2, 2, -1),
            (1.6, -1.8, 2, -1.4), (1.6, -1.7, 2, -1.5),
        ]
    else:
        assert len(traces) == 4
        assert [t.closed for t in traces] == [True] * 4
        expected_bounds = [
            (1, -1.2, 1.4, -1), (1, -1.7, 1.4, -1.5),
            (1.6, -1.2, 2, -1), (1.6, -1.7, 2, -1.5),
        ]
    for trace, bounds in zip(traces, expected_bounds):
        assert trace.getBounds() == pytest.approx(bounds)
    assert field.section.selected_traces == traces
    assert all(t.tags == {"keep"} for t in traces)


@pytest.mark.parametrize("shape", ["rect", "lasso"])
@pytest.mark.parametrize("inclusion", ["inc", "exc"])
def test_lasso_selection_obeys_inclusion_and_visibility(tool_field, shape, inclusion):
    field = tool_field
    inside = _add(field, "inside", [(120, 120), (140, 120), (140, 140), (120, 140)])
    crossing = _add(field, "crossing", [(180, 180), (220, 180), (220, 220), (180, 220)])
    _add(field, "outside", [(250, 250), (270, 250), (270, 270), (250, 270)])
    hidden = _add(field, "hidden", [(150, 120), (170, 120), (170, 140), (150, 140)])
    hidden.hidden = True
    field.section.selected_traces = []
    field.series.setOption("pointer", [shape, inclusion])
    field.setMouseMode(POINTER)
    field.generateView()

    path = [(100, 100), (100, 100), (200, 200)] if shape == "rect" else [
        (100, 100), (100, 100), (200, 100), (200, 200), (100, 200)
    ]
    _draw(field, path)

    assert field.section.selected_traces == ([inside, crossing] if inclusion == "inc" else [inside])
    assert field.current_trace == []
    assert field.is_selecting_traces is False
    assert field.mouse_boundary_timer is None
