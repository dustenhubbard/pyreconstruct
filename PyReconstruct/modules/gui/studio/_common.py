"""Small shared helpers for the Studio widgets."""
import os

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QToolButton

from ..utils import icons

# The shipped app icon (the fork's low-poly Python mark on a squircle), resolved
# relative to the package so the view layer needs no new cross-module import and
# still works headless / offscreen. Dark and light squircles match the two
# shells (as gui.main uses for the OS window icon).
_ASSET_IMG = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "img"))
_APP_ICON = {"dark": "PyReconstruct.png", "light": "PyReconstruct-light.png"}


def app_icon_path(family="dark"):
    """Filesystem path to the app icon for a color family, or None if missing."""
    path = os.path.join(_ASSET_IMG, _APP_ICON.get(family, _APP_ICON["dark"]))
    return path if os.path.exists(path) else None


def repolish(widget):
    """Re-evaluate a widget's QSS after a dynamic property changed.

    Qt only re-runs property-dependent selectors (e.g. ``[active="true"]``) when
    a widget is unpolished and re-polished; setting the property alone is not
    enough.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class IconTileButton(QToolButton):
    """A square icon button that tints its stroked-vector icon to the theme.

    Used for both rails: it carries the resting and active icon tints, flips an
    ``active`` QSS property (so the stylesheet paints the lit-from-within state),
    and re-renders the icon to the right tint on every state or theme change.
    The artwork is the shared :mod:`gui.utils.icon_svgs` set, rendered through
    :func:`gui.utils.icons.tool_icon` (never a unicode glyph).
    """

    def __init__(self, key, icon_name, object_name, tile_px, icon_px, parent=None):
        super().__init__(parent)
        self.key = key
        self.icon_name = icon_name
        self._icon_px = icon_px
        self._rest = "#9aa7b5"
        self._active = "#37c0a6"
        self.setObjectName(object_name)
        self.setFixedSize(tile_px, tile_px)
        self.setIconSize(QSize(icon_px, icon_px))
        self.setCheckable(False)
        self.setFocusPolicy(self.focusPolicy().NoFocus)
        self.setCursor(self.cursor().shape())
        self.setProperty("active", False)
        self._render_icon()

    def retint(self, rest_color, active_color):
        """Set the resting / active icon tints (typically on a theme change)."""
        self._rest = rest_color
        self._active = active_color
        self._render_icon()

    def set_active(self, on: bool):
        """Mark this tile active: flip the QSS property and re-tint the icon."""
        self.setProperty("active", bool(on))
        repolish(self)
        self._render_icon()

    def is_active(self) -> bool:
        return bool(self.property("active"))

    def _render_icon(self):
        color = self._active if self.is_active() else self._rest
        self.setIcon(icons.tool_icon(self.icon_name, self._icon_px, color))
