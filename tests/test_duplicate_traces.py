"""One scan for duplicate traces, and combining what it finds.

`Series ▸ Clean up ▸ Duplicates...` replaces two items: one deleted same-name
duplicates with no list to check first, the other listed cross-name pairs. Now
`Series.findDuplicateTraces` finds overlapping traces whether the names match
or not and reports one group per structure, however many times it was traced.
`Series.combineDuplicateTraces` then combines the groups the user chose a name
for: one trace under that name survives, carrying the tags of the others, and
the rest are deleted.

What is pinned here:

  * one group per structure: same name, two names, and three tracings are each
    one group, never a pair per overlap
  * a group chains, and its ratio is the lowest of the pairs that joined it,
    which two of its traces can fall below
  * different shapes, neighbors, and open against closed are never grouped
  * the threshold is honored, and the fast path agrees with comparing every
    pair through `Trace.overlaps`, across names and within one
  * the scan changes nothing, and leaves locked objects out unless asked
  * combining keeps one trace under the chosen name with every tag of the
    group, deletes the rest, is one undo step, and reaches the disk
  * a group with no name chosen, or a name not its own, is never combined
  * a group that would delete a trace of a locked object is left whole
  * a group whose traces changed since the scan is left whole, never half done
  * the field layer saves first, refreshes every name, and says why a row was
    not combined, suggesting a locked name to keep only when keeping it works

Runs against the real shapes1.jser fixture with synthetic traces layered on, the
same way tests/test_data_cleanup.py does.
"""
import os
import shutil

import numpy as np
import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets",
    "checker", "files", "shapes1.jser",
)

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10)]


def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    series.setProgressReporter(NullProgressReporter)
    return series


def _template_trace(section):
    for cname in section.contours:
        for trace in section.contours[cname]:
            if trace.closed and len(trace.points) >= 3:
                return trace
    pytest.skip("no closed trace in fixture section")


def _make(section, name, points, closed=True, tags=None):
    t = _template_trace(section).copy()
    t.name = name
    t.points = list(points)
    t.closed = closed
    t.tags = set(tags or ())
    section.addTrace(t, log_event=False)
    return t


def _snums_with_closed(series):
    found = []
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        if any(
            trace.closed and len(trace.points) >= 3
            for cname in section.contours
            for trace in section.contours[cname]
        ):
            found.append(snum)
    if not found:
        pytest.skip("no closed trace anywhere in fixture")
    return found


def _snum_with_closed(series):
    return _snums_with_closed(series)[0]


def _seed(series, traces, snum=None):
    """Add (name, points, tags) traces to one section; return its number."""
    snum = _snum_with_closed(series) if snum is None else snum
    section = series.loadSection(snum)
    for name, points, tags in traces:
        _make(section, name, points, tags=tags)
    section.save()
    return snum


def _count(series, snum, name):
    return len(series.loadSection(snum).contours.get(name, []))


def _tags(series, snum, name):
    """The tags of each trace of an object, in contour order."""
    return [
        sorted(t.tags) for t in series.loadSection(snum).contours.get(name, [])
    ]


def _shape(group):
    """A group as the sorted names of its members, one per trace."""
    return tuple(sorted(m["name"] for m in group["members"]))


def _shapes(groups):
    return {_shape(g) for g in groups}


def _only(groups, *names):
    """The one group whose members are exactly these names."""
    wanted = tuple(sorted(names))
    matches = [g for g in groups if _shape(g) == wanted]
    assert len(matches) == 1, f"no single group {wanted}: {_shapes(groups)}"
    return matches[0]


def _shifted(points, dx, dy=0.0):
    return [(x + dx, y + dy) for x, y in points]


def _states(series):
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates
    return SeriesStates(series)


# ---------------------------------------------------------------------------
# the scan: one group per structure
# ---------------------------------------------------------------------------

def test_same_name_duplicates_are_one_group(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [("DUPE", SQUARE, ()), ("DUPE", SQUARE, ())])

    groups = series.findDuplicateTraces(0.95)

    group = _only(groups, "DUPE", "DUPE")
    assert group["section"] == snum
    assert group["names"] == ["DUPE"]
    assert group["count"] == 2


def test_duplicates_under_two_names_are_one_group(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [("TRACER_A", SQUARE, ()), ("TRACER_B", SQUARE, ())])

    group = _only(series.findDuplicateTraces(0.95), "TRACER_A", "TRACER_B")

    assert group["names"] == ["TRACER_A", "TRACER_B"]
    assert group["section"] == snum
    assert group["ratio"] == 1.0  # same points


def test_a_structure_traced_three_times_is_one_group(tmp_path):
    """Three tracings make three overlapping pairs and still one row."""
    series = _load_series(tmp_path)
    _seed(series, [
        ("A", SQUARE, ()),
        ("B", SQUARE, ()),
        ("C", _shifted(SQUARE, 0.2), ()),
    ])

    groups = series.findDuplicateTraces(0.95)

    assert _shapes(groups) == {("A", "B", "C")}
    assert _only(groups, "A", "B", "C")["count"] == 3


