"""Dense incremental redraws must validate live traces without quadratic scans."""

import pytest

from PyReconstruct.modules.backend.view.trace_layer import TraceLayer
from PyReconstruct.modules.datatypes import Contour, Trace, Transform


pytestmark = pytest.mark.gui


@pytest.fixture
def dense_layer(qapp, real_series):
    section = real_series.loadSection(min(real_series.sections))
    section.tforms[real_series.alignment] = Transform.identity()
    real_series.setOption("show_ztraces", False)
    real_series.setOption("show_flags", "none")
    for i in range(200):
        trace = Trace("dense-render", (i % 256, 100, 200), True)
        x, y = i % 20, i // 20
        trace.points = [(x, y), (x + 0.8, y), (x + 0.4, y + 0.8)]
        trace.fill_mode = ("transparent", "always")
        section.addTrace(trace, log_event=False)
    section.clearTracking()
    return TraceLayer(section, real_series)


def _pixels(pixmap):
    image = pixmap.toImage()
    return bytes(image.constBits())


def test_dense_selection_redraw_is_linear_and_matches_full_frame(dense_layer, monkeypatch):
    layer = dense_layer
    section = layer.section
    traces = section.contours["dense-render"].traces
    visits = 0

    class CountingContour(Contour):
        def __iter__(self):
            nonlocal visits
            for trace in super().__iter__():
                visits += 1
                yield trace

    section.contours["dense-render"] = CountingContour("dense-render", traces)
    dim, window = (600, 300), [0, 0, 20, 10]
    layer.generateTraceLayer(dim, window)
    section.selected_traces = traces[::3]
    expected = _pixels(layer.generateTraceLayer(dim, window))
    visits = 0

    def forbid_full_rebuild():
        pytest.fail("selection redraw rebuilt the whole section")

    monkeypatch.setattr(section, "tracesAsList", forbid_full_rebuild)
    actual = _pixels(layer.generateTraceLayer(dim, window, window_moved=False))
    assert actual == expected
    # A shared object with N visible traces must not revisit N(N+1)/2 members.
    assert visits <= 2 * len(traces)


def test_contour_membership_is_refreshed_after_each_edit(dense_layer):
    layer = dense_layer
    section = layer.section
    dim, window = (600, 300), [0, 0, 20, 10]
    layer.generateTraceLayer(dim, window)

    for color in ((255, 0, 0), (0, 255, 0)):
        old = section.contours["dense-render"][0]
        section.editTraceAttributes(
            [old], name=None, color=color, tags=None, mode=None, log_event=False,
        )
        section.clearTracking()
        actual = _pixels(layer.generateTraceLayer(dim, window, window_moved=False))
        assert old not in layer.traces_in_view
        assert actual == _pixels(layer.generateTraceLayer(dim, window))


def test_sparse_redraw_stops_after_finding_its_visible_trace(dense_layer):
    layer = dense_layer
    section = layer.section
    traces = section.contours["dense-render"].traces
    section.hideTraces(traces[1:], log_event=False)
    section.clearTracking()
    visits = 0

    class CountingContour(Contour):
        def __iter__(self):
            nonlocal visits
            for trace in super().__iter__():
                visits += 1
                yield trace

    section.contours["dense-render"] = CountingContour("dense-render", traces)
    dim, window = (600, 300), [0, 0, 20, 10]
    expected = _pixels(layer.generateTraceLayer(dim, window))
    visits = 0
    actual = _pixels(layer.generateTraceLayer(dim, window, window_moved=False))
    assert actual == expected
    assert visits == 1
