# Changelog

All notable changes to PyReconstruct are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[semantic versioning](https://semver.org/). Builds come on two channels:
**Release** (tagged `vX.Y.Z`) and **Pre-release (experimental)** (rolling, latest `main`).

## [Unreleased]

### Changed
- **Large-series performance.** Vectorized the per-trace geometry build and the
  affine point mapping that dominate opening and refreshing a series. On a
  287-section / 3,809-object / 61,121-trace autoseg series, first open and
  `data.refresh` are ~3× faster than the pre-optimization baseline (and the
  geometry is verified numerically identical to the previous code).

### Added
- A `pytest` test suite (geometry/transform equivalence) and a headless
  performance harness.

## [1.20.0] - 2026-06-27

### Added
- **One-click installers** built in CI: Windows (`.exe`, Inno Setup) and macOS
  Apple Silicon (`.dmg`).
- **In-app updater** with **Release** / **Pre-release (experimental)** channels,
  pulling builds from GitHub Releases (checksum-verified).

### Changed
- Modernized the 3D stack to **vtk 9.4.2** + **vedo 2025.5.4**, enabling native
  Apple Silicon support.
- Migrated packaging from `setup.py` to **`pyproject.toml` + setuptools-scm**.

### Fixed
- Corrected user-facing typos, blank/placeholder dialog titles, and repository
  URL casing.

[Unreleased]: https://github.com/dustenhubbard/PyReconstruct/compare/v1.20.0...HEAD
[1.20.0]: https://github.com/dustenhubbard/PyReconstruct/releases/tag/v1.20.0
