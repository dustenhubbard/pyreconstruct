#!/usr/bin/env python
"""Benchmark one (checkout, jser) in a fresh interpreter. Emits JSON.

Usage: harness.py <checkout_dir> <jser_path> <out_json>

Times jser OPEN (Series.openJser), REFRESH (SeriesData.refresh -> per-trace
geometry), and SAVE (saveJser to a temp dir). Records peak RSS, the resident
set size at each phase boundary, and equivalence digests.

The checkout's PyReconstruct is imported via sys.path so fork/origin/baseline
each run their own code unchanged.

CACHE STATE (load-bearing -- see benchmarks/REPORT.md "Correction")
------------------------------------------------------------------
`Series.openJser` short-circuits: if a hidden unpack directory ``.<name>/``
containing ``<name>.ser`` sits next to the .jser, it builds the Series
straight from those per-section files and never parses the .jser at all
(series.py:239-258). Otherwise it parses the whole JSON and writes the hidden
dir (series.py:332 onward). Those are two different workloads with different
peak memory, and they must never be averaged together.

This harness does not manage the hidden dir -- the orchestrator does. What the
harness does is *observe* which path openJser is about to take and report it
as ``cache_state`` ("cold" = full parse + unpack, "warm" = hidden-dir fast
path). The orchestrator asserts the observed state matches the state it
intended, so a mislabelled rep is a hard error instead of a silent average.
"""
import os, sys, json, time, resource, tempfile, shutil, zlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def hidden_dir_for(jser_path):
    """Return (hidden_dir, ser_file) that PyReconstruct would use for this jser."""
    sdir = os.path.dirname(os.path.abspath(jser_path))
    sname = os.path.basename(jser_path)
    sname = sname[:sname.rfind(".")]
    hidden = os.path.join(sdir, f".{sname}")
    return hidden, os.path.join(hidden, f"{sname}.ser")


def observed_cache_state(jser_path):
    """"warm" if openJser will take the hidden-dir fast path, else "cold"."""
    hidden, ser = hidden_dir_for(jser_path)
    return "warm" if (os.path.isdir(hidden) and os.path.isfile(ser)) else "cold"


def rss_mb():
    """Current resident set size in MB (not the peak)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return None


def peak_rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main():
    checkout, jser, out = sys.argv[1], sys.argv[2], sys.argv[3]

    # Observed BEFORE anything touches the file, so it describes the run we are
    # about to do rather than the state we leave behind.
    cache_state = observed_cache_state(jser)

    res = {
        "checkout": checkout,
        "jser": os.path.basename(jser),
        "cache_state": cache_state,
        "ok": False,
    }
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

        res["rss_baseline_mb"] = rss_mb()

        t0 = time.perf_counter()
        series = Series.openJser(jser)
        t_open = time.perf_counter() - t0
        res["rss_after_open_mb"] = rss_mb()
        res["peak_rss_after_open_mb"] = peak_rss_mb()

        sd = SeriesData(series)
        t0 = time.perf_counter()
        sd.refresh()
        t_refresh = time.perf_counter() - t0
        res["rss_after_refresh_mb"] = rss_mb()

        # Equivalence digests.
        #
        # Summed area/length/radius are kept for continuity with earlier runs,
        # but they are a WEAK check: two per-trace errors of opposite sign
        # cancel in the sum. `trace_digest` is an order-insensitive commutative
        # accumulation of per-trace CRC32s, so a change in one trace cannot be
        # cancelled by a change in another. It is deliberately O(1) in memory:
        # collecting per-trace values into a list would inflate the very peak
        # RSS this harness exists to measure.
        #
        # Neither is a gate. Per the modernization plan, equivalence gating
        # belongs in tests/test_perf_equivalence.py against in-repo fixtures;
        # benchmarks/ is an optional local perf study and cannot gate anything.
        objs = sd.data["objects"]
        n_obj, n_tr = len(objs), 0
        s_area = s_len = s_rad = 0.0
        digest = 0
        for od in objs.values():
            for tds in od.traces.values():
                for td in tds:
                    n_tr += 1
                    a, l, r = abs(float(td.area)), float(td.length), float(td.radius)
                    s_area += a
                    s_len += l
                    s_rad += r
                    digest = (digest + zlib.crc32(f"{a:.9g}|{l:.9g}|{r:.9g}".encode())) & 0xFFFFFFFFFFFFFFFF
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
            trace_digest=digest,
            peak_rss_mb=peak_rss_mb(),
        )
    except Exception as e:
        import traceback
        res.update(ok=False, error=repr(e), traceback=traceback.format_exc()[-1500:],
                   peak_rss_mb=peak_rss_mb())

    with open(out, "w") as f:
        json.dump(res, f)
    safe = {k: v for k, v in res.items() if k != "traceback"}
    print(json.dumps(safe))


if __name__ == "__main__":
    main()
