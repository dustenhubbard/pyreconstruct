"""The scale bar's second sizing model: a fixed length in microns.

The bar has always been sized as a share of the field, with the micron figure
under it recomputed from the zoom -- one stored number, a different label at
every zoom. Imaging software conventionally does the opposite: the reader picks
a length in microns and the bar's pixel width follows the zoom. Neither is
wrong, so both ship, chosen by ``scale_bar_mode``.

The half of the promise that lives elsewhere is that nothing changes for anyone
who does not opt in; ``test_scale_bar_screen_fraction_unchanged.py`` proves that
by digest against the tree before this change. This module is about the new
mode, and most of it is about its edges, because that is where the design
decision is.

**The clamping decision.** ``micron_length / scale`` is unbounded in both
directions: zoomed out it falls to a few pixels, zoomed in it runs off the side
of the field. Clamping the *pixel* width -- the obvious move -- would leave a
bar whose drawn rule no longer measures the number printed under it, which on a
figure is worse than no scale bar at all. So the pixel width is never clamped
alone. When the requested length will not fit the drawable range, the length
itself steps by a whole decade and the label steps with it: 5 µm becomes 0.5 µm
or 50 µm, never 4 µm or 6 µm. The mantissa the user chose is invariant, so the
bar still reads as their number, and ``drawn pixels == labelled length / scale``
holds at every zoom. That last equality is the invariant these tests exist to
defend, and it is asserted on rendered output, not on the arithmetic.

This deliberately does not reuse ``NICE_LENGTHS``. That ladder snaps a
screen-fraction bar down to a round number, which would replace the user's
chosen length rather than rescale it.
"""
import math
import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QPixmap

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.default_settings import (
    MAX_PINNED_UM,
    MIN_PINNED_UM,
    default_settings,
    validPinnedLength,
)
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from PyReconstruct.modules.gui.palette import scale_bar as sb_mod
from PyReconstruct.modules.gui.palette.mouse_palette import MousePalette
from PyReconstruct.modules.gui.palette.scale_bar import (
    MIN_PINNED_PIXELS,
    NICE_LENGTHS,
    ScaleBar,
    formatLength,
    pinnedLength,
    pinnedSubdivisions,
)

FIELD_W = 560          # the width the suite's real MainWindow field reports
ROOM = FIELD_W         # how much room a pinned bar is given

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev",
    "assets", "checker", "files", "shapes1.jser",
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(["test"])


