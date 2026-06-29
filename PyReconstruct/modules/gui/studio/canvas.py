"""The canvas — the dark work surface and its glassy floating controls.

The EM canvas is always dark (in Studio *and* Atlas). Controls do not crowd it:
they float as glassy cards over the imagery so the work owns the screen —

  * active-object "needs review" badge (top-left),
  * scale bar (bottom-left),
  * section-nav pill ``‹ section 148 / 287 ›`` (bottom-center),
  * brightness / contrast card with teal-thumb tracks (bottom-right).

Brightness/contrast live here, on the canvas — not in a docked slider. The
floats are children repositioned on resize. :meth:`set_canvas_widget` is the
seam where the real field widget mounts later; until then the canvas paints a
representative dark EM/segmentation backdrop so the layout reads honestly.
"""
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QPen, QRadialGradient, QLinearGradient,
)
from PySide6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel, QToolButton, QSizePolicy,
)

from ..utils import theme, icons

#: curation status -> (chrome token key, badge phrasing)
_STATUS = {
    "curated": ("ok", "curated"),
    "review": ("warn", "needs review"),
    "flagged": ("bad", "flagged"),
}


class _Dot(QLabel):
    """A small status dot (a data hue, constant across themes)."""

    def __init__(self, d=8, parent=None):
        super().__init__(parent)
        self._d = d
        self.setFixedSize(d, d)

    def set_color(self, color_hex):
        self.setStyleSheet(f"background:{color_hex}; border-radius:{self._d // 2}px;")


class TealTrack(QWidget):
    """A minimal slider: a thin raised track with a teal thumb (0–100)."""

    valueChanged = Signal(int)

    def __init__(self, value=50, parent=None):
        super().__init__(parent)
        self._value = max(0, min(100, value))
        self._track = "#222a35"
        self._accent = "#37c0a6"
        self.setMinimumWidth(64)
        self.setFixedHeight(14)
        self.setCursor(Qt.PointingHandCursor)

    def set_tokens(self, tokens):
        self._track = tokens["raised_dark"]
        self._accent = tokens["accent"]
        self.update()

    def value(self):
        return self._value

    def setValue(self, v):
        v = max(0, min(100, int(v)))
        if v != self._value:
            self._value = v
            self.update()
            self.valueChanged.emit(v)

    def _value_from_x(self, x):
        usable = max(1, self.width() - 10)
        return round((x - 5) / usable * 100)

    def mousePressEvent(self, event):
        self.setValue(self._value_from_x(event.position().x()))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.setValue(self._value_from_x(event.position().x()))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cy = h / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._track))
        p.drawRoundedRect(QRectF(0, cy - 2, w, 4), 2, 2)
        cx = 5 + (w - 10) * self._value / 100
        p.setBrush(QColor(self._accent))
        p.drawEllipse(QPointF(cx, cy), 5, 5)
        p.end()


def _float_frame(name="studioFloat"):
    f = QFrame()
    f.setObjectName(name)
    f.setAttribute(Qt.WA_StyledBackground, True)
    return f


class ActiveObjectBadge(QFrame):
    """Top-left glassy badge: a status dot + ``name · <status phrase>``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioFloat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 5, 10, 5)
        lay.setSpacing(7)
        self._dot = _Dot(8, self)
        self._text = QLabel("", self)
        self._text.setObjectName("studioFloatText")
        lay.addWidget(self._dot)
        lay.addWidget(self._text)
        self._tok = theme.studio_tokens()

    def set_tokens(self, tokens):
        self._tok = tokens
        self._refresh()

    def set_object(self, name, status):
        self._name = name
        self._status = status
        self._refresh()

    def _refresh(self):
        name = getattr(self, "_name", "")
        status = getattr(self, "_status", None)
        tok_key, phrase = _STATUS.get(status, ("warn", "needs review"))
        self._dot.set_color(self._tok[tok_key])
        self._text.setText(f"{name} · {phrase}" if name else phrase)
        self.adjustSize()


class ScaleBar(QWidget):
    """Bottom-left scale bar: a solid bar + a mono measurement (no card)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._bar = QFrame(self)
        self._bar.setFixedSize(80, 3)
        self._text = QLabel("2 µm", self)
        self._text.setObjectName("studioScaleText")
        lay.addWidget(self._bar)
        lay.addWidget(self._text)
        self._tok = theme.studio_tokens()
        self._apply()

    def set_tokens(self, tokens):
        self._tok = tokens
        self._apply()

    def set_text(self, text):
        self._text.setText(text)
        self.adjustSize()

    def _apply(self):
        self._bar.setStyleSheet(f"background:{self._tok['scale_bar']}; border-radius:1px;")


