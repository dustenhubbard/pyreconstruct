"""The scale bar as the zoom changes: held to its size, live, and set to a length you type.

Three things, each driven through the real widgets:

* **The cap.** In both modes the drawn bar is never wider than the "Scale bar
  size" share of the field. A micron-pinned bar used to be allowed the whole
  field width, so a 5 µm bar could stretch nearly edge to edge before it
  stepped down a decade.
* **Live follow.** A pinch, Ctrl+scroll or right-drag zoom stretches a copy of
  the field and only redraws on release. `panzoomMove` now tells the bar the
  scale of the stretched view, without a field redraw.
* **A length you type.** The bar's right-click menu can set a length for a
  figure. It is not stored, it may grow past the size option up to the field
  width, and the label always matches what the bar measures.
"""
import copy
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import QPoint
from PySide6.QtGui import QPainter, QPixmap

from PyReconstruct.modules.gui.palette import mouse_palette as mp_mod
from PyReconstruct.modules.gui.palette import scale_bar as sb_mod
from PyReconstruct.modules.gui.palette.scale_bar import (
    MIN_PINNED_PIXELS,
    pinnedLength,
)

FIELD_W = 560                  # the width the suite's real MainWindow field reports
CAP = int(25 / 100 * FIELD_W)  # the default "Scale bar size", 25 %


def _mantissa(value):
    return value / 10.0 ** math.floor(math.log10(value))


def _zoom_sweep(lo=1e-5, hi=1e3, step=1.07):
    scale = lo
    while scale < hi:
        yield scale
        scale *= step


def _render(bar):
    """Paint for real; return (bar length in px, label)."""
    rects, labels = [], []
    real_rect = QPainter.drawRect
    real_outlined = sb_mod.drawOutlinedText

    def spy_rect(painter, *args):
        if len(args) == 4:
            rects.append(args)
        return real_rect(painter, *args)

    def spy_outlined(painter, x, y, text):
        labels.append(text)
        return real_outlined(painter, x, y, text)

    mp = pytest.MonkeyPatch()
    mp.setattr(QPainter, "drawRect", spy_rect)
    mp.setattr(sb_mod, "drawOutlinedText", spy_outlined)
    try:
        pixmap = QPixmap(bar.size())
        pixmap.fill()
        bar.render(pixmap)
    finally:
        mp.undo()
    return (rects[0][2] if rects else None, labels[0] if labels else None)


def _set_window(main_window, microns_per_px):
    """Zoom the field so one screen pixel is `microns_per_px` wide."""
    main_window.series.window[2] = microns_per_px * main_window.field.pixmap_dim[0]
    main_window.mouse_palette.setScale()


# ------------------------------------------------------------------ the cap

@pytest.mark.parametrize("micron_length", [5.0, 2.0, 0.5, 3.7, 12.0])
def test_a_pinned_bar_stays_inside_its_size_and_keeps_its_number(micron_length):
    """Over eight decades of zoom, with the default 25 % of the field as room:
    never wider than the room, never a different mantissa, and the user's own
    length wherever it fits between the 40 px floor and the room."""
    for scale in _zoom_sweep():
        real_len, pix_len = pinnedLength(micron_length, scale, CAP)
        assert 0 < pix_len <= CAP, (micron_length, scale, pix_len)
        assert pix_len == int(real_len / scale)
        assert _mantissa(real_len) == pytest.approx(_mantissa(micron_length))
        if MIN_PINNED_PIXELS <= micron_length / scale <= CAP:
            assert real_len == micron_length, (micron_length, scale, real_len)


@pytest.mark.gui
def test_the_pinned_palette_bar_steps_down_before_it_outgrows_its_size(
    main_window, local_series_settings
):
    """A 5 µm bar at a zoom where 5 µm is 500 px wide used to draw 500 px
    of a 560 px field. With 25 % of the field as its size it draws 0.5 µm."""
    series = local_series_settings(main_window)
    series.setOption("scale_bar_mode", "micron_pinned")
    series.setOption("scale_bar_length_um", 5.0)
    palette = main_window.mouse_palette
    palette.reset()
    cap = palette.sbWidth()
    assert cap == CAP

    _set_window(main_window, 5.0 / 500)
    pix, label = _render(palette.sb)

    assert pix <= cap
    assert palette.sb.width() <= cap
    assert (pix, label) == (50, "0.5 µm")


