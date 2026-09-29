"""Precision of trace area, centroid, and radius far from the origin (#426).

area(), centroid(), and traceGeometry() sum their shoelace terms relative to
the trace's first point. In raw coordinates each cross product is on the order
of x*y, so a small trace far from the origin lost its area and centroid to
rounding: a 40-point circle of radius 0.1 at (100000, 100000) reported a
centroid 0.7 off and a radius of 1.08.

These tests pin that the same shape gives the same numbers wherever it sits,
and that ordinary traces keep the values they had before, to float noise.
"""
import math

import numpy as np
import pytest

from PyReconstruct.modules.calc import area, centroid, distance, traceGeometry
from PyReconstruct.modules.datatypes.series_data import TraceData
from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.datatypes.transform import Transform


def _circle(cx, cy, r=0.1, n=40):
    return [
        (cx + r * math.cos(2 * math.pi * i / n),
         cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _shift(pts, dx, dy):
    return [(x + dx, y + dy) for x, y in pts]


def _scalar(pts):
    """area, centroid, and radius the way Trace.getRadius() works them out."""
    cx, cy = centroid(pts)
    r = max(distance(cx, cy, x, y) for x, y in pts)
    return area(pts), (cx, cy), r


def _trace(pts):
    t = Trace("obj", (255, 0, 0), closed=True)
    t.points = list(pts)
    return t


IDENTITY = Transform([1, 0, 0, 0, 1, 0])


# --------------------------------------------------------------------------- #
# the case in the issue                                                        #
# --------------------------------------------------------------------------- #

def test_small_circle_far_from_origin_matches_the_one_at_the_origin():
    near = _circle(0.0, 0.0)
    far = _circle(100000.0, 100000.0)

    a0, (cx0, cy0), r0 = _scalar(near)
    a1, (cx1, cy1), r1 = _scalar(far)
    assert a1 == pytest.approx(a0, rel=1e-9)
    assert cx1 - 100000.0 == pytest.approx(cx0, abs=1e-9)
    assert cy1 - 100000.0 == pytest.approx(cy0, abs=1e-9)
    assert r1 == pytest.approx(r0, rel=1e-9)
    assert r1 == pytest.approx(0.1, rel=1e-9)

    _, ga0, (gx0, gy0), gr0 = traceGeometry(near, True)
    _, ga1, (gx1, gy1), gr1 = traceGeometry(far, True)
    assert ga1 == pytest.approx(ga0, rel=1e-9)
    assert gx1 - 100000.0 == pytest.approx(gx0, abs=1e-9)
    assert gy1 - 100000.0 == pytest.approx(gy0, abs=1e-9)
    assert gr1 == pytest.approx(gr0, rel=1e-9)


def test_object_list_and_trace_radius_agree_far_from_origin():
    """TraceData (object list, exports) and Trace.getRadius() (trace dialog,
    3D spheres) go through different entry points and must agree."""
    far = _circle(100000.0, 100000.0)
    data = TraceData(_trace(far), 0, IDENTITY)
    trace = _trace(far)
    assert data.getRadius() == pytest.approx(0.1, rel=1e-9)
    assert trace.getRadius() == pytest.approx(data.getRadius(), rel=1e-12)
    assert trace.getCentroid() == pytest.approx(data.getCentroid(), abs=1e-9)
    assert data.getArea() == pytest.approx(area(far), rel=1e-12)


def test_large_shift_in_the_alignment_gives_the_same_numbers():
    """The math runs on transformed points, so a big shift in the alignment
    must not cost precision either."""
    pts = _circle(3.0, 4.0)
    base = TraceData(_trace(pts), 0, IDENTITY)
    shifted = TraceData(_trace(pts), 0, Transform([1, 0, 250000, 0, 1, -125000]))
    assert shifted.getArea() == pytest.approx(base.getArea(), rel=1e-9)
    assert shifted.getRadius() == pytest.approx(base.getRadius(), rel=1e-9)
    cx, cy = shifted.getCentroid()
    assert cx - 250000 == pytest.approx(base.getCentroid()[0], abs=1e-9)
    assert cy + 125000 == pytest.approx(base.getCentroid()[1], abs=1e-9)


# --------------------------------------------------------------------------- #
# translation invariance                                                       #
# --------------------------------------------------------------------------- #

def _star(n=24, r=0.3, seed=3):
    rng = np.random.default_rng(seed)
    rad = r * rng.uniform(0.4, 1.0, n)
    return [
        (float(a * math.cos(2 * math.pi * i / n)),
         float(a * math.sin(2 * math.pi * i / n)))
        for i, a in enumerate(rad)
    ]


SHAPES = {
    "circle_r0.1": _circle(0.0, 0.0),
    "circle_r2": _circle(0.0, 0.0, r=2.0, n=64),
    "triangle": [(0.0, 0.0), (0.05, 0.0), (0.02, 0.03)],
    "l_shape": [(0, 0), (0.4, 0), (0.4, 0.1), (0.1, 0.1), (0.1, 0.3), (0, 0.3)],
    "star": _star(),
}
# Offsets on the 1e-6 grid, so rounding the centroid to 6 places lands on the
# same step at every offset and the comparison sees the math alone.
OFFSETS = [
    (7500.0, 7500.0),
    (100000.0, 100000.0),
    (-250000.0, 40000.5),
    (1e6, -1e6),
    (12345.25, 67890.75),
]


@pytest.mark.parametrize("shape", list(SHAPES))
@pytest.mark.parametrize("offset", OFFSETS, ids=[str(o) for o in OFFSETS])
@pytest.mark.parametrize("winding", ["ccw", "cw"])
def test_translation_invariance(shape, offset, winding):
    pts = SHAPES[shape]
    if winding == "cw":
        pts = pts[::-1]
    dx, dy = offset
    moved = _shift(pts, dx, dy)
    size = max(math.hypot(x, y) for x, y in pts)

    a0, (cx0, cy0), r0 = _scalar(pts)
    a1, (cx1, cy1), r1 = _scalar(moved)
    assert a1 == pytest.approx(a0, rel=1e-8)
    assert cx1 - dx == pytest.approx(cx0, abs=1e-9 * max(1.0, abs(dx)) + 1e-9)
    assert cy1 - dy == pytest.approx(cy0, abs=1e-9 * max(1.0, abs(dy)) + 1e-9)
    assert r1 == pytest.approx(r0, rel=1e-8, abs=1e-9 * size)

    _, ga, (gx, gy), gr = traceGeometry(moved, True)
    assert ga == pytest.approx(a1, rel=1e-12)
    assert (gx, gy) == pytest.approx((cx1, cy1), abs=1.01e-6)
    assert gr == pytest.approx(r1, abs=1.5e-6)


@pytest.mark.parametrize("shape", list(SHAPES))
def test_winding_does_not_change_the_numbers_far_away(shape):
    moved = _shift(SHAPES[shape], 100000.0, 100000.0)
    ccw = traceGeometry(moved, True)
    cw = traceGeometry(moved[::-1], True)
    assert cw[1] == pytest.approx(ccw[1], rel=1e-12)
    assert cw[2] == pytest.approx(ccw[2], abs=1.01e-6)
    assert cw[3] == pytest.approx(ccw[3], abs=1.5e-6)
    assert centroid(moved[::-1]) == pytest.approx(centroid(moved), abs=1.01e-6)


# --------------------------------------------------------------------------- #
# degenerate traces                                                            #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("pts", [
    [(100000.0, 100000.0)],
    [(100000.0, 100000.0), (100000.3, 100000.4)],
], ids=["one_point", "two_points"])
def test_fewer_than_three_points_far_away(pts):
    assert area(pts) == 0
    mean = (round(sum(p[0] for p in pts) / len(pts), 6),
            round(sum(p[1] for p in pts) / len(pts), 6))
    assert centroid(pts) == mean
    _, ga, gc, _ = traceGeometry(pts, True)
    assert ga == 0.0
    assert gc == pytest.approx(mean, abs=1e-9)


