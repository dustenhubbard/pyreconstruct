"""File > New series > From neuroglancer zarr must leave the source Zarr alone.

zarrToNewSeries used to open the source for writing and put ``true_mag``,
``window``, ``sections`` and ``alignment`` on its raw array while it built the
series. It restored only the last three, only when they had existed, and only
when the import succeeded. A failed import also left the new images Zarr
behind, and that Zarr is opened with ``w-``, so a retry with the same name
failed (fork #501).

The thread pool is swapped for one that runs each worker inline, so the label
import really runs without a Qt event loop.
"""
import os

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.autoseg import conversions
from PyReconstruct.modules.datatypes import Series


class _InlinePool:
    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, progress=False):
        self.jobs.append((fn, args))

    def startAll(self, *a, **k):
        for fn, args in self.jobs:
            fn(*args)
        return True


def _snapshot(root):
    """Every file under root, with its bytes."""
    files = {}
    for dirpath, _, names in os.walk(root):
        for name in names:
            fp = os.path.join(dirpath, name)
            with open(fp, "rb") as f:
                files[os.path.relpath(fp, root)] = f.read()
    return files


def _make_source(tmp_path, raw_attrs):
    fp = str(tmp_path / "source.zarr")
    zg = zarr.open(fp, "w")
    raw = zg.create_dataset("raw", data=np.full((3, 8, 8), 7, dtype=np.uint8))
    raw.attrs.update(raw_attrs)
    labels = np.zeros((3, 8, 8), dtype=np.uint64)
    labels[:, 2:6, 2:6] = 5
    lab = zg.create_dataset("labels_cells", data=labels)
    lab.attrs.update({"voxel_size": [50, 4, 4], "offset": [0, 0, 0]})
    return fp


@pytest.fixture
def inline_pool(monkeypatch):
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)


@pytest.mark.parametrize("raw_attrs", [
    # a Zarr this app exported: its own window, sections and a real alignment
    {
        "resolution": [50, 4, 4], "true_mag": 0.004,
        "window": [1.0, 2.0, 0.032, 0.032], "sections": [42],
        "alignment": {"42": [1, 0, 0.5, 0, 1, 0.25]},
    },
    # a plain neuroglancer Zarr with none of those keys, not even true_mag
    {"resolution": [50, 4, 4]},
], ids=["exported", "plain"])
def test_new_series_leaves_the_source_untouched(tmp_path, inline_pool, raw_attrs):
    fp = _make_source(tmp_path, raw_attrs)
    before = _snapshot(fp)

    series = conversions.zarrToNewSeries(fp, ["labels_cells"], "fresh")

    assert _snapshot(fp) == before, "creating a series wrote into the source Zarr"
    # and the labels still came in, on every section, from the local values
    for snum in range(3):
        names = series.loadSection(snum).contours.keys()
        assert any(n.endswith("5") for n in names), f"no labels on section {snum}"
    series.close()


def test_failed_new_series_leaves_the_source_untouched(tmp_path, inline_pool, monkeypatch):
    fp = _make_source(tmp_path, {
        "resolution": [50, 4, 4], "true_mag": 0.004,
        "window": [1.0, 2.0, 0.032, 0.032], "sections": [42],
        "alignment": {"42": [1, 0, 0.5, 0, 1, 0.25]},
    })
    before = _snapshot(fp)
    images = tmp_path / "fresh_images.zarr"

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(Series, "new", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        conversions.zarrToNewSeries(fp, ["labels_cells"], "fresh")

    assert _snapshot(fp) == before, "a failed import left new values in the source"
    assert not images.exists(), "a failed import left its images Zarr behind"

    # so trying again with the same name works
    monkeypatch.undo()
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _InlinePool)
    retry = conversions.zarrToNewSeries(fp, [], "fresh")
    assert retry is not None
    retry.close()


def test_existing_images_zarr_is_not_removed(tmp_path, inline_pool):
    """The images Zarr is created with w-; one already there is not ours to delete."""
    fp = _make_source(tmp_path, {"resolution": [50, 4, 4], "true_mag": 0.004})
    images = tmp_path / "fresh_images.zarr"
    zarr.open(str(images), "w").attrs["keep"] = True

    with pytest.raises(Exception):
        conversions.zarrToNewSeries(fp, [], "fresh")

    assert zarr.open(str(images), "r").attrs["keep"] is True


def test_label_import_error_removes_the_half_built_series(tmp_path, inline_pool, monkeypatch):
    fp = _make_source(tmp_path, {"resolution": [50, 4, 4], "true_mag": 0.004})
    before = _snapshot(fp)

    def boom(*a, **k):
        raise KeyError("voxel_size")

    monkeypatch.setattr(conversions, "labelsToObjects", boom)
    with pytest.raises(KeyError):
        conversions.zarrToNewSeries(fp, ["labels_cells"], "fresh")

    assert _snapshot(fp) == before
    assert not (tmp_path / "fresh_images.zarr").exists()
    assert not (tmp_path / ".fresh").exists()
