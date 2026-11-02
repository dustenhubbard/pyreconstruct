"""A drag exceeds the click tolerance even inside the click time window."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.calc import pixmapPointToField
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.gui.main import field_widget
from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    CLOSEDTRACE, OPENTRACE, PANZOOM, POINTER, ROI_BOX, STAMP,
)
from tests.test_lasso_ends_on_tool_change_and_pinch import _add_square

pytestmark = pytest.mark.gui


def _mouse(field, kind, point):
    button = Qt.NoButton if kind == QEvent.MouseMove else Qt.LeftButton
    buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
    QApplication.sendEvent(field, QMouseEvent(
        kind, QPointF(point), QPointF(field.mapToGlobal(point)),
        button, buttons, Qt.NoModifier,
    ))


@pytest.fixture
def field(main_window, local_series_settings, monkeypatch):
    local_series_settings(main_window)
    field = main_window.field
    monkeypatch.setattr(field_widget.time, "time", lambda: 1000.0)
    return field


def _drag(field, start, points, elapsed=0.05):
    _mouse(field, QEvent.MouseButtonPress, start)
    field.click_time -= elapsed
    for point in points:
        _mouse(field, QEvent.MouseMove, point)
    _mouse(field, QEvent.MouseButtonRelease, points[-1])


@pytest.mark.parametrize("elapsed", [0.05, 0.5], ids=["quick", "slow"])
def test_roi_drag_sets_size(field, elapsed):
    field.setMouseMode(ROI_BOX)
    start, end = QPoint(200, 200), QPoint(250, 230)
    scale = field.series.window[2] / field.pixmap_dim[0]

    _drag(field, start, [end], elapsed)

    assert field.roi_box_size == pytest.approx((50 * scale, 30 * scale))


@pytest.mark.parametrize("path", [[], [QPoint(201, 200)], [QPoint(204, 204)]],
                         ids=["still", "drift", "tolerance"])
def test_quick_roi_click_keeps_size(field, path):
    field.setMouseMode(ROI_BOX)
    size = field.roi_box_size
    start = QPoint(200, 200)
    expected_center = pixmapPointToField(
        200, 200, field.pixmap_dim, field.series.window, field.section.mag
    )
    _mouse(field, QEvent.MouseButtonPress, start)
    for point in path:
        _mouse(field, QEvent.MouseMove, point)
    _mouse(field, QEvent.MouseButtonRelease, path[-1] if path else start)

    assert field.roi_box_size == size
    assert field.roi_box_center == pytest.approx(expected_center)


def test_drag_returning_near_press_stays_a_drag(field):
    field.setMouseMode(ROI_BOX)
    scale = field.series.window[2] / field.pixmap_dim[0]

    _drag(field, QPoint(200, 200), [QPoint(250, 230), QPoint(202, 201)])

    assert field.roi_box_size == pytest.approx((2 * scale, scale))


def test_release_beyond_tolerance_counts_as_a_drag(field):
    field.setMouseMode(ROI_BOX)
    scale = field.series.window[2] / field.pixmap_dim[0]
    _mouse(field, QEvent.MouseButtonPress, QPoint(200, 200))
    _mouse(field, QEvent.MouseMove, QPoint(201, 201))
    _mouse(field, QEvent.MouseButtonRelease, QPoint(250, 230))

    assert field.roi_box_size == pytest.approx((50 * scale, 30 * scale))


@pytest.mark.parametrize("elapsed", [0.05, 0.5], ids=["quick", "slow"])
def test_pointer_drag_moves_selected_trace(field, elapsed):
    field.setMouseMode(POINTER)
    trace = _add_square(field, "move_me", 200, 200, 220, 220)
    field.section.selected_traces = [trace]
    before = list(trace.points)
    scale = field.series.screen_mag

    _drag(field, QPoint(200, 200), [QPoint(250, 230)], elapsed)

    assert field.section.selected_traces == [trace]
    for point, (x, y) in zip(trace.points, before):
        assert point == pytest.approx((x + 50 * scale, y - 30 * scale))
    assert not field.section.temp_hide

    _mouse(field, QEvent.MouseButtonPress, QPoint(250, 230))
    _mouse(field, QEvent.MouseButtonRelease, QPoint(250, 230))
    assert field.section.selected_traces == []


@pytest.mark.parametrize("shape", ["rect", "lasso"])
@pytest.mark.parametrize("elapsed", [0.05, 0.5], ids=["quick", "slow"])
def test_pointer_drag_selects_area(field, shape, elapsed):
    field.setMouseMode(POINTER)
    field.series.setOption("pointer", [shape, "exc"])
    trace = _add_square(field, "select_me", 210, 210, 220, 220)
    start = QPoint(200, 200)
    if shape == "rect":
        points = [QPoint(240, 240)]
    else:
        points = [start, QPoint(240, 200), QPoint(240, 240), QPoint(200, 240)]

    _drag(field, start, points, elapsed)

    assert field.section.selected_traces == [trace]
    assert not field.is_selecting_traces
    assert field.mouse_boundary_timer is None


@pytest.mark.parametrize("mode", [CLOSEDTRACE, OPENTRACE])
def test_quick_combo_drag_draws_trace(field, mode):
    field.setMouseMode(mode)
    field.series.setOption("trace_mode", "combo")
    field.series.setOption("roll_average", False)
    field.series.setOption("auto_merge", False)
    field.tracing_trace = Trace("quick_trace", (255, 0, 255))

    _drag(field, QPoint(200, 200), [QPoint(250, 200), QPoint(250, 230)])

    assert not field.is_line_tracing
    (trace,) = field.section.contours["quick_trace"]
    assert len(trace.points) == 3
    assert trace.closed is (mode == CLOSEDTRACE)


@pytest.mark.parametrize("shape", ["rect", "circle"])
@pytest.mark.parametrize("path", ["release-only", "small-move", "final-move"])
def test_shape_drag_uses_release_position(field, shape, path):
    field.setMouseMode(CLOSEDTRACE)
    field.closed_trace_shape = shape
    field.series.setOption("trace_mode", "combo")
    field.series.setOption("roll_average", False)
    field.series.setOption("auto_merge", False)
    field.tracing_trace = Trace("quick_shape", (255, 0, 255))
    start, end = QPoint(200, 200), QPoint(250, 230)
    scale = field.series.screen_mag

    _mouse(field, QEvent.MouseButtonPress, start)
    if path == "small-move":
        _mouse(field, QEvent.MouseMove, QPoint(201, 201))
    elif path == "final-move":
        _mouse(field, QEvent.MouseMove, end)
    _mouse(field, QEvent.MouseButtonRelease, end)

    assert not field.is_line_tracing
    (trace,) = field.section.contours["quick_shape"]
    xs, ys = zip(*trace.points)
    assert max(xs) - min(xs) == pytest.approx(50 * scale, abs=1e-6)
    assert max(ys) - min(ys) == pytest.approx(30 * scale, abs=1e-6)
    assert trace.closed
    assert field.current_trace == []


@pytest.mark.parametrize("shape", ["rect", "circle"])
@pytest.mark.parametrize("elapsed", [0.05, 0.5], ids=["quick", "slow"])
def test_shape_click_with_drift_starts_line_tracing(field, shape, elapsed):
    field.setMouseMode(CLOSEDTRACE)
    field.closed_trace_shape = shape
    field.series.setOption("trace_mode", "combo")
    field.tracing_trace = Trace("shape_click", (255, 0, 255))

    _drag(field, QPoint(200, 200), [QPoint(201, 201)], elapsed)

    assert field.is_line_tracing
    assert len(field.current_trace) == 1
    assert "shape_click" not in field.section.contours


@pytest.mark.parametrize("shape", ["rect", "circle"])
@pytest.mark.parametrize("trace_mode", ["combo", "poly"])
def test_shape_polyline_adds_only_press_positions(field, shape, trace_mode):
    field.setMouseMode(CLOSEDTRACE)
    field.closed_trace_shape = shape
    field.series.setOption("trace_mode", trace_mode)
    field.tracing_trace = Trace("shape_line", (255, 0, 255))
    start = QPoint(200, 200)
    _mouse(field, QEvent.MouseButtonPress, start)
    _mouse(field, QEvent.MouseButtonRelease, start)
    _mouse(field, QEvent.MouseButtonPress, QPoint(250, 200))
    _mouse(field, QEvent.MouseMove, QPoint(250, 230))
    _mouse(field, QEvent.MouseButtonRelease, QPoint(260, 240))

    assert field.is_line_tracing
    assert field.current_trace == [(200, 200), (250, 200)]
    assert "shape_line" not in field.section.contours


@pytest.mark.parametrize("elapsed", [0.05, 0.5], ids=["quick", "slow"])
def test_stamp_drag_sets_radius(field, elapsed):
    field.setMouseMode(STAMP)
    field.tracing_trace = Trace("quick_stamp", (255, 0, 255))
    field.tracing_trace.points = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    scale = field.series.window[2] / field.pixmap_dim[0]

    _drag(field, QPoint(200, 200), [QPoint(240, 200)], elapsed)

    (trace,) = field.section.contours["quick_stamp"]
    assert trace.getRadius() == pytest.approx(20 * scale, abs=1e-6)
    center = pixmapPointToField(
        220, 200, field.pixmap_dim, field.series.window, field.section.mag
    )
    assert trace.getCentroid(field.section.tform) == pytest.approx(center)


@pytest.mark.parametrize("elapsed", [0.05, 0.5], ids=["quick", "slow"])
def test_pan_drag_moves_window(field, elapsed):
    field.setMouseMode(PANZOOM)
    x, y, w, h = field.series.window
    scale = w / field.pixmap_dim[0]

    _drag(field, QPoint(200, 200), [QPoint(250, 230)], elapsed)

    assert field.series.window == pytest.approx((x - 50 * scale, y + 30 * scale, w, h))


def _release_drag(field, small_move):
    _mouse(field, QEvent.MouseButtonPress, QPoint(200, 200))
    if small_move:
        _mouse(field, QEvent.MouseMove, QPoint(201, 201))
    _mouse(field, QEvent.MouseButtonRelease, QPoint(250, 230))


@pytest.mark.parametrize("small_move", [False, True], ids=["release-only", "small-move"])
def test_pointer_release_moves_selected_trace(field, small_move):
    field.setMouseMode(POINTER)
    trace = _add_square(field, "move_me", 200, 200, 220, 220)
    field.section.selected_traces = [trace]
    before = list(trace.points)
    scale = field.series.screen_mag

    _release_drag(field, small_move)

    for point, (x, y) in zip(trace.points, before):
        assert point == pytest.approx((x + 50 * scale, y - 30 * scale))
    assert not field.section.temp_hide
    assert not field.is_moving_trace


@pytest.mark.parametrize("small_move", [False, True], ids=["release-only", "small-move"])
def test_pointer_release_selects_rectangle(field, small_move):
    field.setMouseMode(POINTER)
    field.series.setOption("pointer", ["rect", "exc"])
    trace = _add_square(field, "select_me", 210, 210, 220, 220)

    _release_drag(field, small_move)

    assert field.section.selected_traces == [trace]
    assert not field.is_selecting_traces
    assert field.mouse_boundary_timer is None


@pytest.mark.parametrize("small_move", [False, True], ids=["release-only", "small-move"])
def test_stamp_release_sets_radius(field, small_move):
    field.setMouseMode(STAMP)
    field.tracing_trace = Trace("quick_stamp", (255, 0, 255))
    field.tracing_trace.points = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    scale = field.series.window[2] / field.pixmap_dim[0]

    _release_drag(field, small_move)

    (trace,) = field.section.contours["quick_stamp"]
    assert trace.getRadius() == pytest.approx(
        (50**2 + 30**2)**0.5 / 2 * scale, abs=1e-6
    )
    center = pixmapPointToField(
        225, 215, field.pixmap_dim, field.series.window, field.section.mag
    )
    assert trace.getCentroid(field.section.tform) == pytest.approx(center)
    assert not field.is_drawing_rad
    assert field.current_trace == []
