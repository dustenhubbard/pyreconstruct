"""The trace draw converts every trace to screen points in one pass.

The pass must change nothing on screen: the same pixels as converting each
trace on its own, with fills, transparency, every selected style, hidden
traces, focus mode, the ROI box and pen scaling, under rotation and shear;
and the same traces_in_view, which picking and lasso selection read.
"""

import math
import random

import pytest

from PyReconstruct.modules.backend.view import trace_layer as trace_layer_module
from PyReconstruct.modules.backend.view.trace_layer import TraceLayer
from PyReconstruct.modules.datatypes import Trace, Transform


pytestmark = pytest.mark.gui

DIM = (400, 300)
NAME = "bulk-draw"


def _pixels(pixmap):
    image = pixmap.toImage()
    return bytes(image.constBits())


@pytest.fixture
def layer(qapp, real_series):
    section = real_series.loadSection(min(real_series.sections))
    real_series.setOption("show_ztraces", False)
    real_series.setOption("show_flags", "none")
    real_series.setOption("fill_opacity", 0.3)
    rng = random.Random(266)
    for i in range(300):
        color = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        trace = Trace(f"{NAME}-{i % 40}", color, i % 5 != 0)
        x, y = rng.uniform(-40, 40), rng.uniform(-40, 40)
        r = rng.uniform(0.05, 6)
        k = rng.randrange(3, 40)
        trace.points = [
            (x + r * math.cos(t), y + r * math.sin(t))
            for t in (j * 2 * math.pi / k for j in range(k))
        ]
        trace.fill_mode = (
            ("transparent", "always"),
            ("solid", "always"),
            ("transparent", "selected"),
            ("solid", "unselected"),
            ("none", "none"),
        )[i % 5]
        section.addTrace(trace, log_event=False)
    section.clearTracking()
    return TraceLayer(section, real_series)


def _draw(layer, window, bulk=True, **kwargs):
    if not bulk:
        # an instance attribute shadows the method; deleting it restores it
        layer._screenPolygons = lambda *a: None
    try:
        pixels = _pixels(layer.generateTraceLayer(DIM, list(window), **kwargs))
    finally:
        if not bulk:
            del layer._screenPolygons
    return pixels, list(layer.traces_in_view)


def _ours(section):
    return [t for t in section.tracesAsList() if t.name.startswith(NAME)]


def _select(layer):
    section = layer.section
    section.selected_traces = _ours(section)[::7]


def _hide(layer):
    for trace in _ours(layer.section)[3::4]:
        trace.hidden = True


SCENARIOS = {
    "plain": (lambda layer: None, {}),
    "standard": (_select, {}),
    "outline": (_select, {}),
    "glow": (_select, {}),
    "hidden": (lambda layer: (_select(layer), _hide(layer)), {}),
    "show_all": (lambda layer: (_select(layer), _hide(layer)), {"show_all_traces": True}),
    "focus": (lambda layer: None, {"focus_on": f"{NAME}-3"}),
    "roi": (lambda layer: None, {"roi_box": (0, 0, 30, 20)}),
}

WINDOWS = {
    "whole": (-50, -40, 100, 75),
    "close": (-6, -4, 12, 9),
    "edge": (2.7, 1.1, 8, 6),
}

TFORMS = {
    "identity": Transform.identity(),
    "rotate_shear": Transform([math.cos(0.6), -math.sin(0.6) + 0.4, 1.5,
                               math.sin(0.6), math.cos(0.6), -2]),
}


@pytest.mark.parametrize("tform", TFORMS)
@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_bulk_pass_draws_the_same_frame(layer, scenario, window, tform):
    layer.section.tforms[layer.series.alignment] = TFORMS[tform]
    if scenario in ("outline", "glow"):
        layer.series.setOption("selected_trace_style", scenario)
    setup, kwargs = SCENARIOS[scenario]
    setup(layer)
    for moved in (True, False):
        expected = _draw(layer, WINDOWS[window], bulk=False, window_moved=moved, **kwargs)
        actual = _draw(layer, WINDOWS[window], window_moved=moved, **kwargs)
        assert actual[0] == expected[0]
        assert actual[1] == expected[1]


def test_pen_scale_draws_the_same_frame(layer):
    _select(layer)
    layer.pen_scale = 2
    assert _draw(layer, WINDOWS["close"]) == _draw(layer, WINDOWS["close"], bulk=False)


def test_drawn_traces_build_no_qpoint_lists(layer, monkeypatch):
    """The point of the change: no Python QPoint per point for a drawn trace."""
    calls = 0
    real = trace_layer_module.qPointList

    def counting(*a, **k):
        nonlocal calls
        calls += 1
        return real(*a, **k)

    monkeypatch.setattr(trace_layer_module, "qPointList", counting)
    _, in_view = _draw(layer, WINDOWS["whole"])
    assert len(in_view) > 200
    assert calls == 0


def test_polygons_hold_each_traces_own_points(layer):
    section = layer.section
    tform = section.tform
    layer.series.window = list(WINDOWS["close"])
    layer.pixmap_dim = DIM
    traces = _ours(section)
    empty = Trace(f"{NAME}-empty", (1, 2, 3), True)
    off = Trace(f"{NAME}-off", (1, 2, 3), True)
    off.points = [(500, 500), (501, 500), (501, 501)]
    trace_list = [traces[0], empty, off] + traces[1:]
    polygons = layer._screenPolygons(trace_list, tform)
    assert polygons[1] is None
    assert polygons[2] is False
    drawn = 0
    for trace, polygon in zip(trace_list, polygons):
        if polygon is None or polygon is False:
            continue
        drawn += 1
        assert [(p.x(), p.y()) for p in polygon] == layer.traceToPix(trace, tform)
    assert drawn > 10


def test_empty_trace_is_reported_and_left_out(layer, monkeypatch, capsys):
    section = layer.section
    empty = Trace(f"{NAME}-empty", (1, 2, 3), True)
    traces = section.tracesAsList()
    monkeypatch.setattr(section, "tracesAsList", lambda: traces + [empty])
    monkeypatch.setattr(layer, "_cullMask", lambda *a: None)
    _, in_view = _draw(layer, WINDOWS["whole"])
    assert "EMPTY TRACE DETECTED" in capsys.readouterr().out
    assert empty not in in_view
    assert len(in_view) > 200


def test_points_past_32_bits_convert_one_trace_at_a_time(layer):
    """Qt points are 32-bit; such a frame takes the per-trace path, as before."""
    section = layer.section
    far = Trace(f"{NAME}-far", (1, 2, 3), False)
    far.points = [(0, 0), (1e12, 0)]
    layer.series.window = list(WINDOWS["close"])
    layer.pixmap_dim = DIM
    assert layer._screenPolygons([far] + _ours(section), section.tform) is None
