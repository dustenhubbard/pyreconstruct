"""The screen-fraction scale bar renders exactly as recorded.

The scale bar has two sizing models (`scale_bar_mode`). This module pins the
screen-fraction model with one digest over every screen-fraction bar the size
option can produce, across a wide zoom range and both display preferences.

`BASELINE_DIGEST` is a golden value and changes only on purpose. It was first
recorded at `e09d21c5`, before the mode toggle, and was unchanged by it.
It was recorded again when the bar became thin and map-like. The
ladder went to 1, 2, 5 per decade, the bar's thickness became an option (6 px
here, the default), and the ticks and their labels moved below the bar and
became outlined so that they read on a light image as well as a dark one.

The digest holds everything about the drawn bar that does not depend on the
font.  That is the widget's size, every `drawRect` (the bar, its inner fill
and the tick marks), every `drawLine`, the label string, and the tick label
strings. Glyph positions are computed from `QFontMetrics.boundingRect`,
so they would make the digest depend on which fonts the machine has; the
strings themselves do not. Which tick labels are printed does depend on the
font, because labels too close to fit are thinned out by their measured width,
so the sweep measures text with `_FixedMetrics`, a font-free stand-in.
"""
import hashlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect
from PySide6.QtGui import QPainter, QPixmap

from PyReconstruct.modules.gui.palette import scale_bar as sb_mod
from PyReconstruct.modules.gui.palette.scale_bar import ScaleBar


FIELD_W = 1000                      # field widget width, held constant
SLIDER_POSITIONS = range(20, 101)   # scale_bar_width's full range, 81 positions
# microns per screen pixel: from beyond a dense EM view out to beyond a whole
# section, wider on both ends than the six the ladder tests sweep
SCALES = (0.0007, 0.004, 0.01, 0.02, 0.04, 0.08, 0.16, 0.3, 1.0)
# both display preferences, both ways
TEXT_AND_TICKS = ((True, True), (True, False), (False, True), (False, False))

# recorded with the 1-2-5 ladder and the 6 px bar; see the module docstring
BASELINE_DIGEST = "c562c05257a56f8d2ec9776a52c59c384765e5e3c1b92245b907191dcaca8d9b"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(["test"])


class _StubSeries:
    """Only what paintEvent touches: the two display preferences."""

    def __init__(self, text=True, ticks=True):
        self._opts = {"show_scale_bar_text": text, "show_scale_bar_ticks": ticks}

    def getOption(self, name, *args, **kwargs):
        return self._opts[name]


class _StubManager:
    def __init__(self, **kwargs):
        self.series = _StubSeries(**kwargs)
        self.mainwindow = None


# The real painters, bound once at import. Re-reading them inside the sweep
# would chain each spy onto the previous one -- 2,916 frames deep by the end,
# which is a RecursionError, not a test result.
_REAL_RECT = QPainter.drawRect
_REAL_LINE = QPainter.drawLine
_REAL_TEXT = QPainter.drawText
_REAL_OUTLINED = sb_mod.drawOutlinedText


class _FixedMetrics:
    """QFontMetrics as if every glyph were 7 px wide and 12 px tall, so the
    digest is the same on a machine with Courier New and one without."""

    def __init__(self, font):
        pass

    def horizontalAdvance(self, text):
        return 7 * len(text)

    def boundingRect(self, text):
        return QRect(0, 0, 7 * len(text), 12)


def _install_spies(monkeypatch):
    """Collect everything drawn that a font cannot move. Installed once."""
    monkeypatch.setattr(sb_mod, "QFontMetrics", _FixedMetrics)
    collected = {"rects": [], "lines": [], "outlined": [], "plain": []}

    def spy_rect(painter, *args):
        collected["rects"].append(tuple(args))
        return _REAL_RECT(painter, *args)

    def spy_line(painter, *args):
        collected["lines"].append(tuple(args))
        return _REAL_LINE(painter, *args)

    def spy_text(painter, *args):
        if args and isinstance(args[-1], str):
            collected["plain"].append(args[-1])
        return _REAL_TEXT(painter, *args)

    def spy_outlined(painter, x, y, text):
        collected["outlined"].append(text)
        return _REAL_OUTLINED(painter, x, y, text)

    monkeypatch.setattr(QPainter, "drawRect", spy_rect)
    monkeypatch.setattr(QPainter, "drawLine", spy_line)
    monkeypatch.setattr(QPainter, "drawText", spy_text)
    monkeypatch.setattr(sb_mod, "drawOutlinedText", spy_outlined)
    return collected


def _render(bar, collected):
    """Paint for real and return everything drawn that a font cannot move."""
    for values in collected.values():
        values.clear()
    pixmap = QPixmap(bar.size())
    pixmap.fill()
    bar.render(pixmap)
    return (bar.width(), bar.height(),
            tuple(collected["rects"]), tuple(collected["lines"]),
            tuple(collected["outlined"]), tuple(collected["plain"]))


def _sweep(monkeypatch):
    """Every screen-fraction bar the option can produce, over the zoom range."""
    collected = _install_spies(monkeypatch)
    digest = hashlib.sha256()
    cases = 0
    for text, ticks in TEXT_AND_TICKS:
        for scale in SCALES:
            for pct in SLIDER_POSITIONS:
                # what MousePalette.createSB builds in screen-fraction mode
                sb_w = int(pct / 100 * FIELD_W)
                bar = ScaleBar(None, _StubManager(text=text, ticks=ticks),
                               sb_w, 6, 1)
                bar.setScale(scale)
                digest.update(
                    repr((text, ticks, scale, pct, _render(bar, collected))).encode()
                )
                cases += 1
                bar.deleteLater()
    return cases, digest.hexdigest()


def test_the_screen_fraction_bar_renders_exactly_as_it_did(app, monkeypatch):
    """2,916 rendered bars, one digest."""
    cases, digest = _sweep(monkeypatch)
    assert cases == 2916
    assert digest == BASELINE_DIGEST, (
        f"the screen-fraction bar changed; recorded as {BASELINE_DIGEST}, "
        f"now {digest}"
    )


def test_the_five_argument_constructor_still_means_screen_fraction(app):
    """The call `MousePalette.createSB` made before the change is still valid,
    and the bar it builds is not pinned to anything."""
    bar = ScaleBar(None, _StubManager(), 250, 6, 1)
    try:
        assert bar.width() == 250
        bar.setScale(0.02)
        assert bar.width() == 250, "a screen-fraction bar never resizes itself"
        assert getattr(bar, "micron_length", None) is None
    finally:
        bar.deleteLater()
