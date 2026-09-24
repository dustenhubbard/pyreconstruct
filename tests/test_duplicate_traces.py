"""``Series.findDuplicateTraces``: one structure traced more than once.

The same-name case and the cross-name case are one scan here. Upstream's
``Series.deleteDuplicateTraces`` draws both traces of a candidate out of a single
``section.contours[cname]``, and contours are keyed by trace name, so two people
tracing one structure under two names produce a duplicate it never compares.
Nothing in the comparison itself reads a name -- ``Trace.overlaps`` is purely
geometric -- so scanning across names finds both cases at once, and that is what
the review list offers.

Overlapping traces are reported as GROUPS rather than pairs, transitively: A-B
and B-C put all three in one group. A duplicate is a claim about one structure,
and a chain of overlaps is one structure, so it is one row and one decision.

The scan never modifies. Combining is a separate call the review list makes after
the user has chosen which trace to keep, because which name is right is a
question about the data rather than about geometry.

``_duplicatePairs`` is where the cost lives, since comparing across names means
comparing every trace on a section against every other. Two filters keep the
number of measured overlap ratios proportional to the trace count rather than to
its square, and ``test_the_filtered_scan_agrees_with_brute_force`` is the test
that matters most here: the filters are only allowed to be faster, never to
change an answer.
"""

import pytest

from PyReconstruct.modules.datatypes.trace import Trace


def _trace(points, closed=True, name="t"):
    t = Trace(name, (255, 0, 0), closed=closed)
    t.points = list(points)
    return t


def _template(section):
    for cname in section.contours:
        for trace in section.contours[cname]:
            if trace.closed and len(trace.points) >= 3:
                return trace
    pytest.skip("no closed trace in the fixture section")


def _add(series, snum, name, points, closed=True, tags=()):
    section = series.loadSection(snum)
    template = _template(section)
    trace = Trace(name, template.color, closed=closed)
    trace.points = list(points)
    trace.tags = set(tags)
    section.addTrace(trace, log_event=False)
    section.save()


def _square(cx, cy, half):
    return [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]


def _first_section(series):
    return sorted(series.sections.keys())[0]


def _groups(records):
    """The reported groups as name sets, so row order never matters."""
    return {frozenset(r["names"]) for r in records}


def _group_with(records, names):
    """The single group whose names are exactly ``names``."""
    wanted = frozenset(names)
    found = [r for r in records if frozenset(r["names"]) == wanted]
    assert len(found) == 1, f"expected one {wanted} group, got {len(found)}"
    return found[0]


# --------------------------------------------------------------------------
# what the scan finds
# --------------------------------------------------------------------------

def test_one_shape_under_two_names_is_found(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape)
    _add(real_series, snum, "d01", shape)

    found = real_series.findDuplicateTraces(0.95)

    assert frozenset(("dendrite", "d01")) in _groups(found)


def test_two_traces_of_one_name_are_found_by_the_same_scan(real_series):
    """The case the old per-contour pass handled, now reported here too.

    This is the collapse: the user asks "are there duplicates", not "are there
    duplicates that happen to share a name".
    """
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "twice", shape)
    _add(real_series, snum, "twice", shape)

    group = _group_with(real_series.findDuplicateTraces(0.95), ("twice",))

    assert group["count"] == 2
    assert group["keep"] == "twice"


def test_a_point_for_point_match_reports_a_ratio_of_one(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape)
    _add(real_series, snum, "d01", shape)

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("dendrite", "d01")
    )

    assert group["ratio"] == 1.0


def test_nearly_identical_shapes_are_found_by_their_overlap_ratio(real_series):
    """Not the same points, so the ratio has to do the work.

    The offset has to clear ``POINTS_MATCH_TOLERANCE``, or ``pointsMatch``
    settles the pair first and the ratio is never measured.
    """
    snum = _first_section(real_series)
    offset = Trace.POINTS_MATCH_TOLERANCE * 2
    _add(real_series, snum, "dendrite", _square(20, 20, 1.0))
    _add(real_series, snum, "d01", _square(20 + offset, 20 + offset, 1.0))

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("dendrite", "d01")
    )

    assert group["ratio"] < 1.0


