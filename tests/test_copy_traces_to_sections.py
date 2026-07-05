"""Tests for "Copy to sections" (#91).

Covers the data-model operation that places selected trace(s) onto multiple
sections at the same field (x, y) location:

  * Series.copyTracesToSections re-projects field coordinates through each
    target section's own transform, so a trace lands at the identical field
    x-y on every section regardless of that section's alignment.
  * Trace attributes (name, color, closed, tags) are preserved verbatim.
  * Sections whose alignment is locked are skipped and reported.

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

    assert parse_section_spec("1-3, 4", valid) == ({1, 2, 3, 4}, [])
    assert parse_section_spec("2", valid) == ({2}, [])
    assert parse_section_spec("0 2 4", valid) == ({0, 2, 4}, [])
    # reversed range is normalised
    assert parse_section_spec("3-1", valid) == ({1, 2, 3}, [])
    # a range that overhangs the valid set clamps to what exists
    assert parse_section_spec("3-7", valid) == ({3, 4}, [])

    # bad / out-of-range tokens are reported and excluded
    chosen, bad = parse_section_spec("7", valid)
    assert chosen == set() and bad == ["7"]
    chosen, bad = parse_section_spec("abc", valid)
    assert chosen == set() and bad == ["abc"]
    chosen, bad = parse_section_spec("1-", valid)
    assert chosen == set() and bad == ["1-"]
    chosen, bad = parse_section_spec("1-2-3", valid)
    assert chosen == set() and bad == ["1-2-3"]
    # a whole range out of range is bad
    chosen, bad = parse_section_spec("10-20", valid)
    assert chosen == set() and bad == ["10-20"]
    # good and bad mixed
    chosen, bad = parse_section_spec("2, nope, 4", valid)
    assert chosen == {2, 4} and bad == ["nope"]


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


def test_skips_locked_sections(tmp_path):
    series = _load_series(tmp_path)

    # section 1 stays locked (fixture default); section 2 is unlocked
    _unlock(series, 2)

    locked_before = len(series.loadSection(1).contours["star"].getTraces())
    unlocked_before = len(series.loadSection(2).contours["star"].getTraces())

    ft = _field_trace(series, 0, "star")

    copied_to, skipped = series.copyTracesToSections(
        [ft], {1, 2}, log_event=False
    )

    assert copied_to == [2]
    assert skipped == [1]

    # locked section untouched
    assert len(series.loadSection(1).contours["star"].getTraces()) == locked_before
    # unlocked section received the trace
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
    assert copied_to == [3] and skipped == []

    section = series.loadSection(3)
    match = [
        t for t in section.contours["star"].getTraces()
        if len(t.points) == len(FIELD_PTS)
        and all(abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6
                for a, b in zip(t.points, FIELD_PTS))
    ]
    assert len(match) == 1
