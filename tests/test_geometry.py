"""Equivalence tests for the vectorized per-trace geometry (traceGeometry).

traceGeometry() collapses lineDistance + area + centroid + max-radius into one
NumPy pass for the hot per-trace refresh path. These tests pin it to the scalar
reference functions it replaced, so a future change to either can't silently
drift the quantitative values users rely on (area, radius, length, centroid).
"""
import numpy as np
import pytest

from PyReconstruct.modules.calc import (
    area, centroid, lineDistance, distance, traceGeometry,
)


def _reference(points, closed):
    """The pre-vectorization scalar path, exactly as TraceData used it."""
    o_len = lineDistance(points, closed=closed)
    o_area = area(points) if closed else 0.0
    ocx, ocy = centroid(points)
    o_rad = max((distance(ocx, ocy, x, y) for x, y in points), default=0.0)
    return o_len, o_area, (ocx, ocy), o_rad


def _assert_matches(points, closed):
    o_len, o_area, (ocx, ocy), o_rad = _reference(points, closed)
    nl, na, (ncx, ncy), nr = traceGeometry(points, closed)
    if not closed:
        na = 0.0
    assert nl == pytest.approx(o_len, abs=1e-7)
    assert na == pytest.approx(o_area, rel=1e-9, abs=1e-6)
    assert ncx == pytest.approx(ocx, abs=1e-6)
    assert ncy == pytest.approx(ocy, abs=1e-6)
    assert nr == pytest.approx(o_rad, abs=1e-9)


CASES = [
    ("square_ccw", [(0, 0), (10, 0), (10, 10), (0, 10)], True),
    ("square_cw", [(0, 0), (0, 10), (10, 10), (10, 0)], True),
    ("triangle", [(0, 0), (4, 0), (2, 3)], True),
    ("open_polyline", [(0, 0), (5, 0), (5, 5)], False),
    ("explicitly_closed", [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)], True),
    ("offset_square", [(100, 100), (110, 100), (110, 110), (100, 110)], True),
    ("two_points", [(0, 0), (3, 4)], False),
    ("one_point", [(2, 2)], True),
    ("collinear_zero_area", [(0, 0), (1, 1), (2, 2), (3, 3)], True),
]


@pytest.mark.parametrize("name,pts,closed", CASES, ids=[c[0] for c in CASES])
def test_matches_scalar_reference(name, pts, closed):
    _assert_matches(pts, closed)


def test_random_polygons_match():
    rng = np.random.default_rng(0)
    for _ in range(300):
        k = int(rng.integers(3, 40))
        pts = [(round(float(x), 3), round(float(y), 3))
               for x, y in rng.uniform(-500, 500, size=(k, 2))]
        for closed in (True, False):
            _assert_matches(pts, closed)


def test_empty_returns_zeros():
    assert traceGeometry([], True) == (0.0, 0.0, (0.0, 0.0), 0.0)


def test_accepts_ndarray_input():
    pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
    a = traceGeometry(pts, True)
    b = traceGeometry(np.asarray(pts, dtype=float), True)
    assert a == b
