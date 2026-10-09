"""An image whose name has a backslash is found in its zarr on every system.

zarr turns a backslash in an array name into a slash, so `a\\b.png` is stored
as `scale_N/a/b.png`. On macOS and Linux a path built with the raw name has a
literal backslash and names nothing, so the section found no scales, showed no
image, and had no size. A slash nests the same way and already worked.

Each test builds a real zarr on disk and spells out where the array is, so the
layout is checked against zarr itself, not against the code under test.
"""
import os

import numpy as np
import pytest

pytestmark = pytest.mark.gui

IW, IH = 200, 160
MAG = 0.01


def _write_zarr(tmp_path, name, scales):
    """A zarr holding one image, written by zarr under its own key rule."""
    import zarr

    fp = str(tmp_path / "images.zarr")
    group = zarr.open_group(fp, mode="w")
    for k in scales:
        rr, cc = np.meshgrid(
            np.arange(IH // k), np.arange(IW // k), indexing="ij"
        )
        values = ((cc * 7 + rr * 13) % 200 + 20).astype("u1")
        group.require_group(f"scale_{k}").create_dataset(
            name, data=values, chunks=(32, 32)
        )
    return fp


def _section(real_series, zarr_fp, src):
    from PyReconstruct.modules.datatypes import Transform

    section = real_series.loadSection(sorted(real_series.sections)[0])
    real_series.src_dir = zarr_fp
    section.src = src
    section.mag = MAG
    section.tform = Transform.identity()
    return section


# name, the folder zarr keeps it in under scale_N
NAMES = [
    ("img.png", "img.png"),
    ("a\\b.png", os.path.join("a", "b.png")),
    ("a/b.png", os.path.join("a", "b.png")),
]


@pytest.mark.parametrize("name, on_disk", NAMES)
def test_zarr_scales_finds_the_array_where_zarr_put_it(
    qapp, real_series, tmp_path, name, on_disk
):
    fp = _write_zarr(tmp_path, name, (1, 2, 4))
    assert os.path.isfile(os.path.join(fp, "scale_2", on_disk, ".zarray"))
    section = _section(real_series, fp, name)

    assert sorted(section.zarr_scales) == [1, 2, 4]
    assert section.src_fp == os.path.join(fp, "scale_1", on_disk)


@pytest.mark.parametrize("name, on_disk", NAMES)
def test_a_nested_scale_without_zarray_is_still_left_out(
    qapp, real_series, tmp_path, name, on_disk
):
    """A conversion that stopped partway leaves chunks and no .zarray."""
    fp = _write_zarr(tmp_path, name, (1, 2, 4))
    os.remove(os.path.join(fp, "scale_2", on_disk, ".zarray"))
    section = _section(real_series, fp, name)

    assert sorted(section.zarr_scales) == [1, 4]


def test_img_dims_of_a_backslash_name_is_scale_1(qapp, real_series, tmp_path):
    fp = _write_zarr(tmp_path, "a\\b.png", (1, 2))
    section = _section(real_series, fp, "a\\b.png")

    assert section.img_dims == (IH, IW)


def test_a_backslash_name_draws(qapp, real_series, tmp_path):
    from PySide6.QtGui import QImage

    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    fp = _write_zarr(tmp_path, "a\\b.png", (1, 2))
    section = _section(real_series, fp, "a\\b.png")

    layer = ImageLayer(section, real_series)

    assert layer.image_found
    assert layer.scales == [2, 1]
    image = layer._generateImage((977, 700), [0.0, 0.0, 2.0, 1.6], bc=False)
    image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    buf = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    assert buf.copy().any(), "the image drew nothing"


def test_optimize_bc_reads_a_backslash_name(qapp, real_series, tmp_path):
    from PyReconstruct.modules.backend.view.optimize_bc import optimizeSectionBC

    fp = _write_zarr(tmp_path, "a\\b.png", (1, 2))
    section = _section(real_series, fp, "a\\b.png")
    section.brightness, section.contrast = 0, 0

    optimizeSectionBC(section, desired_mean=200, desired_std=10)

    assert (section.brightness, section.contrast) != (0, 0)


def test_neuroglancer_export_sizes_a_backslash_name(monkeypatch, qapp, tmp_path):
    """The all-tissue window comes from each image's size in scale_1."""
    import runpy
    import sys

    import cv2
    import zarr

    from PyReconstruct.modules.backend import autoseg, imports
    from PyReconstruct.modules.backend.autoseg import conversions
    from PyReconstruct.modules.datatypes import Series

    class InlinePool:
        def __init__(self):
            self.jobs = []

        def createWorker(self, fn, *args, **kwargs):
            self.jobs.append((fn, args))

        def startAll(self, *args, **kwargs):
            for fn, args in self.jobs:
                fn(*args)
            return True

    images = []
    for i in range(3):
        fp = tmp_path / f"img{i}.png"
        cv2.imwrite(str(fp), np.full((IH, IW, 3), 40, np.uint8))
        images.append(str(fp))
    fp = str(tmp_path / "images.zarr")
    group = zarr.open_group(fp, mode="w")
    series = Series.new(images, "nested", MAG, 0.05)
    try:
        series.src_dir = fp
        for snum in sorted(series.sections):
            name = f"a\\img{snum}.png"
            group.require_group("scale_1").create_dataset(
                name, data=np.full((IH, IW), 40, np.uint8)
            )
            section = series.loadSection(snum)
            section.src = name
            section.save()
        series.save()
        jser = tmp_path / "nested.jser"
        series.saveJser(str(jser))
    finally:
        series.close()

    out = tmp_path / "ng.zarr"
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", InlinePool)
    monkeypatch.setattr(imports, "modules_available", lambda *a, **k: True)
    monkeypatch.setattr(autoseg, "rechunk", lambda *a, **k: True)
    monkeypatch.setattr(sys, "argv", [
        "create_ng_zarr.py", str(jser), "-s", "1", "-e", "2", "-o", str(out),
        "--max_tissue",
    ])
    runpy.run_module(
        "PyReconstruct.assets.scripts.create_ng_zarr.create_ng_zarr",
        run_name="__main__",
    )

    raw = zarr.open(str(out), "r")["raw"]
    assert raw.attrs["window"] == pytest.approx([0, 0, IW * MAG, IH * MAG])


def test_a_name_zarr_cannot_store_finds_no_scales(qapp, real_series, tmp_path):
    """zarr refuses a '..' part; the section has no image, as before."""
    fp = _write_zarr(tmp_path, "img.png", (1,))
    section = _section(real_series, fp, "a\\..\\img.png")

    assert section.zarr_scales == []
