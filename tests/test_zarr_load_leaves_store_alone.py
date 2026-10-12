"""Opening a section never rearranges a zarr that is already in scale layout.

The first zarr layout kept each image as an array at the root, and loading a
section moved them all into a new scale_1 group. Whether to move was decided by
`section.src in group`, and zarr reads a blank name as the root group and a
scale's name as that scale's group. So a section with no image (src "", the
normal state of a blank section) ran the move on a scale-layout zarr: scale_1
was made again, empty, which deleted the full-resolution images, and scale_2
and up ended up inside scale_1.

A flat zarr is still moved into scale_1 when a section's image is an array at
its root, including an image whose own name looks like a scale.
"""
import os

import numpy as np
import pytest

pytestmark = pytest.mark.gui

IW, IH = 64, 48
MAG = 0.01
DIM = (320, 240)
SCALES = (1, 2, 4, 8, 16)


def _values(k):
    rr, cc = np.meshgrid(np.arange(IH // k), np.arange(IW // k), indexing="ij")
    return ((cc * 7 + rr * 13) % 200 + 20).astype("u1")


def _pyramid(tmp_path, names=("img.png", "other.png")):
    """A scale-layout zarr: scale_1 to scale_16, each holding every image."""
    import zarr

    fp = str(tmp_path / "images.zarr")
    group = zarr.open_group(fp, mode="w")
    for k in SCALES:
        scale = group.create_group(f"scale_{k}")
        for name in names:
            scale.create_dataset(name, data=_values(k), chunks=(16, 16))
    return fp


def _flat(tmp_path, names=("img.png", "other.png")):
    """The first layout: each image an array at the root, no scale groups."""
    import zarr

    fp = str(tmp_path / "images.zarr")
    group = zarr.open_group(fp, mode="w")
    for name in names:
        group.create_dataset(name, data=_values(1), chunks=(16, 16))
    return fp


def _snapshot(folder):
    """Every folder and file under folder, with each file's bytes."""
    found = {}
    for root, dirs, files in os.walk(folder):
        rel = os.path.relpath(root, folder)
        found[rel] = None
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                found[os.path.join(rel, f)] = fh.read()
    return found


def _section(real_series, zarr_fp, src):
    from PyReconstruct.modules.datatypes import Transform

    section = real_series.loadSection(sorted(real_series.sections)[0])
    real_series.src_dir = zarr_fp
    section.src = src
    section.mag = MAG
    section.tform = Transform.identity()
    return section


def _load_and_draw(real_series, section):
    """Load the section's image, then draw it close up and far out."""
    from PyReconstruct.modules.backend.view.image_layer import ImageLayer

    layer = ImageLayer(section, real_series)
    for zoom in (2.0, 0.05):
        ww, wh = DIM[0] * MAG / zoom, DIM[1] * MAG / zoom
        layer._generateImage(DIM, [0.0, 0.0, ww, wh], bc=False)
    return layer


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("", id="blank"),
        pytest.param("/", id="slash"),
        pytest.param("scale_2", id="a-scale-name"),
        pytest.param("scale_1/img.png", id="a-path-into-scale_1"),
        pytest.param("missing.png", id="no-such-image"),
        pytest.param("img.png", id="a-real-image"),
    ],
)
def test_loading_any_section_leaves_a_scale_layout_zarr_unchanged(
    qapp, real_series, tmp_path, src
):
    fp = _pyramid(tmp_path)
    before = _snapshot(fp)

    _load_and_draw(real_series, _section(real_series, fp, src))

    after = _snapshot(fp)
    assert sorted(after) == sorted(before), "files added or removed"
    assert after == before, "a file in the zarr was rewritten"
    assert not os.path.exists(os.path.join(fp, "scale_1", "scale_2"))


