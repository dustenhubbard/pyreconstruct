# PyReconstruct performance: fork vs. upstream

Local performance study of this fork against the upstream commit the original
report compared against, `SynapseWeb/PyReconstruct@7b2c92f`.

**Status: Phase 0 of `dev/REFACTOR_PLAN.md`.** The memory figures this file
published in June 2026 are withdrawn — they were an artefact of the harness, not
of the code. The correction is below, followed by re-measured warm-vs-warm and
cold-vs-cold numbers, a cold-spike attribution, and an interactive profile whose
purpose is to decide the plan's Phase 2 (Rust) gate.

> **ERRATA 2026-07-28 — two of this report's forward-looking figures were
> overturned when the work was implemented.** The `cv2.polylines` "22-26×"
> (§7) and the "24.7 s" caching opportunity (§5, refinement 3) were
> **projections from micro-benchmarks**, not measurements of the real code
> paths, and both inverted on contact with those paths: the rasterizer swap
> would have been ~12× *slower* and was rejected; the `refresh()` Section cache
> saves 8.21 s, well short of what §5 implied, at a cost of +2217 MB, and was
> rejected. Each
> is annotated inline where it appears — struck, with the measurement that
> replaced it — and §7a summarises which Phase 0 figures were projections,
> which were measurements, and what the delivered work actually did.
> **The report's two headline conclusions are unaffected:** the ~3.3-3.6×
> open+refresh speedup and the "cut the Rust workstream" verdict both survive.

**Which commit measured what** (these differ; they are not mixed):

