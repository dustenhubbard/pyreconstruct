"""A section save rounds the points of all its traces in one pass.

`Section.getDict` used to round each trace's points on its own, which on a
section of thousands of small traces was most of a save. It now rounds them
together. The rows must not change: the same values, the same types and the
same bytes as rounding each trace on its own, in both row shapes.
"""
import math
import random

import numpy as np
import orjson
import pytest

from PyReconstruct.modules.datatypes import section as section_module
from PyReconstruct.modules.datatypes import trace as trace_module
from PyReconstruct.modules.datatypes.section import fast_dumps
from PyReconstruct.modules.datatypes.trace import (
    Trace,
    roundedCoordinates,
    roundedCoordinatesOfMany,
)


def _one_by_one(point_lists):
    return [roundedCoordinates(p) for p in point_lists]


def _same(got, want):
    """Equal values of equal types, signed zeros and NaN included."""
    assert len(got) == len(want)
    for (gx, gy), (wx, wy) in zip(got, want):
        for g_list, w_list in ((gx, wx), (gy, wy)):
            assert len(g_list) == len(w_list)
            for g, w in zip(g_list, w_list):
                assert type(g) is type(w)
                if isinstance(w, float) and math.isnan(w):
                    assert math.isnan(g)
                else:
                    assert g == w and math.copysign(1, g) == math.copysign(1, w)
    numpy = orjson.OPT_SERIALIZE_NUMPY
    assert orjson.dumps(got, option=numpy) == orjson.dumps(want, option=numpy)


def _random_lists(seed, n=400):
    rng = random.Random(seed)
    lists = []
    for _ in range(n):
        scale = rng.choice([1e-6, 1e-3, 1, 50, 1e5])
        lists.append([
            (rng.uniform(-scale, scale), rng.uniform(-scale, scale))
            for _ in range(rng.choice([0, 1, 2, 3, 17, 120]))
        ])
    # values next to a rounding tie, and values already at seven places
    for _ in range(50):
        k = rng.randrange(-10 ** 11, 10 ** 11)
        tie = (k + 0.5) / 1e7
        lists.append([
            (tie, float(np.nextafter(tie, math.inf))),
            (float(np.nextafter(tie, -math.inf)), k / 1e7),
        ])
    return lists


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_many_lists_round_as_each_list_does(seed):
    lists = _random_lists(seed)
    _same(roundedCoordinatesOfMany(lists), _one_by_one(lists))


@pytest.mark.parametrize("odd", [
    [(1, 2)],                                  # ints stay ints
    [(np.float64(0.123456789), 2.5e-8)],       # a numpy scalar
    [(1.0, 2.0, 3.0)],                         # not a pair
    [(math.nan, 1.5), (math.inf, -math.inf)],  # not finite (floats: one pass)
    [(2.0 ** 60, 1e300)],                      # too large for the fast path
])
def test_an_odd_list_among_many_rounds_as_on_its_own(odd):
    lists = _random_lists(4, n=40)
    lists.insert(7, odd)
    _same(roundedCoordinatesOfMany(lists), _one_by_one(lists))


def test_no_lists_and_empty_lists():
    assert roundedCoordinatesOfMany([]) == []
    assert roundedCoordinatesOfMany([[], []]) == [([], []), ([], [])]


@pytest.fixture
def section(real_series):
    n = next(
        n for n in sorted(real_series.sections)
        if real_series.loadSection(n).tracesAsList()
    )
    section = real_series.loadSection(n)
    for i, points in enumerate(_random_lists(5, n=200)):
        if not points:
            continue
        trace = Trace(f"round-once-{i % 23}", (255, i % 256, 0), i % 3 != 0)
        trace.points = points
        trace.tags = {"b", "a"} if i % 5 == 0 else set()
        section.addTrace(trace)
    # one trace that is not all floats, in the middle of the order
    odd = Trace("round-once-11", (0, 0, 255))
    odd.points = [(1, 2), (3.25, 0.123456789), (4, 5)]
    section.addTrace(odd)
    return section


@pytest.mark.parametrize("keyed", [False, True])
def test_section_rows_are_the_same_bytes(section, monkeypatch, keyed):
    new = fast_dumps(section.getDict(keyed_rows=keyed))
    monkeypatch.setattr(section_module, "roundedCoordinatesOfMany", _one_by_one)
    old = fast_dumps(section.getDict(keyed_rows=keyed))
    assert new == old
    rows = orjson.loads(new)["contours"]["round-once-11"]
    assert len(rows) > 1


def test_a_save_rounds_every_trace_in_one_pass(section, monkeypatch):
    calls = []
    real = trace_module.roundedCoordinates

    def counted(points):
        calls.append(len(points))
        return real(points)
    monkeypatch.setattr(trace_module, "roundedCoordinates", counted)
    # without the odd trace every point is a float pair: no list on its own
    section.removeTrace(
        next(t for t in section.contours["round-once-11"] if t.points[0] == (1, 2))
    )
    section.getDict()
    assert calls == []
