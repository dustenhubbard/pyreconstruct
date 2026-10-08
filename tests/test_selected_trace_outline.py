"""A selected trace is drawn as a see-through glow with a solid line on top.

Both are in the trace's own color. The glow is five pixels across and its
opacity is the `selection_glow_opacity` option (a percent, 40 by default); the
line is two pixels across and always solid. The glow lets the image show
through, so a membrane under the trace stays visible, and the selection is
still easy to find zoomed out. The look before this was a black, white and
color band six pixels across (issue #438), which hid the image under it and
washed out the trace's color.

These render a real section headlessly and read the pixels across the top edge
of an axis-aligned square trace.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

W, H = 400, 400
PPU = 100.0                      # pixels per field unit
MAGENTA = (255, 0, 255)
EDGE_Y = 100                     # pixel row of the square's top edge
COLUMN_X = 300                   # a pixel column crossing that edge


def _alpha(percent):
    """The alpha a glow pixel gets at `percent` opacity on an empty layer."""
    return round(percent / 100 * 255)


@pytest.fixture
def series(shapes1_jser):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore
    s = Series.openJser(str(shapes1_jser))
    s.setSettingsStore(DictSettingsStore())
    yield s
    s.setSettingsStore(None)
    s.close()


def _column(series, selected, fill_mode=("none", "none"), closed=True, focus_on=False,
            preview=None):
    """Render one magenta square and return the pixels across its top edge.

    Returns a dict of pixel row -> (r, g, b, a) for rows near the edge; rows
    with nothing drawn are left out.
    """
    from PyReconstruct.modules.datatypes.trace import Trace
    from PyReconstruct.modules.backend.view.section_layer import SectionLayer

    section = series.loadSection(list(series.sections.keys())[0])
    for contour in section.contours.values():
        for t in contour.getTraces():
            t.hidden = True

    window = [0, 0, W / PPU, H / PPU]
    series.window = window
    # field y grows upward, so the top edge at pixel row 100 is field y 3
    corners = [(2, 3), (4, 3), (4, 1), (2, 1)]
    trace = Trace("outline_probe", MAGENTA, closed=closed)
    trace.points = [
        tuple(p) for p in section.tform.mapPointsArray(corners, inverted=True).tolist()
    ]
    trace.fill_mode = fill_mode
    section.addTrace(trace, log_event=False)
    if selected:
        section.addSelectedTrace(trace)

    layer = SectionLayer(section, series, load_image_layer=False)
    layer.glow_opacity_preview = preview
    image = layer.generateTraceLayer(
        (W, H), window, window_moved=True, focus_on=focus_on
    ).toImage()

    column = {}
    for y in range(EDGE_Y - 8, EDGE_Y + 9):
        c = image.pixelColor(COLUMN_X, y)
        if c.alpha() > 0:
            column[y] = (c.red(), c.green(), c.blue(), c.alpha())
    return column


def _alphas(column):
    """The alphas met going down the column, each with how many pixels it spans."""
    runs = []
    for y in sorted(column):
        a = column[y][3]
        if runs and abs(runs[-1][0] - a) <= 2:
            runs[-1][1] += 1
        else:
            runs.append([a, 1])
    return [tuple(run) for run in runs]


def _colors(column):
    return {rgba[:3] for rgba in column.values()}


def _glow_runs(percent):
    """Glow, solid line, glow: five pixels across with the line inside.

    An odd-width pen at whole-pixel coordinates puts its extra pixel on the
    far side, so the glow shows one pixel above the line and two below.
    """
    a = _alpha(percent)
    return [(a, 1), (255, 2), (a, 2)]


def _assert_runs(column, expected):
    got = _alphas(column)
    assert len(got) == len(expected), column
    for (a, n), (want_a, want_n) in zip(got, expected):
        assert n == want_n, column
        assert a == pytest.approx(want_a, abs=2), column


# --------------------------------------------------------------------------
# the look: a glow and a solid line, both in the trace's own color
# --------------------------------------------------------------------------

@pytest.mark.parametrize("closed", [True, False], ids=["closed", "open"])
def test_selected_trace_is_a_glow_with_a_solid_line(series, closed):
    column = _column(series, selected=True, closed=closed)
    # the trace's own color only: no black or white band
    assert _colors(column) == {MAGENTA}, column
    _assert_runs(column, _glow_runs(40))
    assert column[EDGE_Y][3] == 255, column


@pytest.mark.parametrize("closed", [True, False], ids=["closed", "open"])
def test_glow_is_five_pixels_and_the_line_two(series, closed):
    column = _column(series, selected=True, closed=closed)
    assert len(column) == 5, column
    assert sum(1 for rgba in column.values() if rgba[3] == 255) == 2, column


def test_outline_keeps_a_forced_color(series):
    # focus mode forces the focused object's color, glow and line both
    focus = (246, 249, 72)
    column = _column(series, selected=True, focus_on="outline_probe")
    assert column[EDGE_Y - 1] == (*focus, 255), column
    assert column[EDGE_Y] == (*focus, 255), column
    # the outer glow; inside, focus mode also lays a 25% fill under it
    assert column[EDGE_Y - 2][3] == pytest.approx(_alpha(40), abs=2), column
    for rgba in column.values():
        assert rgba[:3] == pytest.approx(focus, abs=3), column


def test_unselected_trace_has_no_outline(series):
    column = _column(series, selected=False)
    assert list(column.values()) == [(*MAGENTA, 255)], column


# --------------------------------------------------------------------------
# the selection_glow_opacity option
# --------------------------------------------------------------------------

def test_the_glow_opacity_defaults_to_40_percent(series):
    from PyReconstruct.modules.datatypes.default_settings import default_settings
    assert default_settings["selection_glow_opacity"] == 40
    assert series.getOption("selection_glow_opacity") == 40


def test_settings_without_the_key_get_the_default(series):
    # settings saved by a build that had no glow option: other keys, not this one
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore
    store = DictSettingsStore()
    store.set_value(None, "fill_opacity", 0.3)
    series.setSettingsStore(store)
    assert not store.contains(None, "selection_glow_opacity")

    column = _column(series, selected=True)

    _assert_runs(column, _glow_runs(40))
    assert series.getOption("selection_glow_opacity") == 40


@pytest.mark.parametrize("percent", [20, 70])
def test_the_option_sets_the_glow_opacity(series, percent):
    series.setOption("selection_glow_opacity", percent)
    column = _column(series, selected=True)
    assert _colors(column) == {MAGENTA}, column
    _assert_runs(column, _glow_runs(percent))


def test_at_0_percent_only_the_solid_line_shows(series):
    series.setOption("selection_glow_opacity", 0)
    column = _column(series, selected=True)
    assert list(column.values()) == [(*MAGENTA, 255)] * 2, column


def test_at_100_percent_the_glow_is_solid(series):
    series.setOption("selection_glow_opacity", 100)
    column = _column(series, selected=True)
    assert list(column.values()) == [(*MAGENTA, 255)] * 5, column


@pytest.mark.parametrize("stored, used", [(-10, 0), (150, 100)])
def test_a_value_out_of_range_is_clamped(series, stored, used):
    series.setOption("selection_glow_opacity", stored)
    column = _column(series, selected=True)
    expected = _column(series, selected=True, preview=used)
    assert column == expected


def test_each_redraw_reads_the_option(series):
    series.setOption("selection_glow_opacity", 20)
    before = _column(series, selected=True)
    series.setOption("selection_glow_opacity", 70)
    after = _column(series, selected=True)
    _assert_runs(before, _glow_runs(20))
    _assert_runs(after, _glow_runs(70))


def test_a_preview_overrides_the_stored_value(series):
    series.setOption("selection_glow_opacity", 40)
    column = _column(series, selected=True, preview=70)
    _assert_runs(column, _glow_runs(70))
    assert series.getOption("selection_glow_opacity") == 40


# --------------------------------------------------------------------------
# more cases: open ends, painter state between traces, and fills
# --------------------------------------------------------------------------

LEFT_EDGE_X = 200                # pixel column of the square's left edge
MID_Y = 200                      # a pixel row halfway down that edge
INSIDE = (300, 200)              # a pixel well inside the square


def _render(series, specs):
    """Render squares and return the trace layer image.

    Each spec is (selected, fill_mode, closed, corners), drawn in that order.
    """
    from PyReconstruct.modules.datatypes.trace import Trace
    from PyReconstruct.modules.backend.view.section_layer import SectionLayer

    section = series.loadSection(list(series.sections.keys())[0])
    for contour in section.contours.values():
        for t in contour.getTraces():
            t.hidden = True

    window = [0, 0, W / PPU, H / PPU]
    series.window = window
    for selected, fill_mode, closed, corners in specs:
        trace = Trace("outline_probe", MAGENTA, closed=closed)
        trace.points = [
            tuple(p)
            for p in section.tform.mapPointsArray(corners, inverted=True).tolist()
        ]
        trace.fill_mode = fill_mode
        section.addTrace(trace, log_event=False)
        if selected:
            section.addSelectedTrace(trace)

    layer = SectionLayer(section, series, load_image_layer=False)
    return layer.generateTraceLayer((W, H), window, window_moved=True).toImage()


SQUARE = [(2, 3), (4, 3), (4, 1), (2, 1)]   # pixels x 200..400, y 100..300
OTHER = [(0.5, 3), (1.5, 3), (1.5, 1), (0.5, 1)]  # pixels x 50..150


def _drawn(image, x, y):
    return image.pixelColor(x, y).alpha() > 0


@pytest.mark.parametrize("closed", [True, False], ids=["closed", "open"])
def test_a_selected_open_trace_is_not_closed_by_the_outline(series, closed):
    image = _render(series, [(True, ("none", "none"), closed, SQUARE)])
    # the left edge runs from the last point back to the first, so only a
    # closed trace has it
    edge = [_drawn(image, x, MID_Y) for x in range(LEFT_EDGE_X - 6, LEFT_EDGE_X + 7)]
    assert any(edge) == closed, edge


@pytest.mark.parametrize("plain_last", [True, False], ids=["after", "before"])
@pytest.mark.parametrize("selected", [True, False], ids=["selected", "unselected"])
def test_painter_state_does_not_reach_the_next_trace(series, selected, plain_last):
    # a trace with a transparent fill, selected or not, leaves a brush, a
    # lowered opacity or a wide pen on the shared painter if nothing resets them
    first = (selected, ("transparent", "always"), True, OTHER)
    plain = (False, ("none", "none"), True, SQUARE)
    image = _render(series, [first, plain] if plain_last else [plain, first])

    # the plain square: a one pixel line in its own color, fully opaque,
    # nothing inside and nothing beside the line
    c = image.pixelColor(300, EDGE_Y)
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (*MAGENTA, 255)
    assert not _drawn(image, 300, EDGE_Y - 2)
    assert not _drawn(image, 300, EDGE_Y + 2)
    assert not _drawn(image, *INSIDE)


@pytest.mark.parametrize(
    "condition, selected, filled",
    [
        ("selected", True, True),
        ("selected", False, False),
        ("unselected", True, False),
        ("unselected", False, True),
    ],
)
def test_a_fill_follows_its_condition(series, condition, selected, filled):
    image = _render(series, [(selected, ("solid", condition), True, SQUARE)])
    c = image.pixelColor(*INSIDE)
    assert _drawn(image, *INSIDE) == filled
    if filled:
        assert (c.red(), c.green(), c.blue(), c.alpha()) == (*MAGENTA, 255)


def test_a_transparent_fill_under_the_outline(series):
    fill_opacity = series.getOption("fill_opacity")
    assert 0 < fill_opacity < 1, "the test needs a partly transparent fill"
    glow = series.getOption("selection_glow_opacity") / 100
    image = _render(series, [(True, ("transparent", "always"), True, SQUARE)])

    c = image.pixelColor(*INSIDE)
    assert (c.red(), c.green(), c.blue()) == pytest.approx(MAGENTA, abs=2)
    assert c.alpha() == pytest.approx(fill_opacity * 255, abs=2)

    # the line stays solid over the fill; the inner glow adds to the fill
    line = image.pixelColor(COLUMN_X, EDGE_Y)
    assert line.alpha() == 255
    inner = image.pixelColor(COLUMN_X, EDGE_Y + 2)
    both = 1 - (1 - fill_opacity) * (1 - glow)
    assert inner.alpha() == pytest.approx(both * 255, abs=3)
