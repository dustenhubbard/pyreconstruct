"""`native_scroll` reads the macOS event behind a wheel event, or gives None.

It only trusts `[NSApp currentEvent]` when that is a scroll event with the
wheel event's own timestamp, never asks a non-scroll event for its phase
(AppKit raises for that), and turns itself off after any error.
"""

import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from PyReconstruct.modules.gui.main import native_scroll
from PyReconstruct.modules.gui.main.native_scroll import NativeScroll


def wheel_event(timestamp=0):
    event = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 12), QPoint(0, 24),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollPhase.ScrollUpdate, False,
    )
    event.setTimestamp(timestamp)
    return event


class FakeRuntime(native_scroll._Runtime):
    """The Objective-C calls, answered from a dict of selector to value."""

    def __init__(self, event):
        self.app_class, self.shared, self.current = "NSApplication", "shared", "current"
        self.type, self.timestamp = "type", "timestamp"
        self.phase, self.momentum, self.delta_y = "phase", "momentum", "delta_y"
        self.event = event
        self.asked = []

    def _send(self, target, selector):
        self.asked.append(selector)
        if selector == self.shared:
            return "app"
        if selector == self.current:
            return "event" if self.event else None
        return self.event[selector]

    send_id = send_uint = send_double = _send


def test_a_matching_scroll_event_is_read(qapp):
    runtime = FakeRuntime(dict(type=22, timestamp=452.676, phase=0, momentum=1, delta_y=17.0))
    assert runtime.read(452676) == NativeScroll(0, 1, 17.0)


def test_an_event_from_another_time_is_not_trusted(qapp):
    runtime = FakeRuntime(dict(type=22, timestamp=452.675, phase=0, momentum=1, delta_y=17.0))
    assert runtime.read(452676) is None


def test_a_non_scroll_event_is_never_asked_for_its_phase(qapp):
    runtime = FakeRuntime(dict(type=10, timestamp=452.676))
    assert runtime.read(452676) is None
    assert "phase" not in runtime.asked and "momentum" not in runtime.asked


def test_no_current_event_is_none(qapp):
    assert FakeRuntime(None).read(452676) is None


def test_an_error_turns_it_off(qapp, monkeypatch):
    class Broken:
        def read(self, timestamp):
            raise OSError("no runtime")

    monkeypatch.setattr(native_scroll, "_failed", False)
    monkeypatch.setattr(native_scroll, "_runtime", Broken())
    assert native_scroll.read(wheel_event()) is None
    assert native_scroll._failed


def test_an_event_qt_did_not_get_from_appkit_reads_as_none(qapp):
    # a wheel event made in Python has no NSEvent behind it, on any platform
    assert native_scroll.read(wheel_event(timestamp=123)) is None


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS has an NSEvent to read")
def test_other_platforms_never_load_the_runtime(qapp):
    assert native_scroll._failed
    assert native_scroll._runtime is None


def test_the_main_window_reads_the_native_event(main_window):
    assert main_window.wheel_steps.read_native is native_scroll.read
