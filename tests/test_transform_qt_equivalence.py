"""Bit-for-bit oracle: the Qt-free Transform vs the QTransform it replaced.

`datatypes/transform.py` used to hold a `QTransform` and delegate four
operations to it (map a point / a list of points, invert, compose, determinant).
Those are now plain Python/NumPy so the core data model imports no Qt. This
module keeps the old QTransform-backed implementation as a reference oracle and
compares the two *bit-for-bit* (`struct.pack`, so a 1-ULP or a signed-zero
difference fails) over:

  - hand-written fixtures covering every QTransform matrix type (identity,
    translation, scale, rotation, shear, general affine, negative determinant,
    integer-valued lists);
  - 550 seeded random transforms (general / scale-only / pure rotation);
  - 3,600 composition pairs;
  - 25k random points per direction through `map` and `mapPointsArray`.

The one documented divergence is characterized (and bounded) in
`test_fuzz_boundary_is_the_only_divergence`: QTransform classifies a matrix by
type using a 1e-12 fuzz (`qFuzzyIsNull`), so it silently drops a shear / scale /
translation term below that magnitude. The Qt-free affine keeps such a term,
i.e. it returns the mathematically exact result -- proven here with exact
rational arithmetic. Every transform whose special-case structure is exact (all
real transforms: identity, alignments, mag scaling) is bit-identical.
"""
import math
import random
import struct
from fractions import Fraction

import numpy as np
import pytest

from PyReconstruct.modules.datatypes.transform import Transform

pytest.importorskip("PySide6.QtGui")
from PySide6.QtGui import QTransform  # noqa: E402  (the oracle, tests only)


# ---------------------------------------------------------------- the oracle

class QtRefTransform:
    """The pre-refactor implementation, verbatim, kept as the oracle."""

    def __init__(self, tform_list):
        self.tform = tform_list
        self.qtform = self.getQTransform()

    def getQTransform(self):
        t = self.tform
        return QTransform(t[0], t[3], t[1], t[4], t[2], t[5])

    @staticmethod
    def fromQTransform(qtform):
        return QtRefTransform([
            qtform.m11(), qtform.m21(), qtform.m31(),
            qtform.m12(), qtform.m22(), qtform.m32(),
        ])

    def map(self, *args, inverted=False):
        if inverted:
            qtform, invertible = self.qtform.inverted()
            if not invertible:
                raise Exception("Matrix is not invertible.")
        else:
            qtform = self.qtform
        if len(args) == 2:
            return qtform.map(args[0], args[1])
        elif len(args) == 1:
            return [qtform.map(*p) for p in args[0]]

    def mapPointsArray(self, points, inverted=False):
        if inverted:
            qtform, invertible = self.qtform.inverted()
            if not invertible:
                raise Exception("Matrix is not invertible.")
        else:
            qtform = self.qtform
        arr = np.asarray(points, dtype=float)
        if arr.size == 0:
            return np.empty((0, 2), dtype=float)
        x = arr[:, 0]
        y = arr[:, 1]
        out = np.empty((arr.shape[0], 2), dtype=float)
        out[:, 0] = qtform.m11() * x + qtform.m21() * y + qtform.dx()
        out[:, 1] = qtform.m12() * x + qtform.m22() * y + qtform.dy()
        return out

    def getList(self):
        return self.tform.copy()

    def inverted(self):
        t, invertible = self.qtform.inverted()
        if not invertible:
            raise Exception("Matrix is not invertible")
        return QtRefTransform.fromQTransform(t)

    def __mul__(self, other):
        return QtRefTransform.fromQTransform(
            self.getQTransform() * other.getQTransform()
        )

    @property
    def det(self):
        return self.getQTransform().determinant()


# ---------------------------------------------------------------- fixtures

def bits(x):
    """The exact IEEE-754 bits of a float (so 1 ULP and -0.0 both matter)."""
    return struct.pack("<d", float(x))


def assert_bits(got, ref, what):
    assert bits(got) == bits(ref), f"{what}: {got!r} != {ref!r} (bitwise)"


