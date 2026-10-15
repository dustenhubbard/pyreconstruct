"""The image name matcher pairs sections with a zarr's images by number.

`backend.image_name_match` is the one home of the rules the cropper
(`dev/assets/misc/crop_zarr.py`) and the image folder change share. The key
is the number in the series' own image name, read at the start or the end of
the name; the section number is a cross-check reported as `renumbered`. A
match that is not one to one is refused with the reason.
"""
import os

import numpy as np
import pytest

from PyReconstruct.modules.backend import image_name_match as m

GRID = {n: f"00{n}_IMG_grid0{n}_sec0{n}.tif" for n in range(5)}


@pytest.mark.parametrize("name, numbers", [
    ("IMG_000.tif", [0]),
    ("000_IMG_grid000.tif", [0, 0]),
    ("CODE.007", [7]),
    ("007ABC.tif", [7]),
    ("a_12_b_3.jp2", [12, 3]),
    ("plain.tif", []),
])
def test_name_numbers(name, numbers):
    assert m.nameNumbers(name) == numbers


def test_number_at_the_start_of_the_series_names():
    series = {n: f"{n:03d}ZGBJY.tif" for n in range(5)}
    match, reason = m.matchByNumber(series, list(GRID.values()))
    assert reason == ""
    assert match["names"] == GRID
    assert match["renumbered"] == []
    assert match["series"] == "first"


def test_number_at_the_end_of_the_series_names():
    series = {n: f"IMG_{n:03d}.tif" for n in range(5)}
    match, reason = m.matchByNumber(series, list(GRID.values()))
    assert reason == ""
    assert match["names"] == GRID
    assert match["renumbered"] == []


def test_number_at_the_end_of_the_zarr_names():
    series = {n: f"IMG_{n:03d}.tif" for n in range(3)}
    zarr_names = [f"grid7_sec{n}.tif" for n in range(3)]
    match, reason = m.matchByNumber(series, zarr_names)
    assert reason == ""
    assert match["names"] == {0: "grid7_sec0.tif", 1: "grid7_sec1.tif", 2: "grid7_sec2.tif"}
    assert match["zarr"] == "last"


def test_padding_does_not_matter():
    series = {n: f"IMG_{n}.tif" for n in range(3)}
    match, reason = m.matchByNumber(series, ["000_a.tif", "001_a.tif", "002_a.tif"])
    assert reason == ""
    assert match["names"] == {0: "000_a.tif", 1: "001_a.tif", 2: "002_a.tif"}


def test_the_section_number_is_a_cross_check_not_the_key():
    """Sections 0 and 1 hold each other's images, as reordering does. The
    pairing follows the image name; the two sections are reported."""
    series = {0: "IMG_001.tif", 1: "IMG_000.tif", 2: "IMG_002.tif"}
    match, reason = m.matchByNumber(series, list(GRID.values())[:3])
    assert reason == ""
    assert match["names"] == {0: GRID[1], 1: GRID[0], 2: GRID[2]}
    assert match["renumbered"] == [0, 1]


@pytest.mark.parametrize("zarr_names, reason", [
    (list(GRID.values())[:4], "the zarr's 4 images are numbered 0-3, and the series' 5 image names 0-4"),
    (list(GRID.values()) + ["005_IMG_grid05_sec05.tif"],
     "the zarr's 6 images are numbered 0-5, and the series' 5 image names 0-4"),
    ([f"00{n + 1}_IMG.tif" for n in range(5)],
     "the zarr's 5 images are numbered 1-5, and the series' 5 image names 0-4"),
    (["000_a.tif", "000_b.tif", "002_a.tif", "003_a.tif", "004_a.tif"],
     "no number tells the zarr's images apart: '000_a.tif' and '000_b.tif' both have the number 0"),
    (["a.tif", "b.tif", "c.tif", "d.tif", "e.tif"],
     "no number tells the zarr's images apart: 'a.tif' has no number"),
    ([], "the zarr holds no images"),
])
def test_not_one_to_one_is_refused_with_the_reason(zarr_names, reason):
    series = {n: f"IMG_{n:03d}.tif" for n in range(5)}
    match, got = m.matchByNumber(series, zarr_names)
    assert match is None
    assert got == reason