def test_a_chained_group_reports_its_lowest_joining_pair(tmp_path):
    """A over B and B over C is one group though A and C fall short, and the
    ratio is the lower of A-B and B-C, not A-C. The Duplicates help text says
    exactly this about the Overlap column; change one, change the other."""
    threshold = 0.95
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, ()),
        ("B", _shifted(SQUARE, 0.2), ()),
        ("C", _shifted(SQUARE, 0.4), ()),
    ])
    section = series.loadSection(snum)
    a, b, c = (section.contours[name][0] for name in ("A", "B", "C"))
    ab = a.getOverlapRatio(b, section.mag)
    bc = b.getOverlapRatio(c, section.mag)
    ac = a.getOverlapRatio(c, section.mag)
    assert min(ab, bc) > threshold > ac, "premise: a chain, not a clique"

    group = _only(series.findDuplicateTraces(threshold), "A", "B", "C")

    assert group["ratio"] == pytest.approx(min(ab, bc))
    assert group["ratio"] > ac


def test_both_kinds_of_duplicate_land_in_one_group(tmp_path):
    """`A` twice and `B` once over one structure: one group, three traces."""
    series = _load_series(tmp_path)
    _seed(series, [("A", SQUARE, ()), ("A", SQUARE, ()), ("B", SQUARE, ())])

    group = _only(series.findDuplicateTraces(0.95), "A", "A", "B")

    assert group["names"] == ["A", "B"]
    assert group["count"] == 3


def test_two_structures_on_one_section_are_two_groups(tmp_path):
    series = _load_series(tmp_path)
    far = _shifted(SQUARE, 200.0, 200.0)
    _seed(series, [
        ("A", SQUARE, ()), ("B", SQUARE, ()),
        ("C", far, ()), ("C", far, ()),
    ])

    assert _shapes(series.findDuplicateTraces(0.95)) == {
        ("A", "B"), ("C", "C"),
    }


def test_each_member_carries_what_combining_needs(tmp_path):
    """A member names its trace by index, signature and saved identity."""
    from PyReconstruct.modules.datatypes.series import Series
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ()), ("B", SQUARE, ())])

    group = _only(series.findDuplicateTraces(0.95), "A", "B")

    section = series.loadSection(snum)
    for member in group["members"]:
        assert member["section"] == snum
        assert member["points"] == 4
        assert member["area"] > 0
        assert member["lookalikes"] == 1
        assert member["lookalike_ordinal"] == 0
        trace = section.contours[member["name"]][member["index"]]
        assert Series._traceMatchesSignature(trace, member["match"])
    assert group["location"] == group["members"][0]["location"]


def test_identical_traces_under_one_name_are_counted(tmp_path):
    series = _load_series(tmp_path)
    _seed(series, [
        ("A", SQUARE, ("same",)),
        ("A", SQUARE, ("same",)),
        ("A", SQUARE, ("tagged differently",)),
    ])

    group = _only(series.findDuplicateTraces(0.95), "A", "A", "A")

    members = sorted(group["members"], key=lambda m: m["index"])
    assert [m["lookalikes"] for m in members] == [2, 2, 1]
    assert [m["lookalike_ordinal"] for m in members] == [0, 1, 0]


def test_nearly_identical_shapes_are_found(tmp_path):
    series = _load_series(tmp_path)
    _seed(series, [("A", SQUARE, ()), ("B", _shifted(SQUARE, 1.0), ())])

    groups = series.findDuplicateTraces(0.5)

    assert _shapes(groups) == {("A", "B")}
    assert 0.5 < groups[0]["ratio"] < 1.0


def test_different_shapes_are_not_grouped(tmp_path):
    series = _load_series(tmp_path)
    _seed(series, [
        ("SMALL", SQUARE, ()),
        ("FAR", _shifted(SQUARE, 500.0, 500.0), ()),
        # overlapping, under the same name and under another, but far bigger
        ("BIG", [(0, 0), (40, 0), (40, 40), (0, 40)], ()),
        ("SMALL", [(0, 0), (30, 0), (30, 30), (0, 30)], ()),
    ])

    # the fixture's own traces are not duplicates of these
    names = {"SMALL", "FAR", "BIG"}
    assert not [
        g for g in series.findDuplicateTraces(0.95) if set(g["names"]) & names
    ]


def test_partially_overlapping_neighbors_are_not_grouped(tmp_path):
    series = _load_series(tmp_path)
    _seed(series, [
        ("LEFT", SQUARE, ()), ("RIGHT", _shifted(SQUARE, 9.5), ()),
        ("LEFT", _shifted(SQUARE, 9.5), ()),
    ])

    assert ("LEFT", "RIGHT") in _shapes(series.findDuplicateTraces(0.95))
    assert ("LEFT", "LEFT") not in _shapes(series.findDuplicateTraces(0.95))


