"""The tool rail — the flush right strip of drawing tools.

60px wide, ``panel-2`` ground, a hairline border-left, and 38x38 tiles with
muted icons. Deliberately **flush-docked**: not a floating card — no blur, no
shadow, no "TOOLS" header, no keycap badges, no glow. The active tool reads as
"lit from within" (a subtle gradient tile + teal icon + teal border), nothing
more. A small gap separates the drawing tools from Flag / Host.
"""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout

from ._common import IconTileButton

#: (key, tooltip, icon_svg_name); ``None`` is the fixed gap between groups
TOOL_ITEMS = [
    ("pointer", "Pointer", "pointer"),
    ("panzoom", "Pan / zoom", "panzoom"),
    ("closedtrace", "Closed trace", "closedtrace"),
    ("opentrace", "Open trace", "opentrace"),
    ("knife", "Knife", "knife"),
    ("stamp", "Stamp", "stamp"),
    ("grid", "Grid", "grid"),
    None,
    ("flag", "Flag", "flag"),
    ("host", "Host", "host"),
]

_TILE_PX = 38
_ICON_PX = 22
_GAP_PX = 7


class ToolRail(QWidget):
    """Vertical tool rail; emits :attr:`tool_selected` with the active tool key."""

    tool_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioToolRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(60)
        self._buttons = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        for item in TOOL_ITEMS:
            if item is None:
                layout.addSpacing(_GAP_PX)
                continue
            key, tip, icon_name = item
            btn = IconTileButton(key, icon_name, "studioToolButton", _TILE_PX, _ICON_PX, self)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _=False, k=key: self._on_click(k))
            layout.addWidget(btn, 0, Qt.AlignHCenter)
            self._buttons[key] = btn

        layout.addStretch(1)
        self.set_active("pointer")

    def _on_click(self, key):
        self.set_active(key)
        self.tool_selected.emit(key)

    def set_active(self, key):
        """Light the tile for ``key`` (no-op if unknown); clears the others."""
        if key not in self._buttons:
            return
        for k, btn in self._buttons.items():
            btn.set_active(k == key)
        self._active_key = key

    def active_key(self):
        return getattr(self, "_active_key", None)

    def retint(self, rest_color, active_color):
        for btn in self._buttons.values():
            btn.retint(rest_color, active_color)