def test_zero_area_far_away_falls_back_to_the_mean():
    pts = [(100000.0 + 0.1 * i, 100000.0 + 0.2 * i) for i in range(5)]
    assert area(pts) == pytest.approx(0.0, abs=1e-9)
    _, ga, gc, _ = traceGeometry(pts, True)
    assert ga == pytest.approx(0.0, abs=1e-9)
    assert centroid(pts) == pytest.approx((100000.2, 100000.4), abs=1e-6)
    assert gc == pytest.approx((100000.2, 100000.4), abs=1e-6)


@pytest.mark.parametrize("offset", [(0.0, 0.0), (100000.0, 100000.0)])
def test_repeated_first_point_at_the_end_changes_nothing(offset):
    ring = _shift(SHAPES["star"], *offset)
    closed = ring + [ring[0]]
    assert area(closed) == area(ring)
    assert centroid(closed) == centroid(ring)
    _, oa, oc, orad = traceGeometry(ring, True)
    _, ca, cc, crad = traceGeometry(closed, True)
    assert ca == oa
    assert cc == oc
    assert crad == orad


# --------------------------------------------------------------------------- #
# ordinary traces keep their values                                            #
# --------------------------------------------------------------------------- #

def _old_area(pts):
    """area() before #426: the shoelace sum in raw coordinates."""
    if len(pts) <= 2:
        return 0
    if pts[0] != pts[-1]:
        pts = pts + pts[:1]
    s = 0
    for i in range(len(pts) - 1):
        s += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(s / 2)


