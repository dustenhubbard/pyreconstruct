"""The import/export findings from the review fleet (2026-08-28).

Every test here fails against the code as it stood: silently dropped ROI
exports, crashed or distorted ROI imports, a leaked temp descriptor, a
success notice for exports that never happened, and autoseg's section/z
conflation. Grouped in one file because they share a theme: the boundary
where the app talks to other tools is where errors went quietest.
"""

import os

import numpy as np
import pytest

pytestmark = pytest.mark.gui


# --- ROI export -----------------------------------------------------------------

def test_every_trace_of_a_contour_gets_its_own_roi_file(tmp_path):
    pytest.importorskip("roifile")
    from PyReconstruct.modules.backend.exports.roi_export import RoiExporter
    from PyReconstruct.modules.datatypes import Trace

    written = []
    for i in range(3):
        trace = Trace("axon7", (255, 0, 0), closed=True)
        trace.points = [(i, 0.0), (i + 1.0, 0.0), (i + 1.0, 1.0)]
        written.append(RoiExporter(trace, 0.002, 100).export_roi(tmp_path))

    assert len(set(written)) == 3, "same-named traces overwrote one file"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        p.name for p in written
    )


def test_the_exporter_refuses_to_half_construct(monkeypatch):
    from PyReconstruct.modules.backend.exports import roi_export
    from PyReconstruct.modules.datatypes import Trace

    monkeypatch.setattr(roi_export, "modules_available", lambda *a, **k: False)
    trace = Trace("axon7", (255, 0, 0), closed=True)
    trace.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]

    with pytest.raises(ModuleNotFoundError):
        roi_export.RoiExporter(trace, 0.002, 100)


# --- ROI import -----------------------------------------------------------------

def _roi_from_points(points, roitype):
    roifile = pytest.importorskip("roifile")
    roi = roifile.ImagejRoi.frompoints(points)
    roi.roitype = roitype
    return roi


def _import_roi(tmp_path, points, roitype):
    from PyReconstruct.modules.backend.imports.imagej_roi import Roi

    fp = tmp_path / "probe.roi"
    _roi_from_points(points, roitype).tofile(str(fp))
    return Roi(str(fp))


def test_an_open_polyline_keeps_its_endpoints(tmp_path):
    roifile = pytest.importorskip("roifile")
    roi = _import_roi(
        tmp_path,
        [(0.0, 50.0), (25.0, 50.0), (50.0, 50.0), (75.0, 50.0), (100.0, 50.0)],
        roifile.ROI_TYPE.POLYLINE,
    )
    assert roi.closed is False

    coords = roi.get_field_coordinates(img_height=100, mag=1.0)
    xs = [x for x, y in coords]
    # A periodic spline bent this straight line into a loop: the evaluated
    # points swung back toward x=0 and the true endpoint at x=100 was lost.
    assert max(xs) > 95
    assert xs[0] == pytest.approx(0.0, abs=1.0)
    assert xs[-1] == pytest.approx(100.0, abs=1.0)


def test_a_point_roi_imports_without_crashing(tmp_path):
    roifile = pytest.importorskip("roifile")
    roi = _import_roi(tmp_path, [(10.0, 20.0)], roifile.ROI_TYPE.POINT)
    assert roi.closed is False

    coords = roi.get_field_coordinates(img_height=100, mag=0.5)
    assert coords == [(5.0, 40.0)]


def test_a_two_point_line_imports_without_crashing(tmp_path):
    # POLYLINE, not LINE: roifile stores a true LINE roi's endpoints outside
    # the points list, so a frompoints round-trip cannot build one. A two-
    # point polyline hits the same too-short-to-spline path the finding
    # names (the old code force-closed it and crashed the cubic spline).
    roifile = pytest.importorskip("roifile")
    roi = _import_roi(
        tmp_path, [(0.0, 0.0), (10.0, 10.0)], roifile.ROI_TYPE.POLYLINE
    )
    assert roi.closed is False
    coords = roi.get_field_coordinates(img_height=100, mag=1.0)
    # too short to smooth: imported as its own two points, not crashed at k=3
    assert coords == [(0.0, 100.0), (10.0, 90.0)]


def test_a_closed_roi_closes_first_against_last(tmp_path):
    roifile = pytest.importorskip("roifile")
    # already closed: first == last; the old first-vs-second check appended a
    # redundant duplicate here
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 0.0)]
    roi = _import_roi(tmp_path, pts, roifile.ROI_TYPE.POLYGON)
    assert roi.closed is True
    coords = roi.get_field_coordinates(img_height=100, mag=1.0)
    assert len(coords) == 100          # splined cleanly, no duplicate crash


