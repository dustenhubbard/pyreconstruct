"""A loaded section fills its columnar store from the file's own rows.

`Section.__init__` reads each row's x and y lists into an `(n, 2)` array
(`coordinatesFromRow`) and the first store build copies those in, instead of
converting every trace's list of point tuples again. These tests pin that the
store it builds holds exactly what a build from the traces holds, on both
fixture series and on rows a hand-edited or imported file can carry.
"""
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import columnar_store
from PyReconstruct.modules.datatypes.columnar_store import (
    SectionColumns,
    coordinatesFromRow,
)
from PyReconstruct.modules.datatypes.section import Section

SYNTHETIC_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity_series.jser"


@pytest.fixture
def synthetic_series(tmp_path):
    from PyReconstruct.modules.datatypes import Series

    destination = tmp_path / "parity_series.jser"
    shutil.copy(SYNTHETIC_FIXTURE, destination)
    series = Series.openJser(str(destination))
    yield series
    series.close()


def _populated(series):
    sections = [series.loadSection(n) for n in sorted(series.sections)]
    return [s for s in sections if s.contours]


def _assert_same_store(loaded, rebuilt):
    """Every column of every row, coordinates bit for bit."""
    assert loaded.rowCount == rebuilt.rowCount
    assert loaded.contourNames() == rebuilt.contourNames()
    for row in range(rebuilt.rowCount):
        a, b = loaded.getCoordinates(row), rebuilt.getCoordinates(row)
        assert a.dtype == b.dtype == np.float64
        assert a.shape == b.shape
        assert np.array_equal(a, b, equal_nan=True)
        assert loaded.getName(row) == rebuilt.getName(row)
        assert list(loaded.getColor(row)) == list(rebuilt.getColor(row))
        assert list(loaded.getFillMode(row)) == list(rebuilt.getFillMode(row))
        assert loaded.getTags(row) == rebuilt.getTags(row)
        for attribute in ("closed", "negative", "hidden"):
            assert loaded.getFlag(row, attribute) == rebuilt.getFlag(row, attribute)


def _check_series(series):
    sections = _populated(series)
    assert sections
    for section in sections:
        _assert_same_store(section._columns, SectionColumns.fromSection(section))
    return sections


def test_the_loaded_store_equals_a_build_from_the_traces(real_series):
    _check_series(real_series)


def test_the_loaded_store_equals_a_build_from_the_traces_synthetic(synthetic_series):
    _check_series(synthetic_series)


def test_the_load_hands_the_store_arrays_not_point_lists(real_series, monkeypatch):
    """The first build copies the arrays read from the rows; no trace's point
    list is converted again."""
    seen = []
    real = columnar_store._asCoordinateArray

    def recording(points):
        seen.append(type(points))
        return real(points)

    monkeypatch.setattr(columnar_store, "_asCoordinateArray", recording)
    sections = _populated(real_series)
    assert sum(len(s.tracesAsList()) for s in sections) == len(seen) > 0
    assert set(seen) == {np.ndarray}


def test_the_coordinates_are_not_kept_after_the_load(real_series):
    section = _populated(real_series)[0]
    assert section._loaded_coordinates is None


def _write_rows(series, n, rows):
    """Replace section n's contours in its working file with `rows`."""
    fp = Path(series.getwdir()) / series.sections[n]
    data = json.loads(fp.read_text())
    data["contours"] = rows
    fp.write_text(json.dumps(data))


def _row(x, y, closed=True):
    return [x, y, [255, 0, 0], closed, False, False, ["none", "none"], []]


def test_odd_rows_load_into_the_same_store(real_series):
    """Integers, booleans, numbers as text, null and lists of two lengths."""
    n = sorted(real_series.sections)[0]
    _write_rows(real_series, n, {
        "a_ints": [_row([0, 1, 2], [3, 4, 5])],
        "b_mixed": [_row([0.5, True, 2], [1, False, 7.25])],
        "c_text": [_row(["1.5", "2", 3.0], [1, 2, "4e2"])],
        "d_null": [_row([None, 1.0, 2.0], [0.0, None, 2.0])],
        "e_longer_x": [_row([0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 2.0])],
        "f_longer_y": [_row([0.0, 1.0], [0.0, 1.0, 2.0, 3.0], closed=False)],
    })
    section = Section(n, real_series)
    assert len(section.tracesAsList()) == 6
    _assert_same_store(section._columns, SectionColumns.fromSection(section))
    store = section._columns
    (row,) = store.rowsForContour("e_longer_x")
    assert store.getCoordinates(row).shape == (3, 2)
    (row,) = store.rowsForContour("d_null")
    assert math.isnan(store.getCoordinates(row)[0, 0])


def test_a_row_numpy_cannot_read_fails_the_load_as_before(real_series):
    n = sorted(real_series.sections)[0]
    _write_rows(real_series, n, {"a": [_row([10 ** 400, 1, 2], [0, 1, 2])]})
    with pytest.raises(OverflowError):
        Section(n, real_series)
    _write_rows(real_series, n, {"a": [_row(["x", 1, 2], [0, 1, 2])]})
    with pytest.raises(ValueError):
        Section(n, real_series)


@pytest.mark.parametrize("x, y", [
    ([0.1, 2.5, -3.75], [4.0, 5.5, 6.125]),
    ([1, 2], [3, 4]),
    ([True, 0], [1, False]),
    ([None, 1.0], [2.0, 3.0]),
    (["1.5", 2], [3, "4"]),
])
def test_coordinates_from_a_row_match_the_point_tuples(x, y):
    expected = np.array(list(zip(x, y)), dtype=np.float64)
    actual = coordinatesFromRow(x, y)
    assert actual.dtype == np.float64
    assert np.array_equal(actual, expected, equal_nan=True)


@pytest.mark.parametrize("x, y", [
    ([0.0, 1.0, 2.0], [0.0, 1.0]),
    ([10 ** 400], [0]),
    (["x"], [0]),
    ([[1, 2]], [0]),
    (5, [0]),
])
def test_coordinates_from_a_row_give_up_on_what_they_cannot_read(x, y):
    assert coordinatesFromRow(x, y) is None