def test_different_shapes_are_not_reported(real_series):
    snum = _first_section(real_series)
    _add(real_series, snum, "one", _square(20, 20, 1.0))
    _add(real_series, snum, "two", _square(40, 40, 1.0))

    found = _groups(real_series.findDuplicateTraces(0.95))

    assert frozenset(("one", "two")) not in found


def test_merely_touching_neighbors_are_not_reported(real_series):
    """Two autosegmented neighbors share a boundary without being duplicates."""
    snum = _first_section(real_series)
    _add(real_series, snum, "left", _square(20, 20, 1.0))
    _add(real_series, snum, "right", _square(21.9, 20, 1.0))

    found = _groups(real_series.findDuplicateTraces(0.95))

    assert frozenset(("left", "right")) not in found


def test_the_threshold_is_honored(real_series):
    snum = _first_section(real_series)
    _add(real_series, snum, "a", _square(20, 20, 1.0))
    _add(real_series, snum, "b", _square(20.5, 20, 1.0))

    pair = frozenset(("a", "b"))
    strict = _groups(real_series.findDuplicateTraces(0.95))
    loose = _groups(real_series.findDuplicateTraces(0.1))

    assert pair not in strict
    assert pair in loose


def test_open_and_closed_traces_never_pair(real_series):
    """As in Trace.overlaps, which refuses the comparison outright."""
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "closed_one", shape, closed=True)
    _add(real_series, snum, "open_one", shape, closed=False)

    found = _groups(real_series.findDuplicateTraces(0.1))

    assert frozenset(("closed_one", "open_one")) not in found


def test_locked_objects_are_left_out(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape)
    _add(real_series, snum, "d01", shape)
    real_series.setAttr("d01", "locked", True)

    pair = frozenset(("dendrite", "d01"))
    assert pair not in _groups(real_series.findDuplicateTraces(0.95))
    assert pair in _groups(
        real_series.findDuplicateTraces(0.95, include_locked=True)
    )


def test_zero_area_traces_are_settled_on_points_and_do_not_raise(real_series):
    """Both filters reason about area, so a shape with none must bypass them."""
    snum = _first_section(real_series)
    line = [(60, 60), (61, 60), (62, 60)]
    _add(real_series, snum, "flat_a", line)
    _add(real_series, snum, "flat_b", line)

    found = _groups(real_series.findDuplicateTraces(0.95))

    assert frozenset(("flat_a", "flat_b")) in found


# --------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------

def test_three_traces_of_one_structure_are_one_group(real_series):
    """Three pairs, one structure, one decision to make about it."""
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    for name in ("aaa", "bbb", "ccc"):
        _add(real_series, snum, name, shape)

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("aaa", "bbb", "ccc")
    )

    assert group["count"] == 3
    assert len(group["members"]) == 3


def test_grouping_is_transitive_across_a_chain(real_series):
    """A overlaps B and B overlaps C, but A and C do not clear the threshold.

    A chain of overlaps is still one structure, so the three belong in one group
    rather than in two overlapping pairs the user has to reconcile by hand.
    """
    snum = _first_section(real_series)
    _add(real_series, snum, "a", _square(20.0, 20, 1.0))
    _add(real_series, snum, "b", _square(20.4, 20, 1.0))
    _add(real_series, snum, "c", _square(20.8, 20, 1.0))

    # a threshold the neighbors clear and the ends do not
    a, b, c = (_trace(_square(x, 20, 1.0)) for x in (20.0, 20.4, 20.8))
    assert a.overlaps(b, threshold=0.6) is True
    assert a.overlaps(c, threshold=0.6) is False

    group = _group_with(real_series.findDuplicateTraces(0.6), ("a", "b", "c"))

    assert group["count"] == 3


