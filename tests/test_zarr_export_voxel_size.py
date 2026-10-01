"""Zarr export keeps fractional nanometer voxel sizes (fork #603).

``seriesToZarr`` wrote ``voxel_size`` with ``int(mag * 1000)``, so 2.54 nm
pixels were stored as 2 nm and 0.5 nm pixels as 0, and importing labels back
from a 0 nm Zarr divided by zero. Whole nanometer sizes stay ints, as before.
"""
import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg import conversions


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


@pytest.fixture
def export(tmp_path, real_series, monkeypatch):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    ## the images are not what this is about
    monkeypatch.setattr(conversions, "exportSection", lambda *a, **k: None)
    sections = sorted(real_series.sections)[1:3]

    def run(mag):
        out = tmp_path / f"{mag}.zarr"
        conversions.seriesToZarr(
            real_series, sections, mag, [0.0, 0.0, 0.05, 0.05], data_fp=str(out)
        )
        return zarr.open(str(out), "r+")

    return real_series, sections, run


@pytest.mark.parametrize(
    "mag, xy_nm",
    [(0.00254, 2.54), (0.0005, 0.5), (0.00125, 1.25)],
)
def test_fractional_voxel_size_is_kept(export, mag, xy_nm):
    series, sections, run = export
    raw = run(mag)["raw"]

    z, y, x = raw.attrs["voxel_size"]
    assert (y, x) == (pytest.approx(xy_nm), pytest.approx(xy_nm))
    thickness = series.loadSection(sections[0]).thickness
    assert z == pytest.approx(thickness * 1000)
    assert conversions.get_voxel_size_um(raw)[-1] == pytest.approx(mag)


@pytest.mark.parametrize("mag, xy_nm", [(0.002, 2), (0.004, 4), (0.008, 8)])
def test_whole_voxel_size_is_still_an_int(export, mag, xy_nm):
    _, _, run = export
    voxel_size = run(mag)["raw"].attrs["voxel_size"]

    assert voxel_size[1:] == [xy_nm, xy_nm]
    assert all(type(v) is int for v in voxel_size)


def test_labels_import_back_from_a_sub_nanometer_zarr(export):
    series, sections, run = export
    zg = run(0.0005)
    raw = zg["raw"]
    labels = zg.create_dataset("labels_x", shape=raw.shape, dtype=np.uint64)
    labels[1, 20:40, 20:40] = 7
    labels.attrs["offset"] = [0, 0, 0]
    labels.attrs["voxel_size"] = raw.attrs["voxel_size"]

    conversions.setDT()
    conversions.importSection(zg, "labels_x", sections[1], series)

    assert "autoseg_7" in series.loadSection(sections[1]).contours
