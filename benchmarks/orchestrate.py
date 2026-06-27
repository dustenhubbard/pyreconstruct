#!/usr/bin/env python
"""Run the full benchmark matrix: codepoints x series x reps, each a fresh
subprocess of harness.py. Writes results.jsonl incrementally."""
import os, sys, json, subprocess, time

PY = sys.executable
BENCH = "/home/dusten/projects/testing/bench"
HARNESS = os.path.join(BENCH, "harness.py")
TESTING = "/home/dusten/projects/testing"
RESULTS = os.path.join(BENCH, "results.jsonl")
CP = {"fork": BENCH + "/wt-fork", "baseline": BENCH + "/wt-baseline", "origin": BENCH + "/wt-origin"}

SERIES = [  # (label, relpath, size_mb)
    ("crop_1",        "autoseg_large_slow_3/crop_1_SSVQM__3600-25970-29792_2500-2000-2000.zarr_with_labels.jser", 5.7),
    ("ZGBJY",         "cropped_small_class/ZGBJY.jser", 7.0),
    ("crop_2",        "autoseg_large_slow_3/crop_2_SSVQM__3350-23720-27542_3000-6500-6500.zarr_with_labels.jser", 92),
    ("GBSFW",         "autoseg_large_slow_1/GBSFW_D02_2025-09-22-MJ-ROIs_with_labels.jser", 127),
    ("NVWXP",         "autoseg_large_slow_2/NVWXP-R02-2026-06-17-php.jser", 187),
    ("crop_3",        "autoseg_large_slow_3/crop_3_SSVQM__3100-21470-25292_3500-11000-11000.zarr_with_labels.jser", 312),
    ("crop_4",        "autoseg_large_slow_3/crop_4_SSVQM__2850-19220-23042_4000-15500-15500.zarr_with_labels.jser", 701),
    ("crop_ROIsmall", "autoseg_large_slow_3/crop_ROIsmall_SSVQM__0-10000-20000_9700-10000-20000.zarr_with_labels.jser", 1400),
]

def plan(mb):
    if mb <= 10:   return 1, 5, 600
    if mb <= 200:  return 1, 3, 600
    if mb <= 700:  return 1, 2, 1800
    return 0, 2, 1800   # >700MB: no warmup

def cps_for(label):
    base = ["fork", "origin"]
    if label in ("ZGBJY", "crop_2"):   # baseline on a small + a medium to show fork-fixes are perf-neutral
        base.insert(1, "baseline")
    return base

def run_one(cp, jser, timeout, skip_save):
    out = os.path.join(BENCH, f"_run_{cp}.json")
    if os.path.exists(out):
        os.remove(out)
    env = dict(os.environ, TMPDIR=os.path.join(BENCH, "tmp"))
    if skip_save:
        env["SKIP_SAVE"] = "1"
    t0 = time.time()
    try:
        subprocess.run([PY, HARNESS, CP[cp], jser, out], timeout=timeout, env=env,
                       capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "wall": time.time() - t0}
    if os.path.exists(out):
        return json.load(open(out))
    return {"ok": False, "error": "no_output(OOM/crash?)", "wall": time.time() - t0}

def main():
    open(RESULTS, "w").close()
    for label, rel, mb in SERIES:
        jser = os.path.join(TESTING, rel)
        if not os.path.exists(jser):
            print(f"MISSING {label}: {jser}", flush=True); continue
        warm, reps, timeout = plan(mb)
        skip_save = mb > 300
        for cp in cps_for(label):
            for _ in range(warm):
                run_one(cp, jser, timeout, skip_save)  # warmup, discarded
            for r in range(reps):
                res = run_one(cp, jser, timeout, skip_save)
                res.update(label=label, cp=cp, rep=r, size_mb=mb)
                with open(RESULTS, "a") as f:
                    f.write(json.dumps(res) + "\n")
                print(f"{label:14s} {mb:7.1f}MB {cp:8s} rep{r}: ok={res.get('ok')} "
                      f"open={res.get('t_open')} refresh={res.get('t_refresh')} "
                      f"save={res.get('t_save')} rss={res.get('peak_rss_mb')}", flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
