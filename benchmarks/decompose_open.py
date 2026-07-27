#!/usr/bin/env python
"""Decompose the cost of opening a series at REAL scale.

Why: an independent audit of the shipped 560 KB `class_series.jser` (198
sections) found `openJser` at 71.6 ms with the JSON codec only 6.1 ms of it
(8%), concluding that ~90% of open is the per-section unpack/repack
choreography plus Python object construction. That conclusion drives a decision
about restructuring the on-disk format, so it needs checking at the scale where
the pain actually is -- hundreds of MB and hundreds of thousands of traces, not
a half-megabyte fixture.

This script measures, against an already-unpacked hidden dir (i.e. the warm
path, where no .jser JSON is touched at all):

  A  read  -- read every section file's bytes, nothing else       (pure I/O)
  B  decode-- fast_loads each section file                        (JSON codec)
  C  build -- construct the Section objects (Trace/Contour/Transform)
  D  full  -- SeriesData.refresh()

plus, separately, the whole-file .jser codec cost, so the codec's share of a
COLD open can be stated rather than inferred.

IMPORTANT about D: `SeriesData.refresh()` is NOT geometry alone. It iterates
`series.enumerateSections()`, whose `SeriesIterator.__next__` calls
`series.loadSection()` -> `Section(n, series)`, and `loadSection` does not cache
(series.py:954-963). So refresh re-reads, re-decodes and re-builds every section
from disk on top of computing geometry. D therefore contains A+B+C again, and
geometry proper is reported as D - (A+B+C). A warm `openJser` runs exactly one
such pass, which is why D approximates a warm open rather than adding to it.

Usage:
    python decompose_open.py SERIES.jser [--keep]
"""
import argparse, os, shutil, sys, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def hidden_dir_for(jser_path):
    sdir = os.path.dirname(os.path.abspath(jser_path))
    sname = os.path.basename(jser_path)
    sname = sname[:sname.rfind(".")]
    hidden = os.path.join(sdir, f".{sname}")
    return hidden, os.path.join(hidden, f"{sname}.ser")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jser")
    ap.add_argument("--keep", action="store_true",
                    help="leave the hidden unpack dir in place afterwards")
    args = ap.parse_args()

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["decompose"])

    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.section import Section
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.constants.fast_json import fast_loads
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    jser = os.path.abspath(args.jser)
    size_mb = os.path.getsize(jser) / (1 << 20)
    hidden, ser_fp = hidden_dir_for(jser)

    # ---- whole-file .jser codec cost, on its own -------------------------
    with open(jser, "rb") as f:
        raw = f.read()
    t0 = time.perf_counter()
    doc = fast_loads(raw)
    t_codec = time.perf_counter() - t0
    n_slots = len(doc.get("sections", []))
    del doc, raw

    # ---- make sure we have a warm hidden dir -----------------------------
    fresh = not (os.path.isdir(hidden) and os.path.isfile(ser_fp))
    if fresh:
        t0 = time.perf_counter()
        primer = Series.openJser(jser, progress=NullProgressReporter)
        t_cold_open = time.perf_counter() - t0
        # Do NOT call primer.close(): on the cold path leave_open is False and
        # close() deletes the hidden dir we just paid to build. Mark it so any
        # later cleanup is ours to decide, then drop the reference.
        primer.leave_open = True
        del primer
    else:
        t_cold_open = None

    # ---- A: raw read of every section file -------------------------------
    files = [os.path.join(hidden, f) for f in sorted(os.listdir(hidden))
             if f.rsplit(".", 1)[-1].isnumeric()]
    payloads = []
    t0 = time.perf_counter()
    for fp in files:
        with open(fp, "rb") as f:
            payloads.append(f.read())
    t_read = time.perf_counter() - t0
    section_bytes = sum(len(p) for p in payloads)

    # ---- B: JSON decode of every section file ----------------------------
    t0 = time.perf_counter()
    decoded = [fast_loads(p) for p in payloads]
    t_decode = time.perf_counter() - t0
    n_traces = sum(len(v) for d in decoded
                   for v in d.get("contours", {}).values())
    del decoded, payloads

    # ---- C: Section object construction ----------------------------------
    series = Series(ser_fp, {}, get_series_data=False)
    series.jser_fp = jser
    series.sections = {}
    for f in os.listdir(hidden):
        ext = f.rsplit(".", 1)[-1]
        if ext.isnumeric():
            series.sections[int(ext)] = f
    t0 = time.perf_counter()
    sections = [Section(n, series) for n in sorted(series.sections)]
    t_build = time.perf_counter() - t0

    # ---- D: geometry -----------------------------------------------------
    sd = SeriesData(series)
    t0 = time.perf_counter()
    sd.refresh()
    t_full = time.perf_counter() - t0

    if fresh and not args.keep:
        shutil.rmtree(hidden, ignore_errors=True)

    rebuild = t_read + t_decode + t_build
    t_geom_only = t_full - rebuild           # refresh re-does A+B+C internally
    print()
    print(f"series          {os.path.basename(jser)}")
    print(f"jser size       {size_mb:,.1f} MB   section slots {n_slots}   "
          f"section files {len(files)} ({section_bytes / (1 << 20):,.1f} MB)")
    print(f"traces          {n_traces:,}")
    if t_cold_open is not None:
        print(f"cold openJser   {t_cold_open:8.2f} s   (reference)")
    print()
    print("One pass over every section (what a warm open costs):")
    print(f"{'  stage':36s} {'seconds':>9s}  {'% of the pass':>14s}")
    print("-" * 64)
    for name, t in (("A  read section files (pure I/O)", t_read),
                    ("B  fast_loads section files (codec)", t_decode),
                    ("C  build Section/Trace objects", t_build),
                    ("D  geometry (derived, see below)", t_geom_only)):
        print(f"  {name:34s} {t:9.2f}  {t / t_full * 100:13.1f}%")
    print(f"  {'= SeriesData.refresh() total':34s} {t_full:9.2f}  {100.0:13.1f}%")
    print()
    print(f"  refresh() measured               {t_full:9.2f} s")
    print(f"  minus its internal re-read+decode+build (A+B+C) {rebuild:6.2f} s")
    print(f"  = geometry proper                {t_geom_only:9.2f} s")
    print("  (refresh() calls loadSection() per section and loadSection does not")
    print("   cache, so it repeats A+B+C on top of computing geometry.)")
    print()
    print(f"whole-file .jser codec alone      {t_codec:9.2f} s")
    if t_cold_open:
        print(f"  -> {t_codec / t_cold_open * 100:.1f}% of the cold openJser above")
    print(f"both codec passes together        {t_codec + t_decode:9.2f} s")
    if t_cold_open:
        print(f"  -> {(t_codec + t_decode) / t_cold_open * 100:.1f}% of the cold openJser")
    print()
    print("Read this as: a change to the *serialization format* can only attack "
          "the codec\nrows. Object construction and geometry are Python/NumPy "
          "cost and survive it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
