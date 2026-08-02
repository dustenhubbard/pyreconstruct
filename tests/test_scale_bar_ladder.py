"""What the scale bar is allowed to render, pinned by painting it for real.

The scale bar never draws itself at the width the user asked for. It cuts the
bar back to the longest "nice" length that fits, so the number under it is a
round value. That ladder used to be 1 / 2.5 / 5 / 10 per decade -- four rungs,
against a width option with 81 positions (20..100 %) -- so most of the option's
travel changed nothing on screen. Measured on d0eb01a9 by rendering the real
widget: 3 to 4 of the 81 positions produced a different bar, with runs of up to
51 consecutive positions that rendered byte-identically. Two of those "4"
were the same bar printed two different ways (see the label tests below).

Every test here goes through a real `paintEvent`: the widget is rendered into a
QPixmap with `QPainter.drawRect`, `QPainter.drawText` and the module's
`drawOutlinedText` intercepted, so the assertions are about pixels and strings
that a user would actually see, not about the arithmetic that produced them.
`_probe` is the same interception the measurement script uses
(pyrecon-hub scripts/scale_bar_ladder_candidates.py), so a number here can be
compared directly with a number in the PR's ladder table.

The old ladder is kept as `OLD_LADDER` and monkeypatched back in where a test
needs to show that the new one is doing the work.
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
    ScaleBar,
    formatLength,
    niceLength,
)


# the ladder that shipped before this change: four rungs, all ticked in five
OLD_LADDER = ((1.0, 5), (2.5, 5), (5.0, 5), (10.0, 5))

FIELD_W = 1000                    # field widget width, held constant
SLIDER_POSITIONS = range(20, 101)  # scale_bar_width's full range, 81 positions
# zoom levels in microns per screen pixel, from a dense EM view out to a
# whole-section view; the same six the d0eb01a9 measurement used
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
    bar = ScaleBar(None, _StubManager(**opts), sb_w, 50, 1)
    bar.setScale(scale)
    return bar


def _probe(bar, monkeypatch):
    """Render for real; return (bar length in px, label, tick labels)."""
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
            tuple(plain))


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


# --------------------------------------------------------------- the dead zone

@pytest.mark.parametrize("scale", SCALES)
def test_the_width_option_now_moves_the_bar_at_every_zoom(app, monkeypatch, scale):
    """The headline: how many of the 81 positions render a different bar."""
    with monkeypatch.context() as m:
        m.setattr(sb_mod, "NICE_LENGTHS", OLD_LADDER)
        before = _sweep(m, scale)
    after = _sweep(monkeypatch, scale)

    assert len(set(before)) <= 4, "the old ladder was not as coarse as recorded"
    assert len(set(after)) >= 8
    assert len(set(after)) > len(set(before))
    assert _longest_no_op_run(after) < _longest_no_op_run(before)


def test_the_two_widths_from_the_report_no_longer_render_the_same_bar(
    app, monkeypatch
):
    """25 % and 40 % at 0.02 µm/px drew byte-identical 250 px bars on d0eb01a9."""
    with monkeypatch.context() as m:
        m.setattr(sb_mod, "NICE_LENGTHS", OLD_LADDER)
        old_25 = _probe(_make_bar(25, 0.02), m)
        old_40 = _probe(_make_bar(40, 0.02), m)
    assert old_25[:2] == old_40[:2] == (250, "5 µm")

    new_25 = _probe(_make_bar(25, 0.02), monkeypatch)
    new_40 = _probe(_make_bar(40, 0.02), monkeypatch)
    assert new_25[:2] != new_40[:2]
    assert new_40[:2] == (400, "8 µm")


# ------------------------------------------------- conservative where it counts

@pytest.mark.parametrize("pct, scale, expected_px, expected_label", [
    (25, 0.004, 250, "1 µm"),      # l = 1 µm exactly
    (25, 0.01, 250, "2.5 µm"),     # l = 2.5 µm exactly
    (25, 0.02, 250, "5 µm"),       # l = 5 µm exactly
    (100, 0.01, 1000, "10 µm"),    # l = 10 µm exactly
])
def test_a_width_that_already_landed_on_a_rung_is_untouched(
    app, monkeypatch, pct, scale, expected_px, expected_label
):
    """The four rungs the two ladders share still render the lengths they did.

    1, 2.5, 5 and 10 are the whole of the old ladder, and all four survive into
    the new one, so a width that already landed on one draws the same number of
    pixels it drew on d0eb01a9. The pixel figures are the ones the d0eb01a9
    probe recorded. What moves is spelling: the bar label loses a trailing zero
    where it had one ("1.0 µm" -> "1 µm", and "2.5 µm" is unchanged because it
    never had one), and the tick labels lose theirs too ("1.0" -> "1"). Both are
    the formatting fix below.

    Widths that landed between the old rungs are a different matter and are not
    pinned here: 50 % at 0.04 µm/px drew a 250 px "10 µm" bar on d0eb01a9 and
    draws a 500 px "20 µm" bar now, because 2.0 is a rung of the new ladder and
    was not one of the old. That is what the finer ladder is for.
    """
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
    for mantissa, _ in NICE_LENGTHS:
        assert 1.0 <= mantissa <= 10.0
        assert _is_round(f"{mantissa:g}")
    assert list(NICE_LENGTHS) == sorted(NICE_LENGTHS)


def test_every_rung_is_ticked_into_round_numbers():
    """The subdivision count is per rung precisely so this holds.

    A fixed five subdivisions -- what the code did before -- turns the 3 µm rung
    into 0.6 / 1.2 / 1.8 / 2.4 µm ticks.
    """
    for mantissa, subdivs in NICE_LENGTHS:
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
    length, printed two ways -- which also inflated the dead-zone count, because
    two of the four "distinct" renders at 0.02 µm/px were one bar spelled twice.
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
    """0.3 is 2.9999999999999996 decades of 0.1, and must still pick the 3 rung."""
    assert niceLength(0.3)[0] == pytest.approx(0.3)
    assert niceLength(3.0)[0] == pytest.approx(3.0)
    assert niceLength(30.0)[0] == pytest.approx(30.0)
    assert niceLength(7.0)[0] == pytest.approx(7.0)
    assert niceLength(0.07)[0] == pytest.approx(0.07)


def test_a_length_just_under_a_rung_takes_the_one_below():
    assert niceLength(2.999)[0] == pytest.approx(2.5)
    assert niceLength(0.99)[0] == pytest.approx(0.9)


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
