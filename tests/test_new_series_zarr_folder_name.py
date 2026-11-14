"""A new series reads "zarr" in a folder name only where it names a zarr.

`Series.new` used to look for the letters "zarr" anywhere in the image
folder's path and cut the path right after them. Images in
`scans/zarr-test/images/` got `scans/zarr` as their image folder, which does
not exist, and the series went in `scans/`.

The image folder is a zarr when a folder at or above it has a name that ends
in "zarr". That is the test the image readers apply to `src_dir`, so a zarr
named `x.zarr`, `x-zarr` or `x_zarr` keeps working.
"""

import os

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import Series


MAG = 0.00254
THICKNESS = 0.05
IW, IH = 40, 32

# folder names that hold the letters "zarr" and are not zarrs
PLAIN_FOLDERS = ["zarr-test", "zarrs", "images.zarr.bak", "lizard-zarr-old"]

# names the image readers take as a zarr
ZARR_NAMES = ["images.zarr", "images-zarr", "images_zarr"]


def _plain_images(folder, n=2):
    import cv2

    os.makedirs(folder)
    images = []
    for i in range(n):
        fp = os.path.join(folder, f"img{i}.png")
        cv2.imwrite(fp, np.full((IH, IW, 3), 40 + i, np.uint8))
        images.append(fp)
    return images


def _zarr_images(fp, n=2):
    """A zarr with n images under scale_1, and the paths New Series is given."""
    import zarr

    group = zarr.open_group(fp, mode="w").require_group("scale_1")
    images = []
    for i in range(n):
        name = f"img{i}.png"
        group.create_dataset(name, data=np.full((IH, IW), 40 + i, np.uint8))
        images.append(os.path.join(fp, "scale_1", name))
    return images


@pytest.mark.parametrize("folder_name", PLAIN_FOLDERS)
def test_images_under_a_folder_with_zarr_in_its_name(tmp_path, folder_name):
    folder = str(tmp_path / "scans" / folder_name / "images")
    images = _plain_images(folder)

    series = Series.new(images, "plain", MAG, THICKNESS)
    try:
        assert series.src_dir == folder
        assert os.path.dirname(series.hidden_dir) == folder
        for snum, image in zip(sorted(series.sections), images):
            section = series.loadSection(snum)
            assert section.src_fp == image
            assert section.zarr_scales is None
            assert section.img_dims == (IH, IW)
    finally:
        series.close()


@pytest.mark.parametrize("folder_name", PLAIN_FOLDERS)
def test_images_right_in_a_folder_with_zarr_in_its_name(tmp_path, folder_name):
    folder = str(tmp_path / folder_name)
    images = _plain_images(folder)

    series = Series.new(images, "plain", MAG, THICKNESS)
    try:
        assert series.src_dir == folder
        assert os.path.dirname(series.hidden_dir) == folder
        assert series.loadSection(0).src_fp == images[0]
    finally:
        series.close()


@pytest.mark.parametrize("zarr_name", ZARR_NAMES)
def test_images_in_a_zarr_put_the_series_beside_it(tmp_path, zarr_name):
    zarr_fp = str(tmp_path / zarr_name)
    images = _zarr_images(zarr_fp)

    series = Series.new(images, "scaled", MAG, THICKNESS)
    try:
        assert series.src_dir == zarr_fp
        assert os.path.dirname(series.hidden_dir) == str(tmp_path)
        for snum, image in zip(sorted(series.sections), images):
            section = series.loadSection(snum)
            assert section.src_fp == image
            assert section.zarr_scales == [1]
            assert section.img_dims == (IH, IW)
    finally:
        series.close()


@pytest.mark.parametrize("folder_name", PLAIN_FOLDERS)
def test_a_zarr_under_a_folder_with_zarr_in_its_name(tmp_path, folder_name):
    parent = tmp_path / folder_name
    parent.mkdir()
    zarr_fp = str(parent / "images.zarr")
    images = _zarr_images(zarr_fp)

    series = Series.new(images, "scaled", MAG, THICKNESS)
    try:
        assert series.src_dir == zarr_fp
        assert os.path.dirname(series.hidden_dir) == str(parent)
        assert series.loadSection(0).zarr_scales == [1]
    finally:
        series.close()


def test_the_nearest_zarr_above_the_images_is_the_image_folder(tmp_path):
    outer = tmp_path / "outer.zarr"
    outer.mkdir()
    zarr_fp = str(outer / "inner.zarr")
    images = _zarr_images(zarr_fp)

    series = Series.new(images, "scaled", MAG, THICKNESS)
    try:
        assert series.src_dir == zarr_fp
        assert os.path.dirname(series.hidden_dir) == str(outer)
    finally:
        series.close()
