"""Auto-merge is overlap-triggered, and the whole gesture is one undo step.

Upstream issues #138 and #137.

#138 "Auto-merge when tracing in polygon mode": `autoMerge` never tested
overlap. It merged whenever two or more SELECTED closed traces shared the
tracing trace's name, so whether finishing a trace merged into the existing
same-name trace depended on whether that trace happened to be selected --
which differs between the pencil and point-to-point gestures. The trigger is
now geometric: after a closed trace is drawn, it merges with every same-name
closed trace on the section that actually overlaps it, selected or not, and
non-overlapping same-name traces are left alone (that remains the documented
way to keep separate same-name traces).

#137 "Undo following auto-merge should revert to original trace": the gesture
used to record one undo state for the draw (`newTrace`) and more for the merge
(`mergeTraces` re-creates the merged pieces through `newTrace`, then saves
again), so one Ctrl+Z landed on the intermediate state: the original trace
plus the un-merged new trace. The draw and the merge are now folded into a
single undo step, so one undo restores the section exactly as it was before
the draw and one redo reapplies the merged result.

All tests drive the real code path the mouse release handlers use
(`newTrace` followed by `autoMerge`) on a live MainWindow over the fixture
series, with the real state manager underneath.
"""
import pytest

from PyReconstruct.modules.datatypes.trace import Trace

pytestmark = pytest.mark.gui

NAME = "automerge_obj"

# pixel-space squares; the second overlaps the first, the third is far away
SQ_BASE = [(100, 300), (200, 300), (200, 200), (100, 200)]
SQ_OVERLAPPING = [(150, 350), (250, 350), (250, 250), (150, 250)]
SQ_DISJOINT = [(500, 800), (600, 800), (600, 700), (500, 700)]


def _tracing_trace(name=NAME, color=(0, 255, 0), tags=()):
    t = Trace(name, color, True)
    for tag in tags:
        t.tags.add(tag)
    return t


def _draw(field, pix_points, base_trace=None, auto_merge=True):
    """Draw a closed trace the way pencilRelease/lineRelease do."""
    if base_trace is not None:
        field.setTracingTrace(base_trace)
    field.newTrace(pix_points, field.tracing_trace, closed=True)
    if auto_merge:
        field.autoMerge()


def _contour(field):
    return field.section.contours.get(NAME, [])


@pytest.fixture
def merge_field(main_window):
    """The live field widget with the auto_merge option switched on."""
    main_window.series.setOption("auto_merge", True)
    field = main_window.field
    field.setTracingTrace(_tracing_trace())
    return field


def test_overlapping_unselected_trace_merges(merge_field):
    """#138: the merge keys on overlap, not on selection.

    The pre-existing same-name closed trace is deselected before the second
    draw -- the polygon-mode situation that used to skip the merge.
    """
    field = merge_field

    _draw(field, SQ_BASE)
    assert len(_contour(field)) == 1
    base_bounds = _contour(field)[0].getBounds()

    # deselect everything: the old trigger cannot fire now
    field.section.selected_traces = []

    _draw(field, SQ_OVERLAPPING)

    contour = _contour(field)
    assert len(contour) == 1, (
        "an overlapping same-name closed trace must be merged into the new "
        "trace even when it is not selected"
    )
    # the merged trace spans the original square and extends past it
    xmin, ymin, xmax, ymax = contour[0].getBounds()
    assert xmin <= base_bounds[0] and ymax >= base_bounds[3]
    assert xmax > base_bounds[2]


def test_disjoint_selected_trace_does_not_merge(merge_field):
    """#138: no overlap, no merge -- even when both traces are selected.

    Keeping separate same-name traces by drawing them apart is documented
    behavior, and the old selection trigger broke it: two selected same-name
    closed traces merged no matter where they were.
    """
    field = merge_field

    _draw(field, SQ_BASE)
    existing = _contour(field)[0]
    assert existing in field.section.selected_traces

    _draw(field, SQ_DISJOINT)  # newTrace selects it; both are now selected

    contour = _contour(field)
    assert len(contour) == 2, (
        "non-overlapping same-name traces must not be auto-merged, "
        "selected or not"
    )
    # untouched, not deleted-and-recreated
    assert existing in contour.getTraces()


def test_open_trace_is_never_a_merge_target(merge_field):
    """An open same-name trace overlapping the new one is left alone."""
    field = merge_field

    open_base = _tracing_trace()
    field.setTracingTrace(open_base)
    field.newTrace(SQ_BASE, field.tracing_trace, closed=False)
    field.section.selected_traces = []

    _draw(field, SQ_OVERLAPPING)

    contour = _contour(field)
    assert len(contour) == 2
    assert sorted(t.closed for t in contour) == [False, True]


def test_merged_trace_keeps_the_existing_traces_attributes(merge_field):
    """The merged result inherits the pre-existing trace's color and tags.

    The user is extending a trace that already exists; the palette's fresh
    copy must not repaint it or drop its tags. Manual merge is unchanged: it
    still takes the first selected trace's attributes.
    """
    field = merge_field

    existing_base = _tracing_trace(color=(255, 0, 0), tags=("keep_me",))
    _draw(field, SQ_BASE, base_trace=existing_base)
    field.section.selected_traces = []

    fresh_base = _tracing_trace(color=(0, 255, 0))
    _draw(field, SQ_OVERLAPPING, base_trace=fresh_base)

    contour = _contour(field)
    assert len(contour) == 1
    merged = contour[0]
    assert tuple(merged.color) == (255, 0, 0), (
        "the merged trace must keep the existing trace's color, not the "
        "palette's fresh copy"
    )
    assert "keep_me" in merged.tags
