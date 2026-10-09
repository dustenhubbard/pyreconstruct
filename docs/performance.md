# Performance

This distribution opens large series about **3x faster** than the upstream
PyReconstruct it tracks: **3.34x** on a real 427 MB autosegmented series opened
for the first time, and **2.86x** when reopening it. Both versions load every
trace from the same file. This distribution defers Feret-diameter computation
until a Feret value is needed.

The wins are algorithmic and single-threaded (NumPy-vectorized trace geometry,
deferred Feret-diameter computation, NumPy point mapping, orjson-backed `.jser`
I/O, and scoped object operations), so they help every machine and help most on
large autosegmented series. Small series gain much less.

## Opening large series

Open is `Series.openJser`, which reads the series and builds every trace's
geometry: what PyReconstruct does when you open a series. "First open" parses
the whole `.jser`; "reopen" uses the unpacked copy PyReconstruct keeps beside
it. The benchmark then runs one extra full `SeriesData.refresh()`, the same
pass PyReconstruct repeats after some edits; the second table includes it.

I measured on October 9, 2026 at fork commit `d021a9ec` against upstream commit
`af3f8176` (they share `5f324e2b`; upstream has 56 commits since that are not in
this fork), on an AMD EPYC 7352 (96 threads, 504 GiB) with Python 3.11. Both
versions ran in one shared Python environment, so only the code differs. Each
figure is the median of 3 runs, each in a fresh process. The 1-minute load
average was 4.56-18.43. Times are upstream -> this fork.

| Series | Size | Traces | First open | Speedup | Reopen | Speedup |
|---|--:|--:|---|--:|---|--:|
| class_series (small example) | 0.6 MB | 232 | 0.21 s -> 0.17 s | **1.25x** | 0.14 s -> 0.14 s | **0.95x** |
| WVHJM (autosegmented) | 427 MB | 161,767 | 132.77 s -> 39.76 s | **3.34x** | 87.15 s -> 30.51 s | **2.86x** |

With the extra refresh, each time below is the open median plus the refresh
median:

| Series | First open + extra refresh | Speedup | Reopen + extra refresh | Speedup |
|---|---|--:|---|--:|
| class_series (small example) | 0.32 s -> 0.24 s | **1.34x** | 0.25 s -> 0.22 s | **1.16x** |
| WVHJM (autosegmented) | 219.42 s -> 67.89 s | **3.23x** | 175.79 s -> 59.13 s | **2.97x** |

| Series | Peak memory, first open + extra refresh | Peak memory, reopen + extra refresh |
|---|---|---|
| class_series (small example) | 145 MiB -> 115 MiB | 142 MiB -> 113 MiB |
| WVHJM (autosegmented) | 2,010 MiB -> 2,937 MiB | 434 MiB -> 873 MiB |

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
