"""Duplicates traced twice under two different names (board card #109).

`Series.deleteDuplicateTraces` only ever compares traces that already share an
object name, and not because anything in the comparison reads a name:
`Trace.overlaps` is purely geometric. The restriction comes from the loop, which
draws both traces out of one `section.contours[cname]`. So the case two people
produce by tracing the same structure under two names is invisible to it.

`Series.findDifferentlyNamedDuplicates` compares across names instead. The scan
itself never deletes; `Series.deleteDifferentlyNamedDuplicates` applies the
choices a person made, one pair at a time, because which of two names is the
right one is a question about the data rather than about geometry.

What is pinned here:

  * a shape traced twice under two names is found, and the record names both
  * two genuinely different shapes are not reported
  * a locked object is left out of the scan, and the scan modifies nothing
  * the overlap threshold is honored, on both of `Trace.overlaps`' tests
  * the pair the sweep and the ratio ceiling can skip is exactly the pair whose
    ratio would not have cleared the threshold: the fast path and a brute-force
    comparison of every pair agree, trace for trace
  * `deleteDuplicateTraces` still does exactly what it did, including leaving
    differently-named coincident traces alone
  * the removal half deletes only the side the caller did not keep, is undoable,
    logs what it did, and **never resolves a pair nobody answered** -- not even
    when an obvious-looking rule (more sections, larger area) is available
  * a locked object cannot lose a trace through the removal half, even when the
    scan was told to include locked objects
  * the field layer saves field data first, refreshes both names' rows, explains
    a lock refusal by name, and does not also call a refused row a missing one
  * the review list is wired to the field delete rather than opened report-only

Runs against the real shapes1.jser fixture with synthetic traces layered on, the
same way tests/test_data_cleanup.py does.
"""
import os
import shutil

import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
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


def _make(section, name, points, closed=True):
    t = _template_trace(section).copy()
    t.name = name
    t.points = list(points)
    t.closed = closed
    section.addTrace(t, log_event=False)
    return t


def _snum_with_closed(series):
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        for cname in section.contours:
            for trace in section.contours[cname]:
                if trace.closed and len(trace.points) >= 3:
                    return snum
    pytest.skip("no closed trace anywhere in fixture")


def _count(series, snum, name):
    return len(series.loadSection(snum).contours.get(name, []))


def _pairs(records):
    """The reported pairs as name sets, so row order cannot matter."""
    return {frozenset((r["name"], r["other_name"])) for r in records}


def _shifted(points, dx, dy=0.0):
    return [(x + dx, y + dy) for x, y in points]


# ---------------------------------------------------------------------------
# the case the card is about
# ---------------------------------------------------------------------------

def test_identical_shape_under_two_names_is_found(tmp_path):
    """One shape traced twice under two names is reported as a pair."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "TRACER_A", SQUARE)
    _make(section, "TRACER_B", list(SQUARE))
    section.save()

    records = series.findDifferentlyNamedDuplicates(0.95)
    assert _pairs(records) == {frozenset(("TRACER_A", "TRACER_B"))}


def test_record_describes_both_traces_of_the_pair(tmp_path):
    """Each record carries enough to judge the pair without reopening it."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "TRACER_A", SQUARE)
    _make(section, "TRACER_B", list(SQUARE))
    section.save()

    record = series.findDifferentlyNamedDuplicates(0.95)[0]

    assert {record["name"], record["other_name"]} == {"TRACER_A", "TRACER_B"}
    assert record["section"] == snum
    assert record["ratio"] == 1.0                  # same points
    assert record["points"] == record["other_points"] == 4
    # both areas are physical (um^2) and equal, being the same shape
    assert record["area"] > 0
    assert record["area"] == pytest.approx(record["other_area"])
    # a signature per trace, so a later delete could re-find either one. The
    # signature is color + points, which for one shape under two names is the
    # same on both sides; the object name it is looked up under is what tells
    # them apart, and deleteMalformedTraces takes both.
    for side, name in (("match", "name"), ("other_match", "other_name")):
        assert set(record[side]) == {"color", "points"}
        assert len(record[side]["points"]) == 4
        section = series.loadSection(snum)
        contour = section.contours[record[name]]
        from PyReconstruct.modules.datatypes.series import Series
        assert any(
            Series._traceMatchesSignature(t, record[side]) for t in contour
        )
    assert "TRACER" in record["reason"]