def test_two_separate_structures_stay_two_groups(real_series):
    snum = _first_section(real_series)
    _add(real_series, snum, "near_a", _square(20, 20, 1.0))
    _add(real_series, snum, "near_b", _square(20, 20, 1.0))
    _add(real_series, snum, "far_a", _square(60, 60, 1.0))
    _add(real_series, snum, "far_b", _square(60, 60, 1.0))

    found = _groups(real_series.findDuplicateTraces(0.95))

    assert frozenset(("near_a", "near_b")) in found
    assert frozenset(("far_a", "far_b")) in found


def test_the_group_reports_the_weakest_overlap_in_the_chain(real_series):
    """The user is told the least confident link, not the most confident one."""
    snum = _first_section(real_series)
    _add(real_series, snum, "a", _square(20.0, 20, 1.0))
    _add(real_series, snum, "b", _square(20.0, 20, 1.0))   # exact match, 1.0
    _add(real_series, snum, "c", _square(20.4, 20, 1.0))   # partial

    group = _group_with(real_series.findDuplicateTraces(0.6), ("a", "b", "c"))

    assert group["ratio"] < 1.0


def test_a_lone_trace_is_never_a_group(real_series):
    snum = _first_section(real_series)
    _add(real_series, snum, "only_one", _square(20, 20, 1.0))

    assert all(
        r["count"] >= 2 for r in real_series.findDuplicateTraces(0.95)
    )


# --------------------------------------------------------------------------
# the keep default
# --------------------------------------------------------------------------

def test_the_most_detailed_trace_is_kept_by_default(real_series):
    """One careful tracing and one rough one: keeping the careful one loses least."""
    snum = _first_section(real_series)
    rough = _square(20, 20, 1.0)
    careful = [
        (19, 19), (19.5, 19), (20, 19), (20.5, 19), (21, 19),
        (21, 20), (21, 21), (20, 21), (19, 21), (19, 20),
    ]
    _add(real_series, snum, "rough", rough)
    _add(real_series, snum, "careful", careful)

    group = _group_with(
        real_series.findDuplicateTraces(0.6), ("rough", "careful")
    )

    assert group["keep"] == "careful"


def test_the_keep_default_breaks_ties_alphabetically(real_series):
    """Equal detail, so the choice has to be reproducible rather than arbitrary."""
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "zzz", shape)
    _add(real_series, snum, "aaa", shape)

    group = _group_with(real_series.findDuplicateTraces(0.95), ("aaa", "zzz"))

    assert group["keep"] == "aaa"


def test_the_keep_default_is_always_one_of_the_groups_own_names(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    for name in ("aaa", "bbb", "ccc"):
        _add(real_series, snum, name, shape)

    for group in real_series.findDuplicateTraces(0.95):
        assert group["keep"] in group["names"]


# --------------------------------------------------------------------------
# the record, and that the scan modifies nothing
# --------------------------------------------------------------------------

def test_the_record_describes_the_group_and_its_kept_member(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape)
    _add(real_series, snum, "d01", shape)

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("dendrite", "d01")
    )

    for key in (
        "name", "section", "index", "points", "location", "area", "match",
        "reason", "members", "names", "names_text", "keep", "ratio", "count",
        "total_area",
    ):
        assert key in group, f"record is missing {key}"
    # the base-class keys describe the member that combining keeps, so the
    # review list's navigation and export work on a group unchanged
    assert group["name"] == group["keep"]
    assert group["total_area"] > group["area"]
    assert group["names_text"] == "d01, dendrite"


def test_every_member_carries_what_combining_needs(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape)
    _add(real_series, snum, "d01", shape)

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("dendrite", "d01")
    )

    for member in group["members"]:
        for key in ("name", "section", "index", "match", "points", "area"):
            assert key in member, f"member is missing {key}"


