#!/usr/bin/env python
"""Time forward section changes, including load, undo baseline, image and paint.

Run from the checkout root with PYTHONPATH=., in the installed test environment:
  python benchmarks/bench_section_paging.py --fixture /path/to/scratch --prepare
  python benchmarks/bench_section_paging.py --fixture /path/to/scratch
  python benchmarks/bench_section_paging.py --fixture /path/to/scratch --compare
  python benchmarks/bench_section_paging.py --fixture /path/to/scratch --profile

Preparation writes 125 sections with 4,400 eighty-point traces each and TIFFs.
The fixture is synthetic, with identical geometry on each section. Startup and
preparation are excluded. Each measured change visits a new section, rather
than flickering the cached A/B pair. Settings use isolated files. No lists are
open, and the main-window callbacks are stubs. Painting uses offscreen Qt.
Delete the fixture directory when finished.
"""

import argparse
import cProfile
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import pstats
import statistics
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def isolate_settings(directory):
    """Redirect before importing PyReconstruct, including raw Qt callers."""
    from PySide6 import QtCore

    original = QtCore.QSettings

    class ScratchSettings(original):
        def __init__(self, org, app):
            super().__init__(str(directory / f"{org}-{app}.ini"), original.IniFormat)

    QtCore.QSettings = ScratchSettings


