"""Shoot and render the User Guide's four short clips, in one command.

    uv run --no-default-groups --extra test python dev/docs_media/capture/guide_clips.py --out <folder> [--guide]

The clips play on a loop, with no sound, beside the guide text they show:

  * 04-open-series: File > Open series..., and the series opens;
  * 05-move-between-sections: the section buttons, up and back down;
  * 06-draw-closed-trace: pick Closed Trace, drag a loop, let go;
  * 09-open-object-list: Lists > Object list, then its close button.

What this makes, in <folder>:

  * one 2560 x 1440 PNG per screen state, without a pointer (FRAMES);
  * a folder per clip with steps.json, the clip's step list from clips()
    for walkthrough.py's `draft` command, with each click point measured
    from the live widgets on this run; scene.json, drafted from it;
    <clip>.mp4; sheet.jpg, one frame per second; and verification.json;
  * capture-verification.json, the size and sha256 of every frame, the
    pinned inputs, and the settings tripwire read before and after the run.

With --guide, the four videos replace the ones in docs/assets/videos/user-guide/,
and each clip's first frame is saved as its poster, <clip>-start.png, in
docs/assets/images/user-guide/.

How it shoots is capture.py's, on the made-up series the guide's stills
show (shapes1): the theme, username, isolated settings and tripwire, and
QWidget.grab() of the live window. As in walkthrough_3d.py, the window is
1280 x 720 logical pixels, so a frame is 2560 x 1440 on a 2x screen, and the
camera stays at zoom 1: PyReconstruct as a 1280 x 720 screen shows it, at
Retina sharpness, each frame shown pixel for pixel. The videos are rendered
with dev/docs_media/walkthrough/walkthrough.py at --width 2560 --crf 21.

Made-up series only. No file dialog, no recent-files list.
"""

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
WALKTHROUGH = REPO / "dev" / "docs_media" / "walkthrough" / "walkthrough.py"
GUIDE_VIDEOS = REPO / "docs" / "assets" / "videos" / "user-guide"
GUIDE_IMAGES = REPO / "docs" / "assets" / "images" / "user-guide"


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = _load("docs_capture", "capture.py")

# A screencast shows PyReconstruct as a 1280 x 720 screen shows it, at 2x, as
# in walkthrough_3d.py: at the left edge of the screen, with the pointer
# waiting in the menu bar above the window, where no hover state is drawn.
capture.WINDOW_SIZE = (1280, 720)
capture.WINDOW_POS = (0, 40)
capture.POINTER_PARK = (1200, 12)
FRAME_SIZE = (2560, 1440)
WIDTH = 2560
CRF = 21
STROKE_WIDTH = 2  # native pixels: the field draws its live line one point wide
STILL = {"x": 1280, "y": 720, "zoom": 1}
# the view's margin around the image, as shares of the image's height: more
# below, where the trace palette sits over the field
VIEW_MARGIN_TOP, VIEW_MARGIN_BOTTOM = 0.08, 0.25
# the middle of the drawn loop, as shares of the image from its top left:
# left of the star, between the triangle and the rectangle
DRAW_AT = (0.13, 0.55)
# where the pointer starts, in the field and clear of the palettes
REST = [round(FRAME_SIZE[0] * 0.62), round(FRAME_SIZE[1] * 0.62)]
# short clips: quicker moves than the draft defaults, and no zoom out to wait for
TIMING = {"intro": 0.5, "move": 0.9, "outro_delay": 0.5, "outro": 0.2, "tail": 0.3}

FRAMES = {
    "welcome": "04-welcome-series.png",
    "file-menu": "04-file-menu.png",
    "file-menu-row": "04-file-menu-open-series.png",
    "open": "04-series-open.png",
    "next": "05-next-section.png",
    "closed": "06-closed-trace-selected.png",
    "drawn-plain": "06-closed-trace-drawn-plain.png",
    "drawn": "06-closed-trace-drawn.png",
    "lists": "09-lists-menu.png",
    "lists-row": "09-lists-menu-object-list.png",
    "list": "09-object-list-opened.png",
}


