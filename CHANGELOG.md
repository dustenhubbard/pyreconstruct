# Changelog

All notable changes to this distribution of PyReconstruct are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [semantic versioning](https://semver.org/).

Builds come on two channels: **Release** (stable, tagged `vX.Y.Z`) and
**Pre-release (experimental)** (rolling, latest `main`). Entries under
[Unreleased] have landed on `main` and ship on the Pre-release channel ahead of
the next tagged release.

## [Unreleased]

### Added
- A `pytest` test suite covering geometry/transform equivalence and the updater's
  selection, version-comparison, and checksum logic, plus a headless performance
  harness. (#2, #3)
- Reproducible fork-vs-upstream benchmarks under `benchmarks/`, with raw results,
  aggregated medians, and an equivalence report. (#1)

### Changed
- **Large-series performance.** Rewrote the per-trace geometry build and the
  affine point mapping that dominate opening and refreshing a series, with no
  change to the `.jser` format or data model. Open and refresh are **3–4× faster**
  across real autoseg series from 6 MB to 1.4 GB (up to ~4.2×); the geometry is
  verified equivalent to the previous implementation — section/object/trace counts
  match exactly and summed area/length/radius are identical on seven of the eight
  benchmark series (the largest differs by ~1e-11 relative on summed radius, from
  floating-point summation order). The work
  vectorizes `traceGeometry` into a single NumPy pass, defers the Feret-diameter
  convex hull until it is read, maps trace points straight to NumPy arrays, and
  uses [orjson](https://github.com/ijl/orjson) on the JSON load/save paths (with a
  stdlib fallback). Series-wide object operations are scoped to the sections that
  actually contain the targeted objects. (#1)
- **In-app updater polish.** The update check now runs off the GUI thread; a new
  update dialog shows the version, channel, download size, and release notes, then
  downloads and checksum-verifies the installer inline with a progress bar. Added
  an opt-in background check on startup (frozen builds, gated to once per 24 h),
  off by default. (#3)
- Renamed the updater channels to **Release** and **Pre-release (experimental)**.

### Fixed
- Declared the `orjson` dependency in `pyproject.toml`. It powers the jser
  load/save speedups but was previously only in `requirements.txt`, so a
  pyproject-based install silently dropped it and lost both the speedup and the
  orjson code path. (#2)
- Corrected user-facing typos, blank/placeholder dialog titles, and repository
  URL casing.
- Updated the macOS dmg first-launch (Gatekeeper) instructions to match current
  macOS wording.

## [1.20.0] - 2026-06-26

### Added
- **One-click installers** built in CI: Windows (`.exe`, Inno Setup) and macOS
  Apple Silicon (`.dmg`), released from this repository via GitHub Actions
  (unsigned for now).
- **In-app updater** that downloads and installs releases from GitHub Releases,
  with a channel toggle and bundled CA certificates for TLS verification in the
  frozen app.

### Changed
- Modernized the 3D stack to **vtk 9.4.2** + **vedo 2025.5.4**, enabling native
  Apple Silicon support.
- Migrated packaging from `setup.py` to **`pyproject.toml` + setuptools-scm**
  (tag-derived versioning); `requirements.txt` is retained as an export.

### Fixed
- Frozen-build hardening: windowed-stdio, Qt, SSL, and software-OpenGL runtime
  hooks; a Mesa software-OpenGL fallback on Windows for RDP/VM sessions; and a
  frozen-Windows multiprocessing fix so the Zarr conversion runs.

[Unreleased]: https://github.com/dustenhubbard/PyReconstruct/compare/v1.20.0...HEAD
[1.20.0]: https://github.com/dustenhubbard/PyReconstruct/releases/tag/v1.20.0
