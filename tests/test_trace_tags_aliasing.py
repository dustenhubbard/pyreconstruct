"""Regression tests for traces sharing one mutable ``tags`` set.

Bug: the replace branch of ``Section.editTraceAttributes`` assigned the
caller's ``tags`` argument itself, once per loop iteration::

    new_trace.tags = tags

so editing N traces left all N holding the SAME set object, and the caller's
object at that. Tags are mutated in place elsewhere (``Trace.addTag`` is
``self.tags.add(tag)``, and ``Section.importTraces`` calls
``trace.tags.add(...)`` when it flags import conflicts), so adding one tag to
one trace afterwards silently added it to every other trace edited in the same
call.

``Trace.copy`` already does ``copy_trace.tags = self.tags.copy()`` for this
reason, which makes the invariant the codebase's own: a trace owns its tags set.
The replace branch was the one place that broke it.

The caller's set is aliased too, and two callers hand over a set they keep
using: ``pasteAttributes`` passes the clipboard trace's own ``trace.tags``, and
``mergeSelectedTraces(merge_attrs_only=True)`` passes ``first_trace.tags``.
There a later in-place add on any edited trace would also reach back into the
clipboard.

Fix: ``new_trace.tags = set(tags)``, inside the method, so every caller gets the
guarantee without having to know about it.
"""
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.section import Section


def _trace(name, tags=()):
    t = Trace(name, (255, 0, 0))
    t.points = [(0, 0), (1, 0), (1, 1)]
    t.tags = set(tags)
    return t


def _bare_section():
    """A Section with no backing files.

    ``Section.__init__`` reads its section file off disk, so it cannot be
    constructed here. ``editTraceAttributes`` touches only ``contours``, the
    tracking lists and ``selected_traces`` once ``log_event=False`` rules out
    the log call. Same approach as ``test_mixed_selection_tag_wipe.py``.
    """
    section = Section.__new__(Section)
    section.n = 0
    section.contours = {}
    section.added_traces = []
    section.removed_traces = []
    section.selected_traces = []
    return section


def _edited(section, name="a"):
    return section.contours[name].getTraces()


def test_replaced_tags_are_not_shared_between_traces():
    """The bug. Three traces, one in-place add, the other two must not see it."""
    section = _bare_section()
    for tags in ({"x"}, {"y"}, {"z"}):
        section.addTrace(_trace("a", tags), log_event=False)

    section.editTraceAttributes(
        section.contours["a"].getTraces(),
        name=None, color=None, tags={"shared"}, mode=None, log_event=False,
    )

    traces = _edited(section)
    assert len(traces) == 3
    assert all(t.tags == {"shared"} for t in traces)

    # distinct objects, so no in-place edit can travel between them
    assert len({id(t.tags) for t in traces}) == 3

    traces[0].addTag("only-first")

    assert traces[0].tags == {"shared", "only-first"}
    assert traces[1].tags == {"shared"}, "tag leaked to a second trace"
    assert traces[2].tags == {"shared"}, "tag leaked to a third trace"


def test_callers_set_is_copied_not_adopted():
    """``pasteAttributes`` hands over the clipboard trace's own ``tags``.

    Adopting it would let a later edit of any pasted trace write back into the
    clipboard, and into every other trace pasted from it.
    """
    section = _bare_section()
    for _ in range(2):
        section.addTrace(_trace("a"), log_event=False)

    clipboard = _trace("a", {"from-clipboard"})

    section.editTraceAttributes(
        section.contours["a"].getTraces(),
        name=None, color=None, tags=clipboard.tags, mode=None, log_event=False,
    )

    traces = _edited(section)
    assert all(t.tags is not clipboard.tags for t in traces)

    traces[0].addTag("added-later")
    assert clipboard.tags == {"from-clipboard"}, "edit reached the clipboard trace"
    assert traces[1].tags == {"from-clipboard"}


def test_empty_replacement_sets_are_independent():
    """``removeAllTraceTags`` passes one ``set()`` for every trace it clears."""
    section = _bare_section()
    for tags in ({"x"}, {"y"}):
        section.addTrace(_trace("a", tags), log_event=False)

    section.editTraceAttributes(
        section.contours["a"].getTraces(),
        name=None, color=None, tags=set(), mode=None, log_event=False,
    )

    traces = _edited(section)
    assert all(t.tags == set() for t in traces)

    traces[0].addTag("regrown")
    assert traces[1].tags == set(), "a cleared trace picked up another's new tag"


def test_add_tags_branch_stays_per_trace():
    """The ``add_tags=True`` branch was already correct. Pin it."""
    section = _bare_section()
    for tags in ({"x"}, {"y"}):
        section.addTrace(_trace("a", tags), log_event=False)

    incoming = {"common"}
    section.editTraceAttributes(
        section.contours["a"].getTraces(),
        name=None, color=None, tags=incoming, mode=None,
        add_tags=True, log_event=False,
    )

    traces = _edited(section)
    assert sorted(sorted(t.tags) for t in traces) == [
        ["common", "x"], ["common", "y"],
    ]
    assert incoming == {"common"}, "the caller's set was mutated"


def test_sections_do_not_share_a_tags_set():
    """``Series.editObjAttributes`` reuses one ``tags`` set across sections."""
    sections = [_bare_section(), _bare_section()]
    for i, section in enumerate(sections):
        section.n = i
        section.addTrace(_trace("a"), log_event=False)

    tags = {"bulk"}
    for section in sections:
        section.editTraceAttributes(
            section.contours["a"].getTraces(),
            name=None, color=None, tags=tags, mode=None, log_event=False,
        )

    first = _edited(sections[0])[0]
    second = _edited(sections[1])[0]
    assert first.tags is not second.tags

    first.addTag("section-0-only")
    assert second.tags == {"bulk"}, "tag leaked across sections"
    assert tags == {"bulk"}, "the caller's set was mutated"