def test_threshold_is_honored(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ()), ("A", _shifted(SQUARE, 1.0), ())])

    section = series.loadSection(snum)
    a, b = section.contours["A"][0], section.contours["A"][1]
    ratio = a.getOverlapRatio(b)
    assert 0 < ratio < 1, "premise: the pair overlaps partially"

    assert ("A", "A") not in _shapes(
        series.findDuplicateTraces(min(ratio * 1.01, 0.999))
    )
    assert ("A", "A") in _shapes(series.findDuplicateTraces(ratio * 0.99))


def test_open_and_closed_traces_never_group(tmp_path):
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "SHAPE", SQUARE, closed=True)
    _make(section, "SHAPE", list(SQUARE), closed=False)
    section.save()

    assert ("SHAPE", "SHAPE") not in _shapes(series.findDuplicateTraces(0.95))


def test_distinct_collinear_traces_are_not_grouped_and_do_not_raise(tmp_path):
    """Two different traces on one line have no area and are not duplicates."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "DUST", [(0, 0), (0, 10)], closed=False)
    _make(section, "DUST", [(0, 2), (0, 8)], closed=False)
    _make(section, "SPECK", [(4, 0), (4, 4), (4, 8)])
    _make(section, "SPECK", [(4, 1), (4, 3), (4, 9)])
    section.save()

    shapes = _shapes(series.findDuplicateTraces(0.95))
    assert ("DUST", "DUST") not in shapes
    assert ("SPECK", "SPECK") not in shapes


def test_identical_collinear_traces_are_grouped(tmp_path):
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    line = [(0, 0), (0, 5), (0, 10)]
    _make(section, "LINE_A", line, closed=False)
    _make(section, "LINE_B", list(line), closed=False)
    _make(section, "LINE_C", [(0, 20), (0, 24), (0, 30)], closed=False)
    section.save()

    assert ("LINE_A", "LINE_B") in _shapes(series.findDuplicateTraces(0.95))
    assert not any(
        "LINE_C" in g["names"] for g in series.findDuplicateTraces(0.95)
    )


def test_matching_within_tolerance_with_disjoint_boxes_is_found(tmp_path):
    """Boxes that miss each other by less than the point tolerance still group."""
    from PyReconstruct.modules.datatypes.trace import Trace
    gap = Trace.POINTS_MATCH_TOLERANCE * 0.6

    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    line = [(17.7051743, 18.4915389), (17.707118, 18.4895568)]
    _make(section, "NEAR", line, closed=False)
    _make(section, "NEAR", _shifted(line, gap * 0.2, gap), closed=False)
    section.save()

    section = series.loadSection(snum)
    a, b = section.contours["NEAR"][0], section.contours["NEAR"][1]
    assert a.pointsMatch(b) is True, "premise: inside the point tolerance"
    assert a.getBounds()[3] < b.getBounds()[1], "premise: disjoint in y"

    assert ("NEAR", "NEAR") in _shapes(series.findDuplicateTraces(0.95))


def test_an_open_pair_under_one_name_is_found(tmp_path):
    """Near-straight open profiles 0.3% apart in length, under one name."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    t = np.linspace(0, 1, 30)
    a = list(zip((0.25 * t).tolist(), (0.05 + 0.001 * np.sin(3 * t)).tolist()))
    u = np.linspace(0, 1, 23)
    b = list(zip((0.2508 * u).tolist(),
                 (0.0502 + 0.001 * np.sin(3 * u)).tolist()))
    _make(section, "CFA", a, closed=False)
    _make(section, "CFA", b, closed=False)
    section.save()

    assert ("CFA", "CFA") in _shapes(series.findDuplicateTraces(0.95))


# ---------------------------------------------------------------------------
# the scan changes nothing, and the lock
# ---------------------------------------------------------------------------

def test_the_scan_never_modifies_the_series(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ()), ("A", SQUARE, ()),
                          ("B", SQUARE, ())])

    before = {
        c: len(t) for c, t in series.loadSection(snum).contours.items()
    }
    series.findDuplicateTraces(0.01)
    after = {
        c: len(t) for c, t in series.loadSection(snum).contours.items()
    }
    assert after == before


def test_locked_objects_are_left_out_unless_asked(tmp_path):
    series = _load_series(tmp_path)
    _seed(series, [("A", SQUARE, ()), ("B", SQUARE, ()), ("B", SQUARE, ())])
    series.setAttr("B", "locked", True)

    assert not [
        g for g in series.findDuplicateTraces(0.95) if "B" in g["names"]
    ]
    assert ("A", "B", "B") in _shapes(
        series.findDuplicateTraces(0.95, include_locked=True)
    )


# ---------------------------------------------------------------------------
# the fast path finds exactly what brute force finds
# ---------------------------------------------------------------------------

