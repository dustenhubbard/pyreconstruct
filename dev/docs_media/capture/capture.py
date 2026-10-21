"""Shoot the User Guide stills from the real app, in one command.

    uv run --no-default-groups --extra test python dev/docs_media/capture/capture.py --out <folder>

What this makes, in <folder>:

  * one PNG per shot in SHOTS, at the screen's native pixel density (2x on a
    Retina Mac), with labels drawn on the ones that need them;
  * contact-sheet.png, every shot on one page with its file name;
  * targets.json, the native-pixel click and drag points of the short flows in
    FLOWS, for the video renderer (dev/docs_media/video/);
  * verification.json, the size and sha256 of every file, the pinned inputs,
    and the settings tripwire read before and after the run.

How it shoots. Each frame is `QWidget.grab()` of the live window, not a
screen capture: it needs no Screen Recording permission, has no desktop,
cursor or title bar in it (the title bar is where a series path would show),
and gives the same pixels on every run. The window is a real Cocoa window with
the platform's own style and fonts; `QT_QPA_PLATFORM=offscreen` is never used,
since that look is not what users see.

What is pinned, so a rerun gives the same frames: the fixture series
(dev/assets/checker/files/shapes1.jser, copied to a temporary folder), the
window size (WINDOW_SIZE logical pixels), the theme (the app default, light;
the run stops if macOS is in dark mode), the username ("docs"), and an empty
settings store. A run on a different screen density stops rather than give
frames of a different size.

His real settings are never touched. Before anything imports the app, every
`QSettings` is redirected to a throwaway folder by tests/qsettings_isolation.py,
the same mechanism the test suite runs under, and the run stops if the
redirect does not hold. The tripwire (CODING_STANDARDS.md, "His real
settings") is read before and after and written to verification.json; the run
exits non-zero if it moved.

Fixture series only. No lab data, no file dialog, no recent-files list.
"""

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO / "dev" / "assets" / "checker" / "files"
FIXTURE = "shapes1.jser"

# logical pixels; 2240 x 1520 native on a 2x screen. Tall enough that the tool
# column (twelve buttons) clears the section buttons; below about 700 the two
# overlap. That is taller than the mini's 1280 x 800 screen leaves a titled
# window, so the window is frameless (macOS does not clamp those), and may run
# past the bottom of the screen: grab() draws the whole widget regardless.
WINDOW_SIZE = (1120, 760)
WINDOW_POS = (40, 40)
# where the pointer waits, beside the window, so no hover state is drawn
POINTER_PARK = (1240, 400)
EXPECTED_DPR = 2.0
USERNAME = "docs"
SERIES_CODE = "shapes1"

REAL_DOMAIN = "com.khlab.PyReconstruct"
REAL_PLIST = Path.home() / "Library" / "Preferences" / f"{REAL_DOMAIN}.plist"

# label style, in native pixels at 2x
LABEL_BG = "#1f2937"
LABEL_FG = "#ffffff"
ACCENT = "#f59e0b"


# --- his real settings ------------------------------------------------------


def tripwire():
    """The three tripwire values, measured here, never taken from a brief."""
    digest = hashlib.sha256(REAL_PLIST.read_bytes()).hexdigest() if REAL_PLIST.exists() else None
    exported = subprocess.run(
        ["defaults", "export", REAL_DOMAIN, "-"], capture_output=True, check=False
    )
    keys = len(plistlib.loads(exported.stdout)) if exported.returncode == 0 else None
    user = subprocess.run(
        ["defaults", "read", REAL_DOMAIN, "username"], capture_output=True, text=True, check=False
    )
    return {
        "plist_sha256": digest,
        "top_level_keys": keys,
        "username": user.stdout.strip() if user.returncode == 0 else None,
    }


def isolate_settings():
    """Redirect every QSettings before the app is imported; stop if it fails."""
    os.environ["PYRECON_HYBRID_STORE"] = "0"  # no local store under ~/Library
    sys.path.insert(0, str(REPO / "tests"))
    import qsettings_isolation  # noqa: F401  (rebinds QSettings on import)

    if not qsettings_isolation.installed:
        sys.exit("QSettings isolation did not install; refusing to run.")
    qsettings_isolation.verify_isolated()
    return qsettings_isolation


