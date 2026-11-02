"""Merging a positive outline and its negative hole preserves both traces."""

import pytest

from PyReconstruct.modules.datatypes.trace import Trace

pytestmark = pytest.mark.gui

NAME = "signed_merge_obj"
OUTER = [(0, 0), (1, 0), (1, 1), (0, 1)]
HOLE = [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)]


@pytest.mark.parametrize("negative_first", [False, True])
@pytest.mark.parametrize("restricted", [False, True])
def test_mixed_sign_merge_preserves_traces(
    main_window, monkeypatch, negative_first, restricted
):
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    notices = []
    monkeypatch.setattr(fw2, "notify", lambda message: notices.append(message))
    field = main_window.field
    section = field.section
    for points, negative in ((OUTER, False), (HOLE, True)):
        base = Trace(NAME, (0, 255, 0), True)
        base.negative = negative
        field.newTrace(
            points, base, points_as_pix=False,
            reduce_points=False, log_event=False,
        )
    traces = list(section.contours[NAME])
    before = [(trace.negative, list(trace.points)) for trace in traces]
    section.selected_traces = traces[::-1] if negative_first else traces

    if restricted:
        targets = section.selected_traces
        section.selected_traces = [targets[0]]
        field.mergeTraces(restrict=targets)
    else:
        field.mergeTraces()

    after = [(trace.negative, list(trace.points)) for trace in section.contours[NAME]]
    assert after == before
    assert len(notices) == 1
    assert "positive and negative" in notices[0]


@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("selected_only", [False, True])
def test_auto_merge_keeps_opposite_sign_trace(
    main_window, monkeypatch, negative, selected_only
):
    from PyReconstruct.modules.gui.main import field_widget_2_trace as fw2

    notices = []
    monkeypatch.setattr(fw2, "notify", lambda message: notices.append(message))
    field = main_window.field
    main_window.series.setOption("auto_merge", True)
    main_window.series.setOption("auto_merge_selected_only", selected_only)
    same_sign = Trace(NAME, (0, 255, 0), True)
    same_sign.negative = negative
    opposite_sign = same_sign.copy()
    opposite_sign.negative = not negative
    field.setTracingTrace(same_sign)
    for points, base in ((OUTER, same_sign), (HOLE, opposite_sign)):
        field.newTrace(
            points, base, points_as_pix=False,
            reduce_points=False, log_event=False,
        )
    opposite = field.section.contours[NAME][-1]
    opposite_points = list(opposite.points)
    if not selected_only:
        field.section.selected_traces = []
    extension = [(x + 0.5, y) for x, y in OUTER]
    field.newTrace(
        extension, same_sign, points_as_pix=False,
        reduce_points=False, log_event=False,
    )

    field.autoMerge()

    traces = list(field.section.contours[NAME])
    assert len(traces) == 2
    assert opposite in traces
    assert opposite.points == opposite_points
    merged = next(trace for trace in traces if trace is not opposite)
    assert merged.negative == negative
    assert merged.getBounds(field.section.tform) == pytest.approx(
        (0, 0, 1.5, 1), abs=0.001
    )
    assert not notices


@pytest.mark.parametrize("negative", [False, True])
def test_same_sign_manual_merge_keeps_sign(main_window, negative):
    field = main_window.field
    base = Trace(NAME, (0, 255, 0), True)
    base.negative = negative
    for points in (OUTER, [(x + 0.5, y) for x, y in OUTER]):
        field.newTrace(
            points, base, points_as_pix=False,
            reduce_points=False, log_event=False,
        )
    field.section.selected_traces = list(field.section.contours[NAME])

    field.mergeTraces()

    traces = list(field.section.contours[NAME])
    assert len(traces) == 1
    assert traces[0].negative == negative
    assert traces[0].getBounds(field.section.tform) == pytest.approx(
        (0, 0, 1.5, 1), abs=0.001
    )


@pytest.mark.parametrize("negative_first", [False, True])
def test_attribute_merge_preserves_mixed_sign_geometry(main_window, negative_first):
    field = main_window.field
    for points, negative, color in (
        (OUTER, False, (255, 0, 0)),
        (HOLE, True, (0, 0, 255)),
    ):
        base = Trace(NAME, color, True)
        base.negative = negative
        field.newTrace(
            points, base, points_as_pix=False,
            reduce_points=False, log_event=False,
        )
    traces = list(field.section.contours[NAME])
    before = [(trace.negative, list(trace.points)) for trace in traces]
    field.section.selected_traces = traces[::-1] if negative_first else traces
    expected_color = tuple(field.section.selected_traces[0].color)

    field.mergeTraces(merge_attrs_only=True)

    after = list(field.section.contours[NAME])
    assert sorted((trace.negative, list(trace.points)) for trace in after) == before
    assert [tuple(trace.color) for trace in after] == [expected_color, expected_color]
