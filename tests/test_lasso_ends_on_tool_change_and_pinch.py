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

The dropped press stays dropped until every button is up (`dropPress`).
`mousePressEvent` reads the held buttons afresh, so a second button pressed
while the first is still down used to hand it back: the branch that ignores a
middle press combined with another kept the left one, and a rectangle trace
indexed the emptied `current_trace` after all. A right press mid-lasso, from a
second button or a tablet's barrel button, still opens the context menu, and
the menu ends the lasso as a tool change does. Before, the lasso kept its
edge-pan timer through the menu. The release after the menu finishes nothing,
and the next lasso starts from its own press, not from the old lasso's points.

Driven against a real `MainWindow`, a real `FieldWidget` and a real
`TraceLayer`, over a writable copy of the fixture series. The mode changes go
through the real shortcut actions, and every press, move and release goes
through the field's own `mousePressEvent`, `mouseMoveEvent` and
`mouseReleaseEvent`, reporting the buttons held the way Qt does. The pinch is a
stand-in event: a `QPinchGesture`'s state is set only by Qt's gesture manager,
so a test cannot build one in the started state.
"""

import pytest

from PySide6.QtCore import QPoint, QPointF, Qt
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

# A second button pressed while the first is held. The side button is in for
# what `get_clicked` does not read: it reports left, middle and right only, so
# a press of any other button with the left one down reads as a left press.
SECONDARY = {
    "middle": Qt.MouseButton.MiddleButton,
    "right": Qt.MouseButton.RightButton,
    "side": Qt.MouseButton.XButton1,
}


class FakeMouseEvent:
    """The accessors the mouse handlers read off a mouse event.

    `buttons` is what is down once the event has happened, the way Qt reports
    it: for a press, the button pressed and any already held; for a move, what
    is held; for a release, what is still held, so nothing for the last one.
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

    def globalPos(self):
        return QPoint(self._x, self._y)

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


@pytest.fixture
def field_menu(main_window, monkeypatch):
    """Record the field's context menu instead of showing it.

    `exec` spins a modal loop offscreen with no one to dismiss it. Returning at
    once is the menu dismissed without a choice.
    """
    shown = []
    monkeypatch.setattr(
        main_window.field_menu, "exec", lambda *a, **kw: shown.append(a)
    )
    return shown


def _visible_trace(field, name=OBJ):
    field.generateView(update=False)
    for trace in field.section_layer.traces_in_view:
        if trace.name == name:
            return trace
    pytest.fail(f"no trace of {name} is in view on section {field.section.n}")


def _add_square(field, name, x0, y0, x1, y1):
    """Put a closed square trace at these pixel corners, and return it."""
    from PyReconstruct.modules.calc import pixmapPointToField
    from PyReconstruct.modules.datatypes.trace import Trace

    square = Trace(name, (255, 0, 0), closed=True)
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        point = pixmapPointToField(
            x, y, field.pixmap_dim, field.series.window, field.section.mag
        )
        square.add(field.section.tform.map(*point, inverted=True))
    field.section.addTrace(square, log_event=False)
    return _visible_trace(field, name)


def _box_around(field, trace, margin=15):
    xs, ys = zip(*field.section_layer.traceToPix(trace))
    return [
        (min(xs) - margin, min(ys) - margin),
        (max(xs) + margin, min(ys) - margin),
        (max(xs) + margin, max(ys) + margin),
        (min(xs) - margin, max(ys) + margin),
    ]


def _drag_lasso(field, corners):
    """Press at the first corner and drag through them all, button still down.

    Through the field's own handlers. The press is put past the single-click
    window, which is what makes the moves a lasso rather than a click.
    """
    assert field.mouse_mode == POINTER
    field.mousePressEvent(FakeMouseEvent(*corners[0], HELD))
    field.click_time = 0
    for x, y in corners:
        field.mouseMoveEvent(FakeMouseEvent(x, y, HELD))