def _brute_force(section, series, threshold):
    """Groups from every unordered pair, straight into Trace.overlaps."""
    flat = []
    for cname in section.contours:
        if series.getAttr(cname, "locked"):
            continue
        for index, trace in enumerate(section.contours[cname]):
            if trace.points:
                flat.append(((cname, index), trace))
    parent = {key: key for key, _ in flat}

    def find(key):
        while parent[key] != key:
            key = parent[key]
        return key

    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            (akey, atrace), (bkey, btrace) = flat[i], flat[j]
            if atrace.overlaps(btrace, threshold=threshold, mag=section.mag):
                parent[find(bkey)] = find(akey)
    groups = {}
    for key, _ in flat:
        groups.setdefault(find(key), []).append(key)
    return {
        tuple(sorted(groups[root])) for root in groups if len(groups[root]) > 1
    }


@pytest.mark.parametrize("threshold", [0.99, 0.95, 0.8, 0.5, 0.2])
def test_fast_path_agrees_with_brute_force(tmp_path, threshold):
    """The sweep and the ratio ceiling skip only pairs that would not have hit.

    A crowd of shapes at graded separations, half of them sharing a name, is
    grouped both ways at five thresholds, member for member.
    """
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    for i, dx in enumerate([0.0, 0.005, 0.2, 1.0, 2.5, 5.0, 8.0, 11.0, 30.0]):
        _make(section, f"ROW_{i % 2}", _shifted(SQUARE, dx))
    for i, side in enumerate([9.0, 10.0, 10.5, 20.0]):
        _make(section, f"SIZE_{i}",
              [(0, 0), (side, 0), (side, side), (0, side)])
    for i, dy in enumerate([0.0, 0.3, 40.0]):
        _make(section, "COL", _shifted(SQUARE, 0.0, dy))
    _make(section, "LINE_A", [(0, 0), (0, 5), (0, 10)], closed=False)
    _make(section, "LINE_B", [(0, 0), (0, 5), (0, 10)], closed=False)
    section.save()

    section = series.loadSection(snum)
    expected = _brute_force(section, series, threshold)
    got = {
        tuple(sorted((m["name"], m["index"]) for m in g["members"]))
        for g in series.findDuplicateTraces(threshold)
        if g["section"] == snum
    }
    assert got == expected


# ---------------------------------------------------------------------------
# combining
# ---------------------------------------------------------------------------

def test_combining_keeps_the_chosen_name_with_every_tag(tmp_path):
    """The done-when line: one trace is left, with the tags of the others."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, ("a",)),
        ("B", SQUARE, ("b",)),
        ("C", SQUARE, ("c", "shared")),
    ])
    group = _only(series.findDuplicateTraces(0.95), "A", "B", "C")

    applied = series.combineDuplicateTraces(
        [(group, "B")], series_states=_states(series)
    )

    assert applied == [(group, "B")]
    assert _count(series, snum, "A") == 0
    assert _count(series, snum, "C") == 0
    assert _tags(series, snum, "B") == [["a", "b", "c", "shared"]]


def test_combining_a_same_name_group_leaves_one_trace(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("DUPE", SQUARE, ("one",)),
        ("DUPE", SQUARE, ("two",)),
        ("DUPE", _shifted(SQUARE, 0.2), ()),
    ])
    group = _only(series.findDuplicateTraces(0.95), "DUPE", "DUPE", "DUPE")

    series.combineDuplicateTraces([(group, "DUPE")])

    assert _tags(series, snum, "DUPE") == [["one", "two"]]


def test_the_most_detailed_trace_of_the_chosen_name_is_kept(tmp_path):
    """Two traces of `A` in one group: the one with more points survives."""
    detailed = [(0, 0), (5, 0), (10, 0), (10, 5), (10, 10), (0, 10)]
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, ("rough",)),
        ("A", detailed, ("careful",)),
        ("B", SQUARE, ("b",)),
    ])
    group = _only(series.findDuplicateTraces(0.95), "A", "A", "B")

    series.combineDuplicateTraces([(group, "A")])

    left = series.loadSection(snum).contours["A"]
    assert len(left) == 1
    assert len(left[0].points) == len(detailed)
    assert sorted(left[0].tags) == ["b", "careful", "rough"]


def test_combining_is_one_undo_step(tmp_path):
    """Two groups on two sections combine, and one undo puts both back."""
    series = _load_series(tmp_path)
    snums = _snums_with_closed(series)
    if len(snums) < 2:
        pytest.skip("fixture has one section with closed traces")
    first = _seed(series, [("A", SQUARE, ("a",)), ("B", SQUARE, ("b",))],
                  snums[0])
    second = _seed(series, [("C", SQUARE, ("c1",)), ("C", SQUARE, ("c2",))],
                   snums[1])
    groups = series.findDuplicateTraces(0.95)
    ab = _only(groups, "A", "B")
    cc = _only(groups, "C", "C")

    states = _states(series)
    applied = series.combineDuplicateTraces(
        [(ab, "A"), (cc, "C")], series_states=states
    )
    assert len(applied) == 2
    assert len(states.undos) == 1
    assert _tags(series, first, "A") == [["a", "b"]]
    assert _count(series, first, "B") == 0
    assert _tags(series, second, "C") == [["c1", "c2"]]

    states.undoState()

    assert _tags(series, first, "A") == [["a"]]
    assert _tags(series, first, "B") == [["b"]]
    assert _tags(series, second, "C") == [["c1"], ["c2"]]


def test_the_object_list_sees_the_combined_tags(tmp_path):
    """The series data behind the Object List's tags column is refreshed for
    the kept object, whose trace changed only in its tags."""
    series = _load_series(tmp_path)
    _seed(series, [("A", SQUARE, ("a",)), ("B", SQUARE, ("b",))])
    group = _only(series.findDuplicateTraces(0.95), "A", "B")

    series.combineDuplicateTraces([(group, "A")])

    assert series.data.getTags("A") == {"a", "b"}


def test_undo_and_redo_after_an_earlier_edit_on_the_section(tmp_path):
    """With an earlier edit on the section, undo restores only the contours
    the combine changed, so the kept contour has to be among them."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ("a",)), ("B", SQUARE, ("b",))])
    group = _only(series.findDuplicateTraces(0.95), "A", "B")
    states = _states(series)
    far = _shifted(SQUARE, 300.0, 300.0)
    for _snum, section in series.enumerateSections(
        series_states=states, section_numbers=[snum]
    ):
        _make(section, "EARLIER", far)
        section.save()

    series.combineDuplicateTraces([(group, "A")], series_states=states)
    assert _tags(series, snum, "A") == [["a", "b"]]

    states.undoState()
    assert _tags(series, snum, "A") == [["a"]]
    assert _tags(series, snum, "B") == [["b"]]
    assert _count(series, snum, "EARLIER") == 1

    states.undoState(redo=True)
    assert _tags(series, snum, "A") == [["a", "b"]]
    assert _count(series, snum, "B") == 0


