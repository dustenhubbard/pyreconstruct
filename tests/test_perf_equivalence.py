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
import struct
import sys
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
        # TraceData records every attribute a real Trace carries; color is
        # read since the object attributes dialog's series-wide color seed.
        self.color = (0, 0, 0)

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

def _real_trace(points, closed=True, negative=False):
    """A real Trace, needed wherever the code under test calls Trace methods."""
    from PyReconstruct.modules.datatypes.trace import Trace
    t = Trace("obj", (0, 0, 0), closed=closed)
    t.points = list(points)
    t.negative = negative
    return t

class _StubSection:
    """Stands in for the section a Feret read goes through: TraceData.getFeret
    only ever indexes contours[name] by the trace index it was built with."""
    def __init__(self, traces, name="obj"):
        self.contours = {name: traces}

def _feret_from_retained_points(trace, tform):
    """The value the previous implementation produced: map the points to an
    exact float64 array, keep it until the read, then hull the array. Open
    traces have no Feret diameter and never reached the hull."""
    from PyReconstruct.modules.calc import feret
    if not trace.closed:
        return (0, 0)
    pts = tform.mapPointsArray(trace.points)
    return feret([(float(x), float(y)) for x, y in pts]) if len(pts) else (0, 0)

def test_tracedata_lazy_feret():
    TraceData = _tracedata()
    ident = Transform(TFORMS["identity"])
    trace = _real_trace(ALL_POLYS["square"], closed=True)
    section = _StubSection([trace])
    td = TraceData(trace, 0, ident)
    f1 = td.getFeret(section, "obj")
    f2 = td.getFeret(section, "obj")   # cached, must be identical + not recompute
    assert f1 == f2
    opn = TraceData(_real_trace(ALL_POLYS["square"], closed=False), 0, ident)
    assert opn.getFeret(section, "obj") == (0, 0)   # open -> no feret

def test_tracedata_feret_is_lazy_and_retains_nothing():
    """The Feret diameters stay deferred through a bulk build -- they are a
    third of the geometry cost and most series never read them -- but nothing
    is held waiting for the read. Keeping the mapped points until first read
    made this object the largest per-trace allocation in a loaded series, so
    the retained size must not scale with the point count."""
    TraceData = _tracedata()
    ident = Transform(TFORMS["identity"])
    small = TraceData(_real_trace(_rand_poly(4)), 0, ident)
    big = TraceData(_real_trace(_rand_poly(500)), 0, ident)

    assert small._feret is None and big._feret is None   # not computed yet

    def retained(td):
        return sys.getsizeof(td) + sys.getsizeof(td.__dict__) + sum(
            sys.getsizeof(v) for v in td.__dict__.values()
        )

    for td in (small, big):
        for v in td.__dict__.values():
            assert not isinstance(v, np.ndarray), "no point array may be retained"
            assert not isinstance(v, list), "no point list may be retained"
    assert retained(small) == retained(big)

@pytest.mark.parametrize("pname", list(ALL_POLYS))
@pytest.mark.parametrize("tname", list(TFORMS))
def test_tracedata_feret_bit_exact_vs_retained_points(tname, pname):
    """Bit-exact, not approximate. The Feret diameters are a displayed and
    exported scientific measurement, so recomputing them from the live trace at
    read time instead of from a retained copy of the mapped points may not move
    a single bit -- struct.pack, so one ULP or a signed zero fails."""
    TraceData = _tracedata()
    tform = Transform(TFORMS[tname])
    trace = _real_trace(ALL_POLYS[pname])
    td = TraceData(trace, 0, tform)
    got = td.getFeret(_StubSection([trace]), "obj")
    ref = _feret_from_retained_points(trace, tform)
    assert struct.pack("<dd", *got) == struct.pack("<dd", *ref), f"{tname}/{pname}"
    assert type(got[0]) is type(ref[0]) and type(got[1]) is type(ref[1])

def test_tracedata_feret_unavailable_off_section():
    """A series-wide operation updates this data from the sections it writes,
    before the field reloads the section it is showing, so a row can exist for a
    trace the displayed section does not have. That must read as unavailable,
    not raise and not report a zero measurement."""
    TraceData = _tracedata()
    ident = Transform(TFORMS["identity"])
    trace = _real_trace(ALL_POLYS["square"])
    td = TraceData(trace, 0, ident)

    assert td.getFeret(_StubSection([], name="other"), "obj") is None  # no contour
    assert td.getFeret(_StubSection([]), "obj") is None                # contour empty
    assert td.getFeret(_StubSection([trace]), "obj") is not None       # now present

    off_end = TraceData(trace, 3, ident)
    assert off_end.getFeret(_StubSection([trace]), "obj") is None      # index past end

