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
  set. Because the package is installed, `import PyReconstruct` also works with
  no `PYTHONPATH` fiddling.

> `pyproject.toml` is the source of truth for the uv workflow. uv reads
> `[project.dependencies]` (runtime), `[project.optional-dependencies].test`
> (the `test` extra, pytest), and `[dependency-groups].dev` (dev-only tooling).
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
  libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libcairo2
```

A machine that already runs the conda env (`pyrecon_dev`) has these already.

### Native Cairo, on every platform

`libcairo2` above is not a Qt library and not Linux-only. PNG section export
(`File > Export > PNG`) goes through `cairosvg`, which is a declared Python
dependency but does **not** bundle Cairo: it imports `cairocffi`, which
`dlopen`s the native library at import time. So `uv sync` succeeding tells you
nothing about whether PNG export works -- the wheel installs on a machine with
no Cairo at all, and the failure arrives only when a user exports, as
`OSError: no library called "cairo-2" was found`.

| Platform | What you need |
| --- | --- |
| Debian / Ubuntu | `sudo apt-get install libcairo2` (already in the line above) |
| macOS | `brew install cairo`, **plus** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` -- `ctypes.util.find_library` does not search Homebrew's prefix, so an installed Cairo is still invisible without it |
| Windows | a Cairo DLL (`libcairo-2.dll`) on `PATH`; the GTK runtime installer is the usual source |

SVG export (`File > Export > SVG`) needs only `svgwrite` and has no native
requirement, so it works anywhere the Python dependencies are installed.

`tests/test_export_svg_png.py` asserts SVG export unconditionally and skips only
the PNG raster, naming this requirement in the skip message. CI installs
`libcairo2`, so the PNG assertion runs on the gate.

## 2. Create the environment with `uv sync`

`make env` creates the lean test environment from the committed lockfile and
rejects a lockfile that is out of date. It runs
`uv sync --locked --no-default-groups --extra test`.

`uv sync` creates `.venv/` in the repo (git-ignored) and installs PyReconstruct
in editable mode. What else it installs depends on which groups/extras you select:

| Want | Command |
| --- | --- |
| Runtime only (run the app) | `uv sync --no-default-groups` |
| Runtime + test deps (run the suite) | `uv sync --no-default-groups --extra test` |
| Full dev env (conda-parity tooling) | `uv sync` |
| Everything (dev tooling + test deps) | `uv sync --extra test` |

`uv sync` with no flags installs the **`dev` dependency group**
(`psycopg2-binary`, `funlib.show.neuroglancer`) because uv treats a group named
`dev` as a default. That mirrors the dev tooling in the conda
`environment_dev.yaml`, and additionally installs PyReconstruct itself in
editable mode, which the conda env does not do.

> **`funlib.show.neuroglancer` is a dev-only tool installed from git, and the
> only fragile dependency here.** It is *not* needed to run the app or the test
> suite. If its git build fails on your platform, or you just want a lean
> environment, use `--no-default-groups` to skip the whole `dev` group.

## 3. Run the app

```bash
uv run --locked --no-default-groups --extra test PyReconstruct/run.py
```

This uses the same environment selection as `make env` and the test commands.
`uv run` checks the environment first, then launches the GUI. Because the project
declares a console script, this also works:

```bash
uv run --locked --no-default-groups --extra test PyReconstruct
```

Keep these group/extra flags consistent across commands: omitting
`--no-default-groups` requests the git-built dev tooling, and `uv sync` removes
packages that are outside the selected environment.

### Driving the GUI from a script (`PYRECON_UNATTENDED`)

A launch that nobody is sitting in front of — a click-test harness, a screenshot
run, a computer-use agent — should set this:

```bash
PYRECON_UNATTENDED=1 uv run --locked --no-default-groups --extra test PyReconstruct/run.py path/to/series.jser
```

Opening a series is allowed to ask questions: where the images went if the
recorded `src_dir` no longer resolves, what the series code should be, whether
to scale an unscaled zarr. Each is a modal, and a modal raised into a window no
script will ever click is a permanent stall, not a slow dialog. The offscreen
platform is already treated as "no user" for this reason, but a scripted run is
on a *real* platform, so nothing Qt can observe tells it apart from a real
user's session. This variable is how the caller says so; each prompt then takes
the same deliberate no-user answer it already takes offscreen
(`gui/utils/utils.py`, `user_is_present`).

