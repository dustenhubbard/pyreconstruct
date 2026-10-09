"""Replay synthetic trackpad swipes into a running PyReconstruct (macOS only).

Opens a copy of the test fixture series, puts the pointer over the field, and
posts CGEvent scroll events with the trackpad phase fields set, so they go
through AppKit and Qt's cocoa plugin like a real two-finger swipe. Prints one
row per gesture: finger travel in points, sections moved, sections a
finger-only replay of the same swipe gives, the order Qt delivered the first
momentum event in, how many sections moved after the last event the fingers
made (the first momentum event counts as after, whatever Qt calls it), and how
many delivered events `native_scroll` matched to their NSEvent.

Not shipped and not run by the suite. pyobjc is not a dependency; run with:

    uv run --frozen --no-default-groups --extra test \\
        --with pyobjc-framework-Quartz python dev/trackpad_e2e.py [mode] [repeats]

    tap     post through the session event tap, 8 ms apart while the fingers
            move and 16 ms apart after (default). Moves the real pointer.
    burst   the same, back to back, so the system coalesces events.
    direct  call scrollWheel: on the window's view; always Qt's idle order,
            and no NSEvent to read, so Qt's phases alone.
    tap-phases, burst-phases
            tap or burst with the NSEvent reading turned off in the window,
            to measure what Qt's phases alone let through.

`repeats` runs the gesture list that many times (default 1).

Settings go to a throwaway location (tests/qsettings_isolation.py).
"""

import faulthandler
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

import qsettings_isolation  # noqa: E402,F401  (redirects QSettings on import)

import AppKit  # noqa: E402
import objc  # noqa: E402
import Quartz  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from trackpad_replay import (  # noqa: E402
    BEGAN, CHANGED, ENDED, MAY_BEGIN, NONE, native_swipe, qt_events,
)
from PyReconstruct.modules.gui.main import native_scroll  # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else "tap"
PHASES_ONLY = MODE.endswith("-phases")
MODE = MODE.removesuffix("-phases")
REPEATS = int(sys.argv[2]) if len(sys.argv) > 2 else 1
START = 100
FIXTURE = ROOT / "dev" / "assets" / "checker" / "files" / "class_series.jser"

# IOHID values for the CGEvent phase fields
SCROLL_PHASE = {NONE: 0, BEGAN: 1, CHANGED: 2, ENDED: 4, MAY_BEGIN: 128}
MOMENTUM_PHASE = {NONE: 0, BEGAN: 1, CHANGED: 2, ENDED: 3}

# (name, finger deltas in points per event, momentum deltas after the lift)
GESTURES = [
    ("slow drag, slow lift", [4] * 40, []),
    ("short swipe", [2, 6, 10, 14, 14, 10, 6, 2], [12, 10, 8, 6, 4, 3, 2, 1]),
    ("medium swipe", [4, 10, 18, 24, 24, 20, 14, 8], [30, 26, 22, 18, 14, 10, 7, 4, 2, 1]),
    ("long swipe", [6, 16, 30, 44, 52, 52, 44, 30, 16],
     [60, 54, 48, 42, 36, 30, 24, 18, 13, 9, 6, 4, 2, 1]),
    ("very long drag", [8] * 15 + [20] * 20 + [8] * 15, [16, 12, 8, 4, 2, 1]),
    ("flick", [8, 24, 18], [40, 34, 28, 22, 16, 10, 6, 3, 1]),
    ("tiny flick", [6, 10], [12, 8, 4, 2, 1]),
    ("down then back up", [-8] * 10 + [8] * 12, [10, 8, 6, 4, 2, 1]),
]