def test_nearly_identical_shapes_under_two_names_are_found(tmp_path):
    """The realistic case: two people trace one structure, so the points differ.

    A one-unit shift on a ten-unit square is well past the 1e-2 tolerance of the
    point-for-point test, so this pair is only found by measuring an overlap
    ratio, which is the path the ratio ceiling in _duplicatePairs guards.
    """
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "TRACER_A", SQUARE)
    _make(section, "TRACER_B", _shifted(SQUARE, 1.0))
    section.save()

    records = series.findDifferentlyNamedDuplicates(0.5)
    assert _pairs(records) == {frozenset(("TRACER_A", "TRACER_B"))}
    assert 0.5 < records[0]["ratio"] < 1.0


def test_different_shapes_are_not_reported(tmp_path):
    """Two objects that are not the same shape are not a duplicate pair."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "SMALL", SQUARE)
    # a far-away square: no bounding-box overlap at all
    _make(section, "FAR", _shifted(SQUARE, 500.0, 500.0))
    # an overlapping but much bigger square: real overlap, nowhere near 0.95
    _make(section, "BIG", [(0, 0), (40, 0), (40, 40), (0, 40)])
    section.save()

    assert series.findDifferentlyNamedDuplicates(0.95) == []


def test_partially_overlapping_neighbors_are_not_reported(tmp_path):
    """Neighbors sharing an edge overlap geometrically but are not duplicates."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "LEFT", SQUARE)
    _make(section, "RIGHT", _shifted(SQUARE, 9.5))  # boxes overlap, shapes barely
    section.save()

    assert series.findDifferentlyNamedDuplicates(0.95) == []


# ---------------------------------------------------------------------------
# the threshold
# ---------------------------------------------------------------------------

def test_threshold_is_honored(tmp_path):
    """A pair below the threshold is not reported; the same pair above it is."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "TRACER_A", SQUARE)
    _make(section, "TRACER_B", _shifted(SQUARE, 1.0))
    section.save()

    section = series.loadSection(snum)
    a = section.contours["TRACER_A"][0]
    b = section.contours["TRACER_B"][0]
    ratio = a.getOverlapRatio(b)
    assert 0 < ratio < 1, "premise: the pair overlaps partially"

    below = series.findDifferentlyNamedDuplicates(min(ratio * 1.01, 0.999))
    above = series.findDifferentlyNamedDuplicates(ratio * 0.99)
    assert _pairs(below) == set()
    assert _pairs(above) == {frozenset(("TRACER_A", "TRACER_B"))}


def test_zero_area_traces_are_compared_on_points_not_area(tmp_path):
    """Two identical lines under two names are duplicates, and do not raise.

    A straight line encloses no area, so the combined bounding box collapses and
    there is no overlap ratio to measure (getOverlapRatio answers 0 rather than
    dividing by zero). The point-for-point test settles the pair before either
    of the area-based filters can see it, which is why it runs first.
    """
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    line = [(0, 0), (0, 5), (0, 10)]
    _make(section, "LINE_A", line, closed=False)
    _make(section, "LINE_B", list(line), closed=False)
    # a different line on the same axis: not a duplicate, and must not raise
    _make(section, "LINE_C", [(0, 20), (0, 24), (0, 30)], closed=False)
    section.save()

    records = series.findDifferentlyNamedDuplicates(0.95)
    assert _pairs(records) == {frozenset(("LINE_A", "LINE_B"))}


def test_pair_matching_within_tolerance_with_disjoint_boxes_is_found(tmp_path):
    """Boxes that miss each other by less than the point tolerance still pair.

    Trace.pointsMatch calls two points the same when they are within
    Trace.POINTS_MATCH_TOLERANCE on each axis, so two traces can match point for
    point while their bounding boxes do not touch at all. Every bounding-box test
    in _duplicatePairs is therefore slack by that tolerance. Without the slack
    this pair is skipped, and it is not a contrived shape: it is the only
    duplicate pair on the densest section of a real 161,767-trace autoseg series,
    two two-point traces about 0.006 apart in y, found by brute force and missed
    by a strict sweep.
    """
    from PyReconstruct.modules.datatypes.trace import Trace
    tol = Trace.POINTS_MATCH_TOLERANCE
    gap = tol * 0.6  # inside the tolerance, outside both bounding boxes

    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    line = [(17.7051743, 18.4915389), (17.707118, 18.4895568)]
    _make(section, "NEAR_A", line, closed=False)
    _make(section, "NEAR_B", _shifted(line, gap * 0.2, gap), closed=False)
    section.save()

    section = series.loadSection(snum)
    a = section.contours["NEAR_A"][0]
    b = section.contours["NEAR_B"][0]
    assert a.pointsMatch(b) is True, "premise: inside the point tolerance"
    a_bounds, b_bounds = a.getBounds(), b.getBounds()
    assert a_bounds[3] < b_bounds[1], "premise: the boxes are disjoint in y"

    assert _pairs(series.findDifferentlyNamedDuplicates(0.95)) == {
        frozenset(("NEAR_A", "NEAR_B"))
    }


def test_open_and_closed_traces_never_pair(tmp_path):
    """An open trace is not a duplicate of a closed one, as in Trace.overlaps."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "CLOSED", SQUARE, closed=True)
    _make(section, "OPEN", list(SQUARE), closed=False)
    section.save()

    assert series.findDifferentlyNamedDuplicates(0.95) == []