@pytest.mark.gui
@pytest.mark.parametrize("mode", ["screen_fraction", "micron_pinned"])
def test_in_both_modes_the_drawn_bar_never_passes_its_size(
    main_window, local_series_settings, mode
):
    series = local_series_settings(main_window)
    series.setOption("scale_bar_mode", mode)
    series.setOption("scale_bar_length_um", 5.0)
    palette = main_window.mouse_palette
    palette.reset()
    for scale in _zoom_sweep(1e-4, 10.0, 1.15):
        _set_window(main_window, scale)
        pix, _label = _render(palette.sb)
        assert 0 < pix <= palette.sbWidth(), (mode, scale, pix)


# -------------------------------------------------------------- live follow

def _count_redraws(main_window, monkeypatch):
    calls = []
    real = main_window.field.generateView
    monkeypatch.setattr(
        main_window.field, "generateView",
        lambda *a, **k: (calls.append(1), real(*a, **k))[1],
    )
    return calls


@pytest.mark.gui
@pytest.mark.parametrize("mode", ["screen_fraction", "micron_pinned"])
def test_the_bar_follows_a_zoom_while_it_happens(
    main_window, local_series_settings, monkeypatch, mode
):
    """panzoomMove is the one road the pinch, Ctrl+scroll and right-drag zooms
    share. Each call now sets the bar to the scale of the stretched view, and
    the field is not redrawn to do it."""
    series = local_series_settings(main_window)
    series.setOption("scale_bar_mode", mode)
    series.setOption("scale_bar_length_um", 5.0)
    palette = main_window.mouse_palette
    palette.reset()
    _set_window(main_window, 5.0 / 60)       # a 5 µm pinned bar is 60 px
    field = main_window.field
    before = palette.sb.scale
    window_before = list(series.window)
    redraws = _count_redraws(main_window, monkeypatch)

    field.panzoomPress(200, 200)
    field.panzoomMove(zoom_factor=2.0)

    assert palette.sb.scale == pytest.approx(before / 2.0)
    assert palette.sb.currentLength()[0] / palette.sb.scale <= palette.sbWidth()
    if mode == "micron_pinned":
        assert _render(palette.sb) == (120, "5 µm")
    field.panzoomMove(zoom_factor=0.5)
    assert palette.sb.scale == pytest.approx(before * 2.0)
    assert redraws == [], "the field was redrawn during the zoom"
    assert series.window == window_before

    # the release lands on the scale the bar was already showing
    field.panzoomMove(zoom_factor=1.6)
    live = palette.sb.scale
    field.panzoomRelease(zoom_factor=1.6)
    assert palette.sb.scale == pytest.approx(live)


@pytest.mark.gui
def test_a_pan_leaves_the_bar_alone(main_window, local_series_settings):
    local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    before = palette.sb.scale
    field = main_window.field
    field.panzoomPress(100, 100)
    field.panzoomMove(new_x=150, new_y=130)
    assert palette.sb.scale == before


# ------------------------------------------------------ a length you type

def _menu_texts(palette):
    palette._hide_menu = None
    palette.sb.customContextMenuRequested.emit(QPoint(2, 2))
    menu = palette._hide_menu
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    actions = {a.text(): a for a in menu.actions()}
    menu.hide()
    return texts, actions


def _answer(monkeypatch, *responses):
    """Script QuickDialog.get and notify for setSBLength."""
    asked, told = [], []
    queue = list(responses)

    def get(parent, structure, title="Dialog", *args, **kwargs):
        asked.append(structure)
        return queue.pop(0)

    monkeypatch.setattr(mp_mod.QuickDialog, "get", staticmethod(get))
    monkeypatch.setattr(mp_mod, "notify", lambda message, *a, **k: told.append(message))
    return asked, told


def _stored(series):
    """Everything a setting can be written to: the settings store (both
    scopes), the series' own options, and whether the series needs saving."""
    flat = {("store", scope, key): value
            for scope, values in series._settings_store._data.items()
            for key, value in values.items()}
    flat.update({("series", key): value for key, value in series.options.items()})
    flat[("modified",)] = series.modified
    return copy.deepcopy(flat)


def _changed(before, after):
    return {key: (before.get(key), after.get(key))
            for key in set(before) | set(after)
            if before.get(key, KeyError) != after.get(key, KeyError)}


