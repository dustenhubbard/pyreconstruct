"""The scale bar paints through `paintScaleBar`, on screen and at any scale.

The widget draws through the function at scale 1 with the default sizes, and
must look exactly as it did before the function existed.  The reference is
the widget as it was on main at d7f371c5, kept verbatim in
`tests/fixtures/scale_bar_d7f371c5.py` (only its one relative import is made
absolute so it loads from there).  Both widgets render on the same machine
with the same fonts, so the comparison is pixel for pixel without a golden
image that would depend on which fonts a machine has.
"""
import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.gui.palette import scale_bar as sb_mod
from PyReconstruct.modules.gui.utils import fonts
from PyReconstruct.modules.gui.palette.scale_bar import (
    ScaleBar,
    barLayout,
    labelText,
    paintScaleBar,
)


_MAIN_FILE = Path(__file__).parent / "fixtures" / "scale_bar_d7f371c5.py"


def _load_main():
    spec = importlib.util.spec_from_file_location("scale_bar_d7f371c5", _MAIN_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


main_sb = _load_main()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(["test"])


class _StubSeries:
    """Only what the bar reads: the two display preferences."""

    def __init__(self, text=True, ticks=True):
        self._opts = {"show_scale_bar_text": text, "show_scale_bar_ticks": ticks}

    def getOption(self, name, *args, **kwargs):
        return self._opts[name]


class _StubManager:
    def __init__(self, **kwargs):
        self.series = _StubSeries(**kwargs)
        self.mainwindow = None


def _default(bar):
    pass


def _manual_length(bar):
    # what the bar's right-click length does: a length the user typed, with
    # the field's width as room
    bar.setOverride(3.0, 1000)


def _thick(bar):
    bar.setThickness(14)


STATES = {
    "default": _default,
    "manual length": _manual_length,
    "thickness": _thick,
}


def _widget_image(cls, state, text=True, ticks=True):
    """Build a bar as MousePalette.createSB does, put it in `state`, render it."""
    bar = cls(None, _StubManager(text=text, ticks=ticks), 300, 6, 1)
    bar.setScale(0.02)
    STATES[state](bar)
    image = QImage(bar.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    bar.render(image)
    bar.deleteLater()
    return image


def _opaque(image, x, y):
    return image.pixelColor(x, y).alpha() > 0


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("text,ticks", [(True, True), (False, False)])
def test_the_widget_draws_exactly_as_it_did_on_main(app, monkeypatch, state,
                                                     text, ticks):
    # the frozen copy draws in Courier New; a macOS Dev checkout sets the bar
    # in the Mac look's monospace (tests/test_mac_system_fonts.py), so compare
    # the two with that look off
    monkeypatch.setattr(fonts, "macLook", lambda: False)
    before = _widget_image(main_sb.ScaleBar, state, text, ticks)
    after = _widget_image(ScaleBar, state, text, ticks)
    assert after.size() == before.size()
    # something was drawn, so equal is not two blank images
    assert any(_opaque(before, x, before.height() // 2)
               for x in range(before.width()))
    assert after == before, f"the {state} bar no longer matches main"


def _paint(scale, label_size, real_len=2.0, units_per_pixel=0.02, thickness=6):
    """Draw a bar through the function onto a transparent image."""
    width, height = 400 * scale, 200 * scale
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    drawn = paintScaleBar(painter, real_len, 4, units_per_pixel, thickness,
                          True, True, scale=scale, label_size=label_size)
    assert painter.worldTransform().isIdentity(), "the painter is left scaled"
    painter.end()
    return image, drawn


def _bar_run(image, y):
    """How many opaque pixels run from the left edge along row `y`."""
    x = 0
    while x < image.width() and _opaque(image, x, y):
        x += 1
    return x


def _ink_width(image, top, bottom):
    """How wide the ink is between rows `top` and `bottom`."""
    cols = [x for x in range(image.width())
            if any(_opaque(image, x, y) for y in range(top, bottom))]
    return cols[-1] - cols[0] + 1


def test_at_scale_3_the_bar_is_three_times_as_wide(app):
    thickness, label_size = 6, 16
    bar_top = barLayout(thickness, True, True, label_size)[0]
    one, _ = _paint(1, label_size)
    three, drawn = _paint(3, label_size)
    pix_len = int(2.0 / 0.02)
    # the middle row of the bar: no label above, no tick below
    assert _bar_run(one, bar_top + thickness // 2) == pix_len
    assert _bar_run(three, 3 * (bar_top + thickness // 2)) == 3 * pix_len
    assert drawn[0] == pix_len, "the size returned is before the scale"


def test_at_scale_3_the_label_is_drawn_at_the_asked_size(app, monkeypatch):
    """The label's font is the size asked for, under a 3x painter, and its
    ink is as wide as the same text set directly at three times that size."""
    label_size = 16
    seen = []
    real_outlined = sb_mod.drawOutlinedText

    def spy(painter, x, y, text):
        seen.append((text, painter.font().pixelSize(),
                     painter.worldTransform().m11()))
        return real_outlined(painter, x, y, text)

    monkeypatch.setattr(sb_mod, "drawOutlinedText", spy)
    three, _ = _paint(3, label_size)
    assert (labelText(2.0), label_size, 3.0) in seen

    # the label's ink width, above the bar.  Width, not height: the tail of
    # the µ reaches down into the bar
    bar_top = barLayout(6, True, True, label_size)[0]
    drawn_width = _ink_width(three, 0, 3 * bar_top)

    # the same text set at 48 with no scale, for comparison
    reference = QImage(400, 200, QImage.Format_ARGB32_Premultiplied)
    reference.fill(Qt.transparent)
    painter = QPainter(reference)
    real_outlined(painter, 10, 100, labelText(2.0), size=3 * label_size)
    painter.end()
    reference_width = _ink_width(reference, 0, 200)

    # glyph hinting differs a little between a scaled 16 and a plain 48
    assert abs(drawn_width - reference_width) <= 0.05 * reference_width, (
        drawn_width, reference_width
    )
    # and it is plainly wider than the on-screen label size at scale 3
    default, _ = _paint(3, sb_mod.LABEL_SIZE)
    default_top = barLayout(6, True, True)[0]
    assert drawn_width > 1.2 * _ink_width(default, 0, 3 * default_top)


def test_a_larger_label_gets_a_taller_band(app):
    """The label band grows with the label, so a large label stays above the
    bar; at the default sizes the layout is the widget's own."""
    assert barLayout(6, True, True) == (sb_mod.LABEL_ROOM,
                                        sb_mod.LABEL_ROOM + 6 + sb_mod.TICK_LENGTH,
                                        sb_mod.LABEL_ROOM + 6 + sb_mod.TICK_LENGTH
                                        + sb_mod.TICK_LABEL_ROOM)
    assert barLayout(6, True, True, 24)[0] == 2 * sb_mod.LABEL_ROOM


def test_no_length_draws_nothing(app):
    image = QImage(50, 50, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    assert paintScaleBar(painter, 0.0, 0, 0.02, 6, True, True) == (0, 0)
    painter.end()
    assert not any(_opaque(image, x, y) for x in range(50) for y in range(50))
