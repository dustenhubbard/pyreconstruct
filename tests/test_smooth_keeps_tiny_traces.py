"""Smoothing must not collapse a small trace into something that is not a trace.

A closed square 0.003 units on a side is smaller than the 0.004 interpolation
spacing `Series.smoothObject` uses, so interpolation returns only its first
point. `Trace.smooth` used to store that single point and report success, so
the trace was not listed as skipped and the next save dropped it from disk.
"""

import pytest

from PyReconstruct.modules.datatypes import Trace


def square(side, closed=True):
    trace = Trace("tiny", (255, 0, 0), closed=closed)
    trace.points = [
        (1.0, 1.0), (1.0 + side, 1.0), (1.0 + side, 1.0 + side), (1.0, 1.0 + side),
    ]
    return trace


@pytest.mark.parametrize("side", [0.0025, 0.003])
def test_tiny_closed_trace_is_left_unchanged(side):
    trace = square(side)
    before = list(trace.points)

    assert trace.smooth(window=10, spacing=0.004) is False
    assert trace.points == before


def test_a_normal_trace_is_still_smoothed():
    trace = square(0.01)

    assert trace.smooth(window=10, spacing=0.004) is True
    assert len(trace.points) >= 3


def test_smooth_object_keeps_and_reports_a_tiny_trace(real_series):
    series = real_series
    snum = sorted(series.sections)[0]
    section = series.loadSection(snum)
    trace = square(0.003)
    trace.name = "tiny_smooth_probe"
    before = list(trace.points)
    section.addTrace(trace, log_event=False)
    section.save()

    malformed = series.smoothObject(["tiny_smooth_probe"], log_event=False)

    assert [(r["name"], r["section"], r["points"], r["reason"]) for r in malformed] == [
        ("tiny_smooth_probe", snum, 4, "Too small to smooth"),
    ]

    reloaded = series.loadSection(snum).contours.get("tiny_smooth_probe")
    assert reloaded is not None, "the trace was deleted from disk"
    assert [
        [(round(x, 7), round(y, 7)) for x, y in t.points] for t in reloaded.traces
    ] == [[(round(x, 7), round(y, 7)) for x, y in before]]


# A closed square about four or five interpolation spacings around (0.004 to
# 0.005 on a side at spacing 0.004) used to come back as three points: a thin
# triangle stored in place of the square. Whether 0.005 collapses depends on
# rounding at the trace's position; at (1, 1) it does.
@pytest.mark.parametrize("side", [0.004, 0.0045, 0.005])
@pytest.mark.parametrize("window", [1, 5, 10, 20])
def test_small_closed_square_is_not_turned_into_a_triangle(side, window):
    trace = square(side)
    before = list(trace.points)

    assert trace.smooth(window=window, spacing=0.004) is False
    assert trace.points == before


def _pipeline(points, closed, window, spacing):
    """The smoothing pipeline Trace.smooth runs, without its size guards."""
    from PyReconstruct.modules.datatypes.points import Points

    smoothed = Points(points, closed).interp_rolling_average(
        spacing, window, as_int=False
    )
    if smoothed[0] == smoothed[-1]:
        smoothed = smoothed[:-1]
    return smoothed


def circle(radius, n=60):
    import math

    trace = Trace("round", (255, 0, 0), closed=True)
    trace.points = [
        (1.0 + radius * math.cos(2 * math.pi * k / n),
         1.0 + radius * math.sin(2 * math.pi * k / n))
        for k in range(n)
    ]
    return trace


@pytest.mark.parametrize("make", [
    lambda: square(0.01), lambda: square(0.5), lambda: circle(0.2),
])
@pytest.mark.parametrize("window", [5, 10])
def test_normal_trace_smooths_to_the_same_points_as_before(make, window):
    trace = make()
    expected = _pipeline(trace.points, True, window, 0.004)

    assert trace.smooth(window=window, spacing=0.004) is True
    assert trace.points == expected


def test_three_point_closed_trace_may_still_smooth_to_three_points():
    trace = Trace("tri", (255, 0, 0), closed=True)
    trace.points = [(1.0, 1.0), (1.005, 1.0), (1.0, 1.005)]
    expected = _pipeline(trace.points, True, 10, 0.004)

    assert len(expected) == 3
    assert trace.smooth(window=10, spacing=0.004) is True
    assert trace.points == expected
