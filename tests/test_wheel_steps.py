"""Wheel scrolling moves sections by scroll distance, not by event count.

A macOS trackpad sends many small events per swipe and then momentum events
after the fingers lift. `MainWindow.wheelEvent` used to move one section per
event, so one swipe ran through dozens of sections. Now a section takes one
mouse wheel notch (120 units of `angleDelta`) or 60 points of trackpad travel,
the first section of a swipe comes at half that, and nothing moves after the
fingers lift.

No real trackpad is used here. `trackpad_replay` builds each swipe from the
native events AppKit sends and maps them the way Qt 6.9.3's cocoa plugin does,
in both orders Qt can deliver the first momentum event, then sends them through
`QTest.wheelEvent` into a live window on the fixture series. On a Mac the
window reads the NSEvent behind each wheel event; here `NativeEvents` plays
that part, and the `phases` window has no NSEvent, as on Wayland.

"After the lift" is everything after the last event the fingers made: the
first momentum event counts as after, whatever Qt calls it.
"""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from PyReconstruct.modules.gui.main import native_scroll
from PyReconstruct.modules.gui.main.wheel_steps import WheelSteps
from trackpad_replay import (
    BEGAN, ENDED, MAY_BEGIN, NONE, NativeEvents, deliver, last_finger,
    native_swipe, notch, qt_events,
)

pytestmark = pytest.mark.gui

P = Qt.ScrollPhase
START = 52  # the fixture series opens here, with sections 0 to 197
ORDERS = pytest.mark.parametrize("busy", [True, False], ids=["busy", "idle"])


@pytest.fixture
def window(main_window, qtbot):
    main_window.show()
    qtbot.waitExposed(main_window)
    assert main_window.series.current_section == START
    main_window.native = NativeEvents()
    main_window.wheel_steps.read_native = main_window.native
    return main_window


@pytest.fixture
def phases(window):
    """A window with no NSEvent to read, so Qt's phases are all it has."""
    window.native = None
    window.wheel_steps.read_native = lambda event: None
    return window


class Replayed:
    """Stands in for the Objective-C runtime: the replayed NSEvent, by timestamp."""

    def __init__(self, native):
        self.native = native
        self.timestamps = []

    def read(self, timestamp):
        self.timestamps.append(timestamp)
        return self.native.current


@pytest.fixture
def production(main_window, qtbot, monkeypatch):
    """A window that reads through `native_scroll.read`, as it ships.

    Only the Objective-C runtime under it is replayed: a wheel event made in
    Python has no NSEvent behind it.
    """
    main_window.show()
    qtbot.waitExposed(main_window)
    assert main_window.wheel_steps.read_native is native_scroll.read
    main_window.native = NativeEvents()
    main_window.runtime = Replayed(main_window.native)
    monkeypatch.setattr(native_scroll, "_failed", False)
    monkeypatch.setattr(native_scroll, "_runtime", main_window.runtime)
    return main_window


def scroll(window, events, modifiers=Qt.NoModifier):
    """Send wheel events over the field; the section after each one."""
    sections = []
    deliver(
        window.windowHandle(), QPointF(window.field.geometry().center()),
        events, modifiers,
        after=lambda _: sections.append(window.series.current_section),
        native=window.native,
    )
    return sections


def outside(window, phase, pixel, angle):
    """Send one wheel event with the pointer outside the field; the section after."""
    pos = QPointF(-5, -5)
    assert not window.field.geometry().contains(pos.toPoint())
    window.wheelEvent(QWheelEvent(
        pos, QPointF(window.mapToGlobal(pos)), QPoint(0, pixel), QPoint(0, angle),
        Qt.NoButton, Qt.NoModifier, phase, False,
    ))
    return window.series.current_section


def swipe(drag, momentum=(), busy=True):
    return qt_events(native_swipe(drag, momentum), busy)


def after_lift(events, sections):
    """Sections moved after the last finger event."""
    return sections[-1] - sections[last_finger(events)]


def deactivate(window, qtbot):
    """Put another window in front, as a dialog or another app would."""
    front = QWidget()
    front.show()
    front.activateWindow()
    qtbot.waitUntil(lambda: not window.isActiveWindow())
    front.close()


# --- mouse wheels -----------------------------------------------------------


def test_one_mouse_notch_is_one_section(window):
    assert scroll(window, [notch(-1)] * 4) == [51, 50, 49, 48]
    # macOS also reports a pixelDelta for a wheel notch; it does not count
    assert scroll(window, [notch(1, pixel=20)] * 4) == [49, 50, 51, 52]


def test_an_event_with_no_phase_moves_at_most_one_section(window):
    # two notches Windows sent as one event, or a large untagged touchpad
    # inertia event: one section, as before
    assert scroll(window, [notch(2)]) == [START + 1]
    assert scroll(window, [notch(-3)]) == [START]
    assert scroll(window, [notch(2)] * 3) == [START + 1, START + 2, START + 3]
    # and a plain notch is still one
    assert scroll(window, [notch(-1)]) == [START + 2]
    assert window.wheel_steps.total == pytest.approx(0)