class SectionNavPill(QFrame):
    """Bottom-center glassy pill: ``‹ section <n> / <total> ›``."""

    stepped = Signal(int)   # -1 previous, +1 next

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioFloat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        self._prev = self._chev("chevron_left", -1)
        self._label = QLabel("", self)
        self._label.setObjectName("studioSecnavLabel")
        self._label.setTextFormat(Qt.RichText)
        self._next = self._chev("chevron_right", +1)
        lay.addWidget(self._prev)
        lay.addWidget(self._label)
        lay.addWidget(self._next)
        self._tok = theme.studio_tokens()
        self._idx, self._total = 1, 1
        self._refresh_icons()
        self.set_section(148, 287)

    def _chev(self, icon_name, delta):
        b = QToolButton(self)
        b.setObjectName("studioSecnavButton")
        b.setFixedSize(24, 24)
        b.setFocusPolicy(Qt.NoFocus)
        b.setCursor(Qt.PointingHandCursor)
        b._icon_name = icon_name
        b.clicked.connect(lambda _=False, d=delta: self.stepped.emit(d))
        return b

    def set_tokens(self, tokens):
        self._tok = tokens
        self._refresh_icons()
        self._refresh_label()

    def set_section(self, idx, total):
        self._idx, self._total = idx, total
        self._refresh_label()

    def _refresh_icons(self):
        for b in (self._prev, self._next):
            b.setIcon(icons.tool_icon(b._icon_name, 14, self._tok["float_muted"]))

    def _refresh_label(self):
        faint = self._tok["float_faint"]
        self._label.setText(
            f"section <b>{self._idx}</b>"
            f"<span style='color:{faint}'> / {self._total}</span>"
        )
        self.adjustSize()


class BrightnessContrastCard(QFrame):
    """Bottom-right glassy card: brightness + contrast on teal-thumb tracks."""

    brightness_changed = Signal(int)
    contrast_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioFloat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(152)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 11, 8)
        lay.setSpacing(6)
        self.bright = self._row(lay, "Bright")
        self.contr = self._row(lay, "Contr")
        self.bright.valueChanged.connect(self.brightness_changed)
        self.contr.valueChanged.connect(self.contrast_changed)
        self._tok = theme.studio_tokens()

    def _row(self, parent_layout, label):
        row = QHBoxLayout()
        row.setSpacing(8)
        lab = QLabel(label, self)
        lab.setObjectName("studioFloatLabel")
        lab.setFixedWidth(34)
        track = TealTrack(50, self)
        track.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(lab)
        row.addWidget(track, 1)
        parent_layout.addLayout(row)
        return track

    def set_tokens(self, tokens):
        self._tok = tokens
        self.bright.set_tokens(tokens)
        self.contr.set_tokens(tokens)

    def set_values(self, brightness, contrast):
        self.bright.setValue(brightness)
        self.contr.setValue(contrast)


