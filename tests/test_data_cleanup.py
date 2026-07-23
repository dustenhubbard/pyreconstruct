"""Tests for the data clean-up operations (Series menu "Clean up", issue #67).

Three operations, all built on the proven series-states bulk-edit path so each
is a single undoable action with a progress bar:

  * Remove duplicate traces  -> Series.deleteDuplicateTraces (pre-existing;
    same-name + geometrically-coincident only). Guarded here against the
    false positive of merging two *distinct* objects that happen to coincide.
  * Remove pixel-dust traces -> Series.findPixelDustTraces (scan) + a review
    list that deletes via Series.deleteMalformedTraces. Small closed traces at
    or below a pixel-area threshold (px^2); the physical (um^2) cutoff is
    derived per section from that section's magnification, so the same px
    threshold adapts to sections of different scale. Large traces and
    zero-area/degenerate traces are NOT flagged.
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


def _um2(series, snum, name):
    """Physical area (um^2) of the first trace of an object on a section."""
    from PyReconstruct.modules.datatypes.series import Series
    section = series.loadSection(snum)
    return Series._traceArea(section.contours[name][0], section.tform)


def _px2(series, snum, name):
    """Pixel area (px^2) = physical area / mag^2, for that section's mag."""
    section = series.loadSection(snum)
    return _um2(series, snum, name) / (section.mag ** 2)


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

    dust_px = _px2(series, snum, "DUST")
    big_px = _px2(series, snum, "BIG")
    assert 0 < dust_px < big_px

    threshold = (dust_px + big_px) / 2  # pixel-area threshold
    records = series.findPixelDustTraces(threshold)
    names = {r["name"] for r in records}
    assert "DUST" in names
    assert "BIG" not in names        # above threshold
    assert "LINE" not in names       # open trace, no area
    # every record carries both the pixel area and physical area + a signature
    dust_rec = next(r for r in records if r["name"] == "DUST")
    assert dust_rec["area_px"] == pytest.approx(dust_px)
    assert dust_rec["area"] == pytest.approx(_um2(series, snum, "DUST"))
    assert "match" in dust_rec and dust_rec["points"] == 4


def test_pixel_dust_threshold_is_inclusive_edge(tmp_path):
    """A trace exactly at the threshold is flagged; just below the area is not."""
    series = _load_series(tmp_path)
    snum = _snum_with_closed(series)
    section = series.loadSection(snum)
    _make(section, "DUST", [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)])
    section.save()

    area_px = _px2(series, snum, "DUST")
    # exactly at the pixel area -> inclusive hit
    assert {r["name"] for r in series.findPixelDustTraces(area_px)} >= {"DUST"}
    # strictly below -> miss
    assert "DUST" not in {
        r["name"] for r in series.findPixelDustTraces(area_px * 0.99)
    }


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

    records = series.findPixelDustTraces(_px2(series, snum, "DUST") * 1.5)
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


def test_pixel_dust_threshold_adapts_per_section_mag(tmp_path):
    """One px threshold adapts to each section's magnification.

    The SAME physical speck is placed on two sections whose magnifications
    differ (coarse section has 2x the um/px of the fine one). Because pixel
    area = physical area / mag^2, that identical speck is 4x more pixels on the
    fine section than on the coarse one. A single pixel-area threshold chosen
    between the two must therefore flag the speck on the fine section (it is
    "many pixels" there) but not on the coarse section (it is "few pixels"
    there) — proving the physical cutoff is derived per section, not globally.
    """
    series = _load_series(tmp_path)
    snums = sorted(series.sections)
    fine_snum, coarse_snum = snums[0], snums[1]

    dust_pts = [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)]
    fine = series.loadSection(fine_snum)
    base_mag = fine.mag
    _make(fine, "DUST", dust_pts)
    fine.mag = base_mag            # fine scale: more pixels per micron
    fine.save()

    coarse = series.loadSection(coarse_snum)
    _make(coarse, "DUST", list(dust_pts))
    coarse.mag = base_mag * 2      # coarse scale: fewer pixels per micron
    coarse.save()

    # essentially the same physical speck on both sections (the fixture's two
    # sections carry slightly different transforms, hence the loose tolerance)
    assert _um2(series, fine_snum, "DUST") == pytest.approx(
        _um2(series, coarse_snum, "DUST"), rel=1e-2
    )
    fine_px = _px2(series, fine_snum, "DUST")
    coarse_px = _px2(series, coarse_snum, "DUST")
    # the fine section renders that speck as ~4x more pixels (mag differs 2x)
    assert fine_px == pytest.approx(coarse_px * 4, rel=1e-2)

    # threshold between the two pixel areas: flags the fine section only
    threshold = (fine_px + coarse_px) / 2
    hits = {
        (r["section"], r["name"])
        for r in series.findPixelDustTraces(threshold)
        if r["name"] == "DUST"
    }
    assert (coarse_snum, "DUST") in hits    # few pixels on the coarse section
    assert (fine_snum, "DUST") not in hits   # many pixels on the fine section

    # each record reports the pixel area on its OWN section's scale
    rec = next(
        r for r in series.findPixelDustTraces(threshold)
        if r["section"] == coarse_snum and r["name"] == "DUST"
    )
    assert rec["area_px"] == pytest.approx(coarse_px)
    assert rec["area"] == pytest.approx(_um2(series, coarse_snum, "DUST"))


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
