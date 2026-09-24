"""A tag set in the attribute dialog stays on the traces it was set on.

The review on upstream PR #129 reported that setting tags in the trace list
also applied the tag to traces drawn afterward in the field, when only the
palette should decide a new trace's tags. Two ways that could happen were
found while reading: the edited traces and the caller sharing one mutable set
(fixed, pinned in test_trace_tags_aliasing.py), and auto-merge joining a new
closed trace onto a still-selected same-name trace and taking the union of
their tags (auto-merge is selected-only by default since PR #414).

This file pins the reported symptom end to end on a live window: edit tags
through the dialog, deselect, draw the next trace, and the new trace carries
only the palette's tags. It runs with tag sets on the series, so the pick-one
rows and the per-trace resolve path are the ones under test.
"""
import pytest

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.tag_sets import TagSets
from PyReconstruct.modules.gui.main import field_widget_2_trace

pytestmark = pytest.mark.gui

NAME = "leak_probe"
SQ_FIRST = [(100, 300), (200, 300), (200, 200), (100, 200)]
SQ_OVERLAPPING = [(150, 350), (250, 350), (250, 250), (150, 250)]
SQ_DISJOINT = [(500, 800), (600, 800), (600, 700), (500, 700)]

SETS = TagSets({
    "Protrusion type": {"mode": "one", "tags": ["spine", "shaft"]},
    "Qualifiers": {"mode": "many", "tags": ["estimated"]},
})


class _Answering:
    """Stands in for TraceDialog: the user picks "spine" and types "estimated"."""

    def __init__(self, parent, *args, **kwargs):
        self.tag_choices = {"Protrusion type": "spine"}

    def exec(self):
        answer = Trace(None, None, None)
        answer.name = None
        answer.color = None
        answer.tags = {"estimated"}
        answer.points = None
        answer.fill_mode = (None, None)
        return answer, True


@pytest.fixture
def field(main_window, monkeypatch):
    monkeypatch.setattr(field_widget_2_trace, "TraceDialog", _Answering)
    main_window.series.tag_sets = SETS.copy()
    main_window.series.setOption("auto_merge", True)
    main_window.series.setOption("auto_merge_selected_only", True)
    field = main_window.field
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    return field


def _draw(field, pix_points):
    """Draw a closed trace the way pencilRelease/lineRelease do."""
    field.newTrace(pix_points, field.tracing_trace, closed=True)
    field.autoMerge()


def _contour(field):
    return list(field.section.contours.get(NAME, []))


@pytest.mark.parametrize("next_square", [SQ_DISJOINT, SQ_OVERLAPPING])
def test_tags_set_in_the_dialog_do_not_reach_the_next_drawn_trace(field, next_square):
    _draw(field, SQ_FIRST)
    first = _contour(field)[0]
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(first)

    field.traceDialog()

    edited = _contour(field)
    assert len(edited) == 1
    assert edited[0].tags == {"spine", "estimated"}

    # the user clicks away, then draws the next trace of the same object
    field.section.selected_traces.clear()
    assert field.tracing_trace.tags == set(), "the palette trace was never touched"

    _draw(field, next_square)

    traces = _contour(field)
    assert len(traces) == 2, "nothing was selected, so nothing merged"
    new = [t for t in traces if t.tags != {"spine", "estimated"}]
    assert len(new) == 1
    assert new[0].tags == set(), "the new trace carries only the palette's tags"
    assert field.tracing_trace.tags == set()


def test_edited_traces_do_not_share_a_set_with_the_palette_trace(field):
    _draw(field, SQ_FIRST)
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(_contour(field)[0])

    field.traceDialog()

    edited = _contour(field)[0]
    edited.tags.add("later")
    assert "later" not in field.tracing_trace.tags
