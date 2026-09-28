"""A merge that yields no outline leaves the traces alone (fork #467 review).

`mergeTraces` deleted the selected traces and then created the merged result.
When the merge produced nothing, which a trace smaller than one grid cell can
do, the delete had already happened and the user was left with no trace and no
message. The merge now refuses before deleting anything, and says why.
"""
import pytest

pytestmark = pytest.mark.gui

NAME = "tiny_merge_obj"


def test_empty_merge_result_deletes_nothing_and_says_so(main_window, monkeypatch):
    from PyReconstruct.modules.datatypes.trace import Trace
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    field = main_window.field
    section = field.section
    series = main_window.series

    notices = []
    monkeypatch.setattr(fw2, "notify", lambda msg, *a, **k: notices.append(msg))
    # the geometry's answer for "too small to outline"
    monkeypatch.setattr(fw2, "mergeTracesInField", lambda traces, mag: [])

    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * 0.4, wy + wh * 0.4
    sq_a = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    sq_b = [(x + side / 2, y + side / 2) for x, y in sq_a]

    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    for sq in (sq_a, sq_b):
        field.newTrace(sq, field.tracing_trace, points_as_pix=False,
                       reduce_points=False, log_event=False)
    before = [tuple(map(tuple, t.points)) for t in section.contours[NAME]]
    assert len(before) == 2

    section.selected_traces = list(section.contours[NAME])
    field.mergeTraces()

    after = [tuple(map(tuple, t.points)) for t in section.contours[NAME]]
    assert after == before, "an empty merge result must not delete the inputs"
    assert any("no outline" in m for m in notices), notices


def test_the_old_order_would_have_lost_them(main_window, monkeypatch):
    """The premise: deleting first is what made the empty result destructive.
    Pinned through the guard's absence rather than by editing the code: with a
    non-empty result the merge still replaces the inputs as before."""
    from PyReconstruct.modules.datatypes.trace import Trace
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    field = main_window.field
    section = field.section
    series = main_window.series
    monkeypatch.setattr(fw2, "notify", lambda *a, **k: None)

    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.2
    x0, y0 = wx + ww * 0.3, wy + wh * 0.3
    sq_a = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    sq_b = [(x + side / 2, y + side / 2) for x, y in sq_a]

    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    for sq in (sq_a, sq_b):
        field.newTrace(sq, field.tracing_trace, points_as_pix=False,
                       reduce_points=False, log_event=False)
    section.selected_traces = list(section.contours[NAME])
    field.mergeTraces()
    assert len(section.contours[NAME]) == 1
