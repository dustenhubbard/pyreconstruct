"""A large series' open reads its section files in worker processes
(section_rows.ParallelLoader). It must leave the same series data, trace-id
issuer, object ids and working folder as the open in one process, a later
section load must get the same ids, and a worker that fails must not fail
the open.

The size bar is set to 0 here, so every series opens with workers.
"""
import contextlib
import gc
import hashlib
import json
import multiprocessing
import os
import struct
import sys
import threading
import time
import types
import weakref
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import process as futures_process
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series, section_rows
from PyReconstruct.modules.datatypes.trace_id import (
    TraceIDIssuer, canonicalJSON, deriveTraceID, firstDerivedID,
)

from test_open_reads_rows import (  # noqa: F401  (source is a fixture)
    FIXTURES, _copy, _later_loads, _odd_series, _open, _state, source,
)


def _serial(m):
    m.setattr(section_rows, "PARALLEL_MIN_BYTES", float("inf"))


def _parallel(m, used):
    """Open with 2 workers, recording each section built from a worker's
    read (a result _rowsFromWorker rejects is read again here)."""
    m.setattr(section_rows, "PARALLEL_MIN_BYTES", 0)
    m.setattr(section_rows, "MAIN_GUARDED", True)
    m.setattr(section_rows, "PARALLEL_MAX_WORKERS", 2)
    m.setattr(os, "cpu_count", lambda: 8)
    real = section_rows._rowsFromWorker

    def recording(n, series, result):
        rows = real(n, series, result)
        if rows is not None:
            used.append(n)
        return rows

    m.setattr(section_rows, "_rowsFromWorker", recording)


def _files(series):
    folder = os.path.dirname(series.filepath)
    return {
        name: hashlib.sha256(open(os.path.join(folder, name), "rb").read()).hexdigest()
        for name in sorted(os.listdir(folder))
    }


def _first_opens(path, tmp_path, monkeypatch, used):
    opened = {}
    for arm in ("serial", "parallel"):
        folder = tmp_path / arm
        folder.mkdir()
        (folder / "series.jser").write_bytes(open(path, "rb").read())
        with monkeypatch.context() as m:
            _serial(m) if arm == "serial" else _parallel(m, used)
            opened[arm] = _open(folder / "series.jser")
    return opened["serial"], opened["parallel"]


def test_first_open_with_workers_matches_one_process(source, tmp_path, monkeypatch):  # noqa: F811
    used = []
    serial, parallel = _first_opens(source, tmp_path, monkeypatch, used)
    try:
        assert used, "no section was read by a worker"
        assert serial.data.objects, "the fixture has no trace data to compare"
        assert _state(parallel) == _state(serial)
        assert _files(parallel) == _files(serial)
        assert _later_loads(parallel) == _later_loads(serial)
    finally:
        serial.close()
        parallel.close()


def test_resume_with_workers_matches_one_process(source, tmp_path, monkeypatch):  # noqa: F811
    first = _open(_copy(source, tmp_path))
    fp, sections = first.filepath, dict(first.sections)
    used = []
    try:
        with monkeypatch.context() as m:
            _serial(m)
            serial = Series(fp, sections)
        with monkeypatch.context() as m:
            _parallel(m, used)
            parallel = Series(fp, sections)
        assert used == sorted(used) and used
        assert _state(parallel) == _state(serial)
        assert _later_loads(parallel) == _later_loads(serial)
    finally:
        first.close()


def test_own_alignment_with_workers(tmp_path, monkeypatch):
    """Objects measured with an alignment other than the one the workers
    measured with, and an alignment a section lacks, match one process."""
    first = _open(_odd_series(tmp_path / "odd.jser"))
    try:
        states = []
        for arm in ("serial", "parallel"):
            first.setAttr("plain", "alignment", "other")
            with monkeypatch.context() as m:
                _serial(m) if arm == "serial" else _parallel(m, [])
                first.data.refresh(from_rows=True)
            states.append(_state(first))
        assert states[0] == states[1]
    finally:
        first.close()


def _raise_on_one(fp, n, alignment):
    if n == 1:
        raise RuntimeError("worker failed")
    return REAL_READ(fp, n, alignment)


def _exit_on_one(fp, n, alignment):
    if n == 1:
        os._exit(1)
    return REAL_READ(fp, n, alignment)


