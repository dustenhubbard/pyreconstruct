"""Scale bar: the 15 px default, a hover box that keeps off the bar, and one
settings page reachable from the bar's right-click menu.

* **The default.** 15 px for a store with no thickness in it. A stored value,
  6 included, is never rewritten.
* **The hover box.** It used to go in the bottom corner opposite the tool
  palette, which by default is the scale bar's corner, so it covered the bar.
  `hoverDisplayRect` now lifts it in that corner to sit just above the bar
  (or the section buttons), and it never lands on the selected trace and
  z-trace names painted at the top of the same side. A box too tall for the
  room left is cut shorter and scrolls.
* **One page, two places.** Series > Options > View and the bar's "Scale bar
  settings..." dialog are both built by `scale_bar_settings`, preview every
  control on the bar, store nothing until OK, and restore the bar on Cancel.
"""
import pytest

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtWidgets import QLabel

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.default_settings import (
    DEFAULT_SCALE_BAR_THICKNESS,
    default_settings,
)
from PyReconstruct.modules.gui.dialog import scale_bar_settings as sbs
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from PyReconstruct.modules.gui.dialog.scale_bar_settings import (
    ScaleBarSettingsDialog,
    readScaleBarSettings,
    scaleBarStructure,
)
from PyReconstruct.modules.gui.main.field_widget_6_paint import hoverDisplayRect
from PyReconstruct.modules.gui.palette.mouse_palette import MousePalette


# ------------------------------------------------------------------ default

def test_the_default_thickness_is_15():
    assert default_settings["scale_bar_thickness"] == 15
    assert DEFAULT_SCALE_BAR_THICKNESS == 15


def test_an_empty_store_gets_15_and_a_stored_6_stays_6(real_series):
    real_series.setSettingsStore(DictSettingsStore())
    assert real_series.getOption("scale_bar_thickness") == 15

    real_series.setSettingsStore(DictSettingsStore())
    real_series.setOption("scale_bar_thickness", 6)
    assert real_series.getOption("scale_bar_thickness") == 6


# ------------------------------------------------------- hover placement rule

FIELD = QRect(0, 0, 1000, 600)
BOX = QSize(200, 80)
M = 3
BOTTOM_LEFT = QPoint(M, 600 - 80 - M)
BOTTOM_RIGHT = QPoint(1000 - 200 - M, 600 - 80 - M)
BAR_BOTTOM_LEFT = QRect(10, 540, 250, 50)


def _spot(*args, **kwargs):
    """Where the whole box goes: these cases all leave room for all of it."""
    rect = hoverDisplayRect(*args, **kwargs)
    assert rect.size() == BOX
    return rect.topLeft()


@pytest.mark.parametrize("prefer_right, expected", [
    (False, BOTTOM_LEFT), (True, BOTTOM_RIGHT)])
def test_with_nothing_in_the_way_the_box_goes_where_it_always_did(prefer_right, expected):
    assert _spot(FIELD, BOX, prefer_right) == expected


def test_a_hidden_bar_is_not_dodged():
    assert _spot(FIELD, BOX, False, scale_bar=None) == BOTTOM_LEFT


def test_the_box_is_lifted_just_above_the_bar():
    assert _spot(
        FIELD, BOX, False, scale_bar=BAR_BOTTOM_LEFT) == QPoint(M, 540 - M - 80)


def test_a_bar_across_the_whole_bottom_still_lifts_the_box_on_its_side():
    wide_bar = QRect(0, 540, 1000, 50)
    assert _spot(FIELD, BOX, False, scale_bar=wide_bar) == QPoint(
        M, 540 - M - 80)
    assert _spot(FIELD, BOX, True, scale_bar=wide_bar) == QPoint(
        1000 - 200 - M, 540 - M - 80)


def test_the_box_is_lifted_past_everything_stacked_in_its_corner():
    inc_buttons = QRect(900, 500, 90, 85)
    sliders = QRect(880, 400, 110, 60)
    assert _spot(
        FIELD, BOX, True, others=[inc_buttons, sliders]) == QPoint(
        1000 - 200 - M, 400 - M - 80)