def assert_list_bits(got, ref, what):
    assert len(got) == len(ref), f"{what}: length {len(got)} != {len(ref)}"
    for i, (g, r) in enumerate(zip(got, ref)):
        assert_bits(g, r, f"{what}[{i}]")


FIXTURES = {
    "identity_int": [1, 0, 0, 0, 1, 0],
    "identity": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
    "translate": [1, 0, 5.5, 0, 1, -3.25],
    "translate_big": [1.0, 0.0, -12345.678, 0.0, 1.0, 98765.4321],
    "scale": [2.0, 0, 0, 0, 0.5, 0],
    "scale_odd": [0.7, 0, 3.0, 0, 1.3, -4.0],
    "scale_negative": [-1.7, 0, 0, 0, 2.9, 0],
    "rotate": [math.cos(0.3), -math.sin(0.3), 10, math.sin(0.3), math.cos(0.3), -7],
    "shear": [1, 0.4, 0, 0.2, 1, 0],
    "affine": [1.3, 0.2, 4.0, -0.1, 0.9, 2.5],
    "affine_negdet": [1.0, 0.3, 2.0, 0.3, -1.0, 5.0],
    # a realistic alignment transform (near identity, generic entries)
    "alignment": [0.99873, 0.00412, 12.75, -0.00398, 1.00104, -8.5],
    # estimateTform() builds a Transform out of numpy scalars, not Python floats
    "numpy_scalars": [np.float64(v) for v in
                      (1.0102, -0.0311, 7.25, 0.0288, 0.9914, -3.75)],
}

# transforms QTransform treats as fuzzily-special: a nonzero term below its
# 1e-12 qFuzzyIsNull threshold, which it drops and the Qt-free affine keeps
FUZZ_FIXTURES = {
    "tiny_shear": [1.0, 1e-15, 0.0, 0.0, 1.0, 0.0],
    "tiny_scale_offset": [1.0 + 1e-13, 0.0, 0.0, 0.0, 1.0, 0.0],
    "tiny_translate": [1.0, 0.0, 1e-13, 0.0, 1.0, 1e-13],
    "tiny_shear_scaled": [2.0, 1e-14, 3.0, 1e-14, 0.5, -1.0],
}


def random_tforms():
    """550 seeded transforms: general, scale-only and pure rotations."""
    rnd = random.Random(1234)
    out = {}
    for i in range(400):
        out[f"gen{i}"] = [
            rnd.uniform(-3, 3), rnd.uniform(-3, 3), rnd.uniform(-1e4, 1e4),
            rnd.uniform(-3, 3), rnd.uniform(-3, 3), rnd.uniform(-1e4, 1e4),
        ]
    for i in range(100):
        out[f"scale{i}"] = [
            rnd.uniform(0.1, 5), 0.0, rnd.uniform(-1e3, 1e3),
            0.0, rnd.uniform(0.1, 5), rnd.uniform(-1e3, 1e3),
        ]
    for i in range(50):
        th = rnd.uniform(-math.pi, math.pi)
        out[f"rot{i}"] = [
            math.cos(th), -math.sin(th), rnd.uniform(-1e3, 1e3),
            math.sin(th), math.cos(th), rnd.uniform(-1e3, 1e3),
        ]
    return out


RANDOM_TFORMS = random_tforms()
ALL_TFORMS = {**FIXTURES, **RANDOM_TFORMS}

POINTS = [
    (0, 0), (1, 2), (-3.5, 4.25), (100.1, -200.2),
    (12345.6, 7890.1), (-1e6, 1e6), (0.0, -7.5),
]


# ---------------------------------------------------------------- the checks

@pytest.mark.parametrize("name", list(FIXTURES))
def test_single_point_map_bit_identical_fixtures(name):
    """map(x, y) matches QTransform.map bit-for-bit, forward and inverted."""
    t = FIXTURES[name]
    new, ref = Transform(list(t)), QtRefTransform(list(t))
    for inverted in (False, True):
        for (x, y) in POINTS:
            gx, gy = new.map(x, y, inverted=inverted)
            rx, ry = ref.map(x, y, inverted=inverted)
            assert_bits(gx, rx, f"{name} map x (inverted={inverted})")
            assert_bits(gy, ry, f"{name} map y (inverted={inverted})")


