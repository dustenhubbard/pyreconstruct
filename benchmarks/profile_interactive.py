#!/usr/bin/env python
"""Profile a scripted interactive session offscreen: open -> pan/zoom -> hover
-> lasso -> knife -> merge.

This exists to satisfy Phase 0 item 2 of dev/REFACTOR_PLAN.md: the interactive
profile is the *only* admissible evidence for a Phase 2 Rust candidate, so it
must drive the real widget code rather than a reimplementation of it.

What it drives (all verified entry points, not reimplementations):
  frames_full        FieldWidgetBase.generateView(generate_image=True)
                       -> SectionLayer.generateView -> ImageLayer.generateImageLayer
                          + TraceLayer.generateTraceLayer with window_moved=True
                          (full trace rebuild -- the pan/zoom-style frame)
  frames_incremental generateView(generate_image=False) -> window_moved=False,
                       reusing the traces_in_view cache (the edit-style frame)
  frames_with_paint  generateView + field.render() to force a synchronous
                       paintEvent -> paintText -> the hover getTrace lookup
  pan_sweep          panzoomPress/panzoomMove/panzoomRelease (real re-render)
  zoom_sweep         same, with zoom_factor (mirrors the 1.005**dy wheel factor)
  hover_sweep        TraceLayer.getTrace -> Section.findClosest
  lasso_sweep        TraceLayer.getTraces (the per-point/per-trace loop)
  knife_gesture      FieldWidgetTrace.cutTrace -> calc.grid.cutTraces -> shapely
  merge_gesture      FieldWidgetTrace.mergeTraces -> calc.grid.mergeTraces

Usage:
  # cProfile every phase, ranked by self time
  python profile_interactive.py --jser FIXTURE.jser --mode cprofile

  # one phase, no profiler attached, for py-spy to sample from outside:
  py-spy record -o out.svg -- python profile_interactive.py \
      --jser FIXTURE.jser --mode run --phase frames_full --seconds 30

Notes / hazards handled here (each was a real trap):
  * QT_QPA_PLATFORM=offscreen makes gui.utils.notify() fall through to
    input("Press Enter...") and block forever. notify is imported *by name*
    into three field_widget modules, so each binding is patched.
  * paintText dereferences mainwindow.mouse_palette.mode_x unguarded, so the
    stub palette must carry it.
  * traces_in_view is only populated by generateTraceLayer; without a warmup
    generateView() the hover path silently falls back to tracesAsList(), a
    different and slower path.
  * XDG_CONFIG_HOME is redirected to scratch so the real user QSettings is
    never read or written. QSettingsStore is deliberately KEPT (not swapped for
    DictSettingsStore) because the render loops were tuned around its ~60us
    per-getOption cost; removing it would measure a program that does not ship.
"""
import argparse, math, os, shutil, sys, tempfile, time

SCRATCH = tempfile.mkdtemp(prefix="pyrecon-prof-")
os.environ["QT_QPA_PLATFORM"] = "offscreen"          # must precede PySide6 import
os.environ["XDG_CONFIG_HOME"] = os.path.join(SCRATCH, "cfg")
os.makedirs(os.environ["XDG_CONFIG_HOME"], exist_ok=True)

W, H = 1600, 1000


class Ev:
    """Duck-typed mouse event: the widget code only uses x()/y()/buttons()."""

    def __init__(self, x, y, buttons=1):
        self._x, self._y, self._b = x, y, buttons

    def x(self):
        return self._x

    def y(self):
        return self._y

    def buttons(self):
        return self._b


class _Palette:
    """paintText reads .mode_x unguarded (field_widget_6_paint.py:168)."""
    mode_x = 0.0

    def setScale(self):
        pass

    def incrementButton(self):
        pass

    def resize(self):
        pass

    def updateBC(self):
        pass