def test_the_default_layout_keeps_the_box_bottom_left_above_the_bar():
    """Bar bottom-left, section buttons bottom-right, tools top-right, and a
    selection list top-left: the box sits just above the bar."""
    inc_buttons = QRect(900, 500, 90, 85)
    tools = QRect(950, 10, 40, 400)
    selection = QRect(8, 0, 180, 120)
    assert _spot(
        FIELD, BOX, False, scale_bar=BAR_BOTTOM_LEFT,
        others=[inc_buttons, tools], text=selection) == QPoint(M, 540 - M - 80)


def test_the_box_never_lands_on_the_corner_text():
    """A selection list tall enough to meet the lifted box sends it to the
    other side, lifted the same way."""
    selection = QRect(8, 0, 180, 500)
    assert _spot(
        FIELD, BOX, False, scale_bar=BAR_BOTTOM_LEFT,
        text=selection) == BOTTOM_RIGHT


def test_the_corner_text_alone_does_not_move_the_box():
    selection = QRect(8, 0, 180, 120)
    assert _spot(FIELD, BOX, False, text=selection) == BOTTOM_LEFT


def test_covering_a_button_beats_covering_the_bar():
    everywhere = [QRect(0, 0, 1000, 600)]
    assert _spot(
        FIELD, BOX, False, scale_bar=BAR_BOTTOM_LEFT,
        others=everywhere) == BOTTOM_RIGHT


def test_when_every_spot_covers_the_bar_the_usual_corner_wins():
    bar_everywhere = QRect(0, 0, 1000, 600)
    assert _spot(
        FIELD, BOX, False, scale_bar=bar_everywhere) == BOTTOM_LEFT


def test_a_box_too_tall_for_either_side_is_cut_to_the_taller_gap():
    """Names down the left and the bar bottom right: neither side has room for
    the whole box, so it takes the taller gap and its text scrolls."""
    selection = QRect(8, 0, 180, 300)
    bar = QRect(800, 540, 190, 50)
    assert hoverDisplayRect(
        FIELD, QSize(200, 590), False, scale_bar=bar, text=selection,
        min_height=20) == QRect(1000 - 200 - M, M, 200, 540 - 2 * M)


def test_a_gap_shorter_than_one_line_is_not_used():
    selection = QRect(8, 0, 180, 580)
    bar = QRect(800, 10, 190, 580)
    assert hoverDisplayRect(
        FIELD, QSize(200, 590), False, scale_bar=bar, text=selection,
        min_height=20).size() == QSize(200, 590)


def _hover(main_window, qapp):
    field = main_window.field
    trace = next(t for traces in field.section.contours.values() for t in traces)
    field.hover_columns = [("Name", True)]
    field.displayed_item = trace
    field.displayHoverInfo()
    qapp.processEvents()
    return field.hover_display.geometry()


@pytest.mark.gui
def test_the_hover_box_does_not_cover_the_scale_bar(main_window, qapp):
    """The default layout and a real hover: the box must clear the bar."""
    palette = main_window.mouse_palette
    assert palette.mode_x > .5, "the default layout puts the tools on the right"
    if palette.sb_hidden:
        palette.toggleSB()
    assert not palette.sb.isHidden()

    box = _hover(main_window, qapp)

    assert not box.intersects(palette.sb.geometry())
    assert main_window.field.geometry().contains(box)


@pytest.mark.gui
def test_the_hover_box_does_not_cover_the_selected_trace_names(main_window, qapp):
    """A selection list at top-left and the bar at bottom-left, the default
    layout: the box must clear both."""
    field = main_window.field
    palette = main_window.mouse_palette
    if palette.sb_hidden:
        palette.toggleSB()
    traces = [t for traces in field.section.contours.values() for t in traces]
    field.section.selected_traces = traces[:3]
    field.mouse_x = field.mouse_y = -10_000
    field.grab()                       # paintText draws the list
    text = field.cornerTextRect()
    assert text is not None
    assert "Selected Traces:" in field.corner_text[0]

    box = _hover(main_window, qapp)

    assert not box.intersects(text)
    assert not box.intersects(palette.sb.geometry())
    assert main_window.field.geometry().contains(box)


@pytest.mark.gui
@pytest.mark.parametrize("tools_x, bar_corner", [
    (.99, (.99, .99)), (.01, (.01, .99))])
