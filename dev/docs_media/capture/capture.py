"""Shoot the User Guide stills from the real app, in one command.

    uv run --no-default-groups --extra test python dev/docs_media/capture/capture.py --out <folder> --guide

What this makes, in <folder>:

  * one PNG per shot in SHOTS, at the screen's native pixel density (2x on a
    Retina Mac), with labels drawn on the ones that need them;
  * contact-sheet.png, every shot on one page with its file name;
  * targets.json, the native-pixel click and drag points of the short flows
    the guide's clips show, for the video renderer (dev/docs_media/video/);
  * verification.json, the size and sha256 of every file, the pinned inputs,
    and the settings tripwire read before and after the run.

With --guide, the shots docs/USER_GUIDE.md shows are also copied over the
ones in docs/assets/images/user-guide/, so one command reshoots the guide.
With --clips, the guide's clips are rendered from this run's frames into
<folder>/clips/ (dev/docs_media/video/clips.py); with both, they replace the
ones in docs/assets/videos/user-guide/ too.

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

The settings of the PyReconstruct you use day to day are never touched.
Before anything imports the app, every `QSettings` is redirected to a
throwaway folder by tests/qsettings_isolation.py, the same mechanism the test
suite runs under, and the run stops if the redirect does not hold. A tripwire
on the real settings file (its digest, key count and username) is read before
and after and written to verification.json; the run exits non-zero if it moved.

To add a shot, add a block to `shoot` that calls `save`; give it a file name
that starts with its guide section number. A frame that only a video or an
animation uses goes in FLOW_ONLY, so --guide leaves it out of the guide.

Fixture series only. No lab data, no file dialog, no recent-files list.
"""

import argparse
import datetime
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
# column clears the section buttons; with twelve buttons, below about 700 the
# two overlap. That is taller than a 1280 x 800 screen leaves a titled
# window, so the window is frameless (macOS does not clamp those), and may run
# past the bottom of the screen: grab() draws the whole widget regardless.
WINDOW_SIZE = (1120, 760)
WINDOW_POS = (40, 40)
# the 3D scene window, logical pixels
SCENE_SIZE = (900, 640)
SCALE_CUBE_SHIFT = (2.6, 1.4, 0)  # microns
SCENE_ELEVATION, SCENE_AZIMUTH = -40, -15  # degrees from the top-down view
SCENE_ZOOM = 1.4
# where the pointer waits, beside the window, so no hover state is drawn
POINTER_PARK = (1240, 400)
EXPECTED_DPR = 2.0
USERNAME = "docs"
# the time the Backup Settings filename preview shows (see shoot)
BACKUP_PREVIEW_TIME = datetime.datetime(2026, 1, 15, 9, 30)
SERIES_CODE = "shapes1"

# where --guide puts the images docs/USER_GUIDE.md shows; the frames in
# FLOW_ONLY are for the video flows, and the guide does not use them
GUIDE_IMAGES = REPO / "docs" / "assets" / "images" / "user-guide"
FLOW_ONLY = {"04-file-menu", "04-file-menu-open-series", "05-next-section",
             "06-closed-trace-selected", "06-closed-trace-drawn-plain", "06-flag-placed",
             "09-lists-menu", "09-lists-menu-object-list", "09-object-list-opened"}

REAL_DOMAIN = "com.khlab.PyReconstruct"
REAL_PREFS = Path.home() / "Library" / "Preferences"
REAL_PLIST = REAL_PREFS / f"{REAL_DOMAIN}.plist"

# the tool palette buttons, by tooltip, and the MainWindow actions that hold
# their shortcuts (main_window.py, mode_shortcuts); the shot reads each key
# from the live action, so a rebound default shows up in the next run
TOOL_ACTIONS = {
    "Pointer": "usepointer_act",
    "Pan/Zoom": "usepanzoom_act",
    "Knife": "useknife_act",
    "Scissors": "usescissors_act",
    "Closed Trace": "usectrace_act",
    "Open Trace": "useotrace_act",
    "Stamp": "usestamp_act",
    "Grid": "usegrid_act",
    "Flag": "useflag_act",
    "Host": "usehost_act",
}
NO_SHORTCUT = {"Ztool"}

