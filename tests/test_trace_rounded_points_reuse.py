"""A trace's rounded points are reused while its points are the same objects.

Once a series has an edit, every section change saves the section it leaves
and the B section, which the step before saved as the section left. Rounding
every point was most of that save, so `Trace.getList` keeps a trace's
rounded values with the point tuples they came from and uses them again only
when the points list holds the very same tuples. What it writes must be what
`roundedCoordinates` gives for the points as they are now, through every way
a trace's points change.
"""
import math
import random

import numpy as np
import orjson
import pytest

from PyReconstruct.modules.constants.fast_json import fast_dumps
from PyReconstruct.modules.datatypes import trace as trace_module
from PyReconstruct.modules.datatypes.trace import Trace, roundedCoordinates


def _trace(rng, n=40):
    trace = Trace("reuse", (255, 0, 0))
    trace.points = [(rng.uniform(-50, 50), rng.uniform(-50, 50)) for _ in range(n)]
    return trace


def _fresh(trace):
    x, y = roundedCoordinates(trace.points)
    return orjson.dumps([x, y], option=orjson.OPT_SERIALIZE_NUMPY)


def _written(trace):
    row = trace.getList(include_name=False)
    return orjson.dumps(row[:2], option=orjson.OPT_SERIALIZE_NUMPY)


@pytest.fixture
def rounds(monkeypatch):
    # every rounding of a list of points starts here, whichever path it takes
    calls = []
    real = trace_module._roundedFloatPairs

    def counted(points):
        calls.append(len(points))
        return real(points)
    monkeypatch.setattr(trace_module, "_roundedFloatPairs", counted)
    return calls


def test_unchanged_points_are_not_rounded_again(rounds):
    trace = _trace(random.Random(1))
    first = trace.getList()
    second = trace.getList()
    assert first == second
    assert rounds == [40]


def test_each_row_gets_lists_of_its_own():
    trace = _trace(random.Random(2))
    first = trace.getList(include_name=False)
    first[0].append(99.0)
    first[1][0] = 99.0
    second = trace.getList(include_name=False)
    assert second == list(roundedCoordinates(trace.points)) + second[2:]
    assert len(second[0]) == 40 and second[1][0] != 99.0


def test_a_point_replaced_in_place_is_rounded_again():
    rng = random.Random(3)
    trace = _trace(rng)
    trace.getList()
    x, y = trace.points[5]
    trace.points[5] = (x + 1e-3, y)
    assert _written(trace) == _fresh(trace)


def test_an_equal_point_of_another_sign_or_type_is_written_as_it_is():
    # equal values that write other bytes: only the same objects are reused
    trace = Trace("reuse", (255, 0, 0))
    trace.points = [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]
    trace.getList()
    trace.points[0] = (-0.0, 1.0)
    assert _written(trace) == _fresh(trace)
    assert _written(trace).startswith(b"[[-0.0")
    trace.points[1] = (2, 3.0)
    assert _written(trace) == _fresh(trace)
    trace.points[2] = (np.float64(4.0), 5.0)
    assert _written(trace) == _fresh(trace)


@pytest.mark.parametrize("change", [
    lambda t: t.points.append((1.25, 2.5)),
    lambda t: t.points.pop(),
    lambda t: t.points.insert(0, t.points[-1]),
    lambda t: t.points.reverse(),
    lambda t: t.points.__setitem__(slice(0, 2), t.points[2:4]),
    lambda t: setattr(t, "points", list(t.points)),
    lambda t: setattr(t, "points", [(x + 1.0, y) for x, y in t.points]),
    lambda t: setattr(t, "points", []),
    lambda t: setattr(t, "points", [list(p) for p in t.points]),
])
def test_every_change_writes_what_rounding_now_gives(change):
    trace = _trace(random.Random(4))
    trace.getList()
    change(trace)
    assert _written(trace) == _fresh(trace)
    assert _written(trace) == _fresh(trace)


def test_random_edits_always_write_what_rounding_now_gives():
    rng = random.Random(1003)
    traces = [_trace(rng, rng.randrange(1, 60)) for _ in range(30)]
    for _ in range(400):
        trace = rng.choice(traces)
        what = rng.randrange(5)
        if what == 0 and trace.points:
            i = rng.randrange(len(trace.points))
            x, y = trace.points[i]
            trace.points[i] = (x + rng.choice([0.0, 1e-9, 1e-7, 1.0]), y)
        elif what == 1:
            trace.points.append((rng.uniform(-9, 9), rng.uniform(-9, 9)))
        elif what == 2 and trace.points:
            del trace.points[rng.randrange(len(trace.points))]
        elif what == 3:
            k = rng.randrange(-10 ** 9, 10 ** 9)
            tie = (k + 0.5) / 1e7
            trace.points = trace.points + [(tie, float(np.nextafter(tie, math.inf)))]
        assert _written(trace) == _fresh(trace)


def test_points_not_all_float_pairs_are_written_as_before():
    for points in ([(1, 2), (3, 4)], [(0.5, 1.5, 2.5)], [(math.nan, math.inf)]):
        trace = Trace("reuse", (0, 0, 255))
        trace.points = points
        assert _written(trace) == _fresh(trace)
        assert _written(trace) == _fresh(trace)


@pytest.fixture
def section(real_series):
    n = next(
        n for n in sorted(real_series.sections)
        if real_series.loadSection(n).tracesAsList()
    )
    return real_series.loadSection(n)


def test_a_second_save_of_an_unchanged_section_writes_the_same_bytes(section, rounds):
    first = fast_dumps(section.getDict())
    traces = len(section.tracesAsList())
    assert len(rounds) == traces
    second = fast_dumps(section.getDict())
    assert second == first
    assert len(rounds) == traces


def test_a_section_writes_what_rounding_each_trace_now_gives(section, monkeypatch):
    rng = random.Random(5)
    section.getDict()
    traces = section.tracesAsList()
    for trace in rng.sample(traces, min(3, len(traces))):
        x, y = trace.points[0]
        trace.points[0] = (x + 0.5, y)
    reused = fast_dumps(section.getDict())
    monkeypatch.setattr(Trace, "_roundedPoints", lambda t: roundedCoordinates(t.points))
    assert fast_dumps(section.getDict()) == reused


def test_points_held_in_lists_are_never_reused():
    # a list can change in place, so a trace whose points are lists is
    # rounded again on every save
    trace = Trace("reuse", (0, 0, 255))
    trace.points = [[0.5, 1.5], [2.5, 3.5], [4.5, 5.5]]
    trace.getList()
    trace.points[0][0] = 9.0
    assert _written(trace) == _fresh(trace)
    assert _written(trace).startswith(b"[[9.0")