def test_a_long_comment_clears_the_names_and_the_bar_on_opposite_sides(
    main_window, local_series_settings, qapp, tools_x, bar_corner
):
    """A small window, the selected names on one side, the bar in the other
    bottom corner, and a comment long enough to want the whole field height:
    the box must clear both."""
    series = local_series_settings(main_window)
    main_window.resize(640, 480)
    qapp.processEvents()
    palette = main_window.mouse_palette
    palette.reset()
    palette.mode_x = tools_x
    palette.sb_x, palette.sb_y = bar_corner
    palette.resize()
    if palette.sb_hidden:
        palette.toggleSB()
    field = main_window.field
    traces = [t for traces in field.section.contours.values() for t in traces]
    field.section.selected_traces = traces[:3]
    field.mouse_x = field.mouse_y = -10_000
    field.grab()                       # paintText draws the list
    text = field.cornerTextRect()
    assert "Selected Traces:" in field.corner_text[0]
    series.setAttr(traces[0].name, "comment",
                   "A description of this traced object. " * 12)
    field.hover_columns = [("Name", True), ("Comment", True)]
    field.displayed_item = traces[0]

    field.displayHoverInfo()
    qapp.processEvents()
    box = field.hover_display.geometry()

    assert field.geometry().contains(box)
    assert not box.intersects(text)
    assert not box.intersects(palette.sb.geometry())


@pytest.mark.gui
def test_the_placement_is_given_the_corner_text_and_the_obstacles(
    main_window, qapp, monkeypatch
):
    from PyReconstruct.modules.gui.main import field_widget_6_paint as paint

    field = main_window.field
    traces = [t for traces in field.section.contours.values() for t in traces]
    field.section.selected_traces = traces[:2]
    field.mouse_x = field.mouse_y = -10_000
    field.grab()
    seen = {}
    real = paint.hoverDisplayRect

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(paint, "hoverDisplayRect", spy)
    _hover(main_window, qapp)

    assert seen["text"] == field.cornerTextRect() is not None
    sb, others = main_window.mouse_palette.hoverObstacles()
    assert (seen["scale_bar"], seen["others"]) == (sb, others)


@pytest.mark.gui
def test_with_the_bottom_clear_the_hover_box_keeps_its_usual_corner(main_window, qapp):
    """Hide the bar and the other bottom groups (the suite's narrow window
    puts the trace palette under the bottom corners): bottom-left, as before."""
    field = main_window.field
    palette = main_window.mouse_palette
    for hidden, toggle in ((palette.sb_hidden, palette.toggleSB),
                           (palette.palette_hidden, palette.togglePalette),
                           (palette.inc_hidden, palette.toggleIncrement),
                           (palette.bc_hidden, palette.toggleBC)):
        if not hidden:
            toggle()
    assert palette.hoverObstacles()[0] is None

    box = _hover(main_window, qapp)

    # bottom-left, as before, because the tools are on the right
    assert box.x() == field.x() + 3
    assert box.y() + box.height() == field.y() + field.height() - 3


def test_the_hover_obstacles_skip_hidden_widgets():
    class _W:
        def __init__(self, hidden, rect):
            self._hidden, self._rect = hidden, rect

        def isHidden(self):
            return self._hidden

        def geometry(self):
            return self._rect

    class _P:
        hoverObstacles = MousePalette.hoverObstacles

    p = _P()
    p.sb = _W(True, QRect(0, 0, 5, 5))
    p.mode_buttons = {"Pointer": (_W(False, QRect(1, 1, 2, 2)), 0, None)}
    p.palette_buttons = [_W(True, QRect(2, 2, 2, 2))]
    p.palette_side_buttons = []
    p.label = None
    p.inc_buttons = [_W(False, QRect(3, 3, 2, 2))]
    p.bc_widgets = [(_W(False, QRect(4, 4, 1, 1)), _W(True, QRect(5, 5, 1, 1)))]
    sb, others = p.hoverObstacles()
    assert sb is None
    assert others == [QRect(1, 1, 2, 2), QRect(3, 3, 2, 2), QRect(4, 4, 1, 1)]


# ------------------------------------------------- one page, two places

def _labels(page):
    return [w.text() for w in page.findChildren(QLabel) if w.text()]


