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
from ._common import logo_path

_MENU = ["File", "Edit", "Series", "Section", "Lists",
         "Alignments", "Autosegment", "View", "Help"]
_DOTS = ("#f0655a", "#f4bd4f", "#3ecf8e")   # window controls (decorative)


class _BrandMark(QWidget):
    """The app mark — the bare (transparent) fork logo.

    The flat mark reads on both the dark and light title bars, so it needs no
    per-theme variant. Falls back to the conic-gradient placeholder if the asset
    can't be loaded, so the strip never renders empty.
    """

    def __init__(self, size=22, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        path = logo_path()
        pm = QPixmap(path) if path else QPixmap()
        self._pixmap = pm if not pm.isNull() else None

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

        lay.addSpacing(4)
        self._brand = _BrandMark(22, self)
        lay.addWidget(self._brand)
        # one label for the whole wordmark so "Py" and "Reconstruct" are a single
        # word (no layout gap between them); "Reconstruct" takes the teal accent.
        self._brand_label = QLabel(self)
        self._brand_label.setObjectName("studioBrand")
        self._brand_label.setTextFormat(Qt.RichText)
        self._brand_label.setText('Py<span style="color:#37c0a6">Reconstruct</span>')
        lay.addWidget(self._brand_label)

        lay.addSpacing(12)
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
        """Re-tint the wordmark's accent to the active theme (mark is theme-free)."""
        accent = theme.studio_tokens(theme_name)["accent"]
        self._brand_label.setText(f'Py<span style="color:{accent}">Reconstruct</span>')
