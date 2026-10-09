"""Channel-first (1, z, y, x) raw arrays in a new series from a Zarr.

``zarrToNewSeries`` unpacked ``z, y, x = raw.shape``, so any 4D raw raised a
bare "too many values to unpack" before the series was made. Label import
flipped y around ``raw.shape[1]``, which is z on a 4D raw. One channel is the
images now, the way one integer channel is the labels. Several channels are
refused before anything is written, since each section is one grayscale image.
"""
import types
from pathlib import Path

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg import conversions
from PyReconstruct.modules.datatypes import Transform
from PyReconstruct.modules.gui.main import main_window as mw


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        for fn, args in self.jobs:
            fn(*args)
        return True


def _raw():
    """Two 32 by 48 sections with different pixels, so a section read from
    the wrong axis shows. Height and width differ from the section count.
    """
    raw = np.zeros((2, 32, 48), dtype=np.uint8)
    raw[0] = 10
    raw[1, :, :24] = 200
    return raw


def _labels():
    labels = np.zeros((2, 32, 48), dtype=np.uint64)
    labels[0, 4:12, 6:14] = 3
    labels[1, 18:28, 10:20] = 5
    return labels


def _new_series(tmp_path, monkeypatch, name, raw, raw_attrs=None):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    fp = str(tmp_path / f"{name}.zarr")
    zg = zarr.open(fp, "w")
    zg.create_dataset("raw", data=raw).attrs.update(raw_attrs or {})
    zg.create_dataset("labels_cells", data=_labels())
    return conversions.zarrToNewSeries(fp, ["labels_cells"], name)


def _traces(series, snum):
    contours = series.loadSection(snum).contours
    return {
        name: sorted(tuple(map(tuple, trace.points)) for trace in contours[name])
        for name in contours if name.startswith("autoseg_")
    }


def _images(tmp_path, name):
    scale = zarr.open(str(tmp_path / f"{name}_images.zarr"), "r")["scale_1"]
    return {src: scale[src][:] for src in scale}


@pytest.mark.parametrize(
    "raw_attrs",
    [{}, {"voxel_size": [1, 50, 4, 4]}],
    ids=["no-attrs", "channel-first-size"],
)
def test_one_channel_raw_makes_the_same_series_as_3d_raw(tmp_path, monkeypatch, raw_attrs):
    spatial = {"voxel_size": raw_attrs["voxel_size"][1:]} if raw_attrs else {}
    flat = _new_series(tmp_path, monkeypatch, "flat", _raw(), spatial)
    channel = _new_series(tmp_path, monkeypatch, "channel", _raw()[None], raw_attrs)
    try:
        assert sorted(channel.sections) == sorted(flat.sections) == [0, 1]
        for snum in (0, 1):
            flat_section = flat.loadSection(snum)
            channel_section = channel.loadSection(snum)
            assert channel_section.mag == flat_section.mag
            assert channel_section.thickness == flat_section.thickness
            assert _traces(channel, snum) == _traces(flat, snum)
        assert set(_traces(flat, 0)) == {"autoseg_3"}
        assert set(_traces(flat, 1)) == {"autoseg_5"}

        flat_images = _images(tmp_path, "flat")
        channel_images = _images(tmp_path, "channel")
        assert set(channel_images) == set(flat_images) == {"section0", "section1"}
        for src, image in flat_images.items():
            assert image.shape == (32, 48)
            np.testing.assert_array_equal(channel_images[src], image)
    finally:
        flat.close()
        channel.close()


@pytest.mark.parametrize(
    "raw, message",
    [
        (np.zeros((3, 2, 32, 48), dtype=np.uint8), "has 3 channels"),
        (np.zeros((32, 48), dtype=np.uint8), "has 2 axes"),
    ],
    ids=["three-channels", "2d"],
)
def test_unreadable_raw_is_refused_before_anything_is_written(tmp_path, monkeypatch, raw, message):
    with pytest.raises(ValueError, match=message):
        _new_series(tmp_path, monkeypatch, "rgb", raw)
    assert not Path(tmp_path / "rgb_images.zarr").exists()


def test_label_y_flips_around_the_height_of_a_one_channel_raw():
    ext = np.array([[6, 4], [14, 12]])
    args = ([0, 0, 0], [50, 4, 4])
    rest = ([0, 0, 0.192, 0.128], Transform.identity(), 0.004)
    flat = conversions.exterior_to_points(ext, *args, np.zeros((2, 32, 48)), *rest)
    channel = conversions.exterior_to_points(ext, *args, np.zeros((1, 2, 32, 48)), *rest)
    assert channel == flat


def test_new_from_zarr_shows_a_refusal_as_a_notice(monkeypatch, tmp_path):
    zarr_fp = tmp_path / "rgb.zarr"
    zarr_fp.mkdir()
    notified = []
    monkeypatch.setattr(
        mw, "FileDialog", types.SimpleNamespace(get=lambda *a, **k: str(zarr_fp))
    )
    monkeypatch.setattr(
        mw, "QuickDialog",
        types.SimpleNamespace(get=lambda *a, **k: (["new", []], True)),
    )
    monkeypatch.setattr(mw, "notify", lambda *a, **k: notified.append(a))

    def refuse(*args):
        raise ValueError("This Zarr raw array has 3 channels.")

    monkeypatch.setattr(mw, "zarrToNewSeries", refuse)
    opened = []
    stub = types.SimpleNamespace(openSeries=opened.append)

    mw.MainWindow.newFromNgZarr(stub)

    assert notified == [("This Zarr raw array has 3 channels.",)]
    assert opened == []