# --- frames -----------------------------------------------------------------


def settle(app, seconds=0.4):
    """Let paints, layouts and image loads finish."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


def grab(widget):
    """The widget's own pixels at native density, as a QImage."""
    from PySide6.QtGui import QImage

    if not widget.isActiveWindow():
        sys.exit(f"{widget.windowTitle()!r} is not the active window; its frame would "
                 "be drawn inactive. Is someone using the Mac?")

    image = widget.grab().toImage().convertToFormat(QImage.Format_RGB32)
    if abs(image.devicePixelRatio() - EXPECTED_DPR) > 1e-6:
        sys.exit(
            f"Screen density is {image.devicePixelRatio()}x, not {EXPECTED_DPR}x; "
            "the frames would not match a previous run."
        )
    image.setDevicePixelRatio(1.0)  # from here on, everything is native pixels
    return image


def native_rect(widget, window):
    """A child widget's rectangle in the window's native pixels."""
    from PySide6.QtCore import QPoint, QRect

    top_left = widget.mapTo(window, QPoint(0, 0))
    d = EXPECTED_DPR
    return QRect(
        round(top_left.x() * d), round(top_left.y() * d),
        round(widget.width() * d), round(widget.height() * d),
    )


def native_point(widget, window, x=None, y=None):
    """A point in a child widget (its center by default) in native pixels."""
    from PySide6.QtCore import QPoint

    x = widget.width() / 2 if x is None else x
    y = widget.height() / 2 if y is None else y
    origin = widget.mapTo(window, QPoint(0, 0))
    return [round((origin.x() + x) * EXPECTED_DPR), round((origin.y() + y) * EXPECTED_DPR)]


def union(rects):
    out = rects[0]
    for r in rects[1:]:
        out = out.united(r)
    return out


def rect_list(rect):
    return [rect.left(), rect.top(), rect.left() + rect.width(), rect.top() + rect.height()]


def draw_label(painter, text, anchor, side, target=None):
    """One callout: a dark rounded box with white text beside `anchor`.

    `side` puts the box left, right, above or below the anchor point; a line
    joins the box to `target` (the anchor by default).
    """
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFontMetricsF, QPen

    metrics = QFontMetricsF(painter.font())
    pad_x, pad_y, gap = 16, 10, 22
    w = metrics.horizontalAdvance(text) + 2 * pad_x
    h = metrics.height() + 2 * pad_y
    ax, ay = anchor
    if side == "left":
        box = QRectF(ax - gap - w, ay - h / 2, w, h)
        joint = QPointF(box.right(), ay)
    elif side == "right":
        box = QRectF(ax + gap, ay - h / 2, w, h)
        joint = QPointF(box.left(), ay)
    elif side == "above":
        box = QRectF(ax - w / 2, ay - gap - h, w, h)
        joint = QPointF(ax, box.bottom())
    else:
        box = QRectF(ax - w / 2, ay + gap, w, h)
        joint = QPointF(ax, box.top())
    tx, ty = target or anchor
    painter.setPen(QPen(QColor(ACCENT), 4))
    painter.drawLine(joint, QPointF(tx, ty))
    painter.setBrush(QColor(ACCENT))
    painter.drawEllipse(QPointF(tx, ty), 7, 7)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(LABEL_BG))
    painter.drawRoundedRect(box, 10, 10)
    painter.setPen(QColor(LABEL_FG))
    painter.drawText(box, Qt.AlignCenter, text)


def outline(painter, rect, margin=8):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPen

    painter.setPen(QPen(QColor(ACCENT), 5))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect.adjusted(-margin, -margin, margin, margin), 12, 12)


def label_painter(image):
    from PySide6.QtGui import QFont, QPainter

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    font = QFont(painter.font())
    font.setPixelSize(26)
    font.setBold(True)
    painter.setFont(font)
    return painter


# --- the app ----------------------------------------------------------------