@pytest.mark.parametrize("threshold", [0, 0.1, 0.5, 0.95, 1])
def test_the_scan_modifies_nothing_at_any_threshold(real_series, threshold):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape)
    _add(real_series, snum, "d01", shape)

    def snapshot():
        out = {}
        for n in sorted(real_series.sections.keys()):
            section = real_series.loadSection(n)
            out[n] = {
                c: [list(t.points) for t in section.contours[c]]
                for c in section.contours
            }
        return out

    before = snapshot()
    real_series.findDuplicateTraces(threshold)

    assert snapshot() == before


def test_the_member_order_does_not_depend_on_contour_walk_order(real_series):
    """A stable (name, index) order, so the report is reproducible."""
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "zzz", shape)
    _add(real_series, snum, "aaa", shape)

    group = _group_with(real_series.findDuplicateTraces(0.95), ("aaa", "zzz"))

    assert [m["name"] for m in group["members"]] == ["aaa", "zzz"]


# --------------------------------------------------------------------------
# combining
# --------------------------------------------------------------------------

def test_combining_leaves_one_trace_under_the_chosen_name(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape)
    _add(real_series, snum, "d01", shape)

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("dendrite", "d01")
    )
    group["keep"] = "dendrite"

    assert real_series.combineDuplicateTraces([group]) == [group]

    contours = real_series.loadSection(snum).contours
    assert len(contours["dendrite"]) == 1
    assert "d01" not in contours or len(contours["d01"]) == 0


def test_combining_honors_the_other_choice_just_as_well(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape)
    _add(real_series, snum, "d01", shape)

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("dendrite", "d01")
    )
    group["keep"] = "d01"

    real_series.combineDuplicateTraces([group])

    contours = real_series.loadSection(snum).contours
    assert len(contours["d01"]) == 1
    assert "dendrite" not in contours or len(contours["dendrite"]) == 0


def test_the_surviving_trace_takes_on_the_tags_of_the_rest(real_series):
    """A tag is not something the user asked to lose by combining duplicates."""
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape, tags=("checked",))
    _add(real_series, snum, "d01", shape, tags=("needs_review",))

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("dendrite", "d01")
    )
    group["keep"] = "dendrite"

    real_series.combineDuplicateTraces([group])

    kept = real_series.loadSection(snum).contours["dendrite"][0]
    assert kept.tags == {"checked", "needs_review"}


def test_combining_a_three_trace_group_leaves_exactly_one(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    for name in ("aaa", "bbb", "ccc"):
        _add(real_series, snum, name, shape)

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("aaa", "bbb", "ccc")
    )
    group["keep"] = "bbb"

    real_series.combineDuplicateTraces([group])

    contours = real_series.loadSection(snum).contours
    remaining = sum(
        len(contours[c]) for c in ("aaa", "bbb", "ccc") if c in contours
    )
    assert remaining == 1
    assert len(contours["bbb"]) == 1


def test_combining_a_same_name_group_collapses_it_to_one(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "twice", shape)
    _add(real_series, snum, "twice", shape)

    group = _group_with(real_series.findDuplicateTraces(0.95), ("twice",))

    assert real_series.combineDuplicateTraces([group]) == [group]
    assert len(real_series.loadSection(snum).contours["twice"]) == 1


def test_a_group_whose_traces_have_gone_is_left_alone(real_series):
    """Re-found by signature, so a stale group is skipped rather than guessed at."""
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "dendrite", shape)
    _add(real_series, snum, "d01", shape)

    group = _group_with(
        real_series.findDuplicateTraces(0.95), ("dendrite", "d01")
    )
    for member in group["members"]:
        member["match"] = {"color": (1, 2, 3), "points": [(0.0, 0.0)]}

    assert real_series.combineDuplicateTraces([group]) == []

    contours = real_series.loadSection(snum).contours
    assert len(contours["dendrite"]) == 1
    assert len(contours["d01"]) == 1


def test_combining_nothing_is_not_an_error(real_series):
    assert real_series.combineDuplicateTraces([]) == []


