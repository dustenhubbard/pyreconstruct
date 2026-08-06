"""Per-element equivalence tests for the vectorized tform mapping in the 3D
meshing path (``backend/volume/objects_3D.py``).

``Surface.addTrace`` and ``Contours.addTrace`` mapped trace points one at a time
through ``Transform.map()``: the vectorization the 2D path already got
(``Transform.mapPointsArray``) had never reached the 3D path. These tests hold a
frozen copy of the original scalar loop as the reference and require the shipped
implementation to reproduce it **exactly** (``==``, not ``approx``) on every
closed and open trace of the in-repo fixture series, plus adversarial synthetic
traces.

They also pin two things that are easy to break while batching:

* the ``extremes`` bookkeeping, which was per-point and is now derived from the
  per-trace min/max -- equivalent only because ``addToExtremes`` compares each
  coordinate independently;
* the exact Python types in the emitted point tuples (``float`` when a tform is
  applied, the *original* untouched values when it is not -- integer trace
  coordinates must stay integers, since ``generateTrimesh`` rounds them).

``Ztrace3D.generate3D`` is pinned here as well. It is deliberately *not*
batched -- every point carries its own section, so its tform varies per point
and the fixture ztraces have exactly one point per section (a batch of one is
several times slower than a scalar ``map``) -- but the loop-invariant alignment
lookup was hoisted out of it, so its output needs the same guard.
"""
import math
import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication(["test"])

from PyReconstruct.modules.datatypes.transform import Transform
from PyReconstruct.modules.backend.volume.objects_3D import (
    Surface,
    Contours,
    Ztrace3D,
)

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets", "checker", "files"
)

TFORMS = {
    "none": None,
    "identity": Transform([1, 0, 0, 0, 1, 0]),
    "translate": Transform([1, 0, 37.5, 0, 1, -12.25]),
    "scale": Transform([2.5, 0, 0, 0, 0.4, 0]),
    "rotate45": Transform([math.cos(0.785), -math.sin(0.785), 0,
                           math.sin(0.785), math.cos(0.785), 0]),
    "shear_offset": Transform([1.03, 0.7, 3.5, 0.3, 0.98, -2.25]),
}

# Shapes chosen to stress the batching edges: empty, single point, duplicate
# points, integer coordinates, and magnitudes where float error is visible.
SYNTHETIC = {
    "empty": [],
    "one_pt": [(3.0, 4.0)],
    "two_pt": [(0.0, 0.0), (5.0, 12.0)],
    "int_coords": [(0, 0), (10, 0), (10, 10), (0, 10)],
    "duplicates": [(1.5, 1.5), (1.5, 1.5), (5.0, 5.0)],
    "negative": [(-5.0, -5.0), (-1.0, -8.0), (-9.0, -2.0)],
    "huge": [(1e7, -1e7), (1e7, 1e7), (-1e7, 1e7)],
    "tiny": [(1e-9, 2e-9), (-3e-9, 5e-10)],
    "mixed_sign": [(-1e6, 2.5), (3.25, -7e5), (0.0, 0.0)],
}


class _StubTrace:
    """The only trace attributes the 3D addTrace paths read."""

    def __init__(self, points, closed=True, negative=False, color=(1, 2, 3)):
        self.points = points
        self.closed = closed
        self.negative = negative
        self.color = color


# --------------------------------------------------------------- references
def _add_to_extremes(extremes, x, y, s):
    """``Object3D.addToExtremes``, verbatim, against a plain list."""
    if not extremes:
        extremes[:] = [x, x, y, y, s, s]
    else:
        if x < extremes[0]: extremes[0] = x
        if x > extremes[1]: extremes[1] = x
        if y < extremes[2]: extremes[2] = y
        if y > extremes[3]: extremes[3] = y
        if s < extremes[4]: extremes[4] = s
        if s > extremes[5]: extremes[5] = s


def _scalar_map_points(points, snum, tform, extremes):
    """The original per-point loop shared by Surface/Contours.addTrace."""
    pts = []
    for pt in points:
        if tform:
            x, y = tform.map(*pt)
        else:
            x, y = pt
        _add_to_extremes(extremes, x, y, snum)
        pts.append((x, y))
    return pts


def _scalar_ztrace_pts(series, name, extremes):
    """The original per-point loop from ``Ztrace3D.generate3D``."""
    thickness = series.avg_thickness
    ztrace = series.ztraces[name]
    pts = []
    for pt in ztrace.points:
        x, y, s = pt
        _add_to_extremes(extremes, x, y, s)
        alignment = series.getAttr(name, "alignment", ztrace=True)
        if not alignment:
            alignment = series.alignment
        tform = series.data["sections"][s]["tforms"][alignment]
        x, y = tform.map(x, y)
        z = s * thickness
        pts.append((x, y, z))
    return pts


