"""A loaded trace's points are built from the file's x and y lists when first read.

`Section.__init__` gives each trace a `LazyPoints` over the row's own lists
(`lazy_points.py`). It must act as the plain list `list(zip(x, y))` gave in
every way a caller can see, save the same bytes, carry the same ids, hand the
store the array the load read, and stay unbuilt through a draw from the store.
"""

import copy
import json
import pickle
import random

import numpy as np
import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.backend.view.trace_layer import TraceLayer
from PyReconstruct.modules.constants.fast_json import fast_loads
from PyReconstruct.modules.datatypes import columnar_store
from PyReconstruct.modules.datatypes.columnar_store import coordinatesFromRow
from PyReconstruct.modules.datatypes.lazy_points import LazyPoints
from PyReconstruct.modules.datatypes.section import Section, fast_dumps


def _rows(section) -> dict:
    """{(contour, i): (x, y)} as the section file holds them."""
    with open(section.filepath, "rb") as f:
        data = fast_loads(f.read())
    rows = {}
    for name, contour in data["contours"].items():
        for i, row in enumerate(contour):
            fields = row[1:] if len(row) == 9 else row
            rows[(name, i)] = (fields[0], fields[1])
    return rows


def _loaded(series):
    """The first section with traces, and its rows."""
    for n in sorted(series.sections):
        section = Section(n, series)
        if section.contours:
            return section, _rows(section)
    raise AssertionError("no section with traces")


def _points(section):
    return [t.points for c in section.contours.values() for t in c]


def _ids(section):
    columns = section._columns
    return [columns.getID(row) for row in sorted(section.traceRows().values())]


def _plain(x, y, array=True):
    arr = coordinatesFromRow(x, y) if array else None
    return LazyPoints(x, y, arr), list(zip(x, y))


def _random_rows(rng, n=12):
    x = [rng.uniform(-5, 5) if i % 5 else rng.randrange(-5, 5) for i in range(n)]
    y = [rng.uniform(-5, 5) for _ in range(n)]
    return x, y


# --- the load ---------------------------------------------------------------

def test_a_loaded_section_builds_no_point_tuples(real_series):
    section, rows = _loaded(real_series)
    points = _points(section)
    assert len(points) == len(rows) > 0
    assert all(type(p) is LazyPoints and p.pending for p in points)
    assert all(len(p) == len(x) for p, (x, _) in zip(points, rows.values()))


def test_the_points_read_are_the_file_rows_zipped(real_series):
    section, rows = _loaded(real_series)
    for name, contour in section.contours.items():
        for i, trace in enumerate(contour):
            x, y = rows[(name, i)]
            assert trace.points == list(zip(x, y))
            assert [tuple(map(type, p)) for p in trace.points] == \
                [(type(a), type(b)) for a, b in zip(x, y)]
            assert not trace.points.pending


def test_a_row_with_unequal_lists_loads_as_before(real_series):
    section, rows = _loaded(real_series)
    (name, i), (x, y) = next(iter(rows.items()))
    assert LazyPoints.fromRow(x[:-1], y) is None
    assert LazyPoints.fromRow(x, "12") is None
    assert LazyPoints.fromRow(tuple(x), y) is None
    assert section.contours[name][i].points == list(zip(x, y))


def test_a_section_saves_the_same_bytes_and_ids(real_series):
    lazy, _ = _loaded(real_series)
    plain, _ = _loaded(real_series)
    for trace in [t for c in plain.contours.values() for t in c]:
        trace.points = trace.points.copy()
        assert type(trace.points) is list
    plain.resyncColumnarStore()
    assert _ids(lazy) == _ids(plain)
    assert fast_dumps(lazy.getDict()) == fast_dumps(plain.getDict())
    assert fast_dumps(lazy.getDict()) == fast_dumps(plain.getDict())


