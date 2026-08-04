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


# --- the ring's closing edge -------------------------------------------------
#
# The shoelace sum runs over the closed ring, so it needs the wrap edge from the
# last vertex back to the first. These pin the two ways that can go wrong: the
# wrap edge being dropped, and a ring that already carries a duplicate closing
# vertex being counted differently from the same ring given open.


def test_wrap_edge_is_counted():
    """Area is wrong if the last-to-first edge is left out of the sum.

    Chosen so the wrap cross term is non-zero (4*1 - 1*7 == -3): the interior
    edges alone sum to 24, giving 12.0, while the closed ring sums to 21,
    giving the true 10.5.
    """
    pts = [(1.0, 1.0), (5.0, 2.0), (4.0, 7.0)]
    assert traceGeometry(pts, True)[1] == pytest.approx(10.5, abs=1e-12)
    assert traceGeometry(pts, True)[1] == pytest.approx(area(pts), rel=1e-12)


@pytest.mark.parametrize("closed", [True, False])
def test_already_closed_ring_matches_the_open_one(closed):
    """A duplicated final vertex must not change area or centroid.

    The wrap edge of an already-closed ring is x0*y0 - x0*y0, which is exactly
    0.0, so the two spellings of the same polygon describe the same shape. Area
    and centroid must agree; ``length`` legitimately differs, because the
    duplicate vertex adds a zero-length segment only when the trace is open.
    """
    open_ring = [(1.0, 1.0), (5.0, 2.0), (4.0, 7.0), (0.5, 4.0)]
    closed_ring = open_ring + [open_ring[0]]
    _, oa, (ocx, ocy), _ = traceGeometry(open_ring, closed)
    _, ca, (ccx, ccy), _ = traceGeometry(closed_ring, closed)
    assert ca == pytest.approx(oa, rel=1e-12)
    assert (ccx, ccy) == (ocx, ocy)


def test_negative_zero_closing_vertex_is_still_a_closed_ring():
    """-0.0 == 0.0, so a ring closed with signed zeros is still closed.

    IEEE 754 equality, not bit identity, is what makes the wrap term vanish;
    this is the input where the two part company.
    """
    ring = [(0.0, 0.0), (6.0, 0.5), (5.0, 9.0), (-0.0, -0.0)]
    without_dup = ring[:-1]
    assert traceGeometry(ring, True)[1] == pytest.approx(
        traceGeometry(without_dup, True)[1], rel=1e-12
    )


@pytest.mark.parametrize("closed", [True, False])
def test_clockwise_winding_gives_the_same_unsigned_area(closed):
    """The shoelace sum is signed; the reported area is not."""
    pts = [(1.0, 1.0), (5.0, 2.0), (4.0, 7.0), (0.5, 4.0)]
    assert traceGeometry(pts, closed)[1] == pytest.approx(
        traceGeometry(pts[::-1], closed)[1], rel=1e-12
    )
