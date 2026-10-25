"""A section change reads the next section's image before it is asked for.

FieldWidget.changeSection starts a read of the image one section on in the
direction the change went (ImageLayer.readAhead, on a thread of its own), and
the change to that section takes the decoded image instead of reading the
file again. The image shown is always the file as it is at that moment: a
file replaced in between is read again. Nothing is read ahead on a flicker
between the A and B sections or for a zarr.
"""
import gc
import os
import threading
import weakref

import numpy as np
import pytest
from PySide6.QtGui import QImage

from PyReconstruct.modules.backend.view import image_layer

pytestmark = pytest.mark.gui

W, H = 32, 24
# the first sections of the sample series, by the image name each one keeps
NAMES = {0: "000ZGBJY.tif", 1: "001ZGBJY.tif", 2: "002ZGBJY.tif", 3: "003ZGBJY.tif"}


def _pixels(k : int) -> np.ndarray:
    return ((np.arange(W * H, dtype=np.uint32) * 7 + k * 40) % 256).astype(np.uint8).reshape(H, W)


def _write(path, k : int):
    arr = np.ascontiguousarray(_pixels(k))
    image = QImage(arr.data, W, H, W, QImage.Format.Format_Grayscale8).copy()
    if not image.save(str(path)):
        pytest.skip("Qt cannot write a TIFF here")


