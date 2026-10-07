"""A zarr scale with chunks and no .zarray is not offered as an image.

A conversion that stops partway (a worker killed, a full disk, a chunk that
failed to write) leaves `scale_N/<image>/` holding chunks and no `.zarray`.
zarr cannot open that folder as an array, so `zarr_scales` used to list the
scale and then:

- zooming onto it raised `KeyError` in `ImageLayer._generateImage`;
- a section whose only scale was unfinished raised `KeyError` on load;
- `src_fp` did `min([])` once such scales were left out, which aborted
  `optimizeSeriesBC` for the whole batch and `saveFieldView`;
- `img_dims` opened the folder to write and planted a `.zgroup` in it, which
  the converter then takes for a finished image and never rewrites.

Each test drives a consumer against a real zarr on disk.
"""
import os

import numpy as np
import pytest
from PySide6.QtGui import QImage

pytestmark = pytest.mark.gui

IW, IH = 200, 160
MAG = 0.01
DIM = (977, 700)


def _unfinish(zarr_fp, scale, name):
    """Leave the array's chunks and drop its .zarray, as a stopped write does."""
    folder = os.path.join(zarr_fp, f"scale_{scale}", name)
    os.remove(os.path.join(folder, ".zarray"))
    assert any(f[0].isdigit() for f in os.listdir(folder)), "no chunks left"
    return folder