| measurement | fork side | upstream side |
|---|---|---|
| open/refresh/memory matrix | `8e9e185` (fork `main`) | `7b2c92f` |
| interactive profile, open decomposition | `5ac6c2b` (fork `main`, incl. #92/#93) | n/a |
| sparse-view profile cross-check | `8e9e185` | n/a |

The matrix predates #92 (dead grid-cut deletion, 3D tform vectorization) and #93
(Qt-free `transform.py`). Neither changes `Series.openJser` or
`SeriesData.refresh`; #93 carries its own bitwise equivalence oracle
(`tests/test_transform_qt_equivalence.py`). The matrix has **not** been re-run on
top of them — a re-run costs ~3 h of wall clock — so its numbers are labelled
`8e9e185` and should not be quoted as current-HEAD figures. The profile *was*
re-run at `5ac6c2b`, and §6a reports both so the effect of those merges on the
render path is visible rather than assumed.

---

## 1. Correction — why the 3276 MB / 6374 MB figures were withdrawn

The June 2026 report headlined a memory regression of 630 → 3276 MB (`crop_4`)
and 1069 → 6374 MB (`crop_ROIsmall`). Those numbers are not measurements of a
steady state. Three independent harness defects produced them, and all three are
reproducible from the retained raw data (`results.jsonl`, kept in place as
evidence; `aggregate.py` now refuses to process it).

### Defect 1 — the "median" was a mean of two different workloads

`Series.openJser` short-circuits. If a hidden unpack directory `.<name>/`
containing `<name>.ser` sits beside the `.jser`, the series is built from those
per-section files and the `.jser` is **never parsed** (`series.py:239-258`).
Otherwise the whole JSON is parsed and the hidden dir written (`series.py:332`
onward). The old harness never deleted that directory, so rep 0 ran the parse and
rep 1 took the fast path — then aggregation took `statistics.median` of two reps,
which is their mean:

| series | fork rep 0 (cold) | fork rep 1 (warm) | mean | old REPORT.md figure |
|---|--:|--:|--:|--:|
| `crop_4` | 4991.9 MB | 1559.6 MB | **3275.8 MB** | 3276 MB |
| `crop_ROIsmall` | 9831.8 MB | 2915.4 MB | **6373.6 MB** | 6374 MB |

The same arithmetic reproduces the timings: `crop_4` fork open was 58.434 s cold
and 38.596 s warm, mean 48.515 s — the old table's "48.515s". The published
figures *are* cold/warm means.

### Defect 2 — fork-first ordering meant upstream was never measured cold

Checkouts ran in a fixed order, fork first, and the size-based warmup policy gave
series >700 MB zero warmups. On exactly the two headline series the fork's rep 0
paid the full parse **and created the hidden dir**, after which every upstream rep
took the fast path:

| series | fork reps (peak RSS) | upstream reps (peak RSS) |
|---|---|---|
| `crop_4` | 4991.9 (cold), 1559.6 (warm) | 629.0, 630.1 — **both warm** |
| `crop_ROIsmall` | 9831.8 (cold), 2915.4 (warm) | 1068.0, 1069.9 — **both warm** |

Two upstream reps near-identical while the fork's differ 3.2× is the fingerprint.
`crop_3` (312 MB) got one warmup, so all four of its reps were warm — which is why
that row was internally consistent at 2.08× and is the only large-series row of
the old table that survives.

### Defect 3 — the peak-RSS column mixed save-enabled with save-skipped rows

`saveJser` was skipped only above 300 MB, and it dominates peak RSS where it runs.
The old "Peak RAM" column was therefore not comparable down its own length:

| series | size | `saveJser` ran? | upstream peak RSS | traces |
|---|--:|:--:|--:|--:|
| `crop_2` | 92 MB | yes | 743 MB | 27,525 |
| `GBSFW` | 127 MB | yes | 1079 MB | 61,121 |
| `NVWXP` | 187 MB | yes | 1403 MB | 83,126 |
| `crop_3` | 312 MB | **no** | 383 MB | 89,388 |
| `crop_4` | 701 MB | **no** | 629 MB | 204,622 |

89,388 traces appearing to need less memory than 27,525 is the save step, not the
series.

### What was and was not affected

- **Withdrawn:** every peak-RSS figure in the old table, and the open/refresh
  timings for `crop_4` and `crop_ROIsmall` (cold/warm means).
- **Unaffected:** timings for `crop_1`, `ZGBJY`, `crop_2`, `GBSFW`, `NVWXP`,
  `crop_3`, whose reps were uniformly warm. The ~3-4× open+refresh speedup was
  never what was wrong. The *memory regression* was overstated by roughly 3×, and
  its attribution to this fork was never tested at all.

---

## 2. Harness changes

`orchestrate.py`, `harness.py` and `aggregate.py` were rewritten so the defects
cannot recur:

- cold and warm are **explicit, separately-labelled conditions**. The hidden dir
  is deleted before every cold rep; for warm it is deleted once and primed by one
  unmeasured open from the *same* checkout, then reused across that checkout's
  reps.
- `harness.py` **observes** which path `openJser` actually took and reports it as
  `cache_state`. `orchestrate.py` aborts (exit 3) if a rep's observed state
  disagrees with its intended label; `aggregate.py` aborts if such a row reaches
  it. A label is earned, not assumed.
- `aggregate.py` groups by `(series, checkout, condition)` and **never pools cold
  with warm**. It rejects result files lacking a `condition` field outright — which
  includes the old `results.jsonl`.
- a **loud pre-flight manifest** prints and records PRESENT/MISSING per series. A
  missing file is a hard error (exit 2) unless `--allow-missing`, which records
  every skip as a row. The silent `MISSING ... continue` is gone.
- warmup treatment is **identical for every series regardless of size**; only the
  subprocess timeout scales, and it is a crash guard, not a measurement policy.
- checkout order is **rotated per rep**, so no checkout is systematically first.
- the OS page cache is primed before every rep, pinning that axis warm for both
  checkouts. `drop_caches` needs root, so "cold" means *application*-cold.
- `save_skipped` is recorded per rep; per-rep `spread_pct` accompanies every
  median so a bimodal group cannot hide behind a central number.

These guards were verified by negative test, not by inspection: a hand-edited
mismatched label exits 3, a `condition`-less file exits 2, and the committed
pre-Phase-0 `results.jsonl` exits 2.

---

## 3. Benchmark data — what exists now

**None of the eight original lab series could be found on this machine.** All four
parent directories the harness pointed at — `autoseg_large_slow_1`,
`autoseg_large_slow_2`, `autoseg_large_slow_3` and `cropped_small_class` under
`/home/dusten/projects/testing/` — no longer exist, and a size-and-name sweep of
`/data` (`data1`-`data6`) and `/home` turned up no `.jser` matching any of the eight
names and nothing above 430 MB except unrelated 17 GB SSVQM exports. So none of
`crop_1`, `ZGBJY`, `crop_2`, `GBSFW`, `NVWXP`, `crop_3`, `crop_4` or
`crop_ROIsmall` could be re-measured. Stated explicitly rather than silently
skipped, per the plan's own manifest rule. (The sweep was breadth-limited, so this
is "not found", not a proof of deletion; the files may exist on other lab storage.)

The re-run uses the largest real autoseg series still present plus two size-scaled
derivatives built by `make_scaled_series.py` (the plan's open question #7,
answered locally):

| label | size | sections | traces | provenance |
|---|--:|--:|--:|---|
| `WVHJM_407` | 407 MB | 318 | 161,767 | real — copied from `/data/data5/vijay/LYNDS/WVHJM_20260203_ROI_D011_with_labels.jser` |
| `WVHJM_x2` | 745 MB | 636 | 323,534 | synthetic — sections replicated ×2 |
| `WVHJM_x3` | 1118 MB | 954 | 485,301 | synthetic — sections replicated ×3 |

All three, plus the series spec and the run log, are left in place on this machine
at `/home/dusten/projects/testing/bench_phase0/` (~2.3 GB), so the matrix can be
re-run without regenerating anything. The two synthetic files are reproducible from
the real one:

```bash
uv run python benchmarks/make_scaled_series.py WVHJM_407.jser WVHJM_x2.jser --factor 2
uv run python benchmarks/make_scaled_series.py WVHJM_407.jser WVHJM_x3.jser --factor 3
```

The scaled pair brackets the two withdrawn rows: `WVHJM_x2` sits in `crop_4`'s
size class (701 MB) and `WVHJM_x3` matches `crop_ROIsmall`'s trace count almost
exactly (485,301 vs 492,574). Geometry, tag vocabulary and row layout are inherited
from real autoseg data, so the per-trace work is representative; only the volume is
synthetic.

