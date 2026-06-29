"""Offscreen (or on-screen) preview of the Studio layout.

Builds the real :class:`StudioShell` populated with the mockup's content and
renders it in both shells — Studio (dark) and Atlas (light) — for sign-off.

Run it against the worktree (it imports the package, so set PYTHONPATH):

    PYTHONPATH=<repo> QT_QPA_PLATFORM=offscreen \\
        python dev/studio_preview.py --out <dir>      # write studio.png + atlas.png

    PYTHONPATH=<repo> python dev/studio_preview.py --show studio   # interactive

The Studio widgets are a pure view layer, so this needs only PySide6 +
qdarkstyle from the runtime — none of the heavy field/series deps.
"""
import argparse
import os
import sys

from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.gui.studio.shell import StudioShell

WIDTH, HEIGHT = 1200, 604
THEMES = ("studio", "atlas")


def render(out_dir, width=WIDTH, height=HEIGHT):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    shell = StudioShell.demo()
    shell.resize(width, height)
    shell.show()
    for name in THEMES:
        shell.apply_theme(name, app_wide=True)
        app.processEvents()
        app.processEvents()
        pm = shell.grab()
        path = os.path.join(out_dir, f"{name}.png")
        pm.save(path, "PNG")
        paths[name] = path
        print(f"{name}: {path}  ({pm.width()}x{pm.height()})")
    return paths


def show(theme_name):
    app = QApplication.instance() or QApplication(sys.argv)
    shell = StudioShell.demo()
    shell.resize(WIDTH, HEIGHT)
    shell.apply_theme(theme_name, app_wide=True)
    shell.setWindowTitle(f"PyReconstruct — Studio layout preview ({theme_name})")
    shell.show()
    sys.exit(app.exec())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="directory to write studio.png + atlas.png")
    ap.add_argument("--show", choices=THEMES, help="show a theme interactively")
    ap.add_argument("--width", type=int, default=WIDTH)
    ap.add_argument("--height", type=int, default=HEIGHT)
    args = ap.parse_args()
    if args.show:
        show(args.show)
    else:
        out = args.out or os.path.join(os.path.dirname(__file__), "..", "previews", "studio")
        render(os.path.abspath(out), args.width, args.height)


if __name__ == "__main__":
    main()
