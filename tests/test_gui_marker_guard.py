"""Guards on the anti-silent-skip machinery itself.

The failure this exists to prevent has already happened. `pytest-qt` is declared
in the `test` optional-dependency extra, not in the runtime dependencies, so a
.venv synced without `--extra test` has pytest but no `qapp` fixture. The
gui-marked modules used to protect themselves with a module-scope
`pytest.importorskip("pytestqt")`, which dropped every widget test and let the
suite exit 0. Measured on this tree: 4228 tests collected with pytest-qt
present, 4157 without, reported as "2 skipped" because the skips are per-module
rather than per-test. A reviewer reads that as tested.

`tests/conftest.py` now errors instead. These tests assert the properties that
error depends on, none of which the conftest hook can check about itself:

1. no test module reintroduces `importorskip("pytestqt")`, which would put the
   silent skip back for that module;
2. at least one module carries the `gui` mark, so the guard has something to
   fire on. A rename or a dropped `pytestmark` would otherwise leave the guard
   permanently inert with nothing to say so;
3. `gui` is a registered marker and `--strict-markers` is on, so a typo like
   `pytest.mark.gui2` is an error rather than a test that quietly runs unmarked
   and is never selected by `-m gui`;
4. pytest-qt stays in the `test` extra and out of the runtime dependencies, and
   the Makefile and CI keep passing `--extra test`.

Deliberately NOT marked `gui`: these must run in every environment, including a
`-m "not gui"` invocation and one with no pytest-qt at all. They read source
text and resolved config, and construct no widgets.

Source scanning goes through `ast`, not `re`, on purpose: the modules involved
now carry comments that name `importorskip("pytestqt")` in prose, and a textual
scan matches those. Only real calls and real attribute accesses are AST nodes.

No hardcoded collected count here. A "the suite must collect at least 4228
tests" assertion would rot on the next merge and get bumped without thought,
which is how a tripwire becomes noise.
"""

import ast
import re
import tomllib
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent


def _parsed_test_modules():
    """(name, tree) for every test module in tests/, this one included."""
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        yield path.name, ast.parse(path.read_text(encoding="utf-8"), path.name)


def _importorskip_targets(tree):
    """The string argument of every `*.importorskip("...")` call in a module."""
    return [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "importorskip"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]


def _has_gui_mark(tree):
    """True if the module contains a real `pytest.mark.gui` attribute access.

    Covers both spellings the suite uses: a module-scope
    `pytestmark = pytest.mark.gui` and a `@pytest.mark.gui` decorator.
    """
    return any(
        isinstance(node, ast.Attribute)
        and node.attr == "gui"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        for node in ast.walk(tree)
    )


def test_no_module_importorskips_pytest_qt():
    """A gui module must not opt itself out of the run when pytest-qt is absent.

    That is what the conftest guard is for, and the guard can only fire on items
    that were actually collected. A module-level skip happens during collection,
    so the guard never sees the module at all.

    Scoped to pytest-qt. `importorskip` is legitimate elsewhere in this suite
    (numpy, skimage, cv2, PySide6.QtGui) and is not touched here.
    """
    offenders = [
        name
        for name, tree in _parsed_test_modules()
        if "pytestqt" in _importorskip_targets(tree)
    ]
    assert not offenders, (
        "these modules skip themselves when pytest-qt is missing, which is the "
        f"silent-skip bug this guard exists to prevent: {', '.join(offenders)}. "
        "Mark the module `pytest.mark.gui` and let tests/conftest.py's "
        "pytest_collection_modifyitems raise instead."
    )


def test_some_module_carries_the_gui_mark():
    """The guard needs a gui-marked module to have anything to guard.

    If the widget tests are renamed, consolidated, or lose their `pytestmark`,
    the conftest guard goes quiet: it fires on collected gui items and there
    would be none. Nothing else in the suite would report that.
    """
    marked = [name for name, tree in _parsed_test_modules() if _has_gui_mark(tree)]
    assert marked, (
        "no test module carries `pytest.mark.gui`. Either the real-widget tests "
        "were removed or they lost their mark. With no marked module the "
        "missing-pytest-qt guard in tests/conftest.py can never fire."
    )


def test_gui_marker_is_registered(pytestconfig):
    """`-m gui` must not rest on an unregistered marker.

    Registration is what lets `--strict-markers` reject a typo. Registration
    happens in `tests/conftest.py`'s `pytest_configure`, not in `pytest.ini`.
    """
    markers = pytestconfig.getini("markers")
    assert any(entry.split(":", 1)[0].strip() == "gui" for entry in markers), (
        "`gui` is not a registered marker. Register it in tests/conftest.py's "
        f"pytest_configure. Registered markers: {markers}"
    )


def test_strict_markers_is_enabled(pytestconfig):
    """Without this, `pytest.mark.gui2` runs forever as an unmarked test.

    Asserted through the resolved config rather than by reading pytest.ini, so
    moving the setting into pyproject.toml or overriding it on the command line
    still satisfies it.
    """
    assert pytestconfig.getoption("strict_markers"), (
        "--strict-markers is not in effect. Add it to addopts in pytest.ini. An "
        "unregistered marker is otherwise a silent no-op: a module marked "
        "`pytest.mark.gui2` would collect, run as an ordinary test, and never be "
        "selected by `-m gui`."
    )


def test_pytest_qt_is_in_the_test_extra_and_not_the_runtime_deps():
    """pytest-qt belongs in the `test` extra, and only there.

    Both halves matter. It has to be declared somewhere, or the documented
    invocation would not install it either and the guard would abort every run.
    And it must not become a runtime dependency: promoting it to `dependencies`
    is the tempting one-line fix for the silent skip, but
    `.github/workflows/build-installers.yml` builds the frozen app from
    `pip install -e .`, so that would bundle pytest into every installer and
    declare it a requirement of the published wheel.
    """
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    project = pyproject["project"]
    extra = project["optional-dependencies"]["test"]
    assert any(spec.startswith("pytest-qt") for spec in extra), (
        "pytest-qt is not in [project.optional-dependencies].test. The gui tests "
        f"cannot run without it. Found: {extra}"
    )

    leaked = [
        spec for spec in project["dependencies"] if re.match(r"pytest\b|pytest-", spec)
    ]
    assert not leaked, (
        f"a pytest dependency leaked into [project].dependencies: {leaked}. That "
        "ships the test framework to end users and into the frozen installers "
        "built by .github/workflows/build-installers.yml."
    )


def test_makefile_and_ci_both_pass_the_test_extra():
    """The two invocations that must never be able to lose pytest-qt.

    `uv run` re-syncs .venv to the flags it was given, so a bare `uv run pytest`
    is what strips pytest-qt out of a worktree. The Makefile and the CI workflow
    are the two places the flags are written down; if either drops
    `--extra test`, every run through it hits the conftest guard.
    """
    for relative in ("Makefile", ".github/workflows/test.yml"):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "--extra test" in text, (
            f"{relative} no longer passes `--extra test`, so it cannot install "
            "pytest-qt and the gui tests cannot run through it"
        )
