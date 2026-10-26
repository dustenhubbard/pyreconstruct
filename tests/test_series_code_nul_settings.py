"""A NUL in the series code no longer hangs a per-series settings read.

A series' own settings live in the domain ``KHLab / PyReconstruct-<code>``. In
the Ini format (Linux, and this suite) that name becomes a file name, and
given a NUL, `QLockFile` retried the lock forever, so a per-series `getOption`
never returned. A code typed in Series code is refused a NUL, but a code read
from a series file is not. A code with a NUL now names a domain of its own
kind, which no other code can name, and every other code names the same
domain as before.

The settings reads and writes run in a child process with a time limit, so a
hang fails the test instead of stopping the run. The child imports the suite's
settings isolation first, which puts every `QSettings` under a temporary Ini
root inside `tmp_path`.
"""
import ast
import itertools
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from PyReconstruct.modules.constants import settings_domain as SD

CODE = "ab\0c"
# a code a user can have today; replacing the NUL with U+FFFD gave CODE its name
FFFD_CODE = "ab�c"
APPS = ["PyReconstruct", "PyReconstruct Dev"]
TESTS = Path(__file__).resolve().parent
# a hang shows as a timeout; a read that works takes under a second
LIMIT = 60

PRELUDE = f"""
import sys
sys.path.insert(0, {str(TESTS)!r})
import qsettings_isolation
assert qsettings_isolation.installed
"""

SERIES = PRELUDE + """
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.datatypes import Series

def series(code):
    s = Series.__new__(Series)
    s.options = {}
    s.code = code
    s.name = "nul"
    s.filepath = "/nonexistent/nul.ser"
    s.setSettingsStore(QSettingsStore())
    return s
"""

READ = SERIES + f"""
s = series({CODE!r})
s.setOption("autobackup", True)
print(s.getOption("autobackup"))
"""

# the series with the U+FFFD code has its backups set first; the NUL series
# then reads and sets its own
APART = SERIES + f"""
existing = series({FFFD_CODE!r})
existing.setOption("backup_dir", "/existing-series-backups")
incoming = series({CODE!r})
before = incoming.getOption("backup_dir")
incoming.setOption("backup_dir", "/incoming-series-backups")
print(repr([
    before,
    series({FFFD_CODE!r}).getOption("backup_dir"),
    series({CODE!r}).getOption("backup_dir"),
]))
"""

FOLD = PRELUDE + f"""
from PySide6.QtCore import QSettings
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants.settings_domain import fold_series_settings_once

# the Dev domains, written out rather than built from the code: the NUL
# series' own, and the U+FFFD series' one, which the NUL fold must not take
nul_dev = QSettings("KHLab", "PyReconstruct Dev�-ab�0c")
nul_dev.setValue("autobackup", True)
nul_dev.sync()
fffd_dev = QSettings("KHLab", "PyReconstruct Dev-ab�c")
fffd_dev.setValue("backup_dir", "/existing-series-backups")
fffd_dev.sync()
folded = fold_series_settings_once({CODE!r})
store = QSettingsStore()
print(folded, store.value({CODE!r}, "autobackup", bool),
      store.contains({CODE!r}, "backup_dir"))
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


@pytest.mark.parametrize("code", [
    "SER1", "ABC", "a b", "a:b", "a/b", "é", "", "%00", "a0",
    FFFD_CODE, "�", "�0", "��",
])
@pytest.mark.parametrize("app", APPS)
def test_a_code_without_a_nul_names_the_same_domain(app, code):
    # the name every release before this one built
    assert SD.series_app(app, code) == app + "-" + code


def test_a_code_with_a_nul_names_an_escaped_domain_of_its_own_kind():
    assert SD.series_app("PyReconstruct", CODE) == "PyReconstruct�-ab�0c"
    assert (
        SD.series_app("PyReconstruct Dev", "�\0")
        == "PyReconstruct Dev�-���0"
    )


@pytest.mark.parametrize("one, other", [
    (CODE, FFFD_CODE),
    (CODE, "abc"),
    (CODE, "ab�0c"),
    ("\0", "�"),
    ("\0", "�0"),
    ("\0", ""),
    ("\0�", "�\0"),
    ("\0�0", "\0\0"),
])
def test_two_codes_never_share_a_domain(one, other):
    assert SD.series_app("PyReconstruct", one) != SD.series_app("PyReconstruct", other)


def _assert_distinct_names(codes):
    names = {}
    for code in codes:
        for app in APPS:
            name = SD.series_app(app, code)
            assert "\0" not in name
            assert names.setdefault(name, (app, code)) == (app, code), name


def test_every_short_code_names_its_own_domain():
    # every code up to six characters over the characters the escape uses
    alphabet = ["a", "0", "-", "\0", "�"]
    _assert_distinct_names(
        "".join(chars)
        for n in range(7)
        for chars in itertools.product(alphabet, repeat=n)
    )


def test_random_codes_name_their_own_domains():
    rng = random.Random(1069)
    alphabet = ["a", "b", "0", "%", "-", " ", "\0", "�"]
    _assert_distinct_names({
        "".join(rng.choices(alphabet, k=rng.randint(0, 16)))
        for _ in range(20000)
    })


def test_a_series_setting_reads_back_with_a_nul_in_the_code(tmp_path):
    assert _run(READ, tmp_path) == "True"


def test_a_nul_code_leaves_a_fffd_code_its_backups(tmp_path):
    before, existing, incoming = ast.literal_eval(_run(APART, tmp_path))
    assert before == ""
    assert existing == "/existing-series-backups"
    assert incoming == "/incoming-series-backups"


def test_the_dev_fold_carries_only_the_nul_series_own_settings(tmp_path):
    # the fold and the store name the series' domains the same way
    out = _run(FOLD, tmp_path, PYRECON_APP_NAME="PyReconstruct Dev")
    assert out == "True True False"
