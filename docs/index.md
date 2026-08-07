# PyReconstruct

PyReconstruct is an open-source desktop application for tracing, annotating, and
3D-reconstructing serial-section and volume electron-microscopy (EM) data. It is
the modern, actively maintained successor to *Reconstruct*.

This site documents an independently developed and maintained distribution of
PyReconstruct. It tracks the upstream
[SynapseWeb/PyReconstruct](https://github.com/SynapseWeb/PyReconstruct) project
and builds on it with 3-4x faster opens on large series, one-click installers,
an in-app updater with Stable and Beta channels, and ongoing quality-of-life
fixes and features.

## Who it's for

Neuroscientists and EM researchers who trace neural structures across stacks of
serial sections - segmenting objects, aligning sections, measuring morphology,
and building 3D reconstructions of cells, organelles, and synapses from
volume-EM datasets. It reads and writes the `.jser` series format and handles
large autosegmented series with hundreds of thousands of traces.

## Install

Download a one-click build for the current stable release, **v1.21.1** - no
Python required.

| Platform | Download |
| -------- | -------- |
| Windows (x86_64) | [PyReconstruct-1.21.1-Windows-x86_64-Setup.exe](https://github.com/dustenhubbard/PyReconstruct/releases/download/v1.21.1/PyReconstruct-1.21.1-Windows-x86_64-Setup.exe) |
| macOS (Apple Silicon) | [PyReconstruct-1.21.1-macOS-arm64.dmg](https://github.com/dustenhubbard/PyReconstruct/releases/download/v1.21.1/PyReconstruct-1.21.1-macOS-arm64.dmg) |
| macOS (Intel) | [PyReconstruct-1.21.1-macOS-x86_64.dmg](https://github.com/dustenhubbard/PyReconstruct/releases/download/v1.21.1/PyReconstruct-1.21.1-macOS-x86_64.dmg) |
| Linux (x86_64) | [PyReconstruct-1.21.1-Linux-installer.tar.gz](https://github.com/dustenhubbard/PyReconstruct/releases/download/v1.21.1/PyReconstruct-1.21.1-Linux-installer.tar.gz) |

All builds, checksums, and past versions are on the
**[Releases page](https://github.com/dustenhubbard/PyReconstruct/releases/latest)**.
Developers can install from source with `pip` or `uv`.

Full instructions, including the macOS Gatekeeper step and the in-app updater,
are in the [User Guide](USER_GUIDE.md#1-installing-pyreconstruct).

## Where to go next

- **[User Guide](USER_GUIDE.md)** - install, open a series, the tracing tools,
  data lists, alignment, 3D reconstruction, and backups.
- **[Performance](performance.md)** - benchmarks for the fork's speed work.
- **[Developing with uv](DEV_UV.md)** - the uv-based development workflow.
- **[Contributing](https://github.com/dustenhubbard/PyReconstruct/blob/main/CONTRIBUTING.md)**
  - dev setup, branch/commit conventions, tests, and the PR process.
- **[Source code](https://github.com/dustenhubbard/PyReconstruct)** and
  **[issues](https://github.com/dustenhubbard/PyReconstruct/issues)** on GitHub.

## Citation

PyReconstruct was developed in the Kristen Harris Lab at **The University of
Texas at Austin** and introduced in *PNAS* (2025),
[doi:10.1073/pnas.2505822122](https://doi.org/10.1073/pnas.2505822122). See the
[README](https://github.com/dustenhubbard/PyReconstruct/blob/main/README.md)
for full provenance, performance notes, and citation details.
