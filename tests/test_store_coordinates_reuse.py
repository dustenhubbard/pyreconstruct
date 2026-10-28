"""A store build reuses a trace's coordinate array while its points are the
same objects.

Every save rebuilds the section's store from its traces, and once a series has
an edit every section change saves two sections, most of whose traces have not
changed since the store was last built. `SectionColumns.fromSection` keeps
each trace's `(n, 2)` array with the point tuples it came from and uses it
again only when the points list holds the very same tuples. Every row it
builds must hold what converting the trace's points as they are now gives,
through every way a trace's points change.
"""
import random
from types import SimpleNamespace

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import columnar_store
from PyReconstruct.modules.datatypes.columnar_store import (
    SectionColumns,
    _asCoordinateArray,
    coordinatesFromRow,
)
from PyReconstruct.modules.datatypes.trace import Trace


def _traces(rng, count=6, n=30):
    traces = []
    for _ in range(count):
        trace = Trace("reuse", (255, 0, 0))
        trace.points = [
            (rng.uniform(-50, 50), rng.uniform(-50, 50)) for _ in range(n)
        ]
        traces.append(trace)
    return traces


def _section(traces):
    return SimpleNamespace(n=1, contours={"reuse": traces})


def _rows(store):
    return [store.getCoordinates(row) for row in store.rowsForContour("reuse")]


def _assert_rows_hold_points(store, traces):
    rows = _rows(store)
    assert len(rows) == len(traces)
    for row, trace in zip(rows, traces):
        fresh = _asCoordinateArray(trace.points)
        assert row.shape == fresh.shape
        assert row.tobytes() == fresh.tobytes()


@pytest.fixture
def conversions(monkeypatch):
    # every conversion of a trace's points to an array starts here
    calls = []
    real = columnar_store._asCoordinateArray

    def counted(points):
        if not isinstance(points, np.ndarray):
            calls.append(len(points))
        return real(points)
    monkeypatch.setattr(columnar_store, "_asCoordinateArray", counted)
    return calls


def test_unchanged_traces_are_not_converted_again(conversions):
    traces = _traces(random.Random(1))
    section = _section(traces)
    SectionColumns.fromSection(section)
    assert len(conversions) == len(traces)
    store = SectionColumns.fromSection(section)
    assert len(conversions) == len(traces)
    _assert_rows_hold_points(store, traces)


def test_the_arrays_a_load_carries_are_kept(conversions):
    traces = _traces(random.Random(2))
    carried = {
        trace: coordinatesFromRow([p[0] for p in trace.points],
                                  [p[1] for p in trace.points])
        for trace in traces
    }
    section = _section(traces)
    SectionColumns.fromSection(section, carried_coordinates=carried)
    store = SectionColumns.fromSection(section)
    assert conversions == []
    _assert_rows_hold_points(store, traces)


def test_each_change_to_the_points_is_converted_again():
    rng = random.Random(3)
    traces = _traces(rng, count=8)
    section = _section(traces)
    SectionColumns.fromSection(section)
    x, y = traces[0].points[4]
    traces[0].points[4] = (x + 1e-9, y)                    # moved in place
    traces[1].points.append((1.0, 2.0))                    # added
    del traces[2].points[3]                                # removed
    traces[3].points.reverse()                             # reordered
    traces[4].points = list(traces[4].points)              # same tuples
    traces[5].points = [(float(a), float(b)) for a, b in traces[5].points]
    traces[6].points[0] = (-0.0, traces[6].points[0][1])   # equal, other sign
    traces[6].points[1] = (0, 1)                           # ints
    traces[7].points = [traces[7].points[0]] * 3           # one tuple thrice
    _assert_rows_hold_points(SectionColumns.fromSection(section), traces)
    # and again, from the arrays kept for the changed points
    _assert_rows_hold_points(SectionColumns.fromSection(section), traces)


def test_points_that_could_change_unseen_are_not_kept(conversions):
    trace = Trace("reuse", (255, 0, 0))
    trace.points = [[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]]   # lists, not tuples
    section = _section([trace])
    SectionColumns.fromSection(section)
    trace.points[1][0] = 9.0
    _assert_rows_hold_points(SectionColumns.fromSection(section), [trace])
    value = np.array(1.0)                                  # a mutable number
    trace.points = [(value, 1.0), (2.0, 3.0), (4.0, 5.0)]
    SectionColumns.fromSection(section)
    value[...] = 7.0
    _assert_rows_hold_points(SectionColumns.fromSection(section), [trace])
    assert len(conversions) == 4


def test_a_row_written_in_place_leaves_the_kept_array_alone():
    traces = _traces(random.Random(4))
    section = _section(traces)
    store = SectionColumns.fromSection(section)
    for row in _rows(store):
        row[:] = 0.0
    _assert_rows_hold_points(SectionColumns.fromSection(section), traces)


def test_the_kept_array_is_read_only():
    traces = _traces(random.Random(5), count=1)
    SectionColumns.fromSection(_section(traces))
    _, kept = columnar_store._HELD_COORDINATES[traces[0]]
    with pytest.raises(ValueError):
        kept[0, 0] = 1.0


def test_a_bad_point_is_still_refused():
    trace = Trace("reuse", (255, 0, 0))
    trace.points = [(0.0, 1.0), (2.0, 3.0, 4.0)]
    with pytest.raises(ValueError):
        SectionColumns.fromSection(_section([trace]))