REAL_READ = section_rows.readFileRows


@pytest.mark.parametrize("failure", [_raise_on_one, _exit_on_one])
def test_a_failed_worker_does_not_fail_the_open(failure, tmp_path, monkeypatch, capsys):
    """A worker that raises, or that dies and breaks the pool, leaves its
    sections to this process, with the same result."""
    first = _open(_copy(_odd_series(tmp_path / "odd.jser"), tmp_path))
    fp, sections = first.filepath, dict(first.sections)
    used = []
    try:
        with monkeypatch.context() as m:
            _serial(m)
            serial = Series(fp, sections)
        with monkeypatch.context() as m:
            _parallel(m, used)
            m.setattr(section_rows, "readFileRows", failure)
            parallel = Series(fp, sections)
        assert 1 not in used
        assert "its worker failed" in capsys.readouterr().err
        assert _state(parallel) == _state(serial)
        assert _later_loads(parallel) == _later_loads(serial)
    finally:
        first.close()


def test_a_small_series_opens_in_one_process(series_jser, monkeypatch):
    used = []
    with monkeypatch.context() as m:
        _parallel(m, used)
        m.setattr(section_rows, "PARALLEL_MIN_BYTES", 64 * 1024 * 1024)
        series = _open(series_jser)
    series.close()
    assert used == []


def _main(folder, name, spec=None, text="x = 1\n"):
    """A main module from a real file in `folder`, so that a worker can run
    it again: without the check, its workers would read sections."""
    main = types.ModuleType("__main__")
    main.__spec__ = spec
    if name is not None:
        path = folder / name
        path.write_text(text)
        main.__file__ = str(path)
        exec(text, main.__dict__)
    return main


MAINS = {
    "script": (lambda f: _main(f, "script.py"), False),
    "module": (lambda f: _main(f, "mod.py", types.SimpleNamespace(name="mod")), False),
    "package": (lambda f: _main(f, "__main__.py", types.SimpleNamespace(name="pkg.__main__")), True),
    "interactive": (lambda f: _main(f, None), True),
    "run.py": (lambda f: _main(f, "run.py", text="def runPyReconstruct():\n    pass\n"), True),
}


@pytest.mark.parametrize("kind", MAINS)
def test_workers_only_where_the_main_script_does_not_run_again(kind, series_jser, tmp_path, monkeypatch):
    """A worker imports the main script again: an unguarded script that
    opens a series would open it in every worker, so it opens in one process."""
    make, safe = MAINS[kind]
    used = []
    with monkeypatch.context() as m:
        m.syspath_prepend(str(tmp_path))
        _parallel(m, used)
        m.setattr(section_rows, "MAIN_GUARDED", False)
        m.setitem(sys.modules, "__main__", make(tmp_path))
        assert section_rows.mainSafeForWorkers() is safe
        series = _open(series_jser)
    series.close()
    assert bool(used) is safe


ROWS = {
    "a": [[[0, 1, 1], [0, 0, 1], [1, 2, 3], True, False, False, ["none", "none"], []]] * 3,
    "b": [[[5, 6, 6], [5, 5, 6], [1, 2, 3], True, False, False, ["none", "none"], ["t"]]],
}


def _walk(n, contours):
    names = sorted(contours, key=str)
    jsons = [canonicalJSON(row) for c in names for row in contours[c]]
    ids = [firstDerivedID(n, c, canonicalJSON(row)) for c in names for row in contours[c]]
    return jsons, ids


def _issuer_state(issuer):
    return {k: v for k, v in vars(issuer).items() if k != "_bits_source"}


@pytest.mark.parametrize("skip", [(), {("a", 1): "x"}])
def test_derivation_from_worker_inputs_matches(skip):
    """The ids a worker works out give the same ids and issuer state, with
    duplicate rows, a skipped row, a salt-0 id already taken and a second
    load answered from the record."""
    jsons, firsts = _walk(4, ROWS)
    assert firsts[0] == deriveTraceID(4, "a", ROWS["a"][0])
    taken = [firsts[3]]  # "b"'s salt-0 id is held by another trace
    issuers = [TraceIDIssuer(taken), TraceIDIssuer(taken)]
    outs = [
        [issuers[0].deriveForSection(4, ROWS, skip=skip, digest=b"d") for _ in range(2)],
        [issuers[1].deriveForSection(4, ROWS, skip=skip, digest=b"d",
                                     row_jsons=jsons, first_ids=firsts) for _ in range(2)],
    ]
    assert outs[0] == outs[1]
    assert outs[1][0][("b", 0)] != firsts[3]
    assert _issuer_state(issuers[0]) == _issuer_state(issuers[1])