def test_a_stray_root_array_with_the_image_name_is_left_alone(
    qapp, real_series, tmp_path
):
    """A scale-layout zarr that also has the image at its root (an extra copy,
    say, from unpacking an archive into it) is not treated as the old layout."""
    import zarr

    fp = _pyramid(tmp_path)
    zarr.open_group(fp, mode="a").create_dataset(
        "img.png", data=_values(1), chunks=(16, 16)
    )
    before = _snapshot(fp)

    layer = _load_and_draw(real_series, _section(real_series, fp, "img.png"))

    assert _snapshot(fp) == before
    assert layer.image_found
    assert sorted(layer.scales) == list(SCALES)


def test_a_blank_section_leaves_a_flat_zarr_unchanged(
    qapp, real_series, tmp_path
):
    fp = _flat(tmp_path)
    before = _snapshot(fp)

    layer = _load_and_draw(real_series, _section(real_series, fp, ""))

    assert _snapshot(fp) == before
    assert not layer.image_found


def test_a_flat_zarr_is_still_moved_into_scale_1(qapp, real_series, tmp_path):
    """The one load that writes: an image at the root and no scale groups."""
    import zarr

    fp = _flat(tmp_path)

    layer = _load_and_draw(real_series, _section(real_series, fp, "img.png"))

    group = zarr.open_group(fp, mode="r")
    assert sorted(group.group_keys()) == ["scale_1"]
    assert list(group.array_keys()) == []
    assert sorted(group["scale_1"].array_keys()) == ["img.png", "other.png"]
    for name in ("img.png", "other.png"):
        np.testing.assert_array_equal(group["scale_1"][name][:], _values(1))
    assert layer.image_found
    assert layer.scales == [1]


@pytest.mark.parametrize("src", ["scale_2", "img.png"])
def test_a_flat_image_named_like_a_scale_is_still_moved(
    qapp, real_series, tmp_path, src
):
    """An array named scale_2 at the root is an image, not a scale level."""
    import zarr

    fp = _flat(tmp_path, names=("scale_2", "img.png"))

    layer = _load_and_draw(real_series, _section(real_series, fp, src))

    group = zarr.open_group(fp, mode="r")
    assert sorted(group.group_keys()) == ["scale_1"]
    assert sorted(group["scale_1"].array_keys()) == ["img.png", "scale_2"]
    np.testing.assert_array_equal(group["scale_1"]["scale_2"][:], _values(1))
    assert layer.image_found
    assert layer.scales == [1]


def test_a_flat_image_named_scale_1_is_not_overwritten(
    qapp, real_series, tmp_path
):
    """Moving would have to make a scale_1 group where that image is."""
    fp = _flat(tmp_path, names=("scale_1", "img.png"))
    before = _snapshot(fp)

    _load_and_draw(real_series, _section(real_series, fp, "img.png"))

    assert _snapshot(fp) == before


def test_a_scale_layout_zarr_with_no_scale_1_is_left_alone(
    qapp, real_series, tmp_path
):
    """A name that reaches into scale_2 is an array at the root path, and the
    zarr has no scale_1 to stop the move."""
    import zarr

    fp = str(tmp_path / "images.zarr")
    group = zarr.open_group(fp, mode="w")
    for k in (2, 4):
        group.create_group(f"scale_{k}").create_dataset(
            "img.png", data=_values(k), chunks=(16, 16)
        )
    before = _snapshot(fp)

    _load_and_draw(real_series, _section(real_series, fp, "scale_2/img.png"))

    assert _snapshot(fp) == before


@pytest.mark.parametrize("src", [pytest.param("", id="blank"), "/"])
def test_a_blank_section_shows_no_image_named_like_a_scale(
    qapp, real_series, tmp_path, src
):
    """A blank name is no image, not the root array named scale_2."""
    fp = _flat(tmp_path, names=("scale_2", "img.png"))
    before = _snapshot(fp)
    section = _section(real_series, fp, src)

    layer = _load_and_draw(real_series, section)

    assert section.zarr_scales == []
    assert not layer.image_found
    assert _snapshot(fp) == before
