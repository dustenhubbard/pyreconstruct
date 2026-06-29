"""The title strip — brand, menu names, alignment chip, and the ⌘K field.

40px, ``panel-2`` ground. A conic-gradient brand mark + "Py**Reconstruct**"
(with "Reconstruct" in teal), the familiar menu names, and on the right an
"Alignment · default" chip plus a ⌘K "Search actions" field.

This is a representative strip for the shell and the sign-off preview — the real
main window keeps its native ``QMenuBar``; the strip exists so the Studio layout
reads as a whole. The ⌘K field's *affordance* is in scope; its full
command-palette behaviour is a follow-up.
"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QConicalGradient, QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame

from ..utils import theme

_MENU = ["File", "Edit", "Series", "Section", "Lists",
         "Alignments", "Autosegment", "View", "Help"]
_DOTS = ("#f0655a", "#f4bd4f", "#3ecf8e")   # window controls (decorative)


class _BrandMark(QWidget):
    """The 18px conic-gradient app mark."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        g = QConicalGradient(9, 9, 200)
        g.setColorAt(0.00, QColor("#37c0a6"))
        g.setColorAt(0.25, QColor("#5ab0f0"))
        g.setColorAt(0.50, QColor("#b06cf0"))
        g.setColorAt(0.75, QColor("#f4bd4f"))
        g.setColorAt(1.00, QColor("#37c0a6"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0, 0, 18, 18), 5, 5)
        p.end()


class _Dot(QLabel):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.setFixedSize(11, 11)
        self.setStyleSheet(f"background:{color}; border-radius:5px;")


class StudioTitleStrip(QWidget):
    """Brand + menu + alignment chip + ⌘K search field."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioTitleStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 0, 11, 0)
        lay.setSpacing(7)

        for c in _DOTS:
            lay.addWidget(_Dot(c, self))

        lay.addSpacing(6)
        lay.addWidget(_BrandMark(self))
        brand = QLabel("Py", self)
        brand.setObjectName("studioBrand")
        brand_accent = QLabel("Reconstruct", self)
        brand_accent.setObjectName("studioBrandAccent")
        lay.addWidget(brand)
        lay.addSpacing(0)
        lay.addWidget(brand_accent)

        lay.addSpacing(10)
        for name in _MENU:
            item = QLabel(name, self)
            item.setObjectName("studioMenuItem")
            lay.addWidget(item)

        lay.addStretch(1)

        chip = QLabel("Alignment · default", self)
        chip.setObjectName("studioChip")
        lay.addWidget(chip)

        cmdk = QFrame(self)
        cmdk.setObjectName("studioCmdk")
        cmdk.setAttribute(Qt.WA_StyledBackground, True)
        cl = QHBoxLayout(cmdk)
        cl.setContentsMargins(9, 4, 7, 4)
        cl.setSpacing(8)
        cl.addWidget(QLabel("Search actions", cmdk))
        kbd = QLabel("⌘K", cmdk)
        kbd.setObjectName("studioCmdkKbd")
        cl.addWidget(kbd)
        lay.addWidget(cmdk)