def test_combined_tags_reach_the_disk(tmp_path):
    """Read back after a fresh open, so the tags are the saved bytes."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ("a",)), ("A", SQUARE, ("b",))])
    group = _only(series.findDuplicateTraces(0.95), "A", "A")

    series.combineDuplicateTraces([(group, "A")])

    from PyReconstruct.modules.datatypes.section import Section
    fresh = Section(snum, series)
    assert [sorted(t.tags) for t in fresh.contours["A"]] == [["a", "b"]]


def test_a_group_with_no_name_chosen_is_never_combined(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ()), ("B", SQUARE, ())])
    group = _only(series.findDuplicateTraces(0.95), "A", "B")

    assert series.combineDuplicateTraces([(group, None)]) == []
    assert series.combineDuplicateTraces([(group, "")]) == []
    assert series.combineDuplicateTraces([(group, "Z")]) == []

    assert _count(series, snum, "A") == 1
    assert _count(series, snum, "B") == 1


def test_only_the_chosen_groups_of_a_batch_are_combined(tmp_path):
    series = _load_series(tmp_path)
    far = _shifted(SQUARE, 200.0, 200.0)
    snum = _seed(series, [
        ("A", SQUARE, ()), ("B", SQUARE, ()),
        ("C", far, ()), ("D", far, ()),
    ])
    groups = series.findDuplicateTraces(0.95)
    ab, cd = _only(groups, "A", "B"), _only(groups, "C", "D")

    applied = series.combineDuplicateTraces([(ab, None), (cd, "D")])

    assert applied == [(cd, "D")]
    assert (_count(series, snum, "A"), _count(series, snum, "B")) == (1, 1)
    assert (_count(series, snum, "C"), _count(series, snum, "D")) == (0, 1)


def test_a_locked_object_never_loses_a_trace(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ()), ("B", SQUARE, ())])
    series.setAttr("B", "locked", True)
    group = _only(
        series.findDuplicateTraces(0.95, include_locked=True), "A", "B"
    )

    assert series.combineDuplicateTraces([(group, "A")]) == []
    assert (_count(series, snum, "A"), _count(series, snum, "B")) == (1, 1)


def test_a_locked_object_can_be_the_one_kept(tmp_path):
    """Keeping a locked trace deletes only unlocked ones, so it goes ahead."""
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ("a",)), ("B", SQUARE, ("b",))])
    series.setAttr("B", "locked", True)
    group = _only(
        series.findDuplicateTraces(0.95, include_locked=True), "A", "B"
    )

    assert series.combineDuplicateTraces([(group, "B")]) == [(group, "B")]
    assert _count(series, snum, "A") == 0
    assert _tags(series, snum, "B") == [["a", "b"]]


def test_each_deleted_trace_is_logged(tmp_path):
    """Logged as a deletion, so an import knows the trace was removed on
    purpose, and as a combine naming the trace kept. `A` keeps a trace
    elsewhere so its rows are not folded into "Delete object"."""
    from PyReconstruct.modules.datatypes.log import REMOVAL_EVENTS
    far = _shifted(SQUARE, 300.0, 300.0)
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", far, ()), ("A", SQUARE, ()), ("B", SQUARE, ()),
    ])
    group = _only(series.findDuplicateTraces(0.95), "A", "B")
    before = len(series.log_set.all_logs)

    series.combineDuplicateTraces([(group, "B")])

    new = series.log_set.all_logs[before:]
    events = {(log.obj_name, log.event) for log in new}
    assert ("A", "Delete trace(s)") in events
    assert "Delete trace(s)" in REMOVAL_EVENTS
    assert ("A", "Combine duplicate traces (kept 'B')") in events
    assert not any(
        log.obj_name == "B" and log.event == "Delete trace(s)" for log in new
    )
    assert all(
        log.section_ranges == [(snum, snum)]
        for log in new if log.obj_name == "A"
    )


def test_nothing_is_logged_when_nothing_was_combined(tmp_path):
    series = _load_series(tmp_path)
    _seed(series, [("A", SQUARE, ()), ("B", SQUARE, ())])
    group = _only(series.findDuplicateTraces(0.95), "A", "B")
    before = len(series.log_set.all_logs)

    series.combineDuplicateTraces([(group, None)])

    assert len(series.log_set.all_logs) == before


# ---------------------------------------------------------------------------
# an open pair, all the way through combining
#
# The scan compares an open pair curve-to-curve, which needs the section's
# magnification, and getOverlapRatio raises rather than guess one. Combining
# works from the members the scan recorded and never measures anything, which
# is tested here rather than read: a comparison without a mag would raise
# in the middle of a combine.
# ---------------------------------------------------------------------------

OPEN_LINE = [(0.0, 0.0), (2.0, 0.1), (4.0, 0.0), (6.0, 0.1), (8.0, 0.0)]

## the same path at twice the density: every added point sits on a segment of
## OPEN_LINE, so the curves coincide while the point sequences differ
OPEN_LINE_DENSE = [(0.0, 0.0), (1.0, 0.05), (2.0, 0.1), (3.0, 0.05),
                   (4.0, 0.0), (5.0, 0.05), (6.0, 0.1), (7.0, 0.05),
                   (8.0, 0.0)]


def _one_open_group(series):
    """One open path traced twice under two names, at two point densities, so
    the pair is measured rather than matched point for point."""
    from PyReconstruct.modules.datatypes.trace import Trace
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "OPEN_A", OPEN_LINE, closed=False)
    _make(section, "OPEN_B", OPEN_LINE_DENSE, closed=False)
    section.save()

    a, b = section.contours["OPEN_A"][0], section.contours["OPEN_B"][0]
    assert not a.pointsMatch(b), "premise: the pair must be MEASURED"
    assert Trace.ratioIsOverlap(a.getOverlapRatio(b, section.mag), 0.95)

    return snum, _only(series.findDuplicateTraces(0.95), "OPEN_A", "OPEN_B")


def test_an_open_group_is_found_and_combined(tmp_path):
    series = _load_series(tmp_path)
    snum, group = _one_open_group(series)

    assert series.combineDuplicateTraces(
        [(group, "OPEN_B")], series_states=_states(series)
    ) == [(group, "OPEN_B")]
    assert _count(series, snum, "OPEN_A") == 0
    assert _count(series, snum, "OPEN_B") == 1


def test_combining_never_measures_an_overlap(tmp_path, monkeypatch):
    from PyReconstruct.modules.datatypes.trace import Trace
    series = _load_series(tmp_path)
    snum, group = _one_open_group(series)

    def boom(*args, **kwargs):
        raise AssertionError("combining must not measure an overlap")

    monkeypatch.setattr(Trace, "getOverlapRatio", boom)

    assert series.combineDuplicateTraces([(group, "OPEN_A")]) == [
        (group, "OPEN_A")
    ]
    assert _count(series, snum, "OPEN_B") == 0


# ---------------------------------------------------------------------------
# the two Trace answers the scan relies on
# ---------------------------------------------------------------------------

def test_overlaps_still_answers_with_a_plain_bool():
    """getOverlapRatio returns a numpy float; overlaps() must not leak that."""
    from PyReconstruct.modules.datatypes.trace import Trace
    a = Trace("a", (0, 0, 0))
    a.points = list(SQUARE)
    a.closed = True
    b = Trace("b", (0, 0, 0))
    b.points = _shifted(SQUARE, 1.0)
    b.closed = True

    assert a.overlaps(b, threshold=0.5) is True
    assert a.overlaps(b, threshold=0.99) is False
    assert Trace.ratioIsOverlap(a.getOverlapRatio(b), 0.5) is True


def test_points_match_is_the_tolerance_overlaps_always_used():
    """pointsMatch keeps overlaps()' 1e-2 per-axis tolerance and length check."""
    from PyReconstruct.modules.datatypes.trace import Trace
    a = Trace("a", (0, 0, 0))
    a.points = list(SQUARE)
    b = Trace("b", (0, 0, 0))
    b.points = _shifted(SQUARE, 0.009)
    c = Trace("c", (0, 0, 0))
    c.points = _shifted(SQUARE, 0.011)
    d = Trace("d", (0, 0, 0))
    d.points = list(SQUARE) + [(0, 5)]

    assert a.pointsMatch(b) is True     # inside the tolerance
    assert a.pointsMatch(c) is False    # outside it
    assert a.pointsMatch(d) is False    # different point count
    assert a.pointsMatch(a) is True


