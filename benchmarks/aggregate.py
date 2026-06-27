#!/usr/bin/env python
"""Aggregate results.jsonl -> summary.json + summary.csv + a markdown table."""
import json, statistics, collections, csv, os

BENCH = "/home/dusten/projects/testing/bench"
rows = [json.loads(l) for l in open(os.path.join(BENCH, "results.jsonl"))]

vals = collections.defaultdict(lambda: collections.defaultdict(list))   # (label,cp) -> op -> [vals]
meta = {}                                                               # (label,cp) -> dict
fails = collections.defaultdict(list)                                   # (label,cp) -> [errors]
size = {}
for r in rows:
    label, cp = r["label"], r["cp"]
    size[label] = r["size_mb"]
    if not r.get("ok"):
        fails[(label, cp)].append(r.get("error", "?")); continue
    for op in ("t_open", "t_refresh", "t_save", "peak_rss_mb"):
        if r.get(op) is not None:
            vals[(label, cp)][op].append(r[op])
    meta[(label, cp)] = {k: r.get(k) for k in ("n_sections", "n_objects", "n_traces",
                                               "sum_area", "sum_length", "sum_radius")}

def med(label, cp, op):
    xs = vals[(label, cp)].get(op) or []
    return round(statistics.median(xs), 4) if xs else None

labels = sorted(size, key=lambda l: size[l])
summary = {}
for label in labels:
    entry = {"size_mb": size[label]}
    for cp in ("origin", "baseline", "fork"):
        if (label, cp) in vals or (label, cp) in fails:
            entry[cp] = {op: med(label, cp, op) for op in ("t_open", "t_refresh", "t_save", "peak_rss_mb")}
            entry[cp]["meta"] = meta.get((label, cp))
            if (label, cp) in fails:
                entry[cp]["fail"] = fails[(label, cp)]
    f, o, b = entry.get("fork"), entry.get("origin"), entry.get("baseline")
    def sx(a, bb, op):
        try: return round(a[op] / bb[op], 2)
        except Exception: return None
    if f and o:
        of = (o.get("t_open") or 0) + (o.get("t_refresh") or 0)
        ff = (f.get("t_open") or 0) + (f.get("t_refresh") or 0)
        entry["speedup_vs_origin"] = {
            "open": sx(o, f, "t_open"), "refresh": sx(o, f, "t_refresh"),
            "save": sx(o, f, "t_save"), "open+refresh": round(of / ff, 2) if ff else None,
        }
        # equivalence fork vs origin
        eq = {}
        mo, mf = o.get("meta") or {}, f.get("meta") or {}
        for k in ("n_sections", "n_objects", "n_traces"):
            eq[k] = (mf.get(k), mo.get(k), mf.get(k) == mo.get(k))
        for k in ("sum_area", "sum_length", "sum_radius"):
            a, bb = mf.get(k), mo.get(k)
            rel = abs(a - bb) / max(abs(bb), 1e-9) if (a is not None and bb is not None) else None
            eq[k] = (a, bb, rel)
        entry["equivalence"] = eq
    if f and b:
        entry["speedup_vs_baseline"] = {op.replace("t_", ""): sx(b, f, op)
                                        for op in ("t_open", "t_refresh", "t_save")}
    summary[label] = entry

json.dump(summary, open(os.path.join(BENCH, "summary.json"), "w"), indent=2)

# CSV
with open(os.path.join(BENCH, "summary.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["series", "size_mb", "cp", "open_s", "refresh_s", "save_s", "peak_rss_mb", "n_traces"])
    for label in labels:
        for cp in ("origin", "baseline", "fork"):
            e = summary[label].get(cp)
            if e:
                m = e.get("meta") or {}
                w.writerow([label, size[label], cp, e.get("t_open"), e.get("t_refresh"),
                            e.get("t_save"), e.get("peak_rss_mb"), m.get("n_traces")])

# markdown table
print(f"{'series':14s} {'MB':>6s} {'traces':>8s} | {'open o/f':>14s} {'refresh o/f':>16s} | {'o+r speedup':>11s}")
for label in labels:
    e = summary[label]; f, o = e.get("fork"), e.get("origin")
    tr = ((f or o or {}).get("meta") or {}).get("n_traces")
    if f and o:
        sp = e["speedup_vs_origin"]
        print(f"{label:14s} {e['size_mb']:6.0f} {str(tr):>8s} | "
              f"{str(o.get('t_open')):>6s}/{str(f.get('t_open')):<6s} "
              f"{str(o.get('t_refresh')):>7s}/{str(f.get('t_refresh')):<7s} | {str(sp['open+refresh'])+'x':>11s}")
    else:
        print(f"{label:14s} {e['size_mb']:6.0f} {str(tr):>8s} | (incomplete: have {list(e.keys())})")
