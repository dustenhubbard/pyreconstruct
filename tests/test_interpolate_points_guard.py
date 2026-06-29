"""Regression test for interpolate_points on degenerate input.

interpolate_points did ``x, y = zip(*points)`` with no guard, so an empty point
list raised ValueError ("not enough values to unpack"). This is reachable from
the knife tool with rolling-average smoothing on: a single-click scalpel trace
is collapsed by Points to an empty list and then handed to interpolate_points,
crashing the uncaught field interaction. A path needs at least two points to
interpolate, so fewer is a no-op returning an empty path.
"""
from PyReconstruct.modules.calc.quantification import interpolate_points


def test_empty_points_returns_empty():
    assert interpolate_points([]) == []  # previously raised ValueError


def test_single_point_returns_empty():
    assert interpolate_points([(5.0, 7.0)]) == []


def test_valid_path_still_interpolates():
    result = interpolate_points([(0.0, 0.0), (10.0, 0.0)], spacing=1.0)
    assert len(result) == 10
    assert result[0] == (0.0, 0.0)
    assert result[-1] == (10.0, 0.0)