# ---------------------------------------------------------------------------
# lock, and not modifying anything
# ---------------------------------------------------------------------------

def test_locked_objects_are_left_out(tmp_path):
    """A locked object is not reported, and is still there afterwards."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "TRACER_A", SQUARE)
    _make(section, "TRACER_B", list(SQUARE))
    section.save()
    series.setAttr("TRACER_B", "locked", True)

    assert series.findDifferentlyNamedDuplicates(0.95) == []
    # opting in surfaces it again, matching findPixelDustTraces / findEmptyTraces
    assert _pairs(series.findDifferentlyNamedDuplicates(
        0.95, include_locked=True
    )) == {frozenset(("TRACER_A", "TRACER_B"))}

    # either way, both traces survive: this operation only reports
    assert _count(series, snum, "TRACER_A") == 1
    assert _count(series, snum, "TRACER_B") == 1


def test_scan_never_modifies_the_series(tmp_path):
    """Scanning at a threshold that matches everything still deletes nothing."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "TRACER_A", SQUARE)
    _make(section, "TRACER_B", list(SQUARE))
    section.save()

    before = {
        cname: len(traces)
        for cname, traces in series.loadSection(snum).contours.items()
    }
    series.findDifferentlyNamedDuplicates(0.01)
    after = {
        cname: len(traces)
        for cname, traces in series.loadSection(snum).contours.items()
    }
    assert after == before


# ---------------------------------------------------------------------------
# the fast path finds exactly what brute force finds
# ---------------------------------------------------------------------------

def _brute_force(section, series, threshold, include_locked=False):
    """Every unordered cross-name pair, straight into Trace.overlaps."""
    flat = []
    for cname in section.contours:
        if not include_locked and series.getAttr(cname, "locked"):
            continue
        for index, trace in enumerate(section.contours[cname]):
            flat.append((cname, index, trace))
    found = set()
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            aname, _ai, atrace = flat[i]
            bname, _bi, btrace = flat[j]
            if aname == bname:
                continue
            if atrace.overlaps(btrace, threshold=threshold):
                found.add(frozenset((aname, bname)))
    return found


@pytest.mark.parametrize("threshold", [0.99, 0.95, 0.8, 0.5, 0.2])
def test_fast_path_agrees_with_brute_force(tmp_path, threshold):
    """The sweep and the ratio ceiling skip only pairs that would not have hit.

    Both filters exist to avoid measuring overlap ratios that cannot clear the
    threshold, so the thing to prove is that they change nothing about the
    answer. A crowd of shapes at graded separations is compared both ways, at
    five thresholds, and the two sets of pairs must be identical.
    """
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)

    # a row of squares at graded offsets, so every degree of overlap from
    # identical to disjoint is represented, plus shapes of a different size
    for i, dx in enumerate([0.0, 0.005, 0.2, 1.0, 2.5, 5.0, 8.0, 11.0, 30.0]):
        _make(section, f"ROW_{i}", _shifted(SQUARE, dx))
    for i, side in enumerate([9.0, 10.0, 10.5, 20.0]):
        _make(section, f"SIZE_{i}",
              [(0, 0), (side, 0), (side, side), (0, side)])
    for i, dy in enumerate([0.0, 0.3, 40.0]):
        _make(section, f"COL_{i}", _shifted(SQUARE, 0.0, dy))
    _make(section, "LINE_A", [(0, 0), (0, 5), (0, 10)], closed=False)
    _make(section, "LINE_B", [(0, 0), (0, 5), (0, 10)], closed=False)
    section.save()

    section = series.loadSection(snum)
    expected = _brute_force(section, series, threshold)
    got = _pairs(series.findDifferentlyNamedDuplicates(threshold))
    assert got == expected