def build_stub_mainwindow():
    from PySide6.QtWidgets import QLabel, QMainWindow

    class StubMW(QMainWindow):
        """A real MainWindow cannot be used: its openSeries falls into
        changeSrcDir(notify=True) -> modal FileDialog whenever a series' images
        are absent (main_window.py:786-794). This carries exactly the attributes
        the field widget touches."""

        def __init__(self):
            super().__init__()
            self.setGeometry(0, 0, W, H + 40)
            self.mouse_palette = _Palette()
            self.zarr_palette = None
            self.viewer = None
            self.field = None
            self.field_menu = None
            self.label_menu = None
            self.lefthanded_act = None
            self.is_zooming = False
            self.zoom_factor = 1.0
            self.statusbar = self.statusBar()
            # the real MainWindow's permanent readout widget. Carried here so
            # the profiled paint path is the one that ships: without it,
            # updateStatusBar falls back to showMessage and measures a
            # different write.
            self.status_label = QLabel()
            self.statusbar.addPermanentWidget(self.status_label, 0)

        def checkActions(self, *a, **k):
            pass

        def seriesModified(self, *a, **k):
            pass

        def saveAllData(self, *a, **k):
            pass

        def setPaletteButtonFromObj(self, *a, **k):
            pass

        def createContextMenus(self, *a, **k):
            pass

        def createMenuBar(self, *a, **k):
            pass

        def changeSection(self, *a, **k):
            pass

        def addTo(self, *a, **k):
            pass

        def removeFrom(self, *a, **k):
            pass

        def export(self, *a, **k):
            pass

        def exportAs(self, *a, **k):
            pass

    return StubMW()


def silence_notifications():
    """notify() blocks on stdin under offscreen; it is imported by name into
    three field_widget modules, so patch each binding."""
    import PyReconstruct.modules.gui.utils.utils as gutils
    noop = lambda *a, **k: None
    yes = lambda *a, **k: True
    gutils.notify = noop
    gutils.notifyConfirm = yes
    if hasattr(gutils, "notifyLocked"):
        gutils.notifyLocked = yes
    import PyReconstruct.modules.gui.main.field_widget_2_trace as fw2
    import PyReconstruct.modules.gui.main.field_widget_5_mouse as fw5
    import PyReconstruct.modules.gui.main.field_widget_7_view as fw7
    for m in (fw2, fw5, fw7):
        if hasattr(m, "notify"):
            m.notify = noop
        if hasattr(m, "notifyConfirm"):
            m.notifyConfirm = yes


def fit_window_to_section(series, field, pad=0.05):
    """Zoom the view out to the bounding box of every trace in the current
    section.

    A series' saved window is wherever its author left the cursor, which on the
    lab series is a tight crop showing a handful of traces. Profiling that
    measures an unrepresentatively empty screen. Fitting to the section is the
    "user opens a large series and looks at it" case, and is the honest worst
    case for the trace-render path.
    """
    xs, ys = [], []
    for trace in field.section.tracesAsList():
        pts = trace.points
        if not pts:
            continue
        for x, y in pts:
            xs.append(x)
            ys.append(y)
    if not xs:
        return False
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    w, h = max(xmax - xmin, 1e-6), max(ymax - ymin, 1e-6)
    series.window = [xmin - w * pad, ymin - h * pad, w * (1 + 2 * pad), h * (1 + 2 * pad)]
    field.generateView(update=False)
    return True


