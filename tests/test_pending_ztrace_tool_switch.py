"""A z-trace left pending is a line trace only while the Ztool is the tool.

A Ztool click starts a z-trace and sets both `is_z_tracing` and
`is_line_tracing`. The z-trace stays open across tool changes, so a user can
page sections or touch up a trace and then come back to it. `setMouseMode`
kept `is_line_tracing` set under the new tool, though: with Closed Trace in
Scribble, the field stayed in line-tracing mode for a tool that draws no
lines, and the next press added a point to the z-trace's line instead of
starting a stroke. The same held for Poly, Open Trace and the pointer.

`endPendingEvents` skipped every line while a z-trace waited, so a polyline
started under another tool was not finished on a tool change either.

Now the flag follows the tool: off under any other tool, on again when the
Ztool comes back, with the z-trace's points taken from `current_ztrace`.

Driven against a real `MainWindow` and `FieldWidget` over a writable copy of
the fixture series, through the mouse palette and the field's own mouse
events.
"""

import pytest

from PySide6.QtCore import Qt

from PyReconstruct.modules.datatypes import Trace

from test_lasso_ends_on_tool_change_and_pinch import HELD, UP, FakeMouseEvent

pytestmark = pytest.mark.gui

NAME = "pending"
ZPOINT = (150, 150)
DRAG = [(200, 200), (240, 200), (240, 240), (200, 240)]


@pytest.fixture
def main_window(main_window, local_series_settings):
    """The shared fixture window, its option writes kept to this test."""
    local_series_settings(main_window)
    return main_window


def _click(field, x, y, button=HELD):
    field.mousePressEvent(FakeMouseEvent(x, y, button))
    field.mouseReleaseEvent(FakeMouseEvent(x, y, UP))


def _pending_ztrace(window, trace_mode):
    """Leave a one-point z-trace pending; return the field and its points."""
    field = window.field
    field.series.setOption("trace_mode", trace_mode)
    field.series.setOption("roll_average", False)
    field.series.setOption("auto_merge", False)
    field.tracing_trace = Trace(NAME, (255, 0, 255))
    window.mouse_palette.activateModeButton("Ztool")
    _click(field, *ZPOINT)
    assert field.is_z_tracing and field.is_line_tracing
    return field, list(field.current_ztrace)


def _drop_line(field):
    field.is_line_tracing = False
    field.is_z_tracing = False
    field.current_trace = []
    field.current_ztrace = []
    field.deactivateMouseBoundaryTimer()


def _added(field):
    return field.section.contours.get(NAME, [])


@pytest.mark.parametrize(
    "button, trace_mode",
    [
        ("Closed Trace", "scribble"),
        ("Closed Trace", "poly"),
        ("Closed Trace", "combo"),
        ("Open Trace", "scribble"),
        ("Open Trace", "poly"),
        ("Pointer", "combo"),
    ],
)
def test_other_tool_has_no_line_under_way(main_window, button, trace_mode):
    field, points = _pending_ztrace(main_window, trace_mode)
    main_window.mouse_palette.activateModeButton(button)
    try:
        assert not field.is_line_tracing
        assert field.mouse_boundary_timer is None
        assert field.is_z_tracing
        assert field.current_ztrace == points
    finally:
        _drop_line(field)


def test_scribble_stroke_is_its_own_trace(main_window):
    field, points = _pending_ztrace(main_window, "scribble")
    main_window.mouse_palette.activateModeButton("Closed Trace")
    field.mousePressEvent(FakeMouseEvent(*DRAG[0], HELD))
    for x, y in DRAG[1:]:
        field.mouseMoveEvent(FakeMouseEvent(x, y, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(*DRAG[-1], UP))
    try:
        assert not field.is_line_tracing
        assert len(_added(field)) == 1
        assert field.current_ztrace == points
    finally:
        _drop_line(field)


def test_poly_click_starts_a_new_line(main_window):
    field, points = _pending_ztrace(main_window, "poly")
    main_window.mouse_palette.activateModeButton("Closed Trace")
    _click(field, 300, 300)
    try:
        assert field.is_line_tracing
        assert field.current_trace == [(300, 300)]
        assert field.current_ztrace == points
    finally:
        _drop_line(field)


def test_poly_line_ends_on_tool_change(main_window):
    field, points = _pending_ztrace(main_window, "poly")
    main_window.mouse_palette.activateModeButton("Closed Trace")
    for x, y in DRAG:
        _click(field, x, y)
    main_window.mouse_palette.activateModeButton("Pointer")
    try:
        assert not field.is_line_tracing
        assert len(_added(field)) == 1
        assert field.is_z_tracing
        assert field.current_ztrace == points
    finally:
        _drop_line(field)


@pytest.mark.parametrize("button", ["Closed Trace", "Open Trace", "Pointer"])
def test_ztool_resumes_the_pending_ztrace(main_window, button):
    field, points = _pending_ztrace(main_window, "poly")
    main_window.mouse_palette.activateModeButton(button)
    if button != "Pointer":
        _click(field, 300, 300)
    main_window.mouse_palette.activateModeButton("Ztool")
    try:
        assert field.is_line_tracing
        assert field.mouse_boundary_timer is not None
        assert field.current_trace == [(x, y) for x, y, _ in points]
        _click(field, 170, 170)
        points = list(field.current_ztrace)
        _click(field, 170, 170, Qt.MouseButton.RightButton)
        assert not field.is_z_tracing and not field.is_line_tracing
        assert field.series.ztraces[NAME].points == points
    finally:
        _drop_line(field)