def test_the_importer_refuses_to_half_construct(monkeypatch, tmp_path):
    from PyReconstruct.modules.backend.imports import imagej_roi

    monkeypatch.setattr(imagej_roi, "modules_available", lambda *a, **k: False)
    with pytest.raises(ModuleNotFoundError):
        imagej_roi.Roi(str(tmp_path / "whatever.roi"))


# --- the PNG export's temp file ---------------------------------------------------

def test_a_failed_png_export_leaves_no_temp_svg(monkeypatch, tmp_path):
    from PyReconstruct.modules.backend.exports import svg_conversion

    made = []
    real_mkstemp = svg_conversion.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        fd, fp = real_mkstemp(*args, **kwargs)
        made.append(fp)
        return fd, fp

    def exploding_export_svg(*args, **kwargs):
        raise RuntimeError("svg writing failed")

    monkeypatch.setattr(svg_conversion, "mkstemp", tracking_mkstemp)
    monkeypatch.setattr(svg_conversion, "export_svg", exploding_export_svg)

    with pytest.raises(RuntimeError):
        svg_conversion.export_png(None, str(tmp_path / "out.png"))

    assert made, "the temp file was never created"
    for fp in made:
        assert not os.path.exists(fp), "the temp svg outlived the failure"


# --- autoseg: sections are not z-indices -------------------------------------------

def test_import_section_never_wraps_to_another_slice(real_series, monkeypatch):
    """A section below the labels window must be SKIPPED, not wrapped.

    z - z_offset used to go negative for it, and a negative zarr index wraps
    to the far end of the array: the worker silently imported another
    section's labels (found 2026-08-28).
    """
    from PyReconstruct.modules.backend.autoseg import conversions

    touched = []

    class RecordingArray:
        shape = (5, 10, 10)
        attrs = {
            "voxel_size": [50, 8, 8], "offset": [100, 0, 0],
            "window": [0, 0, 1, 1], "sections": list(range(0, 8)),
            "true_mag": 0.008, "alignment": {str(n): [1, 0, 0, 0, 1, 0] for n in range(8)},
        }

        def __getitem__(self, z):
            touched.append(z)
            return np.zeros((10, 10), dtype=np.uint64)

    arr = RecordingArray()
    monkeypatch.setattr(conversions, "get_zarr_array", lambda zg, name: arr)

    # z_offset = 100/50 = 2. Section 0 has z index 0, zi = -2: must be skipped.
    conversions.importSection(None, "labels_test", 0, real_series)
    assert touched == [], f"a negative z reached the array: {touched}"

    # Section 2 (z=2, zi=0) is in range and may be read.
    conversions.importSection(None, "labels_test", 2, real_series)
    assert touched == [0]


def test_labels_to_objects_iterates_real_section_numbers(monkeypatch, real_series):
    from PyReconstruct.modules.backend.autoseg import conversions

    scheduled = []

    class FakePool:
        def createWorker(self, fn, *args):
            scheduled.append(args[2])   # the snum argument

        def startAll(self, *a, **k):
            pass

    sections = [5, 6, 7, 9]             # real exports skip the cal grid
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", FakePool)
    monkeypatch.setattr(conversions, "setDT", lambda: None)
    monkeypatch.setattr(
        conversions, "getLabelsToObjectsData",
        lambda fp, group: (None, sections, 2),
    )

    conversions.labelsToObjects(real_series, "unused.zarr", "labels_test")

    assert scheduled == sections, (
        "the import loop must walk the zarr's section numbers, not "
        "range(z_offset, max+1)"
    )


def test_series_to_zarr_refuses_to_delete_a_non_zarr(tmp_path, real_series):
    from PyReconstruct.modules.backend.autoseg.conversions import seriesToZarr

    victim = tmp_path / "project"
    victim.mkdir()
    (victim / "precious.txt").write_text("do not delete")

    with pytest.raises(ValueError, match="does not"):
        seriesToZarr(
            real_series, [0], 0.008, [0.0, 0.0, 1.0, 1.0],
            data_fp=str(victim),
        )

    assert (victim / "precious.txt").exists()


def test_groups_to_volume_names_the_empty_group(real_series):
    from PyReconstruct.modules.backend.autoseg.conversions import groupsToVolume

    with pytest.raises(ValueError, match="no_such_group"):
        groupsToVolume(real_series, groups=["no_such_group"])
