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
real tool change and from `gestureEvent` when a pinch starts, and the press
goes with it. The button is usually still down, and the tool that inherits it
must not act on a press it never saw: a rectangle trace raised `IndexError` on
the emptied `current_trace`, a pencil or stamp drew, the knife cut, Host
started a link, Pan/Zoom panned, and the pointer, after the pinch or a switch
back, started a second lasso and timer. The pointer shortcut pressed mid-lasso
calls `setMouseMode(POINTER)` with the pointer already the tool, and that
lasso keeps going (pinned below, and in `test_pointer_move_without_press.py`).

Driven against a real `MainWindow`, a real `FieldWidget` and a real
`TraceLayer`, over a writable copy of the fixture series. The mode changes go
through the real shortcut actions, and the moves and release after them go
through the field's own `mouseMoveEvent` and `mouseReleaseEvent`, the way Qt
delivers them. The pinch is a stand-in event: a `QPinchGesture`'s state is set
only by Qt's gesture manager, so a test cannot build one in the started state.
"""

import pytest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPointingDevice

from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    CLOSEDTRACE,
    FLAG,
    GRID,
    HOST,
    KNIFE,
    OPENTRACE,
    PANZOOM,
    POINTER,
    SCISSORS,
    STAMP,
)

pytestmark = pytest.mark.gui

# An object on sections 52-56 of the fixture series. 52 is the section the
# window opens on.
OBJ = "d03p14"

HELD = Qt.MouseButton.LeftButton
UP = Qt.MouseButton.NoButton


class FakeMouseEvent:
    """The accessors the mouse handlers read off a mouse event.

    `buttons` is what is down once the event has happened: the left button
    for a move while it is held, nothing for the release.
    """

    def __init__(self, x, y, buttons=UP):
        self._x = x
        self._y = y
        self._buttons = buttons

    def x(self):
        return self._x

    def y(self):
        return self._y

    def buttons(self):
        return self._buttons

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
    """Record what `notify` would have shown from the field widget modules.

    Both copies: the mouse module and the trace module (knife cuts, lock
    refusals) each bind `notify` in their own namespace. Offscreen, `notify`
    falls through to a console branch ending in `input()`, which raises under
    pytest's capture.
    """
    from PyReconstruct.modules.gui.main import (
        field_widget_2_trace,
        field_widget_5_mouse,
    )

    notices = []
    for module in (field_widget_2_trace, field_widget_5_mouse):
        monkeypatch.setattr(
            module, "notify", lambda message, *a, **kw: notices.append(message)
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

    Drives the pointer handlers directly, so the test can put the press past
    the single-click window that separates a click from a lasso. Returns the
    trace and the edge-pan timer the lasso started.
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
    field.pointerPress(FakeMouseEvent(*corners[0], HELD))
    # past the single-click window, which is what makes the moves a lasso
    field.single_click = False
    field.click_time = 0
    for x, y in corners:
        field.pointerMove(FakeMouseEvent(x, y, HELD))

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


def _hold_then_release(field, trace):
    """Keep the button down and move onto `trace`, then let go there.

    Through the field's own event handlers, the way Qt delivers them. Returns
    `current_trace` as it stood after the moves, before the release.
    """
    x, y = field.section_layer.traceToPix(trace)[0]
    field.mouseMoveEvent(FakeMouseEvent(x - 20, y - 10, HELD))
    field.mouseMoveEvent(FakeMouseEvent(x, y, HELD))
    after_moves = list(field.current_trace)
    field.mouseReleaseEvent(FakeMouseEvent(x, y))
    return after_moves


@pytest.mark.parametrize(
    "actions, mode, shape",
    [
        (("useknife_act",), KNIFE, "trace"),
        (("usescissors_act",), SCISSORS, "trace"),
        (("usectrace_act",), CLOSEDTRACE, "trace"),
        (("usectrace_act",), CLOSEDTRACE, "rect"),
        (("usectrace_act",), CLOSEDTRACE, "circle"),
        (("useotrace_act",), OPENTRACE, "trace"),
        (("usestamp_act",), STAMP, "trace"),
        (("usegrid_act",), GRID, "trace"),
        (("useflag_act",), FLAG, "trace"),
        (("usepanzoom_act",), PANZOOM, "trace"),
        (("usehost_act",), HOST, "trace"),
        (("useknife_act", "usepointer_act"), POINTER, "trace"),
    ],
    ids=[
        "knife",
        "scissors",
        "closed-trace",
        "closed-rectangle",
        "closed-ellipse",
        "open-trace",
        "stamp",
        "grid",
        "flag",
        "panzoom",
        "host",
        "knife-then-pointer",
    ],
)
def test_changing_the_tool_mid_lasso_drops_it_and_its_press(
    main_window, main_window_dialogs, field_notices, actions, mode, shape
):
    field = main_window.field
    field.closed_trace_shape = shape
    trace, timer = _start_lasso(main_window)
    points_before = [tuple(p) for p in trace.points]
    count_before = len(field.section.tracesAsList())
    window_before = list(field.series.window)

    for action in actions:
        getattr(main_window, action).trigger()

    assert field.mouse_mode == mode
    assert field.closed_trace_shape == shape
    _assert_lasso_dropped(field, timer)

    # the button is still down; no tool acts on the press the lasso was using
    after_moves = _hold_then_release(field, trace)

    assert after_moves == []
    _assert_lasso_dropped(field, timer)
    assert len(field.section.tracesAsList()) == count_before
    assert [tuple(p) for p in trace.points] == points_before
    assert list(field.series.window) == window_before
    assert field.hosted_trace is None
    assert main_window_dialogs.dialogs == []
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
    field.mouseMoveEvent(FakeMouseEvent(*points[0], HELD))
    field.mouseReleaseEvent(FakeMouseEvent(*points[0]))

    assert trace in field.section.selected_traces
    assert field.mouse_boundary_timer is None
    assert not timer.isActive()
    assert field_notices == []


@pytest.mark.parametrize("button", ["released-during", "held-after"])
def test_a_pinch_mid_lasso_drops_it_and_its_press(
    main_window, main_window_dialogs, field_notices, button
):
    field = main_window.field
    trace, timer = _start_lasso(main_window)
    x, y = field.current_trace[-1]
    started = Qt.GestureState.GestureStarted
    updated = Qt.GestureState.GestureUpdated
    finished = Qt.GestureState.GestureFinished

    field.gestureEvent(FakeGestureEvent(FakePinch(started, 200, 150, 1.0)))

    assert field.is_gesturing is True
    _assert_lasso_dropped(field, timer)

    field.gestureEvent(FakeGestureEvent(FakePinch(updated, 210, 150, 1.5)))

    if button == "released-during":
        # ignored while gesturing, as before
        field.mouseReleaseEvent(FakeMouseEvent(x, y))
        assert field.is_gesturing is True

    field.gestureEvent(FakeGestureEvent(FakePinch(finished, 210, 150, 1.5)))
    assert field.is_gesturing is False

    if button == "held-after":
        # the button is still down after the pinch: moving with it must not
        # start a second lasso and timer, and letting go must not select
        after_moves = _hold_then_release(field, trace)
        assert after_moves == []

    _assert_lasso_dropped(field, timer)
    assert field_notices == []