class CanvasArea(QWidget):
    """The dark canvas; hosts the glassy floats and (later) the real field."""

    section_changed = Signal(int)
    brightness_changed = Signal(int)
    contrast_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioCanvas")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumSize(420, 320)
        self._tok = theme.studio_tokens()
        self._canvas_widget = None

        self.badge = ActiveObjectBadge(self)
        self.scalebar = ScaleBar(self)
        self.secnav = SectionNavPill(self)
        self.bc = BrightnessContrastCard(self)

        self.secnav.stepped.connect(self.section_changed)
        self.bc.brightness_changed.connect(self.brightness_changed)
        self.bc.contrast_changed.connect(self.contrast_changed)

        self.badge.set_object("spine_042", "review")

    # --- public API -------------------------------------------------------
    def set_canvas_widget(self, widget):
        """Mount a real canvas (the field widget); the demo backdrop yields."""
        if self._canvas_widget is not None:
            self._canvas_widget.setParent(None)
        self._canvas_widget = widget
        if widget is not None:
            widget.setParent(self)
            widget.lower()
            widget.show()
        self._reposition()
        self.update()

    def set_active_object(self, name, status):
        self.badge.set_object(name, status)
        self._reposition()

    def set_section(self, idx, total):
        self.secnav.set_section(idx, total)
        self._reposition()

    def set_scale(self, text):
        self.scalebar.set_text(text)
        self._reposition()

    def set_brightness(self, value):
        self.bc.bright.setValue(value)

    def set_contrast(self, value):
        self.bc.contr.setValue(value)

    def apply_theme(self, theme_name=None):
        self._tok = theme.studio_tokens(theme_name)
        for w in (self.badge, self.scalebar, self.secnav, self.bc):
            w.set_tokens(self._tok)
        self.update()

    # --- layout -----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition()

    def _reposition(self):
        w, h = self.width(), self.height()
        if self._canvas_widget is not None:
            self._canvas_widget.setGeometry(0, 0, w, h)
        for f in (self.badge, self.scalebar, self.secnav, self.bc):
            f.adjustSize()
        self.badge.move(14, 14)
        self.scalebar.move(16, h - self.scalebar.height() - 16)
        self.secnav.move((w - self.secnav.width()) // 2, h - self.secnav.height() - 14)
        self.bc.move(w - self.bc.width() - 14, h - self.bc.height() - 14)
        for f in (self.badge, self.scalebar, self.secnav, self.bc):
            f.raise_()

    # --- representative backdrop (until the real field mounts) ------------
    def paintEvent(self, _event):
        if self._canvas_widget is not None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        tok = self._tok
        p.fillRect(self.rect(), QColor(tok["canvas_bg"]))

        # faint checker, like the mockup's tiled ground
        step = 22
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(tok["canvas_bg_2"]))
        for yy in range(0, h, step):
            for xx in range(0, w, step):
                if ((xx // step) + (yy // step)) % 2 == 0:
                    p.drawRect(xx, yy, step, step)

        # Demo backdrop hues below are representative EM/segmentation imagery —
        # NOT themeable chrome and NOT data the panel reads; they only exist
        # until set_canvas_widget() mounts the real field.
        # soft EM-ish blobs
        for fx, fy, fr, c in (
            (0.40, 0.44, 0.20, "#5b6675"),
            (0.66, 0.60, 0.26, "#474f5b"),
            (0.54, 0.30, 0.15, "#6a7280"),
        ):
            cx, cy, r = w * fx, h * fy, min(w, h) * fr
            g = QRadialGradient(cx, cy, r)
            g.setColorAt(0.0, QColor(c))
            base = QColor(c)
            base.setAlpha(0)
            g.setColorAt(1.0, base)
            p.setBrush(QBrush(g))
            p.drawEllipse(QPointF(cx, cy), r, r * 0.78)

        # translucent segmentation ellipses in data colors (screen blend)
        p.setCompositionMode(QPainter.CompositionMode_Screen)
        for fx, fy, fw, fh, c in (
            (0.30, 0.40, 0.22, 0.30, "#37c0a6"),
            (0.58, 0.56, 0.30, 0.34, "#5ab0f0"),
            (0.48, 0.26, 0.16, 0.20, "#f0a6d8"),
            (0.64, 0.36, 0.13, 0.17, "#f4bd4f"),
        ):
            col = QColor(c)
            col.setAlpha(120)
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(w * fx, h * fy, w * fw, h * fh))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.end()
