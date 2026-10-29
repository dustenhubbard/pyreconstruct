"""A large series' open reads its section files in worker processes
(section_rows.ParallelLoader). It must leave the same series data, trace-id
issuer, object ids and working folder as the open in one process, a later
section load must get the same ids, and a worker that fails must not fail
the open.

The size bar is set to 0 here, so every series opens with workers.
"""
import hashlib
import os

import pytest

from PyReconstruct.modules.datatypes import Series, section_rows
from PyReconstruct.modules.datatypes.trace_id import (
    TraceIDIssuer, canonicalJSON, deriveTraceID, firstDerivedID,
)

from test_open_reads_rows import (  # noqa: F401  (source is a fixture)
    _copy, _later_loads, _odd_series, _open, _state, source,
)


def _serial(m):
    m.setattr(section_rows, "PARALLEL_MIN_BYTES", float("inf"))


def _parallel(m, used):
    """Open with 2 workers, recording each section a worker read."""
    m.setattr(section_rows, "PARALLEL_MIN_BYTES", 0)
    m.setattr(section_rows, "PARALLEL_MAX_WORKERS", 2)
    m.setattr(os, "cpu_count", lambda: 8)
    real = section_rows._rowsFromWorker

    def recording(n, series, result):
        used.append(n)
        return real(n, series, result)

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