def test_one_big_trackpad_event_moves_several_sections(window):
    # 150 points the system merged into one event: 30 for the first section,
    # then 60 each
    assert scroll(window, swipe([150]))[-1] == START + 3


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
    # 360 points: the first section at 30, then one per 60
    assert scroll(window, swipe([12] * 30))[-1] == START + 6
    assert scroll(window, swipe([-3] * 40))[-1] == START + 4


def test_the_first_section_comes_at_half_a_step(window):
    sections = scroll(window, swipe([10] * 9))
    # 30 points moves one, 90 a second, 150 would be a third
    assert sections[1:10] == [START] * 2 + [START + 1] * 6 + [START + 2]


@ORDERS
def test_momentum_after_the_lift_moves_nothing(window, busy):
    # 108 points is two sections with 18 left over; the first momentum event
    # (20 points, never tagged as momentum by Qt) would make it three
    events = swipe([12] * 9, momentum=[20, 16, 12, 8, 4, 2, 1], busy=busy)
    sections = scroll(window, events)
    assert sections[-1] == START + 2
    assert after_lift(events, sections) == 0


@ORDERS
def test_the_last_finger_update_moves_before_the_lift(window, busy):
    # five 12 point updates reach 60; the step is due on the fifth, not later
    events = swipe([12] * 5, momentum=[10, 8, 6, 4], busy=busy)
    sections = scroll(window, events)
    assert sections[last_finger(events)] == START + 1
    assert after_lift(events, sections) == 0


def test_one_big_momentum_event_moves_nothing(window):
    # 59 points of fingers is one section; a lone 61 point momentum event and
    # its end would make it two
    events = swipe([59], momentum=[61])
    sections = scroll(window, events)
    assert sections[-1] == START + 1
    assert after_lift(events, sections) == 0


@ORDERS
def test_a_long_fast_swipe_stops_when_the_fingers_lift(window, busy):
    drag = [6, 18, 30, 40, 40, 40, 30, 20]  # 224 points
    events = swipe(drag, momentum=[60, 50, 40, 30, 20, 12, 6, 3, 1], busy=busy)
    sections = scroll(window, events)
    assert sections[-1] == START + 4
    assert after_lift(events, sections) == 0


@ORDERS
def test_a_short_flick_moves_one_section_before_the_lift(window, busy):
    events = swipe([20, 15], momentum=[30, 25, 20, 15, 10, 5], busy=busy)
    sections = scroll(window, events)
    assert sections[-1] == START + 1
    assert after_lift(events, sections) == 0


def test_a_tiny_flick_moves_nothing(window):
    assert scroll(window, swipe([10], momentum=[12, 8, 4]))[-1] == START


def test_a_finger_end_with_its_own_delta_counts_it(window):
    # 10 points, then the fingers lift with 30 more on the end event
    native = [(MAY_BEGIN, NONE, 0), (BEGAN, NONE, 10), (ENDED, NONE, 30)]
    assert scroll(window, qt_events(native, busy=False))[-1] == START + 1


def test_swiping_back_starts_over(window):
    # 50 points up moves one; 30 points back moves it back
    sections = scroll(window, swipe([10] * 5 + [-10] * 7))
    assert max(sections) == START + 1
    assert sections[-1] == START


def test_a_section_change_from_elsewhere_drops_the_leftover(window):
    scroll(window, [(P.NoScrollPhase, 0, 100)])
    window.changeSection(START + 1)
    window.changeSection(START)
    # 100 + 30 would have crossed a notch
    assert scroll(window, [(P.NoScrollPhase, 0, 30)]) == [START]


def test_a_section_change_mid_swipe_leaves_nothing_to_move_later(window):
    begin, first, second, end = swipe([20, 10])
    # 20 points: 0.83 of the way to the first section
    assert scroll(window, [begin, first]) == [START, START]
    window.changeSection(START + 1)
    window.changeSection(START)
    # without the drop, 10 more points would move one section
    assert scroll(window, [second, end]) == [START, START]


def test_a_window_put_behind_drops_the_pending_swipe(window, qtbot):
    events = swipe([6, 6, 6, 12])
    # 18 points: 0.8 of the way to the first section
    assert scroll(window, events[:4])[-1] == START
    deactivate(window, qtbot)
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    # without the drop, 12 more points would move one section
    assert scroll(window, events[4:5]) == [START]
    assert scroll(window, events[5:])[-1] == START


@pytest.mark.parametrize("reader", ["window", "phases"])
def test_a_window_put_behind_ignores_the_rest_of_that_swipe(request, qtbot, reader):
    window = request.getfixturevalue(reader)
    events = swipe([12] * 10)
    # 24 points: 0.9 of the way to the first section
    assert scroll(window, events[:3])[-1] == START
    deactivate(window, qtbot)
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    # 96 more points of the same swipe move nothing
    assert scroll(window, events[3:])[-1] == START
    # the next swipe, or a mouse wheel, moves as usual
    assert scroll(window, swipe([12] * 5))[-1] == START + 1
    assert scroll(window, [notch(1)]) == [START + 2]