def _write_zarr(tmp_path, images):
    """A zarr with {name: {scale: finished}}; each level a gray ramp."""
    import zarr

    fp = str(tmp_path / "images.zarr")
    group = zarr.open_group(fp, mode="w")
    for name, scales in images.items():
        for k in scales:
            if f"scale_{k}" not in group:
                group.create_group(f"scale_{k}")
            rr, cc = np.meshgrid(
                np.arange(IH // k), np.arange(IW // k), indexing="ij"
            )
            values = ((cc * 7 + rr * 13) % 200 + 20).astype("u1")
            group[f"scale_{k}"].create_dataset(
                name, data=values, chunks=(32, 32)
            )
    for name, scales in images.items():
        for k, finished in scales.items():
            if not finished:
                _unfinish(fp, k, name)
    return fp


def _section(real_series, zarr_fp, src, snum=None):
    from PyReconstruct.modules.datatypes import Transform

    if snum is None:
        snum = sorted(real_series.sections)[0]
    section = real_series.loadSection(snum)
    real_series.src_dir = zarr_fp
    section.src = src
    section.mag = MAG
    section.tform = Transform.identity()
    return section


def _window(zoom):
    ww = DIM[0] * MAG / zoom
    wh = DIM[1] * MAG / zoom
    return [0.0, 0.0, ww, wh]


def _gray(image):
    image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    buf = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    return buf.reshape(image.height(), image.bytesPerLine())[:, : image.width()]


def test_zarr_scales_lists_only_finished_arrays(qapp, real_series, tmp_path):
    fp = _write_zarr(tmp_path, {"img.png": {1: True, 2: False, 4: True}})
    section = _section(real_series, fp, "img.png")
    assert sorted(section.zarr_scales) == [1, 4]


def test_zooming_out_onto_an_unfinished_scale_reads_a_finished_one(
    qapp, real_series, tmp_path
):
    """The zoom that would pick scale_2 falls back to scale_1."""
    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    fp = _write_zarr(tmp_path, {"img.png": {1: True, 2: False}})
    section = _section(real_series, fp, "img.png")
    layer = ImageLayer(section, real_series)
    assert layer.image_found
    assert layer.scales == [1]

    image = layer._generateImage(DIM, _window(0.37), bc=False)  # scale_2 zoom

    assert layer.selected_scale == 1
    assert _gray(image).any(), "the finished scale drew nothing"


def test_a_scale_2_section_whose_scale_1_is_unfinished_still_draws(
    qapp, real_series, tmp_path
):
    """Close zoom wants scale_1; the nearest finished scale is scale_2."""
    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    fp = _write_zarr(tmp_path, {"img.png": {1: False, 2: True}})
    section = _section(real_series, fp, "img.png")
    layer = ImageLayer(section, real_series)
    assert layer.image_found

    image = layer._generateImage(DIM, _window(1.7), bc=False)

    assert layer.selected_scale == 2
    assert _gray(image).any()
    assert section.src_fp == os.path.join(fp, "scale_2", "img.png")


def test_a_section_with_no_finished_scale_loads_as_no_image(
    qapp, real_series, tmp_path
):
    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    fp = _write_zarr(tmp_path, {"img.png": {1: False, 2: False}})
    section = _section(real_series, fp, "img.png")
    assert section.zarr_scales == []

    layer = ImageLayer(section, real_series)
    assert not layer.image_found
    image = layer._generateImage(DIM, _window(0.37), bc=False)
    assert not _gray(image).any(), "expected the blank layer"


def test_src_fp_with_no_finished_scale_is_the_scale_1_path(
    qapp, real_series, tmp_path
):
    fp = _write_zarr(tmp_path, {"img.png": {1: False}})
    section = _section(real_series, fp, "img.png")
    assert section.src_fp == os.path.join(fp, "scale_1", "img.png")


def test_img_dims_of_an_unfinished_array_writes_nothing(
    qapp, real_series, tmp_path
):
    """Reading the size must not turn the folder into a group."""
    import zarr

    fp = _write_zarr(tmp_path, {"img.png": {1: False}})
    section = _section(real_series, fp, "img.png")
    folder = os.path.join(fp, "scale_1", "img.png")
    before = sorted(os.listdir(folder))

    with pytest.raises(FileNotFoundError):
        section.img_dims

    assert sorted(os.listdir(folder)) == before
    assert "img.png" not in zarr.open_group(fp, mode="r")["scale_1"]


def test_optimize_bc_reads_a_finished_scale(qapp, real_series, tmp_path):
    """lowest_res wants the coarsest scale; the unfinished one is passed over."""
    from PyReconstruct.modules.backend.view.optimize_bc import optimizeSectionBC

    fp = _write_zarr(tmp_path, {"img.png": {1: True, 2: True, 4: False}})
    section = _section(real_series, fp, "img.png")
    section.brightness, section.contrast = 0, 0

    optimizeSectionBC(section, desired_mean=200, desired_std=10)

    assert (section.brightness, section.contrast) != (0, 0)


def test_optimize_series_bc_goes_on_past_a_section_with_no_finished_scale(
    qapp, real_series, tmp_path, capsys
):
    from PyReconstruct.modules.backend.view.optimize_bc import optimizeSeriesBC

    fp = _write_zarr(
        tmp_path,
        {"gone.png": {1: False}, "img.png": {1: True}},
    )
    first, second = sorted(real_series.sections)[:2]
    for snum, src in ((first, "gone.png"), (second, "img.png")):
        section = _section(real_series, fp, src, snum)
        section.brightness, section.contrast = 0, 0
        section.save()

    optimizeSeriesBC(
        real_series, desired_mean=200, desired_std=10,
        section_nums=[first, second],
    )

    skipped = real_series.loadSection(first)
    optimized = real_series.loadSection(second)
    assert (skipped.brightness, skipped.contrast) == (0, 0)
    assert (optimized.brightness, optimized.contrast) != (0, 0)
    # an unfinished image is not a corrupt one
    assert "corrupt" not in capsys.readouterr().out


def test_save_field_view_with_no_finished_scale(main_window, tmp_path):
    from PySide6.QtWidgets import QApplication

    fp = _write_zarr(tmp_path, {"img.png": {1: False}})
    main_window.series.src_dir = fp
    main_window.field.section.src = "img.png"
    QApplication.clipboard().clear()

    main_window.saveFieldView(False)

    assert not QApplication.clipboard().image().isNull()
