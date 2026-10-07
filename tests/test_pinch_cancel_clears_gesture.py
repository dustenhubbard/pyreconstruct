"""A canceled pinch lets go of the field and leaves the view where it was.

`gestureEvent` sets `is_gesturing` when a pinch starts and clears it when the
pinch finishes, and every mouse handler returns early while it is set. A
canceled pinch had no branch, so the flag stayed set and the field ignored
every later press, move and release.

Qt cancels a running pinch only when a gesture on a parent widget with
`CancelAllInContext` takes it over, and a cancel commits nothing. The view
goes back to the one from before the pinch rather than to where a finished
pinch would have left it.

The pinch is a stand-in event: a `QPinchGesture`'s state is set only by Qt's
gesture manager, so a test cannot build one in a given state.
"""

import pytest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPointingDevice

from PyReconstruct.modules.gui.main.field_widget_5_mouse import PANZOOM

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
