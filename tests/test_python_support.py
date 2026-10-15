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
import shutil
import tomllib
from pathlib import Path

import pytest
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


def test_python_3_11_through_3_13_are_supported():
    spec = _requires_python()
    for version in ("3.11.0", "3.11.15", "3.12.0", "3.12.14", "3.13.0", "3.13.16"):
        assert spec.contains(version), f"requires-python {spec} refuses {version}"
    assert not spec.contains("3.10.14"), f"requires-python {spec} admits 3.10"
    assert not spec.contains("3.14.0"), f"requires-python {spec} admits 3.14"


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


def test_every_supported_python_gets_exactly_one_pin_of_each_dependency():
    """numpy, opencv, scikit-image and trimesh each carry one pin per Python
    line. A marker gap would install nothing for that package on some line,
    and an overlap would hand the installer two versions at once."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    names = {Requirement(spec).name.lower() for spec in data["project"]["dependencies"]}
    for minor in sorted(_admitted_minors()):
        env = {"python_version": minor, "python_full_version": f"{minor}.0"}
        for name in sorted(names):
            applying = [
                r for r in _pins(name) if r.marker is None or r.marker.evaluate(env)
            ]
            assert len(applying) == 1, f"{len(applying)} {name} pins apply on {minor}"


# The lines numpy 2 brought to 3.13. 3.11 and 3.12 stay on numpy 1, and the
# installers build on 3.11, so none of these may reach either of them.
NUMPY_2_PINS = {
    "numpy": ("1.26.4", "2.2.6"),
    "opencv-python-headless": ("4.8.1.78", "4.10.0.84"),
    "scikit-image": ("0.23.2", "0.25.2"),
    "trimesh": ("3.18.1", "4.4.9"),
}


@pytest.mark.parametrize("name", sorted(NUMPY_2_PINS))
def test_numpy_2_pins_apply_only_from_3_13(name):
    numpy_1_line, numpy_2_line = NUMPY_2_PINS[name]

    def pinned_on(minor):
        env = {"python_version": minor, "python_full_version": f"{minor}.0"}
        (req,) = [
            r for r in _pins(name) if r.marker is None or r.marker.evaluate(env)
        ]
        (version,) = [s.version for s in req.specifier if s.operator == "=="]
        return version

    assert pinned_on("3.12") == numpy_1_line
    assert pinned_on("3.13") == numpy_2_line
    if name != "numpy":
        assert pinned_on("3.11") == numpy_1_line


LINUX_INSTALLER = REPO_ROOT / "packaging" / "linux" / "install.sh"


def _installer_check():
    """The py_is_supported function from install.sh, as bash source."""
    text = LINUX_INSTALLER.read_text(encoding="utf-8")
    fn = re.search(r"^py_is_supported\(\) \{\n.*?^\}\n", text, re.M | re.S)
    assert fn, "install.sh has no py_is_supported function"
    return fn.group(0)


def test_linux_installer_accepts_every_supported_python():
    """install.sh builds its venv with a system Python it finds itself, and
    refuses any line outside its own list. That list has to be the one
    requires-python admits, or the installer turns away a Python the project
    supports (or picks one pip will refuse to install into)."""
    check = _installer_check()
    line = re.search(r"sys\.version_info\[:2\] in \(([^)]*\)(?:, \([^)]*\))*)\)", check)
    assert line, "py_is_supported no longer checks sys.version_info[:2] against a tuple"
    accepted = {f"{a}.{b}" for a, b in re.findall(r"\((\d+), (\d+)\)", line.group(1))}
    assert accepted == _admitted_minors()


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_linux_installer_accepts_the_running_python(tmp_path):
    """Run the installer's check against this interpreter, which CI runs on
    every supported line, and against a program that is not Python."""
    import subprocess
    import sys

    not_python = tmp_path / "not-python"
    not_python.write_text("#!/bin/sh\nexit 0\n")
    not_python.chmod(0o755)
    script = _installer_check() + 'py_is_supported "$1" && echo yes || echo no\n'

    def run(interpreter):
        out = subprocess.run(
            ["bash", "-c", script, "check", str(interpreter)],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()

    assert run(sys.executable) == "yes"
    assert run(not_python) == "no"


def test_no_datetime_utcnow_in_pyreconstruct():
    """datetime.utcnow() warns from 3.12 and is slated for removal. The UTC
    timestamps use datetime.now(timezone.utc) with the zone dropped, which is
    the same naive value."""
    package = REPO_ROOT / "PyReconstruct"
    callers = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in package.rglob("*.py")
        if "utcnow(" in path.read_text(encoding="utf-8")
    )
    assert callers == []


def test_get_now_in_utc_does_not_warn():
    import warnings
    from datetime import datetime, timezone

    from PyReconstruct.modules.backend.settings_store import (
        DictSettingsStore,
        default_settings_store,
        set_default_settings_store,
    )
    from PyReconstruct.modules.constants import get_now

    original = default_settings_store()
    store = DictSettingsStore()
    try:
        set_default_settings_store(store)
        store.set_value(None, "utc", True)
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            now = get_now()
        assert now.tzinfo is None
        expected = datetime.now(timezone.utc).replace(tzinfo=None)
        assert abs((expected - now).total_seconds()) < 5
    finally:
        set_default_settings_store(original)