Two limitations to keep in view when quoting these rows:

- Replicated sections are **not** independent specimens. Read them as "a series
  with this many sections and traces", not as new tissue.
- Replication multiplies sections and traces but **reuses object names**, so the
  object count is identical across all three (12,861) while traces go
  161,767 → 323,534 → 485,301. A genuinely larger crop would also contain more
  distinct objects, so per-object overhead is under-represented here.

That second limitation turns out to be informative rather than merely a caveat:
because object count is held constant while trace count triples, and the
warm-vs-warm memory ratio still climbs monotonically (2.05× → 2.39× → 2.55×), the
regression scales with **traces, not objects**. That is direct support for the
plan's Phase 1d hypothesis that the cost is a per-trace retained stash
(`TraceData._feret_points`) rather than per-object bookkeeping.

---

## 4. Results — warm-vs-warm and cold-vs-cold

Medians of 3 reps. `save` skipped on all three series (uniformly, unlike the old
table). Raw data: `results_phase0.jsonl`; aggregation: `summary_phase0.csv`.

| series | size | traces | cond | open (up→fork) | refresh (up→fork) | open+refresh | peak RSS (up→fork) | RSS ratio |
|---|--:|--:|:--:|---|---|--:|---|--:|
| `WVHJM_407` | 407 MB | 161,767 | cold | 127.95→34.92 s | 84.33→27.25 s | 3.42× | 2047→2948 MB | **1.44×** |
| `WVHJM_407` | 407 MB | 161,767 | warm | 84.20→25.25 s | 85.91→26.38 s | 3.30× | 469→964 MB | **2.05×** |
| `WVHJM_x2` | 745 MB | 323,534 | cold | 263.59→75.56 s | 170.12→50.32 s | 3.44× | 3850→5636 MB | **1.46×** |
| `WVHJM_x2` | 745 MB | 323,534 | warm | 168.25→49.93 s | 172.16→53.51 s | 3.29× | 743→1773 MB | **2.39×** |
| `WVHJM_x3` | 1118 MB | 485,301 | cold | 387.56→101.18 s | 253.05→74.46 s | 3.65× | 5690→8392 MB | **1.48×** |
| `WVHJM_x3` | 1118 MB | 485,301 | warm | 253.73→74.67 s | 258.38→80.64 s | 3.30× | 1009→2577 MB | **2.55×** |

### The steady-state memory regression is real: ~2.4-2.6× warm-vs-warm

This is the defensible replacement for the withdrawn figures, and it independently
reproduces what the plan predicted from the old warm reps (2.5× / 2.7×):

- `WVHJM_x2`: 743 → 1773 MB (**2.39×**)
- `WVHJM_x3`: 1009 → 2577 MB (**2.55×**)

The regression grows mildly with trace count (2.05× at 162k traces, 2.39× at 324k,
2.55× at 485k), consistent with per-trace retained state rather than a fixed
overhead — i.e. consistent with the deferred-Feret point stash the plan identifies
in Phase 1d.

### Most of the cold spike is NOT checkout-attributable

Cold-vs-cold is only **1.44-1.48×**, far below the warm ratio, because *upstream
spikes when cold too* — something the old harness never measured:

| series | checkout | warm peak | cold peak | cold overhead | warm→cold |
|---|---|--:|--:|--:|--:|
| `WVHJM_407` | upstream | 469 MB | 2047 MB | +1577 MB | 4.36× |
| `WVHJM_407` | fork | 964 MB | 2948 MB | +1984 MB | 3.06× |
| `WVHJM_x2` | upstream | 743 MB | 3850 MB | +3107 MB | 5.18× |
| `WVHJM_x2` | fork | 1773 MB | 5636 MB | +3864 MB | 3.18× |
| `WVHJM_x3` | upstream | 1009 MB | 5690 MB | +4680 MB | 5.64× |
| `WVHJM_x3` | fork | 2577 MB | 8392 MB | +5816 MB | 3.26× |

**Attribution:** of the fork's cold spike, the portion in excess of upstream's is
407 MB of 1984 MB on `WVHJM_407` (**20.5%**), 757 MB of 3864 MB on `x2`
(**19.6%**), and 1135 MB of 5816 MB on `x3` (**19.5%**). The figure is stable at
about a fifth across a 3× size range, so:

> **~80% of the cold-open memory spike is inherent to the shared JSON-parse and
> unpack path, is present in upstream, and is not attributable to this fork.
> ~20% is fork-attributable.**

In relative terms upstream's cold spike is *worse* (4.4-5.6× its warm baseline vs
the fork's 3.1-3.3×), because the fork's warm baseline is already higher.

The cold peak is also **transient, not retained**. Resident size immediately after
open, versus the peak during it (`WVHJM_x2`):

| checkout | condition | RSS after open | peak RSS during open |
|---|---|--:|--:|
| fork | cold | 1564 MB | 5636 MB |
| fork | warm | 961 MB | 1773 MB |
| upstream | cold | 1023 MB | 3850 MB |
| upstream | warm | 471 MB | 743 MB |

