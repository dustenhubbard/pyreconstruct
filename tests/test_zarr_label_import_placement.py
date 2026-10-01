"""Zarr label import at a label size other than raw's (fork #606), and from a
Zarr that carries no voxel size at all (fork #607).

``exterior_to_points`` flipped y around the height of raw counted in raw
pixels, while the points it flipped are in label pixels. Labels coarser or
finer than raw came in at the right x and the wrong y.

``zarrToNewSeries`` already fell back to 4 nm pixels when raw had no voxel
size, but ``get_thickness`` raised ``KeyError``, and the label import read
each labels array's ``voxel_size`` and ``offset`` the same way.
"""
import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg import conversions
from PyReconstruct.modules.datatypes import Transform


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


def _bounds(section, name):
    pts = np.array([p for trace in section.contours[name] for p in trace.points])
    return pts[:, 0].min(), pts[:, 0].max(), pts[:, 1].min(), pts[:, 1].max()


@pytest.mark.parametrize("label_nm", [2, 4, 8])
def test_labels_land_on_the_same_spot_at_any_label_size(tmp_path, real_series, label_nm):
    """Raw is 100 by 100 px at 4 nm (0.4 µm across). The labels mark raw rows
    and columns 20 to 40 at their own pixel size, so every size should give
    the trace of the same square.
    """
    snum = sorted(real_series.sections)[1]
    zg = zarr.open(str(tmp_path / "labels.zarr"), "w")
    raw = zg.create_dataset("raw", shape=(1, 100, 100), dtype=np.uint8)
    raw.attrs.update({
        "voxel_size": [50, 4, 4], "offset": [0, 0, 0],
        "true_mag": 0.004, "window": [0, 0, 0.4, 0.4], "sections": [snum],
        "alignment": {str(snum): Transform.identity().getList()},
    })
    n = 400 // label_nm
    lo, hi = 80 // label_nm, 160 // label_nm
    labels = zg.create_dataset("labels_x", shape=(1, n, n), dtype=np.uint64)
    labels[0, lo:hi, lo:hi] = 7
    labels.attrs.update({"voxel_size": [50, label_nm, label_nm], "offset": [0, 0, 0]})

    conversions.setDT()
    conversions.importSection(zg, "labels_x", snum, real_series)

    ## the outline runs through the centers of the edge pixels, and y counts
    ## up from the bottom of the 0.4 µm image
    step = label_nm / 1000
    x0, x1, y0, y1 = _bounds(real_series.loadSection(snum), "autoseg_7")
    assert (x0, x1) == (pytest.approx(lo * step), pytest.approx((hi - 1) * step))
    assert (y0, y1) == (
        pytest.approx(0.4 - (hi - 1) * step), pytest.approx(0.4 - lo * step)
    )


def test_thickness_defaults_without_a_voxel_size():
    raw = zarr.zeros((2, 8, 8), dtype=np.uint8)

    assert conversions.get_thickness(raw) == pytest.approx(0.05)


def test_new_series_from_a_zarr_with_no_attributes(tmp_path, monkeypatch):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    fp = str(tmp_path / "plain.zarr")
    zg = zarr.open(fp, "w")
    zg.create_dataset("raw", data=np.full((2, 32, 32), 9, dtype=np.uint8))
    labels = np.zeros((2, 32, 32), dtype=np.uint64)
    labels[:, 8:16, 8:16] = 3
    zg.create_dataset("labels_cells", data=labels)

    series = conversions.zarrToNewSeries(fp, ["labels_cells"], "fresh")
    try:
        for snum in (0, 1):
            section = series.loadSection(snum)
            assert section.mag == pytest.approx(0.004)
            assert section.thickness == pytest.approx(0.05)
            ## rows and columns 8 to 15 of 32 at the default 4 nm
            x0, x1, y0, y1 = _bounds(section, "autoseg_3")
            assert (x0, x1) == (pytest.approx(0.032), pytest.approx(0.060))
            assert (y0, y1) == (pytest.approx(0.068), pytest.approx(0.096))
    finally:
        series.close()


def _new_series(tmp_path, monkeypatch, labels, **label_attrs):
    """A new series from a 2 by 32 by 32 raw with no attributes."""
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    fp = str(tmp_path / "plain.zarr")
    zg = zarr.open(fp, "w")
    zg.create_dataset("raw", data=np.full((2, 32, 32), 9, dtype=np.uint8))
    zg.create_dataset("labels_cells", data=labels).attrs.update(label_attrs)
    return conversions.zarrToNewSeries(fp, ["labels_cells"], "fresh")


def test_labels_with_a_voxel_size_over_raw_without_one(tmp_path, monkeypatch):
    """Raw falls back to 4 nm pixels, so 8 nm labels cover it at half the
    size. Label rows and columns 4 to 7 are raw's 8 to 15.
    """
    labels = np.zeros((2, 16, 16), dtype=np.uint64)
    labels[:, 4:8, 4:8] = 3

    series = _new_series(
        tmp_path, monkeypatch, labels, voxel_size=[50, 8, 8], offset=[0, 0, 0]
    )
    try:
        for snum in (0, 1):
            x0, x1, y0, y1 = _bounds(series.loadSection(snum), "autoseg_3")
            assert (x0, x1) == (pytest.approx(0.032), pytest.approx(0.056))
            assert (y0, y1) == (pytest.approx(0.072), pytest.approx(0.096))
    finally:
        series.close()


def test_label_offset_is_in_nm_when_neither_has_a_voxel_size(tmp_path, monkeypatch):
    """A 32 nm offset is 8 pixels at the default 4 nm."""
    labels = np.zeros((2, 16, 16), dtype=np.uint64)
    labels[:, 0:8, 0:8] = 3

    series = _new_series(tmp_path, monkeypatch, labels, offset=[0, 32, 32])
    try:
        for snum in (0, 1):
            x0, x1, y0, y1 = _bounds(series.loadSection(snum), "autoseg_3")
            assert (x0, x1) == (pytest.approx(0.032), pytest.approx(0.060))
            assert (y0, y1) == (pytest.approx(0.068), pytest.approx(0.096))
    finally:
        series.close()