# ---------------------------------------------------------------------------
# an edit after the scan: a group is combined whole or not at all
# ---------------------------------------------------------------------------

def _remove_first(series, snum, name):
    """An outside edit: delete the first trace of an object after the scan."""
    section = series.loadSection(snum)
    section.removeTrace(section.contours[name][0], log_event=False)
    section.save()


def test_a_member_deleted_after_the_scan_leaves_the_group_whole(tmp_path):
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, ("a",)), ("B", SQUARE, ("b",)), ("C", SQUARE, ("c",)),
    ])
    group = _only(series.findDuplicateTraces(0.95), "A", "B", "C")
    _remove_first(series, snum, "C")

    ambiguous = []
    assert series.combineDuplicateTraces(
        [(group, "A")], ambiguous=ambiguous
    ) == []
    assert ambiguous == []
    assert _tags(series, snum, "A") == [["a"]]
    assert _tags(series, snum, "B") == [["b"]]


def test_identical_traces_that_changed_count_leave_the_group_whole(tmp_path):
    """Three identical `B` traces, one deleted after the scan: which two are
    left cannot be told apart, so nothing is combined and the traces are
    reported."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, ("a",)),
        ("B", SQUARE, ("same",)),
        ("B", SQUARE, ("same",)),
        ("B", SQUARE, ("same",)),
    ])
    group = _only(series.findDuplicateTraces(0.95), "A", "B", "B", "B")
    _remove_first(series, snum, "B")

    ambiguous = []
    assert series.combineDuplicateTraces(
        [(group, "A")], ambiguous=ambiguous
    ) == []
    assert ambiguous and all(m["name"] == "B" for m in ambiguous)
    assert _tags(series, snum, "A") == [["a"]]
    assert _tags(series, snum, "B") == [["same"], ["same"]]


def test_a_member_that_moved_but_is_unique_is_still_found(tmp_path):
    """An unrelated trace of `B` before the member is deleted, so the index
    shifts; the member is the only one with its saved data, so it is found."""
    far = _shifted(SQUARE, 300.0, 300.0)
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("B", far, ("elsewhere",)),
        ("A", SQUARE, ("a",)),
        ("B", SQUARE, ("b",)),
    ])
    group = _only(series.findDuplicateTraces(0.95), "A", "B")
    _remove_first(series, snum, "B")

    assert series.combineDuplicateTraces([(group, "A")]) == [(group, "A")]
    assert _count(series, snum, "B") == 0
    assert _tags(series, snum, "A") == [["a", "b"]]


def test_the_second_of_two_identical_kept_traces_is_the_one_kept(tmp_path):
    """Identical traces keep their own tags apart: the trace kept is the one
    the group names, by its place among its lookalikes."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, ("first",)),
        ("A", SQUARE, ("second",)),
    ])
    group = _only(series.findDuplicateTraces(0.95), "A", "A")

    series.combineDuplicateTraces([(group, "A")])

    assert _tags(series, snum, "A") == [["first", "second"]]