@pytest.mark.gui
def test_the_menu_offers_a_length_and_automatic_only_while_one_is_set(
    main_window, local_series_settings, monkeypatch
):
    local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()

    texts, _ = _menu_texts(palette)
    assert texts == ["Set the scale bar length...", "Hide the scale bar"]

    _set_window(main_window, 0.01)
    _answer(monkeypatch, ([3.0], True))
    palette.setSBLength()
    texts, actions = _menu_texts(palette)
    assert texts == ["Set the scale bar length...",
                     "Size the scale bar automatically",
                     "Hide the scale bar"]

    actions["Size the scale bar automatically"].trigger()
    assert palette.sb.override_length is None
    assert _menu_texts(palette)[0] == ["Set the scale bar length...",
                                       "Hide the scale bar"]


@pytest.mark.gui
@pytest.mark.parametrize("mode", ["screen_fraction", "micron_pinned"])
def test_a_typed_length_draws_exactly_and_follows_the_zoom(
    main_window, local_series_settings, monkeypatch, mode
):
    """3 µm is not a 1-2-5 length and not the pinned 5 µm. It draws at 3 µm in
    both modes, and past the 140 px size option, because the user asked for
    it; the pixels follow the zoom and the label does not move."""
    series = local_series_settings(main_window)
    series.setOption("scale_bar_mode", mode)
    series.setOption("scale_bar_length_um", 5.0)
    palette = main_window.mouse_palette
    palette.reset()
    _set_window(main_window, 0.01)
    _render(palette.sb)   # a first paint writes its two display defaults back
    stored = _stored(series)
    asked, told = _answer(monkeypatch, ([3.0], True))

    palette.setSBLength()

    assert told == []
    assert palette.sb.override_length == 3.0
    assert _render(palette.sb) == (300, "3 µm")
    assert palette.sb.width() == 300 > palette.sbWidth()

    _set_window(main_window, 0.02)
    assert _render(palette.sb) == (150, "3 µm")
    palette.sb.setScale(0.015)                 # what a live zoom does
    assert _render(palette.sb) == (200, "3 µm")

    assert _changed(stored, _stored(series)) == {}


@pytest.mark.gui
def test_going_back_to_automatic_restores_the_stored_bar(
    main_window, local_series_settings, monkeypatch
):
    series = local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    _set_window(main_window, 0.01)
    automatic = (palette.sb.width(), _render(palette.sb))
    stored = _stored(series)
    _answer(monkeypatch, ([3.0], True))
    palette.setSBLength()
    assert _render(palette.sb) == (300, "3 µm")

    palette.clearSBLength()

    assert (palette.sb.width(), _render(palette.sb)) == automatic
    assert series.getOption("scale_bar_mode") == "screen_fraction"
    assert _changed(stored, _stored(series)) == {}


@pytest.mark.gui
def test_a_typed_length_lasts_until_another_series_opens(
    main_window, local_series_settings, monkeypatch, tmp_path
):
    """What the dialog and the changelog promise: Save, `Series > Options...`
    with OK or Cancel, and a thickness change in it all keep the length; only
    opening another series ends it."""
    import shutil

    from PySide6.QtWidgets import QDialog

    series = local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    _set_window(main_window, 0.01)
    _answer(monkeypatch, ([3.0], True))
    palette.setSBLength()
    assert _render(palette.sb) == (300, "3 µm")

    main_window.saveToJser()
    assert main_window.mouse_palette.sb.override_length == 3.0

    def run_options(accept, thickness=None):
        def exec_(dlg):
            if thickness is not None:
                _thickness_slider(dlg).setValue(thickness)
            if accept:
                return QDialog.Accepted if dlg.accept() else QDialog.Rejected
            dlg.reject()
            return QDialog.Rejected
        monkeypatch.setattr(AllOptionsDialog, "exec", exec_)
        main_window.allOptions()

    run_options(accept=False, thickness=15)
    assert main_window.mouse_palette.sb.override_length == 3.0
    run_options(accept=True, thickness=12)
    sb = main_window.mouse_palette.sb
    assert sb.thickness == 12
    assert sb.override_length == 3.0
    assert _render(sb) == (300, "3 µm")

    copy_fp = tmp_path / "series_b" / "series_b.jser"
    copy_fp.parent.mkdir()
    shutil.copyfile(series.jser_fp, copy_fp)
    main_window.openSeries(jser_fp=str(copy_fp), query_prev=False)
    assert main_window.series is not series
    assert main_window.mouse_palette.sb.override_length is None


