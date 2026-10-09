"""Wheel scrolling moves sections by scroll distance, not by event count.

A macOS trackpad sends many small events per swipe and then momentum events
after the fingers lift. `MainWindow.wheelEvent` used to move one section per
event, so one swipe ran through dozens of sections. Now a section takes one
mouse wheel notch (120 units of `angleDelta`) or 60 points of trackpad travel,
nothing moves after the fingers lift, and a short flick moves one section.

No real trackpad is used here. `trackpad_replay` builds each swipe from the
native events AppKit sends and maps them the way Qt 6.9.3's cocoa plugin does,
in both orders Qt can deliver the first momentum event, then sends them through
`QTest.wheelEvent` into a live window on the fixture series.
"""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from PyReconstruct.modules.gui.main.wheel_steps import WheelSteps
from trackpad_replay import deliver, native_swipe, notch, qt_events

pytestmark = pytest.mark.gui

P = Qt.ScrollPhase
START = 52  # the fixture series opens here, with sections 0 to 197
ORDERS = pytest.mark.parametrize("busy", [True, False], ids=["busy", "idle"])


@pytest.fixture
def window(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    assert main_window.series.current_section == START
    return main_window


def scroll(window, events, modifiers=Qt.NoModifier):
    """Send wheel events over the field; the section after each one."""
    sections = []
    deliver(
        window.windowHandle(), QPointF(window.field.geometry().center()),
        events, modifiers,
        after=lambda _: sections.append(window.series.current_section),
    )
    return sections


def swipe(drag, momentum=(), busy=True):
    return qt_events(native_swipe(drag, momentum), busy)


def lift_index(events):
    """Where the fingers have left: the first momentum or end event."""
    return next(i for i, e in enumerate(events) if e[0] in (P.ScrollMomentum, P.ScrollEnd))


# --- mouse wheels -----------------------------------------------------------


def test_one_mouse_notch_is_one_section(window):
    assert scroll(window, [notch(-1)] * 4) == [51, 50, 49, 48]
    # macOS also reports a pixelDelta for a wheel notch; it does not count
    assert scroll(window, [notch(1, pixel=20)] * 4) == [49, 50, 51, 52]


def test_one_event_of_two_notches_moves_two_sections(window):
    assert scroll(window, [notch(2)]) == [START + 2]
    assert scroll(window, [notch(-3)]) == [START - 1]


def test_fine_wheel_steps_add_up_to_one_section_per_notch(window):
    events = [(P.NoScrollPhase, 0, 30)] * 8
    assert scroll(window, events)[-1] == START + 2
    # 50 + 80 + 110 is two notches, with nothing left over
    events = [(P.NoScrollPhase, 0, d) for d in (50, 80, 110)]
    assert scroll(window, events)[-1] == START + 4
    assert window.wheel_steps.total == pytest.approx(0)


def test_ten_tenths_of_a_notch_are_one_section(qapp):
    steps = WheelSteps()
    event = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 12),
        Qt.NoButton, Qt.NoModifier, P.NoScrollPhase, False,
    )
    assert sum(steps.step(event) for _ in range(10)) == 1


# --- trackpad swipes ----------------------------------------------------------


def test_a_slow_swipe_moves_one_section_per_60_points(window):
    assert scroll(window, swipe([12] * 30))[-1] == START + 6
    assert scroll(window, swipe([-3] * 40))[-1] == START + 4


@ORDERS
def test_momentum_after_the_lift_moves_nothing(window, busy):
    # 108 points is one section with 48 left over; the first momentum event
    # (20 points, never tagged as momentum by Qt) would make it two
    events = swipe([12] * 9, momentum=[20, 16, 12, 8, 4, 2, 1], busy=busy)
    sections = scroll(window, events)
    assert sections[-1] == START + 1
    assert sections[lift_index(events)] == sections[-1]


@ORDERS
def test_a_long_fast_swipe_stops_when_the_fingers_lift(window, busy):
    drag = [6, 18, 30, 40, 40, 40, 30, 20]  # 224 points
    events = swipe(drag, momentum=[60, 50, 40, 30, 20, 12, 6, 3, 1], busy=busy)
    sections = scroll(window, events)
    assert sections[-1] == START + 3
    assert sections[lift_index(events)] == sections[-1]


@ORDERS
def test_a_short_flick_moves_one_section(window, busy):
    events = swipe([20, 15], momentum=[30, 25, 20, 15, 10, 5], busy=busy)
    sections = scroll(window, events)
    assert sections[-1] == START + 1
    # it moves as the fingers lift, not when the momentum runs out
    assert sections[lift_index(events)] == START + 1


def test_a_tiny_flick_moves_nothing(window):
    assert scroll(window, swipe([10], momentum=[12, 8, 4]))[-1] == START


def test_a_flick_after_a_step_adds_nothing(window):
    # 90 points: one section, then 30 left over at the lift
    assert scroll(window, swipe([30, 30, 30]))[-1] == START + 1


def test_reversing_drops_the_leftover(window):
    # 50 points up, then 70 down: one section down, not a net 20 down
    assert scroll(window, swipe([10] * 5 + [-10] * 7))[-1] == START - 1


def test_a_wayland_swipe_moves_by_pixels_not_angle(window):
    # Qt on Wayland reports 12 angleDelta units per pixel of finger travel
    events = [(P.ScrollBegin, 0, 0)] + [(P.ScrollUpdate, 10, 120)] * 6 + [(P.ScrollEnd, 0, 0)]
    assert scroll(window, events)[-1] == START + 1


def test_a_section_change_from_elsewhere_drops_the_leftover(window):
    scroll(window, [(P.NoScrollPhase, 0, 100)])
    window.changeSection(START + 1)
    window.changeSection(START)
    # 100 + 30 would have crossed a notch
    assert scroll(window, [(P.NoScrollPhase, 0, 30)]) == [START]


# --- Cmd+scroll zoom (Ctrl+scroll on Windows/Linux) ------------------------------


@ORDERS
def test_trackpad_zoom_follows_the_fingers_only(window, busy):
    width = window.series.window[2]
    # 60 points is one notch of zoom; the momentum after the lift adds none
    events = swipe([12] * 5, momentum=[40, 30, 20, 10], busy=busy)
    scroll(window, events, Qt.ControlModifier)
    assert window.zoom_factor == pytest.approx(1.1)
    assert window.series.current_section == START
    QTest.keyRelease(window, Qt.Key_Control)
    assert not window.is_zooming
    assert window.series.window[2] == pytest.approx(width / 1.1)


def test_mouse_zoom_is_one_step_per_notch(window):
    scroll(window, [notch(1), notch(1), notch(-1)], Qt.ControlModifier)
    assert window.zoom_factor == pytest.approx(1.1 * 1.1 * 0.9)
