"""Whole-image optimization uses the grayscale levels displayed for uint16 Zarrs."""

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg.conversions import zarrToNewSeries
from PyReconstruct.modules.backend.view.image_layer import ImageLayer
from PyReconstruct.modules.backend.view.optimize_bc import (
    adjustPixelsToStats,
    optimizeSectionBC,
)


@pytest.mark.gui
def test_imported_uint16_optimization_matches_displayed_uint8(qapp, tmp_path):
    source = tmp_path / "source.zarr"
    zarr.open(str(source), "w").create_dataset(
        "raw", data=np.full((1, 4, 8), 0x1212, dtype=np.uint16)
    )
    series = zarrToNewSeries(str(source), [], "imported")
    try:
        section = series.loadSection(0)
        window = [0, 0, 8 * section.mag, 4 * section.mag]
        displayed = ImageLayer(section, series).generateImageArray((8, 4), window)
        np.testing.assert_array_equal(displayed, np.full((4, 8), 18, np.uint8))
        expected = adjustPixelsToStats(displayed, 128, 0)
        assert expected == (46, 0)

        optimizeSectionBC(section, desired_mean=128, desired_std=0)

        assert (section.brightness, section.contrast) == expected
        rendered = ImageLayer(section, series).generateImageArray((8, 4), window)
        assert abs(rendered[1:, 1:].mean() - 128) < 2
    finally:
        series.close()


@pytest.mark.parametrize("dtype", ["u1", "<u2", ">u2"])
@pytest.mark.parametrize("flat", [False, True], ids=["pyramid", "flat"])
@pytest.mark.parametrize("lowest_res", [False, True])
def test_whole_zarr_optimization_uses_grayscale_levels(
    qapp, real_series, tmp_path, dtype, flat, lowest_res,
):
    # Include rounding boundaries and widths that need padding in a Qt image.
    dark = np.array([[0, 0, 1, 18, 63, 127, 128]] * 3, dtype=np.uint8)
    bright = np.array([[0, 128, 170, 255, 255, 255, 255]] * 3, dtype=np.uint8)
    if np.dtype(dtype).itemsize == 2:
        raw_dark = np.array(
            [[0, 128, 129, 0x1212, 0x3F3F, 0x7F7F, 0x8080]] * 3, dtype=dtype
        )
        raw_bright = np.array(
            [[0, 0x8080, 0xAAAA, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]] * 3, dtype=dtype
        )
    else:
        raw_dark, raw_bright = dark, bright
    source = tmp_path / "images.zarr"
    images = zarr.open(str(source), "w")
    dark_path = "image" if flat else "scale_1/image"
    images.create_dataset(dark_path, data=raw_dark)
    if not flat:
        images.create_dataset("scale_2/image", data=raw_bright)
    real_series.src_dir = str(source)
    section = real_series.loadSection(min(real_series.sections))
    section.src = "image"
    expected_pixels = bright if lowest_res and not flat else dark
    expected = adjustPixelsToStats(expected_pixels, 128, 60)

    optimizeSectionBC(section, 128, 60, lowest_res=lowest_res)

    assert (section.brightness, section.contrast) == expected
    np.testing.assert_array_equal(images[dark_path][:], raw_dark)
    assert images[dark_path].dtype == np.dtype(dtype)
    if not flat:
        np.testing.assert_array_equal(images["scale_2/image"][:], raw_bright)
        assert images["scale_2/image"].dtype == np.dtype(dtype)
