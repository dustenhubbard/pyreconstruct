"""A faster section load gives exactly the section the old load gave.

Two speedups sit on the paging path (fork #1003):

* `TraceIDIssuer.deriveForSection` keeps each section file's ids by the file's
  digest, so loading the same file again skips serializing every row;
* `_asCoordinateArray` reads a list of point pairs as one flat list, which
  every save's store rebuild does for every trace.

Each test here builds the same thing both ways -- the old way being the walk
with no digest and `np.array` over the pairs -- and compares everything a
loaded section holds: every trace and attribute in contour order, its id and
store row, the section's own fields, and every store row, column, the index
order, the generation and the change tracking.
"""
import decimal
import fractions
import itertools
import shutil
from pathlib import Path

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import columnar_store
from PyReconstruct.modules.datatypes.columnar_store import SectionColumns
from PyReconstruct.modules.datatypes.trace_id import (
    TraceIDIssuer,
    sectionFileDigest,
)

from conftest import SERIES_FIXTURE

SYNTHETIC_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity_series.jser"


def _oldCoordinateArray(points):
    """`_asCoordinateArray` as it was: `np.array` over the pairs."""
    array = np.array(points, dtype=np.float64)
    if array.size == 0:
        return np.empty((0, 2), dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError(
            f"coordinates must be a sequence of (x, y) pairs, got shape "
            f"{array.shape}"
        )
    return array


def _signature(section) -> list:
    """Everything a loaded section holds, as one comparable value."""
    out = [(
        "section", section.n, section.src, repr(section.mag),
        section.align_locked, repr(section.thickness),
        repr(section.bc_profiles), repr(section.calgrid),
        section.trace_ids_trusted,
        [(a, repr(section.tforms[a].getList())) for a in section.tforms],
        [repr(f.getList()) for f in section.flags],
        len(section.temp_hide), len(section.traces_group_hide),
    )]
    for name, contour in section.contours.items():
        for trace in contour:
            out.append((
                "trace", name, trace.name, repr(trace.points),
                type(trace.color).__name__, repr(list(trace.color)),
                trace.closed, trace.negative, trace.hidden,
                type(trace.fill_mode).__name__, repr(list(trace.fill_mode)),
                repr(sorted(trace.tags)), section.traceID(trace),
                section.traceRows().get(trace),
            ))
    out.extend(_storeSignature(section._columns))
    return out


def _storeSignature(store) -> list:
    out = [(
        "store", store.generation, store.rowCount,
        store.contourNamesInInsertionOrder(), store.contourNames(),
        repr(store._fill_mode_overflow), store._live_count,
        list(store._added_rows), list(store._removed_rows),
        sorted(store._modified_contours),
    )]
    for row in range(store.rowCount):
        if not store.isLive(row):
            out.append(("row", row, False))
            continue
        array = store.getCoordinates(row)
        out.append((
            "row", row, True, store.getName(row), array.tobytes(), array.shape,
            str(array.dtype), array.flags.owndata, array.flags.c_contiguous,
            store.colorColumn[row].tobytes(),
            [store.getFlag(row, k) for k in ("closed", "negative", "hidden")],
            int(store.fillModeColumn[row]), repr(store.getFillMode(row)),
            repr(sorted(store.getTags(row))), store.getID(row),
        ))
    return out


@pytest.fixture
def old_load(monkeypatch):
    """A switch that puts the old load back: the walk, and np.array."""
    new_derive = TraceIDIssuer.deriveForSection

    def walk(self, section_number, contours, skip=(), digest=None):
        return new_derive(self, section_number, contours, skip=skip)

    def use_old():
        monkeypatch.setattr(TraceIDIssuer, "deriveForSection", walk)
        monkeypatch.setattr(columnar_store, "_asCoordinateArray", _oldCoordinateArray)
    return use_old


def _open(path, tmp_path, name):
    from PyReconstruct.modules.datatypes import Series

    if not path.exists():  # pragma: no cover - repo layout guard
        pytest.skip(f"series fixture missing: {path}")
    copy = tmp_path / name
    shutil.copy(path, copy)
    return Series.openJser(str(copy))


@pytest.mark.parametrize("fixture", [SERIES_FIXTURE, SYNTHETIC_FIXTURE],
                         ids=["real", "synthetic"])
def test_every_section_loads_the_same_both_ways(fixture, tmp_path, old_load):
    """Every section of both fixtures: new load, then old load, equal."""
    series = _open(fixture, tmp_path, "series.jser")
    try:
        new = {n: _signature(series.loadSection(n)) for n in sorted(series.sections)}
        assert sum(len(s) for s in new.values()) > len(new) * 2, (
            "the fixture loaded no traces, so this proves nothing"
        )
        ## The open loaded every section once, so every load above took the
        ## ids by digest. Prove it did, or the comparison is the walk twice.
        issuer = series.trace_id_issuer
        assert set(issuer._derived_files) >= set(series.sections)
        old_load()
        for n in sorted(series.sections):
            assert _signature(series.loadSection(n)) == new[n], f"section {n}"
    finally:
        series.close()


def test_a_section_saved_and_reloaded_is_the_same_both_ways(tmp_path, old_load):
    """An edit, a save (the store rebuilt from the traces' points), a reload."""
    series = _open(SYNTHETIC_FIXTURE, tmp_path, "series.jser")
    try:
        n = max(series.sections, key=lambda s: len(series.loadSection(s).tracesAsList()))

        def editSaveReload():
            ## A new row gets a fresh id; draw the same ones in both runs.
            series.trace_id_issuer._bits_source = itertools.count(1).__next__
            section = series.loadSection(n)
            traces = section.tracesAsList()
            section.editTraceShape(traces[:1], [(0.0, 0.0), (3.0, 0.0), (3, 4)])
            section.hideTraces(traces[1:3])
            section.save(update_series_data=False)
            saved = _signature(section)
            return saved, _signature(series.loadSection(n))

        new_saved, new_reloaded = editSaveReload()
    finally:
        series.close()

    series = _open(SYNTHETIC_FIXTURE, tmp_path, "series2.jser")
    try:
        old_load()
        old_saved, old_reloaded = editSaveReload()
    finally:
        series.close()
    assert new_saved == old_saved
    assert new_reloaded == old_reloaded


def test_the_save_rebuild_gives_the_same_store_both_ways(tmp_path, monkeypatch):
    """A store built from every trace's own points, each way, row for row."""
    series = _open(SERIES_FIXTURE, tmp_path, "series.jser")
    try:
        for n in sorted(series.sections):
            section = series.loadSection(n)
            new = _storeSignature(SectionColumns.fromSection(section, generation=7))
            with monkeypatch.context() as m:
                m.setattr(columnar_store, "_asCoordinateArray", _oldCoordinateArray)
                old = _storeSignature(SectionColumns.fromSection(section, generation=7))
            assert new == old, f"section {n}"
    finally:
        series.close()


BIG = 2 ** 60 + 1
POINT_LISTS = [
    [(1.0, 2.0)], [(1, 2), (3, 4)], [(BIG, -BIG)], [(2 ** 70, 1.5)],
    [(2 ** 1100, 1.0)], [(-0.0, 5e-324)], [(float("nan"), float("inf"))],
    [(np.float32(1.1), np.int64(3))], [("1.5", "2")], [("a", "b")],
    [(None, 1.0)], [(True, False)],
    [(decimal.Decimal("1.1"), fractions.Fraction(1, 3))],
    [[1.0, 2.0], (3.0, 4.0)], [(1.0,), (2.0, 3.0, 4.0)], [(1.0, 2.0, 3.0)],
    [(1.0, [2.0])], [(np.array(1.5), 2.0)], [(1.0, 2.0), "ab"],
    [(1.0, 2.0), 3.0], [b"ab"], [{1.0: 0, 2.0: 0}], [{1.0, 2.0}], [],
    [(complex(1, 0), 2.0)], [(np.array([1.0]), 2.0)],
    [(np.array([1.0, 2.0]), np.array([3.0, 4.0]))], [([1.0, 2.0], [3.0, 4.0])],
    [((1.0, 2.0), (3.0, 4.0)), ((5.0, 6.0), (7.0, 8.0))],
    [(1.0, 2.0)] * 3 + [((1.0,), 2.0)], [(1.0, "x")], [(b"1", 2.0)],
    [(float("nan"), None)], np.array([[1.0, 2.0]]), ((1.0, 2.0),),
    [([1.0], [2.0])], [(np.array([1.0]), np.array([2.0]))],
]


@pytest.mark.parametrize("points", POINT_LISTS, ids=range(len(POINT_LISTS)))
def test_coordinates_match_np_array_for_any_input(points):
    """The same array (bytes, shape, dtype, its own memory) or the same error."""
    def outcome(convert):
        try:
            array = convert(points)
        except Exception as error:
            return ("error", type(error))
        return ("array", array.tobytes(), array.shape, str(array.dtype),
                array.flags.owndata, array.flags.c_contiguous)
    assert outcome(columnar_store._asCoordinateArray) == outcome(_oldCoordinateArray)


ROW_A = [[0.0, 1.0, 1.0], [0.0, 0.0, 1.0], [255, 0, 0], True, False, False,
         ["none", "none"], []]
ROW_B = [[5.0, 6.0, 6.5], [0.0, 0.0, 1.0], [0, 255, 0], True, True, False,
         ["solid", "none"], ["t1"]]


def _walk(issuer, n, contours):
    return issuer.deriveForSection(n, contours)


def test_ids_by_digest_are_the_walk_ids_through_changes():
    """Same file, other file, same file again: the walk's answer every time.

    The second file adds byte-identical rows, so the record for one key grows
    by more ids; the first file's rows must still get the first ids. The third
    has as many rows as the first, so only the digest tells them apart.
    """
    a = {"axon": [ROW_A, ROW_A], "den": [ROW_B]}
    b = {"axon": [ROW_A, ROW_A, ROW_A], "den": [ROW_B, ROW_A]}
    c = {"axon": [ROW_B, ROW_A], "den": [ROW_A]}
    da, db, dc = (sectionFileDigest(f) for f in (b"file a", b"file b", b"file c"))
    fast, slow = TraceIDIssuer(), TraceIDIssuer()
    for contours, d in [(a, da), (a, da), (b, db), (a, da), (b, db), (b, db),
                        (c, dc), (a, da), (c, dc)]:
        assert fast.deriveForSection(4, contours, digest=d) == _walk(slow, 4, contours)
    assert fast.taken == slow.taken


def test_a_digest_hit_does_not_walk(monkeypatch):
    """The second load of a file reads no row: no row is serialized."""
    from PyReconstruct.modules.datatypes import trace_id

    issuer = TraceIDIssuer()
    contours = {"axon": [ROW_A, ROW_A], "den": [ROW_B]}
    d = sectionFileDigest(b"file")
    first = issuer.deriveForSection(2, contours, digest=d)
    calls = []
    real = trace_id.canonicalJSON
    monkeypatch.setattr(trace_id, "canonicalJSON", lambda o: calls.append(o) or real(o))
    assert issuer.deriveForSection(2, contours, digest=d) == first
    assert calls == []


def test_ids_by_digest_need_the_same_section_and_no_skip():
    """Another section, or rows skipped for adopted ids, walk as before."""
    contours = {"axon": [ROW_A], "den": [ROW_B]}
    d = sectionFileDigest(b"file")
    fast, slow = TraceIDIssuer(), TraceIDIssuer()
    assert fast.deriveForSection(1, contours, digest=d) == _walk(slow, 1, contours)
    assert fast.deriveForSection(2, contours, digest=d) == _walk(slow, 2, contours)
    skip = {("axon", 0): "x"}
    assert (fast.deriveForSection(1, contours, skip=skip, digest=d)
            == slow.deriveForSection(1, contours, skip=skip))
    assert fast.deriveForSection(1, contours, digest=d) == _walk(slow, 1, contours)


def test_a_digest_with_other_rows_walks():
    """A row count that does not match the kept ids is not trusted."""
    issuer = TraceIDIssuer()
    d = sectionFileDigest(b"file")
    issuer.deriveForSection(1, {"axon": [ROW_A]}, digest=d)
    more = {"axon": [ROW_A, ROW_B]}
    assert issuer.deriveForSection(1, more, digest=d) == _walk(TraceIDIssuer(), 1, more)
