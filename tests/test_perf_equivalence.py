"""Equivalence + property tests for the performance rewrite (PR #1).

Pins the vectorized / orjson hot paths to behave like the scalar / stdlib
reference on adversarial and random inputs, so the speedups can never silently
drift from the original behavior. Tolerances are data-meaningful (one rounding
step), not bit-exact, since two correct float computations may differ in the
last rounded digit.
"""
import json
import math
import os
import numpy as np
import pytest

from PyReconstruct.modules.calc.quantification import (
    area, lineDistance, centroid, traceGeometry,
)
from PyReconstruct.modules.datatypes.transform import Transform
from PyReconstruct.modules.constants.fast_json import fast_loads, fast_dumps

RNG = np.random.default_rng(20260627)

# ---------------------------------------------------------------- inputs
def _rand_poly(n, scale=1000.0):
    return [(float(x), float(y)) for x, y in RNG.uniform(-scale, scale, size=(n, 2))]

ADVERSARIAL = {
    "empty": [],
    "one_pt": [(3.0, 4.0)],
    "two_pt": [(0.0, 0.0), (5.0, 12.0)],
    "collinear": [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)],
    "triangle_ccw": [(0.0, 0.0), (4.0, 0.0), (0.0, 3.0)],
    "triangle_cw": [(0.0, 0.0), (0.0, 3.0), (4.0, 0.0)],
    "square": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
    "closed_dup": [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)],
    "duplicate_pts": [(1.0, 1.0), (1.0, 1.0), (5.0, 5.0), (5.0, 5.0)],
    "self_intersect": [(0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0)],
    "tiny_area": [(0.0, 0.0), (1e-4, 0.0), (1e-4, 1e-4), (0.0, 1e-4)],
    "huge": [(1e7, -1e7), (1e7, 1e7), (-1e7, 1e7), (-1e7, -1e7)],
    "negative_coords": [(-5.0, -5.0), (-1.0, -8.0), (-9.0, -2.0)],
}
RANDOM_POLYS = {f"rand_{n}_{i}": _rand_poly(n) for n in (3, 5, 12, 40, 200) for i in range(3)}
ALL_POLYS = {**ADVERSARIAL, **RANDOM_POLYS}

# ---------------------------------------------------------------- geometry
@pytest.mark.parametrize("name", list(ALL_POLYS))
@pytest.mark.parametrize("closed", [True, False])
def test_length_matches_lineDistance(name, closed):
    pts = ALL_POLYS[name]
    g_len = traceGeometry(pts, closed)[0]
    ref = lineDistance(pts, closed=closed) if len(pts) >= 1 else 0
    assert g_len == pytest.approx(ref, abs=2e-7), f"{name} closed={closed}"

@pytest.mark.parametrize("name", list(ALL_POLYS))
def test_area_matches_area(name):
    pts = ALL_POLYS[name]
    g_area = traceGeometry(pts, True)[1]
    ref = area(pts)
    assert g_area == pytest.approx(ref, rel=1e-9, abs=1e-7), name

@pytest.mark.parametrize("name", list(ALL_POLYS))
def test_centroid_matches_centroid(name):
    pts = ALL_POLYS[name]
    if len(pts) == 0:
        assert traceGeometry(pts, True)[2] == (0.0, 0.0)
        return
    gcx, gcy = traceGeometry(pts, True)[2]
    rcx, rcy = centroid(pts)
    assert gcx == pytest.approx(rcx, abs=2e-6), name
    assert gcy == pytest.approx(rcy, abs=2e-6), name

# ---------------------------------------------------------------- transform
def _rand_affine():
    a, b, c, d = RNG.uniform(-2, 2, 4)
    while abs(a * d - b * c) < 1e-3:  # keep it non-degenerate
        a, b, c, d = RNG.uniform(-2, 2, 4)
    dx, dy = RNG.uniform(-500, 500, 2)
    return [a, b, dx, c, d, dy]

TFORMS = {
    "identity": [1, 0, 0, 0, 1, 0],
    "translate": [1, 0, 37.5, 0, 1, -12.25],
    "scale": [2.5, 0, 0, 0, 0.4, 0],
    "rotate45": [math.cos(.785), -math.sin(.785), 0, math.sin(.785), math.cos(.785), 0],
    "shear": [1, 0.7, 0, 0.3, 1, 0],
    **{f"rand_{i}": _rand_affine() for i in range(6)},
}

@pytest.mark.parametrize("tname", list(TFORMS))
@pytest.mark.parametrize("pname", ["square", "rand_40_0", "negative_coords", "huge"])
def test_mapPointsArray_matches_map(tname, pname):
    t = Transform(TFORMS[tname])
    pts = ALL_POLYS[pname]
    arr = t.mapPointsArray(pts)
    ref = t.map(pts)
    assert arr.shape == (len(pts), 2)
    for (ax, ay), (rx, ry) in zip(arr, ref):
        assert ax == pytest.approx(rx, rel=1e-12, abs=1e-9), f"{tname}/{pname}"
        assert ay == pytest.approx(ry, rel=1e-12, abs=1e-9), f"{tname}/{pname}"

def test_mapPointsArray_empty():
    assert Transform(TFORMS["identity"]).mapPointsArray([]).shape == (0, 2)

