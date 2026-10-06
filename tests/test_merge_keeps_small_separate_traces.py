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

from PyReconstruct.modules.calc.grid import (
    mergeCellSize,
    mergeGroups,
    mergeTracesInField,
)

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


# ---------------------------------------------------------------------------
# the real field
# ---------------------------------------------------------------------------


def _draw_pair(main_window, small_side_px):
    """A long trace and a small separate one, both of NAME, both selected.

    The small one sits centered on a point of the grid the old shared merge
    used, so at that grid its corners all round to one point. Returns the
    section and the points of both traces as stored.
    """
    from PyReconstruct.modules.datatypes.trace import Trace

    field = main_window.field
    section = field.section
    mag = section.mag
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

    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    for pts in (long_trace, small_trace):
        field.newTrace(pts, field.tracing_trace, points_as_pix=False,
                       reduce_points=False, log_event=False)
    assert len(section.contours[NAME]) == 2
    field.saveState()  # the drawing is one undo step, the merge the next
    section.selected_traces = list(section.contours[NAME])
    stored = sorted(tuple(map(tuple, t.points)) for t in section.contours[NAME])
    return field, section, stored


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