def clips(targets):
    """Each clip's step list, from this run's targets."""
    loop_end = targets["draw_path"]["points"][-1]
    return {
        "04-open-series": [
            {"image": "welcome", "click": "file_menu"},
            {"image": "file-menu", "point": "open_series_row", "move": 0.6},
            # the file dialog is the system's and is not shot: the menu fades
            # to the open series instead
            {"image": "file-menu-row", "click": "open_series_row", "after": "open",
             "after_fade": 0.3, "end_dwell": 1.0},
        ],
        "05-move-between-sections": [
            {"image": "open", "click": "next_section_button"},
            {"image": "next", "point": "next_section_button", "dwell": 0.9},
            {"image": "next", "click": "previous_section_button", "move": 0.5, "after": "open",
             "end_dwell": 0.8},
        ],
        "06-draw-closed-trace": [
            {"image": "open", "click": "closed_trace_button"},
            # the live stroke is the field's thin line; at the release it cuts
            # to the unselected trace, drawn the same way, and only then does
            # the selection fade in, so the line never jumps in one frame
            {"image": "closed", "drag": "draw_path", "drag_time": 2.0, "move": 1.0,
             "stroke": {"color": targets["draw_path"]["color"], "width": STROKE_WIDTH}},
            {"image": "drawn-plain", "point": loop_end, "dwell": 0.15, "after": "drawn",
             "after_fade": 0.25, "end_dwell": 1.2},
        ],
        "09-open-object-list": [
            {"image": "open", "click": "lists_menu"},
            {"image": "lists", "point": "object_list_row", "move": 0.6},
            {"image": "lists-row", "click": "object_list_row"},
            {"image": "list", "point": "object_list_row", "dwell": 0.8},
            {"image": "list", "click": "object_list_close", "after": "open", "end_dwell": 0.6},
        ],
    }


def steps_files(targets):
    """Each clip's whole steps.json, by clip name; images are in the folder above."""
    out = {}
    for name, steps in clips(targets).items():
        used = {s["image"] for s in steps} | {s["after"] for s in steps if "after" in s}
        out[name] = {
            "size": list(FRAME_SIZE),
            "images": {key: f"../{FRAMES[key]}" for key in sorted(used)},
            "targets": targets,
            "cursor_start": REST,
            "camera_start": STILL,
            "camera_end": STILL,
            "timing": TIMING,
            "loop": True,
            "steps": [{**s, "camera": STILL} for s in steps],
        }
    return out


def poster(name):
    return f"{name}-start.png"


# --- the shoot --------------------------------------------------------------


def fit_view(app, field):
    """Fit the view to the image, with margins that keep it clear of the
    palettes. The saved view suits capture.py's taller window; in this one
    the image would sit small in a wide black field. The field is wider than
    the image, so its height sets the scale and the image stays centered
    across."""
    field.home()
    x, y, w, h = field.series.window
    tall = 1 + VIEW_MARGIN_TOP + VIEW_MARGIN_BOTTOM
    field.series.window = [x - w * (tall - 1) / 2, y - h * VIEW_MARGIN_BOTTOM, w * tall, h * tall]
    field.generateView()
    capture.settle(app, 0.5)


def image_point(field, fx, fy):
    """The field point (logical pixels) at shares `fx`, `fy` of the image from its top left."""
    from PyReconstruct.modules.calc.pfconversions import fieldPointToPixmap

    min_x, min_y, max_x, max_y = field.imageBounds()
    world = (min_x + (max_x - min_x) * fx, max_y - (max_y - min_y) * fy)
    return fieldPointToPixmap(*world, field.series.window, field.pixmap_dim, field.section.mag)