def test_trace_table_feret_cells_blank_when_off_section():
    """The trace list must render such a row instead of raising: blank Feret
    cells, refilled when the field reload rebuilds the table."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.gui.table.trace import TraceTableWidget
    import types

    TraceData = _tracedata()
    ident = Transform(TFORMS["identity"])
    trace = _real_trace(ALL_POLYS["square"])
    td = TraceData(trace, 0, ident)

    ## getItems only reaches for the section when it needs the Feret columns
    off = types.SimpleNamespace(section=_StubSection([], name="other"))
    items = TraceTableWidget.getItems(off, ("obj", td), "Feret")
    assert [i.text() for i in items] == ["", ""]

    on = types.SimpleNamespace(section=_StubSection([trace]))
    items = TraceTableWidget.getItems(on, ("obj", td), "Feret")
    ## the 10x10 square: max Feret is its diagonal, min Feret its side
    assert [i.text() for i in items] == [str(round(math.hypot(10, 10), 5)), "10.0"]

def test_export_traces_csv_blank_feret_when_section_lacks_trace(tmp_path):
    """The export reads the points off the sections on file. If this data is
    ahead of them, the row is still written with its other measurements and the
    Feret fields left empty -- never filled in with a zero."""
    import shutil
    src = os.path.join(os.path.dirname(__file__), "..", "dev",
                       "assets", "checker", "files", "shapes1.jser")
    if not os.path.exists(src):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(src, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(fp)
    series.setProgressReporter(NullProgressReporter)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd

    try:
        snum = sorted(series.sections)[0]
        live = series.loadSection(snum)          # never saved back to file
        ghost = _real_trace(ALL_POLYS["square"])
        ghost.name = "zzz_unsaved"
        live.addTrace(ghost, log_event=False)
        sd.updateSection(live, update_traces=True, log_events=False)

        rows = [l.split(",") for l in sd.exportTracesCSV().splitlines()[1:]]
        ghost_rows = [r for r in rows if r[0] == "zzz_unsaved"]
        assert len(ghost_rows) == 1
        assert ghost_rows[0][-2:] == ["", ""]            # Feret-Max, Feret-Min
        assert float(ghost_rows[0][7]) == pytest.approx(100.0)  # Area still written
    finally:
        series.close()

def test_export_traces_csv_order_and_feret(tmp_path):
    """The CSV export walks the sections (it needs the trace points for the
    Feret diameters) but must still emit object-name-major, section-ascending,
    index-ascending rows, with the same Feret values a retained-points read
    would have produced."""
    import shutil
    src = os.path.join(os.path.dirname(__file__), "..", "dev",
                       "assets", "checker", "files", "shapes1.jser")
    if not os.path.exists(src):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(src, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(fp)
    series.setProgressReporter(NullProgressReporter)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd

    try:
        lines = sd.exportTracesCSV().splitlines()
        header = lines[0].split(",")
        assert header[:3] == ["Name", "Section", "Index"]
        assert header[-2:] == ["Feret-Max", "Feret-Min"]

        rows = [l.split(",") for l in lines[1:]]
        assert rows, "fixture produced no rows"

        ## one row per trace, in name / section / index order
        expected_keys = []
        for name in sorted(sd.objects):
            for snum in sorted(sd.objects[name].traces):
                for i, _ in enumerate(sd.objects[name].traces[snum]):
                    expected_keys.append((name, snum, i))
        assert [(r[0], int(r[1]), int(r[2])) for r in rows] == expected_keys

        ## the Feret columns match the retained-points reference
        for r in rows:
            name, snum, i = r[0], int(r[1]), int(r[2])
            td = sd.objects[name].traces[snum][i]
            section = series.loadSection(snum)
            trace = section.contours[name][i]
            ref_min, ref_max = _feret_from_retained_points(trace, td._tform)
            assert r[-2] == str(round(ref_max, 7)), (name, snum, i)
            assert r[-1] == str(round(ref_min, 7)), (name, snum, i)
    finally:
        series.close()

def test_tracedata_feret_of_empty_closed_trace():
    """A closed trace with no points has no hull and no extent. It reported
    integer zeros, and callers round() and str() the result, so keep them."""
    TraceData = _tracedata()
    ident = Transform(TFORMS["identity"])
    trace = _real_trace([], closed=True)
    td = TraceData(trace, 0, ident)
    assert td.getFeret(_StubSection([trace]), "obj") == (0, 0)

# ---------------------------------------------------------------- scoped object ops
def test_getObjectSections_matches_disk_truth(tmp_path):
    """The rewrite scopes series-wide object ops to the in-memory object index
    (getObjectSections). Pin that the index lists exactly the sections that
    actually contain each object, versus an independent full-scan disk truth."""
    import shutil
    src = os.path.join(os.path.dirname(__file__), "..", "dev",
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