The cold peak is the whole parsed JSON document held live at once, then released.
That points at streaming/incremental parse, exactly as the plan's Phase 1d note
says — and it is a *shared* problem, not a fork regression.

### Speed: the ~3.3-3.6× open+refresh win holds in both conditions

Now measured per-condition rather than across a cold/warm mixture: 3.42-3.65×
cold, 3.30× warm on all three series. The original speedup claim survives the
correction intact.

### Measurement quality

`peak_rss_spread_pct` is **0.0-0.7% on every one of the twelve groups** — the memory
conclusions are insensitive to load. Timing spread is 0.1-7.2% except `WVHJM_x3`
fork cold at 14.2%, where one of three reps overlapped a concurrent profiling run;
the median is robust to that single outlier, which is why 3 reps were used
instead of 2.
Some `WVHJM_407` reps and some `x2`/`x3` reps ran alongside profiling work on the
same 96-thread box; because checkout order is rotated per rep, such load hits both
checkouts rather than biasing the ratio.

---

## 5. Where the time in an open actually goes (745 MB, 323,534 traces)

An independent audit of the shipped 560 KB `class_series.jser` found `openJser` at
71.6 ms with the JSON codec only 6.1 ms (8%), concluding that ~90% is per-section
unpack choreography plus Python object construction. Measured at ~1300× that size
with `decompose_open.py`:

One pass over every section is what a warm open costs. `SeriesData.refresh()` *is*
that pass: it iterates `enumerateSections()`, which calls `loadSection()` →
`Section(n, series)` per section, and `loadSection` does not cache
(`series.py:954-963`). So refresh re-reads, re-decodes and re-builds every section
on top of computing geometry, and geometry proper is the remainder:

| stage of one pass | seconds | share of the pass |
|---|--:|--:|
| A — read all 636 section files (pure I/O) | 0.30 | 0.6% |
| B — `fast_loads` each section file (codec) | 8.37 | 15.7% |
| C — build `Section`/`Trace`/`Transform` objects | 16.35 | **30.7%** |
| D — geometry proper (= 53.29 − 25.02, derived) | 28.27 | **53.0%** |
| = `SeriesData.refresh()` measured | 53.29 | 100% |

That total (53.29 s) closely matches the independently measured warm `openJser` for
this series (49.93 s, §4), which is the cross-check that the interpretation is
right: a warm open is one such pass.

Separately, the whole-file `.jser` codec on its own is **11.23 s = 16.3% of the
68.8 s cold open**; both codec passes together (11.23 + 8.37) are **19.60 s =
28.5%** of a cold open.

**This corroborates the audit's conclusion and sharpens it.** The serialization
codec is a minority cost at real scale too. Python object construction alone
(16.35 s) exceeds the whole-file codec, and geometry (28.27 s) exceeds both.

Three refinements to the audit's framing:

1. **The file count is irrelevant.** Reading all 636 section files takes 0.30 s —
   0.6% of the pass. The cost attributed to per-section "choreography" is not I/O
   at all; it is decode plus object construction. Reducing the number of files buys
   essentially nothing, and neither would replacing many files with one blob.
2. **The codec's share grows with scale** (8% of open at 560 KB → 16.3% at 745 MB;
   28.5% counting both passes), so a binary/streaming format is worth more on big
   series than the fixture suggests — but it is still bounded at ~28% of cold open
   and cannot touch the 30.7% object-construction or 53.0% geometry shares.
3. **`refresh()` doing a redundant re-read is itself a finding.** A warm open pays
   decode + object construction (24.7 s here) to build Sections, and any subsequent
   `refresh()` throws them away and pays it again. ~~Caching or reusing loaded
   Sections is a pure-Python win available without touching the format at all —
   worth more than a codec swap, and not currently in the plan.~~

   > **CORRECTION 2026-07-28 — the caching conclusion is withdrawn; the
   > decomposition it rests on is not.**
   >
   > The 24.7 s is a *measurement* and stands: it is stages B + C of the table
   > above (8.37 + 16.35), the decode and object-construction cost of one pass.
   > The redundant second pass is also real — instrumenting the fork counts
   > **318 `Section` builds at open and 318 more at refresh** on `WVHJM_407`.
   >
   > What was wrong was the *inference* that a cache recovers that 24.7 s. It
   > does not, and the Section cache was **built, measured and REJECTED**:
   >
   > - a **perfect** cache (every Section retained, no eviction) saves
   >   **8.21 s** where this refinement implied ~24.7 s — geometry, not
   >   `Section` construction, dominates what `refresh()` actually redoes.
   >   (Conditions differ and are not interchangeable: the 8.21 s and +2217 MB
   >   were measured on `WVHJM_407` (318 sections), the stage table above on
   >   `WVHJM_x2` (636 sections). The direction of the result is not in doubt —
   >   a saving smaller than the per-pass decode+construction cost of a
   >   half-sized series — but do not subtract one figure from the other);
   > - it costs **+2217 MB RSS (3.65× steady state)**, i.e. ~270 MB retained per
   >   second saved — on the very series where §4 documents a 2.05-2.55× memory
   >   regression we are trying to *reduce*. Trading memory for time is the
   >   wrong direction here;
   > - a **bounded LRU cannot rescue it**: `refresh()` is a sequential scan of
   >   the whole series, which is LRU's worst case — every entry is evicted
   >   before it is reused;
   > - there is a **correctness landmine** independent of performance.
   >   `SeriesData.updateSection` (`series_data.py:262-268`) rebuilds *all*
   >   contours only when `section.getAllModifiedNames()` is empty, and
   >   `Section.save()` is what clears that set. With live Sections retained
   >   across a refresh, mutate-without-save followed by `refresh()` would
   >   rebuild only the modified contours into a data dict that was just
   >   cleared — **silently dropping every other object from the object list**.
   >   Missing, not merely stale.
   >
   > **The real prize in this area is different work:** skip *geometry* for
   > sections whose file is unchanged (mtime/size keyed) in
   > `SeriesData.refresh()`. That needs no extra memory, because `SeriesData`
   > already retains that data between refreshes. Not yet implemented.

