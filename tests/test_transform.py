"""Tests for the vectorized affine point map (Transform.map).

map() of a point list is now a single NumPy affine pass instead of one
QTransform.map call per point. These pin it to QTransform's result so the
optimization can't drift the coordinates everything downstream depends on.
"""
import math
import pytest

from PyReconstruct.modules.datatypes.transform import Transform

TFORMS = [
    ("identity", [1, 0, 0, 0, 1, 0]),
    ("translate", [1, 0, 5.5, 0, 1, -3.25]),
    ("scale", [2.0, 0, 0, 0, 0.5, 0]),
    ("rotate", [math.cos(0.3), -math.sin(0.3), 10, math.sin(0.3), math.cos(0.3), -7]),
    ("shear", [1, 0.4, 0, 0.2, 1, 0]),
    ("affine", [1.3, 0.2, 4.0, -0.1, 0.9, 2.5]),
]

PTS = [(0, 0), (1, 2), (-3.5, 4.25), (100.1, -200.2), (12345.6, 7890.1)]


@pytest.mark.parametrize("name,t", TFORMS, ids=[x[0] for x in TFORMS])
def test_map_matches_qtransform(name, t):
    tform = Transform(list(t))
    q = tform.qtform
    ref = [q.map(x, y) for (x, y) in PTS]
    got = tform.map(PTS)
    assert len(got) == len(ref)
    for (gx, gy), (rx, ry) in zip(got, ref):
        assert gx == pytest.approx(rx, abs=1e-9)
        assert gy == pytest.approx(ry, abs=1e-9)


def test_map_empty():
    assert Transform([1, 0, 0, 0, 1, 0]).map([]) == []


def test_map_single_point_form_unchanged():
    tform = Transform([1.3, 0.2, 4.0, -0.1, 0.9, 2.5])
    assert tform.map(2.0, 3.0) == tform.qtform.map(2.0, 3.0)


def test_map_inverted_roundtrips():
    tform = Transform([1.3, 0.2, 4.0, -0.1, 0.9, 2.5])
    fwd = tform.map(PTS)
    back = tform.map(fwd, inverted=True)
    for (bx, by), (ox, oy) in zip(back, PTS):
        assert bx == pytest.approx(ox, abs=1e-9)
        assert by == pytest.approx(oy, abs=1e-9)


@pytest.mark.parametrize("name,t", TFORMS, ids=[x[0] for x in TFORMS])
def test_map_points_array_matches_map(name, t):
    tform = Transform(list(t))
    ref = tform.map(PTS)
    arr = tform.mapPointsArray(PTS)
    assert arr.shape == (len(PTS), 2)
    for (rx, ry), (ax, ay) in zip(ref, arr.tolist()):
        assert ax == pytest.approx(rx, abs=1e-9)
        assert ay == pytest.approx(ry, abs=1e-9)


def test_map_points_array_empty():
    out = Transform([1, 0, 0, 0, 1, 0]).mapPointsArray([])
    assert out.shape == (0, 2)
