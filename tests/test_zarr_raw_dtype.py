"""Imported Neuroglancer pixels retain their grayscale values when rendered."""

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg.conversions import ZarrRefused, zarrToNewSeries
from PyReconstruct.modules.backend.view.image_layer import ImageLayer
from PyReconstruct.modules.datatypes import Transform


@pytest.mark.gui
@pytest.mark.parametrize("crop_only", [False, True], ids=["view", "optimizer-crop"])
@pytest.mark.parametrize("dtype", ["<u2", ">u2"])
def test_uint16_neuroglancer_pixels_render_uniformly(tmp_path, qapp, crop_only, dtype):
    source = tmp_path / "source.zarr"
    zarr.open(str(source), "w").create_dataset(
        "raw", data=np.full((1, 4, 8), 0x1200, dtype=dtype)
    )
    series = zarrToNewSeries(str(source), [], "imported")
    try:
        section = series.loadSection(0)
        layer = ImageLayer(section, series)
        pixels = layer.generateImageArray(
            (8, 4), [0, 0, 8 * section.mag, 4 * section.mag],
            get_crop_only=crop_only, bc=False,
        )
        np.testing.assert_array_equal(pixels, np.full((4, 8), 18, dtype=np.uint8))
    finally:
        series.close()


@pytest.mark.gui
@pytest.mark.parametrize("dtype", ["u1", "<u2", ">u2"])
@pytest.mark.parametrize("channel_first", [False, True])
@pytest.mark.parametrize("crop_only", [False, True], ids=["view", "optimizer-crop"])
def test_neuroglancer_grayscale_ramp(tmp_path, qapp, dtype, channel_first, crop_only):
    expected = np.array([[0, 18, 63, 127, 128, 170, 255]] * 3, dtype=np.uint8)
    raw = expected.astype(dtype)
    if raw.dtype.itemsize == 2:
        raw *= 257
    raw = raw[None]
    if channel_first:
        raw = raw[None]
    source = tmp_path / "source.zarr"
    zarr.open(str(source), "w").create_dataset("raw", data=raw)
    series = zarrToNewSeries(str(source), [], "imported")
    try:
        section = series.loadSection(0)
        pixels = ImageLayer(section, series).generateImageArray(
            (7, 3), [0, 0, 7 * section.mag, 3 * section.mag],
            get_crop_only=crop_only, bc=False,
        )
        np.testing.assert_array_equal(pixels, expected)
        stored = zarr.open(series.src_dir, "r")["scale_1"][section.src]
        np.testing.assert_array_equal(stored[:], raw.reshape(3, 7))
        assert stored.dtype == raw.dtype
    finally:
        series.close()


@pytest.mark.gui
def test_uint16_zarr_rotated_view_and_pyramid(tmp_path, qapp):
    source = tmp_path / "source.zarr"
    zarr.open(str(source), "w").create_dataset(
        "raw", data=np.full((1, 4, 8), 0x1212, dtype=">u2")
    )
    series = zarrToNewSeries(str(source), [], "imported")
    try:
        section = series.loadSection(0)
        section.tforms[series.alignment] = Transform([0, -1, 4, 1, 0, 0])
        section.mag = 1
        layer = ImageLayer(section, series)
        pixels = layer.generateImageArray((6, 10), [-1, -1, 6, 10], bc=False)
        expected = np.zeros((10, 6), dtype=np.uint8)
        expected[1:9, 1:5] = 18
        np.testing.assert_array_equal(pixels, expected)

        section.tforms[series.alignment] = Transform.identity()
        images = zarr.open(series.src_dir, "a")
        images.create_dataset("scale_2/section0", data=np.full((2, 4), 0xAAAA, dtype=">u2"))
        layer = ImageLayer(section, series)
        pixels = layer.generateImageArray((2, 1), [0, 0, 8, 4], bc=False)
        assert layer.selected_scale == 2
        np.testing.assert_array_equal(pixels, [[170, 170]])
    finally:
        series.close()


@pytest.mark.parametrize("dtype", ["i2", "u4", "f4"])
@pytest.mark.parametrize("channel_first", [False, True])
def test_unsupported_raw_dtype_is_refused_before_import(tmp_path, dtype, channel_first):
    source = tmp_path / "source.zarr"
    raw = np.full((1, 4, 8), 18, dtype=dtype)
    if channel_first:
        raw = raw[None]
    zarr.open(str(source), "w").create_dataset("raw", data=raw)
    with pytest.raises(ZarrRefused, match="uint8 or uint16"):
        zarrToNewSeries(str(source), [], "imported")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["source.zarr"]
    np.testing.assert_array_equal(zarr.open(str(source), "r")["raw"][:], raw)
