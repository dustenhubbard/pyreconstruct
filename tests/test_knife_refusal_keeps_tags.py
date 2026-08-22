"""A refused cut must not rewrite the tags of the trace it refused to cut.

`cutTrace` combines the tags of every selected trace onto the first one, in
place, before it has decided whether the cut can happen at all. Three refusals
sit after that combine (a self-intersecting outline, a degenerate knife
stroke, a threshold that discards every piece), and each of them tells the
user the object was left unchanged. It was not: the first selected trace had
already absorbed the other traces' tags, so a tag the user had just deleted
from that trace came back the moment a cut was refused.

The combine itself is intended on the success path: the pieces a cut creates
are built from the first trace and are supposed to carry every selected
trace's tags. That behavior is pinned here so the fix cannot change it.

Driven on a real `MainWindow` through the real `cutTrace`, over the fixture
series, the same way `test_knife_cut_guards.py` does.
"""

import pytest

pytestmark = pytest.mark.gui

from shapely.geometry import Polygon

from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.gui.main.field_widget_5_mouse import KNIFE


# the object both traces belong to; the name is the knife's single-object unit
TAGGED = "test_tagcut"


@pytest.fixture
def field_notices(monkeypatch):
    """Record what `notify` would have shown from `field_widget_2_trace`.

    Same reason as in test_knife_cut_guards.py: the module binds `notify` in
    its own namespace, and offscreen the real one falls through to `input()`.
    """
    from PyReconstruct.modules.gui.main import field_widget_2_trace

    notices = []
    monkeypatch.setattr(
        field_widget_2_trace,
        "notify",
        lambda message, *a, **kw: notices.append(message),
    )
    return notices


@pytest.fixture
def knife_field(main_window, main_window_dialogs, local_series_settings):
    """The window's field, in knife mode, over the fixture series."""
    local_series_settings(main_window)
    main_window.field.setMouseMode(KNIFE)
    return main_window.field


def _bbox_of(field, name):
    points = [tuple(p) for p in field.section.contours[name][0].points]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _square(x0, y0, side, tags=()):
    t = Trace(TAGGED, (0, 255, 0), closed=True)
    t.points = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
    t.tags = set(tags)
    return t


def _bowtie(x0, y0, side, tags=()):
    """A closed trace whose outline crosses itself, so a cut is refused."""
    t = Trace(TAGGED, (0, 255, 0), closed=True)
    t.points = [(x0, y0), (x0 + side, y0 + side), (x0 + side, y0), (x0, y0 + side)]
    t.tags = set(tags)
    assert not Polygon(t.points).is_valid, "the fixture stopped being a bowtie"
    return t


def _scalpel_across(field, trace):
    """A knife stroke, in pixel coordinates, that crosses `trace`."""
    pix = field.section_layer.traceToPix(trace)
    xs = [p[0] for p in pix]
    ys = [p[1] for p in pix]
    mid_y = (min(ys) + max(ys)) / 2
    left, right = min(xs) - 10, max(xs) + 10
    steps = 20
    return [(left + (right - left) * i / steps, mid_y) for i in range(steps + 1)]


def _two_traces(field, first_valid):
    """Two same-name closed traces where the field is looking.

    The first carries no tags (the user just deleted them); the second still
    carries "spine". `first_valid` decides whether the first is cuttable or a
    bowtie that forces a refusal.
    """
    # place them inside an existing object's bounding box so they are on screen
    x0, y0, x1, y1 = _bbox_of(field, "d03sp14")
    side = (x1 - x0) / 3

    make_first = _square if first_valid else _bowtie
    first = make_first(x0, y0, side)
    second = _square(x0 + 2 * side, y0, side, tags={"spine"})

    field.section.addTrace(first, log_event=False)
    field.section.addTrace(second, log_event=False)
    field.section.selected_traces = [first, second]
    return first, second


def test_a_refused_cut_leaves_the_first_traces_tags_alone(
    knife_field, field_notices
):
    """The reported reappearance: delete a tag, cut, be refused, tag is back."""
    field = knife_field
    first, second = _two_traces(field, first_valid=False)

    result = field.cutTrace(_scalpel_across(field, first))

    assert result is False
    assert len(field_notices) == 1, "the refusal must still be visible"
    assert first.tags == set(), (
        "the refusal said the object was left unchanged, but the first "
        "selected trace absorbed another trace's tags"
    )
    assert second.tags == {"spine"}


def test_a_completed_cut_still_unions_the_selections_tags(
    knife_field, field_notices
):
    """The pinned success path: pieces carry every selected trace's tags."""
    field = knife_field
    first, _ = _two_traces(field, first_valid=True)

    result = field.cutTrace(_scalpel_across(field, first))

    assert result is True
    assert field_notices == []
    pieces = field.section.contours[TAGGED].getTraces()
    assert pieces, "the cut produced no traces at all"
    assert all(p.tags == {"spine"} for p in pieces)
