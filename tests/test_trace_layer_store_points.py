"""The trace draw reads its screen points from the section's store.

A trace's row holds its points as float64, so the draw must give the same
pixels, the same traces_in_view and the same saved bytes as reading every
trace's own tuples. A trace with no row, or whose row has another point count
than the trace, is read from its own points.
"""

import math
import random

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.backend.view import trace_layer as trace_layer_module
from PyReconstruct.modules.backend.view.trace_layer import TraceLayer, flatPoints
from PyReconstruct.modules.datatypes import Trace, Transform
from PyReconstruct.modules.datatypes.section import fast_dumps


pytestmark = pytest.mark.gui

DIM = (400, 300)
NAME = "store-points"
WINDOWS = {
    "whole": (-50, -40, 100, 75),
    "close": (-6, -4, 12, 9),
}
TFORMS = {
    "identity": Transform.identity(),
    "rotate_shear": Transform([math.cos(0.6), -math.sin(0.6) + 0.4, 1.5,
                               math.sin(0.6), math.cos(0.6), -2]),
}


@pytest.fixture
def layer(qapp, real_series):
    real_series.setSettingsStore(DictSettingsStore())
    section = real_series.loadSection(min(real_series.sections))
    real_series.setOption("show_ztraces", False)
    real_series.setOption("show_flags", "none")
    real_series.setOption("fill_opacity", 0.3)
    rng = random.Random(1003)
    for i in range(200):
        color = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        trace = Trace(f"{NAME}-{i % 30}", color, i % 4 != 0)
        x, y = rng.uniform(-40, 40), rng.uniform(-40, 40)
        r = rng.uniform(0.05, 6)
        k = rng.randrange(3, 40)
        # ints and floats, as a file can hold both
        trace.points = [
            (round(x + r * math.cos(t)) if j % 7 == 0 else x + r * math.cos(t),
             y + r * math.sin(t))
            for j, t in enumerate(j * 2 * math.pi / k for j in range(k))
        ]
        trace.fill_mode = (("transparent", "always"), ("solid", "always"),
                           ("none", "none"), ("solid", "unselected"))[i % 4]
        section.addTrace(trace, log_event=False)
    section.clearTracking()
    yield TraceLayer(section, real_series)
    real_series.setSettingsStore(None)


def _ours(section):
    return [t for t in section.tracesAsList() if t.name.startswith(NAME)]


def _draw(layer, window, from_store=True):
    if not from_store:
        # every trace's own tuples, as the draw read them before
        layer._fieldPoints = lambda traces, counts: flatPoints(traces, int(counts.sum()))
    try:
        image = layer.generateTraceLayer(DIM, list(window)).toImage()
        pixels = bytes(image.constBits())
    finally:
        if not from_store:
            del layer._fieldPoints
    return pixels, list(layer.traces_in_view)


def _saved(section):
    return fast_dumps(section.getDict())


@pytest.mark.parametrize("tform", TFORMS)
@pytest.mark.parametrize("window", WINDOWS)
def test_store_points_draw_the_same_frame_and_save_the_same_bytes(layer, window, tform):
    section = layer.section
    section.tforms[layer.series.alignment] = TFORMS[tform]
    expected = _draw(layer, WINDOWS[window], from_store=False)
    before = _saved(section)
    actual = _draw(layer, WINDOWS[window])
    assert len(actual[1]) > 5
    assert actual == expected
    assert _saved(section) == before


def test_traces_with_rows_are_not_read_from_their_points(layer, monkeypatch):
    seen = []
    real = trace_layer_module.flatPoints

    def spy(traces, count):
        seen.extend(traces)
        return real(traces, count)

    monkeypatch.setattr(trace_layer_module, "flatPoints", spy)
    _, in_view = _draw(layer, WINDOWS["whole"])
    assert len(in_view) > 150
    assert seen == []


def test_edits_through_the_section_draw_their_new_points(layer):
    section = layer.section
    section.selected_traces = _ours(section)[::5]
    section.translateTraces(1.25, -0.5, log_event=False)
    assert _draw(layer, WINDOWS["whole"]) == _draw(layer, WINDOWS["whole"], from_store=False)


def test_a_trace_whose_row_has_another_count_draws_its_own_points(layer, monkeypatch):
    section = layer.section
    _, in_view = _draw(layer, WINDOWS["whole"])
    trace = [t for t in _ours(section) if t in in_view][3]
    # out of the section's edit methods, so its row still has the old count
    trace.points.append((trace.points[0][0] + 3.5, trace.points[0][1] - 2.0))
    seen = []
    real = trace_layer_module.flatPoints

    def spy(traces, count):
        seen.extend(traces)
        return real(traces, count)

    monkeypatch.setattr(trace_layer_module, "flatPoints", spy)
    actual = _draw(layer, WINDOWS["whole"])
    assert seen == [trace]
    monkeypatch.setattr(trace_layer_module, "flatPoints", real)
    assert actual == _draw(layer, WINDOWS["whole"], from_store=False)


def test_a_section_without_a_store_draws_from_the_points(layer):
    expected = _draw(layer, WINDOWS["whole"], from_store=False)
    layer.section._columns = None
    assert _draw(layer, WINDOWS["whole"]) == expected