def test_adoption_from_worker_inputs_matches():
    jsons, _ = _walk(4, ROWS)
    stored = {("a", 2): firstDerivedID(4, "a", jsons[0]), ("b", 0): "bad id"}
    issuers = [TraceIDIssuer(), TraceIDIssuer()]
    assert (issuers[0].adoptForSection(4, ROWS, stored)
            == issuers[1].adoptForSection(4, ROWS, stored, row_jsons=jsons))
    assert _issuer_state(issuers[0]) == _issuer_state(issuers[1])


def test_an_alignment_the_worker_did_not_measure_reads_in_this_process(tmp_path):
    """A worker result without an object's alignment is not used, and the
    issuer is not touched, so `loadForOpen` reads the section as before."""
    series = _open(_odd_series(tmp_path / "odd.jser"))
    try:
        before = {k: repr(v) for k, v in vars(series.trace_id_issuer).items()}
        result = section_rows.readFileRows(series.presentSection(1), 1, {"default"})
        series.setAttr("plain", "alignment", "other")
        assert section_rows._rowsFromWorker(1, series, result) is None
        assert {k: repr(v) for k, v in vars(series.trace_id_issuer).items()} == before
        series.setAttr("plain", "alignment", None)
        assert section_rows._rowsFromWorker(1, series, result) is not None
    finally:
        series.close()


def test_a_series_without_an_alignment_builds_from_the_workers(tmp_path, monkeypatch):
    """The workers of a first open start before updateJSON gives a series
    without an alignment "default", and still measure with it, so the open
    builds every section from their reads."""
    path = tmp_path / "series.jser"
    path.write_bytes(FIXTURES["parity"].read_bytes())
    assert "alignment" not in json.loads(path.read_bytes())["series"]
    used = []
    with monkeypatch.context() as m:
        _parallel(m, used)
        series = _open(path)
    try:
        assert series.alignment == "default"
        assert used == sorted(series.sections)
    finally:
        series.close()


def test_a_cancel_stops_the_workers_and_removes_the_folder(series_jser, monkeypatch):
    """A first open cancelled during the build stops its workers, and the
    working folder it made is removed."""
    used = []

    class CancelInBuild(NullProgressReporter):
        def was_canceled(self):
            return bool(used)

    before = sorted(os.listdir(series_jser.parent))
    with monkeypatch.context() as m:
        _parallel(m, used)
        assert Series.openJser(str(series_jser), progress=CancelInBuild) is None
    assert used
    assert multiprocessing.active_children() == []
    assert sorted(os.listdir(series_jser.parent)) == before


def _stall(fp, n, alignment):
    """Stall on section STALL_SECTION, holding its file open if given its
    path (a first open's workers get its bytes), until the release marker
    exists (at most 30 s), after writing the started marker."""
    if n != int(os.environ["STALL_SECTION"]):
        return REAL_READ(fp, n, alignment)
    marker = Path(os.environ["STALL_MARKER"])
    with open(fp, "rb") if isinstance(fp, str) else contextlib.nullcontext():
        marker.write_text(str(os.getpid()))
        limit = time.monotonic() + 30
        while not Path(f"{marker}.release").exists() and time.monotonic() < limit:
            time.sleep(0.01)
    return REAL_READ(fp, n, alignment)


def _wait_for(path, limit=20):
    end = time.monotonic() + limit
    while not path.exists() and time.monotonic() < end:
        time.sleep(0.01)
    return path.exists()


