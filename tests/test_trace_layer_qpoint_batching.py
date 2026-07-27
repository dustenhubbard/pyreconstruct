"""Pin the batched QPoint construction in trace_layer to the pixels the
per-point listcomp produced.

`TraceLayer._drawTrace` used to build its Qt points with

    [QPoint(int(x), int(y)) for x, y in pix_pts]

which was the rank-1 self-time entry of a dense-view render profile (36.7%).
It is now built by `qPointList`, which converts the whole integer array with a
single `tolist()` call and applies `QPoint` via `starmap`.

The point of these tests is that this is an *allocation-path* change only.
Nothing about the geometry, the point order or the rasterizer changes, so the
rendered output must be byte-for-byte identical -- which is what
`test_rendered_pixels_are_byte_identical` asserts by rendering the same shapes
both ways and comparing the raw image buffers.

A rasterizer swap (drawing the traces with cv2.polylines instead of QPainter)
was measured and rejected: the field never enables QPainter.Antialiasing, so
the two rasterizers disagree by whole on/off pixels rather than by edge
softness -- 74.7% of the lit outline pixels of a wobbly blob differed, at a
max channel delta of 255. `test_qt_and_cv2_rasterizers_disagree_materially`
pins that finding so the "just use cv2" idea is not silently retried.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QBrush
from PySide6.QtCore import QPoint, Qt

from PyReconstruct.modules.backend.view.trace_layer import TraceLayer, qPointList
from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.datatypes.transform import Transform


W, H = 400, 300


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(["test"])


def _reference_qpoints(pix_pts):
    """The expression that shipped before the change."""
    return [QPoint(int(x), int(y)) for x, y in pix_pts]


def _shapes():
    """Awkward-case integer pixel arrays, all as (N, 2) int64."""
    rng = np.random.default_rng(3)
    out = {}

    theta = np.linspace(0, 2 * np.pi, 80, endpoint=False)
    radius = 90 * (1 + 0.15 * rng.standard_normal(80))
    out["wobbly_blob"] = np.rint(np.column_stack(
        [200 + radius * np.cos(theta), 150 + radius * np.sin(theta)]
    )).astype(np.int64)

    out["triangle"] = np.array([[30, 30], [120, 40], [60, 110]], dtype=np.int64)
    out["thin_sliver"] = np.array(
        [[300, 20], [380, 25], [381, 28], [301, 24]], dtype=np.int64
    )
    out["axis_aligned_rect"] = np.array(
        [[250, 200], [350, 200], [350, 270], [250, 270]], dtype=np.int64
    )
    out["single_point"] = np.array([[10, 10]], dtype=np.int64)
    out["two_points"] = np.array([[10, 10], [200, 250]], dtype=np.int64)
    out["duplicate_points"] = np.array(
        [[50, 50], [50, 50], [150, 150], [150, 150]], dtype=np.int64
    )
    out["self_intersecting"] = np.array(
        [[20, 20], [200, 200], [200, 20], [20, 200]], dtype=np.int64
    )
    # partly and wholly off-screen (negative and past-the-edge coordinates)
    out["negative_coords"] = np.array(
        [[-40, -30], [60, -10], [20, 80]], dtype=np.int64
    )
    out["past_edge"] = np.array(
        [[380, 280], [520, 310], [340, 420]], dtype=np.int64
    )
    out["large_random"] = np.rint(
        rng.uniform(-50, 450, size=(500, 2))
    ).astype(np.int64)
    return out


ALL_SHAPES = _shapes()


# ------------------------------------------------------------------ values
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_qpoint_values_match_the_reference_listcomp(app, name):
    pix_pts = ALL_SHAPES[name]
    new = qPointList(pix_pts)
    ref = _reference_qpoints(pix_pts)
    assert len(new) == len(ref)
    assert [(p.x(), p.y()) for p in new] == [(p.x(), p.y()) for p in ref]


@pytest.mark.parametrize("dtype", [np.int64, np.int32, np.int16, np.intp])
def test_qpoint_values_match_across_integer_dtypes(app, dtype):
    """traceToPixArray returns int64 today; guard the helper against a future
    dtype change silently altering the coordinates."""
    pix_pts = ALL_SHAPES["wobbly_blob"].astype(dtype)
    ref = _reference_qpoints(pix_pts)
    new = qPointList(pix_pts)
    assert [(p.x(), p.y()) for p in new] == [(p.x(), p.y()) for p in ref]


def test_float_coordinates_truncate_exactly_like_int(app):
    """traceToPixArray always returns int64, so this is a guard rather than a
    live path: PySide6's QPoint truncates a Python float toward zero, which is
    what the old int(x) did, so a float array would behave the same either
    way. If a future PySide6 rounds instead of truncating, this fails and the
    helper needs an explicit cast."""
    floats = np.array([[1.7, 2.9], [-3.2, 4.5], [-0.9, 0.9]])
    assert [(p.x(), p.y()) for p in qPointList(floats)] == \
           [(p.x(), p.y()) for p in _reference_qpoints(floats)]
    assert [(p.x(), p.y()) for p in qPointList(floats)] == \
           [(1, 2), (-3, 4), (0, 0)]


def test_empty_array_gives_an_empty_list(app):
    """_drawTrace culls empty traces before calling this, but the helper must
    not raise if it is ever reached with none."""
    empty = np.empty((0, 2), dtype=np.int64)
    assert qPointList(empty) == []
    assert _reference_qpoints(empty) == []


def test_non_contiguous_array_is_handled(app):
    """A sliced/strided view must convert the same as a contiguous copy."""
    dense = ALL_SHAPES["large_random"]
    strided = dense[::3]
    assert not strided.flags["C_CONTIGUOUS"]
    assert [(p.x(), p.y()) for p in qPointList(strided)] == \
           [(p.x(), p.y()) for p in _reference_qpoints(strided)]


# ------------------------------------------------------------------ pixels
def _render(pix_pts, builder, closed=True, fill=False, pen_width=1,
            opacity=1.0):
    """Render one shape exactly the way _drawTrace does (no antialiasing --
    the field never sets QPainter.Antialiasing)."""
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    qpoints = builder(pix_pts)
    painter.setOpacity(opacity)
    painter.setBrush(QBrush(QColor(255, 255, 255)) if fill else Qt.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255), pen_width))
    if closed:
        painter.drawPolygon(qpoints)
    else:
        painter.drawPolyline(qpoints)
    painter.end()
    return img.copy()


def _raw(img):
    img = img.convertToFormat(QImage.Format_RGBA8888)
    return np.array(img.constBits()).reshape(img.height(), img.width(), 4).copy()


@pytest.mark.parametrize("name", list(ALL_SHAPES))
@pytest.mark.parametrize(
    "closed,fill,pen_width,opacity",
    [
        (True, False, 1, 1.0),     # plain outline
        (True, False, 8, 0.4),     # selected highlight
        (True, True, 1, 1.0),      # solid fill
        (True, True, 1, 0.3),      # transparent fill
        (False, False, 1, 1.0),    # open trace
    ],
)
def test_rendered_pixels_are_byte_identical(app, name, closed, fill,
                                            pen_width, opacity):
    """The golden comparison: same shape, both construction paths, every draw
    mode _drawTrace uses. Byte-identical buffers, not merely 'close'."""
    pix_pts = ALL_SHAPES[name]
    ref = _render(pix_pts, _reference_qpoints, closed, fill, pen_width, opacity)
    new = _render(pix_pts, qPointList, closed, fill, pen_width, opacity)
    ref_raw, new_raw = _raw(ref), _raw(new)
    differing = int((ref_raw != new_raw).any(axis=2).sum())
    assert differing == 0, (
        f"{name}: {differing} pixels differ between the reference listcomp "
        f"and qPointList"
    )


# ------------------------------------------------------- real code path
class _StubTraceLayer(TraceLayer):
    """TraceLayer with only the attributes traceToPix* touch."""

    def __init__(self):
        self.pixmap_dim = (W, H)

        class _Section:
            tform = Transform([1, 0, 0, 0, 1, 0])
            mag = 0.008

        class _Series:
            window = [0, 0, W * 0.008, H * 0.008]

        self.section = _Section()
        self.series = _Series()


def _trace(points, closed=True):
    trace = Trace("t", (255, 0, 0), closed=closed)
    trace.points = [(float(x), float(y)) for x, y in points]
    return trace


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_traceToPix_qpoints_matches_reference_on_the_real_path(app, name):
    layer = _StubTraceLayer()
    trace = _trace(ALL_SHAPES[name])
    pix_pts = layer.traceToPixArray(trace)
    got = layer.traceToPix(trace, qpoints=True)
    ref = _reference_qpoints(pix_pts)
    assert [(p.x(), p.y()) for p in got] == [(p.x(), p.y()) for p in ref]


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_traceToPix_tuples_keep_their_type_and_values(app, name):
    """getTraces / cutTraces consume this list; it must stay tuples of plain
    Python ints, not lists or numpy scalars."""
    layer = _StubTraceLayer()
    trace = _trace(ALL_SHAPES[name])
    pix_pts = layer.traceToPixArray(trace)
    got = layer.traceToPix(trace)
    ref = [(int(x), int(y)) for x, y in pix_pts]
    assert got == ref
    for point in got:
        assert type(point) is tuple
        assert all(type(c) is int for c in point)


# ------------------------------------------------ why the rasterizer stayed
def test_qt_and_cv2_rasterizers_disagree_materially(app):
    """Documented reason the cv2.polylines swap was NOT taken.

    Batching every trace into cv2 is much faster, but the field draws without
    antialiasing, so Qt's and OpenCV's line rasterizers simply light different
    pixels. The disagreement is whole-pixel (delta 255), not sub-pixel
    softness, and it covers most of a thin trace's visible pixels -- a visible
    change to how every trace is drawn. If this test ever starts failing
    because the two agree, the swap becomes worth revisiting.
    """
    cv2 = pytest.importorskip("cv2")
    pix_pts = ALL_SHAPES["wobbly_blob"]

    qt_raw = _raw(_render(pix_pts, qPointList))[:, :, 0]

    cv_buf = np.zeros((H, W), np.uint8)
    cv2.polylines(cv_buf, [pix_pts.astype(np.int32)], True, 255, 1, cv2.LINE_8)

    lit = int((qt_raw > 0).sum())
    differing = int((qt_raw != cv_buf).sum())
    max_delta = int(np.abs(qt_raw.astype(int) - cv_buf.astype(int)).max())

    assert lit > 0
    # whole on/off flips, not antialiasing gradients
    assert max_delta == 255
    # and they cover a large share of the trace's visible pixels
    assert differing / lit > 0.5, (
        f"{differing} differing vs {lit} lit -- rasterizers now agree more "
        f"closely than when the swap was rejected; re-evaluate"
    )
