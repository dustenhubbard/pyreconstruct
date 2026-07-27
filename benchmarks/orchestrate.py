#!/usr/bin/env python
"""Run the benchmark matrix: checkouts x series x {cold,warm} x reps, each rep a
fresh subprocess of harness.py. Writes results.jsonl incrementally.

WHAT WAS WRONG BEFORE (and what this rewrite fixes)
---------------------------------------------------
The first version of this script produced the memory figures that the
modernization plan struck as unusable. Four defects, all fixed here:

1. **Fork-first ordering dependence.** Checkouts ran in a fixed order with the
   fork always first. Because `Series.openJser` leaves a hidden unpack dir
   behind and nothing ever deleted it, the *first* checkout to touch a series
   paid the full JSON parse + unpack and every later checkout took the
   hidden-dir fast path. The fork was measured cold and upstream warm on
   exactly the two series where it mattered most.
   -> Fixed: the hidden dir is explicitly managed per rep, and checkout order
   is rotated per rep so no checkout is systematically first.

2. **Silent `MISSING ... continue`.** A data file that had moved was skipped
   with one line of stdout and no trace in the results, so an incomplete matrix
   was indistinguishable from a complete one.
   -> Fixed: a pre-flight manifest is printed AND written into results.jsonl as
   a `manifest` record; a missing file is a hard error (exit 2) unless
   --allow-missing is passed, in which case every skip is recorded as a
   `skipped` row so it survives into aggregation.

3. **Cold-vs-warm contamination via the hidden unpack dir.** Reps of the same
   (checkout, series) silently mixed one cold rep and one warm rep, and
   `statistics.median` over two values is their mean -- so the published
   "median" was a mean of two different workloads.
   -> Fixed: cold and warm are explicit, separately-labelled conditions. The
   hidden dir is deleted before every cold rep; for warm it is deleted once,
   primed by an unmeasured open from the *same* checkout, then reused across
   that condition's reps. The harness independently observes which path
   openJser took and this script asserts it matches the intent, so a
   mislabelled rep aborts the run instead of quietly polluting an average.

4. **Size-dependent warmup policy.** The old `plan()` gave series >700 MB zero
   warmups while smaller ones got one, which is the mechanism by which the two
   headline series ended up contaminated.
   -> Fixed: every series gets identical treatment regardless of size. Only the
   subprocess timeout scales with size, and that is a crash guard, not a
   measurement policy.

Also: the OS page cache is primed by reading the .jser before every rep. We
cannot drop_caches without root, so rather than let that axis vary we pin it
warm for every rep of every checkout. "cold" here therefore means
*application*-cold (full JSON parse + unpack) with disk cache held constant.
"""
import argparse, json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "harness.py")

# The historical eight lab series, kept for provenance. These paths are one
# developer's machine and several no longer exist -- pass --series-json to
# describe whatever data the current machine actually has.
DEFAULT_DATA_ROOT = "/home/dusten/projects/testing"
DEFAULT_SERIES = [  # (label, relpath, size_mb)
    ("crop_1",        "autoseg_large_slow_3/crop_1_SSVQM__3600-25970-29792_2500-2000-2000.zarr_with_labels.jser", 5.7),
    ("ZGBJY",         "cropped_small_class/ZGBJY.jser", 7.0),
    ("crop_2",        "autoseg_large_slow_3/crop_2_SSVQM__3350-23720-27542_3000-6500-6500.zarr_with_labels.jser", 92),
    ("GBSFW",         "autoseg_large_slow_1/GBSFW_D02_2025-09-22-MJ-ROIs_with_labels.jser", 127),
    ("NVWXP",         "autoseg_large_slow_2/NVWXP-R02-2026-06-17-php.jser", 187),
    ("crop_3",        "autoseg_large_slow_3/crop_3_SSVQM__3100-21470-25292_3500-11000-11000.zarr_with_labels.jser", 312),
    ("crop_4",        "autoseg_large_slow_3/crop_4_SSVQM__2850-19220-23042_4000-15500-15500.zarr_with_labels.jser", 701),
    ("crop_ROIsmall", "autoseg_large_slow_3/crop_ROIsmall_SSVQM__0-10000-20000_9700-10000-20000.zarr_with_labels.jser", 1400),
]


