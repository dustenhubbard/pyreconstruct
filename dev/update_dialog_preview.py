# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = ["PySide6==6.5.2", "packaging"]
# ///
"""Standalone visual preview for the in-app update dialog (gui.dialog.update_dialog).

Run on a machine WITH a real display (macOS / Windows):

    uv run --script dev/update_dialog_preview.py        # deps + Python 3.11 via PEP 723
    # explicit:  uv run --no-project --python 3.11 --with PySide6==6.5.2 --with packaging dev/update_dialog_preview.py
    # or pip:    pip install PySide6==6.5.2 packaging && python dev/update_dialog_preview.py

It loads update_dialog.py directly by path, so the only dependencies are PySide6
and packaging -- none of the heavy PyReconstruct runtime deps (vtk/vedo/zarr/...).
Shows the dialog with sample data so you can sign off the look: version line,
channel, download size, the "What's new" release notes, and the buttons.

NOTE: "Download & Install" points at a fake URL and needs the full app env, so
this is a LAYOUT preview -- click "Later" to close. Exercise the real
download/verify/install flow from an actual build.
"""
import os
import sys
import importlib.util

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# Load the dialog module by path so we never trigger the gui.dialog package
# __init__ (and its heavier sibling dialogs). update_dialog's own imports are
# PySide6 + the stdlib/packaging-only updater backend.
_path = os.path.join(REPO, "PyReconstruct", "modules", "gui", "dialog", "update_dialog.py")
_spec = importlib.util.spec_from_file_location("_update_dialog_preview", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
UpdateDialog = _mod.UpdateDialog

from PySide6.QtWidgets import QApplication, QMainWindow

INFO = {
    "release": {
        "tag_name": "v1.21.0",
        "body": (
            "## PyReconstruct 1.21.0\n\n"
            "### Highlights\n"
            "- **3–4× faster** opening large autoseg series\n"
            "- Theme now follows your system light/dark setting\n"
            "- Modernized tool-button icons\n\n"
            "### Fixes\n"
            "- Correctness audit of the performance rewrite\n"
            "- Assorted UI polish\n\n"
            "[Full changelog](https://github.com/dustenhubbard/PyReconstruct/releases)\n"
        ),
    },
    "asset": {
        "name": "PyReconstruct-1.21.0-macOS-arm64.dmg",
        "size": 96_300_000,
        "browser_download_url": "https://example.invalid/asset",
    },
    "remote_version": "1.21.0",
    "local_version": "1.20.0",
    "status": "newer",
}


def main():
    app = QApplication(sys.argv)
    parent = QMainWindow()
    parent._updater_pool = None
    parent._pending_installer = None
    parent._pending_update_dir = None
    parent.resize(700, 500)
    parent.show()
    UpdateDialog(parent, INFO, "release").exec()


if __name__ == "__main__":
    main()