def test_the_store_rebuild_takes_the_array_the_load_read(real_series, monkeypatch):
    section, _ = _loaded(real_series)
    seen = []
    real = columnar_store._asCoordinateArray

    def recording(points):
        seen.append(type(points))
        return real(points)
    monkeypatch.setattr(columnar_store, "_asCoordinateArray", recording)
    section.resyncColumnarStore()
    assert set(seen) == {np.ndarray} and len(seen) == len(_points(section))
    trace = section.tracesAsList()[0]
    expected = section._columns.getCoordinates(section.traceRows()[trace]).copy()
    assert trace.points.loadedArray() is not None
    trace.points[0] = (trace.points[0][0] + 1.0, trace.points[0][1])
    assert trace.points.loadedArray() is None
    seen.clear()
    section.resyncColumnarStore()
    assert seen.count(LazyPoints) == 1
    actual = section._columns.getCoordinates(section.traceRows()[trace])
    expected[0, 0] += 1.0
    assert np.array_equal(actual, expected)


def test_a_copy_of_a_trace_holds_a_plain_list(real_series):
    section, _ = _loaded(real_series)
    trace = section.tracesAsList()[0]
    copied = trace.copy()
    assert type(copied.points) is list
    assert copied.points == trace.points
    assert trace.points.loadedArray() is not None


# --- the draw ---------------------------------------------------------------

@pytest.mark.gui
def test_a_draw_from_the_store_reads_no_points(qapp, real_series):
    real_series.setSettingsStore(DictSettingsStore())
    try:
        section, _ = _loaded(real_series)
        real_series.setOption("show_ztraces", False)
        real_series.setOption("show_flags", "none")
        layer = TraceLayer(section, real_series)
        bounds = np.array([t.getBounds(section.tform) for t in section.tracesAsList()])
        # getBounds read the points; the next load's traces are untouched
        section, _ = _loaded(real_series)
        layer = TraceLayer(section, real_series)
        x0, y0 = bounds[:, :2].min(axis=0)
        x1, y1 = bounds[:, 2:].max(axis=0)
        layer.generateTraceLayer((400, 300), [x0, y0, x1 - x0, y1 - y0])
        assert len(layer.traces_in_view) == len(section.tracesAsList()) > 0
        assert all(p.pending for p in _points(section))
    finally:
        real_series.setSettingsStore(None)


# --- the list ---------------------------------------------------------------

def test_the_array_is_the_one_asarray_gives_for_the_tuples():
    rng = random.Random(7)
    for array in (True, False):
        x, y = _random_rows(rng)
        lazy, plain = _plain(x, y, array)
        expected = np.asarray(plain, dtype=float)
        actual = np.asarray(lazy, dtype=float)
        assert actual.dtype == expected.dtype and actual.tobytes() == expected.tobytes()
        assert lazy.pending == array
        assert np.array(lazy).dtype == np.array(plain).dtype
        assert np.asarray(lazy, dtype=np.int64).tolist() == np.asarray(plain, dtype=np.int64).tolist()
    x, y = [1, 2, 3], [4, 5, 6]
    lazy, plain = _plain(x, y)
    assert np.array(lazy).dtype == np.array(plain).dtype == np.int64
    assert np.asarray(lazy, dtype=float).dtype == np.float64


def test_the_array_is_read_only_and_a_copy_in_the_store():
    x, y = _random_rows(random.Random(8))
    lazy, _ = _plain(x, y)
    array = np.asarray(lazy, dtype=float)
    assert array is lazy.loadedArray()
    with pytest.raises(ValueError):
        array[0, 0] = 1.0
    stored = columnar_store._asCoordinateArray(lazy)
    assert stored is not array and stored.flags.writeable
    assert np.array_equal(stored, array)
    assert lazy.pending


CHANGES = {
    "setitem": lambda p: p.__setitem__(1, (9.0, 9.0)),
    "slice": lambda p: p.__setitem__(slice(0, 2), [(1.0, 1.0)]),
    "delitem": lambda p: p.__delitem__(0),
    "append": lambda p: p.append((1.0, 2.0)),
    "extend": lambda p: p.extend([(1.0, 2.0), (3.0, 4.0)]),
    "insert": lambda p: p.insert(0, (1.0, 2.0)),
    "pop": lambda p: p.pop(),
    "remove": lambda p: p.remove(p[3]),
    "clear": lambda p: p.clear(),
    "reverse": lambda p: p.reverse(),
    "sort": lambda p: p.sort(key=lambda q: q[1], reverse=True),
    "iadd": lambda p: p.__iadd__([(1.0, 2.0)]),
    "imul": lambda p: p.__imul__(2),
}


