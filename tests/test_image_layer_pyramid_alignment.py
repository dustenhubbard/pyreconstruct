"""Zarr pyramids retain detail at the sampling rate after alignment."""

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.view.image_layer import ImageLayer
from PyReconstruct.modules.datatypes import Transform

pytestmark = pytest.mark.gui


@pytest.fixture
def checker_layer(qapp, real_series, tmp_path):
    source = ((np.indices((64, 64)).sum(axis=0) % 2) * 255).astype("u1")
    store = tmp_path / "checker.zarr"
    group = zarr.open_group(str(store), mode="w")
    for scale in (1, 2, 4, 8):
        pixels = source.reshape(64 // scale, scale, 64 // scale, scale)
        pixels = pixels.mean(axis=(1, 3)).astype("u1")
        group.create_group(f"scale_{scale}").create_dataset("checker.png", data=pixels)
    section = real_series.loadSection(sorted(real_series.sections)[0])
    real_series.src_dir = str(store)
    section.src = "checker.png"
    section.mag = 1
    return ImageLayer(section, real_series), source


@pytest.mark.parametrize(
    "tform,window,reverse_columns",
    [
        ([1, 0, 0, 0, 1, 0], [0, 0, 64, 64], False),
        ([4, 0, 0, 0, 4, 0], [0, 0, 256, 256], False),
        ([4, 0, 11, 0, 4, -7], [11, -7, 256, 256], False),
        ([4, 0, 0, 0, 1, 0], [0, 0, 256, 64], False),
        ([1, 0, 0, 0, 4, 0], [0, 0, 64, 256], False),
        ([0, -4, 256, 4, 0, 0], [0, 0, 256, 256], True),
        ([-4, 0, 256, 0, 4, 0], [0, 0, 256, 256], True),
    ],
    ids=["identity", "scale", "translate", "stretch-x", "stretch-y", "rotate", "reflect"],
)
def test_native_detail_under_alignment_scale(checker_layer, tform, window, reverse_columns):
    layer, source = checker_layer
    layer.section.tform = Transform(tform)

    gray = layer.generateImageArray((64, 64), window, bc=False)

    expected = source[:, ::-1] if reverse_columns else source
    np.testing.assert_array_equal(gray, expected)
    assert layer.selected_scale == 1


def test_shear_preserves_detail_in_the_most_expanded_direction(checker_layer):
    layer, source = checker_layer
    layer.section.tform = Transform([1, 3, 0, 0, 1, 0])

    # At 62/400 screen pixels per field unit, the shear stretches scale-2
    # pixels beyond one screen pixel, despite preserving area. Even the
    # lengths of the transformed coordinate axes underestimate that stretch.
    # Offset the window so sample centers do not land on source pixel edges.
    gray = layer.generateImageArray((62, 62), [0.123, 0.234, 400, 400], bc=False)

    x = 0.123 + (np.arange(62) + 0.5) * 400 / 62
    y = 0.234 + (61.5 - np.arange(62)) * 400 / 62
    col = np.floor(x[None, :] - 3 * y[:, None]).astype(int)
    row = np.broadcast_to(63 - np.floor(y).astype(int)[:, None], col.shape)
    inside = (col >= 0) & (col < 64) & (row >= 0) & (row < 64)
    expected = np.zeros((62, 62), dtype="u1")
    expected[inside] = source[row[inside], col[inside]]
    assert np.count_nonzero(expected) > 0
    np.testing.assert_array_equal(gray, expected)
    assert layer.selected_scale == 1


@pytest.mark.parametrize("alignment_scale", [0.25, 1, 4])
def test_zoom_changes_still_use_coarser_levels(checker_layer, alignment_scale):
    layer, _ = checker_layer
    layer.section.tform = Transform([alignment_scale, 0, 0, 0, alignment_scale, 0])
    extent = 64 * alignment_scale
    for size, expected_scale in [(64, 1), (32, 1), (24, 2), (16, 2), (12, 4), (4, 8), (64, 1)]:
        gray = layer.generateImageArray((size, size), [0, 0, extent, extent], bc=False)
        assert layer.selected_scale == expected_scale
        assert gray.shape == (size, size)
        if expected_scale > 1:
            np.testing.assert_array_equal(gray, np.full((size, size), 127, dtype="u1"))


@pytest.mark.parametrize(
    "window",
    [[0, 0, 0, 64], [0, 0, 64, 0], [0, 0, -1, 64], [0, 0, 64, -1]],
    ids=["zero-width", "zero-height", "negative-width", "negative-height"],
)
def test_nonpositive_window_returns_blank_image(checker_layer, window):
    layer, _ = checker_layer

    gray = layer.generateImageArray((64, 64), window, bc=False)

    np.testing.assert_array_equal(gray, np.zeros((64, 64), dtype="u1"))
