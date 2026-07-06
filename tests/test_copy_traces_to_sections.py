"""Tests for "Copy to sections" (#91).

Covers the data-model operation that places selected trace(s) onto multiple
sections at the same field (x, y) location:

  * Series.copyTracesToSections re-projects field coordinates through each
    target section's own transform, so a trace lands at the identical field
    x-y on every section regardless of that section's alignment.
  * Trace attributes (name, color, closed, tags) are preserved verbatim.
  * Alignment-locked target sections still receive the copied trace (a lock
    protects the transform, not trace content).

Also unit-tests the pure section-spec parser used by the picker dialog.
"""
import os
import shutil
import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)

# a distinctive, easy-to-recognise field-coordinate shape (4 points, closed)
FIELD_PTS = [(11.5, 22.25), (33.0, 22.25), (33.0, 44.0), (11.5, 44.0)]


def _load_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    return series


def _unlock(series, snum):
    """Persist align_locked=False on a section so it can be copied onto."""
    section = series.loadSection(snum)
    section.align_locked = False
    section.save()


def _field_trace(series, snum, name):
    """A copy of a real trace (for its attributes) with distinctive points and
    a marker tag, its points already in FIELD coordinates."""
    section = series.loadSection(snum)
    trace = section.contours[name].getTraces()[0].copy()
    trace.points = list(FIELD_PTS)
    trace.tags = set(trace.tags)
    trace.tags.add("copytest")
    return trace


def _mapped_matches(section, trace, field_pts, tol=1e-3):
    """True if this section's transform maps the trace's stored points back to
    the expected field points."""
    if len(trace.points) != len(field_pts):
        return False
    tform = section.tform
    for stored, expected in zip(trace.points, field_pts):
        mx, my = tform.map(*stored)
        if abs(mx - expected[0]) > tol or abs(my - expected[1]) > tol:
            return False
    return True


# ---------------------------------------------------------------------------
# pure parser
# ---------------------------------------------------------------------------

def test_parse_section_spec():
    from PyReconstruct.modules.gui.dialog.copy_to_sections import parse_section_spec
    valid = {0, 1, 2, 3, 4}

    assert parse_section_spec("1-3, 4", valid) == ({1, 2, 3, 4}, [], [])
    assert parse_section_spec("2", valid) == ({2}, [], [])
    assert parse_section_spec("0 2 4", valid) == ({0, 2, 4}, [], [])
    # reversed range is normalised
    assert parse_section_spec("3-1", valid) == ({1, 2, 3}, [], [])

    # bad / out-of-range tokens are reported and excluded
    chosen, bad, missing = parse_section_spec("7", valid)
    assert chosen == set() and bad == ["7"] and missing == []
    chosen, bad, missing = parse_section_spec("abc", valid)
    assert chosen == set() and bad == ["abc"] and missing == []
    chosen, bad, missing = parse_section_spec("1-", valid)
    assert chosen == set() and bad == ["1-"] and missing == []
    chosen, bad, missing = parse_section_spec("1-2-3", valid)
    assert chosen == set() and bad == ["1-2-3"] and missing == []
    # a whole range out of range is bad
    chosen, bad, missing = parse_section_spec("10-20", valid)
    assert chosen == set() and bad == ["10-20"] and missing == []
    # good and bad mixed
    chosen, bad, missing = parse_section_spec("2, nope, 4", valid)
    assert chosen == {2, 4} and bad == ["nope"] and missing == []


def test_parse_section_spec_overhanging_range_is_surfaced():
    """A range that overhangs the valid set still yields the sections that
    exist, but the nonexistent remainder is reported, not silently dropped."""
    from PyReconstruct.modules.gui.dialog.copy_to_sections import parse_section_spec
    valid = {0, 1, 2, 3, 4}

    chosen, bad, missing = parse_section_spec("3-7", valid)
    assert chosen == {3, 4}
    assert bad == []
    assert len(missing) == 1
    # 5, 6, 7 do not exist
    assert "3" in missing[0] and "7" in missing[0] and "3 " in missing[0]

    # a range interrupted by a gap in the section numbering is surfaced too
    chosen, bad, missing = parse_section_spec("0-4", {0, 1, 3, 4})
    assert chosen == {0, 1, 3, 4}
    assert bad == []
    assert len(missing) == 1 and "1 " in missing[0]