def make_event(phase, momentum, dy):
    ev = Quartz.CGEventCreateScrollWheelEvent2(
        None, Quartz.kCGScrollEventUnitPixel, 1, int(dy), 0, 0)
    Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGScrollWheelEventIsContinuous, 1)
    Quartz.CGEventSetDoubleValueField(ev, Quartz.kCGScrollWheelEventPointDeltaAxis1, dy)
    Quartz.CGEventSetDoubleValueField(ev, Quartz.kCGScrollWheelEventFixedPtDeltaAxis1, dy / 10.0)
    Quartz.CGEventSetIntegerValueField(
        ev, Quartz.kCGScrollWheelEventScrollPhase, SCROLL_PHASE[phase])
    Quartz.CGEventSetIntegerValueField(
        ev, Quartz.kCGScrollWheelEventMomentumPhase, MOMENTUM_PHASE[momentum])
    return ev


def make_notch(lines):
    return Quartz.CGEventCreateScrollWheelEvent2(
        None, Quartz.kCGScrollEventUnitLine, 1, lines, 0, 0)


def finger_only(drag):
    """Sections the stepper gives for the finger part alone, no window."""
    from PyReconstruct.modules.gui.main.wheel_steps import WheelSteps

    current = None
    steps = WheelSteps(read_native=lambda event: current)
    moved = 0
    for phase, pixel, angle, current in qt_events(native_swipe(drag), busy=False):
        moved += steps.step(QWheelEvent(
            QPointF(), QPointF(), QPoint(0, pixel), QPoint(0, angle),
            Qt.NoButton, Qt.NoModifier, phase, False))
    return moved


def last_finger(log):
    """The index of the last delivered event the fingers made.

    With the NSEvent read, the first event with a momentum phase is after the
    lift. Without it (direct mode, always Qt's idle order), the first
    ScrollMomentum or ScrollBegin with a delta is.
    """
    for i, row in enumerate(log):
        native = row[5]
        if native is not None:
            after = native.momentum != 0
        else:
            after = row[0] == Qt.ScrollPhase.ScrollMomentum or (
                row[0] == Qt.ScrollPhase.ScrollBegin and row[1])
        if after:
            return i - 1
    return len(log) - 1


def order_seen(log):
    """How Qt delivered the first momentum event: busy, idle or none."""
    phases = [(row[0], row[1]) for row in log]
    for i, (phase, pixel) in enumerate(phases):
        if phase == Qt.ScrollPhase.ScrollMomentum:
            before = phases[i - 1] if i else None
            if before and before[0] == Qt.ScrollPhase.ScrollUpdate:
                return "busy"
            if before and before[0] == Qt.ScrollPhase.ScrollBegin and before[1]:
                return "idle"
            return "?"
    return "none"


