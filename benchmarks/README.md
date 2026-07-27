# Benchmarks — fork perf vs. upstream

Local performance study of this fork's `main` against the upstream commit it was
compared against originally (`SynapseWeb/PyReconstruct@7b2c92f`).

> **This directory cannot gate anything.** Per `dev/REFACTOR_PLAN.md`, equivalence
> and performance gating live in the pytest suite against in-repo fixtures
> (`tests/test_perf_equivalence.py`, `tests/test_geometry.py`). These scripts need
> multi-hundred-MB private series that are not in the repo, so they are an
> optional local study, run by hand. See `REPORT.md` for results and for the
> correction history of the figures this directory once published.

## What it measures

Per `(checkout, series, condition)`, in a fresh interpreter per rep:

- **open** — `Series.openJser(path)` (JSON load; the fork uses orjson)
- **refresh** — `SeriesData(series).refresh()` (builds every trace's geometry)
- **save** — `Series.saveJser(...)` (JSON dump; skipped above `--skip-save-above-mb`)
- **peak RSS**, plus resident size sampled after open and after refresh, so a
  memory spike can be attributed to the parse path rather than to geometry

### cold vs. warm — read this before interpreting any number

`Series.openJser` short-circuits. If a hidden unpack directory `.<name>/`
containing `<name>.ser` sits beside the `.jser`, the series is built from those
per-section files and **the `.jser` is never parsed** (`series.py:239-258`).
Otherwise the whole JSON is parsed and the hidden dir is written
(`series.py:332` onward).

These are two different workloads with different peak memory:

| condition | what runs | what a user is doing |
|---|---|---|
| **cold** | full JSON parse + unpack to the hidden dir | opening a `.jser` for the first time |
| **warm** | hidden-dir fast path, no JSON parse | reopening a series already unpacked locally |

They must never be averaged. The original version of this harness did exactly
that, and its published memory figures were withdrawn as a result — see
`REPORT.md` § *Correction*.

The OS page cache is a separate axis. `drop_caches` needs root, so instead the
orchestrator *reads the `.jser` before every rep* to pin the disk cache warm for
every checkout and condition. "cold" therefore means application-cold.

## Layout

| file | purpose |
|---|---|
| `harness.py` | measure one `(checkout, jser)`; imports that checkout's `PyReconstruct` via `sys.path`; observes and reports whether openJser took the cold or warm path; emits JSON |
| `orchestrate.py` | the matrix: checkouts × series × {cold,warm} × reps → `results.jsonl`, with a loud pre-flight manifest |
| `aggregate.py` | `results.jsonl` → `summary.json` + `summary.csv`, grouped by condition and refusing to pool cold with warm |
| `build_report.py` | `summary.json` → `report.md` + `report.html` |
| `profile_interactive.py` | scripted offscreen interactive session (pan/zoom/hover/lasso/knife/merge) for cProfile or py-spy |
| `rank_hotspots.py` | py-spy speedscope JSON → ranked self-time table |
| `make_scaled_series.py` | build a larger `.jser` from a real one by replicating sections, for the >700 MB size class |
| `fork_requirements.txt` | the historical shared-venv deps (superseded by `uv.lock`) |
| `REPORT.md` | the written results, including the correction note |
| `artifacts/` | profile outputs (flamegraph SVG, speedscope JSON, gate evidence scripts) |

Data files, and which run they belong to:

| file | run |
|---|---|
| `results_phase0.jsonl`, `summary_phase0.csv` | the Phase 0 cold/warm re-run — **these are the current numbers** |
| `results.jsonl`, `summary.csv` | the June 2026 run whose memory figures were **withdrawn**. Retained only as the evidence behind `REPORT.md` § *Correction*. `aggregate.py` deliberately refuses to process `results.jsonl`, because its reps silently mix cold and warm. |

## Reproduce

```bash
# 1. environment — uv.lock is canonical; the named conda envs are gone
uv sync --frozen

# 2. checkouts of each code point (detached worktrees of this repo)
git worktree add --detach .worktrees/wt-fork   origin/main
git worktree add --detach .worktrees/wt-origin 7b2c92f

# 3. describe the data this machine actually has
cat > /path/to/series.json <<'JSON'
[{"label": "mySeries", "path": "/abs/path/to/series.jser", "size_mb": 745}]
JSON

# 4. run the matrix (a missing file is a hard error unless --allow-missing)
uv run python benchmarks/orchestrate.py \
    --series-json /path/to/series.json \
    --checkouts fork=.worktrees/wt-fork,origin=.worktrees/wt-origin \
    --reps 3 --out /path/to/results.jsonl

# 5. aggregate (refuses to pool cold with warm, and rejects legacy result files)
uv run python benchmarks/aggregate.py --results /path/to/results.jsonl
```

### Interactive profile

```bash
# ranked self time, per phase (cProfile: precise, biased toward many-small-calls)
uv run python benchmarks/profile_interactive.py --jser SERIES.jser --mode cprofile

# sampled profile of the composite session (unbiased; the Phase 2 gate evidence)
uv tool install py-spy
py-spy record --rate 99 --format speedscope -o out.speedscope.json -- \
    .venv/bin/python3 benchmarks/profile_interactive.py \
    --jser SERIES.jser --mode run --phase session --iters 8
uv run python benchmarks/rank_hotspots.py out.speedscope.json
```

## Notes

- One shared venv is deliberate: numpy/scipy/shapely/PySide6 are pinned to the
  **same** versions for both checkouts, so the comparison isolates the *code*
  difference. Upstream never imports orjson, so it runs as-shipped.
- Headless: `QT_QPA_PLATFORM=offscreen`.
- `profile_interactive.py` keeps the real `QSettingsStore` rather than swapping in
  `DictSettingsStore`, because the render loops were tuned around its
  ~60 µs-per-`getOption` cost (`trace_layer.py:534-539`); replacing it would
  profile a program that does not ship. It redirects `XDG_CONFIG_HOME` to scratch
  so the real user settings are never touched.
- The eight original lab series lived on one machine and most are now gone;
  `make_scaled_series.py` exists so the large-size classes stay reproducible.
  This is the plan's open question #7 answered locally, not upstream-hosted data.