@pytest.mark.gui
def test_a_length_that_cannot_be_drawn_is_refused_in_plain_words(
    main_window, local_series_settings, monkeypatch
):
    """At 0.01 µm/px the field is 560 px, so 5.6 µm is the longest exact bar
    and 40 px, 0.4 µm, the shortest. The dialog says so, a length outside is
    refused with the range, and the dialog opens again."""
    series = local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    _set_window(main_window, 0.01)
    _render(palette.sb)   # a first paint writes its two display defaults back
    stored = _stored(series)
    asked, told = _answer(monkeypatch, ([50.0], True), ([0.1], True), ([5.6], True))

    palette.setSBLength()

    lines = [row[0] for structure in asked for row in structure
             if isinstance(row[0], str)]
    assert "At this zoom the bar can be 0.4 to 5.6 µm long." in lines
    assert len(told) == 2 and all("0.4 to 5.6 µm" in m for m in told)
    assert palette.sb.override_length == 5.6
    assert _render(palette.sb) == (560, "5.6 µm")
    assert _changed(stored, _stored(series)) == {}


@pytest.mark.gui
def test_cancel_sets_nothing(main_window, local_series_settings, monkeypatch):
    local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    before = (palette.sb.width(), _render(palette.sb))
    _answer(monkeypatch, (None, False))
    palette.setSBLength()
    assert palette.sb.override_length is None
    assert (palette.sb.width(), _render(palette.sb)) == before


# ----------------------------------------------------------- the thickness

from PyReconstruct.modules.datatypes.default_settings import (  # noqa: E402
    MAX_SCALE_BAR_THICKNESS,
    MIN_SCALE_BAR_THICKNESS,
    clampScaleBarThickness,
    default_settings,
)
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog  # noqa: E402
from PyReconstruct.modules.gui.palette.scale_bar import (  # noqa: E402
    LABEL_ROOM,
    TICK_LABEL_ROOM,
    TICK_LENGTH,
    ScaleBar,
)


class _StubSeries:
    def __init__(self, text=True, ticks=True):
        self._opts = {"show_scale_bar_text": text, "show_scale_bar_ticks": ticks}

    def getOption(self, name, *args, **kwargs):
        return self._opts[name]


class _StubManager:
    def __init__(self, **kwargs):
        self.series = _StubSeries(**kwargs)
        self.mainwindow = None


def test_the_thickness_default_and_range():
    """Thinner than the 25 px bar it replaces; 25 stays reachable."""
    assert default_settings["scale_bar_thickness"] == 6
    assert isinstance(default_settings["scale_bar_thickness"], int)
    assert (MIN_SCALE_BAR_THICKNESS, MAX_SCALE_BAR_THICKNESS) == (3, 25)
    assert clampScaleBarThickness(1) == 3
    assert clampScaleBarThickness(99) == 25
    assert clampScaleBarThickness(12) == 12
    for junk in (None, "abc", float("inf")):
        assert clampScaleBarThickness(junk) == 6


@pytest.mark.parametrize("text, ticks, extra", [
    (True, True, LABEL_ROOM + TICK_LENGTH + TICK_LABEL_ROOM),
    (True, False, LABEL_ROOM + 1),
    (False, True, 1 + TICK_LENGTH + 1),
    (False, False, 1 + 1),
])
def test_the_widget_is_as_tall_as_the_bar_and_its_text(qapp, text, ticks, extra):
    """No empty grab area: the widget is the bar plus the room its label and
    ticks need, and the room for anything switched off is left out."""
    for thickness in (3, 6, 25):
        bar = ScaleBar(None, _StubManager(text=text, ticks=ticks), 140, thickness, 0.02)
        try:
            assert bar.height() == thickness + extra
            changed = 3 if thickness == 25 else thickness + 4
            bar.setThickness(changed)
            assert bar.height() == changed + extra
        finally:
            bar.deleteLater()


def _drawn(bar):
    """Every rectangle and every outlined string a real paint draws."""
    rects, texts = [], []
    real_rect = QPainter.drawRect
    real_outlined = sb_mod.drawOutlinedText

    def spy_rect(painter, *args):
        if len(args) == 4:
            rects.append(tuple(float(a) for a in args))
        return real_rect(painter, *args)

    def spy_outlined(painter, x, y, text):
        texts.append((x, y, text))
        return real_outlined(painter, x, y, text)

    mp = pytest.MonkeyPatch()
    mp.setattr(QPainter, "drawRect", spy_rect)
    mp.setattr(sb_mod, "drawOutlinedText", spy_outlined)
    try:
        pixmap = QPixmap(bar.size())
        pixmap.fill()
        bar.render(pixmap)
    finally:
        mp.undo()
    return rects, texts


