"""The fonts the palettes, the scale bar and the field's labels are set in.

Everywhere but a macOS Dev build these stay "Courier New", as they always
were, so Windows, Linux and the stable Mac app draw the same pixels as before.
A macOS Dev build sets numbers and field text in the platform's monospace
(SF Mono when it is installed, else Menlo, else the system fixed font) and
the palette labels in the system UI font (SF Pro): the Mac-native look
(2026-10-21), on Dev first, and only when launched with PYRECON_MAC_UI=1
(constants/mac_ui.py).
"""
from functools import lru_cache

from PySide6.QtGui import QFont, QFontDatabase

from PyReconstruct.modules.constants.mac_ui import mac_ui_enabled

LEGACY_FAMILY = "Courier New"

# The platform's own monospace families, tried in order before the system
# fixed font. The What's New notes set inline code in these too.
CODE_FAMILIES = {
    "darwin": ("SF Mono", "Menlo", "Monaco"),
    "win32": ("Consolas", "Cascadia Mono", "Courier New"),
    "linux": ("DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono"),
}


def macLook() -> bool:
    """True on a macOS Dev build launched with PYRECON_MAC_UI=1, the only
    build with the Mac-native look. Read at call time, so a test can set
    any of the signals."""
    return mac_ui_enabled()


@lru_cache(maxsize=None)
def _macMonoFamily() -> str:
    installed = set(QFontDatabase.families())
    for family in CODE_FAMILIES["darwin"]:
        if family in installed:
            return family
    return QFontDatabase.systemFont(QFontDatabase.FixedFont).family()


@lru_cache(maxsize=None)
def _macUiFamily() -> str:
    return QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()


def monoFamily() -> str:
    """The family numbers and field text are set in."""
    return _macMonoFamily() if macLook() else LEGACY_FAMILY


def uiFamily() -> str:
    """The family palette labels are set in."""
    return _macUiFamily() if macLook() else LEGACY_FAMILY


def monoFont(size: int = -1, bold: bool = True) -> QFont:
    """A font in `monoFamily`, at point size `size` (-1 keeps the default)."""
    return QFont(monoFamily(), size, QFont.Bold if bold else -1)


def uiFont(size: int = -1, bold: bool = True) -> QFont:
    """A font in `uiFamily`. On the Mac look, bold is semibold, the weight
    macOS sets its own emphasis in."""
    if not bold:
        weight = -1
    elif macLook():
        weight = QFont.DemiBold
    else:
        weight = QFont.Bold
    return QFont(uiFamily(), size, weight)