def _gray(image : QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    buf = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    return buf.reshape(image.height(), image.bytesPerLine())[:, :image.width()].copy()


@pytest.fixture
def images(tmp_path, qapp):
    """A folder of small, distinct TIFFs named as the sample series' images."""
    for n, name in NAMES.items():
        _write(tmp_path / name, n)
    return tmp_path


@pytest.fixture
def read_ahead(monkeypatch):
    """A fresh read-ahead slot for each test."""
    slot = image_layer._ReadAhead()
    monkeypatch.setattr(image_layer, "_READ_AHEAD", slot)
    return slot


@pytest.fixture
def decodes(monkeypatch):
    """Every image file decoded through the layer's module: (path, thread)."""
    calls = []

    class Counting(QImage):
        def __init__(self, *args):
            super().__init__(*args)
            if args and isinstance(args[0], str):
                calls.append((args[0], threading.get_ident()))

    monkeypatch.setattr(image_layer, "QImage", Counting)
    return calls


def _wait(slot):
    """Until the read asked for has finished (or nothing is asked for)."""
    with slot._cond:
        while slot._wanted is not None and slot._result is None and slot._worker is not None:
            assert slot._cond.wait(10), "the read did not finish"


def _slow_decoder(monkeypatch):
    """Image files decoded through the layer's module on a thread other than
    the main one wait on the returned event; the paths are listed as the
    decodes start."""
    release = threading.Event()
    started = []

    class Slow(QImage):
        def __init__(self, *args):
            super().__init__(*args)
            if args and isinstance(args[0], str) and threading.current_thread() is not threading.main_thread():
                started.append(args[0])
                assert release.wait(15)

    monkeypatch.setattr(image_layer, "QImage", Slow)
    return release, started


def _workers():
    return [t for t in threading.enumerate() if t.name == "image-read-ahead" and t.is_alive()]


def _until(check):
    for _ in range(250):
        if check():
            return
        threading.Event().wait(0.02)
    assert check()


def _bump(path, k : int):
    """Replace the file's pixels and move its modification time on."""
    _write(path, k)
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


# the slot on its own

def test_take_gives_the_image_read_for_the_path(images, read_ahead):
    path = str(images / NAMES[0])
    read_ahead.start(path)
    image = read_ahead.take(path)
    assert image is not None
    assert np.array_equal(_gray(image), _pixels(0))
    # the slot is emptied by the hand-over
    assert read_ahead.take(path) is None


def test_take_of_another_path_leaves_the_read_in_place(images, read_ahead):
    path = str(images / NAMES[0])
    read_ahead.start(path)
    assert read_ahead.take(str(images / NAMES[1])) is None
    image = read_ahead.take(path)
    assert image is not None
    assert np.array_equal(_gray(image), _pixels(0))


def test_a_second_start_on_the_same_path_reads_once(images, read_ahead, decodes):
    path = str(images / NAMES[0])
    read_ahead.start(path)
    _wait(read_ahead)
    read_ahead.start(path)
    _wait(read_ahead)
    assert [p for p, _ in decodes] == [path]
    assert read_ahead.take(path) is not None


def test_a_start_on_another_path_replaces_the_read(images, read_ahead):
    first, second = str(images / NAMES[0]), str(images / NAMES[1])
    read_ahead.start(first)
    read_ahead.start(second)
    assert read_ahead.take(first) is None
    image = read_ahead.take(second)
    assert image is not None
    assert np.array_equal(_gray(image), _pixels(1))


def test_a_file_replaced_after_the_read_is_not_handed_over(images, read_ahead):
    path = str(images / NAMES[0])
    read_ahead.start(path)
    _wait(read_ahead)
    _bump(images / NAMES[0], 9)
    assert read_ahead.take(path) is None


def test_a_file_removed_after_the_read_is_not_handed_over(images, read_ahead):
    path = str(images / NAMES[0])
    read_ahead.start(path)
    _wait(read_ahead)
    os.remove(path)
    assert read_ahead.take(path) is None


def test_a_missing_file_reads_nothing(tmp_path, qapp, read_ahead):
    path = str(tmp_path / "none.tif")
    read_ahead.start(path)
    assert read_ahead.take(path) is None


def test_an_unreadable_image_reads_nothing(tmp_path, qapp, read_ahead):
    path = tmp_path / "bad.tif"
    path.write_bytes(b"not an image")
    read_ahead.start(str(path))
    assert read_ahead.take(str(path)) is None


# in the field

@pytest.fixture
def field(main_window, images, read_ahead):
    """The field on section 0 of the sample series, over the images folder.

    The series opens on a later section; the change to 0 goes back, so
    nothing is read ahead by it (there is no section before 0).
    """
    main_window.series.src_dir = str(images)
    main_window.changeSection(0)
    assert read_ahead._wanted is None
    return main_window.field


def _main():
    return threading.main_thread().ident


def test_a_change_reads_the_next_section_ahead_and_the_next_change_takes_it(
        field, images, read_ahead, decodes):
    mw = field.mainwindow
    assert field.section.n == 0
    mw.changeSection(1)
    # the section one on, read on another thread
    assert read_ahead._wanted == str(images / NAMES[2])
    _wait(read_ahead)
    ahead = [(p, t) for p, t in decodes if p == str(images / NAMES[2])]
    assert len(ahead) == 1 and ahead[0][1] != _main()

    mw.changeSection(2)
    assert field.section_layer.image_found
    assert np.array_equal(_gray(field.section_layer.image), _pixels(2))
    # taken, not read again
    assert [p for p, _ in decodes if p == str(images / NAMES[2])] == [ahead[0][0]]
    # and the read moved one on
    assert read_ahead._wanted == str(images / NAMES[3])


def test_a_change_back_reads_the_section_before(field, images, read_ahead):
    mw = field.mainwindow
    mw.changeSection(2)
    mw.changeSection(1)
    assert read_ahead._wanted == str(images / NAMES[0])


def test_a_flicker_between_a_and_b_reads_nothing_new(field, images, read_ahead):
    mw = field.mainwindow
    mw.changeSection(1)
    assert read_ahead._wanted == str(images / NAMES[2])
    mw.changeSection(0)  # the B section: a swap, no file read
    assert read_ahead._wanted == str(images / NAMES[2])
    mw.changeSection(1)
    assert read_ahead._wanted == str(images / NAMES[2])


def test_the_first_and_last_sections_read_nothing_past_the_end(field, images, read_ahead):
    mw = field.mainwindow
    last = sorted(mw.series.sections)[-1]
    mw.changeSection(last)
    assert read_ahead._wanted is None
    mw.changeSection(1)  # back, so the section before it is read
    assert read_ahead._wanted == str(images / NAMES[0])
    mw.changeSection(0)  # takes that read; nothing before the first section
    assert np.array_equal(_gray(field.section_layer.image), _pixels(0))
    assert read_ahead._wanted is None


def test_a_file_replaced_between_the_read_and_the_change_is_read_again(
        field, images, read_ahead, decodes):
    mw = field.mainwindow
    mw.changeSection(1)
    _wait(read_ahead)
    _bump(images / NAMES[2], 5)
    mw.changeSection(2)
    assert field.section_layer.image_found
    assert np.array_equal(_gray(field.section_layer.image), _pixels(5))
    main_reads = [p for p, t in decodes if p == str(images / NAMES[2]) and t == _main()]
    assert main_reads == [str(images / NAMES[2])]


def test_a_zarr_series_reads_nothing_ahead(main_window, tmp_path, read_ahead):
    main_window.series.src_dir = str(tmp_path / "images.zarr")
    main_window.field.section_layer.loadImage()
    main_window.changeSection(1)
    assert read_ahead._wanted is None


# one read at a time, one image held

def test_requests_made_during_a_read_leave_one_read_under_way(images, read_ahead, monkeypatch):
    release, started = _slow_decoder(monkeypatch)
    paths = [str(images / NAMES[n]) for n in (0, 1, 2)]
    read_ahead.start(paths[0])
    for _ in range(100):
        if started:
            break
        threading.Event().wait(0.02)
    assert started == [paths[0]]
    read_ahead.start(paths[1])
    read_ahead.start(paths[2])
    # still one worker, still one decode started: the newer requests wait
    assert len(_workers()) == 1
    assert started == [paths[0]]
    release.set()
    image = read_ahead.take(paths[2])
    # the first read was dropped, the second was never made, the third was read
    assert started == [paths[0], paths[2]]
    assert image is not None
    assert np.array_equal(_gray(image), _pixels(2))
    _wait(read_ahead)
    for _ in range(100):
        if not _workers():
            break
        threading.Event().wait(0.02)
    assert _workers() == []


def _far_jump_images(mw, images):
    """The images of sections 4 to 6, and the paths read ahead by jumps to 1, 3, 5."""
    for n in (4, 5, 6):
        _write(images / mw.series.data["sections"][n]["src"], n)
    return [str(images / mw.series.data["sections"][n]["src"]) for n in (2, 4, 6)]


def _check_far_jump_outcome(read_ahead, started, ahead, allowed):
    """What holds in every order the worker can run in: one worker at most,
    one image held at most, no request read twice, no request read that was
    replaced before the worker reached it (`allowed` says which could have
    been), and the last jump's image is the one taken."""
    assert len(_workers()) <= 1
    assert read_ahead._wanted == ahead[2]
    assert len(started) == len(set(started))
    assert set(started) <= set(allowed)
    assert started[-1] == ahead[2]
    image = read_ahead.take(ahead[2])
    assert image is not None
    assert np.array_equal(_gray(image), _pixels(6))
    assert read_ahead._result is None and read_ahead._wanted is None
    _until(lambda: not _workers())


def test_far_jumps_while_the_first_read_is_under_way(field, images, read_ahead, monkeypatch):
    """The worker is held in the first jump's read while the next two jumps
    come: one worker, one read; the second request is replaced before it is
    read, the third is read after the first finishes."""
    mw = field.mainwindow
    ahead = _far_jump_images(mw, images)
    gates, started, _ = _gated_decoder(monkeypatch)
    for path in ahead:
        gates[path] = threading.Event()
    mw.changeSection(1)
    _until(lambda: started == [ahead[0]])
    mw.changeSection(3)
    mw.changeSection(5)
    assert len(_workers()) == 1
    assert started == [ahead[0]]
    for gate in gates.values():
        gate.set()
    _until(lambda: len(started) == 2)
    assert started == [ahead[0], ahead[2]]
    _check_far_jump_outcome(read_ahead, started, ahead, allowed=[ahead[0], ahead[2]])


def test_far_jumps_before_the_worker_runs(field, images, read_ahead, monkeypatch):
    """The worker does not run until all three jumps are made: it reads the
    last request only."""
    mw = field.mainwindow
    ahead = _far_jump_images(mw, images)
    gates, started, _ = _gated_decoder(monkeypatch)
    for path in ahead:
        gates[path] = threading.Event()
        gates[path].set()
    go = threading.Event()
    run = image_layer._ReadAhead._run

    def held_run(self):
        assert go.wait(15)
        run(self)

    monkeypatch.setattr(image_layer._ReadAhead, "_run", held_run)
    for n in (1, 3, 5):
        mw.changeSection(n)
    assert len(_workers()) == 1
    assert started == []
    go.set()
    _until(lambda: started)
    assert started == [ahead[2]]
    _check_far_jump_outcome(read_ahead, started, ahead, allowed=[ahead[2]])


def test_far_jumps_in_the_field_keep_one_read_under_way(field, images, read_ahead, monkeypatch):
    """The worker runs as it will: whichever order it takes, the outcome
    is the same."""
    mw = field.mainwindow
    ahead = _far_jump_images(mw, images)
    release, started = _slow_decoder(monkeypatch)
    try:
        for n in (1, 3, 5):
            mw.changeSection(n)
        assert len(_workers()) == 1
    finally:
        release.set()
    _until(lambda: started and started[-1] == ahead[2])
    _check_far_jump_outcome(read_ahead, started, ahead, allowed=ahead)


# the series closes or changes

def test_closing_the_window_drops_the_image_held(field, images, read_ahead):
    mw = field.mainwindow
    mw.changeSection(1)
    _wait(read_ahead)
    held = weakref.ref(read_ahead._result[1])
    mw.series.modified = False
    assert mw.close()
    gc.collect()
    assert read_ahead._wanted is None
    assert held() is None


def test_closing_the_window_does_not_wait_for_a_read_under_way(field, images, read_ahead, monkeypatch):
    mw = field.mainwindow
    release, started = _slow_decoder(monkeypatch)
    try:
        mw.changeSection(1)
        for _ in range(100):
            if started:
                break
            threading.Event().wait(0.02)
        assert started
        mw.series.modified = False
        assert mw.close()
        assert read_ahead._wanted is None
    finally:
        release.set()
    for _ in range(100):
        if not _workers():
            break
        threading.Event().wait(0.02)
    # the read finished into nothing
    assert _workers() == []
    assert read_ahead._result is None
    assert read_ahead._wanted is None


def test_opening_another_series_drops_the_image_held(field, images, read_ahead):
    mw = field.mainwindow
    mw.changeSection(1)
    _wait(read_ahead)
    held = weakref.ref(read_ahead._result[1])
    before = mw.series
    mw.openSeries(jser_fp=str(before.jser_fp), query_prev=False)
    gc.collect()
    assert mw.series is not before
    assert read_ahead._wanted is None
    assert held() is None


# the file on disk is the one shown

def test_a_same_size_replacement_with_the_old_modification_time_is_read_again(images, read_ahead):
    path = images / NAMES[0]
    read_ahead.start(str(path))
    _wait(read_ahead)
    old = path.stat()
    other = images / "other.tif"
    _write(other, 9)
    assert other.stat().st_size == old.st_size
    os.utime(other, ns=(old.st_atime_ns, old.st_mtime_ns))
    os.replace(other, path)
    assert read_ahead.take(str(path)) is None
    assert np.array_equal(_gray(QImage(str(path))), _pixels(9))


def _gated_decoder(monkeypatch):
    """Like _slow_decoder, with one gate per path: a decode of a path waits on
    its own event, so one read can finish while the next is held. `refs`
    keeps a weak reference to each image decoded, by path."""
    gates = {}
    started = []
    refs = {}

    class Gated(QImage):
        def __init__(self, *args):
            super().__init__(*args)
            if args and isinstance(args[0], str) and threading.current_thread() is not threading.main_thread():
                started.append(args[0])
                refs[args[0]] = weakref.ref(self)
                assert gates.setdefault(args[0], threading.Event()).wait(15)

    monkeypatch.setattr(image_layer, "QImage", Gated)
    return gates, started, refs


def test_a_replaced_image_is_released_before_the_next_read(images, read_ahead, monkeypatch):
    gates, started, refs = _gated_decoder(monkeypatch)
    first, second = str(images / NAMES[0]), str(images / NAMES[1])
    gates[first], gates[second] = threading.Event(), threading.Event()
    read_ahead.start(first)
    _until(lambda: first in started)
    # replaced while its read is under way, then the read finishes
    read_ahead.start(second)
    gates[first].set()
    _until(lambda: second in started)
    assert started == [first, second]
    # the replaced image is gone while the next one is still being read
    gc.collect()
    assert refs[first]() is None
    # and stays gone when the slot is emptied under that read
    read_ahead.drop()
    gc.collect()
    assert refs[first]() is None
    gates[second].set()
    _until(lambda: not _workers())
    gc.collect()
    assert read_ahead._result is None
    assert refs[second]() is None
