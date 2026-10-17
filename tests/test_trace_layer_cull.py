"""The trace draw skips traces whose bounds miss the window before mapping their points.

The skip must change nothing on screen: the same pixels, and the same
traces_in_view (which picking and lasso selection read), under rotation and
shear, for traces that cross the window edge, and after an edit or an undo
that moves a trace without replacing it.
"""

import math
import random

import pytest

from PyReconstruct.modules.backend.view.trace_layer import TraceLayer
from PyReconstruct.modules.datatypes import Trace, Transform


pytestmark = pytest.mark.gui

DIM = (400, 300)
NAME = "cull-render"


def _pixels(pixmap):
    image = pixmap.toImage()
    return bytes(image.constBits())


def _rotate_shear(angle, shear, dx, dy):
    c, s = math.cos(angle), math.sin(angle)
    # Transform takes [a, b, c, d, e, f]: x' = a x + b y + c, y' = d x + e y + f
    return Transform([c, -s + shear, dx, s, c, dy])


@pytest.fixture
def layer(qapp, real_series):
    section = real_series.loadSection(min(real_series.sections))
    real_series.setOption("show_ztraces", False)
    real_series.setOption("show_flags", "none")
    rng = random.Random(255)
    for i in range(300):
        trace = Trace(NAME, (rng.randrange(256), 100, 200), i % 4 != 0)
        x, y = rng.uniform(-40, 40), rng.uniform(-40, 40)
        r = rng.uniform(0.05, 3)
        trace.points = [
            (x + r * math.cos(t), y + r * math.sin(t))
            for t in (k * 2 * math.pi / 7 for k in range(7))
        ]
        trace.fill_mode = ("transparent", "always") if i % 3 == 0 else ("none", "none")
        section.addTrace(trace, log_event=False)
    # long thin traces whose points all lie outside the windows below but
    # whose lines cross them
    for x0, y0, x1, y1 in ((-60, 0.3, 60, 0.4), (0.2, -60, 0.25, 60)):
        trace = Trace(NAME, (255, 0, 0), False)
        trace.points = [(x0, y0), (x1, y1)]
        section.addTrace(trace, log_event=False)
    section.clearTracking()
    return TraceLayer(section, real_series)


def _draw(layer, window, cull=True, **kwargs):
    if not cull:
        # an instance attribute shadows the method; deleting it restores it
        layer._cullMask = lambda *a: None
    try:
        pixels = _pixels(layer.generateTraceLayer(DIM, list(window), **kwargs))
    finally:
        if not cull:
            del layer._cullMask
    return pixels, list(layer.traces_in_view)


WINDOWS = {
    "whole": (-50, -40, 100, 75),
    "quarter": (-6, -4, 12, 9),
    "close": (-1, -0.5, 2, 1.5),
    "edge": (2.7, 1.1, 0.8, 0.6),
}
TFORMS = {
    "identity": Transform.identity(),
    "rotate": _rotate_shear(0.6, 0, 1.5, -2),
    "shear": _rotate_shear(-1.1, 0.4, -3, 0.5),
    "flip": Transform([-1, 0, 0.2, 0, 1.3, 0]),
}


@pytest.mark.parametrize("tform", TFORMS)
@pytest.mark.parametrize("window", WINDOWS)
def test_cull_draws_the_same_frame(layer, window, tform):
    section = layer.section
    section.tforms[layer.series.alignment] = TFORMS[tform]
    expected = _draw(layer, WINDOWS[window], cull=False)
    calls = 0
    real = layer.traceToPixArray

    def counting(*a, **k):
        nonlocal calls
        calls += 1
        return real(*a, **k)

    layer.traceToPixArray = counting
    actual = _draw(layer, WINDOWS[window])
    assert actual[0] == expected[0]
    assert actual[1] == expected[1]
    if window != "whole":
        # the point of the change: traces off the window are never mapped
        assert calls < len(section.tracesAsList()) / 2


def test_crossing_traces_are_kept(layer):
    section = layer.section
    section.tforms[layer.series.alignment] = Transform.identity()
    _, in_view = _draw(layer, WINDOWS["close"])
    crossing = [t for t in section.tracesAsList() if len(t.points) == 2]
    assert all(t in in_view for t in crossing)


def test_points_moved_in_place_are_drawn_where_they_went(layer):
    """translateTraces rewrites a trace's points list in place: same trace,
    same list, same length. The cached bounds must not survive it."""
    section = layer.section
    section.tforms[layer.series.alignment] = Transform.identity()
    window = WINDOWS["close"]
    _draw(layer, window)
    outside = next(
        t for t in section.tracesAsList()
        if t not in layer.traces_in_view and len(t.points) == 7
    )
    points = outside.points
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    section.selected_traces = [outside]
    section.translateTraces(-cx, -cy, log_event=False)
    section.selected_traces = []
    assert outside.points is points

    actual = _draw(layer, window, window_moved=True)
    assert outside in actual[1]
    assert actual == _draw(layer, window, cull=False)


