"""Picking follows the traces and segments drawn in the field."""

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.backend.view.trace_layer import TraceLayer
from PyReconstruct.modules.datatypes import Trace, Transform


pytestmark = pytest.mark.gui

DIM = (400, 400)
WINDOW = [0, 0, 400, 400]


@pytest.fixture
def layer(qapp, real_series):
    real_series.setSettingsStore(DictSettingsStore())
    real_series.setOption("show_ztraces", False)
    real_series.setOption("show_flags", "none")
    section = real_series.loadSection(min(real_series.sections))
    for trace in section.tracesAsList():
        section.removeTrace(trace, log_event=False)
    section.tforms[real_series.alignment] = Transform.identity()
    section.mag = 1
    return TraceLayer(section, real_series)


def test_hidden_group_cannot_be_picked_in_an_empty_view(layer):
    trace = Trace("hidden-object", (0, 255, 0))
    trace.points = [(100, 100), (300, 100), (300, 300), (100, 300)]
    layer.section.addTrace(trace, log_event=False)
    layer.generateTraceLayer(DIM, WINDOW)
    assert layer.getTrace(100, 200) == (trace, "trace")

    layer.series.object_groups.add(group="hidden-group", obj=trace.name)
    layer.series.groups_visibility["hidden-group"] = False
    layer.section.setGroupVisibility(layer.series.groups_visibility)
    layer.generateTraceLayer(DIM, WINDOW)

    assert layer.traces_in_view == []
    assert layer.getTrace(100, 200) == (None, None)

    layer.generateTraceLayer(DIM, WINDOW, show_all_traces=True)
    assert layer.getTrace(100, 200) == (trace, "trace")


@pytest.mark.parametrize("fill", ["none", "transparent", "solid"])
def test_open_trace_cannot_be_picked_on_an_undrawn_closing_edge(layer, fill):
    trace = Trace("open-object", (0, 255, 0), closed=False)
    trace.points = [(100, 300), (100, 100), (300, 100)]
    trace.fill_mode = (fill, "always")
    layer.section.addTrace(trace, log_event=False)
    layer.generateTraceLayer(DIM, WINDOW)

    assert layer.traces_in_view == [trace]
    assert layer.getTrace(100, 200) == (trace, "trace")
    assert layer.getTrace(200, 300) == (trace, "trace")
    assert layer.getTrace(200, 200) == (None, None)
    assert layer.getTrace(150, 250) == (None, None)


@pytest.mark.parametrize("fill", ["none", "transparent", "solid"])
def test_closed_trace_keeps_its_closing_edge_and_filled_interior(layer, fill):
    trace = Trace("closed-object", (0, 255, 0))
    trace.points = [(100, 300), (100, 100), (300, 100)]
    trace.fill_mode = (fill, "always")
    layer.section.addTrace(trace, log_event=False)
    layer.generateTraceLayer(DIM, WINDOW)

    assert layer.getTrace(200, 200) == (trace, "trace")
    expected = (None, None) if fill == "none" else (trace, "trace")
    assert layer.getTrace(150, 250) == expected


@pytest.mark.parametrize("points", [
    [(100, 100), (100, 300)],
    [(100, 100), (100, 100), (100, 300)],
])
def test_short_open_traces_and_repeated_points_remain_pickable(layer, points):
    trace = Trace("short-open-object", (0, 255, 0), closed=False)
    trace.points = points
    layer.section.addTrace(trace, log_event=False)
    layer.generateTraceLayer(DIM, WINDOW)

    assert layer.getTrace(100, 300) == (trace, "trace")
    assert layer.getTrace(90, 300) == (trace, "trace")
    assert layer.getTrace(70, 300) == (None, None)
