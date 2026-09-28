"""Hidden groups and traces that appear after the section loads.

Section.traces_group_hide is filled once, when the section loads, and holds
trace objects. A trace brought back by undo or redo is a fresh copy, so it was
not on the list and showed until the section reloaded. Visibility now also
checks the trace's object name against the hidden groups.

Drawing is the other case, and it is handled differently: a trace drawn into a
hidden group turns that group back on, rather than vanishing the moment it is
drawn (his call, 2026-09-28).
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


def _hide_group_with(window, offsets):
    """Draw traces of NAME at the given offsets, put NAME in GROUP, hide it."""
    series, field = window.series, window.field
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    for off in offsets:
        field.newTrace(_square(series, off), field.tracing_trace,
                       points_as_pix=False, reduce_points=False)
    series.object_groups.add(group=GROUP, obj=NAME)
    series.groups_visibility[GROUP] = False
    window.createMenuBar()      # as the object list's Add to group does
    field.section.traces_group_hide = []
    field.section.setGroupVisibility(series.groups_visibility)


def test_drawing_into_a_hidden_group_shows_the_group(window):
    series, field = window.series, window.field
    _hide_group_with(window, [0.2])
    first = field.section.contours[NAME][0]
    assert not _visible(window, first), "fixture premise: the group hides it"

    field.newTrace(_square(series, 0.6), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)

    assert series.groups_visibility[GROUP] is True, "the group was not turned back on"
    for trace in field.section.contours[NAME]:
        assert _visible(window, trace), "a trace of the shown group stayed hidden"
    window.checkActions()
    assert getattr(window, f"{GROUP}_viz_act").isChecked(), "View > Groups box not ticked"


def test_undo_and_redo_keep_a_hidden_groups_trace_hidden(window):
    series, field = window.series, window.field
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(_square(series, 0.3), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)
    field.newTrace(_square(series, 0.6), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)
    series.object_groups.add(group=GROUP, obj=NAME)
    series.groups_visibility[GROUP] = False
    field.section.traces_group_hide = []
    field.section.setGroupVisibility(series.groups_visibility)

    window.undo()
    window.undo(redo=True)
    assert series.groups_visibility[GROUP] is False, "undo or redo must not show the group"
    for trace in field.section.contours[NAME]:
        assert not _visible(window, trace), "undo or redo brought a hidden trace into view"


def test_invert_selection_skips_a_restored_trace_in_a_hidden_group(window):
    """Invert selection picks only traces visible in the field."""
    series, field = window.series, window.field
    _hide_group_with(window, [0.3, 0.6])
    window.undo()
    window.undo(redo=True)
    field.section.selected_traces = []
    field.section.invertTraceSelection()
    for trace in field.section.contours[NAME]:
        assert trace not in field.section.selected_traces
