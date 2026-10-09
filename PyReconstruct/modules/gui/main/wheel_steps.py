"""Turn wheel events into whole section steps and zoom factors.

A mouse wheel sends one event per notch, 120 units of `angleDelta`. A macOS
trackpad sends a stream of small events instead: Qt reports 2 units per pixel
of scroll, with phases ScrollBegin, ScrollUpdate and ScrollEnd, then a run of
ScrollMomentum events after the fingers lift. Moving one section per event made
a single two-finger swipe run through dozens of sections.

`WheelSteps` adds the deltas up and moves one section per 120 units, so a mouse
notch is still exactly one section and a trackpad moves one section per 60
pixels of scroll. Momentum events are ignored, so the series stops when the
fingers lift.
"""

import math

from PySide6.QtCore import Qt

# angleDelta units per section: one mouse wheel notch, 60 pixels on a trackpad
WHEEL_STEP = 120

# zoom per mouse wheel notch
ZOOM_IN_PER_STEP = 1.1
ZOOM_OUT_PER_STEP = 0.9


def is_momentum(event) -> bool:
    """True for the inertia events macOS sends after the fingers lift."""
    return event.phase() == Qt.ScrollPhase.ScrollMomentum


def zoom_step(event) -> float:
    """The zoom factor for one wheel event, in proportion to its size.

    A mouse notch gives exactly 1.1 or 0.9, as before; a trackpad event
    gives the matching fraction of that.
    """
    dy = event.angleDelta().y()
    if dy > 0:
        return ZOOM_IN_PER_STEP ** (dy / WHEEL_STEP)
    if dy < 0:
        return ZOOM_OUT_PER_STEP ** (-dy / WHEEL_STEP)
    return 1.0


class WheelSteps:
    """Adds up vertical wheel deltas and hands out whole section steps."""

    def __init__(self):
        self.total = 0
        self.section = None

    def reset(self):
        self.total = 0

    def step(self, event, section) -> int:
        """Return +1 (up), -1 (down) or 0 for one wheel event.

            Params:
                event (QWheelEvent): the wheel event
                section (int): the section on screen now
        """
        phase = event.phase()
        if phase == Qt.ScrollPhase.ScrollMomentum:
            return 0
        # a new gesture, or a section change from somewhere else, starts over
        if phase == Qt.ScrollPhase.ScrollBegin or section != self.section:
            self.reset()
        self.section = section

        dy = event.angleDelta().y()
        # reversing direction drops what was left over the other way
        if dy and self.total and (dy > 0) != (self.total > 0):
            self.reset()
        self.total += dy

        steps = 0
        if abs(self.total) >= WHEEL_STEP:
            # at most one section per event, like a single notch
            steps = 1 if self.total > 0 else -1
            self.total = math.fmod(self.total, WHEEL_STEP)

        if phase == Qt.ScrollPhase.ScrollEnd:
            self.reset()
        return steps