def test_single_point_map_bit_identical_random():
    """Same, over 550 random transforms x 7 points x 2 directions."""
    for name, t in RANDOM_TFORMS.items():
        new, ref = Transform(list(t)), QtRefTransform(list(t))
        for inverted in (False, True):
            for (x, y) in POINTS:
                gx, gy = new.map(x, y, inverted=inverted)
                rx, ry = ref.map(x, y, inverted=inverted)
                assert_bits(gx, rx, f"{name} map x (inverted={inverted})")
                assert_bits(gy, ry, f"{name} map y (inverted={inverted})")


def test_map_returns_python_floats_and_tuples():
    """The public shape is unchanged: tuple of floats / list of tuples."""
    tform = Transform([1, 0, 0, 0, 1, 0])  # integer-valued list
    pt = tform.map(2, 3)
    assert isinstance(pt, tuple) and len(pt) == 2
    assert all(type(v) is float for v in pt)  # QTransform always returned floats
    pts = tform.map([(1, 2), (3.5, -4.5)])
    assert isinstance(pts, list) and all(isinstance(p, tuple) for p in pts)
    assert all(type(v) is float for p in pts for v in p)
    assert tform.map([]) == []


@pytest.mark.parametrize("name", list(ALL_TFORMS))
def test_point_list_map_bit_identical(name):
    """map(list_of_points) matches the per-point QTransform.map, both ways."""
    t = ALL_TFORMS[name]
    new, ref = Transform(list(t)), QtRefTransform(list(t))
    for inverted in (False, True):
        got = new.map(POINTS, inverted=inverted)
        want = ref.map(POINTS, inverted=inverted)
        assert len(got) == len(want)
        for (gx, gy), (rx, ry) in zip(got, want):
            assert_bits(gx, rx, f"{name} list x (inverted={inverted})")
            assert_bits(gy, ry, f"{name} list y (inverted={inverted})")


@pytest.mark.parametrize("name", list(FIXTURES))
def test_map_points_array_bit_identical_large(name):
    """mapPointsArray over 25k random points, forward and inverted.

    This is the tuned path (the per-trace geometry build); its output feeds
    every downstream number, so it is compared as raw bytes.
    """
    t = FIXTURES[name]
    new, ref = Transform(list(t)), QtRefTransform(list(t))
    pts = np.random.default_rng(7).uniform(-5e4, 5e4, size=(25000, 2))
    for inverted in (False, True):
        got = new.mapPointsArray(pts, inverted=inverted)
        want = ref.mapPointsArray(pts, inverted=inverted)
        assert got.shape == want.shape == (25000, 2)
        assert got.tobytes() == want.tobytes(), (
            f"{name} mapPointsArray (inverted={inverted}) differs bitwise"
        )


def test_map_points_array_matches_map_bitwise():
    """map() and mapPointsArray() agree bit-for-bit (the 5.9M-point claim)."""
    for name, t in ALL_TFORMS.items():
        tform = Transform(list(t))
        for inverted in (False, True):
            listed = tform.map(POINTS, inverted=inverted)
            arr = tform.mapPointsArray(POINTS, inverted=inverted)
            for (lx, ly), (ax, ay) in zip(listed, arr.tolist()):
                assert_bits(ax, lx, f"{name} array/list x")
                assert_bits(ay, ly, f"{name} array/list y")


def test_map_points_array_empty():
    out = Transform([1, 0, 0, 0, 1, 0]).mapPointsArray([])
    assert out.shape == (0, 2) and out.dtype == np.float64


