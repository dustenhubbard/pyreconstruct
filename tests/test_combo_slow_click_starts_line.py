"""In combo trace mode, a press that barely moves is a click, however long.

Combo mode reads a click as the start of a point-by-point trace and a drag as
a scribble. A click used to count only if it lasted at most `max_click_time`
(0.15 s) or had no move event at all. A slower click with a pixel or two of
drift, from a trackpad or a hand resting on the mouse, became a two-point
scribble and drew nothing. Now a press whose pointer stays within
`click_tolerance` pixels of the press point starts point-by-point tracing at
any length.

The rule applies to one release only: the one that ends the left press the
trace tool started as a new trace, in the same tool, with nothing in between.
A tool change, a trace-palette pick, a pinch, a section change or an undo
while the button is held ends that (`endPendingEvents`), and the release is
handled as it was before. So is the release of a press another tool started,
of a click on a line under way, and of a press the field menu took.
"""

import pytest
from PySide6.QtCore import Qt

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    CLOSEDTRACE,
    OPENTRACE,
)
from test_lasso_ends_on_tool_change_and_pinch import (
    HELD,
    UP,
    FakeGestureEvent,
    FakeMouseEvent,
    FakePinch,
    field_menu,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.gui

X, Y = 200, 200

STILL = []
DRIFT = [(1, 0)]
EDGE = [(4, 0), (0, -4)]
OVER = [(5, 0)]
EXCURSION = [(20, 20), (0, 1)]
DRAG = [(10, 0), (20, 5), (30, 10)]


def _field(window, mode, trace_mode):
    field = window.field
    field.series.setOption("trace_mode", trace_mode)
    field.series.setOption("roll_average", False)
    field.series.setOption("auto_merge", False)
    field.setMouseMode(mode)
    field.tracing_trace = Trace("slow_click", (255, 0, 255))
    assert not field.is_line_tracing
    return field


def _press(field, path=STILL):
    """Press at (X, Y) and move along `path` (offsets); return the last point."""
    field.mousePressEvent(FakeMouseEvent(X, Y, HELD))
    dx, dy = 0, 0
    for dx, dy in path:
        field.mouseMoveEvent(FakeMouseEvent(X + dx, Y + dy, HELD))
    return X + dx, Y + dy


def _release(field, point, slow=True):
    """Release at `point`; `slow` puts the press past the single-click window."""
    if slow:
        field.click_time = 0
    field.mouseReleaseEvent(FakeMouseEvent(*point, UP))


def _drop_line(field):
    field.is_line_tracing = False
    field.is_z_tracing = False
    field.current_trace = []
    field.current_ztrace = []
    field.deactivateMouseBoundaryTimer()


def _added(field, name="slow_click"):
    return field.section.contours.get(name, [])


def _start_line(field):
    """Two quick clicks, so a line is under way."""
    for x, y in [(150, 150), (170, 150)]:
        field.mousePressEvent(FakeMouseEvent(x, y, HELD))
        field.mouseReleaseEvent(FakeMouseEvent(x, y, UP))
    assert field.is_line_tracing
    assert field.current_trace == [(150, 150), (170, 150)]


def _pinch(field):
    state = Qt.GestureState
    field.gestureEvent(FakeGestureEvent(FakePinch(state.GestureStarted, 200, 150, 1.0)))
    field.gestureEvent(FakeGestureEvent(FakePinch(state.GestureUpdated, 210, 150, 1.5)))
    field.gestureEvent(FakeGestureEvent(FakePinch(state.GestureFinished, 210, 150, 1.5)))


@pytest.mark.parametrize("mode", [CLOSEDTRACE, OPENTRACE])
@pytest.mark.parametrize("path", [DRIFT, EDGE], ids=["drift", "edge"])
def test_slow_still_press_starts_line_tracing(main_window, mode, path):
    field = _field(main_window, mode, "combo")
    _release(field, _press(field, path))
    try:
        assert field.is_line_tracing
        assert field.current_trace == [(X, Y)]
        assert _added(field) == []
    finally:
        _drop_line(field)


def test_fast_click_with_drift_still_starts_line_tracing(main_window):
    field = _field(main_window, CLOSEDTRACE, "combo")
    _release(field, _press(field, DRAG), slow=False)
    try:
        assert field.is_line_tracing
        assert field.current_trace == [(X, Y)]
    finally:
        _drop_line(field)


@pytest.mark.parametrize(
    "path", [OVER, EXCURSION, DRAG], ids=["over", "excursion", "drag"]
)
def test_slow_drag_past_tolerance_scribbles(main_window, path):
    """A drag past the tolerance scribbles, even one that comes back."""
    field = _field(main_window, OPENTRACE, "combo")
    _release(field, _press(field, path))
    assert not field.is_line_tracing
    assert len(_added(field)) == 1
    assert len(_added(field)[0].points) >= 2


def test_scribble_mode_never_starts_line_tracing(main_window):
    field = _field(main_window, CLOSEDTRACE, "scribble")
    _release(field, _press(field, DRIFT))
    assert not field.is_line_tracing
    assert len(_added(field)) == 1


def test_poly_mode_starts_line_tracing_on_press(main_window):
    field = _field(main_window, CLOSEDTRACE, "poly")
    field.mousePressEvent(FakeMouseEvent(X, Y, HELD))
    try:
        assert field.is_line_tracing
    finally:
        field.mouseReleaseEvent(FakeMouseEvent(X, Y, UP))
        _drop_line(field)


def test_slow_click_on_a_line_under_way_adds_its_point(main_window):
    field = _field(main_window, CLOSEDTRACE, "combo")
    _start_line(field)
    _release(field, _press(field, DRIFT))
    try:
        assert field.is_line_tracing
        assert field.current_trace == [(150, 150), (170, 150), (X, Y)]
        assert _added(field) == []
    finally:
        _drop_line(field)


@pytest.mark.parametrize(
    "interrupt",
    ["other_trace_tool", "same_tool_again", "palette_pick", "pinch"],
)
def test_interrupted_slow_press_is_released_as_before(main_window, interrupt):
    """Anything between press and release puts the slow-click rule aside.

    The release is then handled as before this rule: a slow press with drift
    is a scribble, and in another tool it is that tool's to finish.
    """
    field = _field(main_window, CLOSEDTRACE, "combo")
    point = _press(field, DRIFT)
    if interrupt == "other_trace_tool":
        main_window.useotrace_act.trigger()
    elif interrupt == "same_tool_again":
        main_window.usectrace_act.trigger()
    elif interrupt == "palette_pick":
        main_window.mouse_palette.activatePaletteButton(1)
    else:
        _pinch(field)
    _release(field, point)
    try:
        assert not field.is_line_tracing
    finally:
        _drop_line(field)


def test_release_after_field_menu_adds_nothing(main_window, field_menu):  # noqa: F811
    """A right press opens the field menu; its slow release is no trace click."""
    field = _field(main_window, CLOSEDTRACE, "combo")
    field.current_trace = []
    field.mousePressEvent(FakeMouseEvent(X, Y, Qt.MouseButton.RightButton))
    field.mouseMoveEvent(FakeMouseEvent(X + 1, Y, Qt.MouseButton.RightButton))
    _release(field, (X + 1, Y))
    assert field_menu
    assert not field.is_line_tracing
    assert field.current_trace == []
    assert _added(field) == []


def test_slow_pointer_press_released_in_a_trace_tool_adds_nothing(main_window):
    """A press the pointer started is not a trace click after a tool change."""
    field = _field(main_window, CLOSEDTRACE, "combo")
    main_window.usepointer_act.trigger()
    field.current_trace = []
    point = _press(field, DRIFT)
    assert field.current_trace == [(X + 1, Y)]
    main_window.usectrace_act.trigger()
    _release(field, point)
    try:
        assert not field.is_line_tracing
        assert _added(field) == []
    finally:
        _drop_line(field)


def test_interrupted_z_trace_is_kept(main_window):
    """A z-trace under way survives a press made in a trace tool meanwhile."""
    field = _field(main_window, CLOSEDTRACE, "combo")
    main_window.mouse_palette.activateModeButton("Ztool")
    for x, y in [(150, 150), (170, 170)]:
        field.mousePressEvent(FakeMouseEvent(x, y, HELD))
        field.mouseReleaseEvent(FakeMouseEvent(x, y, UP))
    points = list(field.current_ztrace)
    main_window.usectrace_act.trigger()
    point = _press(field, DRIFT)
    main_window.mouse_palette.activateModeButton("Ztool")
    _release(field, point)
    field.mousePressEvent(FakeMouseEvent(*point, Qt.MouseButton.RightButton))
    field.mouseReleaseEvent(FakeMouseEvent(*point, UP))
    try:
        assert "slow_click" in field.series.ztraces
        assert field.series.ztraces["slow_click"].points == points
    finally:
        _drop_line(field)


def test_slow_press_after_a_release_lost_in_a_pinch_starts_line_tracing(
    main_window,
):
    """The next press after a pinch stands on its own."""
    field = _field(main_window, CLOSEDTRACE, "combo")
    _press(field, DRIFT)
    state = Qt.GestureState
    field.gestureEvent(FakeGestureEvent(FakePinch(state.GestureStarted, 200, 150, 1.0)))
    field.mouseReleaseEvent(FakeMouseEvent(X + 1, Y, UP))
    field.gestureEvent(FakeGestureEvent(FakePinch(state.GestureFinished, 210, 150, 1.5)))
    field.mouseMoveEvent(FakeMouseEvent(X + 1, Y, UP))
    _release(field, _press(field, DRIFT))
    try:
        assert field.is_line_tracing
        assert field.current_trace == [(X, Y)]
    finally:
        _drop_line(field)

