"""Duplicates traced twice under two different names (board card #109).

`Series.deleteDuplicateTraces` only ever compares traces that already share an
object name, and not because anything in the comparison reads a name:
`Trace.overlaps` is purely geometric. The restriction comes from the loop, which
draws both traces out of one `section.contours[cname]`. So the case two people
produce by tracing the same structure under two names is invisible to it.

`Series.findDifferentlyNamedDuplicates` compares across names instead. It
reports and never deletes, because which of two names is the right one is a
question about the data rather than about geometry.

What is pinned here:

  * a shape traced twice under two names is found, and the record names both
  * two genuinely different shapes are not reported
  * a locked object is left out, and nothing is modified either way
  * the overlap threshold is honored, on both of `Trace.overlaps`' tests
  * the pair the sweep and the ratio ceiling can skip is exactly the pair whose
    ratio would not have cleared the threshold: the fast path and a brute-force
    comparison of every pair agree, trace for trace
  * `deleteDuplicateTraces` still does exactly what it did, including leaving
    differently-named coincident traces alone

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
