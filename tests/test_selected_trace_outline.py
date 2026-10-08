"""A selected trace is drawn as upstream PyReconstruct draws it.

The trace keeps its normal one pixel line, and the same path is stroked again
in the trace's own color, eight pixels wide at 40% opacity. That glow goes on
before the fill, so a fill covers its inner half.

The main check renders a section through the real trace layer and compares it
pixel for pixel with ``_upstream_render``, a copy of the drawing calls in
upstream's ``TraceLayer._drawTrace``: one fresh QPainter per trace, line, then
glow, then fill. The other cases read pixels across the top edge of an
axis-aligned square trace.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

W, H = 400, 400
PPU = 100.0                      # pixels per field unit
MAGENTA = (255, 0, 255)
FOCUS = (246, 249, 72)           # the focused object's forced color
EDGE_Y = 100                     # pixel row of the square's top edge
COLUMN_X = 300                   # a pixel column crossing that edge
LEFT_EDGE_X = 200                # pixel column of the square's left edge
MID_Y = 200                      # a pixel row halfway down that edge
INSIDE = (300, 200)              # a pixel well inside the square

SQUARE = [(2, 3), (4, 3), (4, 1), (2, 1)]   # pixels x 200..400, y 100..300
OTHER = [(0.5, 3), (1.5, 3), (1.5, 1), (0.5, 1)]  # pixels x 50..150
# slanted edges and sharp corners, so pen joins and caps show
STAR = [(1, 3.6), (1.6, 2.2), (3.4, 2.8), (2.2, 1.6), (3, 0.4), (0.6, 1.4)]


@pytest.fixture
def series(shapes1_jser):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    s = Series.openJser(str(shapes1_jser))
    # only traces on the layer, so it compares with the upstream trace drawing
    s.setOption("show_ztraces", False)
    s.setOption("show_flags", "none")
    yield s
    s.close()


def _render(series, specs, focus_on=False):
    """Render traces through the trace layer.

    Each spec is (selected, fill_mode, closed, corners), drawn in that order.
    Returns the image and the layer.
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
    image = layer.generateTraceLayer(
        (W, H), window, window_moved=True, focus_on=focus_on
    ).toImage()
    return image, layer


def _upstream_render(layer, focus_on=False):
    """Draw the traces the layer drew with upstream's drawing calls."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap

    section = layer.section
    fill_opacity = layer.series.getOption("fill_opacity")
    pixmap = QPixmap(W, H)
    pixmap.fill(Qt.transparent)
    for trace in layer.traces_in_view:
        color = None
        if focus_on:
            color = FOCUS if trace.name == focus_on else (42, 255, 128)
        draw_color = color if color else trace.color
        qpoints = layer.traceToPix(trace, qpoints=True)
        selected = trace in section.selected_traces

        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor(*draw_color), 1))
        if trace.closed:
            painter.drawPolygon(qpoints)
        else:
            painter.drawPolyline(qpoints)

        if selected:
            painter.setPen(QPen(QColor(*draw_color), 8))
            painter.setOpacity(0.4)
            if trace.closed:
                painter.drawPolygon(qpoints)
            else:
                painter.drawPolyline(qpoints)

        if (
            (trace.closed) and
            (trace.fill_mode[0] != "none") and (
                (trace.fill_mode[1] == "always") or
                ((trace.fill_mode[1] == "selected") == selected)
            )
        ):
            fill = True
        elif trace.closed and color:
            fill = True
        else:
            fill = False

        if fill:
            painter.setPen(QPen(QColor(*draw_color), 1))
            painter.setBrush(QBrush(QColor(*draw_color)))
            if color:
                painter.setOpacity(0.25)
            elif trace.fill_mode[0] == "transparent":
                painter.setOpacity(fill_opacity)
            elif trace.fill_mode[0] == "solid":
                painter.setOpacity(1)
            painter.drawPolygon(qpoints)
        painter.end()
    return pixmap.toImage()


def _rgba(image):
    from PySide6.QtGui import QImage
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.bytesPerLine() // 4, 4
    )[:, :image.width()].copy()


def _assert_same_pixels(image, expected):
    got, want = _rgba(image), _rgba(expected)
    assert got.shape == want.shape
    differ = np.argwhere((got != want).any(axis=2))
    assert not len(differ), (
        f"{len(differ)} pixels differ from upstream, first at (y, x) "
        f"{tuple(differ[0])}: {tuple(got[tuple(differ[0])])} "
        f"instead of {tuple(want[tuple(differ[0])])}"
    )


def _column(image, x=COLUMN_X):
    """Pixel row -> (r, g, b, a) near the square's top edge, drawn pixels only."""
    column = {}
    for y in range(EDGE_Y - 8, EDGE_Y + 9):
        c = image.pixelColor(x, y)
        if c.alpha():
            column[y] = (c.red(), c.green(), c.blue(), c.alpha())
    return column


