
# PyReconstruct performance: fork vs. upstream origin

Hard, reproducible benchmarks of the `perf/large-jser` branch against the upstream it was forked from (`SynapseWeb/PyReconstruct@7b2c92f`, which is the current `origin/main`). The **only** difference between the two on the measured code paths is the 7 performance commits.

**Headline:** up to **4.19× faster** to open+refresh a series (`ZGBJY`); geometry equivalence is exact.

## Results (median of repeated runs)

| Series | Size | Traces | Open (origin→fork) | Refresh (origin→fork) | Open+Refresh speedup | Peak RAM (origin→fork) |
|---|--:|--:|---|---|--:|---|
| crop_1 | 6 MB | 2209 | 1.1154→0.3246s | 1.154→0.335s | 3.44× | 220→222 MB |
| ZGBJY | 7 MB | 2511 | 1.7328→0.409s | 1.7517→0.422s | 4.19× | 236→237 MB |
| crop_2 | 92 MB | 27525 | 18.8694→4.7786s | 18.8129→5.0221s | 3.84× | 743→780 MB |
| GBSFW | 127 MB | 61121 | 28.323→8.7626s | 28.6276→9.1213s | 3.18× | 1079→1102 MB |
| NVWXP | 187 MB | 83126 | 38.7869→12.0432s | 39.2902→12.3581s | 3.2× | 1401→1440 MB |
| crop_3 | 312 MB | 89388 | 63.2351→16.9502s | 64.1214→17.5764s | 3.69× | 384→799 MB |
| crop_4 | 701 MB | 204622 | 143.1437→48.515s | 145.8832→39.4416s | 3.29× | 630→3276 MB |
| crop_ROIsmall | 1400 MB | 492574 | 288.2674→100.9963s | 296.4425→86.8397s | 3.11× | 1069→6374 MB |

## Equivalence (speed is not from skipped work)

Per series, fork vs origin after refresh:

| Series | sections | objects | traces | Σarea rel.diff | Σlength rel.diff | Σradius rel.diff |
|---|--:|--:|--:|--:|--:|--:|
| crop_1 | ✓ | ✓ | ✓ | 0 | 0 | 0 |
| ZGBJY | ✓ | ✓ | ✓ | 0 | 0 | 0 |
| crop_2 | ✓ | ✓ | ✓ | 0 | 0 | 0 |
| GBSFW | ✓ | ✓ | ✓ | 0 | 0 | 0 |
| NVWXP | ✓ | ✓ | ✓ | 0 | 0 | 0 |
| crop_3 | ✓ | ✓ | ✓ | 0 | 0 | 0 |
| crop_4 | ✓ | ✓ | ✓ | 0 | 0 | 0 |
| crop_ROIsmall | ✓ | ✓ | ✓ | 0 | 0 | 8.2e-12 |

## Attribution

`baseline` = the fork's `main` (`bafd899`) without the perf commits. Where measured, `baseline ≈ origin`, confirming the fork's non-perf fixes are performance-neutral — so the fork↔origin gap is attributable to the 7 perf commits (vectorized trace geometry, lazy Feret diameter, NumPy point mapping, orjson JSON, scoped object ops).

## Method

- Hardware: AMD EPYC 7352 (96 threads) · 503 GB RAM · Linux 6.8
- Environment: Python 3.11.15 · PySide6 6.5.2 · NumPy 1.24.1 · SciPy 1.14.1 · Shapely 2.1.1 · orjson 3.11.8 (fork only)

- Each measurement is a fresh Python process importing that checkout's `PyReconstruct` via `PYTHONPATH`; one shared venv (origin never imports orjson, so each runs as-shipped). Headless (`QT_QPA_PLATFORM=offscreen`).

- Ops: **open** = `Series.openJser`; **refresh** = `SeriesData.refresh()` (builds every trace's geometry); **save** = `Series.saveJser`. Warm cache; median of repeated reps (5 for ≤10 MB, 3 for ≤200 MB, 2 above). Save skipped on series >300 MB.

- The wins are algorithmic/single-threaded (NumPy vectorization, deferred work, orjson) — the core count does not carry them; they help every machine, and disproportionately the large autoseg series that were previously near-unusable.
