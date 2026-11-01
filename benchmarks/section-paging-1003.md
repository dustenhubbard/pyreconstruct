# Section paging measurements, November 1, 2026

Neither candidate produced a clear paging improvement in these measurements.
Both production changes were discarded. This branch retains the benchmark and evidence for
[issue #1003](https://github.com/dustenhubbard/pyreconstruct/issues/1003).

The measured code is `d3c47373c791a88d5cede2141a4eef3385511bed`, including lazy
trace points. There are no production changes in this branch.

## Workload and timing

The synthetic series has 125 sections, each with 4,400 closed, unfilled traces
of 80 points. Section JSON totals 1,620,229,515 bytes. Each section has its own
2048 by 2048 grayscale TIFF with deterministic, identical image content.
The viewport is 1600 by 1000 and displays all 4,400 traces.

`bench_section_paging.py` times `FieldWidget.changeSection` and a synchronous
widget paint. This includes actual JSON decoding, trace objects, the columnar
store, a fresh undo baseline, image handling, and rendering. Every change
visits a previously unvisited section. No A/B flicker or cached undo baseline
can replace that work. It asserts section identity, trace count, image presence,
undo initialization, and identical painted pixel hashes after each step.

Startup, series-data construction, verification hashes, and fixture preparation
are outside the timed region. The filesystem cache is warm after startup.
The production image read-ahead remains enabled. Main-window callbacks are
stubs and no lists are open. Unsaved edits, large TIFFs, interactive display
compositing, and the original series are not measured. These results do not
reproduce or replace the original series' reported 1.3-second timing.

The harness redirects settings to temporary INI files before importing
PyReconstruct. It applies `collector.settleAfterOpen`, as the real main window
does. An early harness version omitted this step and attributed full-heap
collection time to unrelated small functions. Those measurements were rejected.

Hardware is a Ryzen 9 5900X with 24 logical CPUs on Linux x86_64, Python 3.12.15,
PySide6 6.9.3, and NumPy 1.26.4. Load averages before the final comparison were
0.76, 1.25, and 1.86. The benchmark used about one core; no parallel benchmark
was running.

## Two rejected changes

Each experiment alternated five runs per side, ten fresh section changes per
run. The table reports the median of the five run medians and their range.
The raw samples and hashes are in
[the measurement artifact](artifacts/paging-1003-2026-11-01.json).

| Experiment | Before, ms | Candidate, ms | Verdict |
| --- | --- | --- | --- |
| Batch numeric columns while rebuilding the store | 198.8, range 198.0 to 217.3 | 198.1, range 195.3 to 209.1 | No clear total gain |
| Pause cyclic collection only during `loadSection` | 200.8, range 195.4 to 204.6 | 197.9, range 196.4 to 205.2 | No clear total gain |

Baseline always runs first in each pair, and each run advances through the same
growing session. Section order, retained undo baselines, and collector history
are not counterbalanced. These measurements cannot resolve small differences.

Batching reduced the store build's median from about 20.8 to 17.5 ms, but that
saves at most a few milliseconds of a roughly 200 ms step. The larger profile
cost for the store included overhead from profiling its many Python calls.
The discarded batch implementation staged numeric values during construction
and assigned whole numeric columns afterwards. Its code is not retained, so the
artifact records that experiment but the harness cannot rerun it.

The collector guard reused `_collectorPaused` from series opening. It reduced
some collection time in a separate profile, but did not clearly reduce total
paging time. The production guard and its temporary test were discarded. Normal
collection resumed after the load, inside the same page change. The harness
retains this probe under `--compare`.

All 100 timed changes in each experiment completed. Every frame had the same
hash, `222dad55819f1a4aab69b6e1667e24b054186f22b477f09f67c58213520e3db3`,
and all 4,400 traces were in view. There were zero failed timed changes.

## Where the time goes

The rejected premise was that per-row Python bookkeeping or repeated collection
inside loading dominated enough of a complete step to make these small changes
materially faster. The benchmark now records each phase to check that premise.

Across the 50 baseline steps of the collector comparison, typical phase medians
were approximately:

| Phase | Time per step, ms |
| --- | --- |
| Section decoding and object/store construction | 108 |
| View generation | 69 |
| Undo baseline | 9 |
| Widget paint | 3 |
| Section-layer initialization, with image read-ahead | Less than 1 |

These are nested measurements, not additive independent medians. View generation
includes both image and trace rendering. A separate profiled census confirms
that trace rendering dominates view generation: roughly 89 ms under profiling,
compared with 3 ms for image rendering. The profile tables are in
[the profile artifact](artifacts/paging-1003-2026-11-01-profile.txt).
Profiler timings are diagnostic and are excluded from the comparison table.

No single small helper accounts for most of the step. These experiments do not
exhaust improvements to synchronous loading or rendering. Avoiding synchronous
construction or changing its representation could remove more work from the
page change, but neither has been measured here. `Section.__init__` documents eager construction of
the checked parallel store as a correctness decision. It also documents that the
object model owns the data. Making either representation lazy would reopen that
decision.

Preloading one neighboring section is another direction. It would add memory
use and require invalidation after saves, edits, alignment changes, section
reordering, and series transitions. Construction also touches the series-wide
trace-ID issuer. The existing image read-ahead handles images only; it cannot
make full section construction safe on another thread. No speedup or memory
budget for section read-ahead has been established by these measurements.

The maintainer decision is whether added memory use for one retained neighboring
section is acceptable. I recommend investigating a bounded prototype if it is,
because construction is the larger measured cost. This is an investigation
direction, not a proved solution. The alternative is to keep loading synchronous
and focus on rendering. A prototype would still need to establish memory use,
responsiveness, GIL behavior, and the invalidation rules before a production change.

## Reproduce

Run from the checkout root with the frozen test environment installed. Choose
an unused scratch path with about 2.2 GB free. The benchmark refuses to overwrite
an existing fixture during preparation.

1. Create the synthetic series.

   ```sh
   PYTHONPATH=. uv run --frozen --no-default-groups --extra test python benchmarks/bench_section_paging.py --fixture /path/to/scratch --prepare
   ```

2. Alternate the current loader with the rejected collector guard, five runs
   per side. The guard exists only in the measurement process.

   ```sh
   PYTHONPATH=. uv run --frozen --no-default-groups --extra test python benchmarks/bench_section_paging.py --fixture /path/to/scratch --compare
   ```

3. Profile a separate comparison.

   ```sh
   PYTHONPATH=. uv run --frozen --no-default-groups --extra test python benchmarks/bench_section_paging.py --fixture /path/to/scratch --compare --runs 1 --profile
   ```

Remove the synthetic fixture after the run. The settings directory is temporary
and cleans itself up. A six-section smoke fixture with eight four-point traces
also passed on Python 3.11.17. Ruff's configured checks passed for the harness.
