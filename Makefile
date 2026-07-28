# Developer task surface for PyReconstruct.
#
# This is the dev loop. `dev/Makefile` is a separate thing -- conda environment
# lifecycle -- and the two are deliberately not merged.
#
# Everything routes through `uv run`, never through `.venv/bin/python`: that
# path is POSIX-only (`.venv/Scripts/python.exe` on Windows) and this project
# has contributors and an installer matrix on all three platforms. `uv run`
# resolves the interpreter itself.
#
# The flag combination below matters and is the reason this file exists.
# `docs/DEV_UV.md` warns that each `uv run` re-syncs `.venv` to match the flags
# it was given, so a run with different flags than the last one churns the
# environment -- including a git-built dependency in the `dev` group. Writing
# the flags down once makes them impossible to mistype:
#
#   --frozen              use uv.lock exactly; fail rather than silently relock
#   --no-default-groups   skip the `dev` group (git-built funlib; not needed to test)
#   --extra test          add pytest, which is not a runtime dependency
#
# These are the same flags `.github/workflows/test.yml` uses, so `make check`
# and the CI gate cannot drift apart.

UV := uv run --frozen --no-default-groups --extra test

# Ruff is pinned exactly. A floating ruff is a self-inflicted CI break, because
# new rules ship in minor releases. This is the same version the lint job in
# .github/workflows/test.yml installs, so local and CI cannot disagree.
RUFF := uvx ruff@0.15.20

# Hoisted here as well as in tests/conftest.py so that non-pytest targets and
# any future scripted target inherit it too.
export QT_QPA_PLATFORM = offscreen

.PHONY: help env test fast lint type check

# Bare `make` should explain itself rather than start a four-thousand-test run.
help:
	@echo 'PyReconstruct dev tasks:'
	@echo '  make env     install the test environment from uv.lock'
	@echo '  make test    run the full suite'
	@echo '  make fast    run the suite minus tests marked `slow`'
	@echo '  make lint    ruff, critical-error set (the CI gate)'
	@echo '  make type    mypy over the Qt-free core (reporting only, not a gate)'
	@echo '  make check   lint + fast -- run this before pushing'

env:
	uv sync --frozen --no-default-groups --extra test

test:
	$(UV) python -m pytest -ra

fast:
	$(UV) python -m pytest -ra -m "not slow"

lint:
	$(RUFF) check .

# Reporting only, and prefixed with `-` so a nonzero exit does not stop `make`.
# Scoped to the Qt-free core (`modules/datatypes`), which is where the geometry
# and serialisation invariants live and is the layer that already has a
# Qt-independence test. A whole-tree strict run reports thousands of errors,
# most of them missing annotations, and is not a gate anyone can act on.
# Deliberately absent from `check` for that reason.
type:
	-$(UV) --with mypy python -m mypy --ignore-missing-imports PyReconstruct/modules/datatypes

check: lint fast