@pytest.mark.parametrize("thickness", [3, 6, 25])
def test_every_thickness_draws_its_outline_ticks_and_labels_inside_the_widget(
    qapp, thickness
):
    """At 0.004 µm/px a 140 px widget holds a 0.5 µm bar of 125 px, ticked in
    five; its labels are spaced out enough to print every other one."""
    bar = ScaleBar(None, _StubManager(), 140, thickness, 0.004)
    try:
        rects, texts = _drawn(bar)
        w, h = bar.width(), bar.height()
        outline, fill, *ticks = rects
        assert outline == (0, LABEL_ROOM, 125, thickness)
        # a black line inside a 1 px white edge, even at the thinnest
        assert fill == (1, LABEL_ROOM + 1, 123, thickness - 2)
        assert fill[3] >= 1
        assert len(ticks) == 2 * 4           # a white edge and a black mark each
        for x, y, rw, rh in rects:
            assert 0 <= x and x + rw <= w and 0 <= y and y + rh <= h, (x, y, rw, rh)
        labels = [text for _x, _y, text in texts]
        assert labels[0] == "0.5 µm"
        assert labels[1:] and set(labels[1:]) <= {"0.1", "0.2", "0.3", "0.4"}
        for _x, y, text in texts:            # y is the baseline
            assert 0 < y <= h, (text, y, h)
        tick_baselines = {y for _x, y, _t in texts[1:]}
        assert min(tick_baselines) > LABEL_ROOM + thickness + TICK_LENGTH
    finally:
        bar.deleteLater()


def test_crowded_tick_labels_are_thinned_not_overlapped(qapp):
    """A 1 µm bar 100 px long ticks at 20 px: too close for "0.2 0.4 0.6
    0.8" side by side, so only some are printed, and those do not touch.
    Measured in whatever font this machine has; the marks themselves all
    stay."""
    from PySide6.QtGui import QFont, QFontMetrics

    bar = ScaleBar(None, _StubManager(), 100, 6, 0.01)
    try:
        rects, texts = _drawn(bar)
        assert len(rects) == 2 + 2 * 4
        assert texts[0][2] == "1 µm"
        ticks = texts[1:]
        assert 1 <= len(ticks) < 4
        assert {t for _x, _y, t in ticks} <= {"0.2", "0.4", "0.6", "0.8"}
        metrics = QFontMetrics(QFont("Courier New", 10, QFont.Bold))
        for (x_a, _y, t_a), (x_b, _y2, _t) in zip(ticks, ticks[1:]):
            assert x_a + metrics.horizontalAdvance(t_a) < x_b, (t_a, x_a, x_b)
    finally:
        bar.deleteLater()


def _thickness_slider(dlg):
    sliders = [f.widget.slider for f in dlg.all_widgets["scale_bar"].inputs
               if f.type == "slider"]
    return sliders[1]


@pytest.mark.gui
def test_the_palette_builds_the_bar_at_the_stored_thickness(
    main_window, local_series_settings
):
    series = local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    assert palette.sb.thickness == 6
    bottom = palette.sb.y() + palette.sb.height()

    series.setOption("scale_bar_thickness", 20)
    palette.reset()
    assert palette.sb.thickness == 20
    # it grows upward from the same bottom edge rather than off the field
    assert palette.sb.y() + palette.sb.height() == pytest.approx(bottom, abs=1)


@pytest.mark.gui
def test_the_thickness_slider_previews_stores_on_ok_and_cancel_restores(
    main_window, local_series_settings, qapp
):
    series = local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    height_at_6 = palette.sb.height()

    dlg = AllOptionsDialog(main_window, series)
    _thickness_slider(dlg).setValue(15)
    qapp.processEvents()
    assert palette.sb.thickness == 15
    assert palette.sb.height() == height_at_6 + 9
    assert series.getOption("scale_bar_thickness") == 6, "a preview stored it"
    dlg.reject()
    qapp.processEvents()
    assert palette.sb.thickness == 6
    assert palette.sb.height() == height_at_6

    dlg = AllOptionsDialog(main_window, series)
    _thickness_slider(dlg).setValue(12)
    assert dlg.accept() is True
    palette.reset()                       # what allOptions() runs after OK
    assert series.getOption("scale_bar_thickness") == 12
    assert palette.sb.thickness == 12


