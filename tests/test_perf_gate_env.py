"""The perf gates' children run on the store backend the limits were set on,
whatever PYRECON_* switches the parent exports, and keep their stores in the
test's folder (tests/test_perf_gates.py, child_env)."""

import json
import subprocess
import sys

from tests.test_perf_gates import ROOT, child_env

PROBE = (
    "import json\n"
    "from PyReconstruct.modules.datatypes import hybrid_store, local_stores\n"
    "print(json.dumps([local_stores.enabled(), str(hybrid_store.storeRoot())]))\n"
)


def test_child_env_pins_the_backend_and_store_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("PYRECON_HYBRID_STORE", "1")
    monkeypatch.setenv("PYRECON_HYBRID_STORE_DIR", str(tmp_path / "parent-stores"))
    monkeypatch.setenv("PYRECON_JSER_PRETTY", "1")
    monkeypatch.setenv("PYRECON_FORCE_FROZEN", "1")

    env = child_env(tmp_path)
    assert env["PYRECON_HYBRID_STORE"] == "0"
    assert env["PYRECON_HYBRID_STORE_DIR"] == str(tmp_path / "stores")
    assert "PYRECON_JSER_PRETTY" not in env
    assert "PYRECON_FORCE_FROZEN" not in env

    # what a child process reads with that environment
    proc = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-4000:]
    enabled, root = json.loads(proc.stdout.strip().splitlines()[-1])
    assert enabled is False
    assert root == str(tmp_path / "stores")
