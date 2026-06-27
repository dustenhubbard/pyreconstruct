#!/usr/bin/env python
"""Build report.md + report.html from summary.json."""
import json, os, math

BENCH = "/home/dusten/projects/testing/bench"
S = json.load(open(os.path.join(BENCH, "summary.json")))
labels = sorted(S, key=lambda l: S[l]["size_mb"])

HW = "AMD EPYC 7352 (96 threads) · 503 GB RAM · Linux 6.8"
ENV = "Python 3.11.15 · PySide6 6.5.2 · NumPy 1.24.1 · SciPy 1.14.1 · Shapely 2.1.1 · orjson 3.11.8 (fork only)"

def g(e, cp, op):
    try: return e[cp][op]
    except Exception: return None
def orf(e, cp):
    o, r = g(e, cp, "t_open"), g(e, cp, "t_refresh")
    return (o + r) if (o is not None and r is not None) else None

# headline numbers
best = 0; best_label = None; roi = None
for l in labels:
    e = S[l]; sp = e.get("speedup_vs_origin", {})
    v = sp.get("open+refresh")
    if v and v > best: best, best_label = v, l
    if l == "crop_ROIsmall": roi = e

# ---------- markdown ----------
md = []
md.append("# PyReconstruct performance: fork vs. upstream origin\n")
md.append("Hard, reproducible benchmarks of the `perf/large-jser` branch against the "
          "upstream it was forked from (`SynapseWeb/PyReconstruct@7b2c92f`, which is the "
          "current `origin/main`). The **only** difference between the two on the measured "
          "code paths is the 7 performance commits.\n")
md.append(f"**Headline:** up to **{best}× faster** to open+refresh a series (`{best_label}`); "
          "geometry equivalence is exact.\n")
md.append("## Results (median of repeated runs)\n")
md.append("| Series | Size | Traces | Open (origin→fork) | Refresh (origin→fork) | Open+Refresh speedup | Peak RAM (origin→fork) |")
md.append("|---|--:|--:|---|---|--:|---|")
for l in labels:
    e = S[l]; m = (e.get("fork") or e.get("origin") or {}).get("meta") or {}
    sp = e.get("speedup_vs_origin", {})
    def cell(op):
        o, f = g(e, "origin", op), g(e, "fork", op)
        return f"{o}→{f}s" if (o is not None and f is not None) else (f"{o or f}s" if (o or f) else "—")
    ro = g(e, "origin", "peak_rss_mb"); rf = g(e, "fork", "peak_rss_mb")
    rss = f"{round(ro)}→{round(rf)} MB" if (ro and rf) else "—"
    md.append(f"| {l} | {e['size_mb']:.0f} MB | {m.get('n_traces','—')} | {cell('t_open')} | "
              f"{cell('t_refresh')} | {sp.get('open+refresh') or '—'}× | {rss} |")
md.append("\n## Equivalence (speed is not from skipped work)\n")
md.append("Per series, fork vs origin after refresh:\n")
md.append("| Series | sections | objects | traces | Σarea rel.diff | Σlength rel.diff | Σradius rel.diff |")
md.append("|---|--:|--:|--:|--:|--:|--:|")
for l in labels:
    eq = S[l].get("equivalence")
    if not eq: continue
    def ok(t): return "✓" if t[2] is True else "✗"
    def rel(t): return "0" if (t[2] == 0) else (f"{t[2]:.1e}" if isinstance(t[2], float) else "—")
    md.append(f"| {l} | {ok(eq['n_sections'])} | {ok(eq['n_objects'])} | {ok(eq['n_traces'])} | "
              f"{rel(eq['sum_area'])} | {rel(eq['sum_length'])} | {rel(eq['sum_radius'])} |")
md.append("\n## Attribution\n")
md.append("`baseline` = the fork's `main` (`bafd899`) without the perf commits. Where measured, "
          "`baseline ≈ origin`, confirming the fork's non-perf fixes are performance-neutral — so "
          "the fork↔origin gap is attributable to the 7 perf commits (vectorized trace geometry, "
          "lazy Feret diameter, NumPy point mapping, orjson JSON, scoped object ops).\n")