def build_window(app, jser):
    """A MainWindow on `jser` (None: the welcome series), sized and settled."""
    from PyReconstruct.modules.gui.main import MainWindow

    from PySide6.QtCore import Qt

    window = MainWindow(jser)
    # nothing may pop up over a frame: no update check, no What's new
    window.update_check_timer.stop()
    window.whats_new_timer.stop()
    # Frameless, so macOS lets it be taller than the screen. Not
    # WindowTransparentForInput: a window with it is never active, and an
    # inactive window draws its sliders without their track.
    window.setWindowFlag(Qt.FramelessWindowHint, True)
    window.showNormal()
    window.resize(*WINDOW_SIZE)
    window.move(*WINDOW_POS)
    window.raise_()
    window.activateWindow()
    settle(app, 1.0)
    if (window.width(), window.height()) != WINDOW_SIZE:
        sys.exit(f"Window is {window.width()} x {window.height()}, not {WINDOW_SIZE}.")
    return window


def close_window(app, window):
    window.series.modified = False  # a fixture copy: never prompt to save
    window.close()
    window.deleteLater()
    settle(app, 0.3)


_expecting_modal = False


def start_watchdog(app):
    """Stop the run if a dialog nobody asked for stays open: it would hang it.

    A progress bar ("Opening shapes1...") is modal too, and closes by itself,
    so it is let be; anything else open for two seconds stops the run.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLabel, QProgressBar

    seen = {"dialog": None, "ticks": 0}

    def check():
        dialog = app.activeModalWidget()
        if dialog is None or _expecting_modal or dialog.findChildren(QProgressBar):
            seen.update(dialog=None, ticks=0)
            return
        if dialog is not seen["dialog"]:
            seen.update(dialog=dialog, ticks=0)
        seen["ticks"] += 1
        if seen["ticks"] >= 8:
            words = " / ".join(w.text() for w in dialog.findChildren(QLabel) if w.text())
            print(f"Unexpected dialog {dialog.windowTitle()!r}: {words[:300]}", file=sys.stderr)
            os._exit(3)

    timer = QTimer(app)
    timer.timeout.connect(check)
    timer.start(250)
    return timer


def grab_modal(app, trigger):
    """Run `trigger`, which opens a modal dialog; grab the dialog and cancel it."""
    from PySide6.QtCore import QTimer

    global _expecting_modal
    found = {}

    def poll():
        dialog = app.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(50, poll)
            return
        settle(app, 0.5)
        found["image"] = grab(dialog)
        dialog.reject()

    _expecting_modal = True
    QTimer.singleShot(0, poll)
    try:
        trigger()
    finally:
        _expecting_modal = False
    if "image" not in found:
        sys.exit("The dialog did not open.")
    return found["image"]


def field_event(field, kind, x, y, buttons):
    """Send one mouse event to the field, in its logical coordinates."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    local = QPointF(x, y)
    world = QPointF(field.mapToGlobal(local.toPoint()))
    types = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove,
             "release": QEvent.MouseButtonRelease}
    button = Qt.NoButton if kind == "move" else Qt.LeftButton
    event = QMouseEvent(types[kind], local, local, world, button, buttons, Qt.NoModifier)
    QApplication.sendEvent(field, event)


def blob(cx, cy, rx, ry, n=48):
    """A closed freehand-looking path: an ellipse with a slight wobble."""
    import math

    points = []
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        wobble = 1 + 0.06 * math.sin(3 * t)
        points.append((cx + rx * wobble * math.cos(t), cy + ry * wobble * math.sin(t)))
    return points


# --- the shot list ----------------------------------------------------------