def _old_centroid(pts):
    """centroid() before #426, in raw coordinates, orientation via signed area."""
    if len(pts) > 2:
        ring = pts + pts[:1] if pts[0] != pts[-1] else pts
        s2 = sx = sy = 0
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            c = x1 * y2 - x2 * y1
            s2 += c
            sx += (x1 + x2) * c
            sy += (y1 + y2) * c
        if abs(s2) / 2 > 1e-6:
            return round(sx / (3 * s2), 6), round(sy / (3 * s2), 6)
    return (round(sum(p[0] for p in pts) / len(pts), 6),
            round(sum(p[1] for p in pts) / len(pts), 6))


def _realistic_traces(count=400, seed=426):
    """Closed traces the size of cell profiles, at the section coordinates a
    typical series uses, rounded to 7 places the way traces are stored."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(count):
        n = int(rng.integers(8, 80))
        cx, cy = rng.uniform(0, 20, 2)
        r = rng.uniform(0.05, 3.0)
        ang = np.sort(rng.uniform(0, 2 * math.pi, n))
        rad = r * rng.uniform(0.7, 1.0, n)
        pts = [(round(float(cx + a * math.cos(b)), 7),
                round(float(cy + a * math.sin(b)), 7)) for a, b in zip(rad, ang)]
        out.append(pts if rng.random() < 0.5 else pts[::-1])
    return out


def test_ordinary_traces_keep_their_values():
    for pts in _realistic_traces():
        old_a = _old_area(pts)
        old_c = _old_centroid(pts)
        old_r = max(distance(*old_c, x, y) for x, y in pts)

        new_a, new_c, new_r = _scalar(pts)
        _, g_a, g_c, g_r = traceGeometry(pts, True)

        for a in (new_a, g_a):
            assert a == pytest.approx(old_a, rel=1e-12)
        # the centroid is rounded to 6 places, so float noise can at most move
        # it by one step, and the radius by as much
        for c in (new_c, g_c):
            assert c == pytest.approx(old_c, abs=1.01e-6)
        for r in (new_r, g_r):
            assert r == pytest.approx(old_r, abs=1.5e-6)