# ---------------------------------------------------------------------------
# the field layer: FieldWidgetObject.combineDuplicateTraces
# ---------------------------------------------------------------------------

class _StubField:
    def __init__(self, series):
        from types import SimpleNamespace
        self.series = series
        self.series_states = _states(series)
        # no section loaded, so the combine has no copy to reload
        self.section = self.b_section = None
        self.updated = []
        self.reloaded = 0
        self.saved = 0
        self.modified = []
        self.table_manager = SimpleNamespace(
            updateObjects=lambda names: self.updated.append(set(names))
        )
        self.mainwindow = SimpleNamespace(
            saveAllData=self._save,
            seriesModified=lambda *a: self.modified.append(a),
        )

    def _save(self):
        self.saved += 1

    def reload(self):
        self.reloaded += 1


def _field(monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_3_object as mod
    notices = []
    monkeypatch.setattr(
        mod, "notify", lambda message, *a, **k: notices.append(message)
    )
    return mod, notices


def test_the_field_layer_combines_and_refreshes(tmp_path, monkeypatch):
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ("a",)), ("B", SQUARE, ("b",))])
    group = _only(series.findDuplicateTraces(0.95), "A", "B")
    mod, notices = _field(monkeypatch)
    field = _StubField(series)

    applied = mod.FieldWidgetObject.combineDuplicateTraces(
        field, [(group, "A")]
    )

    assert applied == [(group, "A")]
    assert field.saved == 1
    assert field.updated == [{"A", "B"}]
    assert field.reloaded == 1
    assert field.modified
    assert notices == []
    assert len(field.series_states.undos) == 1
    assert _tags(series, snum, "A") == [["a", "b"]]