def _series(tmp_path):
    """A real series backed by an in-memory settings store (no QSettings I/O)."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    os.makedirs(tmp_path, exist_ok=True)
    fp = os.path.join(str(tmp_path), "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(DictSettingsStore())
    return series


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


class _StubPalette:
    """Enough of a MousePalette for `getPinnedLength`, which reads two options
    and touches nothing else. Borrowing the real method rather than restating it
    keeps these tests pointed at the shipping code."""

    getPinnedLength = MousePalette.getPinnedLength

    def __init__(self, series):
        self.series = series


_REAL_RECT = QPainter.drawRect
_REAL_TEXT = QPainter.drawText
_REAL_OUTLINED = sb_mod.drawOutlinedText


def _install_spies(monkeypatch):
    """Installed once per test: re-reading the originals inside a sweep chains
    each spy onto the last and ends in a RecursionError."""
    collected = {"rects": [], "outlined": [], "plain": []}

    def spy_rect(painter, *args):
        if len(args) == 4:
            collected["rects"].append(tuple(args))
        return _REAL_RECT(painter, *args)

    def spy_text(painter, *args):
        if args and isinstance(args[-1], str):
            collected["plain"].append(args[-1])
        return _REAL_TEXT(painter, *args)

    def spy_outlined(painter, x, y, text):
        collected["outlined"].append(text)
        return _REAL_OUTLINED(painter, x, y, text)

    monkeypatch.setattr(QPainter, "drawRect", spy_rect)
    monkeypatch.setattr(QPainter, "drawText", spy_text)
    monkeypatch.setattr(sb_mod, "drawOutlinedText", spy_outlined)
    return collected


def _render(bar, collected):
    """Paint for real; return (bar length in px, label, tick labels)."""
    for values in collected.values():
        values.clear()
    pixmap = QPixmap(bar.size())
    pixmap.fill()
    bar.render(pixmap)
    return (collected["rects"][0][2] if collected["rects"] else None,
            collected["outlined"][0] if collected["outlined"] else None,
            tuple(collected["plain"]))


def _pinned_bar(micron_length, scale, room=ROOM, **opts):
    """Build a pinned ScaleBar exactly the way MousePalette.createSB does."""
    bar = ScaleBar(None, _StubManager(**opts), room, 50, 1,
                   micron_length=micron_length, max_pixel_length=room)
    bar.setScale(scale)
    return bar


def _mantissa(value):
    return value / 10.0 ** math.floor(math.log10(value))


def _zoom_sweep(lo=1e-6, hi=1e4, step=1.6):
    """Fourteen decades of zoom, in microns per pixel."""
    scale = lo
    while scale < hi:
        yield scale
        scale *= step


# --------------------------------------------------------------- the invariant

@pytest.mark.parametrize("micron_length", [5.0, 2.0, 1.0, 0.5, 3.7, 12.0])
def test_the_bar_always_measures_exactly_what_it_says(micron_length):
    """The one rule that must never break, over fourteen decades of zoom.

    Whatever the clamp does, the drawn rule and the printed number have to agree,
    or the bar is a lie on a figure.
    """
    for scale in _zoom_sweep():
        real_len, pix_len = pinnedLength(micron_length, scale, ROOM)
        assert real_len > 0 and pix_len > 0, (micron_length, scale)
        assert pix_len == int(real_len / scale), (micron_length, scale)


@pytest.mark.parametrize("micron_length", [5.0, 2.0, 1.0, 0.5, 3.7, 12.0])
def test_the_bar_never_overruns_the_room_it_was_given(micron_length):
    for scale in _zoom_sweep():
        _real_len, pix_len = pinnedLength(micron_length, scale, ROOM)
        assert 0 < pix_len <= ROOM, (micron_length, scale, pix_len)


@pytest.mark.parametrize("micron_length", [5.0, 2.0, 1.0, 0.5, 3.7, 12.0])
def test_only_the_decade_ever_moves(micron_length):
    """The clamp rescales the user's length; it never substitutes another one."""
    wanted = _mantissa(micron_length)
    for scale in _zoom_sweep():
        real_len, _pix_len = pinnedLength(micron_length, scale, ROOM)
        assert _mantissa(real_len) == pytest.approx(wanted, rel=1e-9), (
            f"{micron_length} µm became {formatLength(real_len)} µm at {scale}"
        )
        decades = math.log10(real_len / micron_length)
        assert abs(decades - round(decades)) < 1e-9, (
            f"{formatLength(real_len)} is not a whole decade of {micron_length}"
        )


# ------------------------------------------------------- the untouched middle

def test_the_number_does_not_move_across_the_working_zoom_band():
    """The whole point of the mode: over the range where 5 µm fits legibly, the
    label is 5 µm at every zoom and only the pixel width moves.

    With 560 px of room and a 40 px floor that band is
    5/560 = 0.00893 to 5/40 = 0.125 µm/px, a 14x zoom range.
    """
    lengths, widths = set(), set()
    scale = 5.0 / ROOM
    while scale <= 5.0 / MIN_PINNED_PIXELS:
        real_len, pix_len = pinnedLength(5.0, scale, ROOM)
        lengths.add(real_len)
        widths.add(pix_len)
        scale *= 1.02
    assert lengths == {5.0}
    assert min(widths) == MIN_PINNED_PIXELS and max(widths) == ROOM
    assert len(widths) > 100, "the pixel width is what is supposed to be moving"


def test_the_ends_of_that_band_are_where_the_first_step_happens():
    """One pixel past either end, and the length steps a decade."""
    just_inside_out = 5.0 / MIN_PINNED_PIXELS
    assert pinnedLength(5.0, just_inside_out, ROOM) == (5.0, MIN_PINNED_PIXELS)
    assert pinnedLength(5.0, just_inside_out * 1.05, ROOM)[0] == 50.0

    just_inside_in = 5.0 / ROOM
    assert pinnedLength(5.0, just_inside_in, ROOM) == (5.0, ROOM)
    assert pinnedLength(5.0, just_inside_in * 0.95, ROOM)[0] == 0.5


