"""The trace draw reads every point into one array without np.array's shape pass.

flatPoints must give the same numbers np.array gave for the joined point
lists, so the field must not change by one pixel: at the whole field, a mid
zoom and 1:1, with fills, selected, hidden, negative and open traces and the
hover name label, and the same traces_in_view, which picking reads.
"""

import math
import random
from itertools import chain

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.backend.view import trace_layer as trace_layer_module
from PyReconstruct.modules.backend.view.trace_layer import flatPoints
from PyReconstruct.modules.datatypes import Trace


pytestmark = pytest.mark.gui

FIELD_SIZE = (400, 300)
NAME = "flat-points"


def _before(traces, count):
    """The conversion the draw used before flatPoints."""
    return np.array(list(chain.from_iterable(t.points for t in traces)), dtype=float)


def _trace(points, closed=True):
    trace = Trace(NAME, (10, 20, 30), closed)
    trace.points = points
    return trace


@pytest.mark.parametrize("points", [
    [(0, 0), (1, 2), (3, 4)],
    [(0.1, -0.0), (1e300, -1e-310), (2 ** 60 + 1, 7)],
    [(np.float64(1.5), np.float32(0.25)), (np.int64(3), True)],
    [(math.nan, math.inf), (-math.inf, 0.5)],
])
def test_flat_points_are_the_numbers_np_array_gives(points):
    traces = [_trace(points), _trace([(5.5, 6.5)]), _trace(points[::-1], False)]
    count = sum(len(t.points) for t in traces)
    got = flatPoints(traces, count)
    want = _before(traces, count)
    assert got.dtype == want.dtype and got.shape == want.shape == (count, 2)
    assert got.tobytes() == want.tobytes()


def test_points_that_are_not_pairs_go_through_np_array():
    """A run of the wrong length takes the old conversion, with its result."""
    traces = [_trace([(0, 1, 2), (3, 4, 5)]), _trace([(6, 7, 8)])]
    got = flatPoints(traces, 3)
    assert got.shape == (3, 3)
    assert got.tobytes() == _before(traces, 3).tobytes()


@pytest.fixture
def field(main_window):
    """The field at a fixed size over a section of mixed traces."""
    field = main_window.field
    series = main_window.series
    # the options set here live in the settings store, not the series; a
    # store of this series' own keeps them from reaching later tests
    series.setSettingsStore(DictSettingsStore())
    try:
        yield _mixed(main_window)
    finally:
        series.setSettingsStore(None)


def _mixed(main_window):
    field = main_window.field
    field.setFixedSize(*FIELD_SIZE)
    main_window.resize(FIELD_SIZE[0] + 600, FIELD_SIZE[1] + 400)
    QApplication.processEvents()
    series = main_window.series
    series.setOption("fill_opacity", 0.3)
    section = field.section
    rng = random.Random(1003)
    ours = []
    for i in range(240):
        color = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        trace = Trace(f"{NAME}-{i % 30}", color, i % 6 != 0)
        x, y = rng.uniform(0, 10), rng.uniform(0, 7)
        r = rng.uniform(0.004, 0.8)
        k = rng.randrange(3, 120)
        points = [
            (x + r * math.cos(t), y + r * math.sin(t))
            for t in (j * 2 * math.pi / k for j in range(k))
        ]
        if i % 11 == 0:
            # integer points, as a trace drawn on screen can carry
            points = [(round(px), round(py)) for px, py in points]
        trace.points = points
        trace.negative = i % 7 == 0
        trace.fill_mode = (
            ("transparent", "always"),
            ("solid", "always"),
            ("transparent", "selected"),
            ("solid", "unselected"),
            ("none", "none"),
        )[i % 5]
        section.addTrace(trace, log_event=False)
        ours.append(trace)
    for trace in ours[3::9]:
        trace.hidden = True
    section.selected_traces = ours[::8]
    section.clearTracking()
    bounds = [t.getBounds(section.tform) for t in ours]
    x0 = min(b[0] for b in bounds)
    y0 = min(b[1] for b in bounds)
    x1 = max(b[2] for b in bounds)
    y1 = max(b[3] for b in bounds)
    field.test_bounds = (x0, y0, x1, y1)
    field.test_hover = ours[1]
    return field


def _windows(field):
    x0, y0, x1, y1 = field.test_bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = FIELD_SIZE
    mag = field.section.mag
    return {
        "whole": [x0, y0, x1 - x0, y1 - y0],
        "mid": [cx - 2 * w * mag, cy - 2 * h * mag, 4 * w * mag, 4 * h * mag],
        "1to1": [cx - w * mag / 2, cy - h * mag / 2, w * mag, h * mag],
    }


def _grab(field, window, hover):
    field.series.window = list(window)
    field.generateView()
    if hover:
        # the screen point of the hover trace's first point
        x, y = field.section_layer.traceToPix(field.test_hover)[0]
        field.mouse_x, field.mouse_y = x, y
    else:
        field.mouse_x = field.mouse_y = -10_000
    field.repaint()
    image = field.grab().toImage()
    in_view = list(field.section_layer.traces_in_view)
    return bytes(image.constBits()), in_view


@pytest.mark.parametrize("view", ["whole", "mid", "1to1"])
@pytest.mark.parametrize("style", ["standard", "outline"])
def test_the_field_is_the_same_pixels(field, monkeypatch, view, style):
    field.series.setOption("selected_trace_style", style)
    window = _windows(field)[view]
    # the hover trace must be on screen for its name to be drawn
    field.series.window = list(window)
    field.generateView()
    assert field.test_hover in field.section_layer.traces_in_view
    after = _grab(field, window, hover=True)
    with monkeypatch.context() as m:
        m.setattr(trace_layer_module, "flatPoints", _before)
        before = _grab(field, window, hover=True)
    assert after[0] == before[0]
    assert after[1] == before[1]
    # not an empty comparison: traces are drawn, and the name label shows
    assert len(after[1]) > (100 if view == "whole" else 3)
    assert _grab(field, window, hover=False)[0] != after[0]
