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
