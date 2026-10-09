"""Wheel scrolling moves sections by scroll distance, not by event count.

A macOS trackpad sends many small `angleDelta` events per swipe (2 units per
pixel, ScrollBegin/ScrollUpdate/ScrollEnd) and then ScrollMomentum events after
the fingers lift. `MainWindow.wheelEvent` used to move one section per event,
so one swipe ran through dozens of sections. A mouse wheel sends one 120-unit
event per notch with NoScrollPhase, and that must still be one section.

No real trackpad is used here: the events are built by hand with the deltas
and phases Qt's cocoa plugin produces (qnsview_mouse.mm, `scrollWheel:`).
"""

import types

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QWheelEvent

from PyReconstruct.modules.gui.main import main_window as mw_module
from PyReconstruct.modules.gui.main.main_window import MainWindow
from PyReconstruct.modules.gui.main.wheel_steps import WheelSteps, zoom_step

pytestmark = pytest.mark.gui

NOTCH = 120
P = Qt.ScrollPhase


def wheel(dy, phase=P.NoScrollPhase, pixels=None):
    """A vertical wheel event; trackpad events carry pixels = dy / 2."""
    if pixels is None:
        pixels = 0 if phase == P.NoScrollPhase else dy // 2
    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(0, pixels), QPoint(0, dy),
        Qt.NoButton, Qt.NoModifier, phase, False,
    )


def swipe(dy_per_event, count, momentum=0, momentum_dy=None):
    """One trackpad swipe: begin, updates, momentum after lift, end."""
    events = [wheel(0, P.ScrollBegin)]
    events += [wheel(dy_per_event, P.ScrollUpdate) for _ in range(count)]
    events += [wheel(momentum_dy or dy_per_event, P.ScrollMomentum) for _ in range(momentum)]
    events.append(wheel(0, P.ScrollEnd))
    return events


def run(stepper, events, section=1):
    return [stepper.step(e, section) for e in events]


# --- the stepper alone ----------------------------------------------------


def test_one_mouse_notch_is_one_section(qapp):
    s = WheelSteps()
    assert run(s, [wheel(NOTCH)]) == [1]
    assert run(s, [wheel(-NOTCH)]) == [-1]
    assert run(s, [wheel(NOTCH)] * 5) == [1] * 5


def test_small_trackpad_deltas_summing_to_one_notch_are_one_section(qapp):
    s = WheelSteps()
    steps = run(s, swipe(12, 10))
    assert sum(steps) == 1
    assert steps[10] == 1  # the tenth update is where it reaches 120


def test_momentum_events_move_nothing(qapp):
    s = WheelSteps()
    steps = run(s, swipe(12, 10, momentum=50, momentum_dy=40))
    assert sum(steps) == 1


def test_direction_reversal_drops_the_leftover(qapp):
    s = WheelSteps()
    # 100 up, then 120 down: one section down, not a net 20 down
    assert run(s, [wheel(100), wheel(-30), wheel(-90)]) == [0, 0, -1]


def test_scroll_end_drops_the_leftover(qapp):
    s = WheelSteps()
    assert sum(run(s, swipe(50, 2))) == 0
    assert sum(run(s, swipe(30, 1))) == 0  # 100 + 30 would have been a step


def test_section_change_from_elsewhere_drops_the_leftover(qapp):
    s = WheelSteps()
    assert s.step(wheel(100), section=5) == 0
    assert s.step(wheel(30), section=9) == 0


def test_zoom_is_proportional_to_scroll(qapp):
    assert zoom_step(wheel(NOTCH)) == 1.1
    assert zoom_step(wheel(-NOTCH)) == 0.9
    factor = 1.0
    for _ in range(10):
        factor *= zoom_step(wheel(12, P.ScrollUpdate))
    assert factor == pytest.approx(1.1)


# --- through MainWindow.wheelEvent ------------------------------------------


@pytest.fixture
def window(monkeypatch):
    """A stand-in for the main window with just what wheelEvent reads."""
    mods = {"value": Qt.NoModifier}
    monkeypatch.setattr(
        mw_module, "QApplication",
        types.SimpleNamespace(keyboardModifiers=lambda: mods["value"]),
    )
    w = types.SimpleNamespace()
    w.mods = mods
    w.moves = []
    w.series = types.SimpleNamespace(current_section=50)
    w.field = types.SimpleNamespace(
        mclick=False,
        geometry=lambda: QRect(0, 0, 1000, 1000),
        cursor=lambda: types.SimpleNamespace(pos=lambda: QPoint(5, 5)),
        mapFromGlobal=lambda p: p,
        panzoomPress=lambda x, y: None,
        panzoomMove=lambda zoom_factor: None,
    )
    w.activateWindow = lambda: None
    w.is_zooming = False
    w.wheel_steps = WheelSteps()

    def increment(down=False):
        w.moves.append(-1 if down else 1)
        w.series.current_section += -1 if down else 1

    w.incrementSection = increment
    return w


def test_one_swipe_moves_a_few_sections_not_one_per_event(qapp, window):
    # 30 updates of 12 is 360 units; 40 momentum events follow the lift
    for e in swipe(12, 30, momentum=40, momentum_dy=24):
        MainWindow.wheelEvent(window, e)
    assert window.moves == [1, 1, 1]


def test_mouse_notches_still_move_one_section_each(qapp, window):
    for _ in range(4):
        MainWindow.wheelEvent(window, wheel(-NOTCH))
    assert window.moves == [-1] * 4


def test_ctrl_trackpad_zoom_matches_one_notch(qapp, window):
    window.mods["value"] = Qt.ControlModifier
    for e in swipe(12, 10, momentum=40):
        MainWindow.wheelEvent(window, e)
    assert window.zoom_factor == pytest.approx(1.1)
    assert window.moves == []