# ---------------------------------------------------------------------------
# the same-name operation is untouched
# ---------------------------------------------------------------------------

def test_same_name_removal_is_unchanged(tmp_path):
    """Two identical traces of one object still collapse to one, undoably."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "DUPE", SQUARE)
    _make(section, "DUPE", list(SQUARE))
    section.save()
    assert _count(series, snum, "DUPE") == 2

    from PyReconstruct.modules.backend.func.state_manager import SeriesStates
    states = SeriesStates(series)
    removed = series.deleteDuplicateTraces(0.95, series_states=states)
    assert snum in removed and "DUPE" in removed[snum]
    assert _count(series, snum, "DUPE") == 1

    states.undoState()
    assert _count(series, snum, "DUPE") == 2


def test_same_name_removal_still_spares_differently_named_traces(tmp_path):
    """The new scan reports the pair that deleteDuplicateTraces must not touch.

    The two operations answer the same geometry differently on purpose, and that
    difference is the whole point of the card: the same-name path leaves the
    pair alone (it cannot know which name is right), and the new path says the
    pair is there.
    """
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "OBJ_A", SQUARE)
    _make(section, "OBJ_B", list(SQUARE))
    section.save()

    from PyReconstruct.modules.backend.func.state_manager import SeriesStates
    series.deleteDuplicateTraces(0.95, series_states=SeriesStates(series))
    assert _count(series, snum, "OBJ_A") == 1
    assert _count(series, snum, "OBJ_B") == 1

    assert _pairs(series.findDifferentlyNamedDuplicates(0.95)) == {
        frozenset(("OBJ_A", "OBJ_B"))
    }


# ---------------------------------------------------------------------------
# the refactor Trace.overlaps went through
# ---------------------------------------------------------------------------

def test_overlaps_still_answers_with_a_plain_bool():
    """getOverlapRatio returns a numpy float; overlaps() must not leak that.

    Trace.ratioIsOverlap was split out of overlaps() so a caller that wants the
    ratio itself can reach the same verdict. Returning the comparison directly
    handed back numpy.bool_, which is truthy but is not True.
    """
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
# the removal half: the caller chooses per pair, and nothing is inferred
#
# Settled 2026-07-31. The scan alone was report-only, and the maintainer chose
# per-row selection over three alternatives -- keeping the most-established name
# automatically, reassigning instead of deleting, and leaving it report-only --
# for the reason the scan's own docstring gives: which name is correct is a
# judgment about the data that geometry cannot settle, so the tool must never
# guess. `test_an_unanswered_pair_is_never_resolved` and
# `test_no_rule_breaks_a_tie_on_the_callers_behalf` are that decision; a change
# that makes either one fail is reversing it, not fixing it.
# ---------------------------------------------------------------------------

def _states(series):
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates
    return SeriesStates(series)


def _one_pair(series, name_a="TRACER_A", name_b="TRACER_B"):
    """Lay one shape down twice under two names; return (snum, record)."""
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, name_a, SQUARE)
    _make(section, name_b, list(SQUARE))
    section.save()
    records = series.findDifferentlyNamedDuplicates(0.95)
    assert len(records) == 1, records
    return snum, records[0]


def test_keeping_the_first_name_deletes_only_the_other(tmp_path):
    """"first" keeps the record's own trace and removes the other one."""
    series = _load_series(tmp_path)
    snum, record = _one_pair(series)
    kept, gone = record["name"], record["other_name"]

    applied = series.deleteDifferentlyNamedDuplicates(
        [(record, "first")], series_states=_states(series)
    )

    assert applied == [(record, "first")]
    assert _count(series, snum, kept) == 1
    assert _count(series, snum, gone) == 0


def test_keeping_the_other_name_deletes_the_first(tmp_path):
    """"other" is the mirror image: the side kept is the side the caller named."""
    series = _load_series(tmp_path)
    snum, record = _one_pair(series)
    gone, kept = record["name"], record["other_name"]

    applied = series.deleteDifferentlyNamedDuplicates(
        [(record, "other")], series_states=_states(series)
    )

    assert applied == [(record, "other")]
    assert _count(series, snum, kept) == 1
    assert _count(series, snum, gone) == 0


