"""An old store that cannot be read stays owed until it can be.

Qt parses a settings file once per process and hands later readers that
parse with no error, even when it stopped partway through a damaged file. So
a damaged old file stays owed for the rest of the process, through a touch Qt
cannot see, and copies at the next launch once it is repaired. An old store
that could not be opened is not parsed, and is retried in the same process.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QFileInfo, QSettings

import qsettings_isolation
from PyReconstruct.modules.constants import settings_domain as D

from settings_copy_helpers import DAMAGED, bare_series_store, empty_stores, fail_copy

pytestmark = pytest.mark.gui

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent


@pytest.fixture
def setup_store(qapp, monkeypatch):
    yield from bare_series_store(monkeypatch)

def test_corrupt_ini_keeps_copy_pending(setup_store):
    from pathlib import Path

    app = "PyReconstruct-CORRUPT_COPYTEST"
    target = Path(QSettings(D.LEGACY_SETTINGS_ORG, app).fileName())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DAMAGED)
    assert D.copy_legacy_series_settings_once("CORRUPT_COPYTEST").complete is False
    assert D.copy_legacy_series_settings_once("CORRUPT_COPYTEST").complete is False

def test_corrupt_ini_is_not_certified_after_a_submillisecond_touch(setup_store):
    app = "PyReconstruct-CORRUPT_SUBMS_COPYTEST"
    path = Path(QSettings(D.LEGACY_SETTINGS_ORG, app).fileName())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DAMAGED)
    assert not D.copy_legacy_series_settings_once("CORRUPT_SUBMS_COPYTEST").complete
    before = path.stat()
    before_qt = QFileInfo(str(path)).lastModified().toMSecsSinceEpoch()
    # change only the part of the time below a millisecond, which Qt does not see
    ms_base = (before.st_mtime_ns // 1_000_000) * 1_000_000
    changed_ns = ms_base + (1 if before.st_mtime_ns != ms_base + 1 else 2)
    os.utime(path, ns=(before.st_atime_ns, changed_ns))
    assert path.stat().st_mtime_ns != before.st_mtime_ns
    assert path.read_text() == DAMAGED
    assert QFileInfo(str(path)).lastModified().toMSecsSinceEpoch() == before_qt
    result = D.copy_legacy_series_settings_once("CORRUPT_SUBMS_COPYTEST")
    assert result.complete is False
    assert not QSettings(D.SETTINGS_ORG, app).contains(D.LEGACY_COPY_MARKER)

# A later launch, run as a process of its own on this session's redirected
# stores. The suite's redirect is installed first, on the root given in argv,
# and that root is left for this session to delete.
_LATER_LAUNCH = """
import atexit, json, shutil, sys, tempfile
root, code = sys.argv[1], sys.argv[2]
make = tempfile.mkdtemp
tempfile.mkdtemp = lambda *a, **k: (
    root if k.get("prefix") == "pyrecon-qsettings-" else make(*a, **k))
import qsettings_isolation as isolation
tempfile.mkdtemp = make
atexit.unregister(shutil.rmtree)
isolation.verify_isolated()
from PyReconstruct.modules.constants import settings_domain as D
assert not D._unparsable_legacy
result = D.copy_legacy_series_settings_once(code)
assert isolation.recorded_bypasses() == ()
print(json.dumps({"complete": result.complete, "copied": dict(result)}))
"""

def test_repaired_file_is_held_here_and_copies_in_a_real_later_process(qapp):
    code = "ACTUAL_NEXT_PROCESS"
    app = D.SHARED_APP + "-" + code
    empty_stores(app)
    path = Path(QSettings(D.LEGACY_SETTINGS_ORG, app).fileName())
    assert str(path).startswith(qsettings_isolation.isolation_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DAMAGED)
    assert not D.copy_legacy_series_settings_once(code).complete
    assert app in D._unparsable_legacy
    path.write_text("[General]\nlegacy_repaired=yes\n")
    # this process keeps its partial parse, so the repair waits for a launch
    assert not D.copy_legacy_series_settings_once(code).complete
    assert not QSettings(D.SETTINGS_ORG, app).contains(D.LEGACY_COPY_MARKER)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO), str(TESTS)]))
    later = subprocess.run(
        [sys.executable, "-c", _LATER_LAUNCH, qsettings_isolation.isolation_root, code],
        cwd=REPO, env=env, capture_output=True, text=True,
    )
    assert later.returncode == 0, later.stdout + later.stderr
    outcome = json.loads(later.stdout.strip().splitlines()[-1])
    assert outcome == {"complete": True, "copied": {app: ["legacy_repaired"]}}
    new = QSettings(D.SETTINGS_ORG, app)
    new.sync()
    assert new.value("legacy_repaired") == "yes"
    assert not new.contains("broken/entry")
    empty_stores(app)

def test_access_error_stays_retryable_within_this_process(qapp, monkeypatch):
    code = "ACCESS_RETRY_COPYTEST"
    app = D.SHARED_APP + "-" + code
    empty_stores(app)
    old = QSettings(D.LEGACY_SETTINGS_ORG, app)
    old.setValue("legacy_access", "restored")
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken, app)
        assert not D.copy_legacy_series_settings_once(code).complete
        assert D.legacy_copy_pending(app)
        assert app not in D._unparsable_legacy
    assert D.copy_legacy_series_settings_once(code).complete
    new = QSettings(D.SETTINGS_ORG, app)
    assert new.value("legacy_access") == "restored"
    assert new.value(D.LEGACY_COPY_MARKER, type=bool) is True
    assert not D.legacy_copy_pending(app)
    empty_stores(app)