def test_combining_only_touches_the_groups_it_was_given(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "near_a", shape)
    _add(real_series, snum, "near_b", shape)
    _add(real_series, snum, "far_a", _square(60, 60, 1.0))
    _add(real_series, snum, "far_b", _square(60, 60, 1.0))

    found = real_series.findDuplicateTraces(0.95)
    near = _group_with(found, ("near_a", "near_b"))
    near["keep"] = "near_a"

    real_series.combineDuplicateTraces([near])

    contours = real_series.loadSection(snum).contours
    assert len(contours["far_a"]) == 1
    assert len(contours["far_b"]) == 1


# --------------------------------------------------------------------------
# point-identical traces share a signature: one object per member
# --------------------------------------------------------------------------

def test_combining_three_identical_same_name_traces_leaves_one(real_series):
    """The signature is color plus rounded points, equal for all three.

    Resolving members by signature alone handed every member the same first
    trace, so the group removed one trace twice and raised out of
    Contour.remove, mid-loop, with earlier sections already saved.
    """
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    for _ in range(3):
        _add(real_series, snum, "thrice", shape)

    group = _group_with(real_series.findDuplicateTraces(0.95), ("thrice",))
    assert group["count"] == 3

    assert real_series.combineDuplicateTraces([group]) == [group]
    assert len(real_series.loadSection(snum).contours["thrice"]) == 1


def test_identical_same_name_traces_keep_every_tag(real_series):
    """The kept trace must not be its own doomed twin.

    With one object shared between kept and doomed, mergeTags was a self-merge
    and the trace removed took its tags with it.
    """
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "twice", shape, tags=("checked",))
    _add(real_series, snum, "twice", shape, tags=("needs_review",))

    group = _group_with(real_series.findDuplicateTraces(0.95), ("twice",))
    real_series.combineDuplicateTraces([group])

    contour = real_series.loadSection(snum).contours["twice"]
    assert len(contour) == 1
    assert contour[0].tags == {"checked", "needs_review"}


def test_a_partly_stale_group_is_left_whole(real_series):
    """One member gone is not a licence to combine the others."""
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "aaa", shape)
    _add(real_series, snum, "bbb", shape)

    group = _group_with(real_series.findDuplicateTraces(0.95), ("aaa", "bbb"))
    group["keep"] = "aaa"
    # the survivor has moved on since the scan
    for member in group["members"]:
        if member["name"] == "aaa":
            member["match"] = {"color": (1, 2, 3), "points": [(0.0, 0.0)]}

    assert real_series.combineDuplicateTraces([group]) == []

    contours = real_series.loadSection(snum).contours
    assert len(contours["aaa"]) == 1
    assert len(contours["bbb"]) == 1


def test_combining_reports_which_groups_went(real_series):
    """The dialog drops rows by identity, so a count would not do."""
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "near_a", shape)
    _add(real_series, snum, "near_b", shape)
    _add(real_series, snum, "far_a", _square(60, 60, 1.0))
    _add(real_series, snum, "far_b", _square(60, 60, 1.0))

    found = real_series.findDuplicateTraces(0.95)
    near = _group_with(found, ("near_a", "near_b"))
    far = _group_with(found, ("far_a", "far_b"))
    # far has moved on; near has not
    for member in far["members"]:
        member["match"] = {"color": (1, 2, 3), "points": [(0.0, 0.0)]}

    combined = real_series.combineDuplicateTraces([near, far])

    assert combined == [near]


# --------------------------------------------------------------------------
# the name chosen names an object, not a trace
# --------------------------------------------------------------------------

