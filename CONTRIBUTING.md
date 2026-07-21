# Contributing to PyReconstruct

Thanks for your interest in improving PyReconstruct! This repository is an
independently developed and maintained distribution of PyReconstruct that tracks
the upstream [SynapseWeb/PyReconstruct](https://github.com/SynapseWeb/PyReconstruct)
project (developed in the Kristen Harris Lab at **The University of Texas at
Austin**). Contributions of bug reports, fixes, features, docs, and screenshots are
all welcome.

- **Found a bug or have an idea?** [Open an issue](#filing-issues).
- **Want to write code or docs?** See [development setup](#development-setup) and
  [branch and commit conventions](#branch-and-commit-conventions).

By contributing, you agree that your contributions are licensed under the project's
[GPL-3.0-or-later](LICENSE.md) license.

---

## Filing issues

Open issues on this distribution's
**[GitHub Issues](https://github.com/dustenhubbard/PyReconstruct/issues)**, which the
in-app **Help ▸ Report issues (GitHub)** submenu also links to. Three issue
templates are available from the "New issue" chooser:

- **Bug report** — please include the **version or commit** you're running. Find it
  at the top of the **Help** menu in the app (clicking it copies the commit hash to
  your clipboard), along with your OS, Python version, steps to reproduce, and any
  console error output.
- **Feature request** — describe the problem you're trying to solve, not only a
  proposed solution.
- **Documentation request** — tell us what's missing or unclear.

For a **security vulnerability**, please don't open a public issue — report it
privately as described in [`SECURITY.md`](SECURITY.md).

---

## Development setup

PyReconstruct targets **Python 3.11** (`requires-python = ">=3.11,<3.12"`) and
**PySide6 6.5.2**.

### uv (canonical)

The canonical developer setup uses [uv](https://docs.astral.sh/uv/). It reads the
Python 3.11 pin from `pyproject.toml`, provisions the interpreter, and installs
the exact dependency set recorded in the committed `uv.lock`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # once; or: brew install uv
git clone https://github.com/dustenhubbard/PyReconstruct
cd PyReconstruct
uv sync                            # creates .venv from uv.lock (exact pinned deps)
uv run PyReconstruct               # launch (installs PyReconstruct editable)
```

`uv sync` installs PyReconstruct in editable mode into `.venv/` (git-ignored), so
`import PyReconstruct` works with no `PYTHONPATH` fiddling. The update loop is
`git pull` then `uv run PyReconstruct` — `uv run` re-syncs `.venv` to the lockfile
automatically. To bump a dependency, edit its pin in `pyproject.toml` and run
`uv lock --upgrade` (or `uv lock --upgrade-package <name>`), then commit the
refreshed `uv.lock`. See [docs/DEV_UV.md](docs/DEV_UV.md) for the group/extra
matrix (runtime vs. `test` extra vs. `dev` group) and the full uv reference.

### Conda environment (alternative)

A conda environment named **`pyrecon_dev`** remains supported as a parallel
workflow, created by the `Makefile` in `dev/`:

```bash
cd dev
make env              # create the `pyrecon_dev` conda env and link the source tree
conda activate pyrecon_dev
```

`make env` creates the environment from `dev/environment_dev.yaml` (conda-forge,
Python 3.11, plus the runtime dependencies from `requirements.txt`) and runs
`dev/link_shell.sh`, which puts the repository root on the environment's import
path (so the source checkout is importable without installing) and registers the
helper scripts in `dev/scripts/` on `PATH`.

Other `Makefile` targets (run from `dev/`):

| Command | What it does |
|---|---|
| `make help` | Show the available commands (the default target) |
| `make env` | Create the `pyrecon_dev` environment and link the source tree |
| `make update` | Update the environment from `environment_dev.yaml` (`--prune`) |
| `make clean` | Remove the `pyrecon_dev` environment (alias: `make remove`) |

You can change the environment name by editing `ENV_NAME` in `dev/Makefile`.

### Running the app from a checkout

With uv, `uv run PyReconstruct` (above) launches the app. In an activated conda
environment, run it from the repository root instead:

```bash
python PyReconstruct/run.py
```

Either way, an editable install (`uv sync`, or a plain `pip install -e .`)
provides the `PyReconstruct` console command (the entry point declared in
`pyproject.toml`, `PyReconstruct.cli:main`).

---

## Running the tests

The test suite lives in `tests/` and runs headless. It needs a Qt platform plugin
because a couple of tests construct a `QApplication`, so set the **offscreen**
platform. With uv (installs exactly what CI installs — runtime + the `test` extra):

```bash
QT_QPA_PLATFORM=offscreen uv run --no-default-groups --extra test python -m pytest
```

Or, in an activated conda environment, from the repository root:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD" python -m pytest
```

The suite is fast and requires no display or network. `pytest.ini` restricts
collection to `tests/` and runs quietly (`-q`). (Under `uv sync` and in an
environment created by `make env`, the package is importable, so `PYTHONPATH` is
redundant there — but it's needed for a bare checkout.)

What the tests cover (a representative selection — the suite has grown well beyond
these):

| Test file | Focus |
|---|---|
| `test_geometry.py` | Pins the combined NumPy `traceGeometry()` pass to the scalar reference geometry functions (length/area/centroid/radius) over fixed and random polygons. |
| `test_transform.py` | The vectorized affine point map (`Transform.map` / `mapPointsArray`) against per-point `QTransform.map`, including inverted round-trips. |
| `test_perf_equivalence.py` | Broad equivalence/property suite for the performance rewrite — geometry, transforms, the `orjson` JSON wrapper (with documented `xfail` divergences), lazy Feret caching, and section lookups. |
| `test_updater.py` | The in-app updater's pure functions (release/asset selection, version comparison, checksum parsing) with the network monkeypatched. |
| `test_affine_align_guard.py` | Regression test: "estimate affine transform" must warn and do nothing with fewer than three matched traces. |
| `test_edit_object_attributes.py` | Regression test: editing object attributes with `sections=None` means "all sections the object is on." |
| `test_missing_return_guards.py` | Regression tests for missing `return`-after-guard bugs in several `main_window` actions. |
| `test_set_series_mag.py` | Regression test: a non-positive series magnification is rejected. |

Several of these are regression tests for specific fixes — when you fix a bug or
change behavior, please add a headless test alongside it where practical.

---

## Project layout

PyReconstruct is a PySide6 desktop app. The Python package is `PyReconstruct/`:

```
PyReconstruct/
├── run.py                  # Qt bootstrap + restart loop + frozen-build dispatch
├── cli.py                  # `PyReconstruct` console entry point
└── modules/
    ├── backend/            # non-GUI logic, grouped by concern
    │   ├── view/           #   field rendering layers (image, section, trace, zarr)
    │   ├── volume/         #   3D mesh generation and export
    │   ├── table/          #   data-list/table manager
    │   ├── func/           #   transforms, imports, undo/redo state, conversions
    │   ├── imports/        #   ImageJ ROI and other imports
    │   ├── exports/        #   SVG / ROI export
    │   ├── autoseg/        #   auto-segmentation conversions
    │   ├── remote/         #   remote/example-data access
    │   ├── threading/      #   QThreadPool worker helpers
    │   └── updater/        #   in-app updater (release/asset/checksum logic)
    ├── gui/                # Qt / PySide6 UI
    │   ├── main/           #   main window, menubar, field-widget mixins, context menus
    │   ├── dialog/         #   dialogs (options, alignment, trace, grid, flag, updater, …)
    │   ├── palette/        #   floating tool/trace palettes and overlays
    │   ├── popup/          #   3D scene window, about, help
    │   ├── table/          #   the list/table widgets (object, trace, section, ztrace, flag, history)
    │   └── utils/          #   UI helpers (notifications, progress bars, colors)
    ├── datatypes/          # core domain model (Series, Section, Trace, Transform,
    │                       #   Ztrace, Flag, HostTree, defaults, log, …)
    ├── datatypes_legacy/   # readers/writers for the legacy Reconstruct XML format
    ├── calc/               # pure numeric/geometry (quantification, polygon, Feret, …)
    ├── constants/          # constants and small helpers (paths, repo info, websites, JSON)
    └── assets/             # bundled data (icons/cursors, welcome series, test fixtures)
```

Top-level directories outside the package:

- `tests/` — the pytest suite (see above).
- `dev/` — developer tooling (`Makefile`, `environment_dev.yaml`, `link_shell.sh`,
  helper `scripts/`).
- `packaging/` — PyInstaller spec, runtime hooks, and the macOS, Windows, and Linux
  installer build files.
- `launch/` — clone-and-run scripts for end users.
- `benchmarks/` — the performance harness, results, and report.
- `manual/` — the older upstream user manual (kept for reference; superseded by
  [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)).
- `docs/` — this distribution's user-facing documentation.
- `.github/` — issue templates and CI workflows.

Where it's practical, keep computation and data-model logic in `backend/`,
`datatypes/`, and `calc/` (GUI-free and testable), and keep `gui/` focused on
presentation.

---

## Branch and commit conventions

This repository follows a lightweight, conventional workflow. (You can see it in the
existing branch names and commit history.)

### Branches

Use short `type/slug` branch names, where `type` matches the change:

```
feat/…   fix/…   docs/…   perf/…   refactor/…   test/…   build/…   ci/…   chore/…
```

For example: `feat/ui-theme`, `fix/knife-small-piece`, `docs/guides`,
`perf/object-list-virtualization`, `chore/uv-migration`.

### Commits

Write commit messages as [Conventional Commits](https://www.conventionalcommits.org/):

```
type(optional-scope): short summary in the imperative mood

Optional body explaining what and why.
```

Examples from this repo's history: `perf(jser): 3-4x faster open & refresh on large
autoseg series`, `feat(updater): in-app updater polish`, `docs: rewrite README and
add CHANGELOG`.

Keep messages **measured and factual** — describe the change and its rationale;
avoid hyperbole. Don't add automated co-author or attribution trailers (for example,
trailers crediting AI assistants) to commits or pull requests.

### Pull requests

- Open pull requests **against this repository** (`dustenhubbard/PyReconstruct`,
  `main` branch) — not the upstream `SynapseWeb/PyReconstruct` repository.
- Keep a PR focused on one logical change.
- PRs are **squash-merged**, so the **PR title becomes the squashed commit subject**
  — write the PR title as a Conventional Commit header. The merged commit keeps the
  `(#N)` PR reference.
- Make sure the test suite passes (`QT_QPA_PLATFORM=offscreen python -m pytest`) and
  add tests for fixes and behavioral changes where practical.

---

## Credits and license

PyReconstruct was created in the Kristen Harris Lab at **The University of Texas at
Austin** (Michael A. Chirillo, Julian N. Falco, Michael D. Musslewhite, Larry F.
Lindsey, and Kristen M. Harris) and introduced in *PNAS* (2025); the upstream
project lives at [SynapseWeb/PyReconstruct](https://github.com/SynapseWeb/PyReconstruct).
This distribution is independently developed and maintained by **Dusten Hubbard**
(Kristen Harris Lab, **The University of Texas at Austin**). See the
[README](README.md) for full provenance and citation details.

PyReconstruct is licensed under [GPL-3.0-or-later](LICENSE.md).