def test_a_hand_edited_thickness_is_clamped_not_trusted(qapp):
    bar = ScaleBar(None, _StubManager(), 140, 400, 0.02)
    try:
        assert bar.thickness == MAX_SCALE_BAR_THICKNESS
    finally:
        bar.deleteLater()


def test_a_bar_shorter_than_its_label_keeps_the_label_whole(qapp):
    """A pinned 0.5 µm bar can be about 33 px, narrower than "0.5 µm". The
    widget widens to the label and the label starts inside it, so neither end
    of the text is cut off; the bar itself stays its true length."""
    from PySide6.QtGui import QFontMetrics

    from PyReconstruct.modules.gui.palette.scale_bar import (
        LABEL_SIZE,
        outlinedFont,
    )

    bar = ScaleBar(None, _StubManager(), 275, 6, 5.0 / 330,
                   micron_length=5.0, max_pixel_length=275)
    try:
        rects, texts = _drawn(bar)
        label_x, _y, label = texts[0]
        assert label == "0.5 µm"
        assert rects[0][2] == 33                     # the bar measures 0.5 µm
        width = QFontMetrics(outlinedFont(LABEL_SIZE)).horizontalAdvance(label)
        assert width > 33
        assert bar.width() >= width
        assert 0 <= label_x and label_x + width <= bar.width()
    finally:
        bar.deleteLater()


# ------------------------------------- what the dialog accepts, it draws whole

def _field_edges(main_window):
    field = main_window.field
    return field.x(), field.x() + field.width()


@pytest.mark.gui
@pytest.mark.parametrize("scale", [1e-8, 0.01, 1.0, 1e4])
def test_every_length_the_dialog_accepts_draws_with_its_own_label(
    main_window, local_series_settings, monkeypatch, scale
):
    """The dialog's range is the intersection of what fits the field and what
    a pinned length may be (1e-6 to 1e6 µm). At 1e4 µm/px the field alone
    would offer 400000 to 5600000 µm, and 2000000 µm then drew nothing.
    Both ends and a length between draw, at that length, with that label."""
    from PyReconstruct.modules.datatypes.default_settings import (
        MAX_PINNED_UM,
        MIN_PINNED_UM,
    )
    from PyReconstruct.modules.gui.palette.scale_bar import formatLength

    local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    _set_window(main_window, scale)
    lo, hi = palette.sbLengthRange()
    assert MIN_PINNED_UM <= lo <= hi <= MAX_PINNED_UM, (lo, hi)
    for length in (lo, math.sqrt(lo * hi), hi):
        asked, told = _answer(monkeypatch, ([length], True))
        palette.setSBLength()
        assert told == [], (length, told)
        pix, label = _render(palette.sb)
        assert pix and pix > 0, (scale, length)
        assert label == formatLength(length) + " µm", (scale, length, label)
        assert palette.sb.currentLength()[0] == length


@pytest.mark.gui
def test_a_length_past_what_a_bar_can_be_is_refused(
    main_window, local_series_settings, monkeypatch
):
    """2000000 µm fits a 560 px field at 1e4 µm/px but is longer than any bar
    may be, so it is refused with the range that can."""
    local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    _set_window(main_window, 1e4)
    asked, told = _answer(monkeypatch, ([2e6], True), (None, False))
    palette.setSBLength()
    assert told == ["Please enter a length from 400000 to 1000000 µm, or zoom "
                    "first to draw a longer or shorter bar."]
    assert palette.sb.override_length is None


@pytest.mark.gui
def test_both_ends_of_the_range_draw_their_own_length(
    main_window, local_series_settings, monkeypatch
):
    """At 0.000275 µm/px in a 560 px field the dialog offers 0.011 to 0.154
    µm. 0.011 / 0.000275 is 39.99999999999999 in floating point, a hair under
    the 40 px shortest bar, and the bar used to step up a decade to 0.11 µm.
    Each end now draws at its own length."""
    local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    _set_window(main_window, 0.000275)
    lo, hi = palette.sbLengthRange()
    assert (lo, hi) == (0.011, 0.154)
    for length, label in ((lo, "0.011 µm"), (hi, "0.154 µm")):
        _answer(monkeypatch, ([length], True))
        palette.setSBLength()
        assert palette.sb.currentLength()[0] == length
        assert _render(palette.sb)[1] == label


