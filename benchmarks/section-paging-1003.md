# Bounded section read-ahead

With a 350 ms pause between steps, the median of five run medians fell from
**502.3 ms to 267.2 ms**, a 46.8% reduction on a heavily loaded shared host.
All 100 timed changes completed with identical painted pixels. The candidate
used a prepared neighbor on 45 of 50 steps.

| Measurement | Before | Read-ahead |
| --- | --- | --- |
| Median step, range of run medians | 502.3 ms, 424.9 to 623.7 | 267.2 ms, 250.2 to 335.6 |
| Sampled paging peak RSS, median and range | 2,612.5 MiB, 2,564.0 to 2,620.8 | 2,651.0 MiB, 2,555.6 to 2,657.3 |
| Process peak RSS, median and range | 2,637.5 MiB, 2,581.9 to 2,642.8 | 2,675.5 MiB, 2,580.3 to 2,681.4 |

The RSS comparison is inconclusive under swapping: its variation exceeds the
difference between medians. [Host snapshots](artifacts/paging-read-ahead-1003-host.txt)
record the memory pressure during the run. A separate five-run allocation probe isolates the
neighbor's cost. It holds **33.5 MiB** of traced allocations after preparation,
with a **185.1 MiB temporary allocation peak** during reading and parsing.
After dropping the result and collecting garbage, 76 KiB remains tracked,
unchanged across the five probes. Traced allocations are not resident memory.

Preparation also delays GUI callbacks. A 5 ms idle heartbeat had a median
per-run maximum gap of 7.2 ms before and 108.2 ms after. The candidate's worst
gap was 292.6 ms. Median per-run 95th-percentile gaps were 5.3 and 12.8 ms.
Python work and parsing still hold the GIL; read-ahead moves that interference
into the pause between steps.

Foreground section loading accounts for the gain: its pooled median fell from
284.8 to 69.6 ms. Trace rendering was 133.7 versus 138.0 ms, the undo baseline
about 22 ms, and widget paint about 7 ms. These phase medians are nested and
are not additive. The reduction is within the time previously spent loading.

The one-minute load average at the start of individual runs ranged from
7.4 to 31.3 on 24 logical CPUs. These are measurements under contention,
not quiet-machine estimates or a replication of the earlier 200 ms result.

[Raw paging samples](artifacts/paging-read-ahead-1003.jsonl) and
[allocation samples](artifacts/paging-read-ahead-1003-allocations.json) retain
the measurements. Every timed frame hashes to
`222dad55819f1a4aab69b6e1667e24b054186f22b477f09f67c58213520e3db3`.

Rapid paging showed **no clear difference**. With no pause, the median of five
run medians was 430.0 ms before, range 295.0 to 544.6, and 403.3 ms after,
range 290.0 to 418.4. The variation exceeds the difference. All 100 rapid
changes completed with the same pixel hash, and none used a prepared result.
[Raw rapid samples](artifacts/paging-read-ahead-1003-rapid.jsonl) retain both
sides.

A [separate profile](artifacts/paging-read-ahead-1003-profile.txt) confirms the
remaining foreground costs: checked-store construction and trace rendering.
The profile includes the idle loop and slows Python calls, so its times are
excluded from the comparison.