def test_the_field_layer_names_a_locked_object_it_refused(tmp_path,
                                                         monkeypatch):
    series = _load_series(tmp_path)
    far = _shifted(SQUARE, 200.0, 200.0)
    snum = _seed(series, [
        ("A", SQUARE, ()), ("B", SQUARE, ()),
        ("C", far, ()), ("D", far, ()),
    ])
    series.setAttr("B", "locked", True)
    groups = series.findDuplicateTraces(0.95, include_locked=True)
    ab, cd = _only(groups, "A", "B"), _only(groups, "C", "D")
    mod, notices = _field(monkeypatch)

    applied = mod.FieldWidgetObject.combineDuplicateTraces(
        _StubField(series), [(ab, "A"), (cd, "C")]
    )

    assert applied == [(cd, "C")]
    assert notices == [
        "PyReconstruct did not combine 1 row because it would delete traces "
        "of a locked object:\n\n  B\n\nUnlock it, or keep its name, and "
        "combine again."
    ]
    assert _count(series, snum, "B") == 1


def test_a_row_of_one_locked_name_is_told_only_to_unlock(tmp_path,
                                                         monkeypatch):
    """Both traces are the locked object's, so keeping its name, already
    picked, still deletes one of them. Only unlocking lets the row combine."""
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, ()), ("A", _shifted(SQUARE, 0.2), ()),
    ])
    series.setAttr("A", "locked", True)
    group = _only(
        series.findDuplicateTraces(0.95, include_locked=True), "A", "A"
    )
    mod, notices = _field(monkeypatch)

    assert mod.FieldWidgetObject.combineDuplicateTraces(
        _StubField(series), [(group, "A")]
    ) == []
    assert notices == [
        "PyReconstruct did not combine 1 row because it would delete traces "
        "of a locked object:\n\n  A\n\nUnlock it and combine again."
    ]
    assert _count(series, snum, "A") == 2


def test_keeping_a_name_is_offered_only_when_every_refused_row_can_use_it(
        tmp_path, monkeypatch):
    """`A` alone is locked in its row, so keeping `A` would save that row. The
    other row holds two locked traces, `B` and `C`, and keeping either name
    deletes the other, so the notice says to unlock."""
    series = _load_series(tmp_path)
    far = _shifted(SQUARE, 200.0, 200.0)
    snum = _seed(series, [
        ("A", SQUARE, ()), ("X", SQUARE, ()),
        ("B", far, ()), ("C", far, ()), ("Y", far, ()),
    ])
    for name in ("A", "B", "C"):
        series.setAttr(name, "locked", True)
    groups = series.findDuplicateTraces(0.95, include_locked=True)
    ax, bcy = _only(groups, "A", "X"), _only(groups, "B", "C", "Y")
    mod, notices = _field(monkeypatch)

    assert mod.FieldWidgetObject.combineDuplicateTraces(
        _StubField(series), [(ax, "X"), (bcy, "B")]
    ) == []
    assert notices == [
        "PyReconstruct did not combine 2 rows because they would delete "
        "traces of locked objects:\n\n  A\n  C\n\nUnlock them and combine "
        "again."
    ]
    assert [_count(series, snum, n) for n in "ABCXY"] == [1, 1, 1, 1, 1]


def test_the_field_layer_says_a_row_changed_since_the_scan(tmp_path,
                                                          monkeypatch):
    series = _load_series(tmp_path)
    snum = _seed(series, [("A", SQUARE, ()), ("B", SQUARE, ())])
    group = _only(series.findDuplicateTraces(0.95), "A", "B")
    _remove_first(series, snum, "B")
    mod, notices = _field(monkeypatch)

    assert mod.FieldWidgetObject.combineDuplicateTraces(
        _StubField(series), [(group, "A")]
    ) == []
    assert notices == [
        "PyReconstruct did not combine 1 row. Its traces changed after the "
        "scan. Run the scan again to list them as they are now."
    ]


def test_the_field_layer_reports_identical_traces_it_cannot_tell_apart(
        tmp_path, monkeypatch):
    series = _load_series(tmp_path)
    snum = _seed(series, [
        ("A", SQUARE, ()),
        ("B", SQUARE, ("same",)),
        ("B", SQUARE, ("same",)),
        ("B", SQUARE, ("same",)),
    ])
    group = _only(series.findDuplicateTraces(0.95), "A", "B", "B", "B")
    _remove_first(series, snum, "B")
    mod, notices = _field(monkeypatch)

    assert mod.FieldWidgetObject.combineDuplicateTraces(
        _StubField(series), [(group, "A")]
    ) == []
    assert len(notices) == 1
    assert notices[0].startswith("PyReconstruct did not combine ")
    assert f"  B on section {snum}" in notices[0]