def main():
    # a stuck run prints where it is stuck and exits
    faulthandler.dump_traceback_later(240, exit=True)
    os.environ.pop("QT_QPA_PLATFORM", None)
    work = Path(tempfile.mkdtemp(prefix="trackpad-e2e-"))
    jser = work / "series.jser"
    shutil.copy(FIXTURE, jser)

    from PyReconstruct.modules.gui.dialog.whats_new import APP, ORG, current_version_str
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY
    from PyReconstruct.modules.gui.main import main_window as mw_module
    from PySide6.QtWidgets import QMessageBox

    # nobody answers prompts here: the fixture ships no images or series code
    mw_module.user_is_present = lambda: False
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
    for name in ("notify", "notifyConfirm"):
        setattr(mw_module, name, lambda *a, **k: print("dialog:", a[:1]) or False)

    log = []
    original = MainWindow.wheelEvent

    def logged(self, event):
        native = native_scroll.read(event)  # the reading the window gets
        original(self, event)
        if os.environ.get("TRACKPAD_E2E_DEBUG"):
            print(event.phase().name, event.pixelDelta().y(), event.angleDelta().y(), event.position(), self.field.geometry(), QApplication.keyboardModifiers())
        log.append((event.phase(), event.pixelDelta().y(), event.angleDelta().y(),
                    self.series.current_section, event.timestamp(), native))

    MainWindow.wheelEvent = logged

    app = QApplication.instance() or QApplication(sys.argv)
    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
    mw = MainWindow(str(jser))
    mw._captureListLayout = lambda: None
    if PHASES_ONLY:
        mw.wheel_steps.read_native = lambda event: None
    mw.show()
    mw.raise_()
    mw.activateWindow()
    AppKit.NSApp.activateIgnoringOtherApps_(True)

    rows = []
    queue = []
    for _ in range(REPEATS):
        for name, drag, momentum in GESTURES:
            queue.append(("swipe", name, drag, momentum))
    queue.append(("notch", "mouse wheel, 3 notches up", None, None))

    def field_center_global():
        return mw.field.mapToGlobal(mw.field.rect().center())

    def pointer_is_ours():
        """The window a mouse event at the field center goes to is this one."""
        here = AppKit.NSEvent.mouseLocation()  # the pointer was just warped there
        number = AppKit.NSWindow.windowNumberAtPoint_belowWindowWithWindowNumber_(here, 0)
        view = objc.objc_object(c_void_p=int(mw.winId()))
        return number == view.window().windowNumber()

    def post(events, spacings):
        c = field_center_global()

        def located(ev):
            e = ev()
            Quartz.CGEventSetLocation(e, Quartz.CGPointMake(c.x(), c.y()))
            return e

        if MODE == "direct":
            # an NSEvent with no window has no usable location; with a NaN one
            # Qt reads the pointer, which is over the field
            view = objc.objc_object(c_void_p=int(mw.winId()))
            nowhere = Quartz.CGPointMake(float("nan"), float("nan"))
            for ev in events:
                e = ev()
                Quartz.CGEventSetLocation(e, nowhere)
                view.scrollWheel_(AppKit.NSEvent.eventWithCGEvent_(e))
            return None

        def run():
            for ev, gap in zip(events, spacings):
                Quartz.CGEventPost(Quartz.kCGSessionEventTap, located(ev))
                if MODE == "tap":
                    time.sleep(gap)
        thread = threading.Thread(target=run)
        thread.start()
        return thread

    def next_gesture():
        if not queue:
            report()
            return
        kind, name, drag, momentum = queue.pop(0)
        mw.changeSection(START)
        log.clear()
        c = field_center_global()
        Quartz.CGWarpMouseCursorPosition(Quartz.CGPointMake(c.x(), c.y()))
        if MODE != "direct" and not pointer_is_ours():
            print("another window is over the field; stopping")
            app.quit()
            return
        if kind == "notch":
            events = [lambda: make_notch(1)] * 3
            spacings = [0.05] * 3
        else:
            native = native_swipe(drag, momentum)
            events = [lambda n=n: make_event(*n) for n in native]
            spacings = [0.016 if n[1] != NONE else 0.008 for n in native]
        post(events, spacings)

        def finish():
            moved = mw.series.current_section - START
            matched = f"{sum(r[5] is not None for r in log)}/{len(log)}"
            if kind == "notch":
                rows.append((name, "", moved, 3, "", "", matched))
            else:
                lift = last_finger(log)
                after = mw.series.current_section - (log[lift][3] if lift >= 0 else START)
                rows.append((name, sum(abs(d) for d in drag), moved, finger_only(drag),
                             order_seen(log), after, matched))
            QTimer.singleShot(400, next_gesture)

        QTimer.singleShot(1500, finish)

    def report():
        print(f"mode: {MODE}{' (phases only)' if PHASES_ONLY else ''}, repeats: {REPEATS}")
        print(f"{'gesture':28} {'travel pt':>9} {'moved':>6} {'fingers':>8} {'order':>6}"
              f" {'after lift':>10} {'NSEvent':>8}")
        for name, travel, moved, ideal, order, after, matched in rows:
            print(f"{name:28} {travel!s:>9} {moved:>6} {ideal:>8} {order:>6} {after!s:>10}"
                  f" {matched:>8}")
        swipes = [r for r in rows if r[1] != ""]
        print(f"swipes: {len(swipes)}, moved after the lift: "
              f"{sum(1 for r in swipes if r[5])}, off the finger-only count: "
              f"{sum(1 for r in swipes if r[2] != r[3])}")
        mw.series.modified = False
        mw.close()
        app.quit()

    QTimer.singleShot(1500, next_gesture)
    app.exec()
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
