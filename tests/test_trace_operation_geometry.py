"""Trace edits checked against coordinates, lengths, and areas computed by hand."""

import pytest
from shapely.geometry import Point, Polygon

from PyReconstruct.modules.calc import cutTraces
from PyReconstruct.modules.datatypes import Trace, Transform


SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]
BEND = [(0, 0), (0.012, 0), (0.012, 0.012)]
SMOOTH_BEND = [
    (0, 0), (0.0048, 0), (0.0088, 0.0008),
    (0.0112, 0.0032), (0.012, 0.0072), (0.012, 0.012),
]
RESAMPLED_BEND = [
    (0, 0), (0.0048, 0), (0.0096, 0),
    (0.012, 0.0024), (0.012, 0.0072), (0.012, 0.012),
]


def test_partial_closed_cut_removes_a_notch_without_splitting_the_trace():
    pieces = cutTraces([SQUARE], [(-1, 5), (5, 5)], closed=True)

    assert len(pieces) == 1
    result = Polygon(pieces[0])
    assert result.bounds == (0, 0, 10, 10)
    # The 0.002-wide cut removes 5 * 0.002 plus a semicircular end cap.
    assert result.area == pytest.approx(99.98999843, abs=1e-8)
    assert not result.covers(Point(2, 5))
    assert result.covers(Point(2, 4))


def test_closed_cut_threshold_is_a_percentage_of_each_original_trace():
    smaller = [(0, 20), (4, 20), (4, 30), (0, 30)]

    pieces = cutTraces([SQUARE, smaller], [(2, -1), (2, 31)], 25, closed=True)

    # The small half of the 100-unit square is dropped. Both halves of the
    # 40-unit rectangle survive its own 10-unit threshold.
    assert sorted(Polygon(p).area for p in pieces) == pytest.approx([19.99, 19.99, 79.99])
    bounds = sorted(Polygon(p).bounds for p in pieces)
    assert bounds == [(0, 20, 1.999, 30), (2.001, 0, 10, 10), (2.001, 20, 4, 30)]


@pytest.mark.parametrize("threshold, expected", [
    (20, [[(0, 0), (2, 0)], [(2, 0), (10, 0)]]),
    (20.001, [[(2, 0), (10, 0)]]),
])
def test_open_cut_keeps_a_piece_at_the_length_threshold(threshold, expected):
    assert cutTraces([[(0, 0), (10, 0)]], [(2, -1), (2, 1)], threshold, closed=False) == expected


def test_open_cut_keeps_a_neighbor_the_knife_does_not_cross():
    pieces = cutTraces(
        [[(0, 0), (10, 0)], [(0, 3), (10, 3)]],
        [(2, -1), (2, 1)],
        closed=False,
    )

    assert pieces == [[(0, 0), (2, 0)], [(2, 0), (10, 0)], [(0, 3), (10, 3)]]


def test_smoothing_a_zero_length_trace_preserves_its_points():
    trace = Trace("zero_length", (20, 40, 60))
    trace.points = [(1, 2), (1, 2), (1, 2)]

    assert trace.smooth(window=3, spacing=0.004) is False
    assert trace.points == [(1, 2), (1, 2), (1, 2)]


@pytest.fixture
def edit_field(main_window, local_series_settings):
    local_series_settings(main_window)
    field = main_window.field
    field.section.tform = Transform.identity()
    field.deselectAllTraces()
    return field