def test_the_trace_kept_is_the_detailed_one_of_the_chosen_name(real_series):
    """One object holding two traces of the group: keep the better one.

    _defaultKeepName picks the name BECAUSE of the most detailed trace, so
    keeping the first trace of that name instead deleted the very trace the
    default was chosen for.
    """
    snum = _first_section(real_series)
    rough = _square(20, 20, 1.0)
    careful = [
        (19, 19), (19.5, 19), (20, 19), (20.5, 19), (21, 19),
        (21, 20), (21, 21), (20, 21), (19, 21), (19, 20),
    ]
    # the rough one is added first, so it is index 0 of the contour
    _add(real_series, snum, "obj", rough, tags=("rough",))
    _add(real_series, snum, "obj", careful, tags=("careful",))
    _add(real_series, snum, "other", rough)

    group = _group_with(
        real_series.findDuplicateTraces(0.6), ("obj", "other")
    )
    group["keep"] = "obj"

    real_series.combineDuplicateTraces([group])

    contour = real_series.loadSection(snum).contours["obj"]
    assert len(contour) == 1
    assert len(contour[0].points) == len(careful), "kept the rough trace"


def test_the_group_record_describes_the_detailed_member(real_series):
    snum = _first_section(real_series)
    rough = _square(20, 20, 1.0)
    careful = [
        (19, 19), (19.5, 19), (20, 19), (20.5, 19), (21, 19),
        (21, 20), (21, 21), (20, 21), (19, 21), (19, 20),
    ]
    _add(real_series, snum, "obj", rough)
    _add(real_series, snum, "obj", careful)
    _add(real_series, snum, "other", rough)

    group = _group_with(
        real_series.findDuplicateTraces(0.6), ("obj", "other")
    )

    assert group["keep"] == "obj"
    assert group["points"] == len(careful)


def test_kept_member_answers_none_for_a_name_not_in_the_group(real_series):
    from PyReconstruct.modules.datatypes.series import Series

    members = [
        {"name": "a", "points": 4, "index": 0},
        {"name": "b", "points": 9, "index": 0},
    ]

    assert Series._keptMember(members, "b")["points"] == 9
    assert Series._keptMember(members, "zzz") is None


def test_a_group_whose_chosen_name_is_absent_is_skipped(real_series):
    snum = _first_section(real_series)
    shape = _square(20, 20, 1.0)
    _add(real_series, snum, "aaa", shape)
    _add(real_series, snum, "bbb", shape)

    group = _group_with(real_series.findDuplicateTraces(0.95), ("aaa", "bbb"))
    group["keep"] = "not_in_this_group"

    assert real_series.combineDuplicateTraces([group]) == []

    contours = real_series.loadSection(snum).contours
    assert len(contours["aaa"]) == 1
    assert len(contours["bbb"]) == 1


# --------------------------------------------------------------------------
# the filters are only allowed to be faster
# --------------------------------------------------------------------------

@pytest.mark.parametrize("threshold", [0.1, 0.5, 0.8, 0.95, 1])
@pytest.mark.parametrize("cross_name_only", [False, True])
def test_the_filtered_scan_agrees_with_brute_force(threshold, cross_name_only):
    """Every pair the filters skip is a pair Trace.overlaps would have refused.

    Brute force is every pair straight into ``Trace.overlaps``, which is what a
    literal rewrite of the same-name loop gives. The sweep and the ratio ceiling
    must reach the same set, under either name rule.
    """
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.calc import area

    traces = []
    # a crowd with real overlaps, near misses, and plenty of disjoint pairs
    for i in range(12):
        cx = i * 1.7
        traces.append((f"obj{i}", _square(cx, 0, 1.0)))
        traces.append((f"copy{i}", _square(cx, 0, 1.0)))          # duplicate
        traces.append((f"near{i}", _square(cx + 0.3, 0, 1.0)))    # partial
        traces.append((f"far{i}", _square(cx, 40 + i, 1.0)))      # disjoint
        # a same-name repeat, so the cross_name_only rule has something to cut
        traces.append((f"obj{i}", _square(cx, 0, 1.0)))

    entries = []
    for index, (name, points) in enumerate(traces):
        t = _trace(points, name=name)
        xmin, ymin, xmax, ymax = t.getBounds()
        entries.append(
            (xmin, ymin, xmax, ymax, abs(area(points)), name, index, t)
        )

    filtered = {
        frozenset(((a[5], a[6]), (b[5], b[6])))
        for a, b, _r, _pm in Series._duplicatePairs(
            entries, threshold, cross_name_only=cross_name_only
        )
    }

    brute = set()
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = entries[i], entries[j]
            if cross_name_only and a[5] == b[5]:
                continue
            if a[7].overlaps(b[7], threshold=threshold):
                brute.add(frozenset(((a[5], a[6]), (b[5], b[6]))))

    assert filtered == brute


