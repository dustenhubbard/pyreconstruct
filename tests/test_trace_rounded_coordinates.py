"""`Trace.getList` writes every coordinate as `round(v, 7)`, bit for bit.

The rounding runs on numpy arrays for whole traces at once (it is most of
the time a section save takes). These tests hold the result to Python's own
`round(v, 7)`: same value, same type and the same bytes in the file, on
random values, on values next to a rounding tie, and on the inputs the fast
path hands back to `round` (ints, NaN, infinities, huge values).
"""
import math
import random

import numpy as np
import orjson
import pytest

from PyReconstruct.modules.datatypes.trace import Trace, roundedCoordinates


def _expected(points):
    return [round(p[0], 7) for p in points], [round(p[1], 7) for p in points]


def _same(got, want):
    """Equal values of equal types, signed zeros and NaN included."""
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert type(g) is type(w)
        if isinstance(w, float) and math.isnan(w):
            assert math.isnan(g)
        else:
            assert g == w and math.copysign(1, g) == math.copysign(1, w)
    assert orjson.dumps(got) == orjson.dumps(want)


def _check(points):
    got_x, got_y = roundedCoordinates(points)
    want_x, want_y = _expected(points)
    _same(got_x, want_x)
    _same(got_y, want_y)


@pytest.mark.parametrize("scale", [1e-6, 1e-3, 1, 10, 1e3, 1e5, 1e7])
def test_random_values_round_as_round_does(scale):
    rng = random.Random(1003)
    points = [
        (rng.uniform(-scale, scale), rng.uniform(-scale, scale))
        for _ in range(20000)
    ]
    _check(points)


def test_values_next_to_a_tie_round_as_round_does():
    # (k + 0.5) / 1e7 is a tie in decimal but not in binary: round() decides
    # it on the exact value, and the neighbors either side go the other way
    rng = random.Random(7)
    values = []
    for _ in range(5000):
        k = rng.randrange(-10 ** 11, 10 ** 11)
        tie = (k + 0.5) / 1e7
        values += [tie, np.nextafter(tie, math.inf), np.nextafter(tie, -math.inf)]
    values = [float(v) for v in values]
    points = list(zip(values[0::2], values[1::2]))
    _check(points)


def test_values_already_at_seven_places_are_kept():
    rng = random.Random(3)
    values = [rng.randrange(-10 ** 12, 10 ** 12) / 1e7 for _ in range(10000)]
    points = list(zip(values[0::2], values[1::2]))
    x, y = roundedCoordinates(points)
    assert x == values[0::2] and y == values[1::2]


def test_signed_zero_and_tiny_values():
    points = [(-0.0, 0.0), (-1e-9, 1e-9), (-4.9e-8, 5.1e-8), (-5e-8, 5e-8)]
    _check(points)


def test_inputs_round_handles_itself():
    big = 2.0 ** 60
    points = [
        (1, 2),                     # ints stay ints
        (3, 0.123456789),           # one int in the trace
        (math.nan, 1.5),
        (math.inf, -math.inf),
        (big, -big),
        (1e300, 0.5),
    ]
    for p in points:
        _check([p])
    _check(points)


def test_numpy_scalars_round_as_round_does():
    points = [(np.float64(0.123456789), np.float64(2.5e-8))]
    got_x, got_y = roundedCoordinates(points)
    want_x, want_y = _expected(points)
    assert got_x == want_x and got_y == want_y
    assert [type(v) for v in got_x] == [type(v) for v in want_x]


def test_no_points():
    assert roundedCoordinates([]) == ([], [])


def test_get_list_writes_the_same_row_as_before():
    rng = random.Random(11)
    points = [(rng.uniform(0, 50), rng.uniform(0, 50)) for _ in range(500)]
    trace = Trace("a", (255, 0, 0), closed=True)
    trace.points = points
    trace.tags = {"b", "a"}
    want = [
        "a",
        [round(p[0], 7) for p in points],
        [round(p[1], 7) for p in points],
        trace.color, trace.closed, trace.negative, trace.hidden,
        trace.fill_mode, ["a", "b"],
    ]
    assert orjson.dumps(trace.getList()) == orjson.dumps(want)
    assert orjson.dumps(trace.getList(include_name=False)) == orjson.dumps(want[1:])


def test_huge_and_not_finite_values_warn_nothing():
    import struct
    import warnings

    signaling = struct.unpack("<d", struct.pack("<Q", 0x7FF0000000000001))[0]
    points = [(1e302, 0.5), (-1.7e308, 2.5), (math.inf, math.nan), (signaling, 1.0)]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        got_x, got_y = roundedCoordinates(points)
    want_x, want_y = _expected(points)
    _same(got_x, want_x)
    _same(got_y, want_y)