# ---------------------------------------------------------------- fast_json fidelity
# Cases the orjson wrapper MUST match stdlib json on -- the common, finite,
# in-64-bit-range data PyReconstruct actually serializes.
FJSON_SOUND = [
    {"a": 1, "b": [1, 2, 3], "c": {"d": 4.5}},
    {"ints": [-(2**40), 2**40, 0], "floats": [1.5, -3.25, 1e-9, 1e9]},
    {"unicode": "µm · dendrite — Σ 🧠", "empty": {}, "arr": []},
    {"nested": {"x": [{"y": [1, {"z": True}]}]}, "null": None, "bool": [True, False]},
    list(range(50)),
    {"tuples_become_lists": [(1, 2), (3, 4)]},
    {1: "int_key", 2: "another"},                        # int keys -> str in both
    {"neg_zero": -0.0, "round7": round(1 / 3, 7)},
    {"i64": [2**63 - 1, -(2**63)], "u64max": 2**64 - 1},   # within orjson int range
    {"floats2": [3.141592653589793, 0.1 + 0.2, 1e308, 5e-324]},
    {"ctrl": "a\x00b\tc\n", "": "empty_key"},
]

@pytest.mark.parametrize("i", range(len(FJSON_SOUND)))
def test_fastjson_roundtrip_matches_stdlib(i):
    obj = FJSON_SOUND[i]
    fast = fast_loads(fast_dumps(obj))
    std = json.loads(json.dumps(obj))
    assert json.dumps(fast, sort_keys=True) == json.dumps(std, sort_keys=True), f"case {i}"

def test_fastjson_bytes_and_str():
    b = fast_dumps({"k": "v"})
    assert isinstance(b, (bytes, bytearray))
    assert fast_loads(b) == {"k": "v"}
    assert fast_loads(b.decode("utf-8")) == {"k": "v"}

# --- Known, documented divergences from stdlib (perf audit 2026-06-27). Both are
# unreachable from app-generated data (finite, in-range numerics; computed
# geometry is never serialized) and only surface when re-saving a foreign or
# hand-edited .jser. xfail(strict) so a future fidelity fix flips these to XPASS
# and flags that the markers (and the fast_json docstring caveat) should be removed.

@pytest.mark.xfail(strict=True, reason="orjson.dumps silently coerces NaN/Inf -> null "
                   "(does not raise, so the stdlib fallback never fires); stdlib json "
                   "preserves NaN/Infinity. DUMP-only; loads of those literals fall back.")
@pytest.mark.parametrize("val", [float("nan"), float("inf"), float("-inf")])
def test_fastjson_nonfinite_dump_divergence(val):
    got = fast_loads(fast_dumps({"v": val}))["v"]
    if math.isnan(val):
        assert isinstance(got, float) and math.isnan(got)
    else:
        assert got == val

@pytest.mark.xfail(strict=True, reason="orjson.loads silently parses integers outside "
                   "[-2**63, 2**64-1] as float (does not raise); stdlib json keeps the exact "
                   "int. LOAD-only; boundary is 2**64 / -(2**63)-1.")
@pytest.mark.parametrize("lit", [b'{"v": 18446744073709551616}',     # 2**64
                                 b'{"v": -9223372036854775809}'])     # -(2**63)-1
def test_fastjson_out_of_range_int_load_divergence(lit):
    assert isinstance(fast_loads(lit)["v"], int)

def test_orjson_declared_in_pyproject():
    """orjson powers the JSON speedups and changes JSON edge behavior, so it must
    be a declared dependency. It was in requirements.txt but missing from
    pyproject.toml -- so `pip install .` silently dropped both the speedup and
    the orjson code path."""
    root = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(root, "pyproject.toml")) as f:
        assert "orjson" in f.read(), "orjson must be in pyproject.toml dependencies"

# ---------------------------------------------------------------- TraceData
class _StubTrace:
    def __init__(self, points, closed=True, negative=False):
        self.points, self.closed, self.negative = points, closed, negative
        self.hidden, self.tags = False, set()

def _tracedata():
    from PyReconstruct.modules.datatypes.series_data import TraceData
    return TraceData

def test_tracedata_area_sign_and_open():
    TraceData = _tracedata()
    ident = Transform(TFORMS["identity"])
    sq = ALL_POLYS["square"]
    pos = TraceData(_StubTrace(sq, closed=True, negative=False), 0, ident)
    neg = TraceData(_StubTrace(sq, closed=True, negative=True), 0, ident)
    opn = TraceData(_StubTrace(sq, closed=False, negative=False), 0, ident)
    assert pos.area > 0
    assert neg.area == pytest.approx(-pos.area)
    assert opn.area == 0           # open contour -> area 0

def test_tracedata_lazy_feret():
    TraceData = _tracedata()
    ident = Transform(TFORMS["identity"])
    td = TraceData(_StubTrace(ALL_POLYS["square"], closed=True), 0, ident)
    f1 = td.getFeret()
    f2 = td.getFeret()             # cached, must be identical + not recompute
    assert f1 == f2
    assert td._feret_points is None   # freed after first computation
    opn = TraceData(_StubTrace(ALL_POLYS["square"], closed=False), 0, ident)
    assert opn.getFeret() == (0, 0)   # open -> no feret

# ---------------------------------------------------------------- scoped object ops
def test_getObjectSections_matches_disk_truth(tmp_path):
    """The rewrite scopes series-wide object ops to the in-memory object index
    (getObjectSections). Pin that the index lists exactly the sections that
    actually contain each object, versus an independent full-scan disk truth."""
    import shutil
    src = os.path.join(os.path.dirname(__file__), "..", "PyReconstruct",
                       "assets", "checker", "files", "shapes1.jser")
    if not os.path.exists(src):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")          # isolate any open-time side effects
    shutil.copyfile(src, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData

    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd

    truth = {}
    for snum, sec in series.enumerateSections(show_progress=False):
        for name, contour in sec.contours.items():
            if not contour.isEmpty():
                truth.setdefault(name, set()).add(snum)
    assert truth, "fixture had no objects"
    for name, sections in truth.items():
        assert series.getObjectSections([name]) == sections, name