@pytest.mark.parametrize("stalled", [0, 1])
def test_a_cancel_does_not_wait_for_a_stalled_worker(stalled, series_jser, tmp_path, monkeypatch):
    """A cancel accepted while a worker is stuck reading a section, the one
    the open waits for (0) or a later one (1), returns at once: the worker
    is stopped before the working folder is removed."""
    (tmp_path / "markers").mkdir()
    marker = tmp_path / "markers" / "started"
    used = []

    class CancelWhenStalled(NullProgressReporter):
        def was_canceled(self):
            if stalled == 0:
                return marker.exists()
            return bool(used) and _wait_for(marker)

    monkeypatch.setenv("STALL_SECTION", str(stalled))
    monkeypatch.setenv("STALL_MARKER", str(marker))
    before = sorted(os.listdir(series_jser.parent))
    try:
        with monkeypatch.context() as m:
            _parallel(m, used)
            m.setattr(section_rows, "readFileRows", _stall)
            start = time.monotonic()
            result = Series.openJser(str(series_jser), progress=CancelWhenStalled)
            elapsed = time.monotonic() - start
            alive = multiprocessing.active_children()
        assert result is None
        assert marker.exists()
        assert elapsed < 15
        assert alive == []
        assert sorted(os.listdir(series_jser.parent)) == before
    finally:
        Path(f"{marker}.release").touch()
        for child in multiprocessing.active_children():
            child.join(30)


