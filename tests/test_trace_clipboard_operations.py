"""Clipboard commands on a live field, including ownership and selection safety."""

import pytest

from PyReconstruct.modules.datatypes import Flag, Trace, Transform


pytestmark = pytest.mark.gui

TRIANGLE = [(0.01, 0.01), (0.03, 0.01), (0.02, 0.03)]


@pytest.fixture
def field(main_window, local_series_settings):
    local_series_settings(main_window)
    field = main_window.field
    field.section.tform = Transform.identity()
    field.deselectAllTraces()
    return field


def add_trace(field, name, *, closed=True):
    trace = Trace(name, [20, 40, 60], closed)
    trace.points = list(TRIANGLE)
    trace.tags = {"reviewed"}
    trace.fill_mode = ["solid", "selected"]
    trace.negative = True
    field.section.addTrace(trace, log_event=False)
    return trace


def test_copy_owns_its_geometry_and_attributes_in_field_coordinates(field):
    trace = add_trace(field, "clipboard_source")
    field.section.tform = Transform([2, 0, 0.1, 0, 3, -0.2])
    field.section.selected_traces = [trace]

    field.copy()

    copied, = field.clipboard
    assert copied.points == [
        pytest.approx(p) for p in [(0.12, -0.17), (0.16, -0.17), (0.14, -0.11)]
    ]
    assert (copied.name, copied.closed, copied.negative) == ("clipboard_source", True, True)
    assert copied.color == [20, 40, 60]
    assert copied.fill_mode == ["solid", "selected"]
    assert copied.tags == {"reviewed"}
    copied.points[0] = (9, 9)
    copied.color[0] = 99
    copied.fill_mode[0] = "none"
    copied.tags.add("clipboard_only")
    assert trace.points == TRIANGLE
    assert trace.color == [20, 40, 60]
    assert trace.fill_mode == ["solid", "selected"]
    assert trace.tags == {"reviewed"}


def test_cut_removes_only_selected_traces_and_keeps_selected_flags(field):
    selected = add_trace(field, "cut_source", closed=False)
    bystander = add_trace(field, "cut_bystander")
    flag = Flag("keep_flag", 0.02, 0.02, field.section.n, (255, 0, 0))
    field.section.addFlag(flag, log_event=False)
    field.section.selected_flags = [flag]
    field.section.selected_traces = [selected]

    assert field.cut() is True

    assert list(field.section.contours.get("cut_source", [])) == []
    assert list(field.section.contours["cut_bystander"]) == [bystander]
    assert flag in field.section.flags
    assert field.section.selected_flags == [flag]
    assert [(t.name, t.points, t.closed) for t in field.clipboard] == [
        ("cut_source", TRIANGLE, False),
    ]
    assert field.paste() is True
    restored, = field.section.contours["cut_source"]
    assert restored.points == TRIANGLE
    assert restored.closed is False
    assert restored.tags == {"reviewed"}


@pytest.mark.parametrize("closed", [False, True])
def test_repeated_paste_preserves_geometry_and_owns_each_copy(field, closed):
    source = add_trace(field, "paste_source", closed=closed)
    field.section.tform = Transform([2, 0, 0.1, 0, 3, -0.2])
    field.section.selected_traces = [source]
    field.copy()

    assert field.paste() is True
    assert field.paste() is True

    traces = list(field.section.contours["paste_source"])
    assert len(traces) == 3
    for trace in traces:
        assert trace.points == [pytest.approx(p) for p in TRIANGLE]
        assert (trace.closed, trace.negative) == (closed, True)
        assert trace.color == [20, 40, 60]
        assert trace.fill_mode == ["solid", "selected"]
        assert trace.tags == {"reviewed"}
    traces[1].points[0] = (9, 9)
    traces[1].tags.add("first_paste_only")
    traces[1].color[0] = 99
    traces[1].fill_mode[0] = "none"
    assert source.points == TRIANGLE
    assert traces[2].points == [pytest.approx(p) for p in TRIANGLE]
    assert field.clipboard[0].points == [
        pytest.approx(p) for p in [(0.12, -0.17), (0.16, -0.17), (0.14, -0.11)]
    ]
    for trace in (source, traces[2], field.clipboard[0]):
        assert trace.tags == {"reviewed"}
        assert trace.color == [20, 40, 60]
        assert trace.fill_mode == ["solid", "selected"]


def test_empty_selection_keeps_the_previous_clipboard(field):
    source = add_trace(field, "previous_clipboard")
    field.section.selected_traces = [source]
    field.copy()
    field.section.selected_traces = []

    field.copy()
    assert field.cut() is False

    assert [(t.name, t.points) for t in field.clipboard] == [("previous_clipboard", TRIANGLE)]
    assert field.paste() is True
    assert len(field.section.contours["previous_clipboard"]) == 2


def test_empty_clipboard_paste_does_not_edit_the_selection(field):
    source = add_trace(field, "empty_clipboard")
    field.section.selected_traces = [source]
    field.clipboard = []

    assert field.paste() is False
    assert field.pasteAttributes() is False

    assert list(field.section.contours["empty_clipboard"]) == [source]
    assert source.points == TRIANGLE
    assert source.tags == {"reviewed"}
    field.copy()
    assert field.paste() is True
    assert len(field.section.contours["empty_clipboard"]) == 2


def test_hidden_trace_layer_blocks_clipboard_commands(field):
    first = add_trace(field, "hidden_first")
    second = add_trace(field, "hidden_second", closed=False)
    field.section.selected_traces = [first]
    field.copy()
    field.section.selected_traces = [second]
    field.hide_trace_layer = True

    field.copy()
    assert field.cut() is False
    assert field.paste() is False
    assert field.pasteAttributes() is False

    assert [(t.name, t.points) for t in field.clipboard] == [("hidden_first", TRIANGLE)]
    assert list(field.section.contours["hidden_first"]) == [first]
    assert list(field.section.contours["hidden_second"]) == [second]
    assert second.points == TRIANGLE
    field.hide_trace_layer = False
    field.copy()
    assert [(t.name, t.closed) for t in field.clipboard] == [("hidden_second", False)]


def test_paste_attributes_keeps_geometry_and_does_not_share_tags(field):
    source = add_trace(field, "attribute_source")
    field.section.selected_traces = [source]
    field.copy()
    targets = [add_trace(field, "attribute_target", closed=closed) for closed in (False, True)]
    targets[0].points = [(0.04, 0.01), (0.06, 0.01), (0.05, 0.03)]
    targets[1].points = [(0.01, 0.05), (0.03, 0.05), (0.03, 0.07), (0.01, 0.07)]
    for target in targets:
        target.color = (255, 0, 0)
        target.tags = {"old"}
        target.fill_mode = ("none", "none")
        target.negative = False
    field.section.selected_traces = targets

    assert field.pasteAttributes() is True

    traces = list(field.section.contours["attribute_source"])
    assert len(traces) == 3
    assert sorted((t.closed, t.negative, t.points) for t in traces) == [
        (False, False, [(0.04, 0.01), (0.06, 0.01), (0.05, 0.03)]),
        (True, False, [(0.01, 0.05), (0.03, 0.05), (0.03, 0.07), (0.01, 0.07)]),
        (True, True, TRIANGLE),
    ]
    for trace in traces:
        assert tuple(trace.color) == (20, 40, 60)
        assert tuple(trace.fill_mode) == ("solid", "selected")
        assert trace.tags == {"reviewed"}
    traces[1].tags.add("edited_after_paste")
    assert traces[2].tags == {"reviewed"}
    assert field.clipboard[0].tags == {"reviewed"}
