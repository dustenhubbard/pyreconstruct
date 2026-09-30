"""A selected trace is drawn with a black and white outline (issue #438).

The old highlight was a wider stroke in the trace's own color at 40% opacity,
which disappears for a light trace on a light image or a dark trace on a dark
one. The outline has a black edge and a white band on either side of the trace
line, so one of the two contrasts with whatever is underneath, and the trace's
own color stays down the middle.

These render a real section headlessly and read the pixels across the top edge
of an axis-aligned square trace.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

W, H = 400, 400
PPU = 100.0                      # pixels per field unit
MAGENTA = (255, 0, 255)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
EDGE_Y = 100                     # pixel row of the square's top edge
COLUMN_X = 300                   # a pixel column crossing that edge


@pytest.fixture
def series():
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    s = Series.openJser(FIXTURE)
    yield s
    s.close()


def _column(series, selected, fill_mode=("none", "none")):
    """Render one magenta square and return the opaque RGB pixels across its top edge.

    Returns a dict of pixel row -> (r, g, b) for rows near the edge; rows
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
    trace = Trace("outline_probe", MAGENTA, closed=True)
    trace.points = [
        tuple(p) for p in section.tform.mapPointsArray(corners, inverted=True).tolist()
    ]
    trace.fill_mode = fill_mode
    section.addTrace(trace, log_event=False)
    if selected:
        section.addSelectedTrace(trace)

    layer = SectionLayer(section, series, load_image_layer=False)
    image = layer.generateTraceLayer((W, H), window, window_moved=True).toImage()

    column = {}
    for y in range(EDGE_Y - 8, EDGE_Y + 9):
        c = image.pixelColor(COLUMN_X, y)
        if c.alpha() == 255:
            column[y] = (c.red(), c.green(), c.blue())
    return column


def test_selected_trace_has_black_and_white_outline(series):
    column = _column(series, selected=True)
    colors = set(column.values())
    assert BLACK in colors, f"no black edge across the selected trace: {column}"
    assert WHITE in colors, f"no white band across the selected trace: {column}"
    # the trace keeps its own color down the middle of the outline
    assert column.get(EDGE_Y) == MAGENTA, column


def test_unselected_trace_has_no_outline(series):
    column = _column(series, selected=False)
    assert set(column.values()) == {MAGENTA}, column


def test_outline_is_drawn_over_a_solid_fill(series):
    column = _column(series, selected=True, fill_mode=("solid", "always"))
    inside = {column.get(y) for y in range(EDGE_Y + 1, EDGE_Y + 5)}
    assert WHITE in inside, f"the fill covered the inner side of the outline: {column}"
