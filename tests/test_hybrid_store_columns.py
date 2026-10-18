"""PROTOTYPE (hub #247, R8): the object list read from the store's columns.

An open from the store puts the stored object-list numbers into one
TraceColumns and builds no TraceData. These tests hold it to the numbers a
full refresh gives, number for number (repr, not a tolerance), and check that
the object ids come out as reconcile places them.
"""
import json
import sqlite3

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import hybrid_store, series_data
from PyReconstruct.modules.datatypes.object_ids import ObjectIds
from PyReconstruct.modules.datatypes.series_data import ObjectData, SeriesData, TraceColumns
from PyReconstruct.modules.datatypes.transform import Transform
from tests.test_hybrid_store import SERIES_FILES, _copy, _open


@pytest.fixture
def store_on(tmp_path, monkeypatch):
    root = tmp_path / "stores"
    monkeypatch.setenv(hybrid_store.ENV_SWITCH, "1")
    monkeypatch.setenv(hybrid_store.ENV_DIR, str(root))
    return root


def _object_list(data) -> dict:
    """What the object list reads for every object, floats by repr."""
    out = {}
    for name in data.objects:
        out[name] = (
            data.getStart(name), data.getEnd(name), data.getCount(name),
            repr(data.getFlatArea(name)), repr(data.getVolume(name)),
            repr(data.getAvgRadius(name)), data.getConfiguration(name),
            data.getTags(name), list(data.getColorCounts(name).items()),
        )
    out[None] = data.usedTags()
    return out


def _built(data) -> list:
    """The objects whose TraceData have been built."""
    return [name for name, obj in data.objects.items() if obj.columnRows() is None]


@pytest.mark.parametrize("src", SERIES_FILES, ids=lambda p: p.name)
def test_the_lazy_open_builds_no_trace_data_and_its_object_list_equals_a_full_refresh(src, tmp_path, store_on):
    fp = _copy(src, tmp_path)
    _open(fp).close()
    series = _open(fp)
    try:
        assert series.store.recomputed == []
        assert series.data.objects
        assert _built(series.data) == []
        from_columns = _object_list(series.data)
        assert _built(series.data) == []  # the getters built nothing either
        series.data.refresh(show_progress=False)
        assert _object_list(series.data) == from_columns
    finally:
        series.close()


@pytest.mark.parametrize("src", SERIES_FILES, ids=lambda p: p.name)
def test_trace_data_built_from_the_columns_give_the_same_object_list(src, tmp_path, store_on):
    fp = _copy(src, tmp_path)
    _open(fp).close()
    series = _open(fp)
    try:
        from_columns = _object_list(series.data)
        for obj in series.data.objects.values():
            obj.traces
        assert len(_built(series.data)) == len(series.data.objects)
        assert _object_list(series.data) == from_columns
    finally:
        series.close()


