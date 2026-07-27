#!/usr/bin/env python
"""Build a larger .jser from a real one by replicating its sections.

Why this exists
---------------
The modernization plan's Phase 0 requires re-measuring the two >700 MB series
that produced the struck headline memory figures (crop_4, 701 MB and
crop_ROIsmall, 1400 MB). Those two files no longer exist on the benchmark
machine, and the plan's own open question #7 asks for a reproducible
large-series fixture instead of files that live on exactly one disk.

This script takes a real autoseg series and replicates its section list N times,
renumbering sections so the result is a valid series with N x the sections and
N x the traces. Trace geometry, tag vocabulary, object naming and the
positional row layout are all inherited from real data, so the per-trace work
that `SeriesData.refresh()` does is representative -- it is the *volume* that is
synthetic, not the shape of the data.

What it is NOT: an independent sample. Replicated sections make objects that
span N times as many sections, so results should be read as "a series with this
many sections and traces", not "a different specimen".

Usage:
    python make_scaled_series.py IN.jser OUT.jser --factor 3
    python make_scaled_series.py IN.jser OUT.jser --target-mb 700
"""
import argparse, json, os, sys, time


def load_json(path):
    """Load with orjson when available (much faster on multi-hundred-MB files)."""
    try:
        import orjson
        with open(path, "rb") as f:
            return orjson.loads(f.read())
    except ImportError:
        with open(path, "rb") as f:
            return json.loads(f.read())


def dump_json(obj, path):
    try:
        import orjson
        with open(path, "wb") as f:
            f.write(orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS))
    except ImportError:
        with open(path, "w") as f:
            json.dump(obj, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--factor", type=int, help="replicate the section list this many times")
    g.add_argument("--target-mb", type=float, help="pick the factor that lands nearest this size")
    args = ap.parse_args()

    src_mb = os.path.getsize(args.src) / (1 << 20)
    factor = args.factor or max(1, round(args.target_mb / src_mb))
    print(f"source {os.path.basename(args.src)}: {src_mb:.1f} MB -> factor {factor} "
          f"(~{src_mb * factor:.0f} MB)", flush=True)

    t0 = time.perf_counter()
    data = load_json(args.src)
    print(f"parsed in {time.perf_counter() - t0:.1f}s", flush=True)

    if not isinstance(data, dict) or "sections" not in data or "series" not in data:
        print("FATAL: source is not a modern .jser (need top-level 'sections' and "
              "'series' keys). Legacy layouts are not supported here -- open and "
              "re-save it in PyReconstruct first.", file=sys.stderr)
        return 2

    sections = data["sections"]
    real = [s for s in sections if s is not None]
    print(f"sections: {len(sections)} slots, {len(real)} populated", flush=True)

    # Replicate. Sections are a positional array indexed by section number, so
    # the copies simply continue the numbering. The section dicts are reused by
    # reference: nothing here mutates them, and the serializer only reads.
    out_sections = list(sections)
    for _ in range(factor - 1):
        out_sections.extend(real)
    data["sections"] = out_sections

    # The series dict carries per-section state that must cover the new range.
    ser = data["series"]
    for key in ("current_section",):
        if key in ser and isinstance(ser[key], int):
            ser[key] = 0
    # alignment/section-specific maps keyed by section number, if present
    for key, val in list(ser.items()):
        if isinstance(val, dict) and val and all(
                isinstance(k, str) and k.lstrip("-").isdigit() for k in val):
            base = dict(val)
            n_real = len(real)
            for rep in range(1, factor):
                for k, v in base.items():
                    ser[key][str(int(k) + rep * n_real)] = v

    t0 = time.perf_counter()
    dump_json(data, args.dst)
    print(f"wrote {args.dst}: {os.path.getsize(args.dst) / (1 << 20):.1f} MB "
          f"in {time.perf_counter() - t0:.1f}s "
          f"({len(out_sections)} section slots)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