def _assert_pts_identical(got, ref, ctx):
    """Exact, per-element, type-aware comparison."""
    assert len(got) == len(ref), ctx
    for i, (g, r) in enumerate(zip(got, ref)):
        assert type(g) is tuple, f"{ctx} pt {i}: {type(g)} is not a tuple"
        assert len(g) == len(r), f"{ctx} pt {i}"
        for gv, rv in zip(g, r):
            assert gv == rv, f"{ctx} pt {i}: {gv!r} != {rv!r}"
            assert type(gv) is type(rv), (
                f"{ctx} pt {i}: {type(gv)} != {type(rv)} ({gv!r} vs {rv!r})"
            )


# ------------------------------------------------------------ synthetic data
@pytest.mark.parametrize("tname", list(TFORMS))
@pytest.mark.parametrize("sname", list(SYNTHETIC))
@pytest.mark.parametrize("negative", [False, True])
def test_surface_addtrace_matches_scalar(tname, sname, negative):
    tform = TFORMS[tname]
    points = SYNTHETIC[sname]
    trace = _StubTrace(points, negative=negative)

    surf = Surface("obj", None, None, None, None)
    surf.addTrace(trace, 7, tform)

    ref_extremes = []
    ref_pts = _scalar_map_points(points, 7, tform, ref_extremes)

    bucket = "neg" if negative else "pos"
    assert list(surf.traces) == [7]
    assert len(surf.traces[7][bucket]) == 1
    _assert_pts_identical(surf.traces[7][bucket][0], ref_pts, f"{tname}/{sname}")
    assert surf.traces[7]["neg" if not negative else "pos"] == []
    assert surf.extremes == ref_extremes, f"{tname}/{sname}"
    assert surf.default_color == trace.color


@pytest.mark.parametrize("tname", list(TFORMS))
@pytest.mark.parametrize("sname", [s for s in SYNTHETIC if s != "empty"])
@pytest.mark.parametrize("closed", [False, True])
def test_contours_addtrace_matches_scalar(tname, sname, closed):
    tform = TFORMS[tname]
    points = SYNTHETIC[sname]
    trace = _StubTrace(points, closed=closed)

    cont = Contours("obj", None, None, None, None)
    cont.addTrace(trace, 3, tform)

    ref_extremes = []
    ref_pts = _scalar_map_points(points, 3, tform, ref_extremes)
    if closed:  # the closing point is appended by addTrace, not by the mapping
        ref_pts.append(ref_pts[0])

    _assert_pts_identical(cont.traces[3][0], ref_pts, f"{tname}/{sname}")
    assert cont.extremes == ref_extremes, f"{tname}/{sname}"


def test_surface_empty_trace_leaves_extremes_untouched():
    """A trace with no points made zero addToExtremes calls; the batched form
    must not seed extremes off an empty min/max."""
    surf = Surface("obj", None, None, None, None)
    surf.addTrace(_StubTrace([]), 5, TFORMS["shear_offset"])
    assert surf.extremes == []
    assert surf.traces[5]["pos"] == [[]]


def test_contours_empty_closed_trace_still_raises():
    """The scalar code did ``pts.append(pts[0])`` unguarded, so a closed trace
    with no points raised IndexError. Pin that: silently "fixing" it here would
    hide an upstream bug behind a behavior change."""
    cont = Contours("obj", None, None, None, None)
    with pytest.raises(IndexError):
        cont.addTrace(_StubTrace([], closed=True), 1, TFORMS["identity"])


def test_extremes_accumulate_across_sections():
    """Extremes must still fold across repeated addTrace calls (and across
    sections), not just within one trace."""
    tform = TFORMS["shear_offset"]
    surf = Surface("obj", None, None, None, None)
    ref_extremes = []
    for snum, sname in ((4, "negative"), (9, "huge"), (2, "two_pt"), (9, "tiny")):
        surf.addTrace(_StubTrace(SYNTHETIC[sname]), snum, tform)
        _scalar_map_points(SYNTHETIC[sname], snum, tform, ref_extremes)
    assert surf.extremes == ref_extremes


# --------------------------------------------------------------- real series
def _open_series(tmp_path, name):
    src = os.path.join(FIXTURE_DIR, name)
    if not os.path.exists(src):
        pytest.skip(f"fixture {name} not found")
    fp = str(tmp_path / name)
    shutil.copyfile(src, fp)
    from PyReconstruct.modules.datatypes.series import Series

    return Series.openJser(fp)


def _all_fixture_traces(series):
    out = []
    for snum, sec in series.enumerateSections(show_progress=False):
        for name, contour in sec.contours.items():
            for trace in contour:
                out.append((snum, name, trace))
    return out


