# Developing PyReconstruct with uv

[uv](https://docs.astral.sh/uv/) is a fast, lockfile-based Python project manager.
This document describes the **uv-based development workflow, which is the
canonical developer setup.** The conda workflow (`dev/environment_dev.yaml`)
remains supported as a parallel option, but `git clone` + `uv sync` + `uv run` is
the flow this project develops and releases against. uv has two advantages for
contributors:

- It provisions the correct interpreter itself (the project pins
  `requires-python = ">=3.11,<3.12"`), so you don't need a separate conda env
  just to get Python 3.11.
- `uv sync` installs PyReconstruct into a project-local `.venv` and resolves
  against the committed `uv.lock`, so everyone gets the same pinned dependency
  set — and, because the package is installed, `import PyReconstruct` works with
  no `PYTHONPATH` fiddling.

> `pyproject.toml` is the source of truth for the uv workflow. uv reads
> `[project.dependencies]` (runtime), `[project.optional-dependencies].test`
> (the `test` extra — pytest), and `[dependency-groups].dev` (dev-only tooling).
> The conda env and `requirements.txt` are the older, parallel mechanism.

## 1. Install uv

```bash
# Linux / macOS (standalone installer; installs to ~/.local/bin)
curl -LsSf https://astral.sh/uv/install.sh | sh

# or via pipx / Homebrew / your package manager — see
# https://docs.astral.sh/uv/getting-started/installation/
```

Verify: `uv --version`.

### Linux: headless Qt system libraries

PySide6 6.5 needs a few system libraries even under the offscreen platform.
On a fresh Debian/Ubuntu box (these match the CI `tests` job):

```bash
sudo apt-get install -y --no-install-recommends \
  libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3
```

A machine that already runs the conda env (`pyrecon_dev`) has these already.

## 2. Create the environment — `uv sync`

`uv sync` creates `.venv/` in the repo (git-ignored), installs PyReconstruct in
editable mode, and applies the committed `uv.lock` (re-resolving only if
`pyproject.toml` has drifted from the lock). What *else* it installs depends on
which groups/extras you select:

| Want | Command |
| --- | --- |
| Runtime only (run the app) | `uv sync --no-default-groups` |
| Runtime + test deps (run the suite) | `uv sync --no-default-groups --extra test` |
| Full dev env (conda-parity tooling) | `uv sync` |
| Everything (dev tooling + test deps) | `uv sync --extra test` |

`uv sync` with no flags installs the **`dev` dependency group**
(`psycopg2-binary`, `funlib.show.neuroglancer`) because uv treats a group named
`dev` as a default. That mirrors the dev tooling in the conda
`environment_dev.yaml` — and additionally installs PyReconstruct itself in
editable mode, which the conda env does not do.

> **`funlib.show.neuroglancer` is a dev-only tool installed from git, and the
> only fragile dependency here.** It is *not* needed to run the app or the test
> suite. If its git build fails on your platform — or you just want a lean
> environment — use `--no-default-groups` to skip the whole `dev` group.

## 3. Run the app

```bash
uv run PyReconstruct/run.py
```

`uv run` syncs the environment first (so you can skip a separate `uv sync`), then
launches the GUI. Because the project declares a console script, this also works:

```bash
uv run PyReconstruct          # entry point -> PyReconstruct.cli:main
```

Both pull the `dev` group by default (the funlib git build). To launch without it:

```bash
uv run --no-default-groups PyReconstruct/run.py
```

> **Note — each `uv run` re-syncs `.venv` to match the flags you pass it**, adding
> or removing packages so the environment exactly matches the request. Alternating
> between `uv run PyReconstruct/run.py` (pulls the `dev` group) and the test
> command below (`--no-default-groups`, which drops it) will reinstall/remove the
> `dev` group each time. To avoid the churn, pick one environment shape — e.g.
> `uv sync --no-default-groups --extra test` once — and pass the same flags to
> every `uv run`.

## 4. Run the tests

The suite imports `gui.main` (PySide6), so it runs under the offscreen Qt
platform — no X server or `xvfb` needed. The lean test environment (runtime +
pytest, no dev tooling) installs exactly what CI installs (`pip install -e ".[test]"`):

```bash
QT_QPA_PLATFORM=offscreen uv run --no-default-groups --extra test pytest -ra
```

`-ra` (what CI runs) surfaces xfail/xpass/skip reasons; `pytest.ini` already sets
`addopts = -q`, so a quiet run needs no extra flag. The suite is expected to be
green with a handful of documented `xfail`s (orjson NaN/Inf JSON divergence).

> pytest lives in the `test` **extra**, not the default `dev` group, so a bare
> `uv sync` does not install it. Always pass `--extra test` to run the suite.
> pytest is constrained to the `9.x` line the suite is verified against (8.x is
> untested; 10 drops a config shim deprecated in 9.1).

## 5. Preview scripts (`uv run --script`)

Standalone preview scripts under `dev/` carry [PEP 723](https://peps.python.org/pep-0723/)
inline metadata, so uv builds a throwaway environment from the script's own
header — no project sync, no conda env:

```bash
uv run --script dev/update_dialog_preview.py
```

(That particular script renders the in-app update dialog and needs a **real
display** — run it on macOS/Windows or a Linux box with a desktop, not offscreen.)

## 6. The lockfile

`uv.lock` **is committed** — PyReconstruct ships as an application, so a pinned,
reproducible dependency set is what we want. `uv sync` (and `uv run`) apply it as
is, and `uv sync --frozen` errors out rather than silently re-resolving if the
lock and `pyproject.toml` have diverged — that is what CI and reproducible setups
should use.

Bumping dependencies is a **maintainer** action: edit the pin in `pyproject.toml`
(or not, for a plain refresh), then re-resolve and commit the new lock:

```bash
uv lock --upgrade                  # re-resolve everything to newest allowed, rewrite uv.lock
uv lock --upgrade-package <name>   # bump just one dependency
uv lock                            # re-resolve after editing a pin in pyproject.toml
uv sync                            # apply the new lock to .venv
```

Commit the resulting `uv.lock` alongside the `pyproject.toml` change.

## uv ↔ conda quick reference

| Task | conda (`pyrecon_dev`) | uv |
| --- | --- | --- |
| Create / update env | `conda env create -f dev/environment_dev.yaml` | `uv sync` |
| Run the app | `python PyReconstruct/run.py` | `uv run PyReconstruct/run.py` |
| Run tests | `QT_QPA_PLATFORM=offscreen python -m pytest -ra` | `QT_QPA_PLATFORM=offscreen uv run --no-default-groups --extra test pytest -ra` |
| Preview script | `python dev/update_dialog_preview.py` | `uv run --script dev/update_dialog_preview.py` |

The conda workflow remains fully supported. One practical difference: the conda
env installs dependencies but not PyReconstruct itself, so the conda commands
above rely on running from the repo root (or a `PYTHONPATH`/`link_shell.sh`
setup); the uv `.venv` installs the package, so it needs neither.
