"""Bounded section preparation and paging through real widgets."""
import builtins
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import weakref

import pytest

from PyReconstruct.modules.datatypes import Section, Trace, Transform
from PyReconstruct.modules.datatypes import section_read_ahead as ahead
from PyReconstruct.modules.gui.main import field_widget_1_base


@pytest.fixture
def slot(monkeypatch):
    slot = ahead.SectionReadAhead()
    monkeypatch.setattr(ahead, "READ_AHEAD", slot)
    monkeypatch.setattr(field_widget_1_base, "READ_AHEAD", slot)
    yield slot
    slot.drop()
    wait(slot)


def wait(slot):
    worker = slot._worker
    if worker is not None:
        worker.join(10)
        assert not worker.is_alive()


@pytest.fixture
def files(tmp_path):
    data = Section.getEmptyDict()
    data["contours"] = {"cell": [[
        [1, 2, 2], [1, 1, 2], [255, 0, 0],
        True, False, False, ["none", "none"], [],
    ]]}
    paths = []
    for number in range(3):
        path = tmp_path / f"test.{number}"
        path.write_text(json.dumps(data))
        paths.append(str(path))
    return paths


def test_worker_prepares_once_and_take_transfers_ownership(slot, files, monkeypatch):
    owner = object()
    calls = []
    original = ahead.readSection

    def read(*args):
        calls.append(threading.get_ident())
        return original(*args)

    monkeypatch.setattr(ahead, "readSection", read)
    slot.start(owner, 1, files[1])
    wait(slot)
    prepared = slot.take(owner, 1, files[1])
    assert list(prepared.contours["cell"][0].points) == [(1, 1), (2, 1), (2, 2)]
    assert len(calls) == 1
    assert calls[0] != threading.get_ident()
    assert slot.take(owner, 1, files[1]) is None


def test_replaced_file_with_same_size_and_mtime_is_rejected(slot, files, tmp_path):
    owner = object()
    slot.start(owner, 1, files[1])
    wait(slot)
    old = os.stat(files[1])
    replacement = tmp_path / "replacement"
    replacement.write_text(Path(files[1]).read_text().replace("255", "254"))
    os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
    os.replace(replacement, files[1])
    assert slot.take(owner, 1, files[1]) is None


def test_another_series_cannot_take_the_payload(slot, files):
    owner = object()
    slot.start(owner, 1, files[1])
    wait(slot)
    assert slot.take(object(), 1, files[1]) is None


def test_failed_read_is_retried_only_by_foreground(slot, files):
    owner = object()
    os.unlink(files[1])
    slot.start(owner, 1, files[1])
    wait(slot)
    assert slot.take(owner, 1, files[1]) is None
    with pytest.raises(FileNotFoundError):
        ahead.readSection(files[1], 1)


