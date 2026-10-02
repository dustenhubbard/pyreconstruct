"""The Python versions PyReconstruct supports, and CI's coverage of them.

requires-python in pyproject.toml is the promise. .python-version names the
one `test` runs on (3.11, the version the installers build on), and the
`test-python` matrix in .github/workflows/test.yml lists the others. The
three are edited by hand in three files, so they are checked against each
other here: a version admitted by requires-python and tested nowhere fails.

The workflow is scanned with a regex rather than parsed: PyYAML is not a test
dependency, and the matrix is one line.
"""

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _requires_python():
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return SpecifierSet(data["project"]["requires-python"])


def _admitted_minors():
    spec = _requires_python()
    return {f"3.{minor}" for minor in range(0, 40) if spec.contains(f"3.{minor}.0")}


def _default_python():
    return (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()


def _matrix_pythons():
    text = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = re.search(r"^  test-python:\n(.*?)(?=^  \S)", text, re.M | re.S)
    assert job, "test.yml has no test-python job"
    line = re.search(r"^\s+python:\s*\[([^\]]*)\]", job.group(1), re.M)
    assert line, "the test-python job has no one-line `python: [...]` matrix"
    return {v.strip().strip("'\"") for v in line.group(1).split(",") if v.strip()}


def test_python_3_11_and_3_12_are_supported():
    spec = _requires_python()
    for version in ("3.11.0", "3.11.15", "3.12.0", "3.12.14"):
        assert spec.contains(version), f"requires-python {spec} refuses {version}"
    assert not spec.contains("3.10.14"), f"requires-python {spec} admits 3.10"


def test_default_python_is_the_oldest_supported():
    """`test`, `type` and local `uv sync` all run on .python-version. It is
    the oldest supported line because that is what the installers freeze."""
    assert _default_python() == min(_admitted_minors(), key=lambda v: int(v.split(".")[1]))


def test_ci_runs_the_suite_on_every_supported_python():
    tested = {_default_python()} | _matrix_pythons()
    admitted = _admitted_minors()
    assert admitted - tested == set(), (
        f"requires-python admits {sorted(admitted - tested)} but CI never runs "
        "the suite there; add it to the test-python matrix in test.yml"
    )
    assert tested - admitted == set(), (
        f"CI tests {sorted(tested - admitted)}, which requires-python refuses"
    )


def _pins(name):
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return [
        Requirement(spec)
        for spec in data["project"]["dependencies"]
        if Requirement(spec).name.lower() == name
    ]


def test_installer_build_reads_the_3_11_pins():
    """The macOS installer legs fetch numpy and scipy wheels by version before
    installing the project, and read the version with the regex below: the
    first `name==` in pyproject.toml. The installers build on 3.11, so that
    first pin has to be the one 3.11 resolves, or the frozen app would get a
    numpy the 3.11 lock never tested."""
    text = PYPROJECT.read_text(encoding="utf-8")
    env = {"python_version": "3.11", "python_full_version": "3.11.9"}
    for name in ("numpy", "scipy"):
        first = re.search(rf"{name}==([0-9.]+)", text).group(1)
        on_311 = [
            r for r in _pins(name) if r.marker is None or r.marker.evaluate(env)
        ]
        assert len(on_311) == 1, f"{len(on_311)} {name} pins apply on 3.11"
        (pinned,) = [s.version for s in on_311[0].specifier if s.operator == "=="]
        assert first == pinned, (
            f"the installer build would fetch {name} {first}, but 3.11 "
            f"resolves {pinned}; keep the 3.11 pin first in pyproject.toml"
        )


def test_every_supported_python_gets_exactly_one_numpy():
    for minor in sorted(_admitted_minors()):
        env = {"python_version": minor, "python_full_version": f"{minor}.0"}
        applying = [
            r for r in _pins("numpy") if r.marker is None or r.marker.evaluate(env)
        ]
        assert len(applying) == 1, f"{len(applying)} numpy pins apply on {minor}"