@pytest.mark.parametrize("fixture", ["shapes1.jser", "class_series.jser"])
@pytest.mark.parametrize("tname", ["none", "identity", "shear_offset", "rotate45"])
def test_fixture_traces_match_scalar(tmp_path, fixture, tname):
    """Every real trace in the fixture series, through both 3D addTrace paths,
    must reproduce the scalar mapping element-for-element."""
    tform = TFORMS[tname]
    series = _open_series(tmp_path, fixture)
    try:
        items = _all_fixture_traces(series)
        assert items, f"{fixture} had no traces"

        surf = Surface("obj", series, None, None, None)
        cont = Contours("obj", series, None, None, None)
        surf_ref, cont_ref = [], []
        n_pts = 0

        for snum, name, trace in items:
            surf.addTrace(trace, snum, tform)
            cont.addTrace(trace, snum, tform)

            ref = _scalar_map_points(trace.points, snum, tform, surf_ref)
            _scalar_map_points(trace.points, snum, tform, cont_ref)
            ctx = f"{fixture}/{tname} s{snum} {name}"

            bucket = "neg" if trace.negative else "pos"
            _assert_pts_identical(surf.traces[snum][bucket][-1], ref, ctx)

            cont_expected = list(ref)
            if trace.closed:
                cont_expected.append(cont_expected[0])
            _assert_pts_identical(cont.traces[snum][-1], cont_expected, ctx)
            n_pts += len(trace.points)

        assert n_pts > 0
        assert surf.extremes == surf_ref, f"{fixture}/{tname}"
        assert cont.extremes == cont_ref, f"{fixture}/{tname}"
    finally:
        series.close()


@pytest.mark.parametrize("fixture", ["shapes1.jser", "shapes2.jser"])
def test_ztrace3d_matches_scalar(tmp_path, fixture):
    """Hoisting the loop-invariant alignment lookup out of Ztrace3D.generate3D
    must not move a single vertex. Note the reference keeps the original
    (arguably wrong, but out of scope) behavior of feeding *unmapped* coords to
    addToExtremes."""
    series = _open_series(tmp_path, fixture)
    try:
        names = list(series.ztraces.keys())
        assert names, f"{fixture} had no ztraces"
        for name in names:
            zt = Ztrace3D(name, series, None, None, None)
            mesh = zt.generate3D()

            ref_extremes = []
            ref_pts = _scalar_ztrace_pts(series, name, ref_extremes)
            from PyReconstruct.modules.backend.volume.objects_3D import createTube

            ref_verts, ref_faces = createTube(
                ref_pts, series.ztraces[name].getDistance(series) / 1000
            )
            assert mesh["vertices"].shape == ref_verts.shape, name
            assert (mesh["vertices"] == ref_verts).all(), name
            assert (mesh["faces"] == ref_faces).all(), name
            assert zt.extremes == ref_extremes, name
    finally:
        series.close()


class _StubZtrace:
    def __init__(self, points, color=(9, 9, 9)):
        self.points = points
        self.color = color

    def getDistance(self, series):
        return 250.0


class _StubZSeries:
    """Minimal series for Ztrace3D: a per-section tform table plus an alignment
    that differs from the series default."""

    def __init__(self, ztrace_alignment):
        self.avg_thickness = 0.05
        self.alignment = "series_default"
        self._ztrace_alignment = ztrace_alignment
        self.ztraces = {"zt": _StubZtrace(
            [(1.0, 2.0, 0), (3.5, -4.25, 1), (0.0, 7.75, 2), (-2.5, 1.0, 1)]
        )}
        # each section gets a *different* tform under each alignment, so picking
        # the wrong section or the wrong alignment moves the vertices
        self.data = {"sections": {
            s: {"tforms": {
                "series_default": Transform([1, 0, 100 + s, 0, 1, 200 + s]),
                "ztrace_specific": Transform([2 + s, 0.1 * s, s, -0.2 * s, 3 + s, -s]),
            }} for s in (0, 1, 2)
        }}

    def getAttr(self, name, attr, ztrace=False):
        assert (name, attr, ztrace) == ("zt", "alignment", True)
        return self._ztrace_alignment


@pytest.mark.parametrize("ztrace_alignment, expect_alignment", [
    ("ztrace_specific", "ztrace_specific"),   # per-ztrace alignment wins
    (None, "series_default"),                 # unset -> series alignment
    ("", "series_default"),                   # falsy -> series alignment
])
def test_ztrace3d_uses_per_ztrace_alignment(ztrace_alignment, expect_alignment):
    """The alignment lookup was hoisted out of the point loop; pin that it still
    resolves per-ztrace-first-then-series, and that each point is mapped by its
    own section's tform. The fixture ztraces have no alignment attribute set, so
    only a stub can distinguish these."""
    from PyReconstruct.modules.backend.volume.objects_3D import createTube

    series = _StubZSeries(ztrace_alignment)
    mesh = Ztrace3D("zt", series, None, None, None).generate3D()

    ref_pts = []
    for x, y, s in series.ztraces["zt"].points:
        tform = series.data["sections"][s]["tforms"][expect_alignment]
        mx, my = tform.map(x, y)
        ref_pts.append((mx, my, s * series.avg_thickness))
    ref_verts, _ = createTube(ref_pts, 250.0 / 1000)

    assert (mesh["vertices"] == ref_verts).all()
    # and the other alignment really would have differed
    other = "series_default" if expect_alignment != "series_default" else "ztrace_specific"
    wrong_pts = []
    for x, y, s in series.ztraces["zt"].points:
        mx, my = series.data["sections"][s]["tforms"][other].map(x, y)
        wrong_pts.append((mx, my, s * series.avg_thickness))
    wrong_verts, _ = createTube(wrong_pts, 250.0 / 1000)
    assert not (mesh["vertices"] == wrong_verts).all()