# --------------------------------------------------------------------------
# hidden unpack dir
# --------------------------------------------------------------------------

def hidden_dir_for(jser_path):
    """The ``.<name>/`` dir openJser unpacks into, and its ``<name>.ser`` sentinel."""
    sdir = os.path.dirname(os.path.abspath(jser_path))
    sname = os.path.basename(jser_path)
    sname = sname[:sname.rfind(".")]
    hidden = os.path.join(sdir, f".{sname}")
    return hidden, os.path.join(hidden, f"{sname}.ser")


def drop_hidden_dir(jser_path):
    hidden, _ = hidden_dir_for(jser_path)
    shutil.rmtree(hidden, ignore_errors=True)
    if os.path.exists(hidden):
        raise RuntimeError(
            f"could not remove hidden unpack dir {hidden}; refusing to run a rep "
            f"whose cold/warm state cannot be controlled"
        )


def hidden_dir_bytes(jser_path):
    """Total bytes in the hidden unpack dir (0 if absent).

    Recorded per warm condition so an asymmetry in what each checkout *wrote* is
    visible, rather than silently changing what the warm path has to read.
    """
    hidden, _ = hidden_dir_for(jser_path)
    if not os.path.isdir(hidden):
        return 0
    total = 0
    for root, _dirs, files in os.walk(hidden):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def prime_page_cache(path):
    """Read the file so the OS page cache state is identical for every rep."""
    n = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(64 << 20)
            if not chunk:
                break
            n += len(chunk)
    return n


# --------------------------------------------------------------------------
# one rep
# --------------------------------------------------------------------------

def run_one(cp, checkout, jser, timeout, skip_save, tmpdir):
    out = os.path.join(tmpdir, f"_run_{cp}.json")
    if os.path.exists(out):
        os.remove(out)
    env = dict(os.environ, TMPDIR=tmpdir)
    if skip_save:
        env["SKIP_SAVE"] = "1"
    else:
        env.pop("SKIP_SAVE", None)
    t0 = time.time()
    proc = None
    try:
        proc = subprocess.run([sys.executable, HARNESS, checkout, jser, out],
                              timeout=timeout, env=env, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "wall": time.time() - t0}
    if os.path.exists(out):
        return json.load(open(out))
    return {"ok": False, "error": "no_output(OOM/crash?)", "wall": time.time() - t0,
            "stderr_tail": ((proc.stderr if proc else "") or "")[-500:]}


def timeout_for(mb):
    """Crash guard only -- not a measurement policy. Roughly 6 s per MB, which is
    ~4x the slowest upstream open+refresh ever observed, floored at 10 minutes."""
    return max(600, int(mb * 6))


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

def load_series(args):
    if args.series_json:
        with open(args.series_json) as f:
            spec = json.load(f)
        series = []
        for s in spec:
            path = s["path"]
            if not os.path.isabs(path):
                path = os.path.join(args.data_root, path)
            series.append((s["label"], path,
                           float(s["size_mb"]) if s.get("size_mb") else None))
        return series
    return [(label, os.path.join(args.data_root, rel), mb)
            for label, rel, mb in DEFAULT_SERIES]


def build_manifest(series):
    """Resolve every configured series to PRESENT/MISSING with real sizes."""
    entries = []
    for label, path, declared_mb in series:
        present = os.path.isfile(path)
        exact_mb = os.path.getsize(path) / (1 << 20) if present else None
        actual_mb = round(exact_mb, 1) if exact_mb is not None else None
        entries.append({
            "label": label, "path": path, "present": present,
            "declared_size_mb": declared_mb, "actual_size_mb": actual_mb,
            "exact_size_mb": round(exact_mb, 4) if exact_mb is not None else None,
            "size_mb": actual_mb if actual_mb is not None else declared_mb,
        })
    return entries