def test_a_mouse_wheel_after_a_window_switch_moves(window, qtbot):
    deactivate(window, qtbot)
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    assert scroll(window, [notch(1)]) == [START + 1]


# --- the pointer outside the field --------------------------------------------


def test_scroll_outside_the_field_moves_nothing_and_keeps_the_leftover(window):
    assert scroll(window, [(P.NoScrollPhase, 0, 100)]) == [START]
    # 20 more would cross a notch; outside the field it neither moves nor uses up
    assert outside(window, P.NoScrollPhase, 0, 20) == START
    assert scroll(window, [(P.NoScrollPhase, 0, 20)]) == [START + 1]


def test_trackpad_travel_outside_the_field_keeps_the_leftover(window):
    begin, first, second, *rest = swipe([12] * 4, busy=False)
    # 24 points: 0.9 of the way to the first section
    assert scroll(window, [begin, first, second]) == [START] * 3
    assert outside(window, P.ScrollUpdate, 12, 24) == START
    # without the guard first, the 12 points outside would have used up the step
    assert scroll(window, rest) == [START + 1] * 3


# --- the reader as it ships ---------------------------------------------------


@ORDERS
def test_the_window_reads_momentum_through_native_scroll(production, busy):
    # the busy order is where Qt's phases alone let the first momentum event through
    events = swipe([12] * 9, momentum=[50, 16, 12, 8, 4, 2, 1], busy=busy)
    sections = scroll(production, events)
    assert sections[-1] == START + 2
    assert after_lift(events, sections) == 0
    assert production.runtime.timestamps


def test_a_reader_that_finds_no_event_falls_back_on_qt_phases(production):
    production.runtime.read = lambda timestamp: None
    events = swipe([12] * 9, momentum=[20, 16, 12, 8, 4, 2, 1], busy=False)
    sections = scroll(production, events)
    assert sections[-1] == START + 2
    assert after_lift(events, sections) == 0
    assert not native_scroll._failed


def test_a_reader_that_fails_turns_itself_off_and_scrolling_still_works(production):
    calls = []

    def broken(timestamp):
        calls.append(timestamp)
        raise OSError("AppKit is not loaded")

    production.runtime.read = broken
    sections = scroll(production, swipe([12] * 9, momentum=[20, 16, 12], busy=False))
    assert native_scroll._failed
    assert len(calls) == 1  # never asked again
    assert sections[-1] == START + 2


# --- Qt's phases alone (Wayland, or a Mac whose NSEvent cannot be read) ------------


def test_a_wayland_swipe_moves_by_pixels_not_angle(phases):
    # Qt on Wayland reports 12 angleDelta units per pixel of finger travel
    events = [(P.ScrollBegin, 0, 0)] + [(P.ScrollUpdate, 10, 120)] * 6 + [(P.ScrollEnd, 0, 0)]
    assert scroll(phases, events)[-1] == START + 1


def test_wayland_fractions_never_count_by_angle(phases):
    # sixty 0.25 pixel frames are 15 pixels; Qt rounds each frame and carries
    # the error, so most frames have a pixelDelta of 0 but an angleDelta of 3
    events, error = [(P.ScrollBegin, 0, 0)], 0.0
    for _ in range(60):
        pixel = round(0.25 + error)
        error += 0.25 - pixel
        events.append((P.ScrollUpdate, pixel, 3))
    events.append((P.ScrollEnd, 0, 0))
    assert scroll(phases, events)[-1] == START


def test_phases_alone_count_a_finger_end_delta(phases):
    events = [(P.ScrollBegin, 0, 0), (P.ScrollUpdate, 10, 20), (P.ScrollEnd, 30, 60)]
    assert scroll(phases, events)[-1] == START + 1


def test_phases_alone_ignore_momentum_in_the_idle_order(phases):
    events = swipe([12] * 9, momentum=[20, 16, 12, 8, 4, 2, 1], busy=False)
    sections = scroll(phases, events)
    assert sections[-1] == START + 2
    assert after_lift(events, sections) == 0


def test_phases_alone_count_the_first_momentum_event_in_the_busy_order(phases):
    # the known limit without the NSEvent: Qt sends it as a ScrollUpdate, and
    # 18 points left over plus its 50 cross a step
    events = swipe([12] * 9, momentum=[50, 16, 12, 8, 4, 2, 1], busy=True)
    sections = scroll(phases, events)
    assert after_lift(events, sections) == 1


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


def test_momentum_after_a_finished_zoom_starts_no_zoom(window):
    events = swipe([12] * 5, momentum=[40, 30, 20, 10])
    lift = last_finger(events) + 1
    scroll(window, events[:lift], Qt.ControlModifier)
    assert window.is_zooming
    # moving the mouse finishes the zoom
    QTest.mouseMove(window.field, window.field.rect().center() + QPoint(5, 5))
    assert not window.is_zooming
    width = window.series.window[2]
    scroll(window, events[lift:], Qt.ControlModifier)
    assert not window.is_zooming
    assert window.series.window[2] == pytest.approx(width)