def test_parse_section_spec_huge_range_returns_fast():
    """A huge typed upper bound must not materialize the range (UI hang)."""
    import time
    from PyReconstruct.modules.gui.dialog.copy_to_sections import parse_section_spec
    valid = set(range(100))

    start = time.monotonic()
    chosen, bad, missing = parse_section_spec("1-999999999", valid)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, f"huge range took {elapsed:.2f}s (range materialized?)"
    assert chosen == set(range(1, 100))
    assert bad == []
    assert len(missing) == 1  # the nonexistent 100..999999999 remainder


def test_parse_section_spec_exotic_unicode_digits_do_not_crash():
    """Characters where str.isdigit() is True but int() raises (superscripts,
    circled digits) must be reported as bad tokens, not crash the parser."""
    from PyReconstruct.modules.gui.dialog.copy_to_sections import parse_section_spec
    valid = {0, 1, 2, 3, 4}

    # single-number path
    chosen, bad, missing = parse_section_spec("5²", valid)  # "5²"
    assert chosen == set() and bad == ["5²"]
    chosen, bad, missing = parse_section_spec("①", valid)  # "①"
    assert chosen == set() and bad == ["①"]

    # range-endpoint path
    chosen, bad, missing = parse_section_spec("1-5²", valid)
    assert chosen == set() and bad == ["1-5²"]
    chosen, bad, missing = parse_section_spec("³-4", valid)  # "³-4"
    assert chosen == set() and bad == ["³-4"]

    # good tokens alongside exotic ones still parse
    chosen, bad, missing = parse_section_spec("2, 5²", valid)
    assert chosen == {2} and bad == ["5²"]


# ---------------------------------------------------------------------------
# data-model copy
# ---------------------------------------------------------------------------

def test_copy_preserves_field_xy_and_attributes(tmp_path):
    series = _load_series(tmp_path)

    # targets have real, distinct, non-identity transforms in this fixture
    for snum in (2, 4):
        _unlock(series, snum)

    ft = _field_trace(series, 0, "star")

    before = {}
    for snum in (2, 4):
        before[snum] = len(series.loadSection(snum).contours["star"].getTraces())

    copied_to, skipped = series.copyTracesToSections(
        [ft], {2, 4}, log_event=False
    )

    assert sorted(copied_to) == [2, 4]
    assert skipped == []

    for snum in (2, 4):
        section = series.loadSection(snum)
        traces = section.contours["star"].getTraces()
        # exactly one trace added
        assert len(traces) == before[snum] + 1
        # the added trace sits at the SAME field x-y (re-projected through this
        # section's own transform) and keeps every attribute
        match = [t for t in traces if _mapped_matches(section, t, FIELD_PTS)]
        assert len(match) == 1, f"no field-matching trace on section {snum}"
        copied = match[0]
        assert copied.name == "star"
        assert tuple(copied.color) == tuple(ft.color)
        assert copied.closed == ft.closed
        assert "copytest" in copied.tags


def test_copies_onto_locked_sections(tmp_path):
    """A lock protects a section's transform, not its trace content, so a
    locked target section still receives the copied trace."""
    series = _load_series(tmp_path)

    # section 1 stays locked (fixture default); section 2 is unlocked
    _unlock(series, 2)
    assert series.loadSection(1).align_locked is True

    locked_before = len(series.loadSection(1).contours["star"].getTraces())
    unlocked_before = len(series.loadSection(2).contours["star"].getTraces())

    ft = _field_trace(series, 0, "star")

    copied_to, skipped = series.copyTracesToSections(
        [ft], {1, 2}, log_event=False
    )

    assert sorted(copied_to) == [1, 2]
    assert skipped == []

    # locked section received the trace at the shared field x-y, lock intact
    locked_section = series.loadSection(1)
    assert locked_section.align_locked is True
    assert len(locked_section.contours["star"].getTraces()) == locked_before + 1
    assert any(
        _mapped_matches(locked_section, t, FIELD_PTS)
        for t in locked_section.contours["star"].getTraces()
    )
    # unlocked section received the trace too
    assert len(series.loadSection(2).contours["star"].getTraces()) == unlocked_before + 1


