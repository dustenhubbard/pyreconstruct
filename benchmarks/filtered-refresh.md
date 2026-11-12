# Filtered Object List refresh

The filtered refresh is faster on this generated series. Five matching
objects take a median 73.89 ms, compared with 1,470.26 ms for the full refresh.
This measures the synchronous `Refresh` action, including the check for pending edits,
filter evaluation, loading sections, recomputing measurements, and updating
the open Object List. It excludes series creation, initial opening, and
deferred painting.

The reproducible benchmark is [bench_filtered_refresh.py](bench_filtered_refresh.py).
Run it from the repository root:

```sh
uv run --frozen --no-default-groups --extra test python -m pytest benchmarks/bench_filtered_refresh.py -s
```

The input has 30,000 objects across 100 sections. Each object has one
48-point contour. The regex matches five objects on one section. Both paths
use the same open series, dependencies, and filtered widget. The full path
calls the manager's existing full `Refresh`. The filtered path triggers the
Object List's `Refresh` action. Each path warms once before five measured runs,
with alternating order.

| Run | Full refresh, ms | Filtered refresh, ms |
| --- | ---: | ---: |
| 1 | 1391.31 | 72.63 |
| 2 | 1511.45 | 81.54 |
| 3 | 1470.26 | 73.89 |
| 4 | 1330.32 | 73.23 |
| 5 | 1471.23 | 78.82 |
| Median | 1470.26 | 73.89 |

Measured on Linux with Python 3.11.17 and 24 logical CPUs on November 2, 2026.
The one-minute load average before the run was 7.40, with other Python jobs
active. Neither path ran under a profiler during the measurements.
The ranges do not overlap.

Separate profiles show the full refresh spending 2.397 of 2.512 seconds in
`SeriesData.refresh`, including 1.605 seconds loading 100 sections.
The filtered refresh spends 0.105 of 0.132 seconds evaluating filters over
the 30,000 names. Its data reload takes 0.022 seconds and loads one section.
It still parses every contour in that section but measures only the matches.
These profile times identify hot spots and are excluded from the timing results.

Before each run, the benchmark zeros the cached areas of the five matching
objects. Afterward, it verifies their areas against the regular polygon's
analytic area, the five displayed names, and the unchanged 30,000-object count.
All runs succeeded. The result applies to this synthetic, sparse match case;
a filter matching most objects will save less work.
