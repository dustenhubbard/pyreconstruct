"""Speed and memory limits on a large series: a test fails when a step is slower
or uses more memory than its limit.

Four steps a user waits for, each run in a fresh process (tests/perf_gate_child.py)
on a series built at the start of the run from the checked-in class series:

- open: ``MainWindow(jser)`` on a .jser with no working folder beside it
- memory: the peak resident size of that open
- section: one section change, the median over neighbors and far jumps
- save: a save with no edits

Off by default. CI and ``make test`` skip this module: it runs only with
``PERF_GATES=1``, on khgpu, alone (not under ``-n``), one step after another:

    PERF_GATES=1 uv run --frozen --no-default-groups --extra test \\
        python -m pytest tests/test_perf_gates.py

A step skips, with the load in the reason, when the 5-minute load average is
over ``LOAD_BAR``. ``PERF_GATES_RECORD=<file>`` appends each measurement to that
file as a JSON line, which is how the limits below are set: each is 1.5 times
the median of 5 runs. When a change makes a step faster, lower its limit in the
same change.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

# Set 2026-10-28 on khgpu at fork main ac9670b2: 1.5 x the median of 5 runs,
# median in the comment. Factor 200 is 39,600 sections, a 90 MB .jser.
SCALE_FACTOR = 200
LIMITS = {
    "open": 43.9,  # s, median 29.2
    "memory": 669.0,  # MB, median 446
    "section": 0.0289,  # s, median 0.0192
    "save": 5.54,  # s, median 3.69
}

# khgpu has 96 threads. Above this 5-minute load a step skips rather than
# fail on a busy machine.
LOAD_BAR = 24.0
CHILD_TIMEOUT_S = 1800

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "tests", "perf_gate_child.py")
SOURCE = os.path.join(ROOT, "dev", "assets", "checker", "files", "class_series.jser")
SCALER = os.path.join(ROOT, "benchmarks", "make_scaled_series.py")

pytestmark = [
    pytest.mark.perf,
    pytest.mark.skipif(
        os.environ.get("PERF_GATES") != "1",
        reason="speed and memory limits run only with PERF_GATES=1, on khgpu",
    ),
]


def run(cmd, cwd, env):
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=CHILD_TIMEOUT_S)
    assert proc.returncode == 0, (
        f"{cmd} exited {proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-4000:]}")
    return proc


def child_env(folder):
    # PYRECON_* switches change the work measured (the store backend, the .jser
    # layout, the build flavor), so none is inherited: the limits were set with
    # none exported. The store is set off, and its folder is a scratch folder,
    # so an open or save never writes to the user's real stores.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYRECON_")}
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYRECON_UNATTENDED"] = "1"
    env["PYRECON_HYBRID_STORE"] = "0"
    env["PYRECON_HYBRID_STORE_DIR"] = str(folder / "stores")
    env["XDG_CONFIG_HOME"] = str(folder / "xdg")
    return env


@pytest.fixture(scope="module")
def scaled_series(tmp_path_factory):
    """The class series in the current layout, its sections copied
    SCALE_FACTOR times. Built once per run."""
    folder = tmp_path_factory.mktemp("perf-series")
    legacy = folder / "legacy.jser"
    shutil.copyfile(SOURCE, legacy)
    run([sys.executable, CHILD, "convert", str(legacy), str(folder / "class.json")],
        folder, child_env(folder))
    scaled = folder / "scaled.jser"
    run([sys.executable, SCALER, str(folder / "class.jser"), str(scaled),
         "--factor", str(SCALE_FACTOR)], folder, child_env(folder))
    return scaled


@pytest.mark.skipif("PYTEST_XDIST_WORKER" in os.environ,
                    reason="speed and memory limits run alone, not under -n")
@pytest.mark.parametrize("step", list(LIMITS))
def test_step_within_limit(step, scaled_series, tmp_path):
    load = os.getloadavg()[1]
    if load > LOAD_BAR:
        pytest.skip(f"{step}: 5-minute load {load:.1f} is over {LOAD_BAR}")

    # a fresh copy each time: no working folder beside it, so the open is the
    # first open of this file, and the save writes over the copy only
    jser = tmp_path / scaled_series.name
    shutil.copyfile(scaled_series, jser)
    out = tmp_path / f"{step}.json"
    run([sys.executable, CHILD, step, str(jser), str(out)], tmp_path,
        child_env(tmp_path))
    with open(out) as f:
        report = json.load(f)

    report["limit"] = LIMITS[step]
    report["scale_factor"] = SCALE_FACTOR
    record = os.environ.get("PERF_GATES_RECORD")
    if record:
        with open(record, "a") as f:
            f.write(json.dumps(report) + "\n")
    print(f"{step}: {report['value']:.3f} (limit {LIMITS[step]}), "
          f"load {report['load_start']} to {report['load_end']}")

    if step == "save":
        assert report["detail"]["jser_written"], "the save did not write the .jser"
    assert report["value"] <= LIMITS[step], (
        f"{step} measured {report['value']:.3f}, over its limit {LIMITS[step]} "
        f"(5-minute load {load:.1f})")
