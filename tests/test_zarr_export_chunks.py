"""Neuroglancer zarr export: final chunks written once, empty chunks not stored.

``seriesToZarr`` wrote raw with (1, 256, 256) chunks, one file per chunk,
empty chunks included, and ``rechunk`` then copied it all to (8, 256, 256) and
deleted the original. raw and labels are now written with (8, 256, 256)
chunks, a chunk of only 0 is not stored, and ``rechunk`` leaves an array
already at its target chunks alone.

The comparisons draw the old way by hand: each whole section drawn at once
into a (1, 256, 256) array. ``rechunk`` changes only the chunks, which the
last test checks where dask is installed.
"""

import random
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
zarr = pytest.importorskip("zarr")

from PyReconstruct.modules.backend.autoseg import conversions  # noqa: E402
from PyReconstruct.modules.backend.view import SectionLayer  # noqa: E402
from PyReconstruct.modules.datatypes import Series, Trace, Transform  # noqa: E402

MAG = 0.01  # µm per image pixel
N_SECTIONS = 13  # not a multiple of 8: the last block is 5 deep
## (w, h) of each image; the smaller ones leave empty chunks in the window
SIZES = [(700, 600), (300, 260)] * 7
GROUP = "cells"


def _image(i, w, h):
    rng = np.random.default_rng(i)
    image = np.zeros((h, w), np.uint8)
    ## tissue in a corner, 0 everywhere else
    image[: h // 2, : w // 2] = rng.integers(1, 255, (h // 2, w // 2), np.uint8)
    return image


@pytest.fixture
def series(tmp_path, qapp):
    images = []
    for i in range(N_SECTIONS):
        fp = tmp_path / f"img{i:02d}.png"
        cv2.imwrite(str(fp), _image(i, *SIZES[i]))
        images.append(str(fp))

    series = Series.new(images, "chunks", MAG, 0.05)
    for snum in (3, 9):  # a rotated alignment draws by its own path
        section = series.loadSection(snum)
        section.tform = Transform([0.98, -0.17, 0.3, 0.17, 0.98, -0.2])
        section.save()
    for snum in (2, 5, 8, 12):
        section = series.loadSection(snum)
        trace = Trace(f"cell{snum % 2}", (255, 0, 0), closed=True)
        trace.points = [(1.0, 1.0), (4.5, 1.2), (4.0, 5.1), (1.2, 4.4)]
        section.addTrace(trace, log_event=False)
        section.save()
        series.object_groups.add(GROUP, trace.name)
    series.save()
    yield series
    series.close()


SECTIONS = list(range(N_SECTIONS))
WINDOW = [0.0, 0.0, 7.0, 6.0]
SHAPE = (N_SECTIONS, 600, 700)


def _old_raw(series, fp):
    """raw as the export used to write it, before its rechunk."""
    zg = zarr.open(str(fp), "w")
    raw = zg.create_dataset("raw", shape=SHAPE, chunks=(1, 256, 256), dtype=np.uint8)
    for z, snum in enumerate(SECTIONS):
        layer = SectionLayer(series.loadSection(snum), series)
        raw[z] = layer.generateImageArray((SHAPE[2], SHAPE[1]), WINDOW, bc=False)
    return zg


def _chunk_files(fp, name):
    return len([p for p in Path(fp, name).iterdir() if not p.name.startswith(".")])


def test_raw_matches_the_old_export_with_final_chunks_and_fewer_files(
    series, tmp_path, monkeypatch
):
    ## several bands per section, and one that is not a whole band
    monkeypatch.setattr(conversions, "_EXPORT_BAND_ROWS", 256)

    old = _old_raw(series, tmp_path / "old.zarr")
    old_files = _chunk_files(tmp_path / "old.zarr", "raw")
    new_fp = conversions.seriesToZarr(
        series, SECTIONS, MAG, WINDOW, data_fp=str(tmp_path / "new.zarr")
    )
    new = zarr.open(new_fp, "r")

    assert new["raw"].chunks == (8, 256, 256)
    assert new["raw"].fill_value == 0
    np.testing.assert_array_equal(new["raw"][:], old["raw"][:])
    ## a corner of tissue, the rest 0
    assert 0 < np.count_nonzero(new["raw"][:]) < new["raw"].size // 2

    new_files = _chunk_files(new_fp, "raw")
    assert old_files == N_SECTIONS * 3 * 3  # every chunk, empty ones too
    assert new_files < new["raw"].nchunks  # the empty ones are not stored


def test_labels_match_the_old_export_with_final_chunks(series, tmp_path):
    old_fp = conversions.seriesToZarr(
        series, SECTIONS, MAG, WINDOW, data_fp=str(tmp_path / "old.zarr")
    )
    new_fp = conversions.seriesToZarr(
        series, SECTIONS, MAG, WINDOW, data_fp=str(tmp_path / "new.zarr")
    )
    assert conversions.seriesToLabels(
        series, old_fp, group=GROUP, img_mag=MAG, chunk_size=(1, 256, 256)
    )
    assert conversions.seriesToLabels(series, new_fp, group=GROUP, img_mag=MAG)

    old = zarr.open(old_fp, "r")[f"labels_{GROUP}"]
    new = zarr.open(new_fp, "r")[f"labels_{GROUP}"]
    assert old.chunks == (1, 256, 256)
    assert new.chunks == (8, 256, 256)
    assert new.dtype == np.uint64
    np.testing.assert_array_equal(new[:], old[:])
    assert set(np.unique(new[:])) == {0, 1, 2}
    assert dict(new.attrs) == dict(old.attrs)
    ## four sections hold labels, in a few chunks each
    assert 0 < _chunk_files(new_fp, f"labels_{GROUP}") < new.nchunks // 2


def test_rechunk_leaves_an_export_at_its_target_chunks_alone(
    series, tmp_path, monkeypatch
):
    fp = conversions.seriesToZarr(
        series, SECTIONS, MAG, WINDOW, data_fp=str(tmp_path / "out.zarr")
    )
    raw_dir = Path(fp, "raw")
    before = {p.name: p.stat().st_ino for p in raw_dir.iterdir()}
    ## no dask needed for an array that is already rechunked
    monkeypatch.setitem(sys.modules, "dask", None)
    monkeypatch.setitem(sys.modules, "dask.array", None)

    assert conversions.rechunk(fp) is True

    assert {p.name: p.stat().st_ino for p in raw_dir.iterdir()} == before
    assert not Path(fp, "raw_rechunked").exists()


## SectionBlocks: each block is written once, by one worker


class _RecordingArray:
    """Stands in for a zarr array and records every write."""

    def __init__(self, shape, chunks):
        self.shape = shape
        self.chunks = chunks
        self.dtype = np.dtype(np.uint16)
        self.data = np.zeros(shape, self.dtype)
        self.writes = []
        self._lock = threading.Lock()

    def __setitem__(self, key, value):
        with self._lock:
            self.writes.append((key, threading.get_ident()))
        self.data[key] = value


@pytest.mark.parametrize("n, depth", [(13, 8), (29, 8), (8, 8), (5, 4)])
def test_each_block_is_written_once_whole_on_chunk_boundaries(n, depth):
    array = _RecordingArray((n, 3, 4), (depth, 3, 4))
    blocks = conversions.SectionBlocks(array)
    order = list(range(n))
    random.Random(n).shuffle(order)

    def worker(z):
        plane = blocks.plane(z)
        time.sleep(random.random() / 200)
        plane[:] = z + 1
        blocks.done(z)

    threads = [threading.Thread(target=worker, args=(z,)) for z in order]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    regions = sorted((key.start, key.stop) for key, _ in array.writes)
    assert regions == [(z0, min(z0 + depth, n)) for z0 in range(0, n, depth)]
    np.testing.assert_array_equal(
        array.data, np.broadcast_to(np.arange(1, n + 1)[:, None, None], array.shape)
    )
    assert blocks._open == {}


def test_a_block_with_a_failed_section_is_dropped_and_makes_room():
    array = _RecordingArray((24, 2, 2), (8, 2, 2))
    blocks = conversions.SectionBlocks(array, max_blocks=1)
    for z in range(24):
        blocks.plane(z)  # with one block allowed, this waits on a held block
        blocks.done(z, failed=z == 3)

    assert [(key.start, key.stop) for key, _ in array.writes] == [(8, 16), (16, 24)]
    assert blocks._held == 0


@pytest.mark.parametrize("max_blocks", [1, 2])
def test_no_more_blocks_are_held_than_allowed(max_blocks):
    """Ten workers, started in z order like the pool's, never hold more."""
    n = 40
    array = _RecordingArray((n, 3, 4), (8, 3, 4))
    blocks = conversions.SectionBlocks(array, max_blocks=max_blocks)
    most = [0]
    queue = list(range(n))
    queue_lock = threading.Lock()

    def worker():
        while True:
            with queue_lock:
                if not queue:
                    return
                z = queue.pop(0)
            plane = blocks.plane(z)
            most[0] = max(most[0], blocks._held)
            time.sleep(random.random() / 500)
            plane[:] = z + 1
            blocks.done(z)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "a worker never finished"

    assert most[0] <= max_blocks
    assert len(array.writes) == n // 8
    np.testing.assert_array_equal(array.data[:, 0, 0], np.arange(1, n + 1))


class _ThreadedPool:
    """Ten threads taking the workers in the order they were made, like
    ThreadPoolProgBar, without its progress and error windows."""

    def __init__(self):
        self.jobs = []

    def createWorker(self, fn, *args, **kwargs):
        self.jobs.append((fn, args))

    def startAll(self, *args, **kwargs):
        lock, failed = threading.Lock(), []

        def run():
            while True:
                with lock:
                    if not self.jobs:
                        return
                    fn, args = self.jobs.pop(0)
                try:
                    fn(*args)
                except Exception as e:
                    failed.append(e)

        threads = [threading.Thread(target=run) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
            assert not t.is_alive(), "the export hung"
        return not failed


def test_a_failed_section_stops_the_export_without_a_hang(series, tmp_path, monkeypatch):
    real = SectionLayer.generateImageArray

    def fail_on_section_5(self, *args, **kwargs):
        if self.section.n == 5:
            raise RuntimeError("cannot draw")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(SectionLayer, "generateImageArray", fail_on_section_5)
    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _ThreadedPool)
    ## one block at a time: the second block waits on the failed first one
    blocks = conversions.SectionBlocks
    monkeypatch.setattr(conversions, "SectionBlocks", lambda a: blocks(a, max_blocks=1))
    out = tmp_path / "out.zarr"

    assert conversions.seriesToZarr(series, SECTIONS, MAG, WINDOW, data_fp=str(out)) is None
    assert not out.exists()


def test_labels_give_each_worker_one_whole_block_in_order(series, tmp_path, monkeypatch):
    fp = conversions.seriesToZarr(
        series, SECTIONS, MAG, WINDOW, data_fp=str(tmp_path / "out.zarr")
    )
    jobs = []

    class _Pool:
        def createWorker(self, fn, *args, **kwargs):
            jobs.append((fn, args))

        def startAll(self, *args, **kwargs):
            for fn, args in jobs:
                fn(*args)
            return True

    monkeypatch.setattr(conversions, "ThreadPoolProgBar", _Pool)
    assert conversions.seriesToLabels(series, fp, group=GROUP, img_mag=MAG)

    zs = [[job[5] for job in args[0]] for _, args in jobs]
    assert zs == [list(range(0, 8)), list(range(8, 13))]


def test_rechunk_still_rechunks_an_old_export_to_the_same_values(series, tmp_path):
    pytest.importorskip("dask")
    fp = tmp_path / "old.zarr"
    before = _old_raw(series, fp)["raw"][:]
    files_before = _chunk_files(fp, "raw")

    assert conversions.rechunk(fp) is True

    raw = zarr.open(str(fp), "r")["raw"]
    assert raw.chunks == (8, 256, 256)
    np.testing.assert_array_equal(raw[:], before)
    ## and a chunk of only 0 is not stored
    assert _chunk_files(fp, "raw") < raw.nchunks < files_before