# ------------------------------------------------------------- the two extremes

@pytest.mark.parametrize("scale, expected_um, expected_px", [
    # a 5 µm bar wanted at these zoom-outs, and what it becomes.
    # "ideal" is 5/scale, the width the bar would have to be to stay 5 µm.
    (0.2,    50.0,    250),    # ideal 25 px    -> one decade up
    (1.0,    50.0,     50),    # ideal 5 px     -> one decade up
    (10.0,   500.0,    50),    # ideal 0.5 px   -> two decades up
    (100.0,  5000.0,   50),    # ideal 0.05 px  -> three decades up
    (1000.0, 50000.0,  50),    # ideal 0.005 px -> four decades up
])
def test_zoomed_far_out_the_length_steps_up_in_decades(scale, expected_um, expected_px):
    real_len, pix_len = pinnedLength(5.0, scale, ROOM)
    assert (real_len, pix_len) == (expected_um, expected_px)
    assert pix_len >= MIN_PINNED_PIXELS, "still legible"
    assert formatLength(real_len).lstrip("0.") .startswith("5")


@pytest.mark.parametrize("scale, expected_um, expected_px", [
    # the same 5 µm bar at these zoom-ins. "ideal" is again 5/scale.
    # The 499 is not a clamp: 0.005/1e-5 is 499.99999999999994 in binary
    # floating point, and the pixel length is truncated with int() -- the same
    # int() paintEvent has always used, which is why pinnedLength truncates
    # rather than rounds. One pixel, and the bar still measures its label.
    (0.005,   5.0,    1000),   # ideal 1000 px -- fits 1000 px of room exactly
    (0.001,   0.5,     500),   # ideal 5000 px    -> one decade down
    (0.0001,  0.05,    500),   # ideal 50000 px   -> two decades down
    (1e-5,    0.005,   499),   # ideal 500000 px  -> three decades down
    (1e-6,    0.0005,  500),   # ideal 5000000 px -> four decades down
])
def test_zoomed_far_in_the_length_steps_down_in_decades(scale, expected_um, expected_px):
    room = 1000
    real_len, pix_len = pinnedLength(5.0, scale, room)
    assert (real_len, pix_len) == (expected_um, expected_px)
    assert pix_len <= room, "never off the side of the field"


def test_the_first_step_out_is_taken_only_when_it_has_to_be():
    """Between 41 and 559 px the bar is left exactly alone; the step is not
    early and not late."""
    assert pinnedLength(5.0, 5.0 / 41, ROOM) == (5.0, 41)
    assert pinnedLength(5.0, 5.0 / 559, ROOM) == (5.0, 559)


def test_a_field_too_narrow_for_a_whole_decade_still_never_overruns():
    """When the room is less than ten times the legibility floor there may be no
    decade that satisfies both bounds. Fitting wins: a bar that overruns the
    field is clipped and lies about its length, a bar that is short is only hard
    to read.
    """
    narrow = 100     # 2.5x the 40 px floor, so decades cannot always land inside
    seen_below_floor = False
    for scale in _zoom_sweep():
        real_len, pix_len = pinnedLength(5.0, scale, narrow)
        assert 0 < pix_len <= narrow, (scale, pix_len)
        assert pix_len == int(real_len / scale)
        if pix_len < MIN_PINNED_PIXELS:
            seen_below_floor = True
    assert seen_below_floor, "this test is pointless if the floor is never missed"


def test_nothing_to_draw_is_not_an_error():
    """Same contract as niceLength: (0.0, 0), no exception, no log10 domain error."""
    assert pinnedLength(5.0, 0.0, ROOM) == (0.0, 0)
    assert pinnedLength(5.0, -1.0, ROOM) == (0.0, 0)
    assert pinnedLength(0.0, 0.02, ROOM) == (0.0, 0)
    assert pinnedLength(-5.0, 0.02, ROOM) == (0.0, 0)
    assert pinnedLength(5.0, 0.02, 0) == (0.0, 0)


# ------------------------------------------------------------------- the ticks

