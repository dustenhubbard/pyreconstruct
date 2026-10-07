"""Merging a sliver thinner than a grid cell must not drop its area.

A rectangle 100 by 10 cells and a triangle 50 cells long hanging off it, at
most one cell wide. On the merge grid the two long sides of the triangle are
one cell apart, so the outline traced around them is a band one pixel thick.
`reducePoints` (cv2.approxPolyDP, epsilon 0.8 cells) then closes that band
into a spike with no area. The merge used to return the spike, keeping about
0.01 of the triangle's 25, and the caller deleted both originals.

The merge now refuses when the outline would keep less than half of any
trace, so the caller keeps both traces and says the merge would lose area. It
does not say the trace left no outline, since one exists. The same shapes on a
finer grid still merge and keep the triangle.
"""
import pytest
import shapely
from shapely.geometry import LineString, Polygon

from PyReconstruct.modules.calc.grid import (
    Grid,
    mergeCellSize,
    mergeTracesInField,
    reducePoints,
)

NAME = "merge_thin_sliver"

RECT = [(0, 0), (100, 0), (100, 10), (0, 10)]
SLIVER = [(5, 0), (55, -50), (56, -50)]
# 4 field units per image pixel, so one cell is one field unit
MAG = 4

# A ribbon several image pixels wide is still thinner than a cell once a long
# trace coarsens the grid: the rectangle spans 2500 cells at mag 0.1, so a cell
# is 10 image pixels and the ribbon, 7.8 pixels across, closes up the same way.
WIDE_RECT = [(0, 0), (2500, 0), (2500, 10), (0, 10)]
RIBBON = [(5, 0), (55, -50), (56.1, -50), (6.1, 0)]
WIDE_MAG = 0.1


def _kept(trace, outlines):
    """Share of trace's area the outlines cover."""
    shape = Polygon(trace)
    covered = shapely.union_all([Polygon(o).buffer(0) for o in outlines if len(o) >= 3])
    return shape.intersection(covered).area / shape.area


def test_the_grid_outline_keeps_the_sliver_until_it_is_simplified():
    """The premise, at the grid the merge uses: the traced outline still
    covers most of the sliver, and the simplified one covers almost none."""
    assert mergeCellSize([RECT, SLIVER], MAG) == 1
    assert Polygon(SLIVER).area == 25
    (outline,) = Grid([RECT, SLIVER]).getExterior()
    assert _kept(SLIVER, [outline]) > 0.7
    assert _kept(SLIVER, [reducePoints(outline)]) < 0.01


def test_merge_refuses_when_a_sliver_would_lose_most_of_its_area():
    from PyReconstruct.modules.calc.grid import MergeLosesArea

    with pytest.raises(MergeLosesArea):
        mergeTracesInField([RECT, SLIVER], MAG)


def test_the_refusal_names_the_cell_size_of_the_grid_that_lost_the_area():
    from PyReconstruct.modules.calc.grid import MergeLosesArea

    with pytest.raises(MergeLosesArea) as fine:
        mergeTracesInField([RECT, SLIVER], MAG)
    assert fine.value.pixels == pytest.approx(0.25)
    assert not fine.value.coarse

    # width across the ribbon, in image pixels: area over its long side
    long_side = LineString(RIBBON[:2]).length
    assert Polygon(RIBBON).area / long_side / WIDE_MAG == pytest.approx(7.78, abs=0.01)
    with pytest.raises(MergeLosesArea) as coarse:
        mergeTracesInField([WIDE_RECT, RIBBON], WIDE_MAG)
    assert coarse.value.pixels == pytest.approx(10)
    assert coarse.value.coarse


@pytest.mark.parametrize("mag", [2, 0.4])
def test_the_same_sliver_merges_on_a_finer_grid(mag):
    merged = mergeTracesInField([RECT, SLIVER], mag)
    assert len(merged) == 1
    assert _kept(SLIVER, merged) > 0.95
    assert _kept(RECT, merged) > 0.99


@pytest.mark.gui
@pytest.mark.parametrize(
    "rect, sliver, cell_pixels, says",
    [
        (RECT, SLIVER, 0.25, "A cell is a quarter of an image pixel."),
        (WIDE_RECT, RIBBON, 10, "so here it is 10 image pixels."),
    ],
    ids=["sub-pixel", "coarse-grid"],
)
def test_merge_keeps_both_traces_when_a_sliver_would_lose_its_area(
    main_window, monkeypatch, rect, sliver, cell_pixels, says
):
    from PyReconstruct.modules.datatypes.trace import Trace
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    notices = []
    monkeypatch.setattr(fw2, "notify", lambda msg, *a, **k: notices.append(msg))

    field = main_window.field
    section = field.section
    cell = section.mag * cell_pixels
    wx, wy, ww, wh = main_window.series.window
    # on the cell grid, so the traces round to the same cells as rect and sliver
    x0 = round((wx + ww * 0.1) / cell)
    y0 = round((wy + wh * 0.5) / cell)
    traces = [
        [((x0 + x) * cell, (y0 + y) * cell) for x, y in t] for t in (rect, sliver)
    ]
    assert mergeCellSize(traces, section.mag) == pytest.approx(cell)

    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    for pts in traces:
        field.newTrace(pts, field.tracing_trace, points_as_pix=False,
                       reduce_points=False, log_event=False)
    field.saveState()
    section.selected_traces = list(section.contours[NAME])
    before = sorted(tuple(map(tuple, t.points)) for t in section.contours[NAME])
    assert len(before) == 2

    field.mergeTraces()

    after = sorted(tuple(map(tuple, t.points)) for t in section.contours[NAME])
    assert after == before
    assert len(notices) == 1, notices
    assert "lose most of the area" in notices[0], notices
    assert "thinner than a cell of the grid the merge uses" in notices[0], notices
    assert says in notices[0], notices
    # the coarse grid refuses a trace several image pixels wide, so the
    # message must not put the limit at an image pixel
    assert "thinner than an image pixel" not in notices[0], notices
    # an outline exists, and a thin trace is not a speck to delete
    assert "no outline" not in notices[0], notices
    assert "delete" not in notices[0], notices
