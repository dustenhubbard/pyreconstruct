"""The object list read from columns (series_data.TraceColumns, ObjectIds.placeAll).

An open from the local store (store_open.py) puts the stored object-list
numbers into one TraceColumns and builds no TraceData. These hold the column
getters to the TraceData getters, number for number (repr), and placeAll to
what reconcile places.
"""
import numpy as np
import pytest

from PyReconstruct.modules.datatypes import series_data
from PyReconstruct.modules.datatypes.object_ids import ObjectIds
from PyReconstruct.modules.datatypes.series_data import ObjectData, SeriesData, TraceColumns
from PyReconstruct.modules.datatypes.transform import Transform


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
    data.objects["built"].traces  # noqa: B018  (builds the TraceData)
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
        # the kept id has traces again; a fresh id is in no tree record, so
        # placeAll does not tell the tree about it
        assert 7 in reg.series.host_tree.traced_ids


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
        ({"a", "b"}, (0, 0, 255), 2.5, 0, (0.0, 0.0), 0.75)
    # an open trace's area is the int 0, as a full open gives it
    assert repr(td.area) == "0"
    assert td._tform is tform and td._feret == (0, 0)
    assert obj.columnRows() is None
    assert series_data.TraceData.getFeret(td, None, "x") == (0, 0)


def test_each_trace_data_gets_its_own_tag_set():
    columns = _columns([(4, 0, True, 1.0, 2.5, 0.75, 2, 0), (4, 1, True, 1.0, 2.5, 0.75, 2, 0)], [Transform.identity()])
    a, b = ObjectData(columns, 0, 2).traces[4]
    assert type(a.tags) is set and a.tags is not b.tags
    a.tags.add("c")
    assert b.tags == {"a", "b"} and columns.tags[2] == frozenset({"a", "b"})


def test_an_object_of_open_traces_has_the_volume_a_full_open_gives():
    # an int thickness keeps the int 0 of an open trace's area an int
    rows = [(4, 0, False, 0.0, 2.5, 0.75, 0, 0), (4, 1, False, 0.0, 1.5, 0.5, 0, 0)]
    columns = _columns(rows, [Transform.identity()])
    data = SeriesData(None)
    data.data["sections"] = {4: {"thickness": 1}}
    data.data["objects"] = {"lazy": ObjectData(columns, 0, 2), "built": ObjectData(columns, 0, 2)}
    data.objects["built"].traces  # noqa: B018  (builds the TraceData)
    assert repr(data.getVolume("built")) == "0"
    assert repr(data.getVolume("lazy")) == "0"
    assert _object_list(data)["lazy"] == _object_list(data)["built"]


# ---------------------------------------------------------------------------
# The export hands orjson the stored arrays (jser_splice.ArraySection)
