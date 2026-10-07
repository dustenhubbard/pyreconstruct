"""Channel-first (1, z, y, x) label arrays in label import and the overlay.

Import indexed a label array by its first axis, so the channel of a 4D array
was read as the section. Section 0 handed a whole (z, y, x) volume to
``cv2.findContours``, which raised, and every later section failed the bounds
check and was skipped without a word. The overlay counted only 3D arrays as
labels, so a 4D one went down the image path, which draws one channel as
nothing. One channel is the labels now. Several channels are refused, and
4D images stay images.
"""
import types

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg import conversions
from PyReconstruct.modules.datatypes import Transform


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


def _volume():
    """Two 32 by 32 sections with different squares, so a slice read from
    the wrong section shows. Label 3 is on both.
    """
    labels = np.zeros((2, 32, 32), dtype=np.uint64)
    labels[0, 4:12, 6:14] = 3
    labels[1, 18:28, 10:20] = 5
    labels[1, 2:6, 24:30] = 3
    return labels


## label import


def _new_series(tmp_path, monkeypatch, name, labels, label_attrs=None):
    """A new series from a 2 by 32 by 32 raw with no attributes."""
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    fp = str(tmp_path / f"{name}.zarr")
    zg = zarr.open(fp, "w")
    zg.create_dataset("raw", data=np.full((2, 32, 32), 9, dtype=np.uint8))
    zg.create_dataset("labels_cells", data=labels).attrs.update(label_attrs or {})
    return conversions.zarrToNewSeries(fp, ["labels_cells"], name)


def _traces(series, snum):
    contours = series.loadSection(snum).contours
    return {
        name: sorted(tuple(map(tuple, trace.points)) for trace in contours[name])
        for name in contours if name.startswith("autoseg_")
    }


@pytest.mark.parametrize(
    "label_attrs",
    [{}, {"voxel_size": [50, 4, 4], "offset": [0, 0, 0]}, {"voxel_size": [1, 50, 4, 4]}],
    ids=["no-attrs", "spatial-size", "channel-first-size"],
)
def test_one_channel_labels_import_like_3d_labels(tmp_path, monkeypatch, label_attrs):
    flat = _new_series(tmp_path, monkeypatch, "flat", _volume())
    channel = _new_series(tmp_path, monkeypatch, "channel", _volume()[None], label_attrs)
    try:
        assert set(_traces(flat, 0)) == {"autoseg_3"}
        assert set(_traces(flat, 1)) == {"autoseg_3", "autoseg_5"}
        for snum in (0, 1):
            assert _traces(channel, snum) == _traces(flat, snum)
    finally:
        flat.close()
        channel.close()


def test_a_later_section_imports_instead_of_being_skipped(tmp_path, real_series):
    s0, s1 = sorted(real_series.sections)[:2]
    zg = zarr.open(str(tmp_path / "later.zarr"), "w")
    raw = zg.create_dataset("raw", shape=(2, 32, 32), dtype=np.uint8)
    raw.attrs.update({
        "voxel_size": [50, 4, 4], "true_mag": 0.004,
        "window": [0, 0, 0.128, 0.128], "sections": [s0, s1],
        "alignment": {str(s): Transform.identity().getList() for s in (s0, s1)},
    })
    labels = zg.create_dataset("labels_x", shape=(1, 2, 32, 32), dtype=np.uint64)
    labels[0, 1, 18:28, 10:20] = 5

    conversions.setDT()
    conversions.importSection(zg, "labels_x", s1, real_series)

    assert "autoseg_5" in real_series.loadSection(s1).contours


def test_several_channels_are_refused_before_any_section(tmp_path):
    fp = str(tmp_path / "channels.zarr")
    zg = zarr.open(fp, "w")
    raw = zg.create_dataset("raw", data=np.zeros((2, 32, 32), dtype=np.uint8))
    raw.attrs.update({"voxel_size": [50, 4, 4], "sections": [0, 1]})
    zg.create_dataset("labels_x", data=np.stack([_volume(), _volume()]))

    with pytest.raises(ValueError, match="has 2 channels"):
        conversions.getLabelsToObjectsData(fp, "labels_x")
    with pytest.raises(ValueError, match="has 2 channels"):
        conversions.importSection(zg, "labels_x", 0, object())


## the overlay


def _layer(tmp_path, name, data):
    from PyReconstruct.modules.backend.view.zarr_layer import ZarrLayer

    fp = str(tmp_path / f"{name}.zarr")
    group = zarr.open_group(fp, mode="w")
    raw = group.create_dataset("raw", shape=(2, 32, 32), dtype="u1")
    raw.attrs.update({
        "voxel_size": [50, 4, 4], "true_mag": 0.004,
        "window": [0, 0, 0.128, 0.128], "sections": [0, 1],
    })
    group.create_dataset("labels", data=data)
    series = types.SimpleNamespace(
        zarr_overlay_fp=fp, zarr_overlay_group="labels",
        sections={}, data={"sections": {}}, getOption=lambda name: None,
    )
    return ZarrLayer(series)


def _drawn(layer, snum):
    """The overlay on section snum, two screen pixels per Zarr pixel."""
    from PySide6.QtGui import QImage

    section = types.SimpleNamespace(n=snum)
    pixmap = layer.generateZarrLayer(section, (64, 64), [0, 0, 0.128, 0.128])
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    ## copied while img is alive: the buffer goes with it
    pixels = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).copy()
    return pixels.reshape(64, 64, 4)


def test_one_channel_overlay_draws_picks_and_merges_like_3d(qapp, tmp_path):
    flat = _layer(tmp_path, "flat", _volume())
    channel = _layer(tmp_path, "channel", _volume()[None])
    assert channel.is_labels

    for snum in (0, 1):
        assert np.array_equal(_drawn(channel, snum), _drawn(flat, snum))
        assert channel.getPresentIds() == flat.getPresentIds()

    ## on section 1 now: label 5 at Zarr row 20, column 12, label 3 at 3, 26
    for layer in (flat, channel):
        assert layer.getID(25, 41) == 5
        assert layer.selectID(25, 41) and layer.selectID(53, 7)
        layer.mergeLabels()

    merged = zarr.open(str(tmp_path / "channel.zarr"), "r")["labels"]
    assert merged.shape == (1, 2, 32, 32)
    assert np.array_equal(merged[0], zarr.open(str(tmp_path / "flat.zarr"), "r")["labels"][:])
    assert 5 not in np.unique(merged[0]) and 3 in np.unique(merged[0, 1])


def test_three_channel_image_stays_an_image(qapp, tmp_path):
    image = np.zeros((3, 2, 32, 32), dtype=np.uint8)
    image[:, 1] = np.array([10, 20, 30], dtype=np.uint8)[:, None, None]
    layer = _layer(tmp_path, "rgb", image)

    assert not layer.is_labels
    assert _drawn(layer, 1)[30, 30].tolist() == [10, 20, 30, 255]


def test_one_float_channel_is_not_labels(tmp_path):
    layer = _layer(tmp_path, "pred", np.zeros((1, 2, 32, 32), dtype=np.float32))

    assert not layer.is_labels
    assert layer.zarr.shape == (1, 2, 32, 32)