def prepare(directory, sections, traces, points):
    import numpy as np
    import tifffile

    from PyReconstruct.modules.constants import fast_dumps
    from PyReconstruct.modules.datatypes import Section, Series

    directory.mkdir(parents=True, exist_ok=False)
    # A deterministic textured image, with a different file for each section.
    image = np.random.default_rng(1003).integers(0, 256, (2048, 2048), dtype=np.uint8)
    series = Series.getEmptyDict()
    series.update(src_dir=str(directory), current_section=0, window=[0, 0, 100, 62.5])
    (directory / "paging.ser").write_text(json.dumps(series))
    (directory / "existing_log.csv").write_text("Date, Time, User, Obj, Sections, Event")
    section = Section.getEmptyDict()
    section["mag"] = 100 / 2048
    angles = np.arange(points) * (2 * np.pi / points)
    columns = math.ceil(math.sqrt(traces * 1.76))
    rows = math.ceil(traces / columns)
    for i in range(traces):
        x = 1 + (i % columns) * 98 / columns
        y = 1 + (i // columns) * 60 / rows
        section["contours"][f"object-{i}"] = [[
            (x + 0.35 * np.cos(angles)).tolist(),
            (y + 0.35 * np.sin(angles)).tolist(),
            [i * 31 % 256, i * 61 % 256, i * 97 % 256],
            True, False, False, ["none", "none"], [],
        ]]
    size = 0
    for n in range(sections):
        section["src"] = f"image-{n}.tif"
        tifffile.imwrite(directory / section["src"], image)
        data = fast_dumps(section)
        (directory / f"paging.{n}").write_bytes(data)
        size += len(data)
    metadata = dict(sections=sections, traces=traces, points=points, section_bytes=size)
    (directory / "fixture.json").write_text(json.dumps(metadata))
    print(json.dumps(metadata), flush=True)


def build_field(directory, metadata):
    from PySide6.QtWidgets import QMainWindow

    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes import Series
    from PyReconstruct.modules.gui.main.field_widget import FieldWidget
    from PyReconstruct.modules.gui.main.status_readout import FieldStatusReadout

    class Palette:
        mode_x = 0.0

        def setScale(self):
            pass

        def resize(self):
            pass

    class Window(QMainWindow):
        mouse_palette = Palette()
        zarr_palette = None
        viewer = None
        field_menu = None
        label_menu = None
        lefthanded_act = None
        is_zooming = False
        zoom_factor = 1.0

        def checkActions(self):
            pass

        def seriesModified(self, *args):
            pass

        def seriesTransitionRunning(self):
            return False

    series = Series(str(directory / "paging.ser"),
                    {n: f"paging.{n}" for n in range(metadata["sections"])})
    series.setProgressReporter(NullProgressReporter)
    window = Window()
    window.resize(1600, 1020)
    window.statusbar = window.statusBar()
    window.status_readout = FieldStatusReadout()
    window.statusbar.addPermanentWidget(window.status_readout)
    field = FieldWidget(series, window)
    window.field = field
    field.generateView(update=False)
    return window, series, field


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--sections", type=int, default=125)
    parser.add_argument("--traces", type=int, default=4400)
    parser.add_argument("--points", type=int, default=80)
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--compare", action="store_true",
                        help="probe pausing cyclic collection during each section load")
    parser.add_argument("--runs", type=int, default=5, help="runs per side when comparing")
    args = parser.parse_args()
    if args.sections < 2 or args.traces < 1 or args.points < 3:
        parser.error("require at least two sections, one trace and three points")
    with tempfile.TemporaryDirectory(prefix="paging-settings-") as settings:
        isolate_settings(Path(settings))
        if args.prepare:
            prepare(args.fixture, args.sections, args.traces, args.points)
            return

        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication
        from PyReconstruct.modules.backend.view.image_layer import dropReadAhead
        from PyReconstruct.modules.datatypes import Series, collector
        from PyReconstruct.modules.datatypes.series import _collectorPaused
        from PyReconstruct.modules.backend.func.state_manager import SectionStates
        from PyReconstruct.modules.backend.view.section_layer import SectionLayer
        from PyReconstruct.modules.backend.view.image_layer import ImageLayer
        from PyReconstruct.modules.backend.view.trace_layer import TraceLayer

        sides = [("current", Series.loadSection)]
        if args.compare:
            sides = [("before", Series.loadSection),
                     ("paused", _collectorPaused()(Series.loadSection))] * args.runs

        metadata = json.loads((args.fixture / "fixture.json").read_text())
        if args.steps < 1 or args.runs < 1 or args.steps * len(sides) >= metadata["sections"]:
            parser.error("require positive steps and runs, with fewer total steps than sections")
        app = QApplication.instance() or QApplication(["paging-benchmark"])
        window, series, field = build_field(args.fixture, metadata)
        frame = QPixmap(*field.pixmap_dim)
        field.render(frame)  # deliver the initial resize before timing paging
        collector.settleAfterOpen(series)  # MainWindow.openSeries does this too
        expected_hash = None
        phases = {}

        def record(function, phase):
            def timed(*a, **kw):
                start = time.perf_counter()
                result = function(*a, **kw)
                phases.setdefault(phase, []).append(1000 * (time.perf_counter() - start))
                return result
            return timed

        layer_init = SectionLayer.__init__
        state_init = SectionStates.initialize
        image_view = ImageLayer.generateImageLayer
        trace_view = TraceLayer.generateTraceLayer
        SectionLayer.__init__ = record(layer_init, "image_load")
        SectionStates.initialize = record(state_init, "undo_baseline")
        ImageLayer.generateImageLayer = record(image_view, "image")
        TraceLayer.generateTraceLayer = record(trace_view, "traces")
        field.generateView = record(field.generateView, "view")
        profiler = cProfile.Profile()
        collections = []
        gc_start = 0

        def collection_time(phase, info):
            nonlocal gc_start
            if phase == "start":
                gc_start = time.perf_counter()
            else:
                collections.append((info["generation"], time.perf_counter() - gc_start))

        if args.profile:
            gc.callbacks.append(collection_time)
            profiler.enable()
        for run, (side, load) in enumerate(sides):
            load_times = []
            collection_start = len(collections)
            phases = {}

            def timed_load(number):
                start = time.perf_counter()
                section = load(series, number)
                load_times.append(1000 * (time.perf_counter() - start))
                return section

            series.loadSection = timed_load
            samples, hashes, visible = [], [], []
            for n in range(1 + run * args.steps, 1 + (run + 1) * args.steps):
                start = time.perf_counter()
                field.changeSection(n)
                paint_start = time.perf_counter()
                field.render(frame)
                end = time.perf_counter()
                samples.append(1000 * (end - start))
                phases.setdefault("paint", []).append(1000 * (end - paint_start))
                # Assertions and hashes are outside the timed region.
                assert series.current_section == field.section.n == n
                assert field.section_layer.image_found
                assert series.sections[n] == f"paging.{n}"
                assert field.series_states[n].initialized
                assert len(field.section.tracesAsList()) == metadata["traces"]
                count = len(field.section_layer.traces_in_view)
                assert count == metadata["traces"]
                visible.append(count)
                digest = hashlib.sha256(bytes(frame.toImage().constBits())).hexdigest()
                if expected_hash is None:
                    expected_hash = digest
                assert digest == expected_hash, "identical sections must paint identical pixels"
                hashes.append(digest)
            print(json.dumps(dict(metadata, side=side, run=run,
                                  python=sys.version.split()[0],
                                  median_ms=statistics.median(samples),
                                  samples_ms=samples, section_load_ms=load_times,
                                  phases_ms=phases,
                                  pixels_sha256=hashes, traces_in_view=visible,
                                  gc_seconds={g: sum(t for gen, t in collections[collection_start:]
                                                    if gen == g) for g in range(3)},
                                  errors=0)), flush=True)
        if args.profile:
            profiler.disable()
            gc.callbacks.remove(collection_time)
            print("gc_seconds_by_generation", {
                g: sum(t for generation, t in collections if generation == g)
                for g in range(3)
            })
            pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(35)
            pstats.Stats(profiler).strip_dirs().sort_stats("tottime").print_stats(25)
        del series.loadSection
        SectionLayer.__init__ = layer_init
        SectionStates.initialize = state_init
        ImageLayer.generateImageLayer = image_view
        TraceLayer.generateTraceLayer = trace_view
        field.timer.stop()
        dropReadAhead()
        collector.restore(series)
        window.deleteLater()
        app.quit()


if __name__ == "__main__":
    main()