def test_identity_transform_copies_points_verbatim(tmp_path):
    """When source and target share the same transform, the stored points are
    identical (the field re-projection collapses to a copy)."""
    series = _load_series(tmp_path)

    # section 0 has the identity transform; give the target the identity too
    target = series.loadSection(3)
    from PyReconstruct.modules.datatypes.transform import Transform
    target.tform = Transform([1, 0, 0, 0, 1, 0])
    target.align_locked = False
    target.save()

    ft = _field_trace(series, 0, "star")  # points already == FIELD_PTS

    copied_to, skipped = series.copyTracesToSections(
        [ft], {3}, log_event=False
    )
    assert copied_to == [3]
    assert skipped == []

    section = series.loadSection(3)
    match = [
        t for t in section.contours["star"].getTraces()
        if len(t.points) == len(FIELD_PTS)
        and all(abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6
                for a, b in zip(t.points, FIELD_PTS))
    ]
    assert len(match) == 1


def test_copy_lands_at_same_field_xy_under_rotation_and_scale(tmp_path):
    """Targets with rotation and scale in their transforms still receive the
    trace at the identical field x-y (re-projected through each section's own
    inverse transform)."""
    import math
    from PyReconstruct.modules.datatypes.transform import Transform

    series = _load_series(tmp_path)

    # section 2: rotation by 30 degrees plus a translation
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    rot = Transform([c, -s, 1.25, s, c, -0.75])
    # section 4: anisotropic scale plus rotation by -45 degrees
    c2, s2 = math.cos(math.radians(-45)), math.sin(math.radians(-45))
    scl = Transform([1.5 * c2, -1.5 * s2, -2.0, 0.8 * s2, 0.8 * c2, 3.0])

    for snum, tform in ((2, rot), (4, scl)):
        section = series.loadSection(snum)
        section.tform = tform
        section.align_locked = False
        section.save()

    ft = _field_trace(series, 0, "star")

    copied_to, skipped = series.copyTracesToSections(
        [ft], {2, 4}, log_event=False
    )
    assert sorted(copied_to) == [2, 4]
    assert skipped == []

    for snum in (2, 4):
        section = series.loadSection(snum)
        match = [
            t for t in section.contours["star"].getTraces()
            if _mapped_matches(section, t, FIELD_PTS)
        ]
        assert len(match) == 1, (
            f"trace on section {snum} did not land at the shared field x-y"
        )
        # the stored points differ from the field points (the transform is
        # non-identity), proving a real re-projection happened
        stored = match[0].points
        assert any(
            abs(a[0] - b[0]) > 1e-6 or abs(a[1] - b[1]) > 1e-6
            for a, b in zip(stored, FIELD_PTS)
        )


def test_non_invertible_target_transform_is_skipped(tmp_path):
    """A singular (non-invertible) target transform cannot place the trace:
    the section is skipped and reported, never crashed on or written to."""
    from PyReconstruct.modules.datatypes.transform import Transform

    series = _load_series(tmp_path)

    for snum in (2, 3):
        _unlock(series, snum)

    # det = 1*1 - 1*1 = 0: singular
    singular = Transform([1, 1, 0, 1, 1, 0])
    section = series.loadSection(3)
    section.tform = singular
    section.save()

    before = len(series.loadSection(3).contours["star"].getTraces())

    ft = _field_trace(series, 0, "star")

    copied_to, skipped = series.copyTracesToSections(
        [ft], {2, 3}, log_event=False
    )

    assert copied_to == [2]
    assert skipped == [3]
    # the singular section was not written to
    assert len(series.loadSection(3).contours["star"].getTraces()) == before


def test_all_invalid_targets_noop(tmp_path):
    """Requesting only nonexistent sections must no-op gracefully (this
    exercises the empty-subset SeriesIterator, which used to divide by zero)."""
    series = _load_series(tmp_path)

    ft = _field_trace(series, 0, "star")

    copied_to, skipped = series.copyTracesToSections(
        [ft], {9998, 9999}, log_event=False
    )

    assert copied_to == []
    assert skipped == []


def test_series_iterator_empty_subset_completes(tmp_path):
    """enumerateSections over an empty subset iterates zero times instead of
    raising ZeroDivisionError in the progress computation."""
    series = _load_series(tmp_path)

    visited = [
        snum for snum, _ in series.enumerateSections(section_numbers=set())
    ]
    assert visited == []
