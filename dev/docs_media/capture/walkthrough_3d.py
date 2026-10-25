"""Shoot the frames of the User Guide's "Add an object to the 3D scene" video.

    uv run --no-default-groups --extra test python dev/docs_media/capture/walkthrough_3d.py --out <folder>

The video is in section 11, "Generating a 3D object". It shows the task the
section describes in words: open the Object list from the Lists menu,
select the objects, right-click them, choose 3D > Add to scene, and the 3D
scene opens.

What this makes, in <folder>:

  * one 2560 x 1440 PNG per screen state, without a pointer (FRAMES);
  * steps.json, the step list for walkthrough.py's `draft`
    command, with the click point of each control measured from the live
    widgets on this run (walkthrough_3d.steps.json, filled in);
  * capture-verification.json, the size and sha256 of every file, the pinned inputs,
    and the settings tripwire read before and after the run.

How it shoots, and what is pinned, is capture.py's: the theme, username,
isolated settings and tripwire, and QWidget.grab() of the live window. Three
things differ. The series is neurites.py's, a dendrite with a spine, an
axon and an astroglial process, written fresh for each run. The main window
is 1280 x 720 logical pixels, so a frame is 2560 x 1440 on a 2x screen:
PyReconstruct as a 1280 x 720 screen shows it, at Retina sharpness. And the last
frame puts the 3D scene window over the main window, the way the two sit on
screen, since one grab holds one window.

To make the video, give steps.json to dev/docs_media/walkthrough/walkthrough.py:
`walkthrough.py draft <folder>/steps.json`, then
`walkthrough.py render <folder>/scene.json --width 2560 --crf 21 -o 11-add-to-scene.mp4`
(its README.md has the whole workflow).
The camera stays at zoom 1, so the video shows each frame pixel for pixel. The
guide's copy is docs/assets/videos/user-guide/11-add-to-scene.mp4, and its
poster is 01-series-open.png, saved as 11-add-to-scene-start.png beside the
guide's other images.

Made-up data only. No lab data, no file dialog, no recent-files list.
"""

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS_TEMPLATE = HERE / "walkthrough_3d.steps.json"



def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = _load("docs_capture", "capture.py")
neurites = _load("docs_neurites", "neurites.py")

# A screencast shows PyReconstruct as a 1280 x 720 screen shows it, at 2x: the
# window is 1280 x 720 logical pixels, a frame is 2560 x 1440, and the video
# shows each frame pixel for pixel. At the left edge
# of the screen, so the window fits on a 1280-wide one; the pointer waits
# in the menu bar above it, where no hover state is drawn.
capture.WINDOW_SIZE = (1280, 720)
capture.WINDOW_POS = (0, 40)
capture.POINTER_PARK = (1200, 12)
FRAME_SIZE = (2560, 1440)
# the 3D scene window: shot on screen at capture.WINDOW_POS, drawn into the
# last frame at SCENE_AT (native pixels), over the field and clear of the
# sliders and palettes
SCENE_SIZE = (720, 480)
SCENE_AT = (590, 190)
SHADOW = 24  # native pixels of soft shadow around the scene window
# the Object list's rows, in its order; the video selects them all
OBJECTS = ["ast01", "ax01", "d01", "d01sp01"]
RIGHT_CLICK = "d01"
VIEW_MARGIN = 0.12  # of the image, on each side

FRAMES = {
    "open": "01-series-open.png",
    "lists": "02-lists-menu.png",
    "lists-row": "02-lists-menu-object-list.png",
    "list": "03-object-list.png",
    "list-first": "03-object-list-first-row.png",
    "list-all": "03-object-list-all-rows.png",
    "menu": "04-object-menu.png",
    "menu-3d": "05-object-menu-3d.png",
    "menu-add": "05-object-menu-3d-add-to-scene.png",
    "scene": "06-3d-scene.png",
}


def grab_with_menus(app, window, chain):
    """The window with a chain of popup menus drawn over it.

    `chain` is [(menu, global point, action to highlight or None), ...], each
    menu after the first a submenu of the one before. The menus stay open,
    so the caller hides them; the active rows are drawn highlighted, as with
    the pointer on them.
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter

    for menu, at, active in chain:
        if not menu.isVisible():
            menu.popup(at)
            capture.settle(app, 0.6)
        if active is not None:
            menu.setActiveAction(active)
            capture.settle(app, 0.3)
    image = capture.grab(window, check_active=False)
    p = QPainter(image)
    for menu, _, _ in chain:
        corner = menu.mapToGlobal(QPoint(0, 0)) - window.mapToGlobal(QPoint(0, 0))
        p.drawImage(round(corner.x() * capture.EXPECTED_DPR), round(corner.y() * capture.EXPECTED_DPR),
                    capture.grab(menu, check_active=False))
    p.end()
    return image


def row_center(menu, action, window):
    """The native-pixel center of one menu row, in the window's frame."""
    from PySide6.QtCore import QPoint

    origin = menu.mapToGlobal(QPoint(0, 0)) - window.mapToGlobal(QPoint(0, 0))
    row = menu.actionGeometry(action).center()
    d = capture.EXPECTED_DPR
    return [round((origin.x() + row.x()) * d), round((origin.y() + row.y()) * d)]


