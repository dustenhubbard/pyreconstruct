"""A NUL in the series code no longer hangs a per-series settings read.

A series' own settings live in the domain ``KHLab / PyReconstruct-<code>``. In
the Ini format (Linux, and this suite) that name becomes a file name, and
given a NUL, `QLockFile` retried the lock forever, so a per-series `getOption`
never returned. A code typed in Series code is refused a NUL, but a code read
from a series file is not. A code with a NUL now names the domain
``PyReconstruct NUL-<SHA-256 of the code>``, one file that no other code can
reach, and every other code names the same domain as before.

The settings reads and writes run in a child process with a time limit, so a
hang fails the test instead of stopping the run. The child imports the suite's
settings isolation first, which puts every `QSettings` under a temporary Ini
root inside `tmp_path`.
"""
import ast
import hashlib
import itertools
import os
import random
import re
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


def _digest(code):
    return hashlib.sha256(code.encode("utf-8", "surrogatepass")).hexdigest()


PRELUDE = f"""
import os, sys
sys.path.insert(0, {str(TESTS)!r})
import qsettings_isolation
assert qsettings_isolation.installed
from PySide6.QtCore import QSettings
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.datatypes import Series

store = QSettingsStore()

def series(code):
    s = Series.__new__(Series)
    s.options = {{}}
    s.code = code
    s.name = "nul"
    s.filepath = "/nonexistent/nul.ser"
    s.setSettingsStore(store)
    return s

def where(name):
    # the file Qt resolves a domain to: (its folder, its base name)
    path = QSettings("KHLab", name).fileName()
    return os.path.dirname(path), os.path.basename(path)
"""

READ = PRELUDE + f"""
s = series({CODE!r})
s.setOption("autobackup", True)
print(s.getOption("autobackup"))
"""

def _apart(existing_app, existing_code, incoming_code):
    """Another series has its backups set first, in the domain it names: its
    own shared one, or the Dev app's. The NUL series then reads and sets its
    own."""
    existing_name = f"{existing_app}-{existing_code}"
    return PRELUDE + f"""
existing = QSettings("KHLab", {existing_name!r})
existing.setValue("backup_dir", "/existing-series-backups")
existing.sync()
incoming = series({incoming_code!r})
before = incoming.getOption("backup_dir")
incoming.setOption("backup_dir", "/incoming-series-backups")
existing = QSettings("KHLab", {existing_name!r})
print(repr([
    before,
    existing.value("backup_dir", "", str),
    series({incoming_code!r}).getOption("backup_dir"),
    where({existing_name!r}),
    where("PyReconstruct NUL-{_digest(incoming_code)}"),
    store._settings({incoming_code!r}).fileName(),
]))
"""


FOLD = PRELUDE + f"""
from PyReconstruct.modules.constants.settings_domain import fold_series_settings_once

# the Dev domains, written out rather than built from the code: the NUL
# series' own, and the U+FFFD series' one, which the NUL fold must not take
nul_dev = QSettings("KHLab", "PyReconstruct Dev NUL-{_digest(CODE)}")
nul_dev.setValue("autobackup", True)
nul_dev.sync()
fffd_dev = QSettings("KHLab", "PyReconstruct Dev-ab�c")
fffd_dev.setValue("backup_dir", "/existing-series-backups")
fffd_dev.sync()
folded = fold_series_settings_once({CODE!r})
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
    "SER1", "ABC", "a b", "a:b", "a/b", "a\\b", "..", "é", "", "%00", "a0",
    FFFD_CODE, "�", " NUL-0",
])
@pytest.mark.parametrize("app", APPS)
def test_a_code_without_a_nul_names_the_same_domain(app, code):
    # the name every release before this one built
    assert SD.series_app(app, code) == app + "-" + code


@pytest.mark.parametrize("code", [
    CODE, "\0", "\0/../PyReconstruct-existing", "\0\\..\\x", "..\0", "\0" * 300,
])
@pytest.mark.parametrize("app", APPS)
def test_a_code_with_a_nul_names_its_digest(app, code):
    name = SD.series_app(app, code)
    assert name == f"{app} NUL-{_digest(code)}"
    assert re.fullmatch(re.escape(app) + " NUL-[0-9a-f]{64}", name)


@pytest.mark.parametrize("one, other", [
    (CODE, FFFD_CODE),
    (CODE, "abc"),
    (CODE, "ab\0\0c"),
    ("\0", ""),
    ("\0", "�"),
    ("\0", " NUL-" + _digest("\0")),
    ("\0/../PyReconstruct-existing", "existing"),
    ("\0a", "a\0"),
])
def test_two_codes_never_share_a_domain(one, other):
    for app in APPS:
        assert SD.series_app(app, one) != SD.series_app(app, other)


def _assert_distinct_names(codes):
    names = {}
    for code in codes:
        for app in APPS:
            name = SD.series_app(app, code)
            assert "\0" not in name
            if "\0" in code:
                # nothing a path could read as a separator or a dot segment
                assert re.fullmatch(re.escape(app) + " NUL-[0-9a-f]{64}", name)
            assert names.setdefault(name, (app, code)) == (app, code), name


def test_every_short_code_names_its_own_domain():
    # every code up to five characters over a mix of plain, path and NUL
    alphabet = ["a", "-", "/", "\\", ".", "\0", "�"]
    _assert_distinct_names(
        "".join(chars)
        for n in range(6)
        for chars in itertools.product(alphabet, repeat=n)
    )


def test_random_codes_name_their_own_domains():
    rng = random.Random(1069)
    alphabet = ["a", "N", "0", "%", "-", " ", "/", "\\", ".", "\0", "�"]
    _assert_distinct_names({
        "".join(rng.choices(alphabet, k=rng.randint(0, 16)))
        for _ in range(20000)
    })


def test_a_series_setting_reads_back_with_a_nul_in_the_code(tmp_path):
    assert _run(READ, tmp_path) == "True"


@pytest.mark.parametrize("existing_app, existing_code, incoming_code", [
    ("PyReconstruct", FFFD_CODE, CODE),
    ("PyReconstruct", "existing", "\0/../PyReconstruct-existing"),
    ("PyReconstruct Dev", "existing", "\0/../PyReconstruct Dev-existing"),
])
def test_a_nul_code_leaves_another_series_its_backups(
    tmp_path, existing_app, existing_code, incoming_code
):
    script = _apart(existing_app, existing_code, incoming_code)
    before, existing, incoming, existing_at, nul_at, nul_path = ast.literal_eval(
        _run(script, tmp_path)
    )
    assert before == ""
    assert existing == "/existing-series-backups"
    assert incoming == "/incoming-series-backups"
    # the NUL series' file sits beside the others, under its own name
    assert nul_path == os.path.join(*nul_at)
    assert nul_at == (existing_at[0], f"PyReconstruct NUL-{_digest(incoming_code)}.ini")


def test_the_dev_fold_carries_only_the_nul_series_own_settings(tmp_path):
    # the fold and the store name the series' domains the same way
    out = _run(FOLD, tmp_path, PYRECON_APP_NAME="PyReconstruct Dev")
    assert out == "True True False"