def test_the_deletion_is_undoable(tmp_path):
    """One undo puts the deleted trace back, as the same-name path does."""
    series = _load_series(tmp_path)
    snum, record = _one_pair(series)
    gone = record["other_name"]
    states = _states(series)

    series.deleteDifferentlyNamedDuplicates([(record, "first")],
                                            series_states=states)
    assert _count(series, snum, gone) == 0

    states.undoState()
    assert _count(series, snum, gone) == 1
    assert _count(series, snum, record["name"]) == 1


def test_a_whole_batch_undoes_in_one_step(tmp_path):
    """Several pairs answered at once are one undoable operation, not several."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    for i in range(3):
        _make(section, f"KEEP_{i}", _shifted(SQUARE, i * 50.0))
        _make(section, f"DROP_{i}", _shifted(SQUARE, i * 50.0))
    section.save()

    records = series.findDifferentlyNamedDuplicates(0.95)
    assert len(records) == 3
    choices = [
        (r, "first" if r["name"].startswith("KEEP_") else "other")
        for r in records
    ]
    states = _states(series)
    assert len(series.deleteDifferentlyNamedDuplicates(
        choices, series_states=states
    )) == 3
    for i in range(3):
        assert _count(series, snum, f"KEEP_{i}") == 1
        assert _count(series, snum, f"DROP_{i}") == 0

    states.undoState()
    for i in range(3):
        assert _count(series, snum, f"KEEP_{i}") == 1
        assert _count(series, snum, f"DROP_{i}") == 1


def test_an_unanswered_pair_is_never_resolved(tmp_path):
    """No choice means no deletion. Silence is not a selection.

    The point of the whole design: a row nobody answered carries None, and None
    is skipped rather than turned into a side by any default.
    """
    series = _load_series(tmp_path)
    snum, record = _one_pair(series)

    assert series.deleteDifferentlyNamedDuplicates(
        [(record, None)], series_states=_states(series)
    ) == []
    assert _count(series, snum, record["name"]) == 1
    assert _count(series, snum, record["other_name"]) == 1

    # nor does anything that is not exactly one of the two side names
    for bogus in ("", "keep", "both", "FIRST", 0, True):
        assert series.deleteDifferentlyNamedDuplicates(
            [(record, bogus)], series_states=_states(series)
        ) == []
    assert _count(series, snum, record["name"]) == 1
    assert _count(series, snum, record["other_name"]) == 1


def test_no_rule_breaks_a_tie_on_the_callers_behalf(tmp_path):
    """The rejected alternative: "keep the most-established name" is not applied.

    Here one name is on three sections and the other on one, and the traces have
    different areas -- everything a heuristic would need. Unanswered still means
    untouched.
    """
    series = _load_series(tmp_path)
    snums = sorted(series.sections)[:3]
    if len(snums) < 3:
        pytest.skip("fixture has fewer than 3 sections")
    for snum in snums:
        section = series.loadSection(snum)
        _make(section, "ESTABLISHED", SQUARE)
        section.save()
    section = series.loadSection(snums[0])
    # a slightly smaller square, still well over the 0.95 threshold
    _make(section, "NEWCOMER", [(0, 0), (10, 0), (10, 9.8), (0, 9.8)])
    section.save()

    records = series.findDifferentlyNamedDuplicates(0.95)
    assert _pairs(records) == {frozenset(("ESTABLISHED", "NEWCOMER"))}

    assert series.deleteDifferentlyNamedDuplicates(
        [(r, None) for r in records], series_states=_states(series)
    ) == []
    assert _count(series, snums[0], "ESTABLISHED") == 1
    assert _count(series, snums[0], "NEWCOMER") == 1


def test_only_the_answered_pairs_of_a_mixed_batch_are_applied(tmp_path):
    """Answered and unanswered rows can be handed over together."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "ANSWERED_A", SQUARE)
    _make(section, "ANSWERED_B", list(SQUARE))
    _make(section, "SILENT_A", _shifted(SQUARE, 100.0))
    _make(section, "SILENT_B", _shifted(SQUARE, 100.0))
    section.save()

    by_pair = {
        frozenset((r["name"], r["other_name"])): r
        for r in series.findDifferentlyNamedDuplicates(0.95)
    }
    answered = by_pair[frozenset(("ANSWERED_A", "ANSWERED_B"))]
    silent = by_pair[frozenset(("SILENT_A", "SILENT_B"))]
    keep = "first" if answered["name"] == "ANSWERED_A" else "other"

    applied = series.deleteDifferentlyNamedDuplicates(
        [(answered, keep), (silent, None)], series_states=_states(series)
    )

    assert applied == [(answered, keep)]
    assert _count(series, snum, "ANSWERED_A") == 1
    assert _count(series, snum, "ANSWERED_B") == 0
    assert _count(series, snum, "SILENT_A") == 1
    assert _count(series, snum, "SILENT_B") == 1


