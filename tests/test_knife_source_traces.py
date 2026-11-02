"""Knife replacements retain their source and are committed only after validation."""

import pytest
from shapely.geometry import Polygon

from PyReconstruct.modules.calc import pixmapPointToField
from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.gui.main.field_widget_5_mouse import KNIFE

pytestmark = pytest.mark.gui
NAME = "knife_sources"
REFUSAL = "The cut could not be completed.\nThe object was left unchanged."


@pytest.fixture
def knife_field(main_window, local_series_settings, monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_2_trace

    local_series_settings(main_window)
    field = main_window.field
    field.setMouseMode(KNIFE)
    field.series.setOption("roll_knife_average", False)
    field.series.setOption("knife_del_threshold", 0.0)
    notices = []
    monkeypatch.setattr(field_widget_2_trace, "notify", notices.append)
    return field, notices


def _square(field, x, negative=False, closed=True):
    trace = Trace(NAME, (0, 255, 0), closed=closed)
    trace.negative = negative
    pixels = [(x, 100.25), (x + 80.5, 100.25),
              (x + 80.5, 180.75), (x, 180.75)]
    trace.points = [
        field.section.tform.map(*pixmapPointToField(
            px, py, field.pixmap_dim, field.series.window, field.section.mag
        ), inverted=True)
        for px, py in pixels
    ]
    field.section.addTrace(trace, log_event=False)
    return trace


def _select(field, traces):
    field.section.selected_traces = list(traces)
    field.saveState()


@pytest.mark.parametrize("negative_first", [False, True])
@pytest.mark.parametrize("cut_both", [False, True])
def test_cut_pieces_keep_each_sources_sign(knife_field, negative_first, cut_both):
    field, notices = knife_field
    first = _square(field, 100.25, negative_first)
    second = _square(field, 300.25, not negative_first)
    _select(field, [first, second])

    assert field.cutTrace([(80, 140), (410 if cut_both else 200, 140)]) is True

    pieces = list(field.section.contours[NAME])
    assert len(pieces) == (4 if cut_both else 3)
    for source, count in ((first, 2), (second, 2 if cut_both else 1)):
        source_shape = Polygon(source.points)
        source_pieces = [t for t in pieces if source_shape.covers(Polygon(t.points).centroid)]
        assert len(source_pieces) == count
        assert all(t.negative == source.negative for t in source_pieces)
    assert notices == []


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("zoom", [0.5, 2.0])
def test_a_missed_stroke_preserves_geometry_and_history(knife_field, closed, zoom):
    field, notices = knife_field
    field.series.window[2:] = [d * zoom for d in field.series.window[2:]]
    trace = _square(field, 100.25, closed=closed)
    _select(field, [trace])
    before = list(trace.points)
    states = field.series_states[field.section.n]
    undo_count = len(states.undo_states)
    logs = field.series.log_set.getList()

    changed = field.cutTrace([(300, 300), (400, 300)])

    assert list(field.section.contours[NAME][0].points) == before
    assert changed is False
    assert field.section.contours[NAME][0] is trace
    assert len(states.undo_states) == undo_count
    assert field.series.log_set.getList() == logs
    assert notices == []


def test_a_cut_leaves_the_missed_traces_geometry_exact(knife_field):
    field, notices = knife_field
    first = _square(field, 100.25)
    second = _square(field, 300.25)
    _select(field, [first, second])
    before = list(second.points)

    assert field.cutTrace([(80, 140), (200, 140)]) is True

    assert second in field.section.contours[NAME]
    assert list(second.points) == before
    assert notices == []


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_losing_all_pieces_of_one_trace_refuses_the_whole_cut(
    knife_field, closed, reverse
):
    field, notices = knife_field
    first = _square(field, 100.25, closed=closed)
    second = _square(field, 300.25, closed=closed)
    first.tags = {"first"}
    second.tags = {"second"}
    selection = [second, first] if reverse else [first, second]
    _select(field, selection)
    before = [list(t.points) for t in (first, second)]
    states = field.series_states[field.section.n]
    undo_count = len(states.undo_states)
    logs = field.series.log_set.getList()
    field.series.setOption("knife_del_threshold", 50.0 if closed else 75.0)
    ys = [y for _, y in field.section_layer.traceToPix(first)]
    mid_y = (min(ys) + max(ys)) / 2

    changed = field.cutTrace([(80, mid_y), (200, mid_y)])

    assert changed is False
    assert list(field.section.contours[NAME]) == [first, second]
    assert [list(t.points) for t in (first, second)] == before
    assert first.tags == {"first"}
    assert second.tags == {"second"}
    assert field.section.selected_traces == selection
    assert len(states.undo_states) == undo_count
    assert field.series.log_set.getList() == logs
    assert notices == [REFUSAL]


def test_a_successful_cut_is_one_undo_step(knife_field):
    field, notices = knife_field
    first = _square(field, 100.25)
    second = _square(field, 300.25, negative=True)
    first.tags = {"first"}
    second.tags = {"second"}
    _select(field, [first, second])

    def snapshot():
        return [(list(t.points), t.negative, set(t.tags))
                for t in field.section.contours[NAME]]

    before = snapshot()
    states = field.series_states[field.section.n]
    undo_count = len(states.undo_states)

    assert field.cutTrace([(80, 140), (200, 140)]) is True
    after = snapshot()
    assert len(after) == 3
    assert len(states.undo_states) == undo_count + 1
    assert all(t.tags == {"first", "second"} for t in field.section.contours[NAME])

    field.mainwindow.undo()
    assert snapshot() == before
    field.mainwindow.undo(redo=True)
    assert snapshot() == after
    assert notices == []