def with_window_over(base, top, at):
    """`base` with `top` drawn at `at` (native pixels), on a soft shadow."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QPainter

    image = base.copy()
    p = QPainter(image)
    p.setPen(Qt.NoPen)
    x, y = at
    for i in range(SHADOW, 0, -2):
        p.setBrush(QColor(0, 0, 0, round(5 * (1 - i / SHADOW) ** 2 * 6)))
        p.drawRoundedRect(QRect(x - i, y - i + SHADOW // 3, top.width() + 2 * i, top.height() + 2 * i),
                          i, i)
    p.drawImage(x, y, top)
    p.setPen(QColor(0, 0, 0, 60))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRect(x, y, top.width() - 1, top.height() - 1))
    p.end()
    return image


def shoot(out, app):
    """Make every frame; return the click targets, by name."""
    from PySide6.QtCore import QPoint, QSettings, Qt

    from PyReconstruct.modules.gui.dialog.whats_new import APP, ORG, current_version_str
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    settings = QSettings(ORG, APP)
    settings.setValue(WHATSNEW_KEY, current_version_str())
    settings.setValue("username", capture.USERNAME)

    def save(image, key):
        if (image.width(), image.height()) != FRAME_SIZE:
            sys.exit(f"{FRAMES[key]} is {image.width()} x {image.height()}, not {FRAME_SIZE}.")
        if not image.save(str(out / FRAMES[key]), "PNG"):
            sys.exit(f"Could not write {out / FRAMES[key]}")

    series_dir = Path(tempfile.mkdtemp(prefix="pyrecon-docs-series-"))
    jser = neurites.write_series(series_dir)

    window = capture.build_window(app, str(jser))
    capture.check_no_roi(window.mouse_palette.mode_buttons)
    # the saved view suits capture.py's smaller window; here the image would
    # sit small in a wide black field, so the view is fitted to it, with a
    # margin that keeps the shapes clear of the palettes
    window.field.home()
    x, y, w, h = window.series.window
    window.series.window = [x - w * VIEW_MARGIN, y - h * VIEW_MARGIN,
                            w * (1 + 2 * VIEW_MARGIN), h * (1 + 2 * VIEW_MARGIN)]
    window.field.generateView()
    capture.settle(app, 0.5)
    save(capture.grab(window), "open")

    # Lists > Object list
    menu = window.listsmenu
    bar = window.menubar
    title = bar.actionGeometry(menu.menuAction())
    corner = window.mapToGlobal(bar.mapTo(window, title.bottomLeft()))
    save(grab_with_menus(app, window, [(menu, corner, None)]), "lists")
    save(grab_with_menus(app, window, [(menu, corner, window.objectlist_act)]), "lists-row")
    lists_title = capture.native_point(bar, window, title.center().x(), title.center().y())
    object_row = row_center(menu, window.objectlist_act, window)
    menu.hide()
    capture.settle(app, 0.3)

    window.objectlist_act.trigger()
    capture.settle(app, 1.0)
    window.activateWindow()
    capture.settle(app, 0.3)
    save(capture.grab(window), "list")

    # click the first row, Shift-click the last, right-click inside the selection
    table = window.field.table_manager.tables["object"][-1]
    view, model = table.table, table.model
    names = [model.nameAt(r) for r in range(model.rowCount())]
    if names != OBJECTS:
        sys.exit(f"The Object list shows {names}, not {OBJECTS}.")
    rows = {}
    for r, name in enumerate(names):
        rows[name] = view.viewport().mapTo(window, view.visualRect(model.index(r, 0)).center())

    def native(point):
        return [round(point.x() * capture.EXPECTED_DPR), round(point.y() * capture.EXPECTED_DPR)]

    view.setFocus()  # a click focuses the list: its selection draws blue
    view.selectRow(0)
    capture.settle(app, 0.3)
    save(capture.grab(window), "list-first")
    view.selectAll()
    capture.settle(app, 0.3)
    if table.getSelected() != OBJECTS:
        sys.exit(f"Selecting every row selected {table.getSelected()}.")
    save(capture.grab(window), "list-all")

    table.syncVisibilityActions()
    context = table.context_menu
    at = window.mapToGlobal(rows[RIGHT_CLICK])
    save(grab_with_menus(app, window, [(context, at, None)]), "menu")
    three_d = table.menu_3D
    three_d_row = row_center(context, three_d.menuAction(), window)
    # the submenu where Qt puts it: beside the 3D row, its first row level
    # with it. Opened with popup(): setActiveAction() does not open a submenu.
    geometry = context.actionGeometry(three_d.menuAction())
    sub_at = context.mapToGlobal(QPoint(geometry.right(), geometry.top()))
    chain = [(context, at, three_d.menuAction()), (three_d, sub_at, None)]
    save(grab_with_menus(app, window, chain), "menu-3d")
    add = table.addobjto3D_act
    chain[-1] = (three_d, sub_at, add)
    under = grab_with_menus(app, window, chain)
    save(under, "menu-add")
    add_row = row_center(three_d, add, window)
    three_d.hide()
    context.hide()
    capture.settle(app, 0.3)

    # the click itself. The row's action finds its names through the focused
    # list, which a scripted run cannot count on, so this makes the call the
    # action ends in, on the selected rows.
    window.activateWindow()
    capture.settle(app, 0.3)
    window.addTo3D(table.getSelected())
    viewer = window.viewer
    if viewer is None:
        sys.exit("Add to scene opened no 3D scene.")
    scene = viewer.container
    scene.setWindowFlag(Qt.FramelessWindowHint, True)
    scene.showNormal()
    scene.resize(*SCENE_SIZE)
    scene.move(*capture.WINDOW_POS)
    capture.settle(app, 1.5)
    camera = viewer.plt.camera
    viewer.plt.reset_camera()
    camera.Elevation(capture.SCENE_ELEVATION)
    camera.Azimuth(capture.SCENE_AZIMUTH)
    camera.OrthogonalizeViewUp()
    viewer.plt.reset_camera()
    camera.Zoom(capture.SCENE_ZOOM)
    viewer.plt.render()
    scene.raise_()
    scene.activateWindow()
    capture.settle(app, 1.5)
    scene_image = capture.grab_scene(app, scene, viewer)
    # behind it, the main window as it is after the click: menus closed,
    # the rows still selected
    window_image = capture.grab(window, check_active=False)
    save(with_window_over(window_image, scene_image, SCENE_AT), "scene")
    scene.close()
    capture.settle(app, 0.5)

    capture.close_window(app, window)
    shutil.rmtree(series_dir, ignore_errors=True)

    return {
        "lists_menu": lists_title,
        "object_list_row": object_row,
        "first_row": native(rows[OBJECTS[0]]),
        "last_row": native(rows[OBJECTS[-1]]),
        "right_click_row": native(rows[RIGHT_CLICK]),
        "menu_3d_row": three_d_row,
        "add_to_scene_row": add_row,
        "scene_window": [SCENE_AT[0] + scene_image.width() // 2,
                         SCENE_AT[1] + scene_image.height() // 2],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, type=Path, help="folder for the frames")
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
        sys.exit("The app would not take the light theme. Switch macOS to Light and rerun.")

    watchdog = capture.start_watchdog(app)
    targets = shoot(out, app)
    watchdog.stop()
    if QCursor.pos() != parked:
        sys.exit("The pointer moved during the run, so a hover state may be in a frame. Rerun.")

    steps = json.loads(STEPS_TEMPLATE.read_text())
    steps["size"] = list(FRAME_SIZE)
    steps["images"] = dict(FRAMES)
    steps["targets"] = targets
    (out / "steps.json").write_text(json.dumps(steps, indent=2) + "\n")

    after = capture.tripwire()
    commit, dirty = capture.commit_of_tree()
    files = list(FRAMES.values()) + ["steps.json"]
    verification = {
        "fork_commit": commit,
        "app_source_modified": dirty,
        "method": "QWidget.grab() of the live Cocoa windows; no screen capture",
        "pinned": {"series": "dev/docs_media/capture/neurites.py",
                   "window_logical": list(capture.WINDOW_SIZE),
                   "scene_window_logical": list(SCENE_SIZE), "scene_window_at_native": list(SCENE_AT),
                   "device_pixel_ratio": capture.EXPECTED_DPR, "theme": "default (light)",
                   "username": capture.USERNAME, "settings": "empty, isolated store"},
        "files": {name: {"bytes": (out / name).stat().st_size, "sha256": capture.sha256(out / name)}
                  for name in files},
        "real_settings_tripwire": {"before": before, "after": after, "unchanged": before == after},
    }
    (out / "capture-verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps({"out": str(out), "frames": len(FRAMES), "tripwire_unchanged": before == after}))
    if before != after:
        sys.exit("The real settings changed during the run. Find the writer before using these frames.")


if __name__ == "__main__":
    main()
