# Performance

This distribution opens and loads large series about **3x faster** than the
upstream PyReconstruct it tracks: **3.23x** on a real 427 MB autosegmented series
opened for the first time, and **2.97x** when reopening it. Both versions build
the same traces from the same file, so the speedup is not from skipped work.

The wins are algorithmic and single-threaded (NumPy-vectorized trace geometry,
deferred Feret-diameter computation, NumPy point mapping, orjson-backed `.jser`
I/O, and scoped object operations), so they help every machine and help most on
large autosegmented series. Small series gain much less.

## Opening large series

Open is `Series.openJser`. Load is `SeriesData.refresh()`, which builds every
trace's geometry and is what PyReconstruct does right after an open. "First open"
parses the whole `.jser`; "reopen" uses the unpacked copy PyReconstruct keeps
beside it. Each figure is the median of 3 runs, each in a fresh process. Both
versions run in one shared Python environment, so only the code differs.

Measured October 9, 2026 at fork commit `d021a9ec` against upstream commit
`af3f8176` (they share `5f324e2b`; upstream has 56 commits since that are not in
this fork), on an AMD EPYC 7352 (96 threads, 504 GB) with Python 3.11. The
1-minute load average was 4.56-18.43. Times are upstream -> this fork.

| Series | Size | Traces | Open, first time | First open + load | Speedup | Reopen + load | Speedup |
|---|--:|--:|---|---|--:|---|--:|
| class_series (small example) | 0.6 MB | 232 | 0.21 s -> 0.17 s | 0.32 s -> 0.24 s | **1.34x** | 0.25 s -> 0.22 s | **1.16x** |
| WVHJM (autosegmented) | 427 MB | 161,767 | 132.77 s -> 39.76 s | 219.42 s -> 67.89 s | **3.23x** | 175.79 s -> 59.13 s | **2.97x** |

| Series | Peak memory, first open + load | Peak memory, reopen + load |
|---|---|---|
| class_series (small example) | 145 MB -> 115 MB | 142 MB -> 113 MB |
| WVHJM (autosegmented) | 2,010 MB -> 2,937 MB | 434 MB -> 873 MB |

Peak memory is higher here than upstream: about 1.5x on a first open of the large
series and 2x on a reopen.

Both versions read the same sections, objects and traces. Total area and length
agree to floating-point rounding. Total radius differs by about 2 parts in 10
billion, because this distribution sums trace geometry relative to each trace's
first point so that it stays precise far from the origin.

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
