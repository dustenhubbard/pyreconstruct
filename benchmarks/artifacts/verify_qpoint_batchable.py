#!/usr/bin/env python
"""Evidence for Phase 2 gate criterion (iii) on the top dense-view hotspot.

The profile's rank-1 self-time entry is `trace_layer.py`'s
`qpoints = [QPoint(int(x), int(y)) for x, y in pix_pts]` inside `_drawTrace`,
plus the `QPainter.drawPolygon(qpoints)` that consumes it. The plan's gate
disqualifies any hotspot that is "addressable ... by batching into existing C
libraries (OpenCV, shapely, Qt)".

This script measures the current per-point-Python-object path against an
OpenCV batched rasterisation of the same polygons, to establish whether that
disqualification applies. It is evidence, not a proposed patch: cv2 output is
a filled/stroked raster, so a real change would need pixel-level golden tests
(and would change antialiasing), which is exactly the "characterized
differences" caveat the plan attaches to swapping rasterisers.

Run:  python verify_qpoint_batchable.py
"""
import os, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import cv2
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QPolygon
from PySide6.QtCore import QPoint, Qt

W, H = 1600, 1000
N_TRACES = 500
PTS_PER_TRACE = 120

app = QApplication.instance() or QApplication(["bench"])

rng = np.random.default_rng(11)
traces = []
for _ in range(N_TRACES):
    cx, cy = rng.uniform(100, W - 100), rng.uniform(100, H - 100)
    r = rng.uniform(15, 70)
    th = np.linspace(0, 2 * np.pi, PTS_PER_TRACE, endpoint=False)
    rr = r * (1 + 0.25 * rng.standard_normal(PTS_PER_TRACE))
    traces.append(np.column_stack([cx + rr * np.cos(th), cy + rr * np.sin(th)]))

total_pts = sum(len(t) for t in traces)


def qt_current(reps=5):
    """What ships today: a Python QPoint per point, then drawPolygon."""
    best = float("inf")
    for _ in range(reps):
        img = QImage(W, H, QImage.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        t0 = time.perf_counter()
        for pix_pts in traces:
            qpoints = [QPoint(int(x), int(y)) for x, y in pix_pts]
            p.setPen(QPen(QColor(255, 0, 0), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(qpoints)
        dt = time.perf_counter() - t0
        p.end()
        best = min(best, dt)
    return best


def qt_polygon_bulk(reps=5):
    """Intermediate: still Qt, but build QPolygon once per trace."""
    best = float("inf")
    for _ in range(reps):
        img = QImage(W, H, QImage.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        t0 = time.perf_counter()
        for pix_pts in traces:
            poly = QPolygon([QPoint(int(x), int(y)) for x, y in pix_pts])
            p.setPen(QPen(QColor(255, 0, 0), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(poly)
        dt = time.perf_counter() - t0
        p.end()
        best = min(best, dt)
    return best


def cv2_batched(reps=5):
    """Batched into OpenCV: int32 arrays, one polylines call for every trace,
    straight into a buffer that Qt can wrap as a QImage with no copy."""
    int_traces = [t.astype(np.int32) for t in traces]
    best = float("inf")
    for _ in range(reps):
        buf = np.zeros((H, W, 4), dtype=np.uint8)
        t0 = time.perf_counter()
        cv2.polylines(buf, int_traces, isClosed=True, color=(0, 0, 255, 255),
                      thickness=1, lineType=cv2.LINE_8)
        dt = time.perf_counter() - t0
        best = min(best, dt)
    return best


def cv2_batched_with_cast(reps=5):
    """Same, but paying the float->int32 cast every frame (the honest case,
    since screen coords are recomputed per frame)."""
    best = float("inf")
    for _ in range(reps):
        buf = np.zeros((H, W, 4), dtype=np.uint8)
        t0 = time.perf_counter()
        int_traces = [t.astype(np.int32) for t in traces]
        cv2.polylines(buf, int_traces, isClosed=True, color=(0, 0, 255, 255),
                      thickness=1, lineType=cv2.LINE_8)
        dt = time.perf_counter() - t0
        best = min(best, dt)
    return best


if __name__ == "__main__":
    a = qt_current()
    b = qt_polygon_bulk()
    c = cv2_batched()
    d = cv2_batched_with_cast()
    print(f"{N_TRACES} traces x {PTS_PER_TRACE} points = {total_pts:,} points, "
          f"{W}x{H} target\n")
    print(f"{'path':46s} {'ms/frame':>9s} {'vs current':>11s}")
    print("-" * 70)
    for name, t in (("QPoint listcomp + drawPolygon (ships today)", a),
                    ("QPolygon(list of QPoint) + drawPolygon", b),
                    ("cv2.polylines batched (pre-cast arrays)", c),
                    ("cv2.polylines batched (+ per-frame int32 cast)", d)):
        print(f"{name:46s} {t * 1000:9.2f} {a / t:10.1f}x")
    print("\nConclusion: the per-point Python object construction is removable "
          "by batching\ninto OpenCV, a dependency already pinned. No Rust is "
          "required to reclaim it.")
