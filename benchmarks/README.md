# Benchmarks — fork perf vs. upstream origin

Reproducible measurements of the performance work on `perf/large-jser` against the
upstream it was forked from (`SynapseWeb/PyReconstruct`).

## What it measures

For a set of real autoseg `.jser` series (6 MB → 1.4 GB), in a fresh interpreter
per measurement:

- **open** — `Series.openJser(path)` (JSON load; the fork uses orjson)
- **refresh** — `SeriesData(series).refresh()` (builds every trace's geometry; the
  vectorized `traceGeometry` / lazy-Feret path is the dominant win)
- **save** — `Series.saveJser(...)` (JSON dump)

It also records, per series, the section/object/trace counts and summed
area/length/radius so the fork's output can be checked **identical** to the
origin's (proving the speedup isn't from skipped work), plus peak RSS.

## Layout

| file | purpose |
|---|---|
| `harness.py` | benchmark one `(checkout, jser)`; imports that checkout's `PyReconstruct` via `PYTHONPATH`; emits JSON |
| `orchestrate.py` | run the full matrix (codepoints × series × reps) → `results.jsonl` |
| `aggregate.py` | `results.jsonl` → `summary.json` + `summary.csv` |
| `build_report.py` | `summary.json` → `report.md` + `report.html` |
| `fork_requirements.txt` | the shared venv's deps (the fork's, incl. orjson) |
| `REPORT.md` | the rendered results |
| `summary.csv` | aggregated medians |

## Reproduce

```bash
# one shared Python 3.11 env with the fork's deps (origin never imports orjson)
conda create -y -n pyrecon-bench python=3.11
conda run -n pyrecon-bench pip install -r fork_requirements.txt

# checkouts of each code point (git worktrees of this repo)
git worktree add --detach wt-fork     perf/large-jser
git worktree add --detach wt-origin   origin/main
git worktree add --detach wt-baseline <fork-main-pre-perf>   # attribution

# run, aggregate, report
conda run -n pyrecon-bench python orchestrate.py
python aggregate.py
python build_report.py
```

## Notes

- One shared venv is used deliberately: numpy/scipy/shapely/PySide6 are pinned to
  the **same** versions in both fork and origin, so the comparison isolates the
  *code* difference. Origin's code never imports orjson, so it runs as-shipped.
- Headless: `QT_QPA_PLATFORM=offscreen`.
- The wins are algorithmic/single-threaded — they help every machine, and most on
  the large autoseg series.
