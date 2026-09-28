"""The macOS bundle carries the build's version, not 0.0.0.

The spec never set ``CFBundleShortVersionString`` or ``CFBundleVersion``, so
every shipped bundle reported 0.0.0 to Finder and to anything else that asks a
bundle for its version, the planned in-place updater included. Both keys now
come from the build version: ``PYR_PUBLIC``, which CI's "Compute version" step
exports before the freeze (the setuptools-scm version with no +local part),
then the ``_version.py`` a local ``pip install -e .`` writes, then 0.0.0.

The spec runs only inside PyInstaller, so this reads it as source: the
``info_plist`` keys are checked in the syntax tree, and ``_bundle_version`` is
lifted out and run on its own.
"""
import ast
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "packaging" / "PyReconstruct.spec"
WORKFLOW = REPO / ".github" / "workflows" / "build-installers.yml"


def _tree():
    return ast.parse(SPEC.read_text(encoding="utf-8"))


def _info_plist():
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "BUNDLE":
            for kw in node.keywords:
                if kw.arg == "info_plist":
                    return kw.value
    raise AssertionError("no BUNDLE(info_plist=...) in the spec")


def _bundle_version_fn(version_file):
    """The spec's ``_bundle_version``, compiled against ``version_file``."""
    fn = next(n for n in _tree().body
              if isinstance(n, ast.FunctionDef) and n.name == "_bundle_version")
    ns = {"os": os, "re": re, "_version_file": version_file}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SPEC), "exec"), ns)
    return ns["_bundle_version"]


@pytest.mark.parametrize("key", ["CFBundleShortVersionString", "CFBundleVersion"])
def test_info_plist_sets_the_key_from_the_build_version(key):
    plist = _info_plist()
    values = {k.value: v for k, v in zip(plist.keys, plist.values)
              if isinstance(k, ast.Constant)}

    assert key in values
    # the numeric release part: Apple wants plain dotted integers here
    assert isinstance(values[key], ast.Name) and values[key].id == "BUNDLE_NUMERIC_VERSION"


def test_bundle_version_is_the_result_of_bundle_version():
    assigns = [n for n in _tree().body if isinstance(n, ast.Assign)
               and any(getattr(t, "id", None) == "BUNDLE_VERSION" for t in n.targets)]

    assert len(assigns) == 1
    call = assigns[0].value
    assert isinstance(call, ast.Call) and call.func.id == "_bundle_version"


def test_ci_exports_pyr_public_before_the_freeze():
    text = WORKFLOW.read_text(encoding="utf-8")

    export = text.index('echo "PYR_PUBLIC=${V%%+*}" >> "$GITHUB_ENV"')
    freeze = text.index("pyinstaller --noconfirm packaging/PyReconstruct.spec")
    assert export < freeze


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("PYR_PUBLIC", raising=False)
    monkeypatch.delenv("PYR_VERSION", raising=False)
    return monkeypatch


@pytest.mark.parametrize("value", ["1.24.0", "1.24.0.dev20260928"])
def test_pyr_public_wins(clean_env, tmp_path, value):
    vf = tmp_path / "_version.py"
    vf.write_text("__version__ = version = '9.9.9'\n", encoding="utf-8")
    clean_env.setenv("PYR_PUBLIC", value)

    assert _bundle_version_fn(vf)() == value


def test_pyr_version_drops_its_local_part(clean_env, tmp_path):
    clean_env.setenv("PYR_VERSION", "1.24.0.dev3+g1a2b3c4.d20260928")

    assert _bundle_version_fn(tmp_path / "missing.py")() == "1.24.0.dev3"


def test_a_local_build_reads_version_py(clean_env, tmp_path):
    """The shape setuptools-scm writes, local part and all."""
    vf = tmp_path / "_version.py"
    vf.write_text(
        "version: str\n"
        "__version__: str\n"
        "__version__ = version = '1.24.0.dev5+g1a2b3c4'\n"
        "__version_tuple__ = version_tuple = (1, 24, 0, 'dev5', 'g1a2b3c4')\n",
        encoding="utf-8",
    )

    assert _bundle_version_fn(vf)() == "1.24.0.dev5"


def test_nothing_known_falls_back_to_zero(clean_env, tmp_path):
    assert _bundle_version_fn(tmp_path / "missing.py")() == "0.0.0"


def test_the_full_version_rides_in_its_own_key():
    plist = _info_plist()
    values = {k.value: v for k, v in zip(plist.keys, plist.values)
              if isinstance(k, ast.Constant)}
    assert isinstance(values["PyReconstructVersion"], ast.Name)
    assert values["PyReconstructVersion"].id == "BUNDLE_VERSION"


@pytest.mark.parametrize("full, numeric", [
    ("1.24.0", "1.24.0"),
    ("1.24.0.dev20260928", "1.24.0"),
    ("1.23.1rc2", "1.23.1"),
    ("0.0.0", "0.0.0"),
    ("garbage", "0.0.0"),
])
def test_numeric_version_is_the_dotted_integer_prefix(full, numeric):
    line = next(l for l in SPEC.read_text(encoding="utf-8").splitlines()
                if l.startswith("BUNDLE_NUMERIC_VERSION"))
    ns = {"re": re, "BUNDLE_VERSION": full}
    exec(line, ns)
    assert ns["BUNDLE_NUMERIC_VERSION"] == numeric