def test_a_length_on_the_ladder_is_ticked_the_way_the_ladder_ticks_it():
    for mantissa, subdivs in NICE_LENGTHS:
        for decade in (0.01, 1.0, 100.0):
            assert pinnedSubdivisions(mantissa * decade) == subdivs


def test_a_length_off_the_ladder_gets_no_interior_ticks():
    """3.7 µm has no division into two to seven parts that prints roundly, so
    it gets none rather than ticks labelled 0.74 and 1.48."""
    for value in (3.7, 12.0, 0.63, 8.5):
        assert pinnedSubdivisions(value) == 1
    assert pinnedSubdivisions(0.0) == 1


def test_the_rendered_ticks_of_a_pinned_bar_are_round(app, monkeypatch):
    collected = _install_spies(monkeypatch)
    bar = _pinned_bar(5.0, 0.01)
    try:
        pix, label, ticks = _render(bar, collected)
        assert (pix, label) == (500, "5 µm")
        assert ticks == ("1", "2", "3", "4")
    finally:
        bar.deleteLater()

    bar = _pinned_bar(3.7, 0.01)
    try:
        pix, label, ticks = _render(bar, collected)
        assert (pix, label) == (370, "3.7 µm")
        assert ticks == ()
    finally:
        bar.deleteLater()


# ---------------------------------------------------------------- the widget

def test_the_pinned_widget_is_the_bar(app, monkeypatch):
    """The widget is also the drag handle, so in pinned mode it has to be the
    size of the bar rather than the size of the room -- otherwise there is an
    invisible grab target lying over the field.
    """
    collected = _install_spies(monkeypatch)
    bar = _pinned_bar(5.0, 0.01)
    try:
        pix, label, _ticks = _render(bar, collected)
        assert bar.width() == 500
        assert (pix, label) == (500, "5 µm")
    finally:
        bar.deleteLater()


def test_the_pinned_bar_is_never_clipped_at_any_zoom(app, monkeypatch):
    """Rendered, not computed: the drawn rectangle must fit inside the widget at
    every zoom, which is what makes the resize-on-setScale load bearing."""
    collected = _install_spies(monkeypatch)
    bar = _pinned_bar(5.0, 0.01)
    try:
        widths = set()
        for scale in _zoom_sweep():
            bar.setScale(scale)
            pix, label, _ticks = _render(bar, collected)
            assert pix is not None, scale
            assert pix <= bar.width(), (scale, pix, bar.width())
            assert pix <= ROOM, (scale, pix)
            # and the drawn rule is exactly as long as the label says
            assert label.endswith(" µm")
            assert pix == int(float(label[:-3]) / scale), (scale, pix, label)
            widths.add(bar.width())
        assert len(widths) > 5, "the widget is supposed to be following the zoom"
    finally:
        bar.deleteLater()


def test_the_room_can_be_narrowed_after_construction(app, monkeypatch):
    """A window resize changes how much room the bar has; MousePalette.resize
    passes that on, and the bar must give the room back."""
    collected = _install_spies(monkeypatch)
    bar = _pinned_bar(5.0, 5.0 / 900, room=1000)
    try:
        assert _render(bar, collected)[:2] == (900, "5 µm")
        bar.setMaxPixelLength(500)
        pix, label, _ticks = _render(bar, collected)
        assert pix <= 500
        assert (pix, label) == (90, "0.5 µm")
        assert bar.width() == 90
    finally:
        bar.deleteLater()


# ------------------------------------------------------ defaults and migration

def test_the_shipped_mode_is_the_historic_one():
    """The migration promise: an installation that never touches the new control
    keeps the screen-fraction bar, and its stored scale_bar_width goes on
    meaning a percentage."""
    assert default_settings["scale_bar_mode"] == "screen_fraction"
    assert default_settings["scale_bar_width"] == 25


def test_the_length_default_is_a_float_so_a_fractional_length_survives():
    """`Series.getOption` reads a stored value back with `type(default)`, so an
    int default here would silently truncate a stored 2.5 µm to 2 µm on the next
    read. This assertion is the guard for that, and it is on the default rather
    than on QSettings because the real settings domain is not a test's to touch.
    """
    assert isinstance(default_settings["scale_bar_length_um"], float)