def test_late_read_never_blocks_take_or_retains_a_result(slot, files, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = ahead.readSection

    def held(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(ahead, "readSection", held)
    owner = object()
    slot.start(owner, 1, files[1])
    assert entered.wait(10)
    try:
        assert slot.take(owner, 1, files[1]) is None
        assert slot._request is None
    finally:
        release.set()
        wait(slot)
    assert slot._result is None


def test_repeated_requests_keep_one_worker_and_release_old_payload(slot, files, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = ahead.readSection
    calls, refs = [], []

    def held(path, number, canceled):
        calls.append(number)
        if number == 0:
            # Finish a result even though it was canceled, to test its disposal.
            result = original(path, number)
            refs.append(weakref.ref(result))
            entered.set()
            assert release.wait(10)
            return result
        assert refs[0]() is None
        return original(path, number, canceled)

    monkeypatch.setattr(ahead, "readSection", held)
    owner = object()
    slot.start(owner, 0, files[0])
    assert entered.wait(10)
    worker = slot._worker
    try:
        slot.start(owner, 1, files[1])
        slot.start(owner, 2, files[2])
        assert slot._worker is worker
    finally:
        release.set()
        wait(slot)
    assert calls == [0, 2]
    assert slot.take(owner, 2, files[2]) is not None


@pytest.mark.gui
def test_adjacent_steps_prepare_one_neighbor_and_use_it(paging_window, slot, qtbot, monkeypatch):
    field = paging_window.field
    paging_window.changeSection(1)
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    assert slot._request[1] == 2
    original = ahead.readSection
    foreground = []

    def read(path, number, canceled=None):
        if threading.current_thread() is threading.main_thread():
            foreground.append(number)
        return original(path, number, canceled)

    monkeypatch.setattr(ahead, "readSection", read)
    paging_window.changeSection(2)
    assert foreground == []
    assert field.section.n == 2
    assert field.series_states[2].initialized
    assert field.b_section.n == 1


@pytest.mark.gui
def test_jump_and_reversal_drop_old_neighbor(paging_window, slot, qtbot):
    field = paging_window.field
    paging_window.changeSection(1)
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    paging_window.changeSection(10)
    assert slot._request is None
    assert not field.section_read_timer.isActive()
    paging_window.changeSection(9)
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    assert slot._request[1] == 8
    paging_window.changeSection(10)  # B swap, now paging forward
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    assert slot._request[1] == 11


@pytest.mark.gui
def test_neighbor_uses_section_order_with_gaps(paging_window, slot, qtbot):
    series = paging_window.series
    del series.sections[2]
    paging_window.changeSection(1)
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    assert slot._request[1] == 3
    paging_window.changeSection(3)
    assert paging_window.field.section.n == 3


@pytest.mark.gui
def test_reload_and_close_discard_prepared_data(paging_window, slot, qtbot):
    paging_window.changeSection(1)
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    paging_window.field.reload()
    assert slot._request is None
    paging_window.changeSection(2)
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    paging_window.series.modified = False
    assert paging_window.close()
    assert slot._request is None


@pytest.mark.gui
def test_save_after_preparation_wins_and_ids_undo_redo_survive(paging_window, slot, qtbot):
    series = paging_window.series
    section = series.loadSection(2)
    paging_window.changeSection(1)
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    trace = Trace("read-ahead-edit", (255, 0, 0), True)
    trace.points = [(1, 1), (2, 1), (2, 2)]
    section.addTrace(trace, log_event=False)
    section.tform = Transform([1, 0, 7, 0, 1, 9])
    section.save()
    saved_ids = section._persistedTraceIDs()
    expected_id = saved_ids[trace]
    paging_window.changeSection(2)
    field = paging_window.field
    loaded = field.section.contours["read-ahead-edit"][0]
    assert field.section._persistedTraceIDs()[loaded] == expected_id
    assert field.section.tform.getList() == [1, 0, 7, 0, 1, 9]
    field.section.removeTrace(loaded, log_event=False)
    field.saveState()
    field.undoState()
    restored = field.section.contours["read-ahead-edit"][0]
    assert list(restored.points) == [(1, 1), (2, 1), (2, 2)]
    field.undoState(redo=True)
    assert not field.section.contours.get("read-ahead-edit")
    paging_window.saveAllData()
    paging_window.changeSection(3)
    paging_window.changeSection(4)
    paging_window.changeSection(2)
    assert not field.section.contours.get("read-ahead-edit")


@pytest.fixture
def paging_window(main_window, slot):
    main_window.changeSection(0)
    return main_window

@pytest.mark.gui
def test_preparation_does_not_issue_ids(
        paging_window, slot, qtbot, monkeypatch):
    calls = []
    original = Section.issueLoadedTraceIDs

    def issue(*args, **kwargs):
        calls.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(Section, "issueLoadedTraceIDs", issue)
    paging_window.changeSection(1)
    calls.clear()
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    assert calls == []
    paging_window.changeSection(2)
    assert calls == [threading.get_ident()]


@pytest.mark.gui
def test_pending_timer_cannot_read_closed_series(paging_window, slot, qtbot):
    paging_window.changeSection(1)
    paging_window.series.modified = False
    paging_window.series.unsaved_series_data = False
    assert paging_window.close()
    qtbot.wait(150)
    assert slot._request is None


@pytest.mark.gui
def test_series_transition_discards_payload(paging_window, slot, qtbot):
    paging_window.changeSection(1)
    qtbot.waitUntil(lambda: slot._request is not None)
    wait(slot)
    before = paging_window.series
    paging_window.openSeries(jser_fp=str(before.jser_fp), query_prev=False)
    assert paging_window.series is not before
    assert slot._request is None


@pytest.mark.gui
def test_lazy_neighbor_is_left_to_normal_loader(paging_window, slot, qtbot):
    paging_window.series._lazy = {2}
    try:
        paging_window.changeSection(1)
        qtbot.wait(150)
        assert slot._request is None
    finally:
        paging_window.series._lazy = set()

def test_discarded_short_y_row_does_not_shift_the_next_traces_id(real_series, slot):
    number = 0
    data = Section.getEmptyDict()
    row = [[1, 2, 2], [1, 1, 2], [255, 0, 0],
           True, False, False, ["none", "none"], []]
    short = list(row)
    short[1] = [1]
    data["contours"] = {"cell": [short, row]}
    path = real_series.presentSection(number)
    raw = json.dumps(data).encode()
    Path(path).write_bytes(raw)
    # updateJSON screens x; the trace reader also screens the zipped points.
    Section.updateJSON(data, number)
    _, _, expected = Section.issueLoadedTraceIDs(
        number, real_series, raw, data["contours"], {},
    )
    slot.start(real_series, number, path)
    wait(slot)
    section = real_series.loadSection(number)
    assert len(section.contours["cell"]) == 1
    trace = section.contours["cell"][0]
    assert section._persistedTraceIDs()[trace] == expected[("cell", 1)]

def test_alignment_and_group_visibility_are_read_when_the_section_is_taken(real_series, slot):
    section = real_series.loadSection(0)
    trace = Trace("cell", (255, 0, 0), True)
    trace.points = [(1, 1), (2, 1), (2, 2)]
    section.addTrace(trace, log_event=False)
    section.tforms["other"] = Transform([1, 0, 11, 0, 1, 13])
    section.save()
    slot.start(real_series, 0, section.filepath)
    wait(slot)
    real_series.object_groups.add(group="hidden-group", obj="cell")
    real_series.groups_visibility["hidden-group"] = False
    real_series.alignment = "other"
    loaded = real_series.loadSection(0)
    assert loaded.tform.getList() == [1, 0, 11, 0, 1, 13]
    assert loaded.contours["cell"][0] in loaded.traces_group_hide


def test_replaced_ready_payload_is_not_held_by_a_returning_worker(slot, files, monkeypatch):
    original = ahead.readSection
    refs, first_worker = [], []
    finished, release = threading.Event(), threading.Event()
    lock = threading.Lock()

    def read(path, number, canceled):
        prepared = original(path, number, canceled)
        if number == 0:
            refs.append(weakref.ref(prepared))
            first_worker.append(threading.current_thread())
        return prepared

    class PauseOnReturn:
        def __enter__(self):
            lock.acquire()

        def __exit__(self, *args):
            lock.release()
            if (first_worker and threading.current_thread() is first_worker[0]
                    and slot._worker is None):
                finished.set()
                assert release.wait(10)

    monkeypatch.setattr(ahead, "readSection", read)
    slot._lock = PauseOnReturn()
    owner = object()
    slot.start(owner, 0, files[0])
    assert finished.wait(10)
    try:
        slot.start(owner, 1, files[1])
        wait(slot)
        assert slot.take(owner, 1, files[1]) is not None
        assert refs[0]() is None
    finally:
        release.set()
        first_worker[0].join(10)


@pytest.fixture
def active_read(slot, monkeypatch):
    @contextmanager
    def hold(series, number=2, *, dropped=False):
        path = series.presentSection(number)
        entered, release = threading.Event(), threading.Event()
        streams, attempts = [], []
        original_open = builtins.open
        original_rename, original_remove = os.rename, os.remove

        class HeldRead:
            def __enter__(self):
                self.stream = original_open(path, "rb")
                streams.append(self.stream)
                return self

            def read(self):
                entered.set()
                assert release.wait(10)
                return self.stream.read()

            def __exit__(self, *args):
                self.stream.close()

        def open_section(filepath, mode):
            if threading.current_thread() is threading.main_thread():
                return original_open(filepath, mode)
            assert filepath == path and mode == "rb"
            return HeldRead()

        def guard(operation, src, *args, **kwargs):
            if any(not stream.closed for stream in streams):
                attempts.append(os.fspath(src))
                # Windows exercises its actual open-file rules. Other hosts
                # model the refusal at the same filesystem boundary.
                if os.name != "nt":
                    raise PermissionError(13, "Section read is still open", src)
            return operation(src, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(ahead, "open", open_section, raising=False)
            patch.setattr(os, "rename",
                          lambda src, *a, **kw: guard(original_rename, src, *a, **kw))
            patch.setattr(os, "remove",
                          lambda src, *a, **kw: guard(original_remove, src, *a, **kw))
            slot.start(series, number, path)
            assert entered.wait(10)
            worker = slot._worker
            canceled = slot._request[3]

            def finish_read():
                canceled.wait(5)
                # Keep the handle open beyond cancellation, as a slow read
                # does. File mutations must wait for the context to close.
                release.wait(0.1)
                release.set()

            finisher = threading.Thread(target=finish_read)
            finisher.start()
            try:
                if dropped:
                    slot.drop()
                    assert not streams[0].closed
                yield
                assert streams[0].closed
                assert attempts == []
                assert slot._request is None
                assert slot._result is None
                assert not worker.is_alive()
            finally:
                release.set()
                canceled.set()
                finisher.join(10)
                worker.join(10)
                assert not finisher.is_alive()
                assert not worker.is_alive()

    return hold


@pytest.mark.parametrize("dropped", [False, True])
@pytest.mark.parametrize("operation", ["close", "reorder", "save_as", "delete"])
def test_file_mutations_release_active_read(real_series, active_read, tmp_path,
                                           operation, dropped):
    with active_read(real_series, dropped=dropped):
        if operation == "close":
            real_series.close()
            assert real_series.closed
            assert not Path(real_series.hidden_dir).exists()
        elif operation == "reorder":
            numbers = sorted(real_series.sections)
            real_series.reorderSections({n: n + 1000 for n in numbers}, log_event=False)
            assert sorted(real_series.sections) == [n + 1000 for n in numbers]
        elif operation == "save_as":
            destination = tmp_path / "renamed.jser"
            real_series.saveAs(str(destination))
            assert destination.exists()
            assert real_series.jser_fp == str(destination)
        else:
            real_series.deleteSections([2], log_event=False)
            assert 2 not in real_series.sections

    if not real_series.closed:
        for filename in real_series.sections.values():
            assert (Path(real_series.hidden_dir) / filename).is_file()
        assert not list(Path(real_series.hidden_dir).glob("*.temp"))


@pytest.mark.gui
def test_series_transition_releases_active_read(paging_window, active_read):
    before = paging_window.series
    with active_read(before):
        paging_window.openSeries(jser_fp=str(before.jser_fp), query_prev=False)
    assert paging_window.series is not before
    assert before.closed
    assert not paging_window.series.closed
    assert paging_window.field.section.n in paging_window.series.sections


def test_stop_after_dropped_read_allows_another_neighbor(slot, files, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = ahead.readSection

    def held(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(ahead, "readSection", held)
    owner = object()
    slot.start(owner, 0, files[0])
    assert entered.wait(10)
    worker = slot._worker
    try:
        assert slot.take(owner, 0, files[0]) is None
        slot.drop()
        assert worker.is_alive()
    finally:
        release.set()
        slot.stop()
    assert not worker.is_alive()
    slot.start(owner, 1, files[1])
    wait(slot)
    assert slot.take(owner, 1, files[1]) is not None
