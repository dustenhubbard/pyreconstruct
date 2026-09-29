"""`run.py __apply_update__` reaches the swap helper without importing Qt.

On macOS and Linux the installed app is its own update helper: the app starts
itself again with ``__apply_update__`` as the first argument, and that run
swaps the install folder. It must not load Qt first, since Qt loads from the
very folder being swapped (F7 in the design: run.py used to import PySide6
before looking at its arguments). And the helper must be reached only on that
exact first argument, never because a series path or option happens to
contain the word.

Each check runs run.py in a fresh interpreter with every PySide6 import made
to fail, so any Qt import on the way is an error rather than a slow success.
apply.py itself is also checked to be stdlib only, since on Windows it is
frozen alone as the helper with no third-party packages beside it.
"""
import ast
import json
import os
import subprocess
import sys

from PyReconstruct.modules.backend.updater import apply as A

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_PY = os.path.join(ROOT, "PyReconstruct", "run.py")
APPLY_PY = os.path.join(ROOT, "PyReconstruct", "modules", "backend", "updater", "apply.py")

_DRIVER = r"""
import json, runpy, sys

class NoQt:
    def find_spec(self, name, path=None, target=None):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("PySide6 is blocked in this test: " + name)
        return None

sys.meta_path.insert(0, NoQt())
run_py, args = sys.argv[1], sys.argv[2:]
sys.argv = [run_py] + args
outcome = {"exit": None, "error": None}
try:
    runpy.run_path(run_py, run_name="__main__")
except SystemExit as e:
    outcome["exit"] = e.code
except ImportError as e:
    outcome["error"] = str(e)
outcome["qt_loaded"] = sorted(m for m in sys.modules if m.startswith("PySide6"))
outcome["gui_loaded"] = sorted(m for m in sys.modules if m.startswith("PyReconstruct.modules.gui"))
print("OUTCOME " + json.dumps(outcome))
"""


def _run(args, tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    done = subprocess.run(
        [sys.executable, "-c", _DRIVER, RUN_PY, *args],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120,
    )
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("OUTCOME ")]
    assert lines, done.stdout + done.stderr
    return json.loads(lines[-1][len("OUTCOME "):])


def test_apply_update_runs_the_helper_before_any_qt_import(tmp_path):
    staging = tmp_path / ".PyReconstruct-update"
    staging.mkdir()  # no plan.json, so the helper refuses and says so

    outcome = _run(["__apply_update__", str(staging)], tmp_path)

    assert outcome["error"] is None
    assert outcome["exit"] == 1
    assert outcome["qt_loaded"] == [] and outcome["gui_loaded"] == []
    result = A.read_json(str(staging / "result.json"))
    assert result["status"] == "refused" and "plan.json" in result["reason"]


def test_the_word_anywhere_else_does_not_reach_the_helper(tmp_path):
    staging = tmp_path / ".PyReconstruct-update"
    staging.mkdir()

    for args in (["series.jser", "__apply_update__", str(staging)], ["--__apply_update__", str(staging)]):
        outcome = _run(args, tmp_path)
        # it went on to the normal start, which imports Qt, which is blocked here
        assert outcome["error"] and "PySide6 is blocked" in outcome["error"], outcome
        assert not (staging / "result.json").exists()


def test_apply_py_imports_only_the_standard_library():
    with open(APPLY_PY, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "apply.py must not import from its package"
            names.add(node.module.split(".")[0])
    assert names and names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_apply_py_runs_alone_with_no_site_packages(tmp_path):
    """How the Windows helper runs: the file by itself, nothing installed beside it."""
    staging = tmp_path / ".PyReconstruct-update"
    staging.mkdir()
    done = subprocess.run(
        [sys.executable, "-I", "-S", APPLY_PY, "__apply_update__", str(staging)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 1, done.stderr
    assert A.read_json(str(staging / "result.json"))["status"] == "refused"