def _inputs(page):
    return [field.type for field in page.inputs]


def _buttons(page, index):
    layout = page.inputs[index].widget.layout()
    return [layout.itemAt(i).widget() for i in range(layout.count())]


def _checks(page):
    return _buttons(page, 0)


def _radios(page):
    return _buttons(page, 1)


@pytest.mark.gui
def test_the_options_group_and_the_dialog_are_the_same_page(main_window, local_series_settings):
    series = local_series_settings(main_window)
    options = AllOptionsDialog(main_window, series)
    dialog = ScaleBarSettingsDialog(main_window, series, main_window.mouse_palette)
    try:
        page = options.all_widgets["scale_bar"]
        assert _inputs(page) == _inputs(dialog) == [
            "check", "radio", "slider", "float", "slider"]
        # the group carries its title as a label; the dialog has a window title
        assert [t for t in _labels(page) if t != "Scale Bar"] == _labels(dialog)
        assert dialog.windowTitle() == "Scale Bar Settings"
    finally:
        dialog.reject()
        options.reject()


def test_the_decade_note_sits_under_the_length_and_thickness_is_last():
    class _S:
        def getOption(self, key, *_):
            return default_settings[key]

    flat = [item for row in scaleBarStructure(_S()) for item in row]
    assert (flat.index(sbs.LENGTH_LABEL) < flat.index(sbs.LENGTH_NOTE)
            < flat.index(sbs.THICKNESS_LABEL))
    assert flat[-1][0] == "slider", "thickness is last"
    assert len(sbs.LENGTH_NOTE) <= 90, "one line, two at most"


@pytest.mark.gui
@pytest.mark.parametrize("pinned", [False, True])
def test_only_the_controls_for_the_chosen_mode_are_enabled(
    main_window, local_series_settings, pinned
):
    series = local_series_settings(main_window)
    series.setOption("scale_bar_mode", "micron_pinned" if pinned else "screen_fraction")
    dialog = ScaleBarSettingsDialog(main_window, series)
    try:
        length = dialog.inputs[3].widget
        size = dialog.inputs[2].widget
        assert length.isEnabled() is pinned
        # the size is the bar's width in one mode and its cap in the other
        assert size.isEnabled()
        assert (sbs.SIZE_LABEL_FIXED if pinned else sbs.SIZE_LABEL_SHARE) in _labels(dialog)

        _radios(dialog)[0 if pinned else 1].setChecked(True)
        assert length.isEnabled() is not pinned
        assert (sbs.SIZE_LABEL_SHARE if pinned else sbs.SIZE_LABEL_FIXED) in _labels(dialog)
    finally:
        dialog.reject()


def _bar_state(sb):
    return (sb.width(), sb.height(), sb.thickness, sb.micron_length,
            dict(sb.display_preview), sb.geometry())


@pytest.mark.gui
def test_every_control_previews_and_cancel_restores(main_window, local_series_settings, qapp):
    series = local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    sb = palette.sb
    before = _bar_state(sb)
    stored = {key: series.getOption(key) for key in sbs.KEYS}

    dialog = ScaleBarSettingsDialog(main_window, series, palette)
    _checks(dialog)[1].setChecked(False)               # ticks off
    assert sb.displayOption("show_scale_bar_ticks") is False
    dialog.inputs[4].widget.setValue(22)               # thickness
    assert sb.thickness == 22
    dialog.inputs[2].widget.setValue(60)               # size
    assert sb.max_pixel_length == palette.sbWidth(60)
    _radios(dialog)[1].setChecked(True)                # fixed length
    dialog.inputs[3].widget.setText("2")
    dialog.inputs[3].widget.textEdited.emit("2")
    assert sb.micron_length == 2.0
    _checks(dialog)[0].setChecked(False)               # numbers off
    assert sb.displayOption("show_scale_bar_text") is False

    assert {key: series.getOption(key) for key in sbs.KEYS} == stored, (
        "a preview stored something")

    dialog.reject()
    qapp.processEvents()
    assert palette.sb is sb
    assert _bar_state(sb) == before


