"""Read the macOS scroll event behind a QWheelEvent, without pyobjc.

Qt does not say which wheel events are trackpad momentum: it hands the first
momentum event on as a ScrollUpdate or a ScrollBegin (qnsview_mouse.mm,
`scrollWheel:`). AppKit knows. While Qt delivers a wheel event, the NSEvent it
came from is `[NSApp currentEvent]`, and its `momentumPhase` is the truth.

This reads that through the Objective-C runtime with ctypes, and only trusts
it when it is a scroll event with the same timestamp Qt gave the QWheelEvent.
Anything else, any error, or any other platform gives None, and the caller
goes by Qt's phases alone.
"""

import ctypes
import sys
from typing import NamedTuple, Optional

# NSEventPhase bits, for both `phase` and `momentumPhase`
BEGAN = 1
STATIONARY = 2
CHANGED = 4
ENDED = 8
CANCELLED = 16
MAY_BEGIN = 32

SCROLL_WHEEL = 22  # NSEventTypeScrollWheel


class NativeScroll(NamedTuple):
    phase: int  # the fingers' phase; 0 for momentum and plain wheels
    momentum: int  # 0 while the fingers drive the scroll
    delta_y: float  # scrollingDeltaY, in points for a trackpad


class _Runtime:
    """The few Objective-C calls needed, bound once."""

    def __init__(self):
        lib = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        send = ctypes.cast(lib.objc_msgSend, ctypes.c_void_p).value
        args = (ctypes.c_void_p, ctypes.c_void_p)
        self.send_id = ctypes.CFUNCTYPE(ctypes.c_void_p, *args)(send)
        self.send_uint = ctypes.CFUNCTYPE(ctypes.c_ulong, *args)(send)
        self.send_double = ctypes.CFUNCTYPE(ctypes.c_double, *args)(send)
        self.app_class = lib.objc_getClass(b"NSApplication")
        if not self.app_class:
            raise OSError("AppKit is not loaded")
        sel = lib.sel_registerName
        self.shared = sel(b"sharedApplication")
        self.current = sel(b"currentEvent")
        self.type = sel(b"type")
        self.timestamp = sel(b"timestamp")
        self.phase = sel(b"phase")
        self.momentum = sel(b"momentumPhase")
        self.delta_y = sel(b"scrollingDeltaY")

    def read(self, timestamp: int) -> Optional[NativeScroll]:
        app = self.send_id(self.app_class, self.shared)
        event = self.send_id(app, self.current) if app else None
        if not event:
            return None
        # `phase` and the rest raise for other event types; check first
        if self.send_uint(event, self.type) != SCROLL_WHEEL:
            return None
        # Qt's timestamp is the NSEvent's, in whole milliseconds
        if int(self.send_double(event, self.timestamp) * 1000) != timestamp:
            return None
        return NativeScroll(
            self.send_uint(event, self.phase),
            self.send_uint(event, self.momentum),
            self.send_double(event, self.delta_y),
        )


_runtime: Optional[_Runtime] = None
_failed = sys.platform != "darwin"


def read(event) -> Optional[NativeScroll]:
    """The NSEvent a QWheelEvent came from, or None if it cannot be known."""
    global _runtime, _failed
    if _failed:
        return None
    try:
        if _runtime is None:
            _runtime = _Runtime()
        return _runtime.read(event.timestamp())
    except Exception:
        # never again this run; Qt's phases still work
        _failed = True
        return None
