"""Merging a long trace with a small separate one keeps both.

The merge grid is tied to the image (fork #467), but it is capped at
`MERGE_MAX_CELLS` cells per axis. One grid sized to the whole selection let a
long trace coarsen the cells until a small separate trace, a few image pixels
across, rounded onto one grid point and vanished. The merge then deleted both
originals and created only the long one, and Save kept the loss.

Traces that do not touch are now merged apart, each group on its own grid, and
a group that still leaves no outline makes the merge refuse before it deletes
anything.
"""
import pytest

from PyReconstruct.modules.calc.grid import mergeCellSize, mergeTracesInField

NAME = "merge_small_part"


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _bounds(points):
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

# 0.00025 field units per image pixel: the long trace is 4000 pixels wide and
# the small one 4 pixels, 40000 pixels away
MAG = 0.00025
LONG = _rect(0.0, 0.0, 1.0, 0.01)
SMALL = _rect(10.001, 0.001, 10.002, 0.002)


def test_one_shared_grid_is_too_coarse_for_the_small_trace():
    """The premise: sized to both traces, a cell is wider than the small one."""
    shared = mergeCellSize([LONG, SMALL], MAG)
    assert shared > 0.001  # the small trace's width


def test_separate_traces_are_merged_as_separate_groups():
    from PyReconstruct.modules.calc.grid import mergeGroups

    assert mergeGroups([LONG, SMALL]) == [[0], [1]]
    overlapping = _rect(0.5, 0.005, 1.5, 0.02)
    assert mergeGroups([LONG, SMALL, overlapping]) == [[0, 2], [1]]
    inside = _rect(0.1, 0.002, 0.2, 0.008)
    assert mergeGroups([LONG, inside]) == [[0, 1]]


def test_small_separate_trace_survives_the_merge():
    merged = mergeTracesInField([LONG, SMALL], MAG)
    assert len(merged) == 2
    cell = MAG / 4
    by_x = sorted(merged, key=lambda t: _bounds(t)[0])
    assert _bounds(by_x[0]) == pytest.approx(_bounds(LONG), abs=2 * 0.0004)
    assert _bounds(by_x[1]) == pytest.approx(_bounds(SMALL), abs=2 * cell)


def test_a_group_with_no_outline_empties_the_whole_result():
    """A speck under a quarter pixel cannot be drawn on any merge grid. The
    result is empty rather than missing it, so the caller keeps everything."""
    speck = _rect(10.0, 0.0, 10.0 + MAG / 20, MAG / 20)
    assert mergeTracesInField([LONG, speck], MAG) == []


def _area(points):
    from shapely.geometry import Polygon
    return Polygon(points).area


def test_traces_touching_at_an_edge_or_corner_are_one_group():
    from PyReconstruct.modules.calc.grid import mergeGroups

    a = _rect(0.0, 0.0, 1.0, 1.0)
    edge = _rect(1.0, 0.0, 2.0, 1.0)
    corner = _rect(1.0, 1.0, 2.0, 2.0)
    assert mergeGroups([a, edge]) == [[0, 1]]
    assert mergeGroups([a, corner]) == [[0, 1]]
    assert len(mergeTracesInField([a, edge], 0.01)) == 1


def test_a_chain_of_overlaps_is_one_group():
    """A overlaps B and B overlaps C, while A and C are apart."""
    from PyReconstruct.modules.calc.grid import mergeGroups

    a = _rect(0.0, 0.0, 1.0, 1.0)
    b = _rect(0.9, 0.0, 2.1, 1.0)
    c = _rect(2.0, 0.0, 3.0, 1.0)
    assert mergeGroups([a, c, b]) == [[0, 1, 2]]
    merged = mergeTracesInField([a, c, b], 0.01)
    assert len(merged) == 1
    assert _area(merged[0]) == pytest.approx(3.0, rel=0.01)


def test_a_self_crossing_trace_groups_with_what_it_overlaps():
    from PyReconstruct.modules.calc.grid import mergeGroups

    bowtie = [(0.0, 0.0), (1.0, 1.0), (1.0, 0.0), (0.0, 1.0)]
    beside = _rect(0.9, 0.4, 2.0, 0.6)
    apart = _rect(5.0, 5.0, 6.0, 6.0)
    assert mergeGroups([bowtie, beside, apart]) == [[0, 1], [2]]
    assert mergeTracesInField([bowtie, beside, apart], 0.01)


def test_a_trace_in_a_hole_merges_into_the_ring():
    """The grid keeps only outer outlines, so the grouping fills holes too.
    Grouped apart, the inner trace came back on top of the ring and the two
    areas summed to 17 instead of 16."""
    from PyReconstruct.modules.calc.grid import mergeGroups

    ring = [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0),
            (1, 1), (1, 3), (3, 3), (3, 1), (1, 1), (0, 0)]
    inner = _rect(1.5, 1.5, 2.5, 2.5)
    assert mergeGroups([ring, inner]) == [[0, 1]]
    merged = mergeTracesInField([ring, inner], 0.01)
    assert len(merged) == 1
    assert _area(merged[0]) == pytest.approx(16.0, rel=0.01)


