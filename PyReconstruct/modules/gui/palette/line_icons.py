"""Line icons for the mouse palette's tools, on macOS Dev builds launched with
PYRECON_MAC_UI=1 (constants/mac_ui.py; fork #763).

Every other build keeps the fixed-color PNGs and the text characters (Flag,
Host, ROI). Here each tool gets a Lucide line icon (assets/icons/lucide, ISC
license), drawn in the button's text color, so it reads in light and dark
alike. The selected tool is drawn in the accent color, and Flag in the flag
color.

The color goes into the SVG text in place of Lucide's `currentColor`, and the
icon is rendered once per screen scale, so it stays sharp on Retina. A palette
change (the macOS appearance switching, or a theme change) renders them again.
"""
import os
from functools import lru_cache

from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

from PyReconstruct.modules.constants import locations as loc
from PyReconstruct.modules.constants.mac_ui import mac_ui_enabled

ICON_DIR = os.path.join(loc.assets_dir, "icons", "lucide")

# tool button name: Lucide icon name
TOOL_ICONS = {
    "Pointer": "mouse-pointer-2",
    "Pan/Zoom": "move",
    "Knife": "slice",
    "Scissors": "scissors",
    "Closed Trace": "pentagon",
    "Open Trace": "spline",
    "Stamp": "stamp",
    "Grid": "grid-3x3",
    "Flag": "flag",
    "Host": "git-fork",
    "Ztool": "layers",
    "ROI mode": "scan",
}

ICON_SIZE = 24  # Lucide's own grid; its 2 px stroke stays 2 px


def wanted() -> bool:
    """True on macOS in a Dev build launched with PYRECON_MAC_UI=1."""
    return mac_ui_enabled()


def accentColor(palette : QPalette) -> QColor:
    """The accent color (the macOS one under the native style); Highlight
    where Qt has no Accent role."""
    role = getattr(QPalette.ColorRole, "Accent", QPalette.ColorRole.Highlight)
    return palette.color(role)


@lru_cache(maxsize=None)
def _svgText(icon_name : str) -> str:
    with open(os.path.join(ICON_DIR, icon_name + ".svg"), encoding="utf-8") as f:
        return f.read()


def _ratios() -> list:
    """1x, 2x and the scale of every screen, so no screen gets a scaled copy."""
    ratios = {1.0, 2.0}
    for screen in QGuiApplication.screens():
        ratios.add(screen.devicePixelRatio())
    return sorted(ratios)


def renderPixmap(icon_name : str, color : QColor, size : int, ratio : float) -> QPixmap:
    """The icon in one color, at `size` points and `ratio` pixels per point."""
    svg = _svgText(icon_name).replace("currentColor", color.name())
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    px = round(size * ratio)
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def toolIcon(name : str, color : QColor, selected_color : QColor) -> QIcon:
    """The tool's icon: `color` when unchecked, `selected_color` when checked."""
    icon = QIcon()
    for ratio in _ratios():
        for c, state in ((color, QIcon.Off), (selected_color, QIcon.On)):
            icon.addPixmap(renderPixmap(TOOL_ICONS[name], c, ICON_SIZE, ratio), QIcon.Normal, state)
    return icon


def tint(mode_buttons : dict, flag_color : tuple):
    """Give every mode button its line icon in the current palette's colors.

        Params:
            mode_buttons (dict): name: (button, mouse mode, position)
            flag_color (tuple): the series' flag color, for the Flag tool
    """
    for name, (button, _mode, _pos) in mode_buttons.items():
        palette = button.palette()
        if name == "Flag":
            color = QColor(*flag_color)
        else:
            color = palette.color(QPalette.ButtonText)
        button.setText("")
        button.setIcon(toolIcon(name, color, accentColor(palette)))
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))


class Retinter(QObject):
    """Calls `retint` when `watched` sees its palette change: the macOS
    appearance switching, or the app changing theme.

    The call waits for the event loop: `watched` hears of the change before
    its sibling buttons have their new palettes, and a retint at once reads
    the old colors for every button but `watched`. The wait also folds the
    several events of one change into one retint.
    """

    EVENTS = (QEvent.PaletteChange, QEvent.ApplicationPaletteChange, QEvent.StyleChange)

    def __init__(self, watched, retint):
        super().__init__(watched)
        self.retint = retint
        self.pending = False
        watched.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in self.EVENTS and not self.pending:
            self.pending = True
            QTimer.singleShot(0, self, self.run)
        return False

    def run(self):
        self.pending = False
        self.retint()