This continues the [earlier paging measurements](https://github.com/dustenhubbard/pyreconstruct/blob/00e8db69184b946e07287b1a0f422bb0ae8f6adf/benchmarks/section-paging-1003.md)
for [issue 1003](https://github.com/dustenhubbard/pyreconstruct/issues/1003).

## What changes

After an adjacent section change, a 75 ms single-shot timer requests the next
neighbor in the same direction. Adjacency follows the sorted section numbers,
including gaps. A jump cancels the request and starts no new one. A reversal
replaces the request. Reloading, changing series, and closing discard it.

One worker reads, decodes, normalizes, and builds the neighbor's private traces
and coordinate arrays. It never receives a Series object, registers trace IDs,
changes undo state, or writes a file. The normal loader assigns IDs, builds the
eager checked columnar store, and applies current group visibility. Transforms
still follow the series' current alignment.

The slot holds one prepared neighbor or one read in progress. Replacing a
request cancels the old one, releases its payload, and lets the same worker
handle the latest request. There is no queue of prepared sections. A foreground
load never waits for preparation. Missing, failed, and late results use the
normal synchronous path.

A result is accepted only for its series, section number, path, and unchanged
file identity, size, modification time, and change time. Section saves replace
files atomically, so a saved neighbor invalidates the prepared version. Save As
and renumbering also change the path or file identity. A/B flicker retains the
existing live section objects.

## Workload and measurement

The fixture and geometry come from the earlier harness. There are 125 sections,
each with 4,400 closed, unfilled traces of 80 points. Section JSON totals
1,620,229,515 bytes. Each section has a separate deterministic 2048 by 2048
grayscale TIFF. A 1600 by 1000 viewport displays every trace.

The baseline is commit `d3c47373c791a88d5cede2141a4eef3385511bed`. The candidate
is the implementation in this PR. Each side runs in a fresh process against
the same fixture, warms up on section 1, and times sections 2 through 11.
Five pairs alternate baseline then candidate. The filesystem cache is warm.

A sample includes `FieldWidget.changeSection` and synchronous widget painting.
Startup, fixture generation, the pause between steps, and verification are
outside the timed region. Every step checks section identity, trace count,
image presence, undo initialization, visible traces, and the painted pixel hash.
The main-window callbacks are stubs and no lists are open. Saves and undo are
covered by widget tests, not by the timing workload.

The normal comparison leaves 350 ms between steps. A second comparison has no
pause. A real Qt event loop runs during the pause. An earlier probe used
`QTest.qWait`, which delayed the Python worker: five isolated reads took about
219 to 275 ms there, compared with 81 to 111 ms in a Qt event loop. Those paging
samples were discarded before the reported comparison.

Memory includes current resident size sampled every 5 ms during paging and
the kernel's process-wide peak resident size. The latter includes startup.
The sampler can miss a transient allocation while another thread holds the
GIL. These are process measurements, not a fixed memory budget per section.

Hardware is a Ryzen 9 5900X with 24 logical CPUs and 32 GB RAM, on Linux.
Both sides use Python 3.11.17, PySide6 6.9.3, NumPy 1.24.1, and orjson 3.11.8.
Other jobs ran concurrently. The raw records include load averages before and
after each run. Fixed pair order and changing host load limit small comparisons.

## Limits

- Read-ahead moves work into the pause between steps. It does not eliminate that
  work or make a first step or arbitrary jump faster.
- Decoding and Python trace construction still contend for the GIL. The idle
  heartbeat measurements above record the resulting event-loop delays.
- Local-store stubs retain their normal synchronous hydration path. Read-ahead
  applies only after a section has a materialized JSON file.
- A section's memory cost depends on its trace count and geometry. The bound is
  one speculative neighbor, in addition to the existing current and B sections
  and image read-ahead.
- These synthetic timings do not reproduce the original series' reported
  1.3-second step or measure desktop compositing, unsaved edits, or open lists.

## Validation

The final focused run passed **440 tests**, with 2 platform skips. It covers
section read-ahead, section deletion, pointer state across series changes,
atomic navigation, image read-ahead, lazy points, ID derivation, undo/redo,
columnar parity, and store opening. All 18 new read-ahead tests passed.

The full run collected 14,549 tests: 14,365 passed, 169 skipped, 5 expected
failures, and 10 failures. It ran before the final fixes and is not a clean
full-suite result. Two failures exposed a deleted-current-section navigation
bug and a headless test fixture that needed a timer stub; both are fixed and
pass in the final focused run. Seven failures reproduce on the unchanged
baseline: three backup-path cases, three bash startup-file cases, and one
filesystem-detection case. The remaining save-parity failure differs only in
a log timestamp crossing from 18:31 to 18:32; all saved data otherwise matches,
and that test passes in the final focused run.

Two isolated revert checks each collected one test and failed as intended.
Restoring the original navigation method prevents the neighbor from being
prepared. Retaining a worker's local payload while it returns violates the
single-neighbor lifetime assertion. The existing deletion test also failed
before its fix and passes afterward.

Ruff 0.15.20 and whitespace checks pass. Mypy reports 260 errors versus 264
on the baseline; neither run is clean. Tests and the benchmark redirect
settings to temporary INI files before importing the application.

The focused command was:

```sh
uv run --frozen --no-default-groups --extra test python -m pytest tests/test_section_read_ahead.py tests/test_object_ids_field.py tests/test_pointer_move_without_press.py tests/test_change_section_atomic.py tests/test_image_read_ahead.py tests/test_trace_lazy_points.py tests/test_trace_id_load_derivation.py tests/test_section_undo_redo_characterization.py tests/test_columnar_store_parity.py tests/test_store_open.py
```

The full run used the same environment with `python -m pytest -n 2` and a
disk-backed temporary directory.


## Reproduce

Use a baseline worktree at `d3c47373` and a worktree containing this change.
Run these commands from the changed checkout with its frozen test environment.
The fixture needs about 2.2 GB on disk. Avoid a RAM-backed temporary directory
when measuring memory.

1. Create the fixture. The command refuses to overwrite an existing directory.

   ```sh
   PYTHONPATH=. uv run --frozen --no-default-groups --extra test python benchmarks/bench_section_paging.py --fixture /path/to/paging-fixture --prepare
   ```

2. Run five alternating pairs with a 350 ms pause.

   ```sh
   PYTHONPATH=. uv run --frozen --no-default-groups --extra test python benchmarks/bench_section_paging.py --fixture /path/to/paging-fixture --compare /path/to/before /path/to/after --runs 5 --output /path/to/paging.jsonl
   ```

3. Repeat with no pause.

   ```sh
   PYTHONPATH=. uv run --frozen --no-default-groups --extra test python benchmarks/bench_section_paging.py --fixture /path/to/paging-fixture --compare /path/to/before /path/to/after --runs 5 --idle-ms 0 --output /path/to/rapid.jsonl
   ```

4. Measure allocations for holding and dropping one prepared neighbor.

   ```sh
   PYTHONPATH=. uv run --frozen --no-default-groups --extra test python benchmarks/bench_section_paging.py --fixture /path/to/paging-fixture --allocation-probe --runs 5
   ```

5. Profile separately from the comparison.

   ```sh
   PYTHONPATH=. uv run --frozen --no-default-groups --extra test python benchmarks/bench_section_paging.py --fixture /path/to/paging-fixture --steps 3 --profile
   ```

Remove the synthetic fixture after the run. Settings use temporary INI files
created before importing PyReconstruct.