def test_traces_closer_than_a_cell_stay_apart():
    """Two traces a hundredth of a pixel apart do not touch, so they are
    merged apart and stay two traces. One shared grid used to join them."""
    a = _rect(0.0, 0.0, 1.0, 1.0)
    b = _rect(1.001, 0.0, 2.0, 1.0)
    assert len(mergeTracesInField([a, b], 0.1)) == 2


# the long trace is 40000 pixels wide; a cell on its grid is 16 pixels
TOUCH_MAG = 0.000025
TOUCH_LONG = _rect(0.0, 0.0, 1.0, 0.01)


def test_a_small_trace_touching_a_long_one_empties_the_result():
    """The small trace hangs below the long one and rounds onto one grid
    point. Merging would drop its area, so the result is empty and the
    caller keeps both."""
    below = _rect(0.0048, -0.0001, 0.00488, 0.0)
    from PyReconstruct.modules.calc.grid import mergeGroups

    assert mergeGroups([TOUCH_LONG, below]) == [[0, 1]]
    assert mergeTracesInField([TOUCH_LONG, below], TOUCH_MAG) == []


@pytest.mark.parametrize("offset", [0.0, 1e-12], ids=["duplicate", "near_duplicate"])
def test_two_vanishing_traces_cannot_cover_each_other(offset):
    """Two copies of the small trace both round onto one point. Each covers
    the other, but neither survives, so the result is still empty."""
    below = _rect(0.0048, -0.0001, 0.00488, 0.0)
    again = [(x + offset, y) for x, y in below]
    assert mergeTracesInField([TOUCH_LONG, below, again], TOUCH_MAG) == []


def test_a_small_trace_inside_a_long_one_still_merges():
    """Rounding a trace away is safe when another trace covers its area."""
    inside = _rect(0.0048, 0.001, 0.00488, 0.0011)
    merged = mergeTracesInField([TOUCH_LONG, inside], TOUCH_MAG)
    assert len(merged) == 1
    assert _bounds(merged[0]) == pytest.approx(_bounds(TOUCH_LONG), abs=0.0004)


# ---------------------------------------------------------------------------
# the real field
# ---------------------------------------------------------------------------


def _draw(main_window, traces, negative=False):
    """Draw the traces as NAME, select them all, save an undo state, and
    return the field, the section and the stored points."""
    from PyReconstruct.modules.datatypes.trace import Trace

    field = main_window.field
    section = field.section
    base = Trace(NAME, (0, 255, 0), True)
    base.negative = negative
    field.setTracingTrace(base)
    for pts in traces:
        field.newTrace(pts, field.tracing_trace, points_as_pix=False,
                       reduce_points=False, log_event=False)
    assert len(section.contours[NAME]) == len(traces)
    field.saveState()  # the drawing is one undo step, the merge the next
    section.selected_traces = list(section.contours[NAME])
    return field, section, _stored(section)


def _draw_pair(main_window, small_side_px):
    """A long trace and a small separate one, both of NAME, both selected.

    The small one sits centered on a point of the grid the old shared merge
    used, so at that grid its corners all round to one point. Returns the
    section and the points of both traces as stored.
    """
    mag = main_window.field.section.mag
    wx, wy, ww, wh = main_window.series.window
    x0, y0 = wx + ww * 0.1, wy + wh * 0.5

    long_trace = _rect(x0, y0, x0 + 4000 * mag, y0 + 40 * mag)
    # the shared grid's span is about 40000 pixels: 16 pixels a cell
    probe = _rect(x0 + 40000 * mag, y0, x0 + 40000 * mag + mag, y0 + mag)
    cell = mergeCellSize([long_trace, probe], mag)
    cx = round((x0 + 40000 * mag) / cell) * cell
    cy = round((y0 + 10 * mag) / cell) * cell
    half = small_side_px * mag / 2
    small_trace = _rect(cx - half, cy - half, cx + half, cy + half)
    # the premise: on the one grid sized to both traces, every corner of the
    # small trace rounds onto the same point
    shared = mergeCellSize([long_trace, small_trace], mag)
    assert len({(round(x / shared), round(y / shared)) for x, y in small_trace}) == 1

    return _draw(main_window, [long_trace, small_trace])


def _stored(section):
    return sorted(tuple(map(tuple, t.points)) for t in section.contours[NAME])


