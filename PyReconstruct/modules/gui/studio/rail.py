"""The activity rail — the slim left strip that switches the left panel.

48px wide, ``panel-2`` ground, a column of 34x34 icon tiles (Objects, Traces,
Sections, Flags, 3D scene, then a spacer, then Settings). The active tile is
teal-tinted with an inset teal ring; clicking one emits :attr:`activated` so the
shell can repoint the Objects panel (or launch the 3D panel).
"""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout

from ._common import IconTileButton

#: (key, tooltip, icon_svg_name) in rail order; ``None`` is the flexible spacer
RAIL_ITEMS = [
    ("objects", "Objects", "objects"),
    ("traces", "Traces", "traces"),
    ("sections", "Sections", "sections"),
    ("flags", "Flags", "flag"),
    ("scene3d", "3D scene", "scene3d"),
    None,
    ("settings", "Settings", "settings"),
]

_TILE_PX = 34
_ICON_PX = 20


class ActivityRail(QWidget):
    """Vertical icon rail; emits :attr:`activated` with the selected item key."""

    activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioActivityRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(48)
        self._buttons = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        for item in RAIL_ITEMS:
            if item is None:
                layout.addStretch(1)
                continue
            key, tip, icon_name = item
            btn = IconTileButton(key, icon_name, "studioRailButton", _TILE_PX, _ICON_PX, self)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _=False, k=key: self._on_click(k))
            layout.addWidget(btn, 0, Qt.AlignHCenter)
            self._buttons[key] = btn

        self.set_active("objects")

    def _on_click(self, key):
        self.set_active(key)
        self.activated.emit(key)

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
