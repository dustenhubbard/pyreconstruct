"""Tests for the data clean-up operations (Series menu "Clean up", issue #67).

Three operations, all built on the proven series-states bulk-edit path so each
is a single undoable action with a progress bar:

  * Remove duplicate traces  -> Series.deleteDuplicateTraces (pre-existing;
    same-name + geometrically-coincident only). Guarded here against the
    false positive of merging two *distinct* objects that happen to coincide.
  * Remove pixel-dust traces -> Series.findPixelDustTraces (scan) + a review
    list that deletes via Series.deleteMalformedTraces. Small closed traces at
    or below an area threshold (um^2); large traces and zero-area/degenerate
    traces are NOT flagged.
  * Remove empty traces      -> Series.findEmptyTraces (scan) + the same
    signature-based delete. Zero-area closed / zero-length open / no-point
    traces only; real traces (including small pixel-dust) are NOT flagged.

Everything runs end-to-end against the real shapes1.jser fixture with synthetic
traces layered on, plus a real SeriesStates to prove single-undo restoration.
"""
import os
import shutil

import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)


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
    """A real closed trace from the section, to clone attributes from."""
    for cname in section.contours:
        for trace in section.contours[cname]:
            if trace.closed and len(trace.points) >= 3:
                return trace
    pytest.skip("no closed trace in fixture section")


def _make(section, name, points, closed=True):
    """Clone a real trace's attributes with new name/points, add + save."""
    t = _template_trace(section).copy()
    t.name = name
    t.points = list(points)
    t.closed = closed
    section.addTrace(t, log_event=False)
    return t


def _snum_with_closed(series):
    """First section number that has a usable closed template trace."""
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        for cname in section.contours:
            for trace in section.contours[cname]:
                if trace.closed and len(trace.points) >= 3:
                    return snum
    pytest.skip("no closed trace anywhere in fixture")


def _new_states(series):
    from PyReconstruct.modules.backend.func.state_manager import SeriesStates
    return SeriesStates(series)


def _count(series, snum, name):
    return len(series.loadSection(snum).contours.get(name, []))


# ---------------------------------------------------------------------------
# pixel-dust
# ---------------------------------------------------------------------------

def test_pixel_dust_flags_only_small_closed_traces(tmp_path):
    """A tiny closed trace is flagged; a large one and an open one are not."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)

    _make(section, "DUST", [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)])
    _make(section, "BIG", [(0, 0), (50, 0), (50, 50), (0, 50)])
    _make(section, "LINE", [(0, 0), (0.1, 0), (0.2, 0)], closed=False)
    section.save()

    from PyReconstruct.modules.datatypes.series import Series
    reloaded = series.loadSection(snum)
    dust_area = Series._traceArea(reloaded.contours["DUST"][0], reloaded.tform)
    big_area = Series._traceArea(reloaded.contours["BIG"][0], reloaded.tform)
    assert 0 < dust_area < big_area

    threshold = (dust_area + big_area) / 2
    records = series.findPixelDustTraces(threshold)
    names = {r["name"] for r in records}
    assert "DUST" in names
    assert "BIG" not in names        # above threshold
    assert "LINE" not in names       # open trace, no area
    # every record carries the area used for display + a delete signature
    dust_rec = next(r for r in records if r["name"] == "DUST")
    assert dust_rec["area"] == pytest.approx(dust_area)
    assert "match" in dust_rec and dust_rec["points"] == 4


def test_pixel_dust_threshold_is_inclusive_edge(tmp_path):
    """A trace exactly at the threshold is flagged; just below the area is not."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "DUST", [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)])
    section.save()

    from PyReconstruct.modules.datatypes.series import Series
    area = Series._traceArea(
        series.loadSection(snum).contours["DUST"][0],
        series.loadSection(snum).tform,
    )
    # exactly at area -> inclusive hit
    assert {r["name"] for r in series.findPixelDustTraces(area)} >= {"DUST"}
    # strictly below -> miss
    assert "DUST" not in {r["name"] for r in series.findPixelDustTraces(area * 0.99)}


def test_pixel_dust_scan_does_not_modify(tmp_path):
    """Scanning never removes anything; only an explicit delete does."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "DUST", [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)])
    section.save()

    series.findPixelDustTraces(1e9)  # huge threshold, would match everything
    assert _count(series, snum, "DUST") == 1, "scan must not delete"


def test_pixel_dust_skips_locked_unless_included(tmp_path):
    """Locked objects are excluded from candidates by default."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "DUST", [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)])
    section.save()
    series.setAttr("DUST", "locked", True)

    assert "DUST" not in {r["name"] for r in series.findPixelDustTraces(1e9)}
    assert "DUST" in {
        r["name"] for r in series.findPixelDustTraces(1e9, include_locked=True)
    }


