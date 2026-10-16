"""The app's window and dock icon, dressed up around holidays.

For the two weeks before each holiday in ``backend/holidays.py``, the day
itself and the week after, the window takes that holiday's icon from
``assets/img/holidays/<holiday>/<flavor>`` (``stable``, or ``dev`` for
PyReconstruct Dev, which keeps its DEV badge).
Every other day it is the regular icon, exactly as before.

Each folder holds the window icon at several sizes. ``icon-16.png`` to
``icon-48.png`` are drawn simpler and larger for the title bar and taskbar,
and ``icon-64.png`` up carry the full artwork. ``dock-*.png`` are the same
artwork on Apple's icon grid, for the macOS dock, which otherwise shows the
bundle's own icon and never the window's.

The holiday is decided once, at launch.
"""
import sys
from datetime import date
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.backend.holidays import holiday_for
from PyReconstruct.modules.constants import icon_path, img_dir
from PyReconstruct.modules.datatypes.series_owner import app_display_name

HOLIDAY_ICON_DIR = Path(img_dir) / "holidays"


def icon_flavor():
    """``dev`` in PyReconstruct Dev, ``stable`` otherwise."""
    return "dev" if "Dev" in app_display_name() else "stable"


def holiday_icon_dir(today=None):
    """The folder of today's holiday icon for this build, or None."""
    name = holiday_for(today or date.today())
    if name is None:
        return None
    folder = HOLIDAY_ICON_DIR / name / icon_flavor()
    return folder if folder.is_dir() else None


def _icon_from(folder, pattern):
    icon = QIcon()
    for png in sorted(folder.glob(pattern)):
        icon.addFile(str(png))
    return icon


def window_icon(today=None):
    """Today's holiday icon if there is one, else the regular icon."""
    folder = holiday_icon_dir(today)
    if folder is not None:
        icon = _icon_from(folder, "icon-*.png")
        if not icon.isNull():
            return icon
    return QIcon(QPixmap(icon_path))


def apply_holiday_dock_icon(today=None):
    """Put today's holiday icon in the macOS dock. No-op elsewhere or on an
    ordinary day, so the bundle's icon stays put."""
    if sys.platform != "darwin":
        return
    folder = holiday_icon_dir(today)
    if folder is None:
        return
    icon = _icon_from(folder, "dock-*.png")
    if not icon.isNull():
        QApplication.setWindowIcon(icon)
