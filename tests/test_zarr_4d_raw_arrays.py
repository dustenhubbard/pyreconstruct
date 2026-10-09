"""Channel-first (1, z, y, x) raw arrays in a new series from a Zarr.

``zarrToNewSeries`` unpacked ``z, y, x = raw.shape``, so any 4D raw raised a
bare "too many values to unpack" before the series was made. Label import
flipped y around ``raw.shape[1]``, which is z on a 4D raw. One channel is the
images now, the way one integer channel is the labels. Several channels are
refused before anything is written, since each section is one grayscale image.
"""
import sys
from pathlib import Path

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
    with pytest.raises(conversions.ZarrRefused, match=message):
        _new_series(tmp_path, monkeypatch, "rgb", raw)
    assert not Path(tmp_path / "rgb_images.zarr").exists()


def test_label_y_flips_around_the_height_of_a_one_channel_raw():
    ext = np.array([[6, 4], [14, 12]])
    args = ([0, 0, 0], [50, 4, 4])
    rest = ([0, 0, 0.192, 0.128], Transform.identity(), 0.004)
    flat = conversions.exterior_to_points(ext, *args, np.zeros((2, 32, 48)), *rest)
    channel = conversions.exterior_to_points(ext, *args, np.zeros((1, 2, 32, 48)), *rest)
    assert channel == flat


@pytest.fixture
def recorded_excepthook(monkeypatch):
    """Record what `customExcepthook` would report, without its modal dialog."""
    seen = []
    monkeypatch.setattr(
        sys, "excepthook", lambda exctype, value, tb: seen.append(
            (exctype.__name__, str(value))
        )
    )
    return seen


def _new_from_zarr(window, dialogs, zarr_fp, label_groups=()):
    dialogs.file_responses.append(str(zarr_fp))
    dialogs.responses.append((["new", list(label_groups)], True))
    window.newfromngzarr_act.trigger()


@pytest.mark.gui
@pytest.mark.parametrize(
    "raw, labels, notice",
    [
        (
            np.zeros((3, 2, 32, 48), dtype=np.uint8),
            None,
            "This Zarr raw array has 3 channels. PyReconstruct shows each "
            "section as one grayscale image, so save raw as (z, y, x) or "
            "(1, z, y, x).",
        ),
        (
            _raw(),
            np.zeros((2, 2, 32, 48), dtype=np.uint64),
            "This Zarr label array has 2 channels. PyReconstruct imports "
            "labels from a single channel, so save them as (z, y, x) or "
            "(1, z, y, x).",
        ),
    ],
    ids=["raw-channels", "label-channels"],
)
def test_new_from_zarr_shows_a_refusal_as_a_notice(
    main_window, main_window_dialogs, recorded_excepthook, monkeypatch,
    tmp_path, raw, labels, notice,
):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    zarr_fp = tmp_path / "refused.zarr"
    zg = zarr.open(str(zarr_fp), "w")
    zg.create_dataset("raw", data=raw)
    label_groups = []
    if labels is not None:
        zg.create_dataset("labels_cells", data=labels)
        label_groups.append("labels_cells")
    series = main_window.series

    _new_from_zarr(main_window, main_window_dialogs, zarr_fp, label_groups)

    assert main_window_dialogs.notices == [notice]
    assert recorded_excepthook == []
    assert main_window.series is series
    assert not (tmp_path / "new_images.zarr").exists()


@pytest.mark.gui
def test_new_from_zarr_reports_an_unexpected_error(
    main_window, main_window_dialogs, recorded_excepthook, tmp_path
):
    """A damaged chunk is not a refusal, so it reaches the error report."""
    zarr_fp = tmp_path / "damaged.zarr"
    zarr.open(str(zarr_fp), "w").create_dataset(
        "raw", data=np.ones((1, 4, 4), dtype=np.uint8), compressor=None
    )
    chunk = zarr_fp / "raw" / "0.0.0"
    chunk.write_bytes(chunk.read_bytes()[:7])
    series = main_window.series

    _new_from_zarr(main_window, main_window_dialogs, zarr_fp)

    assert main_window_dialogs.notices == []
    assert recorded_excepthook == [
        ("ValueError", "cannot reshape array of size 7 into shape (1,4,4)")
    ]
    assert main_window.series is series