def test_each_end_of_the_range_draws_at_that_length_at_any_zoom():
    """The range the dialog shows and the length the bar draws are worked out
    by two functions. Over every three-figure scale from 1e-6 to 9.99e5
    µm/px, in three field widths, each end of the range draws unshifted."""
    from PyReconstruct.modules.gui.palette.scale_bar import drawableLengths

    shifted = []
    for width in (140, FIELD_W, 1366):
        for exponent in range(-8, 4):
            for digits in range(100, 1000):
                scale = float(f"{digits}e{exponent}")
                lo, hi = drawableLengths(scale, width)
                if lo > hi:
                    continue
                for length in (lo, hi):
                    if pinnedLength(length, scale, width)[0] != length:
                        shifted.append((scale, width, length))
    assert shifted == []


@pytest.mark.gui
@pytest.mark.parametrize("narrow", [True, False])
def test_no_dialog_when_no_length_can_be_drawn(
    main_window, local_series_settings, monkeypatch, narrow
):
    """A 30 px field is narrower than the 40 px shortest bar, and at 1e-9
    µm/px the field holds less than the shortest length a bar may be. Either
    way there is no length to offer, so the user is told why instead of
    being shown a range that runs backward."""
    local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    if narrow:
        _set_window(main_window, 0.01)
        main_window.field.resize(30, main_window.field.height())
    else:
        _set_window(main_window, 1e-9)
    lo, hi = palette.sbLengthRange()
    assert lo > hi
    asked, told = _answer(monkeypatch)
    palette.setSBLength()
    assert asked == []
    assert len(told) == 1 and "no scale bar length" in told[0]
    assert palette.sb.override_length is None


@pytest.mark.gui
@pytest.mark.parametrize("sb_x", [0.0, 0.01, 0.99, 1.0])
@pytest.mark.parametrize("bar", ["typed", "pinned", "full size"])
def test_the_whole_bar_stays_on_the_field_wherever_it_was_left(
    main_window, local_series_settings, monkeypatch, sb_x, bar
):
    """A bar saved near the right edge used to run off it: a 560 px bar typed
    in at x=544 of a 560 px field showed 16 px. It now moves left as far
    as it must, and the position the user left it at is kept, so a shorter
    bar goes back there."""
    series = local_series_settings(main_window)
    if bar == "pinned":
        series.setOption("scale_bar_mode", "micron_pinned")
        series.setOption("scale_bar_length_um", 1.4)   # 140 px, the full cap
    if bar == "full size":
        series.setOption("scale_bar_width", 100)
    palette = main_window.mouse_palette
    palette.reset()
    palette.sb_x = sb_x
    _set_window(main_window, 0.01)
    if bar == "typed":
        _answer(monkeypatch, ([5.6], True))
        palette.setSBLength()
    palette.placeSB()
    left, right = _field_edges(main_window)
    sb = palette.sb
    assert sb.width() > 100
    assert left <= sb.x() and sb.x() + sb.width() <= right, (sb.x(), sb.width())
    assert palette.sb_x == sb_x

    # a bar short enough to fit sits exactly where it was left
    palette.clearSBLength()
    series.setOption("scale_bar_mode", "screen_fraction")
    series.setOption("scale_bar_width", 20)
    palette.resize()
    saved_x, _y = palette.getButtonCoords("sb")
    if saved_x + sb.width() <= right:
        assert sb.x() == int(saved_x)
    else:
        assert sb.x() + sb.width() == right
    assert palette.sb_x == sb_x


@pytest.mark.gui
def test_a_bar_moved_to_the_left_drags_from_where_it_shows(
    main_window, local_series_settings, monkeypatch
):
    """A drag starts from the bar on screen, not the saved spot off to its
    right, so the bar moves with the first pixel of the drag."""
    local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    palette.sb_x = 0.99
    _set_window(main_window, 0.01)
    _answer(monkeypatch, ([4.0], True))
    palette.setSBLength()
    shown = palette.sb.x()
    palette.moveButton(-20, 0, "sb")
    palette.placeSB()
    # within the pixel any palette group loses to its saved fraction
    assert palette.sb.x() == pytest.approx(shown - 20, abs=1)
