# Phase 0 profile artifacts

| file | what it is |
|---|---|
| `session_dense_autoseg.flamegraph.svg` | py-spy flamegraph, dense view (`WVHJM_407` `--fit`, 483 traces in view) at `5ac6c2b`. Open in a browser. |
| `session_dense_autoseg.speedscope.json.gz` | py-spy speedscope for the same regime, 99 Hz, 31,135 samples. `gunzip` first, then load at speedscope.app or feed to `../rank_hotspots.py`. |
| `session_shapes2.flamegraph.svg` | py-spy flamegraph, sparse/gesture-heavy view (`shapes2.jser`, 41 traces) at `8e9e185`. |
| `session_shapes2.speedscope.json` | py-spy speedscope for the same, 99 Hz, 2564 samples. |
| `verify_isanchorpoint_vectorizable.py` | Evidence that `Grid.isAnchorPoint` is exactly a 3x3 convolution: bit-identical over randomized trials, 22.8x faster via `cv2.filter2D`. **Held up: implemented in #97, 13.7x measured end-to-end on a lasso sweep.** |
| `verify_qpoint_batchable.py` | ~~Evidence that the per-point `QPoint` construction in `_drawTrace` is removable by batching into `cv2.polylines`: 22-26x.~~ **RETRACTED 2026-07-28 — this script draws every trace in ONE polylines call in a single colour, which is not what `_drawTrace` does. With the real per-trace colour/width/opacity the OpenCV path measures 1814 ms against QPainter's 155 ms (~12x SLOWER) and the swap was rejected; see `../REPORT.md` §7. The hotspot was removed by `starmap` QPoint batching instead (1.59x, pixel-identical). Kept as the record of a projection that did not survive.** |

Both `verify_*.py` scripts are self-contained and runnable
(`uv run python benchmarks/artifacts/verify_*.py`). They are *evidence for the
Phase 2 decision gate*, not proposed patches — see `../REPORT.md` §7. They are
also **micro-benchmarks**: each isolates one operation, so its speedup bounds a
best case for that operation and is not a prediction for the function it stands
in for. `../REPORT.md` §7a records which projections survived implementation.

The cProfile tables in `../REPORT.md` §6 are regenerated with
`profile_interactive.py --mode cprofile`; the exact commands are in `../README.md`.
