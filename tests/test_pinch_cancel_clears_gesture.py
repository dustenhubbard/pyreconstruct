"""A canceled pinch lets go of the field and leaves the view where it was.

`gestureEvent` sets `is_gesturing` when a pinch starts and clears it when the
pinch finishes, and every mouse handler returns early while it is set. A
canceled pinch had no branch, so the flag stayed set and the field ignored
every later press, move and release.

Qt cancels a running pinch only when a gesture on a parent widget with
`CancelAllInContext` takes it over, and a cancel commits nothing. The view
goes back to the one from before the pinch rather than to where a finished
pinch would have left it.

A press made during the pinch was ignored, so no tool saw it. A cancel drops it
too, and its release finishes nothing: before, a stamp was placed, and a closed
trace in combo mode indexed an empty trace. A press made before the pinch is
dropped as well, so what it started ends with the cancel: a lasso kept its
edge-pan timer and went on moving the view.

The pinch is a stand-in event: a `QPinchGesture`'s state is set only by Qt's
gesture manager, so a test cannot build one in a given state.
"""

import pytest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPointingDevice

from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    CLOSEDTRACE,
    PANZOOM,
    POINTER,
    STAMP,
)

pytestmark = pytest.mark.gui

STARTED = Qt.GestureState.GestureStarted
UPDATED = Qt.GestureState.GestureUpdated
FINISHED = Qt.GestureState.GestureFinished
CANCELED = Qt.GestureState.GestureCanceled


class FakeMouseEvent:
    """The accessors the mouse handlers read off a mouse event."""

    def __init__(self, x, y, buttons=Qt.MouseButton.NoButton):
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


def _pinch(field, end_state):
    """Start a pinch, zoom it to 1.5x, and end it in `end_state`.

    Returns the window and the rendered field from before the pinch.
    """
    field.generateView(update=False)
    window_before = list(field.series.window)
    view_before = field.field_pixmap.toImage()

    field.gestureEvent(FakeGestureEvent(FakePinch(STARTED, 200, 150, 1.0)))
    field.gestureEvent(FakeGestureEvent(FakePinch(UPDATED, 210, 150, 1.5)))

    # true before the fix as well: the pinch is under way and has redrawn
    # the field, so a restored view below is not one that never changed
    assert field.is_gesturing is True
    assert field.is_panzooming is True
    assert field.field_pixmap.toImage() != view_before

    field.gestureEvent(FakeGestureEvent(FakePinch(end_state, 210, 150, 1.5)))

    return window_before, view_before


def test_a_canceled_pinch_ends_and_restores_the_view(main_window):
    field = main_window.field

    window_before, view_before = _pinch(field, CANCELED)

    assert field.is_gesturing is False
    assert field.is_panzooming is False
    assert field.series.window == window_before
    assert field.field_pixmap.toImage() == view_before


def test_the_field_takes_mouse_events_after_a_canceled_pinch(
    main_window, monkeypatch
):
    main_window.usepanzoom_act.trigger()
    field = main_window.field
    assert field.mouse_mode == PANZOOM

    _pinch(field, CANCELED)

    presses = []
    monkeypatch.setattr(
        field, "mousePanzoomPress", lambda event: presses.append(event)
    )
    press = FakeMouseEvent(40, 50, Qt.MouseButton.LeftButton)
    field.mousePressEvent(press)

    assert presses == [press]
    assert (field.clicked_x, field.clicked_y) == (40, 50)


def test_a_finished_pinch_still_commits_its_zoom(main_window):
    """The contrast: a finished pinch keeps the view it ended on."""
    field = main_window.field

    window_before, _view_before = _pinch(field, FINISHED)

    assert field.is_gesturing is False
    assert field.is_panzooming is False
    assert field.series.window != window_before
    # zoomed in 1.5x, so the window is two thirds as wide
    assert field.series.window[2] == pytest.approx(window_before[2] / 1.5)


def _trace_count(field):
    return sum(len(contour) for contour in field.section.contours.values())


def _press_during_canceled_pinch(field):
    """Press the left button mid-pinch, cancel the pinch, then let go."""
    field.generateView(update=False)
    field.gestureEvent(FakeGestureEvent(FakePinch(STARTED, 200, 150, 1.0)))
    field.gestureEvent(FakeGestureEvent(FakePinch(UPDATED, 210, 150, 1.5)))
    field.mousePressEvent(FakeMouseEvent(40, 50, Qt.MouseButton.LeftButton))
    field.gestureEvent(FakeGestureEvent(FakePinch(CANCELED, 210, 150, 1.5)))
    field.mouseReleaseEvent(FakeMouseEvent(40, 50))


