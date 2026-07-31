"""A trace the knife cannot cut must survive the attempt.

`cut_closed_traces` builds `Polygon(trace)` and computes a difference against
the cut line, which needs a polygon shapely will accept. It did not get one for
two kinds of trace, and in both cases it dropped the trace from its result with
`continue`:

  * an outline that crosses itself (a freehand loop doubled back on, a figure
    eight). `Polygon.is_valid` is False.
  * a contour of fewer than three points. `Polygon()` raises outright, so this
    one surfaced as an error dialog rather than a loss.

Dropping is the wrong disposal because of what the one caller in the field does
with the result. `FieldWidgetTrace.cutTrace` deletes the selected traces and
*then* recreates one trace per returned piece, so a result missing a trace means
the object was deleted and nothing came back. Freehand tracing produces
self-intersecting outlines routinely, which is how a cut could destroy an object
outright.

The floor here is that this function never returns fewer closed traces than it
was given. The refusal a user sees is one level up, in `cutTrace`, driven by
`uncuttable_closed_traces`, so the object is never touched at all; these tests
cover the pure geometry underneath it. No Qt: `cutTraces` takes plain lists.
"""
import pytest

from PyReconstruct.modules.calc.grid import cutTraces
from PyReconstruct.modules.calc.polygon import (
    cut_closed_traces,
    uncuttable_closed_traces,
)

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]

# the diagonals of a square, taken in an order that makes the outline cross
# itself in the middle. Polygon(BOWTIE).is_valid is False.
BOWTIE = [(0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0)]

TWO_POINTS = [(0.0, 0.0), (10.0, 10.0)]

# a cut line that runs clear across the square, well outside it at both ends
ACROSS = [(-1.0, 5.0), (11.0, 5.0)]


# --- the predicate ------------------------------------------------------------

def test_a_valid_polygon_is_cuttable():
    assert uncuttable_closed_traces([SQUARE]) == []


def test_a_self_intersecting_outline_is_uncuttable():
    assert uncuttable_closed_traces([BOWTIE]) == [0]


def test_a_two_point_contour_is_uncuttable():
    """Fewer than three points. `Polygon()` would raise, so this is checked
    before shapely sees it."""
    assert uncuttable_closed_traces([TWO_POINTS]) == [0]


def test_every_offending_index_is_reported():
    """A selection can hold more than one trace, and the caller refuses the
    whole selection, so the predicate reports all of them rather than the
    first."""
    assert uncuttable_closed_traces([SQUARE, BOWTIE, SQUARE, TWO_POINTS]) == [1, 3]


def test_an_empty_selection_is_cuttable():
    assert uncuttable_closed_traces([]) == []


# --- the floor under it -------------------------------------------------------

def test_a_self_intersecting_trace_is_kept_not_dropped():
    """The bug, at the level it was introduced. The trace used to vanish."""
    result = cut_closed_traces([BOWTIE], ACROSS, 0.0)

    assert result == [BOWTIE], "the uncuttable trace was dropped from the result"


def test_a_two_point_trace_is_kept_and_does_not_raise():
    """`Polygon()` on two points raises GEOSException. It must not be reached."""
    result = cut_closed_traces([TWO_POINTS], ACROSS, 0.0)

    assert result == [TWO_POINTS]


def test_an_uncuttable_trace_does_not_take_its_neighbors_with_it():
    """A mixed list: the cuttable trace is still cut, the other is preserved.

    Pins the loop, not just the single-trace case. The square is bisected into
    two pieces and the bowtie comes back whole, so the result is three traces.
    """
    result = cut_closed_traces([SQUARE, BOWTIE], ACROSS, 0.0)

    assert len(result) == 3
    assert BOWTIE in result


def test_cut_traces_returns_the_uncuttable_trace_rather_than_nothing():
    """Through the public entry point. An empty result is what deletes an
    object, so the thing to assert is that this is not empty."""
    result = cutTraces([BOWTIE], ACROSS, 0.0, closed=True)

    assert result == [BOWTIE]


# --- guardrails: none of the above may change a valid cut ---------------------

def test_a_valid_cut_still_splits_a_square():
    result = cutTraces([SQUARE], ACROSS, 0.0, closed=True)

    assert len(result) == 2


def test_a_cut_that_misses_still_returns_the_trace_unchanged():
    result = cutTraces([SQUARE], [(100.0, 100.0), (200.0, 200.0)], 0.0, closed=True)

    assert result == [SQUARE]


@pytest.mark.parametrize("trace_list", [[SQUARE], [BOWTIE], [TWO_POINTS], [SQUARE, BOWTIE]])
def test_a_closed_cut_never_returns_fewer_traces_than_it_was_given(trace_list):
    """The invariant, stated once. Pieces may multiply; traces may not vanish.

    With `del_threshold` at 0 nothing is discarded for being small, so any
    shortfall here is a trace that was dropped rather than cut.
    """
    result = cut_closed_traces(trace_list, ACROSS, 0.0)

    assert len(result) >= len(trace_list)