@pytest.mark.gui
def test_merge_keeps_the_small_trace_and_undo_restores(main_window, monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    notices = []
    monkeypatch.setattr(fw2, "notify", lambda msg, *a, **k: notices.append(msg))

    field, section, before = _draw_pair(main_window, small_side_px=4)
    small_before = min(before, key=lambda t: _bounds(t)[2] - _bounds(t)[0])

    field.mergeTraces()
    after = _stored(section)
    assert len(after) == 2, "the small separate trace was lost in the merge"
    assert after != before  # both were redrawn on the merge grid
    assert not notices, notices
    small_after = min(after, key=lambda t: _bounds(t)[2] - _bounds(t)[0])
    cell = section.mag / 4
    assert _bounds(small_after) == pytest.approx(_bounds(small_before), abs=2 * cell)

    field.undoState()
    assert _stored(field.section) == before


@pytest.mark.gui
def test_merge_refuses_when_a_trace_would_vanish(main_window, monkeypatch):
    """A speck below a quarter pixel leaves no outline on any grid: the merge
    keeps both traces exactly as they were and says why."""
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    notices = []
    monkeypatch.setattr(fw2, "notify", lambda msg, *a, **k: notices.append(msg))

    field, section, before = _draw_pair(main_window, small_side_px=0.1)

    field.mergeTraces()
    assert _stored(section) == before
    assert any("no outline" in m for m in notices), notices


@pytest.mark.gui
def test_merge_refuses_when_a_touching_trace_would_vanish(main_window, monkeypatch):
    """A small trace hanging below a long one rounds onto one point of the
    long one's grid. The merge keeps both traces and says why."""
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    notices = []
    monkeypatch.setattr(fw2, "notify", lambda msg, *a, **k: notices.append(msg))

    mag = main_window.field.section.mag
    wx, wy, ww, wh = main_window.series.window
    probe = _rect(wx, wy, wx + 40000 * mag, wy + 400 * mag)
    cell = mergeCellSize([probe], mag)
    x0 = round((wx + ww * 0.1) / cell) * cell
    y0 = round((wy + wh * 0.5) / cell) * cell
    long_trace = _rect(x0, y0, x0 + 40000 * mag, y0 + 400 * mag)
    cx = x0 + 12 * cell
    below = _rect(cx - 1.6 * mag, y0 - 4 * mag, cx + 1.6 * mag, y0)
    # the premise: on the long trace's grid the small one is a single point
    shared = mergeCellSize([long_trace, below], mag)
    assert len({(round(x / shared), round(y / shared)) for x, y in below}) == 1

    field, section, before = _draw(main_window, [long_trace, below])
    field.mergeTraces()
    assert _stored(section) == before
    assert any("no outline" in m for m in notices), notices


def _long_and_straddling_speck(main_window):
    """A long trace on the field and a 3 by 4 pixel speck straddling its
    bottom edge, placed so the speck rounds onto one point of the long
    trace's grid. Field units."""
    mag = main_window.field.section.mag
    wx, wy, ww, wh = main_window.series.window
    probe = _rect(wx, wy, wx + 40000 * mag, wy + 400 * mag)
    cell = mergeCellSize([probe], mag)
    x0 = round((wx + ww * 0.1) / cell) * cell
    y0 = round((wy + wh * 0.5) / cell) * cell
    long_trace = _rect(x0, y0, x0 + 40000 * mag, y0 + 400 * mag)
    cx = x0 + 12 * cell
    speck = _rect(cx - 1.6 * mag, y0 - 2 * mag, cx + 1.6 * mag, y0 + 2 * mag)
    shared = mergeCellSize([long_trace, speck], mag)
    assert len({(round(x / shared), round(y / shared)) for x, y in speck}) == 1
    return long_trace, speck


@pytest.mark.gui
@pytest.mark.parametrize(
    "offset_px, negative",
    [(0.0, False), (1e-7, False), (0.0, True)],
    ids=["duplicate", "near_duplicate", "negative_duplicate"],
)
def test_merge_refuses_two_vanishing_copies(main_window, monkeypatch, offset_px, negative):
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    notices = []
    monkeypatch.setattr(fw2, "notify", lambda msg, *a, **k: notices.append(msg))

    long_trace, speck = _long_and_straddling_speck(main_window)
    offset = offset_px * main_window.field.section.mag
    again = [(x + offset, y) for x, y in speck]

    field, section, before = _draw(main_window, [long_trace, speck, again], negative)
    field.mergeTraces()
    assert _stored(section) == before
    assert any("no outline" in m for m in notices), notices


@pytest.mark.gui
def test_auto_merge_refuses_a_drawn_copy_of_a_vanishing_trace(main_window, monkeypatch):
    """Drawing a copy of the speck auto-merges it with the speck and the long
    trace. Neither speck survives that grid, so the merge refuses and the
    field keeps all three traces."""
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    notices = []
    monkeypatch.setattr(fw2, "notify", lambda msg, *a, **k: notices.append(msg))
    main_window.series.setOption("auto_merge", True)
    main_window.series.setOption("auto_merge_selected_only", False)

    long_trace, speck = _long_and_straddling_speck(main_window)
    field, section, _ = _draw(main_window, [long_trace, speck])
    section.selected_traces = []

    field.newTrace(speck, field.tracing_trace, points_as_pix=False,
                   reduce_points=False, log_event=False)
    drawn = _stored(section)
    assert len(drawn) == 3
    field.autoMerge()

    assert _stored(section) == drawn
    assert any("no outline" in m for m in notices), notices
