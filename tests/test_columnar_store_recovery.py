"""Store edits remain usable after compaction or a refused update."""

from types import SimpleNamespace

import pytest

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.columnar_store import SectionColumns


POINTS = [(1.0, 2.0), (3.0, 4.0)]


def append(store, name="axon"):
    return store.appendRow(
        name, POINTS, [10, 20, 30], closed=False,
        tags={"review"}, trace_id="kept-id",
    )


def test_an_empty_frozen_store_can_grow_again():
    store = SectionColumns(2)
    store.freeze()

    row = append(store)

    assert row == 0
    assert store.rowsForContour("axon") == [0]
    assert store.getPoints(row) == POINTS
    assert store.getColor(row) == [10, 20, 30]
    assert store.getFlag(row, "closed") is False
    assert store.getTags(row) == {"review"}
    assert store.getID(row) == "kept-id"

    store.freeze()
    other = append(store, "dendrite")
    store.setCoordinates(other, [(8.0, 9.0), (10.0, 11.0)])
    assert store.getPoints(row) == POINTS
    assert store.getPoints(other) == [(8.0, 9.0), (10.0, 11.0)]


@pytest.mark.parametrize("points", [
    [1.0, 2.0],
    [(1.0, 2.0, 3.0)],
    [[(1.0, 2.0)]],
])
def test_refused_geometry_keeps_the_row_and_allows_a_retry(points):
    store = SectionColumns(2)
    row = append(store)
    other = append(store, "dendrite")
    store.clearTracking()
    generation = store.generation

    with pytest.raises(ValueError, match="sequence of .* pairs"):
        store.setCoordinates(row, points)

    assert store.getPoints(row) == POINTS
    assert store.getPoints(other) == POINTS
    assert store.getID(row) == "kept-id"
    assert store.generation == generation
    assert store.getAllModifiedNames() == set()

    store.setCoordinates(row, [(5.0, 6.0), (7.0, 8.0)])
    assert store.getPoints(row) == [(5.0, 6.0), (7.0, 8.0)]
    assert store.getPoints(other) == POINTS
    assert store.getAllModifiedNames() == {"axon"}


@pytest.mark.parametrize("attribute, value, error", [
    ("color", [1, 2], ValueError),
    ("tags", {"changed"}, KeyError),
])
def test_refused_attribute_keeps_the_values_and_tracking(attribute, value, error):
    store = SectionColumns(2)
    row = append(store)
    store.clearTracking()
    generation = store.generation

    with pytest.raises(error):
        store.setAttribute(row, attribute, value)

    assert store.getColor(row) == [10, 20, 30]
    assert store.getTags(row) == {"review"}
    assert store.getPoints(row) == POINTS
    assert store.getID(row) == "kept-id"
    assert store.generation == generation
    assert store.getAllModifiedNames() == set()

    store.setAttribute(row, "color", [40, 50, 60])
    store.setTags(row, {"changed"})
    assert store.getColor(row) == [40, 50, 60]
    assert store.getTags(row) == {"changed"}
    assert store.getAllModifiedNames() == {"axon"}


def test_removed_coordinates_cannot_be_read_or_resurrected():
    store = SectionColumns(2)
    removed = append(store)
    kept = append(store, "dendrite")
    backing = store.coordinateBacking
    store.removeRow(removed)

    assert len(backing) == 2
    with pytest.raises(IndexError, match="removed"):
        backing.get(removed)
    with pytest.raises(IndexError, match="removed"):
        backing.set(removed, [(8.0, 9.0), (10.0, 11.0)])

    assert store.getPoints(kept) == POINTS
    added = append(store)
    assert added == 2
    assert store.rowsForContour("axon") == [2]
    assert store.getPoints(added) == POINTS


@pytest.mark.parametrize("replacement", [[], ((5.0, 6.0), (7.0, 8.0))])
def test_a_rebuild_discards_cached_points_after_a_sequence_change(replacement):
    trace = Trace("axon", [10, 20, 30], False)
    trace.points = list(POINTS)
    section = SimpleNamespace(n=2, contours={"axon": [trace]})
    original = SectionColumns.fromSection(section)

    trace.points = replacement
    rebuilt = SectionColumns.fromSection(section)

    assert original.getPoints(0) == POINTS
    assert rebuilt.getPoints(0) == list(replacement)

    trace.points = [(9.0, 10.0), (11.0, 12.0)]
    retried = SectionColumns.fromSection(section)
    assert retried.getPoints(0) == [(9.0, 10.0), (11.0, 12.0)]
    assert original.getPoints(0) == POINTS