def _send_part(fp, n, alignment):
    """Read section 0, then send only the start of its result: write the
    started marker and stall (at most 30 s) before the rest."""
    from multiprocessing.connection import Connection

    result = REAL_READ(fp, n, alignment)
    if n == 0:
        def send_part(self, buf):
            self._send(struct.pack("!i", len(buf)))
            self._send(buf[:len(buf) // 2])
            Path(os.environ["STALL_MARKER"]).write_text(str(os.getpid()))
            time.sleep(30)
            self._send(buf[len(buf) // 2:])

        Connection._send_bytes = send_part
    return result


class _KeepResults(ProcessPoolExecutor):
    """Keeps its result queue, so a test can free a stuck manager thread."""

    made = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.results = self._result_queue
        self.made.append(self)


@pytest.mark.skipif(sys.platform == "win32", reason="a Windows pipe sends a result whole")
def test_a_cancel_ends_a_result_a_worker_sent_partway(series_jser, tmp_path, monkeypatch):
    """A worker stopped partway through sending its result leaves no
    executor thread waiting for the rest, so Python can still exit."""
    marker = tmp_path / "started"

    class CancelWhenSending(NullProgressReporter):
        def was_canceled(self):
            return marker.exists()

    monkeypatch.setenv("STALL_MARKER", str(marker))
    _KeepResults.made.clear()
    try:
        with monkeypatch.context() as m:
            _parallel(m, [])
            m.setattr(section_rows, "readFileRows", _send_part)
            m.setattr(section_rows, "ProcessPoolExecutor", _KeepResults)
            result = Series.openJser(str(series_jser), progress=CancelWhenSending)
            alive = multiprocessing.active_children()
            managers = [
                t for t in threading.enumerate()
                if isinstance(t, futures_process._ExecutorManagerThread)
            ]
        assert result is None
        assert marker.exists()
        assert alive == []
        assert managers == []
    finally:
        for executor in _KeepResults.made:
            executor.results._writer.close()
        for child in multiprocessing.active_children():
            child.kill()
            child.join(30)


@pytest.mark.gui
def test_cancel_clicked_while_a_worker_stalls_lands(qtbot, series_jser, tmp_path, monkeypatch):
    """A click on the progress window's Cancel while the open waits for a
    stuck worker is seen at the next poll: the wait handles window events."""
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from PyReconstruct.modules.backend.progress import QtProgressReporter

    (tmp_path / "markers").mkdir()
    marker = tmp_path / "markers" / "started"
    seen = {}
    reporters = []

    class Recording(QtProgressReporter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            reporters.append(self)

        def canceled_while_waiting(self):
            seen.setdefault("waiting", time.monotonic())
            canceled = super().canceled_while_waiting()
            if canceled:
                seen.setdefault("canceled", time.monotonic())
            return canceled

    class Clicker(QObject):
        request = Signal()

        def __init__(self):
            super().__init__()
            self.request.connect(self.click, Qt.QueuedConnection)

        def click(self):
            button = reporters[-1]._progbar.findChild(QPushButton)
            seen["clicked"] = time.monotonic()
            QTest.mouseClick(button, Qt.LeftButton)

    clicker = Clicker()

    def control():
        ## a first open's worker stalls during the unpack: click once the
        ## open waits for it
        end = time.monotonic() + 20
        while "waiting" not in seen and time.monotonic() < end:
            time.sleep(0.01)
        if _wait_for(marker) and "waiting" in seen:
            clicker.request.emit()
            end = time.monotonic() + 5
            while "returned" not in seen and time.monotonic() < end:
                time.sleep(0.01)
        seen["released"] = time.monotonic()
        Path(f"{marker}.release").touch()

    monkeypatch.setenv("STALL_SECTION", "0")
    monkeypatch.setenv("STALL_MARKER", str(marker))
    thread = threading.Thread(target=control)
    try:
        with monkeypatch.context() as m:
            _parallel(m, [])
            m.setattr(section_rows, "readFileRows", _stall)
            thread.start()
            result = Series.openJser(str(series_jser), progress=Recording)
            seen["returned"] = time.monotonic()
        assert result is None
        assert seen.get("released", float("inf")) >= seen["returned"]
        assert seen["canceled"] - seen["clicked"] < 1
        assert multiprocessing.active_children() == []
    finally:
        Path(f"{marker}.release").touch()
        thread.join(10)
        for child in multiprocessing.active_children():
            child.join(30)


class _FailSecondSubmit(ProcessPoolExecutor):
    """Starts one worker, which holds section 0 open, then fails."""

    def submit(self, fn, *args, **kwargs):
        if getattr(self, "submitted", False):
            raise OSError("second submit failed")
        self.submitted = True
        future = super().submit(_stall, *args, **kwargs)
        assert _wait_for(Path(os.environ["STALL_MARKER"]))
        return future


def test_a_failed_start_stops_its_workers_first(series_jser, tmp_path, monkeypatch, capsys):
    """Workers that fail to start partway are all stopped before the open
    goes on in this process."""
    marker = tmp_path / "started"
    monkeypatch.setenv("STALL_SECTION", "0")
    monkeypatch.setenv("STALL_MARKER", str(marker))
    series = None
    try:
        with monkeypatch.context() as m:
            _parallel(m, [])
            m.setattr(section_rows, "ProcessPoolExecutor", _FailSecondSubmit)
            series = _open(series_jser)
            alive = multiprocessing.active_children()
        assert "the workers failed" in capsys.readouterr().err
        assert alive == []
    finally:
        if series is not None:
            series.close()
        Path(f"{marker}.release").touch()
        for child in multiprocessing.active_children():
            child.join(30)


def _mark_read(fp, n, alignment):
    """Read the section, then leave a file named n in READ_DIR."""
    result = REAL_READ(fp, n, alignment)
    (Path(os.environ["READ_DIR"]) / str(n)).touch()
    return result


def test_a_first_open_feeds_the_workers_during_the_unpack(series_jser, tmp_path, monkeypatch):
    """The workers read sections before the unpack has written the .ser,
    and the open matches one process."""
    read_dir = tmp_path / "read"
    read_dir.mkdir()
    monkeypatch.setenv("READ_DIR", str(read_dir))
    real_update = Series.updateJSON
    seen = []

    def update(series_data):
        end = time.monotonic() + 20
        while not os.listdir(read_dir) and time.monotonic() < end:
            time.sleep(0.01)
        seen.append(sorted(os.listdir(read_dir)))
        return real_update(series_data)

    serial_jser = tmp_path / "serial" / "series.jser"
    serial_jser.parent.mkdir()
    serial_jser.write_bytes(series_jser.read_bytes())
    with monkeypatch.context() as m:
        _serial(m)
        serial = _open(serial_jser)
    try:
        with monkeypatch.context() as m:
            _parallel(m, [])
            m.setattr(section_rows, "readFileRows", _mark_read)
            m.setattr(Series, "updateJSON", staticmethod(update))
            parallel = _open(series_jser)
        try:
            assert seen and seen[0], "no worker read a section during the unpack"
            assert _state(parallel) == _state(serial)
            assert _files(parallel) == _files(serial)
        finally:
            parallel.close()
    finally:
        serial.close()


def _unpack_stall(monkeypatch, tmp_path):
    """Stall section 0's worker, and record each Series.updateJSON call (the
    unpack's step after the sections)."""
    marker = tmp_path / "markers" / "started"
    marker.parent.mkdir(exist_ok=True)
    monkeypatch.setenv("STALL_SECTION", "0")
    monkeypatch.setenv("STALL_MARKER", str(marker))
    updates = []
    real_update = Series.updateJSON

    def update(series_data):
        updates.append(True)
        return real_update(series_data)

    monkeypatch.setattr(section_rows, "readFileRows", _stall)
    monkeypatch.setattr(Series, "updateJSON", staticmethod(update))
    return marker, updates


def test_a_cancel_during_the_unpack_stops_the_workers(series_jser, tmp_path, monkeypatch):
    """A cancel while the unpack is still writing, with a worker stuck on a
    section, returns at once, stops the workers and removes what the open
    made."""
    (tmp_path / "markers").mkdir()
    before = sorted(os.listdir(series_jser.parent))
    try:
        with monkeypatch.context() as m:
            _parallel(m, [])
            marker, updates = _unpack_stall(m, tmp_path)

            waited = []

            class CancelOnceStalled(NullProgressReporter):
                def was_canceled(self):
                    if waited:
                        return marker.exists()
                    waited.append(True)
                    return _wait_for(marker, 10)

            start = time.monotonic()
            result = Series.openJser(str(series_jser), progress=CancelOnceStalled)
            elapsed = time.monotonic() - start
            alive = multiprocessing.active_children()
        assert result is None
        assert updates == [], "the cancel came after the unpack"
        assert elapsed < 15
        assert alive == []
        assert sorted(os.listdir(series_jser.parent)) == before
    finally:
        Path(f"{tmp_path / 'markers' / 'started'}.release").touch()
        for child in multiprocessing.active_children():
            child.join(30)


def test_a_failure_during_the_unpack_stops_the_workers_and_keeps_the_folder(series_jser, tmp_path, monkeypatch):
    """A section that fails to unpack while a worker is stuck on an earlier
    one stops the workers, and the folder at the working folder's place is
    put back untouched."""
    (tmp_path / "markers").mkdir()
    hidden = series_jser.parent / ".series"
    hidden.mkdir()
    (hidden / "keep.txt").write_text("mine")
    before = sorted(os.listdir(series_jser.parent))
    real_section_update = section_rows.Section.updateJSON
    calls = []
    try:
        with monkeypatch.context() as m:
            _parallel(m, [])
            marker, updates = _unpack_stall(m, tmp_path)

            def failing(section_data, n, **kwargs):
                calls.append(n)
                if len(calls) == 2:
                    calls.append(_wait_for(marker, 10))
                    raise RuntimeError("a corrupt section")
                return real_section_update(section_data, n, **kwargs)

            m.setattr(section_rows.Section, "updateJSON", staticmethod(failing))
            with pytest.raises(RuntimeError, match="a corrupt section"):
                Series.openJser(str(series_jser), progress=NullProgressReporter)
            alive = multiprocessing.active_children()
        assert calls[2] is True, "no worker was reading when the unpack failed"
        assert alive == []
        assert sorted(os.listdir(series_jser.parent)) == before
        assert os.listdir(hidden) == ["keep.txt"]
        assert (hidden / "keep.txt").read_text() == "mine"
    finally:
        Path(f"{tmp_path / 'markers' / 'started'}.release").touch()
        for child in multiprocessing.active_children():
            child.join(30)


def test_a_result_is_dropped_once_the_pass_takes_it(tmp_path, monkeypatch):
    """The loader holds no worker result for a section the pass has built:
    with every result kept to the end, a DW09 open held 0.6 GB more."""
    first = _open(_copy(_odd_series(tmp_path / "odd.jser"), tmp_path))
    fp, sections = first.filepath, dict(first.sections)
    loader_class = section_rows.ParallelLoader
    real_submit, real_call = loader_class.submit, loader_class.__call__
    refs, kept, used = {}, [], []

    def submit(self, n, fp):
        real_submit(self, n, fp)
        refs[n] = weakref.ref(self.futures[n])

    def call(self, series, n):
        rows = real_call(self, series, n)
        gc.collect()
        kept.extend(m for m, ref in refs.items() if m <= n and ref() is not None)
        return rows

    try:
        with monkeypatch.context() as m:
            _parallel(m, used)
            m.setattr(loader_class, "submit", submit)
            m.setattr(loader_class, "__call__", call)
            Series(fp, sections)
        assert used and len(refs) == len(sections)
        assert kept == []
    finally:
        first.close()