def _drawn(image, x, y):
    return image.pixelColor(x, y).alpha() > 0


# --------------------------------------------------------------------------
# pixel for pixel against upstream
# --------------------------------------------------------------------------

FILLS = [
    ("none", "none"),
    ("transparent", "always"),
    ("solid", "always"),
    ("solid", "selected"),
    ("transparent", "unselected"),
]


@pytest.mark.parametrize("fill_mode", FILLS, ids=["-".join(f) for f in FILLS])
@pytest.mark.parametrize("closed", [True, False], ids=["closed", "open"])
@pytest.mark.parametrize("shape", [SQUARE, STAR], ids=["square", "star"])
def test_a_selected_trace_matches_upstream(series, shape, closed, fill_mode):
    image, layer = _render(series, [(True, fill_mode, closed, shape)])
    assert layer.traces_in_view
    _assert_same_pixels(image, _upstream_render(layer))


@pytest.mark.parametrize("closed", [True, False], ids=["closed", "open"])
def test_a_selected_trace_in_focus_mode_matches_upstream(series, closed):
    image, layer = _render(
        series, [(True, ("none", "none"), closed, STAR)], focus_on="outline_probe"
    )
    _assert_same_pixels(image, _upstream_render(layer, focus_on="outline_probe"))


def test_overlapping_traces_match_upstream(series):
    # selected and unselected, filled and not, drawn over each other
    specs = [
        (True, ("transparent", "always"), True, STAR),
        (False, ("solid", "always"), True, OTHER),
        (True, ("none", "none"), False, SQUARE),
        (False, ("none", "none"), True, STAR),
        (True, ("solid", "always"), True, OTHER),
    ]
    image, layer = _render(series, specs)
    assert len(layer.traces_in_view) == len(specs)
    _assert_same_pixels(image, _upstream_render(layer))


# --------------------------------------------------------------------------
# the look itself
# --------------------------------------------------------------------------

def test_a_selected_trace_glows_in_its_own_color(series):
    image, _ = _render(series, [(True, ("none", "none"), True, SQUARE)])
    column = _column(image)
    # eight pixels across, all the trace's color: the one pixel line at full
    # opacity and the glow around it at 40%
    assert len(column) == 8, column
    assert {rgba[:3] for rgba in column.values()} == {MAGENTA}, column
    assert column[EDGE_Y][3] == 255, column
    glow = {rgba[3] for y, rgba in column.items() if y != EDGE_Y}
    assert glow == {round(0.4 * 255)}, column


def test_a_selected_trace_in_focus_mode_glows_in_the_forced_color(series):
    image, _ = _render(
        series, [(True, ("none", "none"), False, SQUARE)], focus_on="outline_probe"
    )
    column = _column(image)
    assert len(column) == 8, column
    for rgba in column.values():
        # a 40% pixel loses a step to rounding
        assert rgba[:3] == pytest.approx(FOCUS, abs=1), column


def test_an_unselected_trace_is_a_one_pixel_line(series):
    image, _ = _render(series, [(False, ("none", "none"), True, SQUARE)])
    assert _column(image) == {EDGE_Y: (*MAGENTA, 255)}


def test_a_solid_fill_covers_the_inner_half_of_the_glow(series):
    image, _ = _render(series, [(True, ("solid", "always"), True, SQUARE)])
    column = _column(image)
    outside = [column[y][3] for y in column if y < EDGE_Y]
    inside = [column[y][3] for y in column if y > EDGE_Y]
    assert outside and set(outside) == {round(0.4 * 255)}, column
    assert inside and set(inside) == {255}, column


# --------------------------------------------------------------------------
# open ends, painter state between traces, and fills
# --------------------------------------------------------------------------

@pytest.mark.parametrize("closed", [True, False], ids=["closed", "open"])
def test_a_selected_open_trace_is_not_closed_by_the_glow(series, closed):
    image, _ = _render(series, [(True, ("none", "none"), closed, SQUARE)])
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
    image, _ = _render(series, [first, plain] if plain_last else [plain, first])

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
    image, _ = _render(series, [(selected, ("solid", condition), True, SQUARE)])
    c = image.pixelColor(*INSIDE)
    assert _drawn(image, *INSIDE) == filled
    if filled:
        assert (c.red(), c.green(), c.blue(), c.alpha()) == (*MAGENTA, 255)


def test_a_transparent_fill_is_drawn_at_the_fill_opacity(series):
    fill_opacity = series.getOption("fill_opacity")
    assert 0 < fill_opacity < 1, "the test needs a partly transparent fill"
    image, _ = _render(series, [(True, ("transparent", "always"), True, SQUARE)])
    c = image.pixelColor(*INSIDE)
    assert (c.red(), c.green(), c.blue()) == pytest.approx(MAGENTA, abs=2)
    assert c.alpha() == pytest.approx(fill_opacity * 255, abs=2)
