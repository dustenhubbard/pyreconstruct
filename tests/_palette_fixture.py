"""Headless fixture for the floating tool palette.

Builds a real :class:`MousePalette` tool card against a minimal fake main
window + series, without dragging in the heavy trace-palette / scale-bar /
brightness machinery. Both ``test_tool_palette.py`` and the offscreen preview
script use this, so the preview renders the *same* code the tests cover.
"""
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QAction, QPainter, QColor, QRadialGradient, QBrush
from PySide6.QtCore import Qt, QRectF

from PyReconstruct.modules.gui.palette.mouse_palette import MousePalette
from PyReconstruct.modules.gui.utils import theme


# Sensible stand-ins for the series options the tool card reads. Shortcut keys
# mirror PyReconstruct/modules/datatypes/default_settings.py so the keycaps in
# the preview match what the app actually shows.
_DEFAULTS = {
    "left_handed": False,
    "usepointer_act": "P",
    "usepanzoom_act": "Z",
    "useknife_act": "K",
    "usectrace_act": "C",
    "useotrace_act": "O",
    "usestamp_act": "S",
    "usegrid_act": "G",
    "useflag_act": "F",
    "usehost_act": "Q",
    "flag_name": "flag",
    "flag_color": (255, 80, 80),
    "flag_size": 14,
    "show_flags": "all",
}


class FakeSeries:
    def __init__(self, opts=None):
        self.opts = dict(opts or {})

    def getOption(self, key, *args):
        if key in self.opts:
            return self.opts[key]
        return _DEFAULTS.get(key)

    def setOption(self, key, value):
        self.opts[key] = value


class _FieldBg(QWidget):
    """A stand-in field that paints an EM-like backdrop, so the translucent
    palette card reads against realistic content in the preview."""

    def __init__(self, parent, scheme):
        super().__init__(parent)
        self._scheme = scheme

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()
        grad = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.7)
        if self._scheme == "light":
            grad.setColorAt(0.0, QColor("#e9eef7"))
            grad.setColorAt(0.7, QColor("#d6deea"))
            grad.setColorAt(1.0, QColor("#c4cedd"))
            blobs = [("#9ec5ff", 0.20), ("#ffd0e2", 0.18)]
        else:
            grad.setColorAt(0.0, QColor("#1a222e"))
            grad.setColorAt(0.68, QColor("#0d1219"))
            grad.setColorAt(1.0, QColor("#05070a"))
            blobs = [("#37c6ff", 0.16), ("#ff5d9e", 0.16), ("#42e08b", 0.14)]
        p.fillRect(r, QBrush(grad))
        # a few faint "cells" so the card has texture behind it
        cx, cy, w, h = r.x(), r.y(), r.width(), r.height()
        spots = [(0.30, 0.40, 0.26), (0.62, 0.62, 0.30), (0.50, 0.22, 0.18)]
        for (fx, fy, fr), (col, alpha) in zip(spots, blobs * 2):
            c = QColor(col)
            c.setAlphaF(alpha)
            rad = fr * min(w, h)
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(cx + fx * w - rad, cy + fy * h - rad * 0.8,
                                 rad * 2, rad * 1.6))
        p.end()


class FakeMainWindow(QWidget):
    def __init__(self, series, field_size, scheme):
        super().__init__()
        self.series = series
        self.resize(field_size[0], field_size[1])
        self.field = _FieldBg(self, scheme)
        self.field.setGeometry(0, 0, field_size[0], field_size[1])
        self.field.section = SimpleNamespace(
            selected_flags=[], brightness=0, contrast=0)
        self.lefthanded_act = QAction(self)
        self.lefthanded_act.setCheckable(True)
        self.last_mouse_mode = None

    # methods the tool card may call
    def changeMouseMode(self, mode):
        self.last_mouse_mode = mode

    def modifyPointer(self):
        pass

    def changeTraceMode(self):
        pass

    def modifyGrid(self):
        pass

    def modifyKnife(self):
        pass


def make_palette(left_handed=False, scheme=None, field_size=(900, 600)):
    """Build a tool-palette card headlessly.

    Returns ``(app, mainwindow, palette, restore)``. ``scheme`` (``"dark"`` /
    ``"light"``) pins the rendered theme by patching ``theme.current_scheme``;
    call the returned ``restore()`` (or ``None``) when finished to undo it.
    """
    app = QApplication.instance() or QApplication([])

    restore = None
    if scheme is not None:
        _orig = theme.current_scheme
        theme.current_scheme = lambda *a, **k: scheme

        def restore():
            theme.current_scheme = _orig

    series = FakeSeries({"left_handed": left_handed})
    mw = FakeMainWindow(series, field_size, scheme or "dark")

    mp = MousePalette.__new__(MousePalette)
    mp.mainwindow = mw
    mp.series = series
    mp.mblen = 38
    mp.is_dragging = False
    mp._tokens = theme.tokens()
    mp.mode_x = 0.99
    mp.mode_y = 0.01
    mp.mode_buttons = {}
    mp.selected_mode = "pointer"
    mp.createPaletteCard()

    return app, mw, mp, restore
