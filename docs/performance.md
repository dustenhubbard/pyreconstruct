# Performance

This distribution is significantly faster than the upstream it forked from on the
paths that dominate day-to-day work on large series - **up to 4.19x faster** on
the best-measured series (ZGBJY), with **exact geometry equivalence** (the
speedup is not from skipped work).

The wins are algorithmic and single-threaded (NumPy-vectorized trace geometry,
deferred Feret-diameter computation, NumPy point mapping, orjson-backed `.jser`
I/O, and scoped object operations), so they help every machine and
disproportionately help the large autosegmented series that were previously near
unusable.

## Opening large series

Measured open times (`Series.openJser`), medians of repeated warm runs, upstream
origin to this fork. Measured at fork commit `8e9e185` against upstream
`7b2c92f`:

| Series | Size | Traces | Open (origin -> fork) |
|---|--:|--:|---|
| crop_1 | 6 MB | 2,209 | 1.12 s -> 0.33 s |
| ZGBJY | 7 MB | 2,511 | 1.73 s -> 0.41 s |
| crop_2 | 92 MB | 27,525 | 18.9 s -> 4.8 s |
| GBSFW | 127 MB | 61,121 | 28.3 s -> 8.8 s |
| NVWXP | 187 MB | 83,126 | 38.8 s -> 12.0 s |
| crop_3 | 312 MB | 89,388 | 63.2 s -> 17.0 s |

A later re-measurement on a different dataset (a real 407 MB autosegmented series
with 161,767 traces, plus size-scaled derivatives up to 1.1 GB and 485,301
traces) confirms the same picture: opens improved roughly 3.3-3.8x, cold and
warm alike.

Per-series geometry equivalence (section, object, and trace counts, plus summed
area / length / radius) is exact across the board.

## Interactive editing

Two further wins landed after the open-path work, both measured end-to-end on
the real gestures:

- **Lasso select and merge** on trace-dense sections: a cached anchor mask
  (exact - zero mismatches against the previous scalar code) took a scripted
  lasso sweep from 13.67 s to 1.00 s - **13.7x faster**.
- **Dense-view rendering**: batching the per-point Qt allocation on the paint
  path (pixel-identical by construction) made dense full-frame redraws **1.59x
  faster** (13.16 s to 8.27 s).

## Memory

Feret diameters are now computed on demand instead of being precomputed and
retained for every trace. The retained size of a closed trace's cached data is a
constant **392 bytes at any point count** (previously 648 bytes at 4 points,
rising to 16,520 bytes at 500 points) - about **75% less** trace-data memory on
a 20,000-trace series at 64 points per trace, and 88% less on the shipped
example series.

## Full report and method

The complete report - including the equivalence checks, per-commit attribution,
hardware and dependency versions, and the measurement methodology - and the
reproducible benchmark harness live in the repository:

- **[benchmarks/REPORT.md](https://github.com/dustenhubbard/PyReconstruct/blob/main/benchmarks/REPORT.md)**
  - the full report.
- **[benchmarks/](https://github.com/dustenhubbard/PyReconstruct/tree/main/benchmarks)**
  - the harness (`harness.py`, `orchestrate.py`, `build_report.py`) and raw
  results.