def shoot(out, app):
    """Make every frame; return (shots, flows)."""
    from PySide6.QtCore import QRect, QSettings
    from PySide6.QtGui import QColor, QImage

    from PyReconstruct.modules.gui.dialog.whats_new import APP, ORG, current_version_str
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    settings = QSettings(ORG, APP)
    settings.setValue(WHATSNEW_KEY, current_version_str())
    settings.setValue("username", USERNAME)

    shots = []

    def save(image, name, heading, purpose):
        path = out / f"{name}.png"
        if not image.save(str(path), "PNG"):
            sys.exit(f"Could not write {path}")
        shots.append({"file": path.name, "heading": heading, "purpose": purpose,
                      "size": [image.width(), image.height()]})

    # 4. On first launch: the welcome series
    window = build_window(app, None)
    save(grab(window), "04-welcome-series", "4. On first launch",
         "The welcome series PyReconstruct opens with no file.")

    # 4. Creating a new series from images: the calibration prompt. The images
    # and the name are passed in, so no file dialog opens; Cancel ends it.
    images = sorted(str(p) for p in FIXTURE_DIR.glob("shapes_*.tif"))
    dialog = grab_modal(app, lambda: window.newSeries(image_locations=images, series_name="shapes"))
    save(dialog, "04-new-series-calibration", "4. Creating a new series from images",
         "The image calibration prompt (um/px, default 0.00254).")
    close_window(app, window)

    # the fixture, copied so the hidden working folder lands in the temp dir
    # The fixture has no series code, so opening it asks for one; the copy
    # gets one, and the fixture in the repo is left as it is.
    series_dir = Path(tempfile.mkdtemp(prefix="pyrecon-docs-series-"))
    data = json.loads((FIXTURE_DIR / FIXTURE).read_text())
    data["series"]["code"] = SERIES_CODE
    (series_dir / FIXTURE).write_text(json.dumps(data))
    for image in FIXTURE_DIR.glob("shapes_*.tif"):
        shutil.copy(image, series_dir / image.name)

    window = build_window(app, str(series_dir / FIXTURE))
    palette = window.mouse_palette
    field = window.field

    # 4. Opening an existing series; also frame 1 of both flows
    opened = grab(window)
    save(opened, "04-series-open", "4. Opening an existing series",
         "shapes1.jser open on section 0, Pointer tool active.")

    # 5. The main window, labeled
    mode_rect = union([native_rect(b, window) for b, _, _ in palette.mode_buttons.values()])
    trace_widgets = [b for b in palette.palette_buttons if b is not None]
    trace_widgets += list(palette.palette_side_buttons) + [palette.label]
    trace_rect = union([native_rect(w, window) for w in trace_widgets if w.isVisible()])
    inc_rect = union([native_rect(b, window) for b in palette.inc_buttons])
    bc_rect = union([native_rect(w, window) for pair in palette.bc_widgets for w in pair])
    bc_rect.setRight(min(bc_rect.right(), mode_rect.left() - 28))  # off the tool column
    sb_rect = native_rect(palette.sb, window)
    field_rect = native_rect(field, window)

    labeled = opened.copy()
    p = label_painter(labeled)
    for r in (mode_rect, trace_rect, inc_rect, bc_rect, sb_rect):
        outline(p, r)
    draw_label(p, "Tool palette", (mode_rect.left() - 8, mode_rect.top() + 60), "left")
    draw_label(p, "Trace palette", (trace_rect.center().x(), trace_rect.top() - 8), "above")
    draw_label(p, "Section buttons", (inc_rect.left() - 8, inc_rect.center().y()), "left")
    draw_label(p, "Brightness / contrast", (bc_rect.left() - 8, bc_rect.center().y()), "left")
    draw_label(p, "Scale bar", (sb_rect.center().x(), sb_rect.top() - 8), "above")
    draw_label(p, "Field", (field_rect.left() + 120, field_rect.top() + 50), "right",
               target=(field_rect.left() + 60, field_rect.top() + 50))
    p.end()
    save(labeled, "05-main-window-labeled", "5. The main window and navigation",
         "The field and its floating overlays, labeled.")

    # 6. The tool palette: the column alone, on a light panel, each button
    # named by its own tooltip so the names follow the app
    bounds = QRect(0, 0, opened.width(), opened.height())
    column = opened.copy(mode_rect.adjusted(-6, -16, 6, 16).intersected(bounds))
    label_w = 300
    panel = QImage(column.width() + label_w, column.height(), QImage.Format_RGB32)
    panel.fill(QColor("#f3f4f6"))
    p = label_painter(panel)
    p.drawImage(label_w, 0, column)
    shift_x = label_w - (mode_rect.left() - 6)
    shift_y = -(mode_rect.top() - 16)
    for name, (button, _, _) in palette.mode_buttons.items():
        r = native_rect(button, window).translated(shift_x, shift_y)
        draw_label(p, button.toolTip() or name, (r.left() - 10, r.center().y()), "left")
    p.end()
    save(panel, "06-tool-palette-labeled", "6. The tool palette",
         "The tool palette column with each tool's name, as its tooltip gives it.")

    # 6. Closed Trace: the mode and shape dialog its right-click opens
    dialog = grab_modal(app, window.changeTraceMode)
    save(dialog, "06-closed-trace-mode-dialog", "6. Closed Trace (C) and Open Trace (O)",
         "Right-click on the Closed Trace button: mode, shape, merge and smoothing.")

    # flow A: pick Closed Trace, draw a trace
    closed_button = palette.mode_buttons["Closed Trace"][0]
    closed_center = native_point(closed_button, window)
    closed_button.click()
    settle(app, 0.5)
    save(grab(window), "06-closed-trace-selected", "6. Closed Trace (C) and Open Trace (O)",
         "Closed Trace selected in the tool palette.")

    # an empty part of the field, left of center, clear of the fixture's shapes
    path = blob(field.width() * 0.30, field.height() * 0.50, 70, 52)
    field_event(field, "press", *path[0], buttons=_left())
    for x, y in path[1:]:
        field_event(field, "move", x, y, buttons=_left())
        app.processEvents()
    time.sleep(0.6)  # longer than a click, so combo mode keeps the scribble
    field_event(field, "release", *path[-1], buttons=_none())
    settle(app, 0.6)
    save(grab(window), "06-closed-trace-drawn", "6. Closed Trace (C) and Open Trace (O)",
         "A closed trace just drawn with the Closed Trace tool.")
    drag_native = [native_point(field, window, x, y) for x, y in path]

    # flow B: next section with the section button, back on the Pointer
    palette.mode_buttons["Pointer"][0].click()
    settle(app, 0.3)
    up_center = native_point(palette.up_bttn, window)
    palette.up_bttn.click()
    settle(app, 1.2)
    save(grab(window), "05-next-section", "5. Moving between sections",
         "Section 1, after the section button (or Page Up).")

    # 5. Theme: the Dark theme, then back to the default
    window.setTheme("qdark")
    settle(app, 0.8)
    save(grab(window), "05-dark-theme", "5. Theme", "The same window in the Dark theme.")
    window.setTheme("default")
    settle(app, 0.3)
    close_window(app, window)
    shutil.rmtree(series_dir, ignore_errors=True)

    flows = {
        "pick-closed-trace-and-draw": {
            "steps": [
                {"frame": "04-series-open.png", "action": "click", "target": "closed_trace_button"},
                {"frame": "06-closed-trace-selected.png", "action": "drag", "target": "draw_path"},
                {"frame": "06-closed-trace-drawn.png", "action": "hold"},
            ],
        },
        "next-section": {
            "steps": [
                {"frame": "04-series-open.png", "action": "click", "target": "next_section_button"},
                {"frame": "05-next-section.png", "action": "hold"},
            ],
        },
    }
    targets = {
        "closed_trace_button": {"center": closed_center,
                                "bounds": rect_list(native_rect(closed_button, window)),
                                "frame": "04-series-open.png"},
        "draw_path": {"points": drag_native, "frame": "06-closed-trace-selected.png",
                      "note": "left button held from the first point to the last"},
        "next_section_button": {"center": up_center,
                                "frame": "04-series-open.png"},
    }
    return shots, flows, targets