def test_the_boxes_are_read_from_the_store(layer):
    """The boxes come from the section's columnar store rows, so a new
    section does not convert every trace's points again."""
    section = layer.section
    section.tforms[layer.series.alignment] = Transform.identity()
    window = WINDOWS["quarter"]
    _, in_view = _draw(layer, window)
    trace = next(t for t in in_view if len(t.points) == 7)
    # move only the trace's row off the window, at the same point count
    section._columns.setCoordinates(
        section.traceRows()[trace], [(x + 1000, y) for x, y in trace.points]
    )
    _, in_view = _draw(layer, window)
    assert trace not in in_view


def test_a_row_with_another_point_count_is_not_used(layer):
    """A trace whose points no longer match its row in length is tested on
    its own points."""
    section = layer.section
    section.tforms[layer.series.alignment] = Transform.identity()
    window = WINDOWS["close"]
    _draw(layer, window)
    outside = next(
        t for t in section.tracesAsList()
        if t not in layer.traces_in_view and len(t.points) == 7
    )
    outside.points = [(0.1 * math.cos(k), 0.1 * math.sin(k)) for k in range(8)]
    actual = _draw(layer, window)
    assert outside in actual[1]
    assert actual == _draw(layer, window, cull=False)


def test_a_trace_with_no_row_is_tested_on_its_own_points(layer):
    _draw(layer, WINDOWS["close"])
    inside = Trace(NAME, (0, 0, 0), True)
    inside.points = [(0, 0), (0.1, 0), (0.1, 0.1)]
    outside = Trace(NAME, (0, 0, 0), True)
    outside.points = [(30, 30), (31, 30), (31, 31)]
    empty = Trace(NAME, (0, 0, 0), True)
    mask = layer._cullMask([inside, outside, empty], Transform.identity())
    assert list(mask) == [True, False, True]


def test_a_magnification_change_moves_the_boxes(layer):
    """setMag rewrites every trace's points in place; the boxes follow."""
    section = layer.section
    section.tforms[layer.series.alignment] = Transform.identity()
    window = WINDOWS["quarter"]
    before = _draw(layer, window)
    section.setMag(section.mag / 4)
    actual = _draw(layer, window)
    assert set(actual[1]) - set(before[1])
    assert actual == _draw(layer, window, cull=False)


def test_redo_of_a_move_takes_the_trace_off_again(main_window):
    field = main_window.field
    series = main_window.series
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * 0.4, wy + wh * 0.4
    item = Trace("cull-redo", (0, 255, 0), True)
    field.setTracingTrace(item)
    field.newTrace(
        [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)],
        field.tracing_trace, points_as_pix=False, reduce_points=False,
    )
    field.generateView()
    drawn = next(t for t in field.section_layer.traces_in_view if t.name == "cull-redo")
    field.section.selected_traces = [drawn]
    field.translate(ww * 10, 0)

    def names():
        field.generateView()
        return [t.name for t in field.section_layer.traces_in_view]

    main_window.undo()
    assert "cull-redo" in names()
    main_window.undo(redo=True)
    assert "cull-redo" not in names()
    main_window.undo()
    assert "cull-redo" in names()


def test_undo_of_a_move_draws_the_trace_back(main_window):
    """Move a drawn trace off the window and undo: it is drawn again."""
    field = main_window.field
    series = main_window.series
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * 0.4, wy + wh * 0.4
    item = Trace("cull-undo", (0, 255, 0), True)
    field.setTracingTrace(item)
    field.newTrace(
        [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)],
        field.tracing_trace, points_as_pix=False, reduce_points=False,
    )
    field.generateView()
    layer = field.section_layer
    drawn = next(t for t in layer.traces_in_view if t.name == "cull-undo")

    field.section.selected_traces = [drawn]
    field.translate(ww * 10, 0)
    assert drawn not in field.section_layer.traces_in_view

    main_window.undo()
    field.generateView()
    names = [t.name for t in field.section_layer.traces_in_view]
    assert "cull-undo" in names
    culled = _pixels(field.section_layer.trace_layer)
    layer = field.section_layer
    layer._cullMask = lambda *a: None
    try:
        field.generateView()
        assert _pixels(layer.trace_layer) == culled
    finally:
        del layer._cullMask