@pytest.fixture
def edit_notices(monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_2_trace

    notices = []
    monkeypatch.setattr(field_widget_2_trace, "notify", notices.append)
    return notices


def add_trace(field, name, points, *, closed=True):
    trace = Trace(name, (20, 40, 60), closed)
    trace.points = list(points)
    trace.tags = {name}
    field.section.addTrace(trace, log_event=False)
    return trace


@pytest.mark.gui
def test_smooth_selection_uses_each_objects_window_and_preserves_open_ends(edit_field):
    field = edit_field
    field.series.setOption("roll_window", 3)
    field.series.setAttr("window_override", "smooth_window", 1)
    default = add_trace(field, "window_default", BEND, closed=False)
    override = add_trace(field, "window_override", BEND, closed=False)
    bystander = add_trace(field, "smooth_bystander", BEND, closed=False)
    field.section.selected_traces = [default, override]

    field.smoothTraces()

    # The bend has length 0.024, giving six equally spaced interpolation
    # samples. A three-sample mean rounds its corner and keeps both ends.
    assert default.points == SMOOTH_BEND
    assert override.points == RESAMPLED_BEND
    assert bystander.points == BEND
    for trace in (default, override, bystander):
        assert trace.closed is False
        assert trace.color == (20, 40, 60)
        assert trace.tags == {trace.name}


@pytest.mark.gui
def test_merge_attributes_uses_first_selection_and_keeps_both_geometries(edit_field):
    field = edit_field
    first = add_trace(field, "merge_first", [(0, 0), (0.01, 0), (0, 0.01)])
    second = add_trace(field, "merge_second", BEND, closed=False)
    second.color = (90, 80, 70)
    second.fill_mode = ("solid", "always")
    field.section.selected_traces = [second, first]

    field.mergeTraces(merge_attrs_only=True)

    merged = list(field.section.contours["merge_second"])
    assert len(merged) == 2
    assert sorted(t.closed for t in merged) == [False, True]
    assert sorted(tuple(t.points) for t in merged) == sorted([
        tuple(BEND), ((0, 0), (0.01, 0), (0, 0.01)),
    ])
    for trace in merged:
        assert trace.color == (90, 80, 70)
        assert trace.fill_mode == ("solid", "always")
        assert trace.tags == {"merge_second"}
    merged[0].tags.add("only_one")
    assert merged[1].tags == {"merge_second"}


@pytest.mark.gui
@pytest.mark.parametrize("mixed_names", [False, True])
def test_knife_refuses_a_mixed_selection_without_changing_either_trace(
    edit_field, edit_notices, mixed_names,
):
    field = edit_field
    first = add_trace(field, "knife_first", [(0, 0), (0.01, 0), (0, 0.01)])
    second = add_trace(
        field, "knife_other" if mixed_names else "knife_first", BEND, closed=mixed_names,
    )
    field.section.selected_traces = [first, second]

    assert field.cutTrace([(0, 0), (100, 100)]) is False

    assert first.points == [(0, 0), (0.01, 0), (0, 0.01)]
    assert second.points == BEND
    assert first.tags == {"knife_first"}
    assert second.tags == {"knife_other" if mixed_names else "knife_first"}
    assert first in field.section.contours["knife_first"]
    assert second in field.section.contours[second.name]
    assert edit_notices == [
        "Select a single object to cut at a time." if mixed_names
        else "Select traces that are all exclusively open or closed."
    ]


@pytest.mark.gui
@pytest.mark.parametrize("case, message", [
    ("single", "Please select two or more traces to merge."),
    ("different_names", "Please merge traces with the same name."),
    ("open", "Please merge only closed traces."),
])
def test_merge_refuses_invalid_selections_without_replacing_traces(
    edit_field, edit_notices, case, message,
):
    field = edit_field
    first = add_trace(field, "merge_guard", [(0, 0), (0.01, 0), (0, 0.01)])
    second = add_trace(
        field, "different_name" if case == "different_names" else "merge_guard",
        BEND, closed=case != "open",
    )
    field.section.selected_traces = [first] if case == "single" else [first, second]

    field.mergeTraces()

    assert first in field.section.contours["merge_guard"]
    assert second in field.section.contours[second.name]
    assert first.points == [(0, 0), (0.01, 0), (0, 0.01)]
    assert second.points == BEND
    assert edit_notices == [message]


@pytest.mark.gui
def test_knife_with_no_selection_keeps_traces_and_reports_the_reason(edit_field, edit_notices):
    field = edit_field
    trace = add_trace(field, "unselected_knife", BEND, closed=False)
    field.section.selected_traces = []

    assert field.cutTrace([(0, 0), (100, 100)]) is False

    assert list(field.section.contours["unselected_knife"]) == [trace]
    assert trace.points == BEND
    assert edit_notices == ["Select trace you would like to cut."]


@pytest.mark.gui
def test_smoothed_knife_splits_an_open_trace_and_keeps_its_attributes(edit_field):
    field = edit_field
    field.series.setOption("roll_knife_average", True)
    field.series.setOption("roll_knife_window", 3)
    field.series.setOption("knife_del_threshold", 0)
    field.series.window = [0, 0, 0.1, 0.1]
    field.generateView()
    trace = add_trace(field, "smoothed_knife", [(0.02, 0.02), (0.08, 0.02)], closed=False)
    trace.fill_mode = ("solid", "selected")
    trace.negative = True
    field.section.selected_traces = [trace]
    (x0, y), (x1, _) = field.section_layer.traceToPix(trace)
    knife = [((x0 + x1) / 2, y - 20 + 2 * i) for i in range(21)]

    assert field.cutTrace(knife) is True

    pieces = sorted(field.section.contours["smoothed_knife"], key=lambda t: t.points[0])
    assert len(pieces) == 2
    # Pixel conversion rounds the original endpoints and crossing to the
    # screen grid. Allow one field pixel, while checking the entire path.
    tolerance = 0.1 / min(field.pixmap_dim)
    for piece, expected in zip(pieces, [
        [(0.02, 0.02), (0.05, 0.02)], [(0.05, 0.02), (0.08, 0.02)],
    ]):
        assert piece.points == [pytest.approx(p, abs=tolerance) for p in expected]
        assert piece.closed is False
        assert piece.negative is True
        assert piece.color == (20, 40, 60)
        assert piece.tags == {"smoothed_knife"}
        assert piece.fill_mode == ("solid", "selected")