def _start_lasso(window):
    """Press beside a trace and drag a lasso all the way around it.

    Returns the trace and the edge-pan timer the lasso started.
    """
    window.usepointer_act.trigger()
    field = window.field
    assert field.mouse_mode == POINTER

    trace = _visible_trace(field)
    field.section.selected_traces.clear()

    _drag_lasso(field, _box_around(field, trace))

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


def _pinch(field):
    started = Qt.GestureState.GestureStarted
    updated = Qt.GestureState.GestureUpdated
    finished = Qt.GestureState.GestureFinished
    field.gestureEvent(FakeGestureEvent(FakePinch(started, 200, 150, 1.0)))
    field.gestureEvent(FakeGestureEvent(FakePinch(updated, 210, 150, 1.5)))
    field.gestureEvent(FakeGestureEvent(FakePinch(finished, 210, 150, 1.5)))


@pytest.mark.parametrize("secondary", list(SECONDARY))
@pytest.mark.parametrize(
    "interruption, shape",
    [
        ("usectrace_act", "rect"),
        ("usectrace_act", "trace"),
        ("useknife_act", "trace"),
        ("usestamp_act", "trace"),
        ("usepanzoom_act", "trace"),
        ("usehost_act", "trace"),
        ("pinch", "trace"),
    ],
    ids=[
        "closed-rectangle",
        "closed-trace",
        "knife",
        "stamp",
        "panzoom",
        "host",
        "pinch",
    ],
)
def test_a_second_button_does_not_hand_the_dropped_press_back(
    main_window,
    main_window_dialogs,
    field_notices,
    field_menu,
    interruption,
    shape,
    secondary,
):
    """The press a tool change or a pinch dropped stays dropped while held.

    A second press used to hand the left button back to the new tool: a
    rectangle trace raised `IndexError` on the emptied `current_trace`,
    Pan/Zoom raised `AttributeError` or moved the view, the pencil, the knife
    and the stamp drew, Host started a link, and the pointer started another
    lasso. A right press opened the menu. It is ignored now as well, so no
    menu opens under a press the field has let go of.
    """
    field = main_window.field
    field.closed_trace_shape = shape
    trace, timer = _start_lasso(main_window)
    points_before = [tuple(p) for p in trace.points]
    count_before = len(field.section.tracesAsList())

    if interruption == "pinch":
        _pinch(field)
    else:
        getattr(main_window, interruption).trigger()
    _assert_lasso_dropped(field, timer)
    # after the interruption: the pinch moves the view itself
    window_before = list(field.series.window)

    # the first button is still down; press another with it, move, and let go
    # of them one at a time
    x, y = field.section_layer.traceToPix(trace)[0]
    both = HELD | SECONDARY[secondary]
    field.mousePressEvent(FakeMouseEvent(x - 20, y - 10, both))
    field.mouseMoveEvent(FakeMouseEvent(x - 10, y - 5, both))
    field.mouseMoveEvent(FakeMouseEvent(x, y, both))
    after_moves = list(field.current_trace)
    field.mouseReleaseEvent(FakeMouseEvent(x, y, HELD))
    field.mouseMoveEvent(FakeMouseEvent(x + 5, y + 5, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(x + 5, y + 5))

    assert after_moves == []
    _assert_lasso_dropped(field, timer)
    assert len(field.section.tracesAsList()) == count_before
    assert [tuple(p) for p in trace.points] == points_before
    assert list(field.series.window) == window_before
    assert field.hosted_trace is None
    assert field_menu == []
    assert main_window_dialogs.dialogs == []
    assert field_notices == []

    # every button is up, so the press is over: the next one is a fresh press
    main_window.usepointer_act.trigger()
    corners = _box_around(field, trace)
    _drag_lasso(field, corners)
    field.mouseReleaseEvent(FakeMouseEvent(*corners[-1]))
    assert trace in field.section.selected_traces


def test_a_lost_release_does_not_cost_the_next_press(
    main_window, main_window_dialogs, field_notices, field_menu
):
    """A press of one button alone is a fresh press.

    The dropped button cannot still be down, whether or not its release
    reached the field, so the drop does not swallow it.
    """
    field = main_window.field
    trace, timer = _start_lasso(main_window)
    main_window.useknife_act.trigger()
    main_window.usepointer_act.trigger()
    _assert_lasso_dropped(field, timer)

    # no release: the next thing the field hears is a fresh press
    corners = _box_around(field, trace)
    _drag_lasso(field, corners)
    field.mouseReleaseEvent(FakeMouseEvent(*corners[-1]))

    assert trace in field.section.selected_traces
    assert field_menu == []
    assert field_notices == []


@pytest.mark.parametrize("barrel", ["on its own", "with the pen still down"])
def test_a_barrel_press_mid_lasso_ends_it_before_the_menu(
    main_window, main_window_dialogs, field_notices, field_menu, barrel
):
    """The right press still opens the menu; the lasso under it ends.

    Both shapes a tablet's barrel press arrives in: with the tip, or, when the
    tablet stops reporting the tip for one event, on its own. The second leaves
    nothing in the event to say a lasso is under way.
    """
    main_window.usepointer_act.trigger()
    field = main_window.field
    # placed where the two lassos' points, run together, also go around it
    _add_square(field, "old-region", 75, 50, 90, 65)
    _add_square(field, "new-region", 150, 150, 170, 170)
    field.section.selected_traces.clear()

    _drag_lasso(field, [(40, 40), (100, 40), (100, 100), (40, 100)])
    timer = field.mouse_boundary_timer
    assert field.is_selecting_traces is True
    assert timer is not None and timer.isActive()

    if barrel == "on its own":
        field.mousePressEvent(FakeMouseEvent(60, 60, Qt.MouseButton.RightButton))
    else:
        field.mousePressEvent(
            FakeMouseEvent(60, 60, HELD | Qt.MouseButton.RightButton)
        )
    assert len(field_menu) == 1
    after_menu = (
        field.is_selecting_traces,
        field.mouse_boundary_timer,
        timer.isActive(),
        list(field.current_trace),
    )
    if barrel == "with the pen still down":
        field.mouseReleaseEvent(FakeMouseEvent(60, 60, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(60, 60))

    # a fresh lasso somewhere else selects what it goes around, and only that
    corners = [(140, 140), (180, 140), (180, 180), (140, 180)]
    _drag_lasso(field, corners)
    lasso = list(field.current_trace)
    field.mouseReleaseEvent(FakeMouseEvent(*corners[-1]))

    assert [t.name for t in field.section.selected_traces] == ["new-region"]
    assert lasso == corners
    assert after_menu == (False, None, False, [])
    assert field_notices == []


def test_the_release_after_the_menu_still_clears_the_pointers_points(
    main_window, main_window_dialogs, field_notices, field_menu
):
    """A barrel press before the lasso starts, while it could still be a click.

    The pointer keeps those points in `current_trace` too, and `pointerRelease`
    is what clears them. Only a dropped press's release is held back from the
    tools, so the release after this menu still reaches it.
    """
    main_window.usepointer_act.trigger()
    field = main_window.field
    # a single-click window that lasts, however slow the run
    field.max_click_time = 60

    field.mousePressEvent(FakeMouseEvent(40, 40, HELD))
    field.mouseMoveEvent(FakeMouseEvent(45, 45, HELD))
    assert field.is_selecting_traces is False
    assert field.current_trace == [(45, 45)]

    field.mousePressEvent(FakeMouseEvent(45, 45, Qt.MouseButton.RightButton))
    assert len(field_menu) == 1
    field.mouseReleaseEvent(FakeMouseEvent(45, 45))

    corners = [(140, 140), (180, 140), (180, 180), (140, 180)]
    _drag_lasso(field, corners)
    assert field.current_trace == corners
    assert field_notices == []


def _rectangle(field, x0, y0, x1, y1, pressed=True):
    """Drag a rectangle trace, through the field's own handlers.

    With `pressed` False the press is taken to have happened already. Either
    way it is put past the single-click window, where a release in the combo
    trace mode would start a line trace instead.
    """
    if pressed:
        field.mousePressEvent(FakeMouseEvent(x0, y0, HELD))
    field.click_time = 0
    field.mouseMoveEvent(FakeMouseEvent((x0 + x1) / 2, (y0 + y1) / 2, HELD))
    field.mouseMoveEvent(FakeMouseEvent(x1, y1, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(x1, y1))


@pytest.mark.parametrize("when", ["during the pinch", "after it"])
def test_a_fresh_press_around_the_pinch_that_ended_a_lasso(
    main_window, main_window_dialogs, field_notices, field_menu, when
):
    """The lasso's button comes up during the pinch, and a new press follows.

    Every mouse event is ignored while gesturing, so a press made during the
    pinch reaches no tool. Its click flags outlasted the pinch, and the moves
    after it drew a rectangle `tracePress` never started: with `current_trace`
    emptied by the lasso's end, that raised `IndexError`. Such a press is
    dropped now, like the lasso's. A press after the pinch is a fresh one and
    draws as usual.
    """
    field = main_window.field
    trace, timer = _start_lasso(main_window)
    x, y = field.current_trace[-1]
    started = Qt.GestureState.GestureStarted
    updated = Qt.GestureState.GestureUpdated
    finished = Qt.GestureState.GestureFinished

    field.gestureEvent(FakeGestureEvent(FakePinch(started, 200, 150, 1.0)))
    field.gestureEvent(FakeGestureEvent(FakePinch(updated, 210, 150, 1.5)))
    field.mouseReleaseEvent(FakeMouseEvent(x, y))
    _assert_lasso_dropped(field, timer)

    field.closed_trace_shape = "rect"
    main_window.usectrace_act.trigger()
    assert field.mouse_mode == CLOSEDTRACE
    assert field.closed_trace_shape == "rect"
    count = len(field.section.tracesAsList())

    if when == "during the pinch":
        field.mousePressEvent(FakeMouseEvent(300, 60, HELD))
        field.gestureEvent(FakeGestureEvent(FakePinch(finished, 210, 150, 1.5)))
        _rectangle(field, 300, 60, 340, 100, pressed=False)
        assert len(field.section.tracesAsList()) == count
        assert field.current_trace == []
    else:
        field.gestureEvent(FakeGestureEvent(FakePinch(finished, 210, 150, 1.5)))

    # the next press draws, whichever came before it
    _rectangle(field, 300, 60, 340, 100)
    assert len(field.section.tracesAsList()) == count + 1
    assert field_notices == []


def test_a_press_during_a_pinch_does_not_start_a_host_link(
    main_window, main_window_dialogs, field_notices, field_menu
):
    """The same press in Host, with no lasso before it.

    Host acts on any release, so the press the pinch kept from it picked the
    trace under the cursor as the start of a link.
    """
    field = main_window.field
    main_window.usehost_act.trigger()
    trace = _visible_trace(field)
    started = Qt.GestureState.GestureStarted
    finished = Qt.GestureState.GestureFinished

    field.gestureEvent(FakeGestureEvent(FakePinch(started, 200, 150, 1.0)))
    x, y = field.section_layer.traceToPix(trace)[0]
    field.mousePressEvent(FakeMouseEvent(x, y, HELD))
    field.gestureEvent(FakeGestureEvent(FakePinch(finished, 200, 150, 1.0)))
    field.mouseMoveEvent(FakeMouseEvent(x, y, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(x, y))

    assert field.hosted_trace is None

    # a click after the pinch still starts one
    field.mousePressEvent(FakeMouseEvent(x, y, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(x, y))
    assert field.hosted_trace is not None
    assert field_notices == []
