"""Resizing the field keeps unfinished vertices at their image coordinates."""

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from PyReconstruct.modules.datatypes import Trace, Transform
from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    CLOSEDTRACE,
    OPENTRACE,
    SCISSORS,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def field(main_window, local_series_settings, qapp):
    field = main_window.field
    local_series_settings(main_window)
    field.setFixedSize(800, 600)
    qapp.processEvents()
    field.series.window = [0, 0, 800, 600]
    field.section.tform = Transform([1, 0, 0, 0, 1, 0])
    field.series.setOption("trace_mode", "poly")
    field.series.setOption("roll_average", False)
    field.series.setOption("auto_merge", False)
    field.closed_trace_shape = "trace"
    field.generateView()
    return field


def _click(field, x, y, button=Qt.LeftButton):
    QTest.mouseClick(field, button, Qt.NoModifier, QPoint(x, y))


@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("dx,dy,last_point", [
    (0, 0, (300, 300)),
    (200, 0, (300, 300)),
    (-200, 0, (300, 300)),
    (0, 100, (300, 300)),
    (0, -100, (300, 300)),
    (201, 101, (299.5, 300.5)),
    (-201, -101, (299.5, 300.5)),
])
def test_finishing_polygon_after_resize_keeps_image_coordinates(field, closed, dx, dy, last_point):
    field.setMouseMode(CLOSEDTRACE if closed else OPENTRACE)
    field.tracing_trace = Trace("resize_polygon", (255, 0, 255))
    _click(field, 200, 200)
    _click(field, 300, 200)
    assert field.is_line_tracing

    field.setFixedSize(800 + dx, 600 + dy)
    _click(field, 300 + dx // 2, 300 + dy // 2)
    _click(field, 300 + dx // 2, 300 + dy // 2, Qt.RightButton)

    saved = field.section.contours["resize_polygon"].getTraces()
    assert len(saved) == 1
    assert saved[0].closed == closed
    np.testing.assert_allclose(
        sorted(saved[0].points), [(200, 400), last_point, (300, 400)], rtol=0, atol=1e-9
    )


@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("dx,dy", [(200, 0), (-200, 100)])
def test_finishing_scissors_after_resize_keeps_image_coordinates(field, closed, dx, dy):
    trace = Trace("resize_scissors", (255, 0, 255), closed)
    trace.points = [(200, 400), (300, 400), (300, 300), (200, 300)]
    field.section.addTrace(trace, log_event=False)
    field.generateView()
    field.setMouseMode(SCISSORS)
    _click(field, 200, 200)
    assert field.is_scissoring

    field.setFixedSize(800 + dx, 600 + dy)
    _click(field, 200 + dx // 2, 200 + dy // 2, Qt.RightButton)

    saved = field.section.contours["resize_scissors"].getTraces()
    assert len(saved) == 1
    assert saved[0].closed == closed
    np.testing.assert_allclose(
        sorted(saved[0].points), [(200, 300), (200, 400), (300, 300), (300, 400)],
        rtol=0, atol=1e-9,
    )


def test_odd_resize_cycles_keep_pending_vertices_without_rounding(field, qapp):
    field.setMouseMode(OPENTRACE)
    field.tracing_trace = Trace("resize_cycles", (255, 0, 255))
    _click(field, 200, 200)
    _click(field, 300, 300)

    for _ in range(10):
        field.setFixedSize(801, 599)
        qapp.processEvents()
        assert field.current_trace == [(200.5, 199.5), (300.5, 299.5)]
        field.setFixedSize(800, 600)
        qapp.processEvents()
        assert field.current_trace == [(200, 200), (300, 300)]

    _click(field, 300, 300, Qt.RightButton)
    saved = field.section.contours["resize_cycles"].getTraces()
    assert len(saved) == 1
    np.testing.assert_allclose(saved[0].points, [(200, 400), (300, 300)], rtol=0, atol=1e-9)


@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("scissors", [True, False])
def test_finishing_after_odd_resize_keeps_half_pixel_vertices(field, qapp, closed, scissors):
    trace = Trace("resize_halves", (255, 0, 255), closed)
    trace.points = [(200, 400), (300, 400), (300, 300), (200, 300)]
    if scissors:
        field.section.addTrace(trace, log_event=False)
        field.generateView()
        field.setMouseMode(SCISSORS)
        _click(field, 200, 200)
        assert field.is_scissoring
    else:
        field.setMouseMode(CLOSEDTRACE if closed else OPENTRACE)
        field.tracing_trace = trace
        for x, y in [(200, 200), (300, 200), (300, 300), (200, 300)]:
            _click(field, x, y)
        assert field.is_line_tracing

    field.setFixedSize(801, 599)
    qapp.processEvents()
    _click(field, 200, 300, Qt.RightButton)

    saved = field.section.contours["resize_halves"].getTraces()
    assert len(saved) == 1
    assert saved[0].closed == closed
    np.testing.assert_allclose(
        sorted(saved[0].points), [(200, 300), (200, 400), (300, 300), (300, 400)],
        rtol=0, atol=1e-9,
    )
