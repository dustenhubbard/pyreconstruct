#!/usr/bin/env python
"""Measure complete trace-layer redraws on a synthetic section (no image I/O).

Run with the project's installed test environment, from the checkout root:
  uv run --no-sync python benchmarks/bench_trace_redraw.py
  uv run --no-sync python benchmarks/bench_trace_redraw.py --objects 5000
  uv run --no-sync python benchmarks/bench_trace_redraw.py --visible 1

Compare a historical implementation without a second environment:
  git show 39a315c4:PyReconstruct/modules/backend/view/trace_layer.py > /tmp/trace-before.py
  uv run --no-sync python benchmarks/bench_trace_redraw.py --source /tmp/trace-before.py

Includes real transforms, QPainter outlines, transparent fills and selection
highlights. Settings are fixed in memory; timings exclude application startup,
image rendering and file I/O. Compare pixel hashes as well as median timings.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PyReconstruct.modules.backend.view.trace_layer import TraceLayer
from PyReconstruct.modules.datatypes import Contour, Section, Trace, Transform


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="historical trace_layer.py")
    parser.add_argument("--traces", type=int, default=5000)
    parser.add_argument("--objects", type=int, default=1)
    parser.add_argument("--visible", type=int, help="first N traces in view")
    parser.add_argument("--visible-start", type=int, default=0,
                        help="index of the first visible trace")
    parser.add_argument("--reps", type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.objects <= args.traces or args.reps < 1:
        parser.error("require 1 <= objects <= traces and reps >= 1")
    visible = args.traces if args.visible is None else args.visible
    if not 1 <= visible <= args.traces or not 0 <= args.visible_start <= args.traces - visible:
        parser.error("visible range must fall within the section's traces")

    layer_class = TraceLayer
    if args.source:
        spec = importlib.util.spec_from_file_location("baseline_trace_layer", args.source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        layer_class = module.TraceLayer

    app = QApplication.instance() or QApplication(["bench"])
    options = {"fill_opacity": 0.35, "show_ztraces": False,
               "show_flags": "none", "flag_size": 10}
    series = SimpleNamespace(alignment="default", window=[0, 0, 100, 100],
                             ztraces={}, getOption=options.__getitem__)
    section = Section.__new__(Section)
    section.series, section.mag = series, 1
    section.tforms = {"default": Transform.identity()}
    section.contours = {}
    for i in range(args.traces):
        name = f"object-{i % args.objects}"
        trace = Trace(name, ((i * 31) % 256, (i * 61) % 256, (i * 97) % 256), True)
        in_view = args.visible_start <= i < args.visible_start + visible
        x, y = i % 100 + (0 if in_view else 1000), (i // 100) % 100
        trace.points = [(x, y), (x + 0.6, y), (x + 0.3, y + 0.6)]
        trace.fill_mode = ("transparent", "always")
        if name not in section.contours:
            section.contours[name] = Contour(name)
        section.contours[name].append(trace)
    section.selected_traces = section.tracesAsList()[::20]
    section.temp_hide, section.traces_group_hide = [], []
    section.removed_traces, section.added_traces, section.flags = [], [], []
    layer = layer_class(section, series)
    expected = layer.generateTraceLayer((1000, 1000), series.window).toImage()
    expected_pixels = bytes(expected.constBits())
    for full in (False, True):
        times = []
        for i in range(args.reps + 1):
            start = time.perf_counter()
            frame = layer.generateTraceLayer((1000, 1000), series.window, window_moved=full)
            elapsed = time.perf_counter() - start
            if i:  # warm up each render mode once
                times.append(elapsed * 1000)
        image = frame.toImage()
        pixels = bytes(image.constBits())
        assert pixels == expected_pixels
        print(json.dumps({"source": str(args.source) if args.source else "current",
                          "traces": args.traces, "objects": args.objects,
                          "visible": visible, "visible_start": args.visible_start, "full": full,
                          "median_ms": statistics.median(times), "samples_ms": times,
                          "pixels_sha256": hashlib.sha256(pixels).hexdigest()}), flush=True)
    app.quit()


if __name__ == "__main__":
    main()
