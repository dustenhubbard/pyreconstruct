#!/usr/bin/env python
"""Aggregate results.jsonl -> summary.json + summary.csv + a markdown table.

Grouping key is (series, checkout, CONDITION). Cold and warm reps are never
pooled: pooling them is precisely the defect that produced the struck
3276/6374 MB headline figures, where `statistics.median` over one cold rep and
one warm rep returned their mean.

Guards that make a bad input loud instead of silent:
  * a `manifest` record is required; missing series are reported
  * rows written by the pre-Phase-0 orchestrator (no `condition`) are refused
  * any rep whose recorded `cache_state` disagrees with its `condition` aborts
  * groups with fewer than 2 reps are flagged `low_n`
  * `spread_pct` (max-min over median) is reported for every metric, so a
    bimodal group cannot hide behind a single central number
"""
import argparse, csv, collections, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OPS = ("t_open", "t_refresh", "t_save", "peak_rss_mb",
       "rss_after_open_mb", "rss_after_refresh_mb")
META = ("n_sections", "n_objects", "n_traces",
        "sum_area", "sum_length", "sum_radius", "trace_digest")


def load(path):
    manifest, reps, skipped = None, [], []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            kind = r.get("record")
            if kind == "manifest":
                manifest = r
            elif kind == "skipped":
                skipped.append(r)
            elif kind == "rep":
                reps.append(r)
            else:
                # results.jsonl from the pre-Phase-0 harness had no `record`
                # field and no condition/cache_state at all.
                r["record"] = "legacy"
                reps.append(r)
    return manifest, reps, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(HERE, "results.jsonl"))
    ap.add_argument("--out-json", default=os.path.join(HERE, "summary.json"))
    ap.add_argument("--out-csv", default=os.path.join(HERE, "summary.csv"))
    args = ap.parse_args()

    manifest, reps, skipped = load(args.results)

    legacy = [r for r in reps if r.get("record") == "legacy"]
    if legacy:
        print(f"FATAL: {len(legacy)} rows have no `condition` field -- this file was "
              f"written by the pre-Phase-0 orchestrator, whose reps silently mixed "
              f"cold and warm. Re-run orchestrate.py; these rows cannot be "
              f"aggregated honestly.", file=sys.stderr)
        return 2

    if manifest is None:
        print("FATAL: no `manifest` record in results.jsonl -- cannot tell whether "
              "the matrix is complete.", file=sys.stderr)
        return 2

    mismatched = [r for r in reps if r.get("cache_state_mismatch")]
    for r in reps:
        if r.get("ok") and r.get("cache_state") != r.get("condition") and not r.get("cache_state_mismatch"):
            mismatched.append(r)
    if mismatched:
        for r in mismatched[:10]:
            print(f"FATAL: {r.get('label')}/{r.get('cp')} rep{r.get('rep')} labelled "
                  f"{r.get('condition')!r} but ran {r.get('cache_state')!r}",
                  file=sys.stderr)
        return 3

    # ---- group strictly by (label, cp, condition) --------------------------
    vals = collections.defaultdict(lambda: collections.defaultdict(list))
    meta, fails, size = {}, collections.defaultdict(list), {}
    for r in reps:
        key = (r["label"], r["cp"], r["condition"])
        if r.get("size_mb") is not None:
            size[r["label"]] = r["size_mb"]
        if not r.get("ok"):
            fails[key].append(r.get("error", "?"))
            continue
        for op in OPS:
            if r.get(op) is not None:
                vals[key][op].append(r[op])
        meta[key] = {k: r.get(k) for k in META}

    def stat(key, op):
        xs = vals[key].get(op) or []
        if not xs:
            return None
        med = statistics.median(xs)
        return {
            "median": round(med, 4),
            "min": round(min(xs), 4),
            "max": round(max(xs), 4),
            "n": len(xs),
            "spread_pct": round((max(xs) - min(xs)) / med * 100, 1) if med else None,
        }

    keys = set(vals) | set(fails)
    labels = sorted(size, key=lambda l: size[l])
    conditions = sorted({k[2] for k in keys})
    cps = sorted({k[1] for k in keys})

    summary = {
        "manifest": {
            "started": manifest.get("started"),
            "checkouts": manifest.get("checkouts"),
            "series_present": [s["label"] for s in manifest.get("series", []) if s["present"]],
            "series_missing": [s["label"] for s in manifest.get("series", []) if not s["present"]],
            "skipped_records": skipped,
        },
        "series": {},
    }

    for label in labels:
        entry = {"size_mb": size[label], "by_condition": {}}
        for cond in conditions:
            per_cp = {}
            for cp in cps:
                key = (label, cp, cond)
                if key not in vals and key not in fails:
                    continue
                d = {op: stat(key, op) for op in OPS}
                d["meta"] = meta.get(key)
                d["n_reps"] = max([(d[op] or {}).get("n", 0) for op in OPS] or [0])
                if d["n_reps"] < 2:
                    d["low_n"] = True
                if key in fails:
                    d["fail"] = fails[key]
                per_cp[cp] = d
            if not per_cp:
                continue
            block = {"checkouts": per_cp}
            # ratios, computed only WITHIN a condition
            f, o = per_cp.get("fork"), per_cp.get("origin")
            if f and o:
                def ratio(op, num, den):
                    a = (num.get(op) or {}).get("median")
                    b = (den.get(op) or {}).get("median")
                    return round(a / b, 3) if (a and b) else None
                block["fork_vs_origin"] = {
                    "open_speedup": ratio("t_open", o, f),
                    "refresh_speedup": ratio("t_refresh", o, f),
                    "save_speedup": ratio("t_save", o, f),
                    "peak_rss_ratio": ratio("peak_rss_mb", f, o),
                }
                oo = (o.get("t_open") or {}).get("median") or 0
                orf = (o.get("t_refresh") or {}).get("median") or 0
                fo = (f.get("t_open") or {}).get("median") or 0
                frf = (f.get("t_refresh") or {}).get("median") or 0
                block["fork_vs_origin"]["open_plus_refresh_speedup"] = (
                    round((oo + orf) / (fo + frf), 3) if (fo + frf) else None)
                eq = {}
                mf = meta.get((label, "fork", cond)) or {}
                mo = meta.get((label, "origin", cond)) or {}
                for k in ("n_sections", "n_objects", "n_traces", "trace_digest"):
                    eq[k] = {"fork": mf.get(k), "origin": mo.get(k),
                             "equal": mf.get(k) == mo.get(k)}
                for k in ("sum_area", "sum_length", "sum_radius"):
                    a, b = mf.get(k), mo.get(k)
                    eq[k] = {"fork": a, "origin": b,
                             "rel_diff": (abs(a - b) / max(abs(b), 1e-9)
                                          if (a is not None and b is not None) else None)}
                block["equivalence"] = eq
            entry["by_condition"][cond] = block

        # cold-vs-warm delta WITHIN each checkout (the cold-spike attribution)
        deltas = {}
        for cp in cps:
            c = ((entry["by_condition"].get("cold") or {}).get("checkouts") or {}).get(cp)
            w = ((entry["by_condition"].get("warm") or {}).get("checkouts") or {}).get(cp)
            if not (c and w):
                continue
            g = lambda d, op: (d.get(op) or {}).get("median")
            cr, wr = g(c, "peak_rss_mb"), g(w, "peak_rss_mb")
            co, wo = g(c, "t_open"), g(w, "t_open")
            deltas[cp] = {
                "peak_rss_cold_mb": cr, "peak_rss_warm_mb": wr,
                "cold_rss_overhead_mb": round(cr - wr, 1) if (cr and wr) else None,
                "cold_rss_ratio": round(cr / wr, 3) if (cr and wr) else None,
                "t_open_cold_s": co, "t_open_warm_s": wo,
                "cold_open_overhead_s": round(co - wo, 3) if (co and wo) else None,
            }
        if deltas:
            entry["cold_vs_warm"] = deltas
        summary["series"][label] = entry

    json.dump(summary, open(args.out_json, "w"), indent=2)

    # ---- CSV: one row per (series, condition, checkout) --------------------
    with open(args.out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["series", "size_mb", "condition", "cp", "n_reps",
                    "open_s_median", "open_spread_pct",
                    "refresh_s_median", "save_s_median",
                    "peak_rss_mb_median", "peak_rss_spread_pct",
                    "rss_after_open_mb_median", "n_traces"])
        for label in labels:
            e = summary["series"][label]
            for cond, block in sorted(e["by_condition"].items()):
                for cp, d in sorted(block["checkouts"].items()):
                    g = lambda op, fld="median": (d.get(op) or {}).get(fld)
                    w.writerow([label, e["size_mb"], cond, cp, d.get("n_reps"),
                                g("t_open"), g("t_open", "spread_pct"),
                                g("t_refresh"), g("t_save"),
                                g("peak_rss_mb"), g("peak_rss_mb", "spread_pct"),
                                g("rss_after_open_mb"),
                                (d.get("meta") or {}).get("n_traces")])

    # ---- stdout table -----------------------------------------------------
    miss = summary["manifest"]["series_missing"]
    if miss:
        print(f"!! MISSING SERIES (not measured): {miss}\n")
    hdr = (f"{'series':16s} {'MB':>7s} {'cond':>5s} {'traces':>8s} | "
           f"{'open o->f':>19s} {'refresh o->f':>19s} {'o+r':>7s} | "
           f"{'peakRSS o->f':>19s} {'ratio':>7s}")
    print(hdr)
    print("-" * len(hdr))
    for label in labels:
        e = summary["series"][label]
        for cond in ("cold", "warm"):
            block = e["by_condition"].get(cond)
            if not block:
                continue
            f = block["checkouts"].get("fork")
            o = block["checkouts"].get("origin")
            if not (f and o):
                print(f"{label:16s} {e['size_mb']:7.0f} {cond:>5s} "
                      f"{'':>8s} | (incomplete: have {sorted(block['checkouts'])})")
                continue
            r = block["fork_vs_origin"]
            tr = (f.get("meta") or {}).get("n_traces")
            g = lambda d, op: (d.get(op) or {}).get("median")
            print(f"{label:16s} {e['size_mb']:7.0f} {cond:>5s} {str(tr):>8s} | "
                  f"{g(o,'t_open'):9.2f}->{g(f,'t_open'):<9.2f} "
                  f"{g(o,'t_refresh'):9.2f}->{g(f,'t_refresh'):<9.2f} "
                  f"{str(r['open_plus_refresh_speedup'])+'x':>7s} | "
                  f"{g(o,'peak_rss_mb'):9.0f}->{g(f,'peak_rss_mb'):<9.0f} "
                  f"{str(r['peak_rss_ratio'])+'x':>7s}")
        cw = e.get("cold_vs_warm")
        if cw:
            for cp, d in sorted(cw.items()):
                sgn = lambda v: (f"{v:+g}" if isinstance(v, (int, float)) else str(v))
                print(f"{'':16s} {'':>7s} {'':>5s} {'':>8s} | cold-spike[{cp}]: "
                      f"peak RSS {d['peak_rss_warm_mb']} -> {d['peak_rss_cold_mb']} MB "
                      f"({sgn(d['cold_rss_overhead_mb'])} MB, {d['cold_rss_ratio']}x), "
                      f"open {sgn(d['cold_open_overhead_s'])} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
