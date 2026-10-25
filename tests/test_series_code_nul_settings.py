"""A NUL in the series code no longer hangs a per-series settings read.

A series' own settings live in the domain ``KHLab / PyReconstruct-<code>``. In
the Ini format (Linux, and this suite) that name becomes a file name, and
given a NUL, `QLockFile` retried the lock forever, so a per-series `getOption`
never returned. A code typed in Series code is refused a NUL, but a code read
from a series file is not. The NUL now stands in as U+FFFD in the domain name,
and every other code names the same domain as before.

The settings reads and writes run in a child process with a time limit, so a
hang fails the test instead of stopping the run. The child imports the suite's
settings isolation first, which puts every `QSettings` under a temporary Ini
root inside `tmp_path`.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from PyReconstruct.modules.constants import settings_domain as SD

CODE = "ab\0c"
TESTS = Path(__file__).resolve().parent
# a hang shows as a timeout; a read that works takes under a second
LIMIT = 60

READ = f"""
import sys
sys.path.insert(0, {str(TESTS)!r})
import qsettings_isolation
assert qsettings_isolation.installed
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.datatypes import Series

series = Series.__new__(Series)
series.options = {{}}
series.code = {CODE!r}
series.name = "nul"
series.filepath = "/nonexistent/nul.ser"
series.setSettingsStore(QSettingsStore())
series.setOption("autobackup", True)
print(series.getOption("autobackup"))
"""

FOLD = f"""
import sys
sys.path.insert(0, {str(TESTS)!r})
import qsettings_isolation
assert qsettings_isolation.installed
from PySide6.QtCore import QSettings
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants.settings_domain import fold_series_settings_once

# the Dev domain of this series, written out rather than built from the code
dev = QSettings("KHLab", "PyReconstruct Dev-ab\ufffdc")
dev.setValue("autobackup", True)
dev.sync()
folded = fold_series_settings_once({CODE!r})
print(folded, QSettingsStore().value({CODE!r}, "autobackup", bool))
"""


def _run(script, tmp_path, **env):
    """Run `script` in a child process, failing if it does not finish in time."""
    env = {**os.environ, "TMPDIR": str(tmp_path), "QT_QPA_PLATFORM": "offscreen", **env}
    try:
        done = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=LIMIT, env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"the settings read did not finish in {LIMIT} s")
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize("code", ["SER1", "ABC", "a b", "a:b", "a/b", "é", ""])
def test_a_code_without_a_nul_names_the_same_domain(code):
    assert SD.series_app("PyReconstruct", code) == f"PyReconstruct-{code}"


def test_a_nul_is_replaced_in_the_domain_name():
    name = SD.series_app("PyReconstruct", CODE)
    assert "\0" not in name
    assert name == "PyReconstruct-ab\ufffdc"
    # not the domain of the same code with the NUL dropped
    assert name != SD.series_app("PyReconstruct", "abc")


def test_a_series_setting_reads_back_with_a_nul_in_the_code(tmp_path):
    assert _run(READ, tmp_path) == "True"


def test_the_dev_fold_carries_a_setting_with_a_nul_in_the_code(tmp_path):
    # the fold and the store name the series' domains the same way
    assert _run(FOLD, tmp_path, PYRECON_APP_NAME="PyReconstruct Dev") == "True True"