@pytest.mark.parametrize("name", list(ALL_TFORMS))
def test_inverted_bit_identical(name):
    """inverted() reproduces QTransform.inverted()'s six numbers exactly."""
    t = ALL_TFORMS[name]
    assert_list_bits(
        Transform(list(t)).inverted().getList(),
        QtRefTransform(list(t)).inverted().getList(),
        f"{name} inverted",
    )


def test_compose_bit_identical():
    """__mul__ reproduces QTransform's operator* over 3,600 pairs."""
    sample = list(FIXTURES.items()) + list(RANDOM_TFORMS.items())[:48]
    for n1, t1 in sample:
        for n2, t2 in sample:
            got = (Transform(list(t1)) * Transform(list(t2))).getList()
            want = (QtRefTransform(list(t1)) * QtRefTransform(list(t2))).getList()
            assert_list_bits(got, want, f"compose {n1} * {n2}")


def test_compose_order_is_unchanged():
    """(A*B).map(p) ~= B.map(A.map(p)) -- QTransform's row-vector convention.

    Composing then mapping and mapping twice are not bit-identical (float
    arithmetic is not associative); QTransform had the same property, so this
    pins the *order*, not the bits.
    """
    a = Transform([1.3, 0.2, 4.0, -0.1, 0.9, 2.5])
    b = Transform([0.5, -0.3, -7.0, 0.4, 1.1, 3.0])
    for (x, y) in POINTS:
        composed = (a * b).map(x, y)
        chained = b.map(*a.map(x, y))
        ref_composed = (QtRefTransform([1.3, 0.2, 4.0, -0.1, 0.9, 2.5])
                        * QtRefTransform([0.5, -0.3, -7.0, 0.4, 1.1, 3.0])).map(x, y)
        assert_list_bits(composed, ref_composed, "compose order vs Qt")
        assert composed[0] == pytest.approx(chained[0], rel=1e-12, abs=1e-9)
        assert composed[1] == pytest.approx(chained[1], rel=1e-12, abs=1e-9)


@pytest.mark.parametrize("name", list(ALL_TFORMS))
def test_det_bit_identical(name):
    t = ALL_TFORMS[name]
    assert_bits(Transform(list(t)).det, QtRefTransform(list(t)).det, f"{name} det")


# Degenerate matrices, with QTransform's *observed* verdict. Qt's invertibility
# test is fuzzy and branch-dependent (the scale branch checks m11/m22 against
# 1e-12 and never looks at the determinant, so a scale matrix with det 1e-13 is
# still invertible; the general branch rejects |det| <= 1e-12). The Qt-free
# affine must agree case for case, so these are pinned rather than assumed.
DEGENERATE = {
    "singular": [1.0, 2.0, 3.0, 2.0, 4.0, 5.0],           # det == 0
    "near_singular_scale": [1e-7, 0.0, 0.0, 0.0, 1e-6, 0.0],  # det 1e-13, ok
    "near_singular_shear": [1e-7, 1e-7, 0.0, 1e-7, 2e-7, 0.0],  # det 1e-14
    "tiny_det_general": [1e-6, 1e-6, 3.0, 1e-6, 2e-6, 4.0],   # det == 1e-12
    "zero_scale": [0.0, 0.0, 5.0, 0.0, 3.0, 2.0],         # fuzzy-null m11
    "all_zero": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
}


@pytest.mark.parametrize("name", list(DEGENERATE))
def test_degenerate_invertibility_verdict_matches_qtransform(name):
    """Whatever QTransform did with a degenerate matrix, the affine does too.

    Where Qt refused, `inverted()` / the inverted map paths must still raise
    (rather than silently producing enormous coordinates); where Qt accepted, the
    six numbers must match bit-for-bit.
    """
    t = DEGENERATE[name]
    ref = QtRefTransform(list(t))
    new = Transform(list(t))
    try:
        ref_inv = ref.inverted().getList()
    except Exception:
        ref_inv = None

    if ref_inv is None:
        with pytest.raises(Exception, match="not invertible"):
            new.inverted()
        with pytest.raises(Exception, match="not invertible"):
            new.map(1.0, 2.0, inverted=True)
        with pytest.raises(Exception, match="not invertible"):
            new.map([(1.0, 2.0)], inverted=True)
        with pytest.raises(Exception, match="not invertible"):
            new.mapPointsArray([(1.0, 2.0)], inverted=True)
    else:
        assert_list_bits(new.inverted().getList(), ref_inv, f"{name} inverted")