def shoot(out, app):
    """Make every frame; return the click and drag targets, by name."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QAbstractButton, QDockWidget

    from PyReconstruct.modules.gui.dialog.whats_new import APP, ORG, current_version_str
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    settings = QSettings(ORG, APP)
    settings.setValue(WHATSNEW_KEY, current_version_str())
    settings.setValue("username", capture.USERNAME)

    by_file = {file: key for key, file in FRAMES.items()}

    def save(image, key):
        if (image.width(), image.height()) != FRAME_SIZE:
            sys.exit(f"{FRAMES[key]} is {image.width()} x {image.height()}, not {FRAME_SIZE}.")
        if not image.save(str(out / FRAMES[key]), "PNG"):
            sys.exit(f"Could not write {out / FRAMES[key]}")

    def save_named(image, name, *_):
        save(image, by_file[f"{name}.png"])

    # 04: the welcome series, and File > Open series...
    window = capture.build_window(app, None)
    fit_view(app, window.field)
    save(capture.grab(window), "welcome")
    file_title, open_row = capture.menubar_menu(app, window, window.filemenu, window.open_act,
                                                "04-file-menu", "", save_named)
    capture.close_window(app, window)

    series_dir = capture.fixture_copy()
    window = capture.build_window(app, str(series_dir / capture.FIXTURE))
    palette, field = window.mouse_palette, window.field
    capture.check_no_roi(palette.mode_buttons)
    fit_view(app, field)
    save(capture.grab(window), "open")

    # 09: Lists > Object list, then its close button
    lists_title, object_row = capture.menubar_menu(app, window, window.listsmenu,
                                                   window.objectlist_act, "09-lists-menu", "",
                                                   save_named)
    view = list(window.series.window)
    window.objectlist_act.trigger()
    capture.settle(app, 1.0)
    window.activateWindow()
    capture.settle(app, 0.3)
    save(capture.grab(window), "list")
    dock = next(d for d in window.findChildren(QDockWidget) if d.isVisible())
    close = dock.findChild(QAbstractButton, "qt_dockwidget_closebutton")
    if close is None or not close.isVisible():
        sys.exit("The Object list dock has no close button to point at.")
    close_center = capture.native_point(close, window)
    field.table_manager.closeAll()
    capture.settle(app, 0.5)
    # the dock resized the field, which rounds its view: put it back, so the
    # frames below match the open series
    window.series.window = view
    field.generateView()
    capture.settle(app, 0.3)

    # 05: the section buttons
    up_center = capture.native_point(palette.up_bttn, window)
    down_center = capture.native_point(palette.down_bttn, window)
    palette.up_bttn.click()
    capture.settle(app, 1.2)
    save(capture.grab(window), "next")
    palette.down_bttn.click()
    capture.settle(app, 1.2)

    # 06: pick Closed Trace, drag a loop in an empty part of the image
    closed_button = palette.mode_buttons["Closed Trace"][0]
    closed_center = capture.native_point(closed_button, window)
    closed_button.click()
    capture.settle(app, 0.5)
    save(capture.grab(window), "closed")
    path = capture.blob(*image_point(field, *DRAW_AT), 56, 42)
    capture.field_event(field, "press", *path[0], buttons=capture._left())
    for x, y in path[1:]:
        capture.field_event(field, "move", x, y, buttons=capture._left())
        app.processEvents()
    time.sleep(0.6)  # longer than a click, so combo mode keeps the scribble
    capture.field_event(field, "release", *path[-1], buttons=capture._none())
    capture.settle(app, 0.6)
    if len(field.section.selected_traces) != 1:
        sys.exit("The drag drew no trace.")
    save(capture.grab(window), "drawn")
    drawn = field.section.selected_traces[0]
    field.deselectAllTraces()
    capture.settle(app, 0.4)
    save(capture.grab(window), "drawn-plain")
    draw_path = [capture.native_point(field, window, x, y) for x, y in path]

    capture.close_window(app, window)
    shutil.rmtree(series_dir, ignore_errors=True)

    return {
        "file_menu": {"center": file_title},
        "open_series_row": {"center": open_row},
        "lists_menu": {"center": lists_title},
        "object_list_row": {"center": object_row},
        "object_list_close": {"center": close_center},
        "next_section_button": {"center": up_center},
        "previous_section_button": {"center": down_center},
        "closed_trace_button": {"center": closed_center},
        "draw_path": {"points": draw_path, "color": list(drawn.color)},
    }


# --- the videos -------------------------------------------------------------


def walkthrough(*args):
    subprocess.run([sys.executable, str(WALKTHROUGH), *map(str, args)], check=True)


def render(out, targets):
    """Draft, render, sheet and verify every clip; return the videos."""
    videos = []
    for name, steps in steps_files(targets).items():
        folder = out / name
        folder.mkdir(exist_ok=True)
        (folder / "steps.json").write_text(json.dumps(steps, indent=2) + "\n")
        walkthrough("draft", folder / "steps.json")
        video = folder / f"{name}.mp4"
        walkthrough("render", folder / "scene.json", "--width", WIDTH, "--crf", CRF, "-o", video)
        walkthrough("sheet", folder / "scene.json", "-o", folder / "sheet.jpg")
        walkthrough("verify", folder / "scene.json", video)
        videos.append(video)
    return videos


def copy_to_guide(out, videos, targets, video_dir=GUIDE_VIDEOS, image_dir=GUIDE_IMAGES):
    """Put each video in the guide, and its first frame as its poster."""
    steps = clips(targets)
    for video in videos:
        shutil.copyfile(video, video_dir / video.name)
        shutil.copyfile(out / FRAMES[steps[video.stem][0]["image"]], image_dir / poster(video.stem))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, type=Path, help="folder for the frames and clips")
    parser.add_argument("--guide", action="store_true",
                        help="also replace the clips and their posters in docs/assets/")
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    before = capture.tripwire()
    capture.isolate_settings()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QApplication

    app = QApplication([sys.argv[0]])
    app.setCursorFlashTime(0)
    QCursor.setPos(*capture.POINTER_PARK)
    app.processEvents()
    parked = QCursor.pos()
    from PyReconstruct.modules.gui.utils import MenuShortcutSpacingStyle
    app.setStyle(MenuShortcutSpacingStyle())
    # the pinned theme is the light default. On a Mac set to Auto, evening
    # turns it dark, so PyReconstruct asks for light for itself; macOS is not changed.
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.processEvents()
    if app.styleHints().colorScheme() != Qt.ColorScheme.Light:
        sys.exit("PyReconstruct would not take the light theme. Switch macOS to Light and rerun.")

    watchdog = capture.start_watchdog(app)
    targets = shoot(out, app)
    watchdog.stop()
    if QCursor.pos() != parked:
        sys.exit("The pointer moved during the run, so a hover state may be in a frame. Rerun.")

    after = capture.tripwire()
    commit, dirty = capture.commit_of_tree()
    verification = {
        "fork_commit": commit,
        "app_source_modified": dirty,
        "method": "QWidget.grab() of the live Cocoa window; no screen capture",
        "pinned": {"fixture": f"dev/assets/checker/files/{capture.FIXTURE}",
                   "window_logical": list(capture.WINDOW_SIZE),
                   "device_pixel_ratio": capture.EXPECTED_DPR, "theme": "default (light)",
                   "username": capture.USERNAME, "settings": "empty, isolated store"},
        "files": {f: {"bytes": (out / f).stat().st_size, "sha256": capture.sha256(out / f)}
                  for f in FRAMES.values()},
        "targets": targets,
        "real_settings_tripwire": {"before": before, "after": after, "unchanged": before == after},
    }
    (out / "capture-verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps({"out": str(out), "frames": len(FRAMES), "tripwire_unchanged": before == after}))
    if before != after:
        sys.exit("The real settings changed during the run. Find the writer before using these frames.")

    videos = render(out, targets)
    if args.guide:
        copy_to_guide(out, videos, targets)
        print(f"{len(videos)} clips and posters in docs/assets/")


if __name__ == "__main__":
    main()