# section 2: an update offer for a version that does not exist, from data
# made up here; no network, nothing is downloaded
EXAMPLE_VERSION = "9.9.9"
EXAMPLE_LOCAL_VERSION = "1.25.0"
EXAMPLE_UPDATE = {
    "status": "newer",
    "remote_version": EXAMPLE_VERSION,
    "local_version": EXAMPLE_LOCAL_VERSION,
    "asset": {"name": f"PyReconstruct-{EXAMPLE_VERSION}-macOS-arm64.dmg",
              "size": 187_400_000, "browser_download_url": ""},
    "release": {},
}

# label style, in native pixels at 2x
LABEL_BG = "#1f2937"
LABEL_FG = "#ffffff"
ACCENT = "#f59e0b"


# --- the real settings ------------------------------------------------------


def tripwire():
    """The three tripwire values, measured on this machine at run time."""
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
    os.environ.pop("PYRECON_ROI_MODE", None)  # held features stay hidden
    sys.path.insert(0, str(REPO / "tests"))
    import qsettings_isolation  # noqa: F401  (rebinds QSettings on import)

    if not qsettings_isolation.installed:
        sys.exit("QSettings isolation did not install; refusing to run.")
    qsettings_isolation.verify_isolated()
    # and a check of its own: where the app's global and per-series settings
    # would be written now
    from PySide6.QtCore import QSettings

    org, app = qsettings_isolation.ORG, qsettings_isolation.APP
    for application in (app, f"{app}-{SERIES_CODE}"):
        check_settings_path(QSettings(org, application).fileName())
    return qsettings_isolation


def check_settings_path(path, real_dir=REAL_PREFS):
    """Stop unless `path`, a settings file, is outside the real settings folder."""
    resolved = Path(path).expanduser().resolve()
    real = Path(real_dir).expanduser().resolve()
    if resolved == real or real in resolved.parents:
        sys.exit(f"Settings would be written to {resolved}, in {real}; refusing to run.")
    return resolved


def check_no_roi(mode_names):
    """Stop if the tool palette shows ROI mode, which the guide must not show.

    ROI mode is held out of every user build until it is ready
    (constants/roi_mode.py).
    """
    if "ROI mode" in mode_names:
        sys.exit("The tool palette shows ROI mode, which the guide must not show. "
                 "Shoot on a tree that hides it, with PYRECON_ROI_MODE unset.")


# --- shortcuts --------------------------------------------------------------


def shortcut_text(portable):
    """A shortcut the way the guide writes it, macOS first.

    `portable` is QKeySequence.PortableText, where Ctrl is the Command key on
    a Mac and Meta is Control: "Shift+K" stays as it is, and "Ctrl+Shift+V"
    becomes "Cmd+Shift+V (Ctrl+Shift+V on Windows/Linux)".
    """
    if not portable:
        return ""
    mac = portable.replace("Meta+", "\0").replace("Ctrl+", "Cmd+").replace("\0", "Ctrl+")
    return mac if mac == portable else f"{mac} ({portable} on Windows/Linux)"


def tool_label(name, shortcut):
    """One tool palette label: the tool's name, then its shortcut if it has one."""
    return f"{name}  {shortcut}" if shortcut else name


def tool_shortcuts(window, names):
    """Each tool's shortcut, read from the live window's action."""
    from PySide6.QtGui import QKeySequence

    out = {}
    for name in names:
        if name in NO_SHORTCUT:
            out[name] = ""
            continue
        if name not in TOOL_ACTIONS:
            sys.exit(f"The tool {name!r} is not in TOOL_ACTIONS or NO_SHORTCUT; add it.")
        key = getattr(window, TOOL_ACTIONS[name]).shortcut()
        out[name] = shortcut_text(key.toString(QKeySequence.PortableText))
    return out


# --- frames -----------------------------------------------------------------