**Bottom line for the format decision:** restructuring serialization addresses at
most ~28% of cold-open time and none of the steady-state memory regression in §4.
The larger levers are avoiding materialization of every trace as Python objects
(lazy/columnar sections), and ~~not rebuilding them twice~~ **[2026-07-28: not
rebuilding their *geometry* twice — retaining the Sections themselves was
measured and rejected, see refinement 3 above]**. Streaming the whole-file
parse is still worth doing, but for the *transient memory* peak documented in §4
rather than for time.

The lever with the larger payoff is *avoiding materializing every trace as Python
objects up front* (lazy/columnar sections), not changing how bytes are encoded.
Streaming the whole-file parse would additionally remove the transient cold peak
documented in §4, which is a memory win rather than a time win.

---

## 6. Interactive profile

Scripted offscreen session driving the real widget code — `generateView` frames,
pan, zoom, hover, lasso, knife, merge, section scroll — via
`profile_interactive.py`. The top hotspot **depends on how much is on screen**, so
both regimes are reported.

### 6a. Dense view — a large autoseg series filling the window

`WVHJM_407` at `5ac6c2b`, `--fit` (483 traces in view), cProfile over one full
session, wall 10.973 s. Self time (cProfile `tottime`):

| rank | self % | cum % | function | location |
|--:|--:|--:|---|---|
| 1 | **36.7%** | 36.7% | `<listcomp>` building one `QPoint` per point | `backend/view/trace_layer.py:278` |
| 2 | 10.2% | 46.9% | `numpy.array` (C) | builtin |
| 3 | 8.5% | 55.4% | `numpy.asarray` (C) | builtin |
| 4 | 8.3% | 63.7% | `QPainter.drawPolygon` (Qt C++) | PySide6 |
| 5 | 4.8% | 68.5% | `generateTraceLayer` | `backend/view/trace_layer.py:501` |
| 6 | 4.0% | 72.5% | `isAnchorPoint` | `calc/grid.py:99` |
| 7 | 3.9% | 76.4% | `_drawTrace` | `backend/view/trace_layer.py:250` |
| 8 | 3.4% | 79.8% | `mapPointsArray` | `datatypes/transform.py:180` |
| 9 | 3.2% | 83.0% | `traceToPixArray` | `backend/view/trace_layer.py:80` |
| 10 | 2.8% | 85.8% | `findClosest` | `datatypes/section.py:575` |

The same session at `8e9e185` ranks identically (rank 1 = 3.925 s vs 4.022 s), so
#93's `transform.py` rewrite did not shift the profile; `mapPointsArray` is 3.4%
either way and marginally faster after the rewrite.

**py-spy cross-check** (`artifacts/session_dense_autoseg.speedscope.json.gz`, 99 Hz,
31,135 samples, 8 session iterations; this run also includes the ~57 s open+refresh
setup, so its percentages are diluted relative to the session-only cProfile table):

| self% | function |
|--:|---|
| 22.3% | `<listcomp>` — `trace_layer.py` (rank 1, same as cProfile) |
| 19.1% | `mapPointsArray` — `transform.py` |
| 11.2% | `_drawTrace` — `trace_layer.py` |
| 6.7% | `fast_loads` (setup: open) |
| 6.0% | `pointInPoly` |
| 5.1% | `fromList` (setup: open) |
| 5.1% | `traceGeometry` (setup: refresh) |
| 3.5% | `isAnchorPoint` |

Both profilers put the `trace_layer.py` listcomp first. They disagree on
`mapPointsArray` (19.1% vs 3.4%) and `pointInPoly` (6.0% vs 1.0%) for a
methodological reason that matters to the Rust question: **py-spy attributes a
C-extension call to the innermost *Python* frame, so NumPy and OpenCV time is
folded into the calling Python function; cProfile separates it into `{built-in
method ...}` rows.** cProfile's split is the one that answers "is this time in
Python bytecode or in C?", which is exactly criterion (i) of the gate — so the
cProfile table above is the primary evidence and py-spy is corroboration on
ranking. Read the other way, py-spy's `mapPointsArray` 19.1% is almost entirely
NumPy C time inside an already-vectorized function, and its `pointInPoly` 6.0% is
almost entirely `cv2.pointPolygonTest`.