Exactly `1` enables it. Leave it unset for an ordinary launch — it suppresses
dialogs a real user wants to see.

## 4. Run the tests

Run these from the checkout you are editing:

```bash
make check                              # lint + tests except those marked slow
make test                               # full suite, as in CI
make gui                                # real Qt widget tests
make test PYTEST_ARGS='tests/test_transform.py -x'
make gui PYTEST_ARGS='tests/test_section_list_real_widget.py'
make test PYTEST_ARGS='--lf --durations=10'
```

The Makefile uses the same locked dependency selection as CI and sets Qt to
`offscreen`; no X server or `xvfb` is needed. The `gui` marker selects tests
that construct real Qt widgets. Full application tests can use the existing
`main_window` fixture in `tests/conftest.py`, which opens a writable copy of
the checked-in series and isolates application preferences. That fixture has
no image data, so image rendering and native display behavior still need
separate verification.

Without `make` (including Windows), the equivalent full suite command is:

```bash
uv run --locked --no-default-groups --extra test python -m pytest -ra
```

`-ra` surfaces xfail/xpass/skip reasons. Each test that runs for more than
60 seconds prints all thread stacks to help diagnose a modal dialog or deadlock.
This is a diagnostic, not a time limit: teardown still runs if the test returns.
For a deliberately long test, override it with
`PYTEST_ARGS='-o faulthandler_timeout=300'`; use `-vv -s` to see which test is
running and its uncaptured output.

> pytest lives in the `test` **extra**, not the default `dev` group, so a bare
> `uv sync` does not install it. Always pass `--extra test` to run the suite.
> pytest is constrained to the `9.x` line the suite is verified against (8.x is
> untested; 10 drops a config shim deprecated in 9.1).

### Worktrees

Run `make env` inside each worktree so it gets its own `.venv`. To confirm
which checkout an interpreter imports:

```bash
uv run --locked --no-default-groups --extra test python -c 'import PyReconstruct; print(PyReconstruct.__file__)'
```

The printed path must be in the worktree being edited. For a shared conda
interpreter, `dev/dev-run.sh --check` performs this check with the worktree
prepended to `PYTHONPATH`; `dev/dev-run.sh` launches that checkout.

## 5. Preview scripts (`uv run --script`)

Standalone preview scripts under `dev/` carry [PEP 723](https://peps.python.org/pep-0723/)
inline metadata, so uv builds a throwaway environment from the script's own
header, with no project sync and no conda env:

```bash
uv run --script dev/update_dialog_preview.py
```

(That particular script renders the in-app update dialog and needs a **real
display**. Run it on macOS/Windows or a Linux box with a desktop, not offscreen.)

## 6. The lockfile

`uv.lock` **is committed**: PyReconstruct ships as an application, so a pinned,
reproducible dependency set is what we want. Use `--locked` in verification
commands: it errors out if the lock and
`pyproject.toml` have diverged and leaves the lockfile unchanged. `--frozen`
also leaves it unchanged, but skips the freshness check and can therefore
test an environment that omits a newly declared dependency. See
[uv's lockfile semantics](https://docs.astral.sh/uv/concepts/projects/sync/#automatic-lock-and-sync).

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
| Run the app | `python PyReconstruct/run.py` | `uv run --locked --no-default-groups --extra test PyReconstruct/run.py` |
| Run tests | `QT_QPA_PLATFORM=offscreen python -m pytest -ra` | `make test` (or the equivalent uv command in section 4) |
| Preview script | `python dev/update_dialog_preview.py` | `uv run --script dev/update_dialog_preview.py` |

The conda workflow remains fully supported. One practical difference: the conda
env installs dependencies but not PyReconstruct itself, so the conda commands
above rely on running from the repo root (or a `PYTHONPATH`/`link_shell.sh`
setup); the uv `.venv` installs the package, so it needs neither.