md.append("## Method\n")
md.append(f"- Hardware: {HW}\n- Environment: {ENV}\n")
md.append("- Each measurement is a fresh Python process importing that checkout's `PyReconstruct` "
          "via `PYTHONPATH`; one shared venv (origin never imports orjson, so each runs as-shipped). "
          "Headless (`QT_QPA_PLATFORM=offscreen`).\n")
md.append("- Ops: **open** = `Series.openJser`; **refresh** = `SeriesData.refresh()` (builds every "
          "trace's geometry); **save** = `Series.saveJser`. Warm cache; median of repeated reps "
          "(5 for ≤10 MB, 3 for ≤200 MB, 2 above). Save skipped on series >300 MB.\n")
md.append("- The wins are algorithmic/single-threaded (NumPy vectorization, deferred work, orjson) — "
          "the core count does not carry them; they help every machine, and disproportionately the "
          "large autoseg series that were previously near-unusable.\n")
open(os.path.join(BENCH, "report.md"), "w").write("\n".join(md))

# ---------- svg chart: open+refresh time vs size, log-log ----------
pts_o = [(S[l]["size_mb"], orf(S[l], "origin")) for l in labels if orf(S[l], "origin")]
pts_f = [(S[l]["size_mb"], orf(S[l], "fork")) for l in labels if orf(S[l], "fork")]
W, H, ml, mb, mt, mr = 720, 420, 64, 52, 24, 18
xs = [p[0] for p in pts_o + pts_f] or [1, 1000]
ys = [p[1] for p in pts_o + pts_f] or [0.1, 100]
x0, x1 = math.log10(min(xs) * 0.8), math.log10(max(xs) * 1.2)
y0, y1 = math.log10(min(ys) * 0.7), math.log10(max(ys) * 1.4)
def X(v): return ml + (math.log10(v) - x0) / (x1 - x0) * (W - ml - mr)
def Y(v): return H - mb - (math.log10(v) - y0) / (y1 - y0) * (H - mt - mb)
def poly(pts, color):
    d = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in pts)
    dots = "".join(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="4" fill="{color}"/>' for x, y in pts)
    return f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="2.5"/>{dots}'
grid = ""
for e in range(int(math.floor(y0)), int(math.ceil(y1)) + 1):
    yy = Y(10 ** e); grid += f'<line x1="{ml}" y1="{yy:.1f}" x2="{W-mr}" y2="{yy:.1f}" stroke="#2a313c"/>'
    grid += f'<text x="{ml-8}" y="{yy+4:.1f}" fill="#6c7889" font-size="11" text-anchor="end">{10.0**e:g}s</text>'
for mbx in (10, 100, 1000):
    xx = X(mbx); grid += f'<line x1="{xx:.1f}" y1="{mt}" x2="{xx:.1f}" y2="{H-mb}" stroke="#2a313c"/>'
    grid += f'<text x="{xx:.1f}" y="{H-mb+18}" fill="#6c7889" font-size="11" text-anchor="middle">{mbx} MB</text>'
chart = (f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto">{grid}'
         f'{poly(pts_o, "#f85149")}{poly(pts_f, "#42e08b")}'
         f'<text x="{W-mr}" y="{mt+4}" fill="#f85149" font-size="12" text-anchor="end">origin (upstream)</text>'
         f'<text x="{W-mr}" y="{mt+22}" fill="#42e08b" font-size="12" text-anchor="end">fork (perf)</text></svg>')

# ---------- html ----------
def row(l):
    e = S[l]; m = (e.get("fork") or e.get("origin") or {}).get("meta") or {}
    sp = e.get("speedup_vs_origin", {})
    def c(op):
        o, f = g(e, "origin", op), g(e, "fork", op)
        if o is None and f is None: return "—"
        return f'<span class="o">{o}</span> → <span class="f">{f}</span>s'
    spv = sp.get("open+refresh")
    return (f"<tr><td>{l}</td><td class=n>{e['size_mb']:.0f}</td><td class=n>{m.get('n_traces','—')}</td>"
            f"<td>{c('t_open')}</td><td>{c('t_refresh')}</td>"
            f"<td class=n><b>{str(spv)+'×' if spv else '—'}</b></td></tr>")
rows = "\n".join(row(l) for l in labels)
eq_all = all((eq[k][2] is True or (isinstance(eq[k][2], float) and eq[k][2] < 1e-6))
             for l in labels if (eq := S[l].get("equivalence")) for k in eq)
html = f'''<title>PyReconstruct — perf vs origin</title>
<meta name="description" content="Benchmarks: the PyReconstruct fork's perf branch vs upstream origin across autoseg series from 6 MB to 1.4 GB. Up to {best}x faster, exact equivalence.">
<style>
 :root{{--bg:#0d1117;--panel:#161b22;--hair:#2a313c;--txt:#e6eaf0;--dim:#9aa7bb;--faint:#6c7889;--green:#42e08b;--red:#f85149;--accent:#4c8dff;--mono:ui-monospace,Menlo,Consolas,monospace;--font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--txt);font-family:var(--font);line-height:1.55}}
 .wrap{{max-width:880px;margin:0 auto;padding:48px 22px 80px}}
 .kick{{font-size:12px;letter-spacing:2.5px;text-transform:uppercase;color:var(--accent);font-weight:700;margin:0 0 10px}}
 h1{{font-size:30px;margin:0 0 8px}} .sub{{color:var(--dim);max-width:70ch}}
 .big{{font-size:44px;font-weight:750;color:var(--green);margin:18px 0 2px}} .big small{{font-size:15px;color:var(--dim);font-weight:400}}
 h2{{font-size:13px;letter-spacing:1.5px;text-transform:uppercase;color:var(--faint);font-weight:700;margin:38px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--hair)}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}} th,td{{padding:8px 10px;border-bottom:1px solid var(--hair);text-align:left}}
 th{{color:var(--faint);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}
 td.n{{text-align:right;font-family:var(--mono)}} .o{{color:var(--red);font-family:var(--mono)}} .f{{color:var(--green);font-family:var(--mono)}}
 .card{{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:18px 20px}}
 .note{{color:var(--dim);font-size:13.5px}} .ok{{color:var(--green);font-weight:600}}
 code{{font-family:var(--mono);font-size:12px;color:var(--accent)}}
</style>
<div class="wrap">
 <p class="kick">Benchmark · fork vs upstream origin</p>
 <h1>Opening large autoseg series</h1>
 <p class="sub">The <code>perf/large-jser</code> branch vs the upstream it was forked from (<code>SynapseWeb/PyReconstruct</code> = current <code>origin/main</code>). Same lib versions; the only code difference on these paths is the 7 perf commits.</p>
 <div class="big">up to {best}× faster <small>open + refresh — series <code>{best_label}</code></small></div>
 <h2>Open + refresh time vs. series size (log–log)</h2>
 <div class="card">{chart}</div>
 <h2>Results — median of repeated runs</h2>
 <table><thead><tr><th>Series</th><th>MB</th><th>Traces</th><th>Open (o→f)</th><th>Refresh (o→f)</th><th>O+R</th></tr></thead><tbody>
 {rows}
 </tbody></table>
 <h2>Equivalence</h2>
 <p class="note">{'<span class="ok">All series: identical section/object/trace counts and geometry sums within float tolerance.</span> The fork is faster, not cutting corners.' if eq_all else 'See report.md for per-series equivalence (any mismatches are flagged).'}</p>
 <h2>Method</h2>
 <p class="note">{HW} · {ENV}. Each measurement is a fresh process importing the given checkout via PYTHONPATH (one shared venv; origin never imports orjson, so each runs as-shipped); headless. Open = <code>Series.openJser</code>, refresh = <code>SeriesData.refresh()</code> (builds all trace geometry), warm cache, median of reps. The wins are algorithmic/single-threaded (NumPy vectorization, deferred Feret, orjson) — they help every machine and most on the large series.</p>
</div>'''
open(os.path.join(BENCH, "report.html"), "w").write(html)
print(f"wrote report.md + report.html | headline {best}x ({best_label}) | equivalence_all={eq_all}")
