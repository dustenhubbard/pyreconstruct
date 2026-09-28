"""Merging traces gives the same result at any zoom (fork issue #423).

Merge used to draw the traces on the screen's pixel grid, fill them, and read
the outline back, so a merge while zoomed in kept more detail than the same
merge while zoomed out. The grid is now tied to the image: a fixed number of
cells per image pixel, coarser only for traces that span more cells than a
cap, and never a function of the view.

The first tests are pure geometry on `calc.grid`. The last drives the real
`FieldWidget.mergeTraces` on a live window at two zooms and compares the stored
points.
"""
import pytest

from PyReconstruct.modules.calc.grid import (
    MERGE_MAX_CELLS,
    MERGE_SUPERSAMPLE,
    mergeCellSize,
    mergeTracesInField,
)

MAG = 0.002   # a typical section magnification, field units per image pixel

# two overlapping squares, field units, 100 and 100 image pixels wide
SQ_A = [(1.0, 1.0), (1.2, 1.0), (1.2, 1.2), (1.0, 1.2)]
SQ_B = [(1.1, 1.1), (1.3, 1.1), (1.3, 1.3), (1.1, 1.3)]


def _bounds(points):
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def test_cell_is_a_fraction_of_an_image_pixel():
    assert mergeCellSize([SQ_A, SQ_B], MAG) == pytest.approx(MAG / MERGE_SUPERSAMPLE)


def test_cell_grows_only_for_traces_wider_than_the_cap():
    huge = [(0.0, 0.0), (MAG * MERGE_MAX_CELLS, 0.0), (MAG * MERGE_MAX_CELLS, 1.0), (0.0, 1.0)]
    cell = mergeCellSize([huge], MAG)
    assert cell > MAG / MERGE_SUPERSAMPLE
    span = MAG * MERGE_MAX_CELLS
    assert span / cell <= MERGE_MAX_CELLS + 1e-9


def test_two_overlapping_squares_merge_into_one_union():
    merged = mergeTracesInField([SQ_A, SQ_B], MAG)
    assert len(merged) == 1
    cell = mergeCellSize([SQ_A, SQ_B], MAG)
    xmin, ymin, xmax, ymax = _bounds(merged[0])
    assert (xmin, ymin) == pytest.approx((1.0, 1.0), abs=2 * cell)
    assert (xmax, ymax) == pytest.approx((1.3, 1.3), abs=2 * cell)
    # the union of two offset squares is an L-shaped outline with 8 corners
    assert 6 <= len(merged[0]) <= 12, merged[0]


def test_disjoint_squares_stay_two_traces():
    far = [(x + 5.0, y + 5.0) for x, y in SQ_B]
    merged = mergeTracesInField([SQ_A, far], MAG)
    assert len(merged) == 2


def test_result_does_not_depend_on_where_the_traces_sit():
    """A shift by a whole number of cells shifts the answer and nothing else."""
    cell = mergeCellSize([SQ_A, SQ_B], MAG)
    shift = 40 * cell
    base = mergeTracesInField([SQ_A, SQ_B], MAG)
    moved = mergeTracesInField(
        [[(x + shift, y) for x, y in SQ_A], [(x + shift, y) for x, y in SQ_B]], MAG
    )
    assert len(base) == len(moved) == 1
    back = {(round(x - shift, 9), round(y, 9)) for x, y in moved[0]}
    assert back == {(round(x, 9), round(y, 9)) for x, y in base[0]}


# ---------------------------------------------------------------------------
# the real field, two zooms
# ---------------------------------------------------------------------------

@pytest.mark.gui
def test_field_merge_gives_identical_points_at_two_zooms(main_window):
    from PyReconstruct.modules.datatypes.trace import Trace

    field = main_window.field
    series = main_window.series
    section = field.section
    name = "zoom_merge_obj"

    # field-space squares inside the current view
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.2
    x0, y0 = wx + ww * 0.3, wy + wh * 0.3
    sq_a = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    sq_b = [(x + side / 2, y + side / 2) for x, y in sq_a]

    def merge_at(window):
        series.window = list(window)
        field.generateView()
        base = Trace(name, (0, 255, 0), True)
        field.setTracingTrace(base)
        section.selected_traces = []
        # reduce_points=False: newTrace's reduction runs on a pixel grid and
        # is not meant for field-unit input
        for sq in (sq_a, sq_b):
            field.newTrace(
                sq, field.tracing_trace,
                points_as_pix=False, reduce_points=False, log_event=False,
            )
        traces = list(section.contours[name])
        assert len(traces) == 2
        section.selected_traces = traces
        field.mergeTraces()
        merged = list(section.contours[name])
        assert len(merged) == 1, "two overlapping squares must merge into one"
        pts = [tuple(p) for p in merged[0].points]
        section.deleteTraces(merged, log_event=False)
        return pts

    zoomed_in = merge_at((wx, wy, ww, wh))
    zoomed_out = merge_at((wx - ww * 1.5, wy - wh * 1.5, ww * 4, wh * 4))
    series.window = [wx, wy, ww, wh]

    assert [pytest.approx(p, abs=1e-9) for p in zoomed_out] == zoomed_in, (
        "the merged outline changed with the zoom"
    )
    assert len(zoomed_in) >= 6