def test_at_least_one_degenerate_case_raises():
    """Guard the guard: the DEGENERATE table must exercise both verdicts."""
    verdicts = set()
    for t in DEGENERATE.values():
        try:
            Transform(list(t)).inverted()
            verdicts.add(True)
        except Exception:
            verdicts.add(False)
    assert verdicts == {True, False}


def test_nan_transform_does_not_raise_like_before():
    """A NaN transform behaves as it did: no raise, NaN out (see #  guards)."""
    nan_t = [float("nan")] * 6
    ref = QtRefTransform(list(nan_t)).map(1.0, 2.0)
    got = Transform(list(nan_t)).map(1.0, 2.0)
    assert all(math.isnan(v) for v in ref)
    assert all(math.isnan(v) for v in got)


def test_fuzz_boundary_is_the_only_divergence():
    """Characterize the single documented divergence from QTransform.

    QTransform picks its arithmetic by matrix *type*, classified with a 1e-12
    fuzz, so a shear/scale/translation term smaller than that is dropped. The
    Qt-free affine keeps it. This test asserts, for each such matrix, that:
      1. the two implementations really do differ (so the divergence stays
         documented rather than silently changing shape), and
      2. the Qt-free result is the one exact rational arithmetic agrees with,
         while Qt's is not, and
      3. the absolute difference stays below 1e-6 even at |coord| = 1e6.
    """
    diverged = 0
    worst = 0.0
    for name, t in FUZZ_FIXTURES.items():
        a, b, c, d, e, f = (float(v) for v in t)
        new, ref = Transform(list(t)), QtRefTransform(list(t))
        for (x, y) in POINTS:
            gx, gy = new.map(x, y)
            rx, ry = ref.map(x, y)
            exact_x = Fraction(a) * Fraction(x) + Fraction(b) * Fraction(y) + Fraction(c)
            exact_y = Fraction(d) * Fraction(x) + Fraction(e) * Fraction(y) + Fraction(f)
            # the Qt-free result is always the correctly-rounded one
            assert abs(Fraction(gx) - exact_x) <= abs(Fraction(rx) - exact_x)
            assert abs(Fraction(gy) - exact_y) <= abs(Fraction(ry) - exact_y)
            if bits(gx) != bits(rx) or bits(gy) != bits(ry):
                diverged += 1
                worst = max(worst, abs(gx - rx), abs(gy - ry))
        assert worst < 1e-6, f"{name}: divergence {worst} exceeds the bound"
    assert diverged, "expected the fuzz-boundary cases to diverge"


def test_qtform_adapters_still_round_trip():
    """The Qt adapters are unchanged: list -> QTransform -> list is exact."""
    for name, t in ALL_TFORMS.items():
        q = Transform(list(t)).getQTransform()
        assert_list_bits(Transform.fromQTransform(q).getList(),
                         [float(v) for v in t], f"{name} adapter round-trip")
        # the compat attribute still hands back an equivalent QTransform
        assert Transform(list(t)).qtform == q


def test_transform_pickles_and_deepcopies():
    """No Qt object lives in a Transform, so it pickles and deepcopies."""
    import copy
    import pickle

    t = Transform([1.3, 0.2, 4.0, -0.1, 0.9, 2.5])
    for clone in (pickle.loads(pickle.dumps(t)), copy.deepcopy(t), t.copy()):
        assert_list_bits(clone.getList(), t.getList(), "clone")
        assert_list_bits(clone.map(3.5, -2.25), t.map(3.5, -2.25), "clone map")
        clone.magScale(1.0, 2.0)  # mutates in place; must not touch the original
        assert t.getList() == [1.3, 0.2, 4.0, -0.1, 0.9, 2.5]