def settle(app, seconds=0.4):
    """Let paints, layouts and image loads finish."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


def grab(widget, check_active=True):
    """The widget's own pixels at native density, as a QImage.

    `check_active` is off only for a popup menu, which is never the active
    window itself.
    """
    from PySide6.QtGui import QImage

    if check_active and not widget.isActiveWindow():
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


def label_font(base):
    from PySide6.QtGui import QFont

    font = QFont(base)
    font.setPixelSize(26)
    font.setBold(True)
    return font


def label_painter(image):
    from PySide6.QtGui import QPainter

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setFont(label_font(painter.font()))
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


def grab_modal(app, trigger, accept=False, prepare=None):
    """Run `trigger`, which opens a modal dialog; grab the dialog and cancel it.

    `accept` presses OK instead, for a dialog whose result a later shot needs.
    `prepare(dialog)` runs before the grab, to pin a value the dialog would
    otherwise fill from the machine.
    """
    from PySide6.QtCore import QTimer

    global _expecting_modal
    found = {}

    def poll():
        dialog = app.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(50, poll)
            return
        try:
            if prepare:
                prepare(dialog)
            dialog.activateWindow()
            settle(app, 0.5)
            found["image"] = grab(dialog)
        except BaseException as error:
            # raised inside a Qt slot it would be swallowed, and the open
            # dialog would hang the run
            text = getattr(dialog, "text", lambda: "")()
            print(f"While grabbing {dialog.windowTitle() or text[:200]!r}: {error}", file=sys.stderr)
            os._exit(4)
        dialog.accept() if accept else dialog.reject()

    _expecting_modal = True
    QTimer.singleShot(0, poll)
    try:
        trigger()
    finally:
        _expecting_modal = False
    if "image" not in found:
        sys.exit("The dialog did not open.")
    return found["image"]


def grab_with_menu(app, window, menu, at, active=None):
    """The window with `menu` popped up at `at` (window logical coordinates).

    `active`, one of the menu's actions, is drawn highlighted, the way the
    row under the pointer is.
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter

    menu.popup(window.mapToGlobal(QPoint(*at)))
    settle(app, 0.6)
    if active is not None:
        menu.setActiveAction(active)
        settle(app, 0.3)
    image = grab(window, check_active=False)
    menu_image = grab(menu, check_active=False)
    corner = menu.mapToGlobal(QPoint(0, 0)) - window.mapToGlobal(QPoint(0, 0))
    p = QPainter(image)
    p.drawImage(round(corner.x() * EXPECTED_DPR), round(corner.y() * EXPECTED_DPR), menu_image)
    p.end()
    menu.hide()
    settle(app, 0.3)
    return image


def grab_scene(app, scene, viewer):
    """The 3D window: its menu bar from grab(), the scene from VTK itself.

    grab() of the render widget returns its framebuffer at the wrong row
    stride (stripes), so the scene pixels are read back from VTK's own
    render window and drawn into the widget's place.
    """
    from PySide6.QtGui import QImage, QPainter

    image = grab(scene)
    viewer._syncRenderWindowSize()
    viewer.plt.render()
    pixels = viewer.plt.screenshot(asarray=True)
    h, w = pixels.shape[:2]
    rect = native_rect(viewer, scene)
    if (w, h) != (rect.width(), rect.height()):
        sys.exit(f"The 3D render is {w} x {h}, not the widget's {rect.width()} x {rect.height()}.")
    rgb = QImage(pixels.tobytes(), w, h, 3 * w, QImage.Format_RGB888).copy()
    p = QPainter(image)
    p.drawImage(rect.topLeft(), rgb)
    p.end()
    return image