# ---------------------------------------------------------------------------
# lock on the removal half
#
# Deleting a trace is a change to quantitative data, which is exactly what
# locking an object refuses (specs/lock-semantics.md). The scan can be told to
# include locked objects; that must not become a way to delete from one.
# ---------------------------------------------------------------------------

def test_a_locked_object_never_loses_a_trace(tmp_path):
    """Choosing to delete a locked object's trace is refused, not obeyed."""
    series = _load_series(tmp_path)
    snum, _ = _one_pair(series)
    series.setAttr("TRACER_B", "locked", True)

    # the scan surfaces it only when asked to; the record is then a real one
    records = series.findDifferentlyNamedDuplicates(0.95, include_locked=True)
    assert len(records) == 1
    record = records[0]
    # keep the unlocked name, i.e. ask for the LOCKED object's trace to go
    keep = "first" if record["name"] == "TRACER_A" else "other"

    assert series.deleteDifferentlyNamedDuplicates(
        [(record, keep)], series_states=_states(series)
    ) == []
    assert _count(series, snum, "TRACER_A") == 1
    assert _count(series, snum, "TRACER_B") == 1


def test_locking_one_side_does_not_protect_the_other(tmp_path):
    """Lock guards the object it is on; keeping a trace does not modify it.

    The narrow reading of lock, deliberately: the unlocked object's trace can
    still be deleted while the locked one is the name being kept.
    """
    series = _load_series(tmp_path)
    snum, _ = _one_pair(series)
    series.setAttr("TRACER_B", "locked", True)

    record = series.findDifferentlyNamedDuplicates(
        0.95, include_locked=True
    )[0]
    # keep the LOCKED name, so the unlocked object is the one losing a trace
    keep = "other" if record["name"] == "TRACER_A" else "first"

    assert len(series.deleteDifferentlyNamedDuplicates(
        [(record, keep)], series_states=_states(series)
    )) == 1
    assert _count(series, snum, "TRACER_A") == 0
    assert _count(series, snum, "TRACER_B") == 1


# ---------------------------------------------------------------------------
# saying what happened
# ---------------------------------------------------------------------------

def test_each_deletion_is_logged_against_the_object_that_lost_a_trace(tmp_path):
    """The log names the object deleted from, its section, and the name kept.

    SeriesData.updateSection writes its own "Delete object" log when a section
    edit empties an object, exactly as it does for the pixel-dust and same-name
    paths, so that one is expected alongside and is not what this pins.
    """
    series = _load_series(tmp_path)
    snum, record = _one_pair(series)
    gone, kept = record["other_name"], record["name"]
    before = len(series.log_set.all_logs)

    series.deleteDifferentlyNamedDuplicates([(record, "first")],
                                            series_states=_states(series))

    added = series.log_set.all_logs[before:]
    mine = [l for l in added if "named differently" in l.event]
    assert len(mine) == 1, [(l.obj_name, l.event) for l in added]
    log = mine[0]
    assert log.obj_name == gone
    assert log.section_ranges == [(snum, snum)]
    assert kept in log.event


def test_nothing_is_logged_when_nothing_was_deleted(tmp_path):
    """An unanswered batch leaves no trace in the history either."""
    series = _load_series(tmp_path)
    _, record = _one_pair(series)
    before = len(series.log_set.all_logs)

    series.deleteDifferentlyNamedDuplicates([(record, None)],
                                            series_states=_states(series))

    assert series.log_set.all_logs[before:] == []


# ---------------------------------------------------------------------------
# the field layer, and the wiring that reaches it
#
# FieldWidgetObject.deleteDifferentlyNamedDuplicates is the dialog's callback.
# It is driven here unbound against a stub, because the guard that matters is
# the series' (tested above) and what this layer adds is what it *says*.
# ---------------------------------------------------------------------------