def test_same_name_pairs_are_included_unless_asked_otherwise():
    """The default is the unified scan; the old rule is still available."""
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.calc import area

    entries = []
    for index, name in enumerate(("twice", "twice")):
        t = _trace(_square(0, 0, 1.0), name=name)
        xmin, ymin, xmax, ymax = t.getBounds()
        entries.append((
            xmin, ymin, xmax, ymax, abs(area(t.points)), name, index, t
        ))

    assert len(list(Series._duplicatePairs(entries, 0.95))) == 1
    assert list(
        Series._duplicatePairs(entries, 0.95, cross_name_only=True)
    ) == []


def test_a_pair_matching_within_tolerance_with_disjoint_boxes_is_found():
    """The bounding-box tests have to be slack by the point-match tolerance.

    ``Trace.pointsMatch`` calls two points the same within
    ``POINTS_MATCH_TOLERANCE`` per axis, so two traces can match point for point
    while their bounding boxes do not touch. A strict box test drops exactly the
    pairs the comparison would have called duplicates, and real data has them.
    """
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.calc import area

    offset = Trace.POINTS_MATCH_TOLERANCE * 0.6
    a_points = [(0, 0), (1, 0)]
    b_points = [(0, offset), (1, offset)]

    entries = []
    for name, points in (("a", a_points), ("b", b_points)):
        t = _trace(points, closed=False, name=name)
        xmin, ymin, xmax, ymax = t.getBounds()
        entries.append((xmin, ymin, xmax, ymax, abs(area(points)), name, 0, t))

    pairs = list(Series._duplicatePairs(entries, 0.95))

    assert len(pairs) == 1
    assert pairs[0][3] is True  # settled on points
    assert _trace(a_points, closed=False).overlaps(
        _trace(b_points, closed=False), threshold=0.95
    ) is True


# --------------------------------------------------------------------------
# the two halves extracted out of overlaps()
# --------------------------------------------------------------------------

def test_points_match_carries_the_tolerance():
    tol = Trace.POINTS_MATCH_TOLERANCE
    a = _trace([(0, 0), (1, 0), (1, 1)])

    assert a.pointsMatch(_trace([(0, tol * 0.5), (1, 0), (1, 1)])) is True
    assert a.pointsMatch(_trace([(0, tol * 2), (1, 0), (1, 1)])) is False
    assert a.pointsMatch(_trace([(0, 0), (1, 0)])) is False


@pytest.mark.parametrize("ratio, threshold, expected", [
    (0.96, 0.95, True),
    (0.95, 0.95, False),   # exclusive
    (1.0, 1, True),
    (0.999, 1, False),     # a threshold of 1 demands exactly 1
])
def test_ratio_is_overlap_matches_the_threshold_semantics(
    ratio, threshold, expected
):
    assert Trace.ratioIsOverlap(ratio, threshold) is expected


def test_overlaps_still_answers_with_a_plain_bool():
    """getOverlapRatio divides two numpy sums, so the verdict must be coerced."""
    a = _trace(_square(0, 0, 1.0))
    b = _trace(_square(0.1, 0, 1.0))

    for threshold in (0.1, 0.95, 1):
        verdict = a.overlaps(b, threshold=threshold)
        assert type(verdict) is bool, f"{threshold} gave {type(verdict)}"