def setup(jser_src, copy_siblings=True, fit=False):
    """Copy the series (and any image siblings) into scratch, open it, and build
    a FieldWidget over a stub mainwindow."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["prof"])

    fp = os.path.join(SCRATCH, os.path.basename(jser_src))
    shutil.copyfile(jser_src, fp)
    if copy_siblings:
        srcdir = os.path.dirname(os.path.abspath(jser_src))
        for fn in os.listdir(srcdir):
            if fn.lower().endswith((".tif", ".tiff", ".txt")):
                try:
                    shutil.copyfile(os.path.join(srcdir, fn), os.path.join(SCRATCH, fn))
                except OSError:
                    pass

    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.backend.notifier import NullNotifier

    t0 = time.perf_counter()
    series = Series.openJser(fp, progress=NullProgressReporter)
    t_open = time.perf_counter() - t0
    series.setProgressReporter(NullProgressReporter)

    # The in-repo fixtures carry a stale absolute src_dir from the machine that
    # made them (shapes2.jser still points at a Windows path), so the image
    # layer would report image_found=False and we would profile a blank image
    # layer -- and _generateImage is a large share of frame cost. Repoint
    # src_dir at the scratch copy when that makes the images resolvable.
    if not (series.src_dir or "").endswith("zarr"):
        probe = None
        for snum, sdata in series.sections.items():
            probe = sdata
            break
        if probe is not None:
            cand = os.path.join(SCRATCH, os.path.basename(str(probe)))
            if os.path.isfile(cand) or any(
                    f.lower().endswith((".tif", ".tiff")) for f in os.listdir(SCRATCH)):
                series.src_dir = SCRATCH
    try:
        series.setNotifier(NullNotifier())
    except Exception:
        pass

    t0 = time.perf_counter()
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    t_refresh = time.perf_counter() - t0

    silence_notifications()

    from PyReconstruct.modules.gui.main.field_widget import FieldWidget
    mw = build_stub_mainwindow()
    field = FieldWidget(series, mw)
    mw.field = field
    field.setGeometry(0, 0, W, H)
    field.pixmap_dim = (W, H)

    # Required: populates section_layer.traces_in_view. Without it the hover
    # path silently falls back to tracesAsList() -- a different code path.
    field.generateView(update=False)

    if fit:
        fit_window_to_section(series, field)

    print(f"[setup] {os.path.basename(jser_src)}: open={t_open:.3f}s "
          f"refresh={t_refresh:.3f}s sections={len(series.sections)} "
          f"traces_in_view={len(field.section_layer.traces_in_view)} "
          f"image_found={getattr(field.section_layer, 'image_found', '?')}", flush=True)
    return app, series, field


# --------------------------------------------------------------------------
# phases
# --------------------------------------------------------------------------

def lasso_poly(cx, cy, r, k=64):
    return [(int(cx + r * math.cos(2 * math.pi * i / k)),
             int(cy + r * math.sin(2 * math.pi * i / k))) for i in range(k)]


def make_phases(field, frame):
    cx, cy = W // 2, H // 2

    def frames_full(n=1):
        for _ in range(n):
            field.generateView(generate_image=True, generate_traces=True, update=False)

    def frames_incremental(n=1):
        for _ in range(n):
            field.generateView(generate_image=False, generate_traces=True, update=False)

    def frames_with_paint(n=1):
        for _ in range(n):
            field.generateView(update=False)
            field.render(frame)

    def pan_sweep(n=1):
        for i in range(n):
            dx = 16 if (i // 8) % 2 == 0 else -16
            field.panzoomPress(cx, cy)
            field.panzoomMove(new_x=cx + dx, new_y=cy + dx // 2)
            field.panzoomRelease(new_x=cx + dx, new_y=cy + dx // 2)

    def zoom_sweep(n=1):
        for i in range(n):
            f = 1.005 ** (10 if (i // 6) % 2 == 0 else -10)
            field.panzoomPress(cx, cy)
            field.panzoomMove(zoom_factor=f)
            field.panzoomRelease(zoom_factor=f)

    def hover_sweep(n=1):
        field.lclick = field.rclick = field.mclick = False
        for i in range(n):
            x = 80 + (i * 37) % (W - 160)
            y = 80 + (i * 53) % (H - 160)
            field.mouse_x, field.mouse_y = x, y
            field.section_layer.getTrace(x, y)

    def hover_sweep_full(n=1):
        field.lclick = field.rclick = field.mclick = False
        for i in range(n):
            field.mouse_x = 80 + (i * 37) % (W - 160)
            field.mouse_y = 80 + (i * 53) % (H - 160)
            field.render(frame)

    def lasso_sweep(n=1):
        poly = lasso_poly(cx, cy, min(W, H) // 3)
        for _ in range(n):
            field.section_layer.getTraces(poly)

    def knife_gesture(n=1):
        for _ in range(n):
            closed = [t for t in field.section.tracesAsList() if t.closed]
            if not closed:
                return
            name = closed[0].name
            field.section.selected_traces = [t for t in closed if t.name == name]
            cut = [(x, cy + int(30 * math.sin(x / 50.0))) for x in range(40, W - 40, 8)]
            field.cutTrace(cut)

    def merge_gesture(n=1):
        from collections import defaultdict
        for _ in range(n):
            by = defaultdict(list)
            for t in field.section.tracesAsList():
                if t.closed:
                    by[t.name].append(t)
            grp = next((v for v in by.values() if len(v) > 1), None)
            if not grp:
                return
            field.section.selected_traces = list(grp)
            field.mergeTraces()

    def section_scroll(n=1):
        """Changing section is the other common per-frame path."""
        nums = sorted(field.series.sections.keys())
        if not nums:
            return
        for i in range(n):
            field.changeSection(nums[i % len(nums)])

    def session(n=1):
        """One realistic interactive session, in the order the plan names:
        pan/zoom -> hover -> lasso -> knife -> merge, with frames throughout.
        This is the single profile that the Phase 2 decision gate reads."""
        for _ in range(n):
            frames_full(6)
            pan_sweep(6)
            zoom_sweep(4)
            frames_incremental(10)
            hover_sweep(120)
            hover_sweep_full(6)
            lasso_sweep(3)
            knife_gesture(1)
            merge_gesture(1)
            section_scroll(6)

    return {
        "session": session,
        "frames_full": frames_full,
        "frames_incremental": frames_incremental,
        "frames_with_paint": frames_with_paint,
        "pan_sweep": pan_sweep,
        "zoom_sweep": zoom_sweep,
        "hover_sweep": hover_sweep,
        "hover_sweep_full": hover_sweep_full,
        "lasso_sweep": lasso_sweep,
        "knife_gesture": knife_gesture,
        "merge_gesture": merge_gesture,
        "section_scroll": section_scroll,
    }


# iterations chosen so each phase runs long enough to be sampled meaningfully
DEFAULT_ITERS = {
    "session": 3,
    "frames_full": 40, "frames_incremental": 60, "frames_with_paint": 40,
    "pan_sweep": 30, "zoom_sweep": 24, "hover_sweep": 400,
    "hover_sweep_full": 40, "lasso_sweep": 60, "knife_gesture": 3,
    "merge_gesture": 3, "section_scroll": 30,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jser", required=True)
    ap.add_argument("--mode", choices=("cprofile", "run"), default="cprofile")
    ap.add_argument("--phase", help="run only this phase (repeatable via commas)")
    ap.add_argument("--seconds", type=float,
                    help="in --mode run, loop the phase(s) for at least this long")
    ap.add_argument("--iters", type=int, help="override the iteration count")
    ap.add_argument("--top", type=int, default=25, help="rows of the self-time table")
    ap.add_argument("--dump", help="write cProfile .prof stats here (per phase suffix)")
    ap.add_argument("--no-siblings", action="store_true",
                    help="do not copy .tif siblings (image layer will be blank)")
    ap.add_argument("--fit", action="store_true",
                    help="zoom out to the current section's full trace extent "
                         "(the dense-view worst case) instead of the series' "
                         "saved window")
    args = ap.parse_args()

    from PySide6.QtGui import QPixmap
    app, series, field = setup(args.jser, copy_siblings=not args.no_siblings,
                               fit=args.fit)
    frame = QPixmap(W, H)
    phases = make_phases(field, frame)

    # "session" is the composite end-to-end profile; opt into it explicitly so
    # the default sweep does not run every phase twice.
    wanted = [p for p in phases if p != "session"]
    if args.phase:
        wanted = [p.strip() for p in args.phase.split(",")]
        for p in wanted:
            if p not in phases:
                ap.error(f"unknown phase {p!r}; have {sorted(phases)}")

    if args.mode == "run":
        for name in wanted:
            fn, n = phases[name], args.iters or DEFAULT_ITERS.get(name, 20)
            t0 = time.perf_counter()
            if args.seconds:
                while time.perf_counter() - t0 < args.seconds:
                    fn(n)
            else:
                fn(n)
            print(f"[run] {name}: {time.perf_counter() - t0:.2f}s", flush=True)
    else:
        import cProfile, pstats
        for name in wanted:
            fn, n = phases[name], args.iters or DEFAULT_ITERS.get(name, 20)
            field.generateView(update=False)          # reset view state
            pr = cProfile.Profile()
            t0 = time.perf_counter()
            pr.enable()
            fn(n)
            pr.disable()
            wall = time.perf_counter() - t0
            print(f"\n===== {name}  (n={n}, wall={wall:.3f}s, "
                  f"{wall / max(n, 1) * 1000:.2f} ms/iter) =====", flush=True)
            st = pstats.Stats(pr)
            st.sort_stats("tottime").print_stats(args.top)
            if args.dump:
                st.dump_stats(f"{args.dump}.{name}.prof")

    if getattr(field, "timer", None) is not None:
        try:
            field.timer.stop()
        except Exception:
            pass
    shutil.rmtree(SCRATCH, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
