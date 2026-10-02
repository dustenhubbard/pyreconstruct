"""Neuroglancer export sizes: the whole tissue, ``--mag``, and exact crop offsets.

``create_ng_zarr.py`` took the image size of the first section for every
section, so with all tissue requested a small first image cropped any larger
image after it. It parsed ``-m/--mag`` and then ignored it. ``get_offset``
rounded a label crop's x and y offsets to whole nm, which is up to a pixel at
0.5 nm pixels.

The script tests run the real script in this process on a real series, with
only the progress-bar pool made inline and the dask rechunk skipped.
"""

import runpy
import sys

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
zarr = pytest.importorskip("zarr")

from PyReconstruct.modules.backend import autoseg, imports  # noqa: E402
from PyReconstruct.modules.backend.autoseg import conversions  # noqa: E402
from PyReconstruct.modules.datatypes import Series, Trace  # noqa: E402

MAG = 0.01  # µm per image pixel
SIZES = [400, 200, 400, 300]  # image w and h of sections 0 to 3


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
def sized_jser(tmp_path, qapp):
    images = []
    for i, size in enumerate(SIZES):
        fp = tmp_path / f"img{i}.png"
        cv2.imwrite(str(fp), np.full((size, size, 3), 40 + i, np.uint8))
        images.append(str(fp))

    series = Series.new(images, "sized", MAG, 0.05)
    try:
        trace = Trace("box", (255, 0, 0), closed=True)
        trace.points = [(1.0, 1.0), (1.5, 1.0), (1.5, 1.6), (1.0, 1.6)]
        section = series.loadSection(2)
        section.addTrace(trace, log_event=False)
        section.save()
        series.object_groups.add("g_box", "box")
        series.save()
        jser = tmp_path / "sized.jser"
        series.saveJser(str(jser))
    finally:
        series.close()
    return jser


def _export(monkeypatch, jser, out, *args):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    monkeypatch.setattr(imports, "modules_available", lambda *a, **k: True)
    monkeypatch.setattr(autoseg, "rechunk", lambda *a, **k: True)
    monkeypatch.setattr(sys, "argv", [
        "create_ng_zarr.py", str(jser), "-s", "1", "-e", "3", "-o", str(out), *args,
    ])
    runpy.run_module(
        "PyReconstruct.assets.scripts.create_ng_zarr.create_ng_zarr",
        run_name="__main__",
    )
    return zarr.open(str(out), "r")


def test_all_tissue_covers_a_later_image_larger_than_the_first(
    monkeypatch, sized_jser, tmp_path
):
    ## section 1 is 200 px (2 µm) across, section 2 is 400 px (4 µm)
    zg = _export(monkeypatch, sized_jser, tmp_path / "all.zarr", "--max_tissue")

    assert zg["raw"].attrs["window"] == pytest.approx([0, 0, 4, 4])
    assert zg["raw"].shape == (3, 400, 400)


def test_without_mag_the_image_pixel_size_stays(
    monkeypatch, sized_jser, tmp_path
):
    zg = _export(monkeypatch, sized_jser, tmp_path / "default.zarr", "--max_tissue")

    assert zg["raw"].attrs["true_mag"] == pytest.approx(MAG)
    assert zg["raw"].attrs["voxel_size"] == [50, 10, 10]


def test_mag_sets_the_pixel_size(monkeypatch, sized_jser, tmp_path):
    zg = _export(
        monkeypatch, sized_jser, tmp_path / "mag.zarr", "--max_tissue", "-m", "0.02",
    )

    assert zg["raw"].attrs["true_mag"] == pytest.approx(0.02)
    assert zg["raw"].attrs["voxel_size"] == [50, 20, 20]
    assert zg["raw"].shape == (3, 200, 200)


@pytest.mark.parametrize("mag", [None, "0.02", "0.005"])
def test_labels_sit_over_their_traces_at_any_mag(monkeypatch, sized_jser, tmp_path, mag):
    args = ["--max_tissue", "-g", "g_box", "-p", "0"]
    if mag:
        args += ["-m", mag]
    zg = _export(monkeypatch, sized_jser, tmp_path / "labels.zarr", *args)

    raw, labels = zg["raw"], zg["labels_g_box"]
    zarr_mag = raw.attrs["true_mag"]
    window = raw.attrs["window"]
    offset = labels.attrs["offset"]
    ## the label crop's corner, back in series µm: x left, y top
    x = window[0] + offset[2] / 1000
    y_top = window[1] + window[3] - offset[1] / 1000
    assert (x, y_top) == (pytest.approx(1.0), pytest.approx(1.6))
    assert labels.shape[1:] == (round(0.6 / zarr_mag), round(0.5 / zarr_mag))
    assert offset[0] == 50  # section 2 is raw slice 1


def test_mag_must_be_positive(monkeypatch, sized_jser):
    from PyReconstruct.assets.scripts.create_ng_zarr import parser

    monkeypatch.setattr(sys, "argv", ["create_ng_zarr.py", str(sized_jser), "-m", "0"])
    with pytest.raises(SystemExit):
        parser.get_args()


## get_offset


def test_crop_offset_keeps_its_fraction_of_a_nm():
    ## 0.5 nm pixels; the crop starts 1.2345 nm right and 2.25 nm down
    offset = conversions.get_offset(
        ([0.0012345, 9.99775, 1, 0], [0, 1]),
        [50, 0.5, 0.5],
        0.0005,
        relative_to=[0, 0, 10, 10],
        section_diff=2,
    )

    assert offset == [100, pytest.approx(2.25), pytest.approx(1.2345)]


def test_crop_offset_in_whole_nm_stays_an_int():
    offset = conversions.get_offset(
        ([0.004, 6, 1, 2], [0, 1]), [50, 2, 2], 0.002, relative_to=[0, 0, 10, 10],
    )

    assert offset == [0, 2000, 4]
    assert all(isinstance(v, int) for v in offset)
