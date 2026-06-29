"""Regression test for a single-point ("knife single-click") cut line.

cutTraces guarded an empty cut line (``not cut_trace``) but not a degenerate
single-point one. A 1-point list is truthy, so it fell through to
cut_closed_traces / cut_open_traces, which build ``LineString(cut_trace)`` --
shapely raises GEOSException ("point array must contain 0 or >1 elements") for
a 1-point array.

This is reachable from the knife tool: knifePress seeds the current trace with
one point and, on a press-release with no intervening drag (a single click),
knifeRelease passes that single-point list straight to cutTraces. The field
interaction wrapper has no try/except, so the harmless click surfaced an error
dialog instead of being a no-op. cutTraces takes plain lists, so this is tested
directly with no Qt.
"""
import pytest

from PyReconstruct.modules.calc.grid import cutTraces

SQUARE = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
OPEN_LINE = [[(0.0, 0.0), (0.0, 10.0), (10.0, 10.0)]]


def test_single_point_cut_closed_is_noop():
    # must not raise GEOSException; a degenerate cut leaves the traces unchanged
    assert cutTraces(SQUARE, [(5.0, 5.0)], 0.0, closed=True) == SQUARE


def test_single_point_cut_open_is_noop():
    assert cutTraces(OPEN_LINE, [(5.0, 5.0)], 0.0, closed=False) == OPEN_LINE


def test_empty_cut_is_noop():
    assert cutTraces(SQUARE, [], 0.0, closed=True) == SQUARE


def test_valid_two_point_cut_still_splits():
    """A real (>= 2 point) cut line must still bisect the trace -- the guard
    must not change behavior for valid input."""
    result = cutTraces(SQUARE, [(5.0, -1.0), (5.0, 11.0)], 0.0, closed=True)
    assert len(result) == 2
