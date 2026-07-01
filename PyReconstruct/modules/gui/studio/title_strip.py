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
from PySide6.QtGui import QPainter, QConicalGradient, QColor, QPixmap
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame

from ..utils import theme
from ._common import app_icon_path

_MENU = ["File", "Edit", "Series", "Section", "Lists",
         "Alignments", "Autosegment", "View", "Help"]
_DOTS = ("#f0655a", "#f4bd4f", "#3ecf8e")   # window controls (decorative)


class _BrandMark(QWidget):
    """The app mark — the real fork icon (per shell family).

    Uses the shipped squircle icon (dark on the Studio shell, light on Atlas,
    mirroring the OS window icon). Falls back to the conic-gradient placeholder
    if the asset can't be loaded, so the strip never renders empty.
    """

    def __init__(self, size=18, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._pixmap = None
        self.set_family("dark")

    def set_family(self, family):
        path = app_icon_path(family)
        pm = QPixmap(path) if path else QPixmap()
        self._pixmap = pm if not pm.isNull() else None
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = self.rect()
        if self._pixmap is not None:
            p.drawPixmap(r, self._pixmap)
        else:
            g = QConicalGradient(r.center().x(), r.center().y(), 200)
            for pos, col in ((0.0, "#37c0a6"), (0.25, "#5ab0f0"), (0.5, "#b06cf0"),
                             (0.75, "#f4bd4f"), (1.0, "#37c0a6")):
                g.setColorAt(pos, QColor(col))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(QRectF(r), 5, 5)
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
        self._brand = _BrandMark(18, self)
        lay.addWidget(self._brand)
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

    def apply_theme(self, theme_name=None):
        """Match the brand mark to the shell family (dark/light squircle)."""
        self._brand.set_family(theme.studio_tokens(theme_name)["family"])
