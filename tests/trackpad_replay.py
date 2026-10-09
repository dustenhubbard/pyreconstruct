"""Replay macOS trackpad swipes into a Qt window the way Qt 6.9.3 maps them.

A swipe is written as the native events AppKit hands Qt: (phase, momentum
phase, scrollingDeltaY in points). `qt_events` turns them into the
`QWheelEvent` phases and deltas Qt's cocoa plugin makes of them
(qtbase v6.9.3, src/plugins/platforms/cocoa/qnsview_mouse.mm, `scrollWheel:`):

  * MayBegin and Began become ScrollBegin, or ScrollUpdate once a sequence is
    open; Changed becomes ScrollUpdate.
  * Ended is dropped when the momentum Began event is already queued behind it
    (the app was busy), otherwise it becomes ScrollEnd.
  * The momentum Began event becomes ScrollUpdate when a sequence is open (busy
    order), else ScrollBegin with its delta (idle order). Qt never tags it
    ScrollMomentum. Momentum Changed becomes ScrollMomentum; momentum Ended
    becomes ScrollEnd.
  * pixelDelta is the points, angleDelta twice that.

Each event also keeps the NSEvent it came from, as `native_scroll` reads it
from `[NSApp currentEvent]` on a Mac. `deliver` sends them with
`QTest.wheelEvent`, which goes through `QWindowSystemInterface::handleWheelEvent`
like a real event: a ScrollUpdate with no delta is dropped, and a ScrollBegin
or ScrollEnd with no delta arrives twice. While it does, `NativeEvents` stands
in for `[NSApp currentEvent]`.
"""

from typing import NamedTuple

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest

P = Qt.ScrollPhase

# NSEvent phases; only which one matters here, not the AppKit bit values
NONE, MAY_BEGIN, BEGAN, CHANGED, ENDED, CANCELLED = (
    "none", "mayBegin", "began", "changed", "ended", "cancelled",
)
# their NSEventPhase bits, as `phase` and `momentumPhase` return them
NS_PHASE = {NONE: 0, BEGAN: 1, CHANGED: 4, ENDED: 8, CANCELLED: 16, MAY_BEGIN: 32}


class Native(NamedTuple):
    """The NSEvent behind a wheel event, shaped like `native_scroll.NativeScroll`."""
    phase: int
    momentum: int
    delta_y: float


class NativeEvents:
    """Stands in for `native_scroll.read`: the NSEvent of the event being sent."""

    def __init__(self):
        self.current = None

    def __call__(self, event):
        return self.current


def native_swipe(drag, momentum=()):
    """A two-finger swipe: fingers down, `drag` deltas, lift, `momentum` deltas.

    `drag` and `momentum` are scrollingDeltaY values in points, one per event.
    """
    events = [(MAY_BEGIN, NONE, 0)]
    events += [(BEGAN if i == 0 else CHANGED, NONE, dy) for i, dy in enumerate(drag)]
    events.append((ENDED, NONE, 0))
    if momentum:
        events.append((NONE, BEGAN, momentum[0]))
        events += [(NONE, CHANGED, dy) for dy in momentum[1:]]
        events.append((NONE, ENDED, 0))
    return events


def qt_events(native, busy):
    """(phase, pixelDelta.y, angleDelta.y, Native) for each native event Qt passes on.

    `busy` says whether the momentum Began event was already queued when Qt
    looked behind the finger Ended event.
    """
    out = []
    scrolling = False
    for i, (phase, momentum, dy) in enumerate(native):
        if phase in (MAY_BEGIN, BEGAN):
            qt_phase = P.ScrollUpdate if scrolling else P.ScrollBegin
            scrolling = True
        elif phase == CHANGED:
            qt_phase = P.ScrollUpdate
        elif phase == ENDED:
            following = native[i + 1] if i + 1 < len(native) else None
            if busy and following and following[1] == BEGAN:
                continue  # dropped, even with a delta
            qt_phase = P.ScrollEnd
            scrolling = False
        elif momentum == BEGAN:
            qt_phase = P.ScrollUpdate if scrolling else P.ScrollBegin
            scrolling = True
        elif momentum == CHANGED:
            qt_phase = P.ScrollMomentum
        else:  # Cancelled, or momentum Ended or Cancelled
            qt_phase = P.ScrollEnd
            scrolling = False
            dy = 0 if phase == CANCELLED else dy
        ns = Native(NS_PHASE[phase], NS_PHASE[momentum], dy)
        out.append((qt_phase, int(dy), int(dy * 2), ns))
    return out


def is_finger(event):
    """The fingers made this event: it has a native phase and no momentum."""
    return len(event) > 3 and event[3].momentum == 0


def last_finger(events):
    """The index of the last event the fingers made; what comes after is after the lift."""
    return max(i for i, e in enumerate(events) if is_finger(e))


def deliver(window, pos, events, modifiers=Qt.NoModifier, after=None, native=None):
    """Send (phase, pixel, angle[, Native]) events to a QWindow at `pos`.

    `native`, a `NativeEvents`, is set to each event's Native while it is
    sent. `after(phase)` runs after each event is sent.
    """
    for phase, pixel, angle, *ns in events:
        if native is not None:
            native.current = ns[0] if ns else None
        QTest.wheelEvent(
            window, QPointF(pos), QPoint(0, angle), QPoint(0, pixel),
            modifiers, phase,
        )
        if after is not None:
            after(phase)
    if native is not None:
        native.current = None


def notch(count=1, pixel=0):
    """A mouse wheel event of `count` notches; `pixel` as macOS reports it."""
    return (P.NoScrollPhase, pixel, 120 * count)