def menubar_menu(app, window, menu, action, name, heading, save):
    """Frames and targets for a click on a menu bar title, then on one row.

    Saves `name` (the menu just opened) and `name`-<row> (the row highlighted,
    as with the pointer on it); returns the native-pixel centers of the title
    and of the row.
    """
    from PySide6.QtCore import QPoint

    bar = window.menubar
    title = bar.actionGeometry(menu.menuAction())
    corner = bar.mapTo(window, title.bottomLeft())
    at = (corner.x(), corner.y())
    save(grab_with_menu(app, window, menu, at), name, heading,
         f"The {menu.title()} menu, just opened.")
    # where the row sat: measured on the popup just shown, before it is hidden
    origin = menu.mapToGlobal(QPoint(0, 0)) - window.mapToGlobal(QPoint(0, 0))
    row = menu.actionGeometry(action).center()
    slug = action.text().rstrip(".").lower().replace(" ", "-")
    save(grab_with_menu(app, window, menu, at, active=action), f"{name}-{slug}", heading,
         f"The {menu.title()} menu with {action.text()} highlighted.")
    title_center = native_point(bar, window, title.center().x(), title.center().y())
    row_center = [round((origin.x() + row.x()) * EXPECTED_DPR),
                  round((origin.y() + row.y()) * EXPECTED_DPR)]
    return title_center, row_center


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
    import math

    from PySide6.QtCore import QRect, QSettings, Qt
    from PySide6.QtGui import QColor, QFontMetricsF, QImage
    from PySide6.QtWidgets import QApplication

    from PyReconstruct.modules.gui.dialog.update_dialog import UpdateDialog
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

    # clip: File > Open series...
    file_title, open_row = menubar_menu(app, window, window.filemenu, window.open_act,
                                        "04-file-menu", "4. Opening an existing series", save)

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
    check_no_roi(palette.mode_buttons)

    # 4. Opening an existing series; also frame 1 of both flows
    opened = grab(window)
    save(opened, "04-series-open", "4. Opening an existing series",
         "shapes1.jser open on section 0, Pointer tool active.")

    # clip: Lists > Object list
    lists_title, object_row = menubar_menu(app, window, window.listsmenu, window.objectlist_act,
                                           "09-lists-menu", "9. Object list", save)
    # what that row opens, on this clean section; the guide's own Object list
    # shot comes later, with the trace and flag drawn below. The dock resizes
    # the field, which rounds its view, so the view is put back after: the
    # later shots stay as they were.
    view = list(window.series.window)
    window.objectlist_act.trigger()
    settle(app, 1.0)
    window.activateWindow()
    settle(app, 0.3)
    save(grab(window), "09-object-list-opened", "9. Object list",
         "The Object list just opened from the Lists menu.")
    from PySide6.QtWidgets import QAbstractButton, QDockWidget

    dock = next(d for d in window.findChildren(QDockWidget) if d.isVisible())
    close = dock.findChild(QAbstractButton, "qt_dockwidget_closebutton")
    if close is None or not close.isVisible():
        sys.exit("The Object list dock has no close button to point at.")
    close_center = native_point(close, window)
    field.table_manager.closeAll()
    settle(app, 0.5)
    window.series.window = view
    field.generateView()
    settle(app, 0.3)

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
    # named by its own tooltip and its shortcut, so both follow the app
    bounds = QRect(0, 0, opened.width(), opened.height())
    column = opened.copy(mode_rect.adjusted(-6, -16, 6, 16).intersected(bounds))
    keys = tool_shortcuts(window, palette.mode_buttons)
    labels = {name: tool_label(button.toolTip() or name, keys[name])
              for name, (button, _, _) in palette.mode_buttons.items()}
    metrics = QFontMetricsF(label_font(QApplication.font()))
    # the widest label, its box padding and gap (draw_label), and a margin
    label_w = max(300, math.ceil(max(metrics.horizontalAdvance(t) for t in labels.values())) + 96)
    panel = QImage(column.width() + label_w, column.height(), QImage.Format_RGB32)
    panel.fill(QColor("#f3f4f6"))
    p = label_painter(panel)
    p.drawImage(label_w, 0, column)
    shift_x = label_w - (mode_rect.left() - 6)
    shift_y = -(mode_rect.top() - 16)
    for name, (button, _, _) in palette.mode_buttons.items():
        r = native_rect(button, window).translated(shift_x, shift_y)
        draw_label(p, labels[name], (r.left() - 10, r.center().y()), "left")
    p.end()
    save(panel, "06-tool-palette-labeled", "6. The tool palette",
         "The tool palette column with each tool's name and default shortcut.")

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
    # the same trace unselected, the thin line the clip's live stroke cuts
    # to before the selection fades in; then selected again, as before
    drawn = field.section.selected_traces[0]
    field.deselectAllTraces()
    settle(app, 0.4)
    save(grab(window), "06-closed-trace-drawn-plain", "6. Closed Trace (C) and Open Trace (O)",
         "The closed trace just drawn, unselected.")
    field.selectTrace(drawn)
    settle(app, 0.4)

    # flow B: next section with the section button, back on the Pointer
    palette.mode_buttons["Pointer"][0].click()
    settle(app, 0.3)
    up_center = native_point(palette.up_bttn, window)
    down_center = native_point(palette.down_bttn, window)
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

    # back to section 0, where the trace drawn above is
    palette.down_bttn.click()
    settle(app, 1.2)

    # 6. The right-click settings of the other tools
    for name, heading, trigger, purpose in (
        ("06-pointer-options", "6. Pointer (P)", window.modifyPointer,
         "Right-click on the Pointer button: selection shape and what it selects."),
        ("06-knife-options", "6. Knife (K)", window.modifyKnife,
         "Right-click on the Knife button: % original trace, smooth cuts, other buttons."),
        ("06-grid-options", "6. Grid (G)", window.modifyGrid,
         "Right-click on the Grid button: element size, spacing, columns, rows, sampling frame."),
        ("06-flag-options", "6. Flag (F)", palette.modifyFlag,
         "Right-click on the Flag button: default name, color, size, which flags show."),
    ):
        save(grab_modal(app, trigger), name, heading, purpose)

    # 6. Flag: the Flag tool's own dialog on a click in the field; OK places
    # the flag the Flag list shows below
    palette.mode_buttons["Flag"][0].click()
    settle(app, 0.3)
    fx, fy = field.width() * 0.72, field.height() * 0.30

    def click_flag():
        field_event(field, "press", fx, fy, buttons=_left())
        field_event(field, "release", fx, fy, buttons=_none())

    save(grab_modal(app, click_flag, accept=True), "06-flag-new", "6. Flag (F)",
         "A click with the Flag tool: name, color and an optional comment.")
    settle(app, 0.5)
    palette.mode_buttons["Pointer"][0].click()
    settle(app, 0.3)
    save(grab(window), "06-flag-placed", "6. Flag (F)", "The flag just placed on the section.")

    # 7. The trace palette: the row alone, then a preset's right-click dialog
    trace_crop = opened.copy(trace_rect.adjusted(-24, -24, 24, 24).intersected(bounds))
    save(trace_crop, "07-trace-palette", "7. The trace palette",
         "The trace palette: twenty presets in two rows, the active name above them.")
    first = palette.palette_buttons[0]
    save(grab_modal(app, first.openDialog), "07-trace-palette-edit", "7. The trace palette",
         "Right-click on a preset: name, color, fill, tags, shape and stamp radius.")

    # 8. The field context menu on a selected trace
    field.deselectAllTraces()
    star = next(t for t in field.section.contours["star"])
    field.selectTrace(star)
    window.checkActions()
    settle(app, 0.4)
    at = native_point(field, window, field.width() * 0.52, field.height() * 0.42)
    menu_at = (round(at[0] / EXPECTED_DPR), round(at[1] / EXPECTED_DPR))
    save(grab_with_menu(app, window, window.field_menu, menu_at), "08-field-context-menu",
         "8. Working with traces", "Right-click on a selected trace: the field context menu.")
    field.deselectAllTraces()
    settle(app, 0.3)

    # 9. The data lists, each docked beside the field by itself
    for kind, name, heading, purpose in (
        ("object", "09-object-list", "9. Object list",
         "The Object list docked beside the field, with its menus."),
        ("trace", "09-trace-list", "9. Trace list", "The Trace list for the current section."),
        ("section", "09-section-list", "9. Section list", "The Section list."),
        ("ztrace", "09-ztrace-list", "9. Z-trace list", "The Z-trace list."),
        ("flag", "09-flag-list", "9. Flag list", "The Flag list, with the flag placed above."),
    ):
        field.openList(list_type=kind)
        settle(app, 1.0)
        window.activateWindow()
        settle(app, 0.3)
        save(grab(window), name, heading, purpose)
        field.table_manager.closeAll()
        settle(app, 0.5)

    # 10. Alignment dialogs
    save(grab_modal(app, window.modifyAlignments), "10-edit-alignments",
         "10. Switching and managing alignments",
         "Alignments > Edit alignments: new, rename, remove.")
    # the transform dialog opens only on an unlocked section: the app's own
    # Alignments > Unlock current section
    was_locked = field.section.align_locked
    if was_locked:
        field.unlockSection()
        settle(app, 0.3)
    save(grab_modal(app, window.changeTform), "10-edit-transformation",
         "10. Adjusting a section's transform",
         "Alignments > Edit transformation: the six numbers a b c d e f.")

    # 12. Backup settings
    # The filename preview shows today's date and time; it is pinned to
    # BACKUP_PREVIEW_TIME so a rerun on another day gives the same frame.
    def pin_preview_time(dialog):
        dialog.now = BACKUP_PREVIEW_TIME
        dialog.updateWidgets()

    save(grab_modal(app, window.setBackup, prepare=pin_preview_time),
         "12-backup-settings", "12. Backups",
         "File > Backup > Settings: folder, auto-backup and the filename template.")

    # 13. The shortcuts list
    save(grab_modal(app, window.displayShortcuts), "13-shortcuts-list", "13. Keyboard shortcuts",
         "Help > Shortcuts list, where every shortcut can be rebound.")

    # 11. The 3D scene: the fixture's four objects as surfaces, with the
    # scale cube, the way Object list > 3D > Add to scene opens it
    window.activateWindow()
    settle(app, 0.3)
    window.addTo3D(["circle2", "square", "star", "triangle"])
    viewer = window.viewer
    scene = viewer.container
    scene.setWindowFlag(Qt.FramelessWindowHint, True)
    scene.showNormal()
    scene.resize(*SCENE_SIZE)
    scene.move(*WINDOW_POS)
    settle(app, 1.0)
    viewer.togglesc_act.setChecked(True)
    viewer.toggleScaleCube()
    # the cube appears at the scene center, over the star: move it to the
    # empty upper right (the arrow keys do the same), then tilt the camera
    # so the objects read as solids
    cube = viewer.plt.objs.getType("scale_cube")[0]
    cube.translate(*SCALE_CUBE_SHIFT)
    viewer.plt.show(*viewer.plt.actors, resetcam=True)
    camera = viewer.plt.camera
    camera.Elevation(SCENE_ELEVATION)
    camera.Azimuth(SCENE_AZIMUTH)
    camera.OrthogonalizeViewUp()
    viewer.plt.reset_camera()
    camera.Zoom(SCENE_ZOOM)
    viewer.plt.render()
    scene.raise_()
    scene.activateWindow()
    settle(app, 1.5)
    save(grab_scene(app, scene, viewer), "11-3d-scene", "11. Generating a 3D object",
         "The 3D scene with the fixture's four objects and the scale cube.")
    scene.close()
    settle(app, 0.5)

    # 2. Updates, last, so nothing they open is in an earlier frame
    window.activateWindow()
    settle(app, 0.3)
    menu = window.helpmenu
    menu.popup(window.mapToGlobal(window.rect().center()))
    settle(app, 0.6)
    rows = [menu.actionGeometry(a) for a in
            (window.checkupdates_act, window.toggleupdatecheck_act, window.getotherflavor_act)]
    menu_image = grab(menu, check_active=False)
    top, bottom = rows[0].top(), rows[-1].bottom()
    crop = QRect(0, round((top - 6) * EXPECTED_DPR), menu_image.width(),
                 round((bottom - top + 13) * EXPECTED_DPR))
    menu.hide()
    settle(app, 0.3)
    save(menu_image.copy(crop.intersected(menu_image.rect())), "02-help-menu-updates",
         "2. Checking for updates",
         "The update rows of the Help menu: check now, check on startup, the other app.")

    # The real dialog, on EXAMPLE_UPDATE; Later closes it
    window.activateWindow()
    settle(app, 0.3)
    offer = UpdateDialog(window, EXAMPLE_UPDATE, "stable")
    save(grab_modal(app, offer.exec), "02-update-dialog", "2. Checking for updates",
         f"The update dialog, offering {EXAMPLE_VERSION}, an example version that does not exist.")
    offer.deleteLater()

    # The status bar notice; _setUpdateNotice only shows it, where
    # showUpdateNotice would also store the version
    window.activateWindow()
    window._setUpdateNotice(EXAMPLE_VERSION)
    settle(app, 0.5)
    status = native_rect(window.statusbar, window)
    notice = native_rect(window.update_notice, window)
    status.setLeft(max(status.left(), notice.left() - 360))
    save(grab(window).copy(status), "02-update-notice", "2. Checking automatically on startup",
         f"The Update available notice in the status bar, for the example version {EXAMPLE_VERSION}.")
    window._setUpdateNotice(None)
    settle(app, 0.3)

    close_window(app, window)
    shutil.rmtree(series_dir, ignore_errors=True)

    flows = {
        "open-series": {
            "steps": [
                {"frame": "04-welcome-series.png", "action": "click", "target": "file_menu"},
                {"frame": "04-file-menu.png", "action": "move", "target": "open_series_row"},
                {"frame": "04-file-menu-open-series.png", "action": "click",
                 "target": "open_series_row"},
                {"frame": "04-series-open.png", "action": "hold",
                 "note": "the file dialog is not shot; the clip fades to the open series"},
            ],
        },
        "pick-closed-trace-and-draw": {
            "steps": [
                {"frame": "04-series-open.png", "action": "click", "target": "closed_trace_button"},
                {"frame": "06-closed-trace-selected.png", "action": "drag", "target": "draw_path"},
                {"frame": "06-closed-trace-drawn-plain.png", "action": "hold"},
                {"frame": "06-closed-trace-drawn.png", "action": "hold"},
            ],
        },
        "next-section": {
            "steps": [
                {"frame": "04-series-open.png", "action": "click", "target": "next_section_button"},
                {"frame": "05-next-section.png", "action": "click", "target": "previous_section_button"},
                {"frame": "04-series-open.png", "action": "hold"},
            ],
        },
        "open-object-list": {
            "steps": [
                {"frame": "04-series-open.png", "action": "click", "target": "lists_menu"},
                {"frame": "09-lists-menu.png", "action": "move", "target": "object_list_row"},
                {"frame": "09-lists-menu-object-list.png", "action": "click",
                 "target": "object_list_row"},
                {"frame": "09-object-list-opened.png", "action": "click",
                 "target": "object_list_close"},
                {"frame": "04-series-open.png", "action": "hold"},
            ],
        },
    }
    targets = {
        "file_menu": {"center": file_title, "frame": "04-welcome-series.png"},
        "open_series_row": {"center": open_row, "frame": "04-file-menu.png"},
        "closed_trace_button": {"center": closed_center,
                                "bounds": rect_list(native_rect(closed_button, window)),
                                "frame": "04-series-open.png"},
        "draw_path": {"points": drag_native, "frame": "06-closed-trace-selected.png",
                      "color": list(drawn.color),
                      "note": "left button held from the first point to the last"},
        "next_section_button": {"center": up_center,
                                "frame": "04-series-open.png"},
        "previous_section_button": {"center": down_center,
                                    "frame": "05-next-section.png"},
        "lists_menu": {"center": lists_title, "frame": "04-series-open.png"},
        "object_list_row": {"center": object_row, "frame": "09-lists-menu.png"},
        "object_list_close": {"center": close_center, "frame": "09-object-list-opened.png"},
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
    for key in ("closed_trace_button", "next_section_button", "previous_section_button"):
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
    parser.add_argument("--guide", action="store_true",
                        help=f"also replace the User Guide's images in {GUIDE_IMAGES.relative_to(REPO)}")
    parser.add_argument("--clips", action="store_true",
                        help="also render the User Guide's clips from these frames")
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
    contact_sheet(out, sorted(shots, key=lambda s: s["file"]))
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
    if args.guide:
        kept = copy_to_guide(out, shots)
        print(f"{len(kept)} images in {GUIDE_IMAGES.relative_to(REPO)}")
    if args.clips:
        sys.path.insert(0, str(REPO))
        from dev.docs_media.video import clips

        made = clips.build(out, guide=args.guide)
        print(f"{len(made)} clips in {out / 'clips'}")


def copy_to_guide(out, shots, guide=GUIDE_IMAGES):
    """Replace the guide's images with this run's, leaving out the flow-only frames.

    A PNG in `guide` that this run did not make is removed, so a renamed shot
    leaves no stale copy; other files there are left alone. Returns the names
    copied.
    """
    guide.mkdir(parents=True, exist_ok=True)
    keep = sorted(s["file"] for s in shots if Path(s["file"]).stem not in FLOW_ONLY)
    for old in guide.glob("*.png"):
        if old.name not in keep:
            old.unlink()
    for name in keep:
        shutil.copyfile(out / name, guide / name)
    return keep


def _png_size(path):
    if path.suffix != ".png":
        return ()
    with open(path, "rb") as f:
        header = f.read(24)
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


if __name__ == "__main__":
    main()