def test_a_series_that_never_saw_the_keys_reads_the_historic_behaviour(tmp_path):
    series = _series(tmp_path)
    series.setOption("scale_bar_width", 25)
    assert series.getOption("scale_bar_mode") == "screen_fraction"
    assert series.getOption("scale_bar_width") == 25
    assert series.getOption("scale_bar_length_um") == 5.0


def test_a_fractional_length_roundtrips_through_the_store(tmp_path):
    series = _series(tmp_path)
    series.setOption("scale_bar_length_um", 2.5)
    assert series.getOption("scale_bar_length_um") == 2.5


# ------------------------------------------------------------------ the dialog

def _widget(dlg):
    return dlg.all_widgets["scale_bar"]


def test_the_response_layout_is_what_the_other_tests_index(qapp, tmp_path):
    """Pin the shape of the scale bar option widget's response tuple, because
    `test_options_reset_defaults_sliders.py` indexes into it by number."""
    series = _series(tmp_path)
    dlg = AllOptionsDialog(None, series)
    try:
        w = _widget(dlg)
        assert w.accept(close=False)
        assert len(w.responses) == 4
        assert [label for label, _checked in w.responses[0]] == [
            "show numbers", "show ticks"]
        assert len(w.responses[1]) == 2                  # the mode radio
        assert isinstance(w.responses[2], int)           # the percentage slider
        assert isinstance(w.responses[3], float)         # the µm length
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("stored, expect_pinned", [
    ("screen_fraction", False),
    ("micron_pinned", True),
])
def test_the_mode_radio_shows_the_stored_mode(qapp, tmp_path, stored, expect_pinned):
    series = _series(tmp_path)
    series.setOption("scale_bar_mode", stored)
    dlg = AllOptionsDialog(None, series)
    try:
        w = _widget(dlg)
        assert w.accept(close=False)
        fraction_on, pinned_on = (checked for _label, checked in w.responses[1])
        assert pinned_on is expect_pinned
        assert fraction_on is not expect_pinned
    finally:
        dlg.deleteLater()


def test_choosing_the_pinned_mode_stores_it_and_leaves_the_percentage_alone(
    qapp, tmp_path
):
    series = _series(tmp_path)
    series.setOption("scale_bar_width", 45)
    dlg = AllOptionsDialog(None, series)
    try:
        w = _widget(dlg)
        radios = w.inputs[1].widget.layout()
        radios.itemAt(1).widget().setChecked(True)
        assert w.accept(close=False)
        w.set()
    finally:
        dlg.deleteLater()
    assert series.getOption("scale_bar_mode") == "micron_pinned"
    assert series.getOption("scale_bar_width") == 45, (
        "the percentage must survive the round trip so switching back is lossless"
    )


def test_switching_back_restores_the_percentage_bar_exactly(qapp, tmp_path):
    series = _series(tmp_path)
    series.setOption("scale_bar_width", 45)
    series.setOption("scale_bar_mode", "micron_pinned")

    dlg = AllOptionsDialog(None, series)
    try:
        w = _widget(dlg)
        w.inputs[1].widget.layout().itemAt(0).widget().setChecked(True)
        assert w.accept(close=False)
        w.set()
    finally:
        dlg.deleteLater()

    assert series.getOption("scale_bar_mode") == "screen_fraction"
    assert series.getOption("scale_bar_width") == 45


def test_the_length_box_stores_what_the_user_typed(qapp, tmp_path):
    series = _series(tmp_path)
    dlg = AllOptionsDialog(None, series)
    try:
        w = _widget(dlg)
        w.inputs[3].widget.setText("2.5")
        assert w.accept(close=False)
        w.set()
    finally:
        dlg.deleteLater()
    assert series.getOption("scale_bar_length_um") == 2.5


@pytest.mark.parametrize("typed", ["", "0", "-3"])
def test_a_missing_or_nonsensical_length_keeps_the_stored_one(qapp, tmp_path, typed):
    """An empty or zero box must not pin the bar to nothing."""
    series = _series(tmp_path)
    series.setOption("scale_bar_length_um", 7.0)
    dlg = AllOptionsDialog(None, series)
    try:
        w = _widget(dlg)
        w.inputs[3].widget.setText(typed)
        assert w.accept(close=False)
        w.set()
    finally:
        dlg.deleteLater()
    assert series.getOption("scale_bar_length_um") == 7.0


