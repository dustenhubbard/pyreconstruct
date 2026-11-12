#!/usr/bin/env python
"""Time forward section changes, including load, undo baseline, image and paint.

Run from the checkout root with PYTHONPATH=., in the installed test environment:
  python benchmarks/bench_section_paging.py --fixture /path/to/scratch --prepare
  python benchmarks/bench_section_paging.py --fixture /path/to/scratch
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
import hashlib
import json
import math
import os
from pathlib import Path
import pstats
import statistics
import sys
import subprocess
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
    parser.add_argument("--idle-ms", type=int, default=350)
    parser.add_argument("--label", default="current")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--allocation-probe", action="store_true")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    if args.sections < 3 or args.traces < 1 or args.points < 3:
        parser.error("require three sections, one trace, and three points")
    if args.runs < 1 or args.idle_ms < 0:
        parser.error("runs must be positive and idle time nonnegative")
    if args.compare:
        if args.output is None or args.runs < 1:
            parser.error("--compare requires --output and positive --runs")
        expected_frames = None
        with args.output.open("w") as stream:
            for run in range(args.runs):
                for side, root in zip(("before", "after"), args.compare):
                    env = dict(os.environ, PYTHONPATH=str(root.resolve()))
                    load = os.getloadavg()
                    result = subprocess.run([
                        sys.executable, str(Path(__file__).resolve()),
                        "--fixture", str(args.fixture.resolve()), "--label", side,
                        "--steps", str(args.steps), "--idle-ms", str(args.idle_ms),
                    ], cwd=root, env=env, capture_output=True, text=True)
                    if result.returncode:
                        print(result.stderr, file=sys.stderr)
                        result.check_returncode()
                    row = json.loads(result.stdout)
                    if expected_frames is None:
                        expected_frames = row["pixels_sha256"]
                    assert row["pixels_sha256"] == expected_frames, "before/after pixels differ"
                    row.update(run=run, load_before=load, load_after=os.getloadavg())
                    stream.write(json.dumps(row) + "\n")
                    stream.flush()
                    print(side, run, round(row["median_ms"], 1), "ms",
                          round(row["rss_paging_peak_bytes"] / 2**20, 1), "MiB",
                          "hits", sum(row["prepared_hits"]), flush=True)
        return
    with tempfile.TemporaryDirectory(prefix="paging-settings-") as settings:
        isolate_settings(Path(settings))
        if args.prepare:
            prepare(args.fixture, args.sections, args.traces, args.points)
            return

        import resource
        import threading
        if args.allocation_probe:
            import gc
            import tracemalloc
            from PyReconstruct.modules.datatypes.section_read_ahead import readSection

            path = str(args.fixture / "paging.2")
            # Warm imports and allocator caches before tracing allocations.
            prepared = readSection(path, 2)
            del prepared
            gc.collect()
            records = []
            for run in range(args.runs):
                tracemalloc.start()
                before, _ = tracemalloc.get_traced_memory()
                prepared = readSection(path, 2)
                traces = sum(len(contour) for contour in prepared.contours.values())
                points = sum(len(trace.points) for contour in prepared.contours.values()
                             for trace in contour)
                held, peak = tracemalloc.get_traced_memory()
                del prepared
                gc.collect()
                dropped, _ = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                records.append(dict(run=run, traces=traces, points=points,
                                    held_bytes=held-before, peak_bytes=peak-before,
                                    after_drop_bytes=dropped-before))
            print(json.dumps(records), flush=True)
            return

        from PySide6.QtCore import QTimer, QEventLoop
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication
        from PyReconstruct.modules.backend.view.image_layer import dropReadAhead
        from PyReconstruct.modules.datatypes import collector
        from PyReconstruct.modules.backend.func.state_manager import SectionStates
        from PyReconstruct.modules.backend.view.section_layer import SectionLayer
        from PyReconstruct.modules.backend.view.image_layer import ImageLayer
        from PyReconstruct.modules.backend.view.trace_layer import TraceLayer

        metadata = json.loads((args.fixture / "fixture.json").read_text())
        if not 0 < args.steps < metadata["sections"] - 1:
            parser.error("steps must leave room for a warmup and a neighbor")
        app = QApplication.instance() or QApplication(["paging-benchmark"])
        window, series, field = build_field(args.fixture, metadata)
        frame = QPixmap(*field.pixmap_dim)
        field.render(frame)
        collector.settleAfterOpen(series)
        # Enter the paging direction before sampling the same fresh sections.
        field.changeSection(1)
        field.render(frame)
        phases = {}

        def record(function, phase):
            def timed(*a, **kw):
                start = time.perf_counter()
                result = function(*a, **kw)
                phases.setdefault(phase, []).append(1000 * (time.perf_counter() - start))
                return result
            return timed

        for cls, name, phase in (
            (SectionLayer, "__init__", "image_load"),
            (SectionStates, "initialize", "undo_baseline"),
            (ImageLayer, "generateImageLayer", "image"),
            (TraceLayer, "generateTraceLayer", "traces"),
        ):
            setattr(cls, name, record(getattr(cls, name), phase))
        field.generateView = record(field.generateView, "view")
        series.loadSection = record(series.loadSection, "section_load")

        hits = []
        slot = None
        try:
            from PyReconstruct.modules.datatypes.section_read_ahead import READ_AHEAD
            slot = READ_AHEAD
        except ImportError:
            pass
        if slot is not None:
            take = slot.take

            def counted_take(*args):
                result = take(*args)
                hits.append(result is not None)
                return result

            slot.take = counted_take

        def rss():
            # Linux current RSS, unlike ru_maxrss which includes startup.
            return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")

        rss_samples = []
        stop = threading.Event()

        def sample_memory():
            while not stop.is_set():
                rss_samples.append(rss())
                stop.wait(0.005)

        sampler = threading.Thread(target=sample_memory)
        sampler.start()
        idle_gaps, resident = [], []
        last_tick = time.perf_counter()

        def tick():
            nonlocal last_tick
            now = time.perf_counter()
            idle_gaps.append(1000 * (now - last_tick))
            last_tick = now

        heartbeat = QTimer()
        heartbeat.setInterval(5)
        heartbeat.timeout.connect(tick)
        samples, hashes, visible = [], [], []
        expected_hash = None
        profiler = cProfile.Profile()
        if args.profile:
            profiler.enable()
        try:
            for n in range(2, args.steps + 2):
                last_tick = time.perf_counter()
                heartbeat.start()
                idle_loop = QEventLoop()
                idle_end = QTimer()
                idle_end.setSingleShot(True)
                idle_end.timeout.connect(idle_loop.quit)
                idle_end.start(args.idle_ms)
                idle_loop.exec()
                heartbeat.stop()
                resident.append(rss())
                start = time.perf_counter()
                field.changeSection(n)
                paint_start = time.perf_counter()
                field.render(frame)
                end = time.perf_counter()
                samples.append(1000 * (end - start))
                phases.setdefault("paint", []).append(1000 * (end - paint_start))
                assert series.current_section == field.section.n == n
                assert field.section_layer.image_found
                assert field.series_states[n].initialized
                assert len(field.section.tracesAsList()) == metadata["traces"]
                count = len(field.section_layer.traces_in_view)
                assert count == metadata["traces"]
                visible.append(count)
                digest = hashlib.sha256(bytes(frame.toImage().constBits())).hexdigest()
                if expected_hash is None:
                    expected_hash = digest
                assert digest == expected_hash
                hashes.append(digest)
        finally:
            stop.set()
            sampler.join()
        if args.profile:
            profiler.disable()
        print(json.dumps(dict(
            metadata, side=args.label, python=sys.version.split()[0],
            idle_ms=args.idle_ms, median_ms=statistics.median(samples),
            samples_ms=samples, phases_ms=phases, pixels_sha256=hashes,
            traces_in_view=visible, prepared_hits=hits, errors=0,
            idle_gap_max_ms=max(idle_gaps, default=0),
            idle_gap_p95_ms=sorted(idle_gaps)[int(len(idle_gaps) * .95)] if idle_gaps else 0,
            rss_idle_bytes=resident, rss_paging_peak_bytes=max(rss_samples),
            process_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        )), flush=True)
        if args.profile:
            pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(25)
        field.timer.stop()
        if slot is not None:
            field.section_read_timer.stop()
            slot.drop()
            worker = slot._worker
            if worker is not None:
                worker.join()
        dropReadAhead()
        collector.restore(series)
        window.deleteLater()
        app.quit()


if __name__ == "__main__":
    main()
