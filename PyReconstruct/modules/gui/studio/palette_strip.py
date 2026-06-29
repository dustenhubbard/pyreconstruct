"""The trace-palette strip — a real palette across the bottom of the main column.

A tracked ``PALETTE`` label, a row of 30px data-color swatches (the active one
ringed with a teal outline), a dashed ``+`` add tile, and a right-aligned mono
readout of the active trace (``circle · r=0.045``). The swatch colors are *data*
(trace colors), never chrome.
"""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QToolButton,
)

from ..utils import theme

_SW = 30        # the swatch itself
_BOX = 34       # widget footprint (leaves room for the offset active outline)


class _Swatch(QWidget):
    """A single 30px data-color swatch; teal-outlined when active."""

    clicked = Signal(int)

    def __init__(self, index, color_hex, parent=None):
        super().__init__(parent)
        self._index = index
        self._color = color_hex
        self._active = False
        self._accent = "#37c0a6"
        self.setFixedSize(_BOX, _BOX)
        self.setCursor(Qt.PointingHandCursor)

    def set_active(self, on):
        self._active = bool(on)
        self.update()

    def set_accent(self, accent):
        self._accent = accent
        self.update()

    def mousePressEvent(self, _event):
        self.clicked.emit(self._index)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        fill = QRectF((_BOX - _SW) / 2, (_BOX - _SW) / 2, _SW, _SW)
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.setBrush(QColor(self._color))
        p.drawRoundedRect(fill, 8, 8)
        if self._active:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(self._accent), 2))
            p.drawRoundedRect(QRectF(1, 1, _BOX - 2, _BOX - 2), 9, 9)
        p.end()


class PaletteStrip(QWidget):
    """Bottom palette strip; emits :attr:`color_selected` / :attr:`add_requested`."""

    color_selected = Signal(int)
    add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioPaletteStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._swatches = []
        self._active = 0
        self._accent = theme.studio_tokens()["accent"]

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(13, 7, 13, 7)
        self._row.setSpacing(11)

        self._label = QLabel("PALETTE", self)
        self._label.setObjectName("studioPaletteLabel")
        self._row.addWidget(self._label)

        self._swatch_row = QHBoxLayout()
        self._swatch_row.setSpacing(6)
        self._row.addLayout(self._swatch_row)

        self._add = QToolButton(self)
        self._add.setObjectName("studioAddSwatch")
        self._add.setText("+")
        self._add.setFixedSize(_SW, _SW)
        self._add.setCursor(Qt.PointingHandCursor)
        self._add.setFocusPolicy(Qt.NoFocus)
        self._add.clicked.connect(self.add_requested)
        self._swatch_row.addWidget(self._add)

        self._row.addStretch(1)

        self._readout = QLabel("", self)
        self._readout.setObjectName("studioPaletteReadout")
        self._row.addWidget(self._readout)

    def set_colors(self, colors):
        """Replace the swatch colors (a list of hex strings)."""
        for sw in self._swatches:
            self._swatch_row.removeWidget(sw)
            sw.deleteLater()
        self._swatches = []
        for i, color in enumerate(colors):
            sw = _Swatch(i, color, self)
            sw.set_accent(self._accent)
            sw.clicked.connect(self._on_click)
            # keep the add tile last
            self._swatch_row.insertWidget(self._swatch_row.count() - 1, sw)
            self._swatches.append(sw)
        self.set_active(min(self._active, len(colors) - 1) if colors else 0)

    def set_active(self, index):
        self._active = index
        for i, sw in enumerate(self._swatches):
            sw.set_active(i == index)

    def set_readout(self, text):
        self._readout.setText(text)

    def apply_theme(self, theme_name=None):
        self._accent = theme.studio_tokens(theme_name)["accent"]
        for sw in self._swatches:
            sw.set_accent(self._accent)

    def _on_click(self, index):
        self.set_active(index)
        self.color_selected.emit(index)