def test_series_names_without_a_number_are_refused():
    match, reason = m.matchByNumber({0: "a.tif", 1: "b.tif"}, ["0.tif", "1.tif"])
    assert match is None
    assert reason == "no number tells the series' image names apart: 'a.tif' has no number"


def test_first_and_last_that_pair_differently_are_refused():
    """Keyed by the first number the pairing is 1:1, by the last it is 1:2."""
    series = {1: "1_2.tif", 2: "2_1.tif"}
    match, reason = m.matchByNumber(series, ["1.tif", "2.tif"])
    assert match is None
    assert reason.startswith("the first and the last number in the names both fit")


def test_the_reading_that_numbers_sections_as_their_own_wins():
    """Both readings give the same pairing; the one with no renumbered
    section is returned."""
    series = {1: "7_1.tif", 2: "8_2.tif"}
    match, reason = m.matchByNumber(series, ["1.tif", "2.tif"])
    assert reason == ""
    assert match["names"] == {1: "1.tif", 2: "2.tif"}
    assert match["renumbered"] == []
    assert match["series"] == "last"


def test_empty_series_is_refused():
    match, reason = m.matchByNumber({}, ["0.tif"])
    assert match is None
    assert reason == "the series has no sections"


def _zarr(folder, layout, names):
    import zarr

    root = zarr.open_group(str(folder), mode="w")
    if layout == "scaled":
        groups = [root.create_group("scale_1"), root.create_group("scale_2")]
    else:
        groups = [root]
    for group in groups:
        for name in names:
            group.create_dataset(name, data=np.zeros((8, 8), "u1"))
    return str(folder)


@pytest.mark.parametrize("layout", ["scaled", "flat"])
def test_zarr_image_names_in_both_layouts(tmp_path, layout):
    fp = _zarr(tmp_path / "images.zarr", layout, ["b.tif", "a.tif"])
    assert m.zarrImageNames(fp) == ["a.tif", "b.tif"]


def test_zarr_image_names_skip_entries_without_a_zarray(tmp_path):
    fp = _zarr(tmp_path / "images.zarr", "scaled", ["a.tif", "b.tif"])
    os.remove(os.path.join(fp, "scale_1", "b.tif", ".zarray"))
    os.mkdir(os.path.join(fp, "scale_1", "notes"))
    assert m.zarrImageNames(fp) == ["a.tif"]


def test_zarr_with_scale_levels_but_no_scale_1_has_no_names(tmp_path):
    import zarr

    fp = str(tmp_path / "images.zarr")
    zarr.open_group(fp, mode="w").create_group("scale_2").create_dataset(
        "a.tif", data=np.zeros((8, 8), "u1")
    )
    assert m.zarrImageNames(fp) == []


def test_an_image_named_like_a_scale_is_an_image(tmp_path):
    """A root array named scale_2 is an image of a flat zarr, not a level."""
    fp = _zarr(tmp_path / "images.zarr", "flat", ["scale_2", "a.tif"])
    assert m.zarrImageNames(fp) == ["a.tif", "scale_2"]


def test_zarr_image_names_raise_for_a_missing_folder(tmp_path):
    with pytest.raises(OSError):
        m.zarrImageNames(str(tmp_path / "missing.zarr"))


def test_the_cropper_uses_this_module():
    """One home for the rules: the cropper's names are these functions."""
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "dev" / "assets" / "misc" / "crop_zarr.py"
    spec = importlib.util.spec_from_file_location("crop_zarr_shared", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.matchByNumber is m.matchByNumber
    assert module.numberKeys is m.numberKeys
    assert module.nameNumbers is m.nameNumbers
