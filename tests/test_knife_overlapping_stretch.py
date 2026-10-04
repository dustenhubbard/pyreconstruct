"""A knife that runs along an open trace cuts at both ends of the shared stretch.

Where the knife lies on the trace for a stretch, shapely returns that stretch as
a line, not as points. `cut_open_trace` only looked for points, so the stretch
was skipped: a knife drawn along a straight edge cut nothing there, while the
same stroke a hair to one side cut at both ends. Pixel coordinates make the
exact case easy to hit on any horizontal or vertical edge.
"""

import pytest
from shapely.geometry import LineString

from PyReconstruct.modules.calc import cutTraces

U_TRACE = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]
# the bottom edge carries an extra vertex at (5, 0), inside the shared stretch
U_WITH_MIDPOINT = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]
ALONG_THEN_OUT = [(3.0, -1.0), (3.0, 0.0), (7.0, 0.0), (7.0, -1.0)]
SPLIT_AT_3_AND_7 = [
    [(0.0, 0.0), (3.0, 0.0)],
    [(3.0, 0.0), (7.0, 0.0)],
    [(7.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)],
]


def _rounded(pieces):
    return [[(round(x, 6), round(y, 6)) for x, y in p] for p in pieces]


def _assert_pieces_follow(trace, pieces):
    original = LineString(trace)
    total = sum(LineString(piece).length for piece in pieces)
    assert total == pytest.approx(original.length)
    for piece in pieces:
        assert original.buffer(1e-6).contains(LineString(piece))


def test_a_shared_stretch_cuts_at_both_ends():
    pieces = cutTraces([U_TRACE], ALONG_THEN_OUT, 0.0, closed=False)

    assert _rounded(pieces) == SPLIT_AT_3_AND_7
    _assert_pieces_follow(U_TRACE, pieces)


def test_a_shared_stretch_matches_a_stroke_just_beside_it():
    beside = [(3.0, -1.0), (3.0, 1e-9), (7.0, 1e-9), (7.0, -1.0)]

    on_edge = cutTraces([U_TRACE], ALONG_THEN_OUT, 0.0, closed=False)
    off_edge = cutTraces([U_TRACE], beside, 0.0, closed=False)

    assert _rounded(on_edge) == _rounded(off_edge)


def test_a_trace_vertex_inside_the_stretch_is_not_a_cut():
    pieces = cutTraces([U_WITH_MIDPOINT], ALONG_THEN_OUT, 0.0, closed=False)

    assert _rounded(pieces) == [
        [(0.0, 0.0), (3.0, 0.0)],
        [(3.0, 0.0), (5.0, 0.0), (7.0, 0.0)],
        [(7.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)],
    ]
    _assert_pieces_follow(U_WITH_MIDPOINT, pieces)


def test_a_shared_stretch_and_a_crossing_both_cut():
    knife = [(3.0, 0.0), (7.0, 0.0), (7.0, 6.0)]  # along the bottom, up through the top
    pieces = cutTraces([U_TRACE], knife, 0.0, closed=False)

    assert _rounded(pieces) == [
        [(0.0, 0.0), (3.0, 0.0)],
        [(3.0, 0.0), (7.0, 0.0)],
        [(7.0, 0.0), (10.0, 0.0), (10.0, 5.0), (7.0, 5.0)],
        [(7.0, 5.0), (0.0, 5.0)],
    ]
    _assert_pieces_follow(U_TRACE, pieces)


def test_a_clean_crossing_is_unchanged():
    pieces = cutTraces([U_TRACE], [(5.0, -1.0), (5.0, 1.0)], 0.0, closed=False)

    assert _rounded(pieces) == [
        [(0.0, 0.0), (5.0, 0.0)],
        [(5.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)],
    ]
