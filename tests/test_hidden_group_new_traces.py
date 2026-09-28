"""A hidden group hides new and restored traces, not only loaded ones.

Section.traces_group_hide is filled once, when the section loads, and holds
trace objects. A trace drawn into a hidden group afterwards, or brought back
by undo or redo as a fresh copy, was not on it, so it showed until the section
reloaded. Visibility now also checks the trace's object name against the
hidden groups.
"""
import pytest

from PyReconstruct.modules.datatypes.trace import Trace

pytestmark = pytest.mark.gui

NAME = "hidden_group_obj"
GROUP = "hidden_here"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def _square(series, offset):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


def _visible(window, trace):
    window.field.generateView()
    return window.field.section_layer.trace_visibile_p(trace)


def test_a_new_trace_in_a_hidden_group_is_hidden(window):
    series = window.series
    field = window.field
    series.object_groups.add(group=GROUP, obj=NAME)
    series.groups_visibility[GROUP] = False

    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(_square(series, 0.3), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)
    trace = field.section.contours[NAME][0]
    assert not _visible(window, trace), "a new trace in a hidden group showed"

    series.groups_visibility[GROUP] = True
    assert _visible(window, trace), "showing the group again must show the trace"


def test_undo_and_redo_keep_a_hidden_groups_trace_hidden(window):
    series = window.series
    field = window.field
    series.object_groups.add(group=GROUP, obj=NAME)
    series.groups_visibility[GROUP] = False
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(_square(series, 0.3), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)
    field.newTrace(_square(series, 0.6), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)

    window.undo()
    window.undo(redo=True)
    for trace in field.section.contours[NAME]:
        assert not _visible(window, trace), "undo or redo brought a hidden trace back into view"


def test_invert_selection_skips_a_new_trace_in_a_hidden_group(window):
    """Invert selection picks only traces visible in the field."""
    series = window.series
    field = window.field
    series.object_groups.add(group=GROUP, obj=NAME)
    series.groups_visibility[GROUP] = False
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(_square(series, 0.3), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)
    trace = field.section.contours[NAME][0]

    field.section.selected_traces = []
    field.section.invertTraceSelection()
    assert trace not in field.section.selected_traces
