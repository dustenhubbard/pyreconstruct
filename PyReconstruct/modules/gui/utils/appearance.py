"""The theme choices, and System, Light and Dark on macOS Dev builds.

The stored theme keeps its old values: "default" and "qdark". The macOS Dev
app offers three choices, like macOS's own Appearance setting:

* System, stored "default": follows macOS light and dark, live. The native
  style's standard palette already tracks the color scheme, so this is the
  old Default under a new label.
* Light, stored "light" (new): always light.
* Dark, stored "qdark": always dark, with the native controls, not qdarkstyle.

Light and Dark set the scheme for this app only (QStyleHints.setColorScheme);
macOS's own setting is never touched. Everywhere else (the stable app,
Windows, Linux) the choices are Default and Dark (qdarkstyle) as before, and
"light" reads as "default", so a stable build that meets a value a Dev build
saved draws the default look.

The qdarkstyle sheet pads table cells, so the lists widen their columns by
8 px under it. They ask qdarkstyleApplied(), not the stored name: native Dark
is stored as "qdark" too and needs no padding.
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.constants import build_flavor

SYSTEM = "default"
LIGHT = "light"
DARK = "qdark"

# the app property setTheme sets while the qdarkstyle sheet is on
QDARKSTYLE_PROPERTY = "pyreconQDarkStyle"


def native() -> bool:
    """True in the macOS Dev app, where all three choices keep native controls."""
    return sys.platform == "darwin" and build_flavor.is_dev_build()


def choices(legacy_labels=("Default", "Dark")):
    """(label, stored value) for each theme this build offers.

    legacy_labels are the caller's own labels for Default and Dark, used
    where the choices stay as before."""
    if native():
        return [("System", SYSTEM), ("Light", LIGHT), ("Dark", DARK)]
    return list(zip(legacy_labels, (SYSTEM, DARK)))


def resolve(theme) -> str:
    """The stored value this build draws: an unknown one is drawn as default."""
    if theme in [value for _, value in choices()]:
        return theme
    return SYSTEM


def setColorScheme(theme):
    """Set this app's color scheme for a theme; System follows macOS again."""
    hints = QApplication.styleHints()
    if theme == LIGHT:
        hints.setColorScheme(Qt.ColorScheme.Light)
    elif theme == DARK:
        hints.setColorScheme(Qt.ColorScheme.Dark)
    else:
        hints.unsetColorScheme()


def qdarkstyleApplied() -> bool:
    """True while the qdarkstyle sheet is on the app."""
    app = QApplication.instance()
    return bool(app is not None and app.property(QDARKSTYLE_PROPERTY))
