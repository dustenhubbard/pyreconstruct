# Developer tasks; dev/Makefile manages the optional conda environment.
# Match .github/workflows/test.yml: --locked rejects stale uv.lock metadata;
# --frozen would silently use it. Skip git-built dev extras and include pytest.
UV := uv run --locked --no-default-groups --extra test

# Keep these tool versions in sync with .github/workflows/test.yml.
RUFF := uvx ruff@0.15.20
MYPY := mypy==2.3.0

# Example: make test PYTEST_ARGS='tests/test_transform.py -x --durations=10'
PYTEST_ARGS ?=
export QT_QPA_PLATFORM = offscreen

.PHONY: help env test fast gui lint type check

help:
	@echo 'PyReconstruct dev tasks:'
	@echo '  make env     install the test environment from uv.lock'
	@echo '  make test    run the full suite'
	@echo '  make fast    run the suite minus tests marked `slow`'
	@echo '  make gui     run the tests marked `gui` (real Qt widgets, offscreen)'
	@echo '  make lint    ruff syntax and import checks'
	@echo '  make type    mypy over the Qt-free core (reporting only, not a gate)'
	@echo '  make check   lint + fast -- run this before pushing'
	@echo '  Add PYTEST_ARGS="tests/test_transform.py -x" to select tests or pass flags.'

env:
	uv sync --locked --no-default-groups --extra test

test:
	$(UV) python -m pytest -ra $(PYTEST_ARGS)

fast:
	$(UV) python -m pytest -ra -m "not slow" $(PYTEST_ARGS)

gui:
	$(UV) python -m pytest -ra -m gui $(PYTEST_ARGS)

lint:
	$(RUFF) check .

# Reporting only. mypy.ini owns the scope; CLI paths would override its files.
type:
	-$(UV) --with $(MYPY) python -m mypy

check: lint fast
