"""What the scale bar is allowed to render, pinned by painting it for real.

The screen-fraction bar never draws itself at the width the user asked for. It
cuts the bar back to the longest "nice" length that fits, so the number under it
is a round value. The ladder is 1, 2, 5 per decade, the steps a map's scale bar
takes. As the zoom changes the bar's width follows it, between 40 % and 100 % of
its widget, and when it would outgrow the widget the label steps to the next
rung. It used to be a twelve-rung ladder (1, 1.5, 2, 2.5 ... 10), kept here as
`TWELVE_RUNGS` and monkeypatched back in where a test needs to show that the
result comes from the 1-2-5 ladder.

Every test here goes through a real `paintEvent`: the widget is rendered into a
QPixmap with `QPainter.drawRect`, `QPainter.drawText` and the module's
`drawOutlinedText` intercepted, so the assertions are about pixels and strings
that a user would actually see, not about the arithmetic that produced them.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

import pytest

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QPixmap

from PyReconstruct.modules.gui.palette import scale_bar as sb_mod
from PyReconstruct.modules.gui.palette.scale_bar import (
    NICE_LENGTHS,
    TICK_SUBDIVISIONS,
    ScaleBar,
    formatLength,
    niceLength,
)


# the ladder the screen-fraction bar used before it took the 1-2-5 steps
TWELVE_RUNGS = TICK_SUBDIVISIONS

FIELD_W = 1000                    # field widget width, held constant
SLIDER_POSITIONS = range(20, 101)  # scale_bar_width's full range, 81 positions
# zoom levels in microns per screen pixel, from a dense EM view out to a
# whole-section view
SCALES = (0.004, 0.01, 0.02, 0.04, 0.08, 0.16)


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


def _make_bar(stored_width_pct, scale, **opts):
    """Build a ScaleBar exactly the way MousePalette.createSB does."""
    sb_w = int(stored_width_pct / 100 * FIELD_W)
    bar = ScaleBar(None, _StubManager(**opts), sb_w, 6, 1)
    bar.setScale(scale)
    return bar


def _probe(bar, monkeypatch):
    """Paint the widget; return (bar length in px, label, tick labels).

    The label and the tick labels are both outlined text, label first.
    """
    rects, outlined, plain = [], [], []

    real_rect = QPainter.drawRect
    real_text = QPainter.drawText
    real_outlined = sb_mod.drawOutlinedText

    def spy_rect(self, *args):
        if len(args) == 4:
            rects.append(tuple(args))
        return real_rect(self, *args)

    def spy_text(self, *args):
        if args and isinstance(args[-1], str):
            plain.append(args[-1])
        return real_text(self, *args)

    def spy_outlined(painter, x, y, text):
        outlined.append(text)
        return real_outlined(painter, x, y, text)

    monkeypatch.setattr(QPainter, "drawRect", spy_rect)
    monkeypatch.setattr(QPainter, "drawText", spy_text)
    monkeypatch.setattr(sb_mod, "drawOutlinedText", spy_outlined)

    pixmap = QPixmap(bar.size())
    pixmap.fill()
    bar.render(pixmap)

    return (rects[0][2] if rects else None,
            outlined[0] if outlined else None,
            tuple(outlined[1:]) + tuple(plain))


def _sweep(monkeypatch, scale):
    """Every rendered bar the width option can produce at one zoom level."""
    out = []
    for pct in SLIDER_POSITIONS:
        bar = _make_bar(pct, scale)
        out.append(_probe(bar, monkeypatch)[:2])
        bar.deleteLater()
    return out


def _longest_no_op_run(rendered):
    best = run = 1
    for i in range(1, len(rendered)):
        run = run + 1 if rendered[i] == rendered[i - 1] else 1
        best = max(best, run)
    return best


def _is_round(text):
    """Is this printed number in the class the scale bar has always used?

    Every number the bar has ever shown -- 1, 2.5, 5, 10 and their ticks 0.2,
    0.5, 1, 2 -- has an integer or half-integer mantissa. New rungs have to stay
    inside that class, which is what makes "the labels stay round" checkable.
    """
    value = abs(float(text))
    if value == 0:
        return True
    mantissa = value / 10.0 ** math.floor(math.log10(value))
    return abs(mantissa * 2 - round(mantissa * 2)) < 1e-6


def _is_one_two_five(text):
    value = float(text)
    mantissa = value / 10.0 ** math.floor(math.log10(value))
    return any(abs(mantissa - m) < 1e-6 for m in (1.0, 2.0, 5.0))


def _zoom_steps(lo=0.0005, hi=4.0, step=1.03):
    scale = lo
    while scale < hi:
        yield scale
        scale *= step


# ------------------------------------------------------------ the 1-2-5 steps

def test_the_ladder_is_one_two_five():
    assert [m for m, _ in NICE_LENGTHS] == [1.0, 2.0, 5.0, 10.0]


@pytest.mark.parametrize("pct", (20, 25, 60, 100))
def test_every_label_is_one_two_or_five(app, monkeypatch, pct):
    """Over about four decades of zoom, the printed length is always 1, 2 or 5
    times a power of ten."""
    for scale in _zoom_steps():
        bar = _make_bar(pct, scale)
        _, label, _ = _probe(bar, monkeypatch)
        assert label.endswith(" µm")
        assert _is_one_two_five(label.split()[0]), (pct, scale, label)
        bar.deleteLater()


def test_the_twelve_rung_ladder_printed_other_numbers(app, monkeypatch):
    """The previous ladder fails the check above."""
    with monkeypatch.context() as m:
        m.setattr(sb_mod, "NICE_LENGTHS", TWELVE_RUNGS)
        labels = set()
        for scale in _zoom_steps(0.01, 0.1):
            labels.add(_probe(_make_bar(25, scale), m)[1].split()[0])
    assert not all(_is_one_two_five(label) for label in labels), labels


@pytest.mark.parametrize("pct", (20, 25, 60, 100))
def test_the_bar_fills_between_two_fifths_and_all_of_its_size(
    app, monkeypatch, pct
):
    """1 to 2 and 5 to 10 are factors of two, 2 to 5 is 2.5, so the drawn bar
    is never under 40 % of the room it was given and never over it."""
    widths = []
    for scale in _zoom_steps():
        bar = _make_bar(pct, scale)
        bar_px, _, _ = _probe(bar, monkeypatch)
        assert 0.4 * bar.width() - 1 <= bar_px <= bar.width(), (pct, scale, bar_px)
        widths.append(bar_px / bar.width())
        bar.deleteLater()
    # and it uses that full band as the zoom changes
    assert min(widths) < 0.45 and max(widths) > 0.97


def test_zooming_in_grows_the_bar_until_the_label_steps_down(app, monkeypatch):
    """Zooming in a little at a time, the label does not change while the bar widens,
    then drops one rung (2.5x or 2x shorter) when it would outgrow its size."""
    seen = []
    scale = 0.2
    while scale > 0.002:
        bar = _make_bar(25, scale)
        seen.append(_probe(bar, monkeypatch)[:2])
        bar.deleteLater()
        scale /= 1.01
    for (px_a, label_a), (px_b, label_b) in zip(seen, seen[1:]):
        if label_a == label_b:
            assert px_b >= px_a, "the bar narrowed while zooming in"
        else:
            ratio = float(label_a.split()[0]) / float(label_b.split()[0])
            assert ratio == pytest.approx(2.0) or ratio == pytest.approx(2.5)
            assert px_b < px_a
    assert len({label for _px, label in seen}) >= 6


# ------------------------------------------------- conservative where it counts

@pytest.mark.parametrize("pct, scale, expected_px, expected_label", [
    (25, 0.004, 250, "1 µm"),      # l = 1 µm exactly
    (25, 0.01, 200, "2 µm"),       # l = 2.5 µm, cut back to 2 µm
    (25, 0.02, 250, "5 µm"),       # l = 5 µm exactly
    (100, 0.01, 1000, "10 µm"),    # l = 10 µm exactly
])
def test_a_width_on_a_rung_draws_it_and_one_between_is_cut_back(
    app, monkeypatch, pct, scale, expected_px, expected_label
):
    bar_px, label, _ = _probe(_make_bar(pct, scale), monkeypatch)
    assert (bar_px, label) == (expected_px, expected_label)


def test_the_bar_never_overruns_the_widget(app, monkeypatch):
    """A nice length is the longest that *fits*, so it can never overhang."""
    for scale in SCALES + (0.0007, 0.3, 1.0):
        for pct in SLIDER_POSITIONS:
            bar = _make_bar(pct, scale)
            bar_px, _, _ = _probe(bar, monkeypatch)
            assert 0 < bar_px <= bar.width()
            bar.deleteLater()


# ------------------------------------------------------------- round-ness rules

def test_every_rung_is_a_round_number():
    for mantissa, _ in TICK_SUBDIVISIONS:
        assert 1.0 <= mantissa <= 10.0
        assert _is_round(f"{mantissa:g}")
    assert list(TICK_SUBDIVISIONS) == sorted(TICK_SUBDIVISIONS)
    assert set(NICE_LENGTHS) <= set(TICK_SUBDIVISIONS)


def test_every_rung_is_ticked_into_round_numbers():
    """The subdivision count is per rung precisely so this holds.

    A fixed five subdivisions turns the 3 µm entry into 0.6 / 1.2 / 1.8 /
    2.4 µm ticks. The screen-fraction bar only uses 1, 2 and 5 now, but a
    pinned bar can be any length in the table.
    """
    for mantissa, subdivs in TICK_SUBDIVISIONS:
        assert 2 <= subdivs <= 7, "more than six tick labels will not fit"
        for i in range(1, subdivs):
            assert _is_round(formatLength(mantissa * i / subdivs)), (
                f"rung {mantissa:g} in {subdivs} gives an odd tick"
            )


def test_a_rendered_bar_and_its_ticks_are_all_round(app, monkeypatch):
    """The same check, but on the strings a real paint puts on screen."""
    scale = 0.0005
    while scale < 4.0:
        bar = _make_bar(25, scale)
        _, label, ticks = _probe(bar, monkeypatch)
        assert label.endswith(" µm")
        assert _is_round(label.split()[0])
        for tick in ticks:
            assert _is_round(tick)
        bar.deleteLater()
        scale *= 1.07


def test_the_ticks_follow_the_rung_not_a_fixed_five(app, monkeypatch):
    """A 2 µm bar is cut in four (0.5 µm ticks), not in five (0.4 µm)."""
    _, label, ticks = _probe(_make_bar(50, 0.04), monkeypatch)
    assert label == "20 µm"
    assert ticks == ("5", "10", "15")


# ------------------------------------------------------------ label formatting

def test_one_length_has_one_spelling(app, monkeypatch):
    """The 10 µm bar used to print "10 µm" or "10.0 µm" depending on the zoom.

    `n * 10 ** (-p)` returned an int on one side of a decade and a float on the
    other, and the label was `str()` of that. So the same bar, at the same
    length, printed two ways.
    """
    spellings = {}
    scale = 0.0005
    while scale < 4.0:
        for pct in (20, 25, 40, 60, 100):
            bar = _make_bar(pct, scale)
            bar_px, label, _ = _probe(bar, monkeypatch)
            length = round(niceLength(bar.width() * scale)[0], 10)
            spellings.setdefault(length, set()).add(label)
            bar.deleteLater()
        scale *= 1.11
    doubled = {k: v for k, v in spellings.items() if len(v) > 1}
    assert not doubled, f"one length printed more than one way: {doubled}"


@pytest.mark.parametrize("value, text", [
    (10.0, "10"),
    (1.0, "1"),
    (2.5, "2.5"),
    (0.5, "0.5"),
    (0.25, "0.25"),
    (1000.0, "1000"),
    (0.30000000000000004, "0.3"),   # what 3 x 0.1 actually is
    (0.000001, "0.000001"),         # never in scientific notation
])
def test_lengths_print_without_trailing_zeros(value, text):
    assert formatLength(value) == text


def test_tick_labels_use_the_same_formatter(app, monkeypatch):
    """Ticks printed "2.0" where the bar printed "10"; now both print plainly."""
    _, label, ticks = _probe(_make_bar(100, 0.01), monkeypatch)
    assert label == "10 µm"
    assert ticks == ("2", "4", "6", "8")


# ------------------------------------------------------------------ the corners

def test_a_length_that_is_exactly_a_rung_lands_on_it():
    """A length that is a rung must pick that rung, whatever the float error
    in dividing it by its decade."""
    assert niceLength(0.2)[0] == pytest.approx(0.2)
    assert niceLength(2.0)[0] == pytest.approx(2.0)
    assert niceLength(50.0)[0] == pytest.approx(50.0)
    assert niceLength(0.05)[0] == pytest.approx(0.05)
    assert niceLength(0.6 / 3)[0] == pytest.approx(0.2)    # 1.9999999999999998 decades of 0.1
    assert niceLength(0.7 / 7 * 5)[0] == pytest.approx(0.5)  # 4.999999999999999 of 0.1


def test_a_length_just_under_a_rung_takes_the_one_below():
    assert niceLength(1.999)[0] == pytest.approx(1.0)
    assert niceLength(4.999)[0] == pytest.approx(2.0)
    assert niceLength(0.99)[0] == pytest.approx(0.5)


def test_nothing_to_draw_is_not_an_error(app, monkeypatch):
    """A zero scale or a zero width has no bar in it, and must not raise.

    Without the guard this is a log10 domain error -- and before the rewrite it
    was an infinite loop in paintEvent, which is worse.
    """
    assert niceLength(0.0) == (0.0, 0)
    assert niceLength(-1.0) == (0.0, 0)

    rendered = _probe(_make_bar(25, 0.0), monkeypatch)
    assert rendered == (None, None, ())


# ------------------------------------------------------- preferences still hold

def test_the_text_and_tick_preferences_still_switch_things_off(app, monkeypatch):
    bar_px, label, ticks = _probe(
        _make_bar(60, 0.02, text=False, ticks=False), monkeypatch
    )
    assert bar_px and label is None and ticks == ()

    bar_px, label, ticks = _probe(
        _make_bar(60, 0.02, text=True, ticks=False), monkeypatch
    )
    assert label and ticks == ()

    bar_px, label, ticks = _probe(
        _make_bar(60, 0.02, text=False, ticks=True), monkeypatch
    )
    assert label is None and ticks == ()   # tick labels ride on the text option
