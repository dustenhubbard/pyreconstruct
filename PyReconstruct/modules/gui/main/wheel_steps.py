"""Turn wheel events into whole section steps and zoom factors.

A mouse wheel sends one event per notch, 120 units of `angleDelta`, with no
scroll phase. A macOS trackpad sends a stream of small events with phases
instead: ScrollBegin, ScrollUpdate while the fingers move, then ScrollMomentum
after they lift, and ScrollEnd. Moving one section per event made a single
two-finger swipe run through dozens of sections.

`WheelSteps` adds the scroll up and moves one section per notch, or per
`STEP_PX` pixels of finger travel on a trackpad. Nothing moves after the
fingers lift. Qt does not tag the first momentum event (qnsview_mouse.mm,
`scrollWheel:`), and it reaches the window in one of two orders:

    busy: ... ScrollUpdate, ScrollUpdate (first momentum), ScrollMomentum ...
    idle: ... ScrollUpdate, ScrollEnd, ScrollBegin (first momentum, with a delta) ...

So each ScrollUpdate is held until the next event shows what it was: another
ScrollUpdate or a ScrollEnd means the fingers made it, a ScrollMomentum means
it was the first momentum event. A ScrollBegin's own delta is never used.
"""

import math
from contextlib import contextmanager

from PySide6.QtCore import Qt

P = Qt.ScrollPhase

# angleDelta units per mouse wheel notch, and per section
NOTCH = 120
# pixels of trackpad finger travel per section (the same as one notch on macOS,
# where Qt reports 2 angleDelta units per pixel)
STEP_PX = 60
# a swipe that lifts with no step yet but at least this much of one still
# moves one section, so a short flick is never lost
FLICK_FRACTION = 0.5

# zoom per mouse wheel notch
ZOOM_IN_PER_STEP = 1.1
ZOOM_OUT_PER_STEP = 0.9


def scroll_units(event) -> float:
    """The vertical scroll of one event in notches (1.0 = one section).

    Trackpads (events with a scroll phase) are measured in pixels, so the
    feel does not depend on how a platform scales `angleDelta`: Wayland
    reports 12 units per pixel, macOS 2. Wheels have no phase and use
    `angleDelta`; their `pixelDelta` is a guess on macOS and null elsewhere.
    """
    if event.phase() != P.NoScrollPhase and event.pixelDelta().y():
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

    def __init__(self):
        self.total = 0.0  # leftover scroll toward the next section, in notches
        self.held = None  # the last ScrollUpdate, until the next event says what it was
        self.fingers_down = False
        self.stepped = False  # this gesture has moved a section already
        self.lifted = False  # the event just fed ended the finger part of a gesture
        self._moving = False

    def reset(self):
        """Drop the leftover scroll."""
        self.total = 0.0

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

    def feed(self, event) -> float:
        """The scroll in notches that the fingers or the wheel made, known now.

        Sets `lifted` when this event shows the fingers have left the
        trackpad. Momentum, and a ScrollBegin's delta, give nothing.
        """
        phase = event.phase()
        self.lifted = False
        if phase == P.NoScrollPhase:
            return scroll_units(event)

        released = 0.0
        if phase == P.ScrollMomentum:
            # a held update right before momentum was the first momentum event
            self.held = None
        elif self.held is not None:
            released = self.held
            self.held = None

        if phase == P.ScrollBegin:
            # a new gesture; Qt sends begin twice, and the idle order's first
            # momentum event comes as a ScrollBegin with a delta
            self.fingers_down = True
            self.stepped = False
            self.reset()
        elif phase == P.ScrollUpdate:
            self.held = scroll_units(event)
        elif self.fingers_down:  # the first ScrollMomentum or ScrollEnd
            self.fingers_down = False
            self.lifted = True
        return released

    def step(self, event) -> int:
        """Sections to move for one wheel event: positive up, negative down."""
        units = self.feed(event)
        # reversing direction drops what was left over the other way
        if units and self.total and (units > 0) != (self.total > 0):
            self.reset()
        self.total += units
        # whole notches, toward zero; the nudge keeps ten 0.1s from being 0.999...
        steps = int(self.total + math.copysign(1e-9, self.total))
        self.total -= steps
        if steps:
            self.stepped = True
        if self.lifted:
            if not self.stepped and abs(self.total) >= FLICK_FRACTION:
                steps = 1 if self.total > 0 else -1
            self.reset()
        return steps

    def zoom(self, event) -> float:
        """The zoom factor for one wheel event, in proportion to its scroll."""
        return zoom_factor(self.feed(event))