def test_a_section_measured_again_leaves_the_other_objects_in_columns(tmp_path, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    _open(fp).close()
    db_fp, _ = hybrid_store.storePaths(str(fp))
    con = sqlite3.connect(db_fp)
    snum, keys = con.execute(
        "SELECT snum, keys FROM section_stats WHERE cpos != x'' ORDER BY snum LIMIT 1"
    ).fetchone()
    keys = ["elsewhere" if k is not None else None for k in json.loads(keys)]
    con.execute("UPDATE section_stats SET keys=? WHERE snum=?", (json.dumps(keys), snum))
    con.commit()
    con.close()

    series = _open(fp)
    try:
        assert series.store.recomputed == [snum]
        built = set(_built(series.data))
        from_columns = _object_list(series.data)
        assert built and built <= set(series.loadSection(snum).contours)
        assert len(built) < len(series.data.objects)
        # each (section, name) with traces has an id, as after a refresh
        placed = set(series.data.object_ids.placed)
        series.data.refresh(show_progress=False)
        assert set(series.data.object_ids.placed) == placed
        fresh = _object_list(series.data)
        assert fresh.keys() == from_columns.keys()
        assert fresh == from_columns
    finally:
        series.close()


def test_a_store_with_no_column_rows_measures_every_section_once(tmp_path, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    _open(fp).close()
    db_fp, _ = hybrid_store.storePaths(str(fp))
    con = sqlite3.connect(db_fp)
    con.execute("DELETE FROM section_stats")
    con.commit()
    con.close()

    series = _open(fp)
    try:
        assert series.store.recomputed == sorted(series.sections)
    finally:
        series.close()
    series = _open(fp)
    try:
        assert series.store.recomputed == []
        from_columns = _object_list(series.data)
        series.data.refresh(show_progress=False)
        assert _object_list(series.data) == from_columns
    finally:
        series.close()


def _columns(rows, tforms):
    """A TraceColumns of hand-made rows: (snum, index, closed, area, length, radius, tag, color)."""
    arrays = {
        "snum": np.array([r[0] for r in rows], dtype=np.int32),
        "index": np.array([r[1] for r in rows], dtype=np.int32),
        "closed": np.array([r[2] for r in rows], dtype=bool),
        "hidden": np.zeros(len(rows), dtype=bool),
        "negative": np.zeros(len(rows), dtype=bool),
        "tag": np.array([r[6] for r in rows], dtype=np.int32),
        "color": np.array([r[7] for r in rows], dtype=np.int32),
        "length": np.array([r[4] for r in rows], dtype=np.float64),
        "area": np.array([r[3] for r in rows], dtype=np.float64),
        "cx": np.zeros(len(rows)),
        "cy": np.zeros(len(rows)),
        "radius": np.array([r[5] for r in rows], dtype=np.float64),
        "tform": np.zeros(len(rows), dtype=np.int32),
    }
    tags = [frozenset(), frozenset({"a"}), frozenset({"a", "b"})]
    colors = [None, (255, 0, 0), (0, 0, 255)]
    return TraceColumns(arrays, tags, colors, tforms)


def test_the_column_getters_add_in_the_order_the_trace_data_add():
    # 1e16 + 1.0 rounds back to 1e16, so the order of the additions shows
    rows = [
        (1, 0, True, 1e16, 3.0, 1e16, 1, 1),
        (1, 1, True, 1.0, 2.0, 1.0, 0, 0),
        (2, 0, True, -1e16, 1.5, -1e16, 2, 1),
        (2, 1, False, 0.0, 1e17, 1.0, 0, 2),
        (3, 0, True, 1.0, 0.25, 0.5, 1, 1),
    ]
    columns = _columns(rows, [Transform.identity()])
    data = SeriesData(None)
    data.data["sections"] = {1: {"thickness": 0.1}, 2: {"thickness": 0.05}, 3: {"thickness": 0.07}}
    data.data["objects"] = {"lazy": ObjectData(columns, 0, len(rows)), "built": ObjectData(columns, 0, len(rows))}
    data.objects["built"].traces
    lazy, built = _object_list(data)["lazy"], _object_list(data)["built"]
    assert data.objects["lazy"].columnRows() is not None
    assert lazy == built
    assert lazy[3] == repr(1.0 + 1e17 * 0.05)  # flat area, added in row order


def test_place_all_places_what_reconcile_places():
    pairs = [(1, "a"), (2, "a"), (1, "b"), (3, "c"), (2, "c"), (5, "c")]
    one, two = ObjectIds(), ObjectIds()
    one.reconcile(pairs)
    by_name = {}
    for snum, name in pairs:
        by_name.setdefault(name, []).append(snum)
    two.placeAll(by_name.items())
    assert set(one.placed) == set(two.placed)
    for reg in (one, two):
        for name in by_name:
            ids = {oid for (s, n), oid in reg.placed.items() if n == name}
            assert len(ids) == 1
            assert reg.live(name) == ids
            assert reg.name_of[ids.pop()] == name
    assert {n: sorted(c.values()) for n, c in one._live.items()} == \
        {n: sorted(c.values()) for n, c in two._live.items()}
    assert one.version == two.version == len(by_name)


class _Tree:
    """A host tree that keeps id 7 for "kept"."""

    def __init__(self):
        self.traced_ids = []

    def holdsIds(self, ids):
        return True

    def keptId(self, name):
        return 7 if name == "kept" else None

    def traced(self, oid):
        self.traced_ids.append(oid)


class _Series:
    def __init__(self):
        self.host_tree = _Tree()


def test_place_all_takes_the_id_the_host_tree_keeps():
    by_reconcile, by_place_all = ObjectIds(_Series()), ObjectIds(_Series())
    for reg in (by_reconcile, by_place_all):
        reg.name_of[7] = "kept"
    by_reconcile.reconcile([(1, "kept"), (2, "kept"), (1, "new")])
    by_place_all.placeAll([("kept", [1, 2]), ("new", [1])])
    for reg in (by_reconcile, by_place_all):
        assert reg.peek(1, "kept") == reg.peek(2, "kept") == 7
        assert reg.peek(1, "new") not in (None, 7)
        assert sorted(reg.series.host_tree.traced_ids) == sorted([7, reg.peek(1, "new")])


def test_place_all_refuses_a_registry_with_something_placed():
    reg = ObjectIds()
    reg.ensure(1, "a")
    with pytest.raises(ValueError):
        reg.placeAll([("b", [1])])


def test_a_trace_data_built_from_the_columns_is_what_the_columns_hold():
    tform = Transform.identity()
    columns = _columns([(4, 2, False, 0.0, 2.5, 0.75, 2, 2)], [tform])
    obj = ObjectData(columns, 0, 1)
    (td,) = obj.traces[4]
    assert (td.index, td.closed, td.hidden, td.negative) == (2, False, False, False)
    assert (td.tags, td.color, td.length, td.area, td.centroid, td.radius) == \
        (frozenset({"a", "b"}), (0, 0, 255), 2.5, 0.0, (0.0, 0.0), 0.75)
    assert td._tform is tform and td._feret == (0, 0)
    assert obj.columnRows() is None
    assert series_data.TraceData.getFeret(td, None, "x") == (0, 0)
