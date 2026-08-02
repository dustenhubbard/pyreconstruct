"""Pin the argument contract of ``Points.__add__``.

The check used to read ``isinstance(other_points, tuple or list)``. Python
evaluates ``tuple or list`` to ``tuple`` before isinstance runs, so the branch
was always tuple-only. That spelling is wrong -- it names ``list`` and then
ignores it -- but the behaviour it produced is the one the module's own type
aliases ask for: ``Point = Tuple[Coordinate, Coordinate]`` and
``PointSeq = List[Point]``, so a tuple is one point and a list is a sequence of
points. The check now reads ``isinstance(other_points, tuple)``, which says the
same thing on purpose. No argument shape changes behaviour.

These tests exist to stop the obvious "tidy-up" -- rewriting the check to
``isinstance(other_points, (tuple, list))`` -- which looks like a fix for the
bad spelling but routes every list to ``append``, so a ``PointSeq`` gets nested
inside the coordinate list as though it were one point.
``test_add_point_seq_extends`` is the test that catches that.

``__add__`` is annotated ``-> None`` and mutates in place, so the only call form
that works is the bare statement ``p + x``; ``p = p + x`` would rebind ``p`` to
None. That is a separate design wart, tracked separately, not touched here.
"""
from PyReconstruct.modules.datatypes.points import Points


def test_add_tuple_appends_as_one_point():
    # Point is a Tuple, so a tuple argument is a single point.
    p = Points([(0, 0), (1, 1)], closed=False)
    p + (2, 2)
    assert p.points == [(0, 0), (1, 1), (2, 2)]


def test_add_point_seq_extends():
    # PointSeq is a List[Point], so a list argument is a sequence of points and
    # extends. This is the case that breaks if the check is widened to
    # (tuple, list): the whole list would be appended as one nested element.
    p = Points([(0, 0), (1, 1)], closed=False)
    p + [(3, 3), (4, 4)]
    assert p.points == [(0, 0), (1, 1), (3, 3), (4, 4)]


def test_add_single_point_written_as_a_list_is_not_a_point():
    # Documents the sharp edge rather than papering over it. A list is read as
    # a sequence, so [2, 2] is read as two malformed points and splices two
    # bare scalars in. One point must be written as a tuple.
    p = Points([(0, 0), (1, 1)], closed=False)
    p + [2, 2]
    assert p.points == [(0, 0), (1, 1), 2, 2]


def test_add_tuple_of_points_is_appended_whole():
    # The mirror sharp edge, unchanged by any spelling of the check: a tuple is
    # always one point, so a tuple *of* points nests rather than extending.
    p = Points([(0, 0), (1, 1)], closed=False)
    p + ((3, 3), (4, 4))
    assert p.points == [(0, 0), (1, 1), ((3, 3), (4, 4))]