@pytest.mark.parametrize("change", CHANGES)
def test_a_change_applies_to_the_points_and_drops_the_array(change):
    x, y = _random_rows(random.Random(9))
    lazy, plain = _plain(x, y)
    assert CHANGES[change](lazy) == CHANGES[change](plain)
    assert lazy == plain and len(lazy) == len(plain) and not lazy.pending
    assert lazy.loadedArray() is None
    actual = np.asarray(lazy, dtype=float)
    assert actual.tolist() == np.asarray(plain, dtype=float).tolist()
    assert actual.flags.writeable


READS = {
    "len": len,
    "bool": bool,
    "iter": list,
    "reversed": lambda p: list(reversed(p)),
    "getitem": lambda p: p[3],
    "negative": lambda p: p[-1],
    "slice": lambda p: p[1:5:2],
    "contains": lambda p: p[2] in p,
    "not contains": lambda p: (0.5, 0.5) in p,
    "repr": repr,
    "str": str,
    "index": lambda p: p.index(p[4]),
    "count": lambda p: p.count(p[4]),
    "copy": lambda p: p.copy(),
    "unpack": lambda p: [*p],
    "zip star": lambda p: list(zip(*p)),
    "add": lambda p: p + [(1.0, 1.0)],
    "radd": lambda p: [(1.0, 1.0)] + p,
    "mul": lambda p: p * 2,
    "rmul": lambda p: 2 * p,
    "json": json.dumps,
    "sorted": sorted,
    "min": min,
    "sum of x": lambda p: sum(q[0] for q in p),
    "pickle": lambda p: pickle.loads(pickle.dumps(p)),
    "copy.copy": copy.copy,
    "deepcopy": copy.deepcopy,
    "enumerate": lambda p: list(enumerate(p)),
    "fromiter": lambda p: np.fromiter((q[0] for q in p), dtype=float).tolist(),
}


@pytest.mark.parametrize("read", READS)
def test_a_read_gives_what_the_list_gives(read):
    x, y = _random_rows(random.Random(10))
    lazy, plain = _plain(x, y)
    actual, expected = READS[read](lazy), READS[read](plain)
    assert actual == expected
    assert type(actual) is type(expected)
    assert lazy == plain
    if read not in ("len", "bool"):
        assert not lazy.pending
    assert lazy.loadedArray() is not None


def test_adding_the_points_in_place_keeps_the_destination_list():
    x, y = _random_rows(random.Random(14))
    lazy, plain = _plain(x, y)
    target = [(0.0, 0.0)]
    alias = target
    target += lazy
    assert alias is target
    assert alias == [(0.0, 0.0)] + plain
    with pytest.raises(TypeError):
        ((0.0, 0.0),) + LazyPoints(x, y)


def test_len_and_truth_build_nothing():
    x, y = _random_rows(random.Random(11))
    lazy, _ = _plain(x, y)
    assert len(lazy) == 12 and lazy
    assert lazy.pending
    empty = LazyPoints([], [])
    assert len(empty) == 0 and not empty and empty == []


COMPARISONS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
}


@pytest.mark.parametrize("comparison", COMPARISONS)
def test_comparisons_with_the_list_on_either_side(comparison):
    x, y = _random_rows(random.Random(12))
    compare = COMPARISONS[comparison]
    for other in (list(zip(x, y)), list(zip(x, y))[:-1], list(zip(x, y)) + [(0.0, 0.0)],
                  [(9.0, 9.0)] + list(zip(x, y))[1:], LazyPoints(x, y)):
        lazy, plain = _plain(x, y)
        assert compare(lazy, other) == compare(plain, list(other))
        lazy, plain = _plain(x, y)
        assert compare(other, lazy) == compare(list(other), plain)
    with pytest.raises(TypeError):
        hash(LazyPoints(x, y))


def test_the_points_are_the_very_same_objects_the_lists_hold():
    x, y = _random_rows(random.Random(13))
    lazy, _ = _plain(x, y)
    assert all(p[0] is a and p[1] is b for p, a, b in zip(lazy, x, y))
    assert all(type(p) is tuple for p in lazy)


def test_the_lists_must_match():
    with pytest.raises(ValueError):
        LazyPoints([1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        LazyPoints((1.0,), [1.0])