class _StubTableManager:
    def __init__(self):
        self.updated = None

    def updateObjects(self, names):
        self.updated = set(names)


class _StubMainWindow:
    def __init__(self):
        self.saved = 0
        self.modified = 0

    def saveAllData(self):
        self.saved += 1

    def seriesModified(self, *args):
        self.modified += 1


class _StubField:
    """Just enough of FieldWidgetObject for the delete callback."""

    def __init__(self, series):
        self.series = series
        self.series_states = _states(series)
        self.table_manager = _StubTableManager()
        self.mainwindow = _StubMainWindow()
        self.reloads = 0

    def reload(self):
        self.reloads += 1


def _field_delete(field, choices, monkeypatch):
    """Call the real field method on the stub, capturing its notifications."""
    from PyReconstruct.modules.gui.main import field_widget_3_object as mod
    notices = []
    monkeypatch.setattr(mod, "notify", lambda message, *a, **k: notices.append(
        message
    ))
    applied = mod.FieldWidgetObject.deleteDifferentlyNamedDuplicates(
        field, choices
    )
    return applied, notices


def test_the_field_layer_deletes_and_refreshes(tmp_path, monkeypatch):
    """The happy path: field data saved first, tables and field refreshed after."""
    series = _load_series(tmp_path)
    snum, record = _one_pair(series)
    field = _StubField(series)

    applied, notices = _field_delete(field, [(record, "first")], monkeypatch)

    assert applied == [(record, "first")]
    assert notices == []
    assert field.mainwindow.saved == 1
    assert field.reloads == 1
    assert field.mainwindow.modified == 1
    # both names are refreshed: one lost a trace, the other is what remains
    assert field.table_manager.updated == {"TRACER_A", "TRACER_B"}
    assert _count(series, snum, "TRACER_B") == 0


def test_the_field_layer_refuses_a_locked_object_and_names_it(tmp_path,
                                                             monkeypatch):
    """The refusal is explained, and nothing is deleted or refreshed."""
    series = _load_series(tmp_path)
    snum, _ = _one_pair(series)
    series.setAttr("TRACER_B", "locked", True)
    record = series.findDifferentlyNamedDuplicates(0.95, include_locked=True)[0]
    keep = "first" if record["name"] == "TRACER_A" else "other"
    field = _StubField(series)

    applied, notices = _field_delete(field, [(record, keep)], monkeypatch)

    assert applied == []
    assert len(notices) == 1
    assert "locked" in notices[0]
    assert "TRACER_B" in notices[0]
    assert field.reloads == 0
    assert _count(series, snum, "TRACER_A") == 1
    assert _count(series, snum, "TRACER_B") == 1


def test_the_field_layer_does_not_call_a_locked_row_a_missing_one(tmp_path,
                                                                 monkeypatch):
    """A locked row is reported once, as locked, not also as "not found".

    Both refusals are counted off the same batch, so miscounting one shows up as
    a second, wrong notice.
    """
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "LOCKED_A", SQUARE)
    _make(section, "OPEN_B", list(SQUARE))
    _make(section, "LOCKED_A2", _shifted(SQUARE, 100.0))
    _make(section, "OPEN_B2", _shifted(SQUARE, 100.0))
    section.save()
    series.setAttr("OPEN_B", "locked", True)
    series.setAttr("OPEN_B2", "locked", True)

    records = series.findDifferentlyNamedDuplicates(0.95, include_locked=True)
    assert len(records) == 2
    choices = [
        (r, "first" if r["name"].startswith("LOCKED_A") else "other")
        for r in records
    ]
    field = _StubField(series)

    applied, notices = _field_delete(field, choices, monkeypatch)

    assert applied == []
    assert len(notices) == 1, notices
    assert "not found" not in notices[0]


def test_the_review_list_is_wired_to_the_field_delete(tmp_path):
    """MainWindow hands the dialog the field callback, not a report-only list.

    Pins the wiring the per-row choice needs, without opening a MainWindow: the
    source of the caller must pass the field method through as the dialog's
    delete_unselected.
    """
    import inspect
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    from PyReconstruct.modules.gui.main.field_widget_3_object import (
        FieldWidgetObject,
    )

    assert hasattr(FieldWidgetObject, "deleteDifferentlyNamedDuplicates")
    src = inspect.getsource(MainWindow.findDifferentlyNamedDuplicates)
    assert "delete_unselected=(" in src
    assert "self.field.deleteDifferentlyNamedDuplicates" in src