def target_check(out, targets):
    """The flow targets drawn on their frame, to check them by eye."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

    image = QImage(str(out / "06-closed-trace-selected.png"))
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#ef4444"), 5))
    p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in targets["draw_path"]["points"]]))
    for key in ("closed_trace_button", "next_section_button"):
        x, y = targets[key]["center"]
        p.drawEllipse(QPointF(x, y), 22, 22)
        p.drawLine(x - 30, y, x + 30, y)
        p.drawLine(x, y - 30, x, y + 30)
    p.end()
    image.save(str(out / "target-check.png"), "PNG")


def _left():
    from PySide6.QtCore import Qt
    return Qt.LeftButton


def _none():
    from PySide6.QtCore import Qt
    return Qt.NoButton


# --- outputs ----------------------------------------------------------------


def contact_sheet(out, shots):
    """Every shot, scaled into a cell, with its file name under it."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    cols, cell_w, cell_h, caption = 3, 760, 480, 56
    rows = (len(shots) + cols - 1) // cols
    sheet = QImage(cols * cell_w, rows * (cell_h + caption), QImage.Format_RGB32)
    sheet.fill(QColor("#e5e7eb"))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    font = QFont(p.font())
    font.setPixelSize(22)
    p.setFont(font)
    for i, shot in enumerate(shots):
        image = QImage(str(out / shot["file"]))
        thumb = image.scaled(cell_w - 32, cell_h - 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x0 = (i % cols) * cell_w
        y0 = (i // cols) * (cell_h + caption)
        p.drawImage(x0 + (cell_w - thumb.width()) // 2, y0 + 16 + (cell_h - 24 - thumb.height()) // 2, thumb)
        p.setPen(QColor("#111827"))
        p.drawText(QRect(x0, y0 + cell_h, cell_w, caption), Qt.AlignHCenter | Qt.AlignTop,
                   f"{shot['file']}  ({shot['size'][0]} x {shot['size'][1]})")
    p.end()
    sheet.save(str(out / "contact-sheet.png"), "PNG")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commit_of_tree():
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False)
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "PyReconstruct"],
                           capture_output=True, text=True, check=False)
    return head.stdout.strip(), bool(dirty.stdout.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, type=Path, help="folder for the frames")
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    before = tripwire()
    isolate_settings()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication([sys.argv[0]])
    app.setCursorFlashTime(0)  # a steady caret, not one caught mid-blink
    from PySide6.QtGui import QCursor

    QCursor.setPos(*POINTER_PARK)
    app.processEvents()
    parked = QCursor.pos()
    from PyReconstruct.modules.gui.utils import MenuShortcutSpacingStyle
    app.setStyle(MenuShortcutSpacingStyle())
    if app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        sys.exit("macOS is in dark mode; the pinned theme is the light default. Switch and rerun.")

    watchdog = start_watchdog(app)
    shots, flows, targets = shoot(out, app)
    watchdog.stop()
    if QCursor.pos() != parked:
        sys.exit("The pointer moved during the run, so a hover state may be in a frame. Rerun.")
    contact_sheet(out, shots)
    target_check(out, targets)

    files = [s["file"] for s in shots] + ["contact-sheet.png", "target-check.png"]
    (out / "targets.json").write_text(json.dumps({
        "canvas": {"width": 2 * WINDOW_SIZE[0], "height": 2 * WINDOW_SIZE[1],
                   "origin": "top-left", "units": "native pixels"},
        "targets": targets,
        "flows": flows,
        "note": "Each frame is a still of the real window. Click and drag points are "
                "where the script sent its events; the cursor is not in any frame.",
    }, indent=2) + "\n")

    after = tripwire()
    commit, dirty = commit_of_tree()
    verification = {
        "fork_commit": commit,
        "app_source_modified": dirty,
        "method": "QWidget.grab() of the live Cocoa window; no screen capture",
        "pinned": {"fixture": f"dev/assets/checker/files/{FIXTURE}",
                   "window_logical": list(WINDOW_SIZE), "device_pixel_ratio": EXPECTED_DPR,
                   "theme": "default (light); 05-dark-theme.png is the Dark theme",
                   "username": USERNAME, "settings": "empty, isolated store"},
        "files": {name: {"size": list(_png_size(out / name)), "bytes": (out / name).stat().st_size,
                         "sha256": sha256(out / name)} for name in files + ["targets.json"]},
        "shots": shots,
        "real_settings_tripwire": {"before": before, "after": after, "unchanged": before == after},
    }
    (out / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps({"out": str(out), "shots": len(shots), "tripwire_unchanged": before == after}))
    if before != after:
        sys.exit("The real settings changed during the run. Find the writer before using these frames.")


def _png_size(path):
    if path.suffix != ".png":
        return ()
    with open(path, "rb") as f:
        header = f.read(24)
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


if __name__ == "__main__":
    main()