def test_pixel_dust_delete_is_single_undo(tmp_path):
    """Deleting flagged dust across sections undoes in one step."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "DUST", [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)])
    section.save()

    from PyReconstruct.modules.datatypes.series import Series
    area = Series._traceArea(
        series.loadSection(snum).contours["DUST"][0],
        series.loadSection(snum).tform,
    )
    records = series.findPixelDustTraces(area * 1.5)
    assert records

    states = _new_states(series)
    deleted = series.deleteMalformedTraces(records, series_states=states)
    assert len(deleted) == len(records)
    assert _count(series, snum, "DUST") == 0

    can, _, _ = states.canUndo()
    assert can
    states.undoState()
    assert _count(series, snum, "DUST") == 1, "undo restores the dust trace"


def test_pixel_dust_delete_across_sections_single_undo(tmp_path):
    """Dust on several sections is removed and restored by ONE series undo."""
    series = _load_series(tmp_path)
    dust_pts = [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)]
    snums = sorted(series.sections)[:3]
    for snum in snums:
        section = series.loadSection(snum)
        _make(section, "DUST", dust_pts)
        section.save()

    records = series.findPixelDustTraces(1e6)
    touched = {r["section"] for r in records if r["name"] == "DUST"}
    assert touched == set(snums), "dust found on every seeded section"

    states = _new_states(series)
    series.deleteMalformedTraces(
        [r for r in records if r["name"] == "DUST"], series_states=states
    )
    for snum in snums:
        assert _count(series, snum, "DUST") == 0

    states.undoState()  # single undo
    for snum in snums:
        assert _count(series, snum, "DUST") == 1, \
            f"one undo must restore dust on section {snum}"


# ---------------------------------------------------------------------------
# empty / degenerate
# ---------------------------------------------------------------------------

def test_empty_flags_degenerate_only(tmp_path):
    """Zero-area closed and zero-length open traces are flagged; real ones not."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)

    _make(section, "COLLINEAR", [(0, 0), (1, 1), (2, 2)])       # closed, area 0
    _make(section, "ZEROLEN", [(5, 5), (5, 5)], closed=False)    # open, length 0
    _make(section, "DUST", [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)])  # real area
    _make(section, "BIG", [(0, 0), (50, 0), (50, 50), (0, 50)])
    section.save()

    names = {r["name"] for r in series.findEmptyTraces()}
    assert "COLLINEAR" in names
    assert "ZEROLEN" in names
    assert "DUST" not in names   # tiny but non-zero area -> pixel dust, not empty
    assert "BIG" not in names


def test_empty_delete_is_single_undo(tmp_path):
    """Removing empty traces is one undoable operation."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "COLLINEAR", [(0, 0), (1, 1), (2, 2)])
    section.save()

    records = series.findEmptyTraces()
    assert {r["name"] for r in records} >= {"COLLINEAR"}

    states = _new_states(series)
    deleted = series.deleteMalformedTraces(records, series_states=states)
    assert _count(series, snum, "COLLINEAR") == 0

    states.undoState()
    assert _count(series, snum, "COLLINEAR") == 1


def test_empty_skips_locked(tmp_path):
    """Locked objects are never flagged as empty."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "COLLINEAR", [(0, 0), (1, 1), (2, 2)])
    section.save()
    series.setAttr("COLLINEAR", "locked", True)
    assert "COLLINEAR" not in {r["name"] for r in series.findEmptyTraces()}


# ---------------------------------------------------------------------------
# duplicates (pre-existing op) + false-positive guard
# ---------------------------------------------------------------------------

def test_duplicate_removal_and_undo(tmp_path):
    """Two identical traces of the SAME object collapse to one, undoably."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
    _make(section, "DUPE", pts)
    _make(section, "DUPE", list(pts))  # exact duplicate, same name
    section.save()
    assert _count(series, snum, "DUPE") == 2

    states = _new_states(series)
    removed = series.deleteDuplicateTraces(0.95, series_states=states)
    assert snum in removed and "DUPE" in removed[snum]
    assert _count(series, snum, "DUPE") == 1

    states.undoState()
    assert _count(series, snum, "DUPE") == 2, "undo restores the duplicate"


def test_duplicate_removal_does_not_merge_distinct_objects(tmp_path):
    """Two coincident traces with DIFFERENT names are not duplicates.

    This is the key false-positive guard: legitimately-overlapping distinct
    objects must survive, because duplicate detection is scoped per object
    name (per contour), never geometry-only across objects.
    """
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
    _make(section, "OBJ_A", pts)
    _make(section, "OBJ_B", list(pts))  # identical geometry, different object
    section.save()

    states = _new_states(series)
    series.deleteDuplicateTraces(0.95, series_states=states)
    assert _count(series, snum, "OBJ_A") == 1
    assert _count(series, snum, "OBJ_B") == 1