def print_manifest(entries, args):
    print("=" * 78, flush=True)
    print("MANIFEST -- what this run will actually measure", flush=True)
    print("=" * 78, flush=True)
    for e in entries:
        if e["present"]:
            drift = ""
            if e["declared_size_mb"] and e["exact_size_mb"]:
                rel = abs(e["exact_size_mb"] - e["declared_size_mb"]) / e["declared_size_mb"]
                if rel > 0.05:
                    drift = (f"  (!! declared {e['declared_size_mb']} MB, "
                             f"on disk {e['exact_size_mb']} MB)")
            print(f"  PRESENT  {e['label']:16s} {e['actual_size_mb']:>9.1f} MB  "
                  f"{e['path']}{drift}", flush=True)
        else:
            print(f"  MISSING  {e['label']:16s} {'':>9s}     {e['path']}", flush=True)
    n_present = sum(1 for e in entries if e["present"])
    print(f"  -> {n_present}/{len(entries)} series present; conditions={args.conditions}; "
          f"reps={args.reps}; checkouts={args.checkouts}", flush=True)
    print("=" * 78, flush=True)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Honest cold/warm benchmark matrix. See module docstring.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root",
                    default=os.environ.get("PYRECON_BENCH_DATA", DEFAULT_DATA_ROOT),
                    help="root for relative series paths (env: PYRECON_BENCH_DATA)")
    ap.add_argument("--series-json",
                    help="JSON list of {label, path, size_mb} overriding the built-in set")
    ap.add_argument("--checkouts", required=True,
                    help="comma-separated name=path pairs, e.g. fork=/x/wt-fork,origin=/x/wt-origin")
    ap.add_argument("--conditions", default="cold,warm",
                    help="comma-separated subset of cold,warm (default both)")
    ap.add_argument("--reps", type=int, default=3,
                    help="measured reps per (checkout, series, condition)")
    ap.add_argument("--out", default=os.path.join(HERE, "results.jsonl"))
    ap.add_argument("--tmpdir", default=os.path.join(HERE, "tmp"))
    ap.add_argument("--skip-save-above-mb", type=float, default=300.0,
                    help="skip the saveJser op for series larger than this")
    ap.add_argument("--allow-missing", action="store_true",
                    help="record missing series as skipped rows instead of exiting 2")
    ap.add_argument("--only", help="comma-separated series labels to restrict to")
    args = ap.parse_args()

    checkouts = []
    for pair in args.checkouts.split(","):
        name, _, path = pair.partition("=")
        if not path:
            ap.error(f"--checkouts entry {pair!r} must be name=path")
        path = os.path.abspath(path)
        if not os.path.isdir(os.path.join(path, "PyReconstruct")):
            ap.error(f"checkout {name} at {path} has no PyReconstruct/ directory")
        checkouts.append((name, path))

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    for c in conditions:
        if c not in ("cold", "warm"):
            ap.error(f"unknown condition {c!r} (want cold and/or warm)")

    series = load_series(args)
    if args.only:
        keep = {s.strip() for s in args.only.split(",")}
        unknown = keep - {s[0] for s in series}
        if unknown:
            ap.error(f"--only names unknown series: {sorted(unknown)}")
        series = [s for s in series if s[0] in keep]

    os.makedirs(args.tmpdir, exist_ok=True)
    entries = build_manifest(series)
    print_manifest(entries, args)

    absent = [e for e in entries if not e["present"]]
    if absent and not args.allow_missing:
        print(f"\nFATAL: {len(absent)} configured series are missing: "
              f"{[e['label'] for e in absent]}\n"
              f"Fix the paths, or pass --allow-missing to proceed with a recorded "
              f"partial matrix.", flush=True)
        return 2

    with open(args.out, "w") as f:
        f.write(json.dumps({
            "record": "manifest",
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "data_root": args.data_root,
            "checkouts": dict(checkouts),
            "conditions": conditions,
            "reps": args.reps,
            "python": sys.version,
            "series": entries,
        }) + "\n")

    def emit(row):
        with open(args.out, "a") as f:
            f.write(json.dumps(row) + "\n")

    for series_index, e in enumerate(entries):
        label, jser, mb = e["label"], e["path"], e["size_mb"]
        if not e["present"]:
            emit({"record": "skipped", "label": label, "path": jser,
                  "reason": "file not found"})
            print(f"SKIPPED {label}: file not found ({jser})", flush=True)
            continue

        timeout = timeout_for(mb or 1000)
        skip_save = bool(mb and mb > args.skip_save_above_mb)

        def measure(cp, checkout, condition, rep, order_index, primed_bytes):
            """Run one measured rep, record it, and refuse a mislabelled one."""
            res = run_one(cp, checkout, jser, timeout, skip_save, args.tmpdir)
            # The label is earned, not assumed: the harness reports which path
            # openJser actually took.
            observed = res.get("cache_state")
            mismatch = bool(res.get("ok")) and observed != condition
            res.update(record="rep", label=label, cp=cp, condition=condition,
                       rep=rep, size_mb=mb, order_index=order_index,
                       save_skipped=skip_save,
                       hidden_dir_bytes_after_priming=primed_bytes)
            if mismatch:
                res["cache_state_mismatch"] = True
            emit(res)
            print(f"{label:14s} {(mb or 0):7.1f}MB {cp:8s} {condition:4s} "
                  f"rep{rep} (order {order_index}): ok={res.get('ok')} "
                  f"state={observed} open={_r(res.get('t_open'))} "
                  f"refresh={_r(res.get('t_refresh'))} "
                  f"save={_r(res.get('t_save'))} "
                  f"peak_rss={_r(res.get('peak_rss_mb'), 1)}", flush=True)
            if not res.get("ok"):
                print(f"  !! FAILED: {res.get('error')}", flush=True)
            if mismatch:
                print(f"FATAL: {label}/{cp}/{condition} rep{rep} intended "
                      f"{condition!r} but openJser took the {observed!r} path. "
                      f"Refusing to continue with mislabelled reps.", flush=True)
                return False
            return True

        def rotated(shift):
            s = shift % len(checkouts)
            return list(enumerate(checkouts[s:] + checkouts[:s]))

        for condition in conditions:
            if condition == "cold":
                # Every cold rep starts from no hidden dir at all. Checkout order
                # is rotated per rep so no checkout is systematically first
                # (allocator warmth, .pyc page cache, thermal drift).
                for rep in range(args.reps):
                    for order_index, (cp, checkout) in rotated(rep):
                        drop_hidden_dir(jser)
                        prime_page_cache(jser)
                        if not measure(cp, checkout, condition, rep, order_index, None):
                            return 3
            else:
                # Warm: each checkout gets its own hidden dir, deleted then primed
                # by ONE unmeasured open from that same checkout, and reused
                # across that checkout's reps. Priming with the same checkout
                # keeps it symmetric -- each side reads a hidden dir its own code
                # wrote, which is also what a real user experiences.
                for order_index, (cp, checkout) in rotated(series_index):
                    drop_hidden_dir(jser)
                    prime_page_cache(jser)
                    prime = run_one(cp, checkout, jser, timeout, True, args.tmpdir)
                    if not prime.get("ok"):
                        emit({"record": "rep", "label": label, "cp": cp,
                              "condition": condition, "rep": None, "ok": False,
                              "error": f"warm priming open failed: {prime.get('error')}",
                              "size_mb": mb})
                        print(f"{label:14s} {cp:8s} {condition}: PRIMING FAILED "
                              f"{prime.get('error')}", flush=True)
                        continue
                    primed_bytes = hidden_dir_bytes(jser)
                    for rep in range(args.reps):
                        prime_page_cache(jser)
                        if not measure(cp, checkout, condition, rep, order_index,
                                       primed_bytes):
                            return 3

        # don't leave GBs of unpacked sections lying around
        drop_hidden_dir(jser)

    print("DONE", flush=True)
    return 0


def _r(x, nd=4):
    return round(x, nd) if isinstance(x, (int, float)) else x


if __name__ == "__main__":
    sys.exit(main())