def test_reset_defaults_moves_the_mode_and_the_length(qapp, tmp_path):
    series = _series(tmp_path)
    series.setOption("scale_bar_mode", "micron_pinned")
    series.setOption("scale_bar_length_um", 42.0)
    dlg = AllOptionsDialog(None, series)
    try:
        dlg.resetDefaults()
        w = _widget(dlg)
        assert w.accept(close=False)
        _fraction_on, pinned_on = (checked for _label, checked in w.responses[1])
        assert pinned_on is False
        assert w.responses[3] == 5.0
    finally:
        dlg.deleteLater()
    # Reset Defaults only repopulates the dialog; nothing is stored until OK
    assert series.getOption("scale_bar_mode") == "micron_pinned"


# ------------------------------------------- lengths the arithmetic cannot use
#
# `> 0` was not a strong enough guard, and the hole was not cosmetic. `inf > 0`
# is True, `float("1e400")` parses to inf without raising, and `1e-320` is a
# positive finite denormal, so all three cleared the dialog's check and were
# written to `scale_bar_length_um` -- a *global*-scope option, the same for every
# series and persisted across restarts. Read back, each one raised out of
# `pinnedLength` (`math.log10(0.0)` for the infinities, `math.ceil(inf)` for the
# denormal) inside `ScaleBar.__init__`, which runs inside `MousePalette.__init__`
# -- so the application died during startup, every startup, and the only way back
# was to hand-edit the settings plist. `nan` and `-inf` were already rejected by
# the old guard, and non-numeric text by the float parser; those are the controls.

BAD_LENGTHS = ["inf", "1e400", "1e-320", "nan", "-inf"]


@pytest.mark.parametrize("typed", BAD_LENGTHS)
def test_a_length_the_arithmetic_cannot_use_is_never_stored(qapp, tmp_path, typed):
    """The point of first contact: the value must not reach the store at all."""
    series = _series(tmp_path)
    series.setOption("scale_bar_mode", "micron_pinned")
    series.setOption("scale_bar_length_um", 7.0)
    dlg = AllOptionsDialog(None, series)
    try:
        w = _widget(dlg)
        w.inputs[3].widget.setText(typed)
        assert w.accept(close=False)
        w.set()
    finally:
        dlg.deleteLater()
    assert series.getOption("scale_bar_length_um") == 7.0
    assert series.getOption("scale_bar_mode") == "micron_pinned", (
        "the mode is the user's other choice on the same OK and must still land"
    )


@pytest.mark.parametrize("typed", BAD_LENGTHS)
def test_and_the_next_launch_still_builds_a_bar(qapp, tmp_path, typed):
    """The crash itself: type the value, then rebuild the bar the way a fresh
    launch does. Before the guard was widened this raised out of
    `ScaleBar.__init__` for inf, 1e400 and 1e-320."""
    series = _series(tmp_path)
    series.setOption("scale_bar_mode", "micron_pinned")
    dlg = AllOptionsDialog(None, series)
    try:
        w = _widget(dlg)
        w.inputs[3].widget.setText(typed)
        assert w.accept(close=False)
        w.set()
    finally:
        dlg.deleteLater()

    stored = series.getOption("scale_bar_length_um")
    bar = ScaleBar(None, _StubManager(), ROOM, 50, 1,
                   micron_length=stored, max_pixel_length=ROOM)
    try:
        bar.setScale(0.01)
        assert bar.width() > 0
    finally:
        bar.deleteLater()


