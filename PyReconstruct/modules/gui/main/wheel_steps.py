"""Turn wheel events into whole section steps and zoom factors.

A mouse wheel sends one event per notch, 120 units of `angleDelta`, with no
scroll phase. A macOS trackpad sends a stream of small events with phases
instead: ScrollBegin, ScrollUpdate while the fingers move, then ScrollMomentum
after they lift, and ScrollEnd. Moving one section per event made a single
two-finger swipe run through dozens of sections.

`WheelSteps` adds the scroll up and moves one section per notch, or per
`STEP_PX` pixels of finger travel on a trackpad. The first section of a swipe
comes at half that, so a short flick moves one. Nothing moves after the
fingers lift.

Qt does not tag the first momentum event (qnsview_mouse.mm, `scrollWheel:`);
it comes as a ScrollUpdate, or as a ScrollBegin with a delta. On macOS the
NSEvent behind each wheel event says which it is (`native_scroll`). Where that
cannot be read, Qt's phases are all there is: momentum and a ScrollBegin's
delta give nothing, so only a first momentum event that Qt sends as a
ScrollUpdate can count.
"""

import math
from contextlib import contextmanager

from PySide6.QtCore import Qt

from . import native_scroll

P = Qt.ScrollPhase

# angleDelta units per mouse wheel notch, and per section
NOTCH = 120
# pixels of trackpad finger travel per section (the same as one notch on macOS,
# where Qt reports 2 angleDelta units per pixel)
STEP_PX = 60
# the first section of a swipe, or of a swipe back, comes after this much of
# one, so a short flick moves one section while the fingers are still down
FIRST_STEP = 0.5

# zoom per mouse wheel notch
ZOOM_IN_PER_STEP = 1.1
ZOOM_OUT_PER_STEP = 0.9


def scroll_units(event) -> float:
    """The vertical scroll of one event in notches (1.0 = one section).

    Trackpads (events with a scroll phase) are measured in pixels, so the
    feel does not depend on how a platform scales `angleDelta`: Wayland
    reports 12 units per pixel, macOS 2. A pixel delta that rounds to zero is
    zero; Wayland carries the fraction into the next event. Wheels have no
    phase and use `angleDelta`; their `pixelDelta` is a guess on macOS and
    null elsewhere.
    """
    if event.phase() != P.NoScrollPhase:
        return event.pixelDelta().y() / STEP_PX
    return event.angleDelta().y() / NOTCH


def zoom_factor(units: float) -> float:
    """The zoom for a scroll of `units` notches: 1.1 or 0.9 per notch."""
    if units > 0:
        return ZOOM_IN_PER_STEP ** units
    if units < 0:
        return ZOOM_OUT_PER_STEP ** -units
    return 1.0


class WheelSteps:
    """Adds up the scroll the fingers or the wheel made and hands out sections."""

    def __init__(self, read_native=native_scroll.read):
        self.read_native = read_native  # the NSEvent behind a wheel event, or None
        self.total = 0.0  # leftover scroll toward the next section, in notches
        self.direction = 0  # which way this swipe goes: 1 up, -1 down, 0 not yet
        self.fingers_down = False
        self.lifted = False  # the event just fed ended the finger part of a gesture
        self._moving = False

    def reset(self):
        """Drop the leftover scroll; the next swipe starts fresh."""
        self.total = 0.0
        self.direction = 0

    def cancel(self):
        """Drop everything pending; the rest of this gesture moves nothing."""
        self.reset()
        self.fingers_down = False

    def navigated(self):
        """A section change from elsewhere drops the leftover scroll."""
        if not self._moving:
            self.reset()

    @contextmanager
    def moving(self):
        """The section change made for a step keeps the leftover."""
        self._moving = True
        try:
            yield
        finally:
            self._moving = False

    def _begin(self):
        self.reset()
        self.fingers_down = True

    def _lift(self):
        if self.fingers_down:
            self.fingers_down = False
            self.lifted = True

    def feed(self, event) -> float:
        """The scroll in notches that the fingers or the wheel made.

        Sets `lifted` when this event shows the fingers have left the
        trackpad. Momentum gives nothing.
        """
        phase = event.phase()
        self.lifted = False
        if phase == P.NoScrollPhase:
            return scroll_units(event)

        native = self.read_native(event)
        if native is not None:
            if native.momentum:
                self._lift()
                return 0.0
            if phase == P.ScrollBegin:
                self._begin()
            units = 0.0
            # Qt sends an event with no delta twice; count the native delta once
            if event.pixelDelta().y() or event.angleDelta().y():
                units = native.delta_y / STEP_PX
            if native.phase & (native_scroll.ENDED | native_scroll.CANCELLED):
                self._lift()
            return units

        if phase == P.ScrollBegin:
            # a new gesture; in Qt's idle order the first momentum event comes
            # as a ScrollBegin with a delta, so a ScrollBegin's delta is not used
            self._begin()
            return 0.0
        if phase == P.ScrollMomentum:
            self._lift()
            return 0.0
        if phase == P.ScrollEnd:
            if not self.fingers_down:
                return 0.0  # the end of momentum
            self._lift()
        return scroll_units(event)

    def step(self, event) -> int:
        """Sections to move for one wheel event: positive up, negative down."""
        units = self.feed(event)
        if units:
            direction = 1 if units > 0 else -1
            if event.phase() == P.NoScrollPhase:
                # reversing a wheel drops what was left over the other way
                if self.total and direction * self.total < 0:
                    self.reset()
            elif direction != self.direction:
                # a new swipe, or a swipe back, drops the leftover too and
                # moves its first section after FIRST_STEP of travel
                self.direction = direction
                self.total = direction * (1 - FIRST_STEP)
        self.total += units
        # whole notches, toward zero; the nudge keeps ten 0.1s from being 0.999...
        steps = int(self.total + math.copysign(1e-9, self.total))
        self.total -= steps
        if self.lifted:
            self.reset()
        return steps

    def zoom(self, event) -> float:
        """The zoom factor for one wheel event, in proportion to its scroll."""
        return zoom_factor(self.feed(event))
