"""A lasso cut off by a tool change or a pinch ends there, with its timer.

A pointer lasso is a press, moves and a release. `pointerMove` sets
`is_selecting_traces`, collects the points in `current_trace` and starts the
edge-pan timer (`activateMouseBoundaryTimer`), and only `pointerRelease` ends
it. Two interruptions kept that release from ever running:

  * a tool change with the button held (a bare-letter shortcut mid-drag). The
    release goes to the new tool's handler, so the flag, the points and the
    timer stayed. The points were drawn in the new tool's pen, and the timer
    kept panning the view whenever the cursor came near an edge.
  * a pinch. `mouseReleaseEvent` returns while `is_gesturing` is set, so a
    release during the pinch never reached `pointerRelease` either.

The fix drops the lasso without selecting anything, from `setMouseMode` on a
real tool change and from `gestureEvent` when a pinch starts. The pointer
shortcut pressed mid-lasso calls `setMouseMode(POINTER)` with the pointer
already the tool, and that lasso keeps going (pinned below, and in
`test_pointer_move_without_press.py`).

Driven against a real `MainWindow`, a real `FieldWidget` and a real
`TraceLayer`, over a writable copy of the fixture series. The mode changes go
through the real shortcut actions. The pinch is a stand-in event: a
`QPinchGesture`'s state is set only by Qt's gesture manager, so a test cannot
build one in the started state.
"""

import pytest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPointingDevice

from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    CLOSEDTRACE,
    KNIFE,
    PANZOOM,
    POINTER,
)

pytestmark = pytest.mark.gui

# An object on sections 52-56 of the fixture series. 52 is the section the
# window opens on.
OBJ = "d03p14"


class FakeMouseEvent:
    """The accessors the mouse handlers read off a mouse event, all buttons up."""

    def __init__(self, x, y):
        self._x = x
        self._y = y

    def x(self):
        return self._x

    def y(self):
        return self._y

    def buttons(self):
        return Qt.MouseButton.NoButton

    def pointerType(self):
        return QPointingDevice.PointerType.Generic

    def modifiers(self):
        return Qt.NoModifier


class FakePinch:
    """The accessors `gestureEvent` reads off a `QPinchGesture`."""

    def __init__(self, state, x, y, scale):
        self._state = state
        self._center = QPointF(x, y)
        self._scale = scale

    def state(self):
        return self._state

    def centerPoint(self):
        return self._center

    def totalScaleFactor(self):
        return self._scale


class FakeGestureEvent:
    def __init__(self, pinch):
        self._pinch = pinch

    def gesture(self, kind):
        assert kind == Qt.PinchGesture
        return self._pinch


@pytest.fixture
def field_notices(monkeypatch):
    """Record what `notify` would have shown from the field's mouse module.

    Offscreen, `notify` falls through to a console branch ending in `input()`,
    which raises under pytest's capture.
    """
    from PyReconstruct.modules.gui.main import field_widget_5_mouse

    notices = []
    monkeypatch.setattr(
        field_widget_5_mouse,
        "notify",
        lambda message, *a, **kw: notices.append(message),
    )
    return notices


def _visible_trace(field):
    field.generateView(update=False)
    for trace in field.section_layer.traces_in_view:
        if trace.name == OBJ:
            return trace
    pytest.fail(f"no trace of {OBJ} is in view on section {field.section.n}")


def _start_lasso(window):
    """Press beside a trace and drag a lasso all the way around it.

    Returns the trace and the edge-pan timer the lasso started.
    """
    window.usepointer_act.trigger()
    field = window.field
    assert field.mouse_mode == POINTER

    trace = _visible_trace(field)
    field.section.selected_traces.clear()

    xs, ys = zip(*field.section_layer.traceToPix(trace))
    margin = 15
    corners = [
        (min(xs) - margin, min(ys) - margin),
        (max(xs) + margin, min(ys) - margin),
        (max(xs) + margin, max(ys) + margin),
        (min(xs) - margin, max(ys) + margin),
    ]

    field.lclick = True
    field.single_click = True
    field.pointerPress(FakeMouseEvent(*corners[0]))
    # past the single-click window, which is what makes the moves a lasso
    field.single_click = False
    field.click_time = 0
    for x, y in corners:
        field.pointerMove(FakeMouseEvent(x, y))

    # true before the fix as well, so a test fails on its own subject
    assert field.is_selecting_traces is True
    timer = field.mouse_boundary_timer
    assert timer is not None and timer.isActive()
    # a release now would select the trace, so "nothing selected" below means
    # the lasso was dropped, not that it missed
    assert trace in field.section_layer.getTraces(field.current_trace)

    return trace, timer


def _assert_lasso_dropped(field, timer):
    assert field.is_selecting_traces is False
    assert field.current_trace == []
    assert field.mouse_boundary_timer is None
    assert not timer.isActive()
    assert field.section.selected_traces == []


@pytest.mark.parametrize(
    "action, mode",
    [
        ("useknife_act", KNIFE),
        ("usectrace_act", CLOSEDTRACE),
        ("usepanzoom_act", PANZOOM),
    ],
)
def test_changing_the_tool_mid_lasso_drops_it_and_stops_the_timer(
    main_window, main_window_dialogs, field_notices, action, mode
):
    field = main_window.field
    _trace, timer = _start_lasso(main_window)

    getattr(main_window, action).trigger()

    assert field.mouse_mode == mode
    _assert_lasso_dropped(field, timer)
    assert field_notices == []


def test_pointer_shortcut_mid_lasso_keeps_it_going(
    main_window, main_window_dialogs, field_notices
):
    field = main_window.field
    trace, timer = _start_lasso(main_window)
    points = list(field.current_trace)

    main_window.usepointer_act.trigger()

    assert field.mouse_mode == POINTER
    assert field.is_selecting_traces is True
    assert field.current_trace == points
    assert field.mouse_boundary_timer is timer and timer.isActive()

    # and its release still selects what it went around
    field.pointerMove(FakeMouseEvent(*points[0]))
    field.pointerRelease(FakeMouseEvent(*points[0]))

    assert trace in field.section.selected_traces
    assert field.mouse_boundary_timer is None
    assert not timer.isActive()
    assert field_notices == []


@pytest.mark.parametrize(
    "release_during_pinch", [True, False], ids=["during", "after"]
)
def test_a_pinch_mid_lasso_drops_it_and_stops_the_timer(
    main_window, main_window_dialogs, field_notices, release_during_pinch
):
    field = main_window.field
    _trace, timer = _start_lasso(main_window)
    x, y = field.current_trace[-1]
    started = Qt.GestureState.GestureStarted
    updated = Qt.GestureState.GestureUpdated
    finished = Qt.GestureState.GestureFinished

    field.gestureEvent(FakeGestureEvent(FakePinch(started, 200, 150, 1.0)))

    assert field.is_gesturing is True
    _assert_lasso_dropped(field, timer)

    field.gestureEvent(FakeGestureEvent(FakePinch(updated, 210, 150, 1.5)))

    if release_during_pinch:
        # ignored while gesturing, as before
        field.mouseReleaseEvent(FakeMouseEvent(x, y))
        assert field.is_gesturing is True

    field.gestureEvent(FakeGestureEvent(FakePinch(finished, 210, 150, 1.5)))
    assert field.is_gesturing is False

    if not release_during_pinch:
        field.mouseReleaseEvent(FakeMouseEvent(x, y))

    _assert_lasso_dropped(field, timer)
    assert field_notices == []