Rank 1 is `qpoints = [QPoint(int(x), int(y)) for x, y in pix_pts]` inside
`_drawTrace` — a Python-level allocation of one Qt object per trace point, on the
per-frame paint path. The surrounding code is already optimized ("vectorized; no
QPoints yet", bbox cull "before allocating any QPoint/QPolygon"), so this is the
*residual* after the fork's vectorization pass. Together with the `drawPolygon`
that consumes it and the array churn feeding it, the per-point Qt path is ~55% of
a dense frame.

### 6b. Sparse view / gesture-heavy — lasso and merge dominate

`shapes2.jser` fixture at `8e9e185`, py-spy sampling at 99 Hz, 2564 samples over
25.9 s (`artifacts/session_shapes2.speedscope.json`, flamegraph SVG alongside):

| rank | self % | function | location |
|--:|--:|---|---|
| 1 | **48.6%** | `isAnchorPoint` | `calc/grid.py` |
| 2 | 10.5% | `_generateImage` | `backend/view/image_layer.py` |
| 3 | 6.1% | `loadImage` | `backend/view/image_layer.py` |
| 4 | 5.5% | `_settings` (QSettings construction) | `backend/settings_store.py` |
| 5 | 2.9% | `generateView` | `backend/view/section_layer.py` |
| 6 | 2.8% | `_drawGridLine` | `calc/grid.py` |
| 7 | 2.2% | `getAnchorTrace` | `calc/grid.py` |
| 8 | 2.1% | `mapPointsArray` | `datatypes/transform.py` |
| 9 | 2.0% | `_drawTrace` | `backend/view/trace_layer.py` |
| 10 | 1.6% | `generateTraceLayer` | `backend/view/trace_layer.py` |

cProfile on the same session independently puts `isAnchorPoint` at 45.6%, so the
two profilers agree. `grid.py` as a whole is 54% of that session.

One lasso costs ~147 ms even on a 41-trace fixture, because the cost is
`O(lasso pixel area)`, not `O(traces)`. `Grid.getExterior` is reached from lasso
select (`TraceLayer.getTraces`), trace close, and `mergeTraces` — all one-shot
gestures. Note this refines the plan's §1 finding: the plan correctly established
that every *knife/cut* branch of `grid.py` was dead (and #92 has now deleted it),
but `getExterior` → `getAnchorTrace` → `isAnchorPoint` is very much live and is the
single largest cost of a lasso or merge.

`_settings` at 5.5% overall is 69% of hover self-time — a QSettings object
constructed per `getOption` at ~64 µs. It is on the per-frame path and is a
caching problem, not a compute problem.

---

## 7. VERDICT on the Phase 2 (Rust) decision gate

The plan's gate requires *"a residual hotspot that is (i) pure-Python-hot, (ii) on
a per-frame/per-paint path, and (iii) not addressable by the already-landed
numpy/orjson techniques or by batching into existing C libraries (OpenCV, shapely,
Qt)"*, and directs that if the gate fails, **"cut the Rust workstream entirely."**

**The gate FAILS. No hotspot satisfies all three criteria. Recommendation: cut the
Rust workstream.**

Candidate by candidate:

| candidate | (i) pure-Python-hot | (ii) per-frame | (iii) not addressable by C batching | verdict |
|---|:--:|:--:|:--:|---|
| `trace_layer.py:278` QPoint listcomp (36.7%) | **yes** | **yes** | **no** | disqualified on (iii) |
| `grid.py` `isAnchorPoint` (48.6% sparse / 4.0% dense) | **yes** | no | **no** | disqualified on (ii) and (iii) |
| `numpy.array` / `asarray` (18.7%) | no — C | yes | n/a | disqualified on (i) |
| `QPainter.drawPolygon` (8.3%) | no — Qt C++ | yes | n/a | disqualified on (i) |
| `settings_store._settings` (5.5%) | no — QSettings/Qt | yes | **no** — memoize | disqualified on (i), (iii) |
| `image_layer._generateImage`/`loadImage` (16.5%) | no — QImage ops + file I/O | yes | n/a | disqualified on (i) |
| `mapPointsArray` (3.4%) | no — already NumPy-vectorized | yes | n/a | disqualified on (i) |
| `findClosest` (2.8%), `pointInPoly` (1.0%) | no — `cv2.pointPolygonTest` | yes | n/a | disqualified on (i) |

**[2026-07-28: both "no" answers in column (iii) held, and both are now
*implemented* rather than projected — but the QPoint row's fix is `starmap`
batching, not the `cv2.polylines` swap this section proposed (which was measured
and rejected; see the retraction below). The table's verdicts are unchanged.]**

The two genuinely pure-Python hotspots both fail criterion (iii), and this was
**measured, not asserted** — but read the next two bullets with §7a: what was
measured here were *stand-alone micro-benchmarks*, and only one of the two
speedups survived being implemented in the real function.

- **`isAnchorPoint`** is exactly a 3×3 neighbour-count convolution. Replacing the
  scalar loop with `cv2.filter2D` plus a boolean mask is **bit-identical (30/30
  randomized trials, zero mismatches) and 22.8× faster**
  (`artifacts/verify_isanchorpoint_vectorizable.py`).
  **[2026-07-28: HELD UP. Implemented in #97 as a lazily built per-`Grid` cached
  anchor mask. Exact, and end-to-end a lasso sweep on `shapes2` went 13.67 s →
  1.00 s (13.7×), with `getAnchorTrace` alone 60-90×. The 22.8× was the
  micro-benchmark of the kernel; 13.7× is the measured whole-gesture figure and
  is the one to quote.]**
- ~~**The QPoint listcomp** is removable by batching into OpenCV: rasterizing 500
  traces × 120 points via `cv2.polylines` into a buffer is **22-26× faster** than
  the QPoint-per-point path, including the per-frame `int32` cast
  (`artifacts/verify_qpoint_batchable.py`).~~ Rebuilding the same list as a
  `QPolygon` first saves nothing (148.6 ms vs 149.7 ms) — confirming the cost is
  the per-point Python/Qt object construction, not the draw call.

  > **RETRACTED 2026-07-28 — the 22-26× does not exist, and the swap would have
  > been ~12× SLOWER. `cv2.polylines` was REJECTED.**
  >
  > The 22-26× was a projection from a micro-benchmark that drew **every trace
  > in one `cv2.polylines` call in a single colour**. The real `_drawTrace`
  > varies **colour, pen width and opacity per trace**, and per-trace opacity
  > requires a **blend per trace**. Measured on the real per-trace loop:
  > **1814 ms for the OpenCV path vs 155 ms for QPainter** — the swap loses by
  > ~12×. The micro-benchmark was not measuring the work the function does.
  >
  > The pixel caveat below was also *understated*, not merely unquantified: the
  > field **never enables QPainter antialiasing**, so this is not a question of
  > edge softness. Two Bresenham-family rasterizers simply light different
  > pixels — **1102 of 1475 lit outline pixels differ (74.7%), max channel delta
  > 255** on a wobbly blob. For a 1 px non-antialiased trace that is most of
  > what the user sees.
  >
  > `tests/test_trace_layer_qpoint_batching.py::test_qt_and_cv2_rasterizers_disagree_materially`
  > now pins that disagreement so the "just use cv2" idea is not silently
  > retried; it fails if the two rasterizers ever start agreeing, which is the
  > condition under which the swap becomes worth revisiting.
  >
  > **What actually removed the rank-1 hotspot** (#97): the listcomp was
  > replaced by `list(starmap(QPoint, pix_pts.tolist()))` — PySide6 exposes no
  > bulk `QPolygon` constructor — which is **pixel-identical by construction**
  > (0 differing pixels across 11 shapes × 5 draw modes) and worth **1.59× on
  > dense full frames (13.16 s → 8.27 s)**, 1.17× on incremental frames. An
  > allocation-path change, not a rasterizer change. Criterion (iii) is still
  > failed — the hotspot *was* addressable without Rust — but by batching the
  > allocation, not by handing the raster to OpenCV.

Both fixes are the plan's own prescription, not a new proposal: §1's `grid.py`
finding already says that if profiling shows per-gesture latency matters, the
answer is *"`cv2.polylines` + numpy — no Rust"*. Phase 0 profiling *does* flag
lasso select, so that conditional work is now triggered — and its remedy is
OpenCV batching, which is exactly what disqualifies a Rust rewrite under (iii).

**One correction to Phase 1e's lasso remedy.** Phase 1e says: *"If (and only if)
Phase 0 profiling flags lasso select: hoist the polygon conversion out of the loop
in `TraceLayer.getTraces` and batch with shapely `contains_xy`."* Profiling flags
lasso select — but that fix targets the wrong function. The per-point membership
test in `getTraces` is cheap: `pointInPoly` is 1.0% of a dense session and does not
reach the top ten of the lasso-dominated session at all. The cost is the single
`getExterior(pix_poly)` call near the top of `getTraces`
(`trace_layer.py:166`), which rasterizes the lasso polygon onto a `Grid` and then
walks every contour point through `isAnchorPoint` in Python — 86% of lasso self
time when measured in isolation. Batching the inner loop with shapely would leave
essentially all of the lasso latency in place; vectorizing `isAnchorPoint` removes
it.

~~Caveat stated plainly: swapping Qt's rasterizer for OpenCV's changes antialiasing
and pixel output, so it needs golden-file tests and is a *characterized
difference*, not a drop-in. That is a cost of the Phase 1e fix~~ — it is not an
argument for Rust, which would face the identical pixel-equivalence problem plus a
toolchain and distribution burden the plan already prices as unaffordable at a bus
factor of 1.

**[2026-07-28: the caveat turned out to be the decisive objection, not a
manageable cost.** The golden-file tests were written, and they showed the
difference is whole on/off pixels on 74.7% of a trace's lit outline (the field
never antialiases), while the per-trace opacity blend made the OpenCV path ~12×
slower. There was no "characterized difference" worth accepting: the swap was
rejected outright. **Do not read this paragraph as a green light with a
footnote.]**

**Consequence for the plan:** answer "no" to open question #1 — Rust does not
survive Phase 0. Phase 2 should be cut, and its budget redirected to Phase 1e
(vectorize `isAnchorPoint`; ~~batch the trace raster~~ **[batch the QPoint
allocation — the raster itself stays with Qt]**), Phase 1d (the warm-memory
regression measured in §4), and the object-construction cost measured in §5.

---

## 7a. Phase 0's projections vs what implementation measured

**The failure mode this section exists to name: Phase 0 generalised stand-alone
micro-benchmarks to real code paths that do more work.** Both retractions above
have the same shape — a script that isolated one operation was fast, and the
production function around it either did something the script omitted (per-trace
colour, width and opacity) or spent its time somewhere else entirely (geometry,
not `Section` construction). A micro-benchmark bounds a *best case for the
operation it ran*; it is not a prediction about the function it is standing in
for. **Before quoting any row of this report forward, check whether it was
measured on the real path or on a script.**

| Phase 0 figure | kind | what it measured | outcome |
|---|---|---|---|
| ~3.3-3.6× open+refresh (§4) | **measurement** | `Series.openJser` / `SeriesData.refresh()`, 3 reps × 3 series, per-condition | **stands** |
| 2.05-2.55× warm memory regression (§4) | **measurement** | `ru_maxrss`, warm-vs-warm, spread 0.0-0.7% | **stands**; addressed by #98 (Phase 1d) |
| ~80/20 cold-spike attribution (§4) | **measurement** | cold vs warm peaks, both checkouts | **stands** |
| stage table A-D, incl. 24.7 s decode+construction (§5) | **measurement** | `decompose_open.py` on the real pass | **stands as a decomposition** |
| "caching Sections is worth that 24.7 s" (§5.3) | **projection** (inference from the decomposition) | nothing — no cache existed | **REJECTED**: a perfect cache saves 8.21 s at +2217 MB (`WVHJM_407`), plus a data-loss landmine |
| `isAnchorPoint` 22.8× (§7) | **projection** (micro-benchmark) | `cv2.filter2D` vs the scalar loop, in isolation | **held up**: 13.7× measured end-to-end on a lasso sweep (#97) |
| `cv2.polylines` 22-26× (§7) | **projection** (micro-benchmark) | one polylines call, all traces, single colour, no opacity | **REJECTED**: real per-trace loop is 1814 ms vs QPainter's 155 ms (~12× slower) |

Delivered so far, with measured end-to-end figures:

- **#97** — cached `cv2.filter2D` anchor mask (exact): lasso sweep 13.67 s → 1.00 s
  (**13.7×**), `getAnchorTrace` 60-90×. `starmap` QPoint batching
  (pixel-identical, 0 differing pixels over 11 shapes × 5 draw modes): dense full
  frames 13.16 s → 8.27 s (**1.59×**).
- **#98** (Phase 1d) — Feret computed on demand: retained bytes per closed
  `TraceData` become a constant **392 B at any point count** (was 648 B at 4 points
  rising to 16,520 B at 500), i.e. **−75%** on 20k traces × 64 points and **−88%**
  on `class_series`. This attacks the §4 regression directly, which is also why
  spending +2217 MB on a Section cache was the wrong trade.

---

## 8. Method

- Hardware: AMD EPYC 7352 (96 threads) · 503 GB RAM · Linux 6.8
- Environment: one shared venv from `uv.lock` (`uv sync --frozen`), Python 3.11 —
  numpy/scipy/shapely/PySide6 pinned identically for both checkouts, so the
  comparison isolates the *code*. Upstream never imports orjson, so it runs
  as-shipped. The conda envs named in the old README no longer exist.
- Each rep is a fresh process importing that checkout's `PyReconstruct` via
  `sys.path`. Headless (`QT_QPA_PLATFORM=offscreen`).
- Ops: **open** = `Series.openJser`; **refresh** = `SeriesData.refresh()`;
  **save** = `Series.saveJser`, skipped above 300 MB (so skipped uniformly here).
- 3 measured reps per (checkout, series, condition); medians with min/max spread.
  Three rather than two, specifically so a median is not also a mean.
- Peak RSS is `ru_maxrss`; resident size is additionally sampled after open and
  after refresh to separate transient parse cost from retained state.
- The profile keeps the real `QSettingsStore` rather than substituting a dict, and
  redirects `XDG_CONFIG_HOME` to scratch; the render loops were tuned around the
  real store's cost, so replacing it would profile a program that does not ship.
- The autoseg series' zarr images are not mounted on this machine, so §6a excludes
  image-layer cost; §6b (fixture with real `.tif` siblings) includes it. This is
  why `_generateImage`/`loadImage` appear only in the sparse table.
