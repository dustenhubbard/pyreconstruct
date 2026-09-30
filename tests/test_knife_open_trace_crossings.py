"""A knife cut across an open trace splits it only where the knife crosses it.

`cut_at_points` used to apply every crossing to every piece it had made so far.
`cut_at_point` projects the crossing onto the piece whether or not the piece
passes through it, so a piece that did not contain the crossing was joined to it
by a new edge. Cutting a U-shaped trace with one knife stroke across both arms
gave four pieces, one of them a diagonal that was never drawn, and the pieces
were longer in total than the trace. cutTraces takes plain lists, so this is
tested directly with no Qt.
"""

import pytest
from shapely.geometry import LineString

from PyReconstruct.modules.calc import cutTraces

U_TRACE = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]
ACROSS_BOTH_ARMS = [(8.0, -1.0), (2.0, 6.0)]
ZIGZAG = [(0.0, 0.0), (10.0, 0.0), (10.0, 2.0), (0.0, 2.0), (0.0, 4.0), (10.0, 4.0)]
DOWN_THE_MIDDLE = [(5.0, -1.0), (5.0, 5.0)]


def _rounded(piece):
    return [(round(x, 6), round(y, 6)) for x, y in piece]


def _assert_pieces_follow(trace, pieces):
    original = LineString(trace)
    total = sum(LineString(piece).length for piece in pieces)
    assert total == pytest.approx(original.length)
    for piece in pieces:
        segment = LineString(piece)
        # every edge of every piece lies on the original trace
        assert original.buffer(1e-6).contains(segment)


def test_two_crossings_give_three_pieces_along_the_trace():
    pieces = cutTraces([U_TRACE], ACROSS_BOTH_ARMS, 0.0, closed=False)

    assert [_rounded(p) for p in pieces] == [
        [(0.0, 0.0), (7.142857, 0.0)],
        [(7.142857, 0.0), (10.0, 0.0), (10.0, 5.0), (2.857143, 5.0)],
        [(2.857143, 5.0), (0.0, 5.0)],
    ]
    _assert_pieces_follow(U_TRACE, pieces)


def test_three_crossings_give_four_pieces_along_the_trace():
    pieces = cutTraces([ZIGZAG], DOWN_THE_MIDDLE, 0.0, closed=False)

    assert len(pieces) == 4
    _assert_pieces_follow(ZIGZAG, pieces)
    crossings = {(5.0, 0.0), (5.0, 2.0), (5.0, 4.0)}
    ends = {pt for p in pieces for pt in (_rounded(p)[0], _rounded(p)[-1])}
    assert crossings <= ends


def test_a_single_crossing_still_gives_two_pieces():
    pieces = cutTraces([U_TRACE], [(5.0, -1.0), (5.0, 1.0)], 0.0, closed=False)

    assert [_rounded(p) for p in pieces] == [
        [(0.0, 0.0), (5.0, 0.0)],
        [(5.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)],
    ]


def test_a_crossing_at_a_vertex_splits_there():
    knife = [(12.0, 7.0), (8.0, 3.0), (2.0, -3.0)]  # through (10, 5) and (5, 0)
    pieces = cutTraces([U_TRACE], knife, 0.0, closed=False)

    _assert_pieces_follow(U_TRACE, pieces)
    assert [_rounded(p) for p in pieces] == [
        [(0.0, 0.0), (5.0, 0.0)],
        [(5.0, 0.0), (10.0, 0.0), (10.0, 5.0)],
        [(10.0, 5.0), (0.0, 5.0)],
    ]


def test_the_threshold_still_drops_short_pieces():
    # the last piece is 2.86 of 25, under 20 percent; the first is 7.14, over it
    pieces = cutTraces([U_TRACE], ACROSS_BOTH_ARMS, 20.0, closed=False)

    assert [_rounded(p) for p in pieces] == [
        [(0.0, 0.0), (7.142857, 0.0)],
        [(7.142857, 0.0), (10.0, 0.0), (10.0, 5.0), (2.857143, 5.0)],
    ]