@pytest.mark.gui
def test_a_half_typed_length_previews_the_stored_one(main_window, local_series_settings):
    series = local_series_settings(main_window)
    series.setOption("scale_bar_mode", "micron_pinned")
    series.setOption("scale_bar_length_um", 5.0)
    main_window.mouse_palette.reset()
    dialog = ScaleBarSettingsDialog(main_window, series, main_window.mouse_palette)
    try:
        length = dialog.inputs[3].widget
        for partial in ("", "-", "0", "0."):
            length.setText(partial)
            length.textEdited.emit(partial)
            assert readScaleBarSettings(dialog, series)["scale_bar_length_um"] == 5.0
            assert main_window.mouse_palette.sb.micron_length == 5.0
    finally:
        dialog.reject()


@pytest.mark.gui
def test_ok_stores_every_setting_and_keeps_the_bar(main_window, local_series_settings):
    series = local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    sb = palette.sb

    dialog = ScaleBarSettingsDialog(main_window, series, palette)
    _checks(dialog)[0].setChecked(False)
    _checks(dialog)[1].setChecked(False)
    _radios(dialog)[1].setChecked(True)
    dialog.inputs[2].widget.setValue(40)
    dialog.inputs[3].widget.setText("3")
    dialog.inputs[4].widget.setValue(9)
    assert dialog.accept() is True

    assert series.getOption("show_scale_bar_text") is False
    assert series.getOption("show_scale_bar_ticks") is False
    assert series.getOption("scale_bar_mode") == "micron_pinned"
    assert series.getOption("scale_bar_width") == 40
    assert series.getOption("scale_bar_length_um") == 3.0
    assert series.getOption("scale_bar_thickness") == 9
    # applied in place: same widget, nothing left previewing
    assert palette.sb is sb
    assert sb.display_preview == {}
    assert (sb.thickness, sb.micron_length) == (9, 3.0)
    assert sb.property("pyrecon_hide_menu")


@pytest.mark.gui
def test_ok_refuses_a_length_that_is_not_a_number(main_window, local_series_settings,
                                                   monkeypatch):
    from PyReconstruct.modules.gui.dialog import quick_dialog
    said = []
    monkeypatch.setattr(quick_dialog, "notify", lambda *a, **k: said.append(a))
    series = local_series_settings(main_window)
    before = series.getOption("scale_bar_length_um")
    dialog = ScaleBarSettingsDialog(main_window, series, main_window.mouse_palette)
    try:
        dialog.inputs[3].widget.setText("abc")
        assert dialog.accept() is False
        assert said, "the user is told why"
        assert series.getOption("scale_bar_length_um") == before
    finally:
        dialog.reject()


@pytest.mark.gui
def test_an_inf_length_is_not_stored(main_window, local_series_settings):
    series = local_series_settings(main_window)
    before = series.getOption("scale_bar_length_um")
    dialog = ScaleBarSettingsDialog(main_window, series, main_window.mouse_palette)
    dialog.inputs[3].widget.setText("1e400")
    assert dialog.accept() is True
    assert series.getOption("scale_bar_length_um") == before


@pytest.mark.gui
def test_the_right_click_item_opens_the_settings(main_window, monkeypatch):
    palette = main_window.mouse_palette
    opened = []
    monkeypatch.setattr(ScaleBarSettingsDialog, "exec",
                        lambda self: opened.append(self) or 0)
    palette._hide_menu = None
    palette.sb.customContextMenuRequested.emit(QPoint(2, 2))
    menu = palette._hide_menu
    actions = {a.text(): a for a in menu.actions()}
    menu.hide()
    actions["Scale bar settings..."].trigger()
    assert len(opened) == 1
    assert opened[0].palette is palette
    opened[0].reject()


@pytest.mark.gui
def test_the_options_group_previews_ticks_too(main_window, local_series_settings, qapp):
    """Unchecking ticks in Series > Options previews on the bar and Cancel restores it."""
    series = local_series_settings(main_window)
    palette = main_window.mouse_palette
    palette.reset()
    height = palette.sb.height()
    options = AllOptionsDialog(main_window, series)
    _checks(options.all_widgets["scale_bar"])[1].setChecked(False)
    assert palette.sb.height() < height
    assert series.getOption("show_scale_bar_ticks") is True
    options.reject()
    qapp.processEvents()
    assert palette.sb.height() == height