@pytest.mark.parametrize("stored", [float("inf"), float("nan"), 1e-320, 1e300, -1.0])
def test_a_store_already_holding_one_degrades_instead_of_crashing(
    app, tmp_path, stored
):
    """Defence in depth for the users whose settings are already poisoned, and
    for a hand-edited plist. Nothing keeps a bad value out of the store except
    the dialog, so the two readers have to survive one: the palette declines to
    pin the bar, which is the historic screen-fraction sizing, and the bar's own
    arithmetic reports nothing to draw rather than raising."""
    series = _series(tmp_path)
    series.setOption("scale_bar_mode", "micron_pinned")
    series.setOption("scale_bar_length_um", stored)

    assert _StubPalette(series).getPinnedLength() is None
    assert pinnedLength(stored, 0.01, ROOM) == (0.0, 0)

    bar = ScaleBar(None, _StubManager(), ROOM, 50, 1,
                   micron_length=stored, max_pixel_length=ROOM)
    try:
        bar.setScale(0.01)
    finally:
        bar.deleteLater()


@pytest.mark.parametrize("micron_length", [0.002, 1.0, 5.0, 50.0, 500.0, 2.5])
def test_the_lengths_a_microscopist_actually_types_are_untouched(
    qapp, tmp_path, micron_length
):
    """The guard is a floor and a ceiling twelve decades apart; nothing anyone
    would type at a specimen goes near either. Stored, pinned, and drawn."""
    assert validPinnedLength(micron_length)

    series = _series(tmp_path)
    series.setOption("scale_bar_mode", "micron_pinned")
    dlg = AllOptionsDialog(None, series)
    try:
        w = _widget(dlg)
        w.inputs[3].widget.setText(str(micron_length))
        assert w.accept(close=False)
        w.set()
    finally:
        dlg.deleteLater()
    assert series.getOption("scale_bar_length_um") == micron_length
    assert _StubPalette(series).getPinnedLength() == micron_length

    real_len, pix_len = pinnedLength(micron_length, micron_length / 200, ROOM)
    assert (real_len, pix_len) == (micron_length, 200)


def test_the_bounds_are_stated_once_so_moving_them_is_visible():
    """The three call sites all defer to this predicate, so this is the only
    place the floor and the ceiling are written down."""
    assert validPinnedLength(MIN_PINNED_UM) and validPinnedLength(MAX_PINNED_UM)
    assert not validPinnedLength(MIN_PINNED_UM / 10)
    assert not validPinnedLength(MAX_PINNED_UM * 10)
    assert not validPinnedLength(0)
    assert not validPinnedLength(None)
    assert not validPinnedLength("abc"), "a corrupted store need not hold a number"


# ------------------------------------------------- the palette, for real

@pytest.mark.gui
def test_the_palette_builds_a_screen_fraction_bar_by_default(
    main_window, local_series_settings, monkeypatch
):
    """On the suite's real MainWindow, with nothing set: the historic bar."""
    series = local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    assert palette.getPinnedLength() is None
    assert palette.sb.micron_length is None

    field_w = main_window.field.width()
    expected = int(series.getOption("scale_bar_width") / 100 * field_w)
    assert palette.sb.width() == expected


@pytest.mark.gui
def test_the_palette_builds_a_pinned_bar_when_asked(
    main_window, local_series_settings, monkeypatch
):
    """Turn the option on, rebuild the palette the way the options dialog does,
    and the real bar is pinned: the label holds still and the width moves."""
    series = local_series_settings(main_window)
    series.setOption("scale_bar_mode", "micron_pinned")
    series.setOption("scale_bar_length_um", 5.0)

    palette = main_window.mouse_palette
    palette.reset()                       # what MainWindow.allOptions does on OK
    assert palette.getPinnedLength() == 5.0
    assert palette.sb.micron_length == 5.0

    collected = _install_spies(monkeypatch)
    pix_width = main_window.field.pixmap_dim[0]
    seen = []
    # the window widths whose zoom keeps a 5 µm bar inside the field's own
    # legible range: 560 px of room and a 40 px floor put that at 5 to 70 µm
    for window_um in (10.0, 20.0, 50.0, 60.0):
        series.window[2] = window_um
        palette.setScale()
        pix, label, _ticks = _render(palette.sb, collected)
        seen.append((window_um, window_um / pix_width, pix, label))

    labels = {label for _w, _s, _p, label in seen}
    widths = {pix for _w, _s, pix, _l in seen}
    assert labels == {"5 µm"}, seen
    assert len(widths) == len(seen), seen
    for _window_um, scale, pix, _label in seen:
        assert pix == int(5.0 / scale)
