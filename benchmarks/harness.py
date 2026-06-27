#!/usr/bin/env python
"""Benchmark one (checkout, jser) in a fresh interpreter. Emits JSON.

Usage: harness.py <checkout_dir> <jser_path> <out_json>
Times jser OPEN (Series.openJser), REFRESH (SeriesData.refresh -> per-trace
geometry), and SAVE (saveJser to a temp dir). Also records equivalence metrics
(#sections/#objects/#traces, summed area/length/radius) and peak RSS.
The checkout's PyReconstruct is imported via sys.path so fork/origin/baseline
each run their own code unchanged.
"""
import os, sys, json, time, resource, tempfile, shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

def main():
    checkout, jser, out = sys.argv[1], sys.argv[2], sys.argv[3]
    res = {"checkout": checkout, "jser": os.path.basename(jser), "ok": False}
    try:
        sys.path.insert(0, checkout)
        # provide a version stub if setuptools-scm hasn't written one in the worktree
        vpath = os.path.join(checkout, "PyReconstruct", "_version.py")
        if not os.path.exists(vpath):
            try:
                open(vpath, "w").write("__version__ = '0.0.0+bench'\nversion = __version__\n")
            except Exception:
                pass

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(["bench"])

        from PyReconstruct.modules.datatypes.series import Series
        from PyReconstruct.modules.datatypes.series_data import SeriesData

        t0 = time.perf_counter()
        series = Series.openJser(jser)
        t_open = time.perf_counter() - t0

        sd = SeriesData(series)
        t0 = time.perf_counter()
        sd.refresh()
        t_refresh = time.perf_counter() - t0

        objs = sd.data["objects"]
        n_obj, n_tr = len(objs), 0
        s_area = s_len = s_rad = 0.0
        for od in objs.values():
            for tds in od.traces.values():
                for td in tds:
                    n_tr += 1
                    s_area += abs(float(td.area)); s_len += float(td.length); s_rad += float(td.radius)
        n_sec = len(sd.data["sections"])

        t_save = None
        if not os.environ.get("SKIP_SAVE"):
            tmpd = tempfile.mkdtemp(prefix="pyrbench_")
            try:
                t0 = time.perf_counter()
                series.saveJser(os.path.join(tmpd, "out.jser"))
                t_save = time.perf_counter() - t0
            finally:
                shutil.rmtree(tmpd, ignore_errors=True)

        res.update(
            ok=True, t_open=t_open, t_refresh=t_refresh, t_save=t_save,
            n_sections=n_sec, n_objects=n_obj, n_traces=n_tr,
            sum_area=s_area, sum_length=s_len, sum_radius=s_rad,
            peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        )
    except Exception as e:
        import traceback
        res.update(ok=False, error=repr(e), traceback=traceback.format_exc()[-1500:])

    with open(out, "w") as f:
        json.dump(res, f)
    safe = {k: v for k, v in res.items() if k != "traceback"}
    print(json.dumps(safe))

if __name__ == "__main__":
    main()