def test_a_press_made_during_a_canceled_pinch_places_no_stamp(main_window):
    main_window.usestamp_act.trigger()
    field = main_window.field
    assert field.mouse_mode == STAMP
    traces_before = _trace_count(field)

    _press_during_canceled_pinch(field)

    assert _trace_count(field) == traces_before
    assert (field.lclick, field.rclick, field.mclick) == (False, False, False)

    # the dropped press is over, so the next click places a stamp
    field.mousePressEvent(FakeMouseEvent(60, 70, Qt.MouseButton.LeftButton))
    field.mouseReleaseEvent(FakeMouseEvent(60, 70))
    assert _trace_count(field) == traces_before + 1


def test_a_press_made_during_a_canceled_pinch_starts_no_trace(main_window):
    main_window.usectrace_act.trigger()
    field = main_window.field
    assert field.mouse_mode == CLOSEDTRACE
    assert field.series.getOption("trace_mode") == "combo"

    _press_during_canceled_pinch(field)

    assert field.is_line_tracing is False
    assert field.current_trace == []


def test_a_press_released_before_the_cancel_does_not_eat_the_next_click(
    main_window,
):
    """The pinch ignores the release too, so the cancel sees a stale press."""
    main_window.usestamp_act.trigger()
    field = main_window.field
    traces_before = _trace_count(field)

    field.generateView(update=False)
    field.gestureEvent(FakeGestureEvent(FakePinch(STARTED, 200, 150, 1.0)))
    field.mousePressEvent(FakeMouseEvent(40, 50, Qt.MouseButton.LeftButton))
    field.mouseReleaseEvent(FakeMouseEvent(40, 50))
    field.gestureEvent(FakeGestureEvent(FakePinch(CANCELED, 200, 150, 1.0)))
    assert _trace_count(field) == traces_before

    field.mousePressEvent(FakeMouseEvent(60, 70, Qt.MouseButton.LeftButton))
    field.mouseReleaseEvent(FakeMouseEvent(60, 70))
    assert _trace_count(field) == traces_before + 1


def _drag_then_cancel_a_pinch(field):
    """Press and drag past the click time, then pinch, cancel and let go."""
    field.generateView(update=False)
    field.mousePressEvent(FakeMouseEvent(40, 50, Qt.MouseButton.LeftButton))
    field.click_time -= 10  # past max_click_time, so this is a drag
    field.mouseMoveEvent(FakeMouseEvent(5, 60, Qt.MouseButton.LeftButton))
    field.mouseMoveEvent(FakeMouseEvent(3, 80, Qt.MouseButton.LeftButton))
    started = (field.is_selecting_traces, field.is_drawing_rad, list(field.current_trace))

    field.gestureEvent(FakeGestureEvent(FakePinch(STARTED, 200, 150, 1.0)))
    field.gestureEvent(FakeGestureEvent(FakePinch(UPDATED, 210, 150, 1.5)))
    field.gestureEvent(FakeGestureEvent(FakePinch(CANCELED, 210, 150, 1.5)))
    field.mouseReleaseEvent(FakeMouseEvent(3, 80))
    return started


def test_a_lasso_held_through_a_canceled_pinch_ends(main_window):
    main_window.usepointer_act.trigger()
    field = main_window.field
    assert field.mouse_mode == POINTER

    is_selecting, _rad, trace = _drag_then_cancel_a_pinch(field)
    # the lasso was under way near the edge, with its edge-pan timer
    assert is_selecting is True
    assert trace

    assert field.is_selecting_traces is False
    assert field.mouse_boundary_timer is None
    assert field.current_trace == []


def test_a_stamp_radius_held_through_a_canceled_pinch_ends(main_window):
    main_window.usestamp_act.trigger()
    field = main_window.field
    traces_before = _trace_count(field)

    _is_selecting, is_drawing_rad, _trace = _drag_then_cancel_a_pinch(field)
    assert is_drawing_rad is True

    assert field.is_drawing_rad is False
    assert field.current_trace == []
    assert _trace_count(field) == traces_before


def test_a_pencil_stroke_held_through_a_canceled_pinch_ends(main_window):
    main_window.usectrace_act.trigger()
    field = main_window.field
    traces_before = _trace_count(field)

    _is_selecting, _rad, trace = _drag_then_cancel_a_pinch(field)
    assert len(trace) > 1

    assert field.current_trace == []
    assert _trace_count(field) == traces_before
