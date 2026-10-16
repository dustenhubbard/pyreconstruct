"""Round 3 review of the settings move.

A damaged old file stays owed across the in-app Restart, in the same process
(``settings_restart_child.py``, run in a pytest process of its own because it
reloads modules), and copies at a real later launch once it is repaired. An
old store that could not be opened is retried in the same process. A Save
whose automatic backup cannot find its folder, and whose Backup Settings
dialog is canceled, does not store fallback backup choices over the ones the
series' copy is still to bring. A window opened and closed on a series whose
copy failed stores nothing in that series' store.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

import qsettings_isolation
from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants import settings_domain as D

from settings_copy_review import DAMAGED, DEV, empty_stores, fail_copy

pytestmark = pytest.mark.gui

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent


def test_a_damaged_old_file_stays_owed_across_the_in_app_restart():
    child = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
            "-c", str(REPO / "pytest.ini"),
            str(TESTS / "settings_restart_child.py"),
        ],
        cwd=REPO, capture_output=True, text=True,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert "3 passed" in child.stdout, child.stdout


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
    code = "ACCESS_RETRY_REVIEW"
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


@pytest.mark.parametrize("copy_fails", [False, True])
def test_cancelled_auto_backup_must_not_replace_owed_series_preferences(
    main_window, tmp_path, monkeypatch, copy_fails,
):
    from PyReconstruct.modules.gui.dialog.backup import BackupDialog

    series = main_window.series
    series.setSettingsStore(QSettingsStore())
    app = D.SHARED_APP + "-" + series.code
    empty_stores(app)
    old = QSettings(D.LEGACY_SETTINGS_ORG, app)
    new = QSettings(D.SETTINGS_ORG, app)
    valid = tmp_path / "real-legacy-backups"
    valid.mkdir()
    old.setValue("autobackup", True)
    old.setValue("backup_dir", str(valid))
    old.sync()
    # the global defaults pick auto-backup, but their folder is gone
    series.setOption("default_autobackup", True)
    series.setOption("default_backup_dir", str(tmp_path / "missing-default"))
    with monkeypatch.context() as broken:
        if copy_fails:
            fail_copy(broken, app)
        assert D.copy_legacy_series_settings_once(series.code).complete is (not copy_fails)
    assert D.shared_copy_pending("-" + series.code) is copy_fails
    # the real dialog is built; its exec stands for Cancel, without a modal loop
    rejected = []
    monkeypatch.setattr(BackupDialog, "exec", lambda dialog: rejected.append(True) or False)
    main_window.saveToJser()
    assert rejected == ([True] if copy_fails else [])
    if not copy_fails:
        assert len(list(valid.glob("*.jser"))) == 1
    assert D.copy_legacy_series_settings_once(series.code).complete
    assert new.value("autobackup", type=bool) is True
    assert new.value("backup_dir") == str(valid)
    defaults = QSettings(D.SETTINGS_ORG, D.SHARED_APP)
    defaults.remove("default_autobackup")
    defaults.remove("default_backup_dir")
    defaults.sync()
    empty_stores(app)


@pytest.mark.parametrize("dev_only", [False, True])
def test_pending_series_store_has_no_startup_or_unmoved_close_defaults(
    qapp, series_jser, monkeypatch, request, dev_only,
):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    data = json.loads(Path(series_jser).read_text())
    raw = next(value for key, value in data.items() if key.endswith(".ser"))
    code = raw.get("code") or Path(series_jser).stem
    empty_stores(D.SHARED_APP + "-" + code, DEV + "-" + code)
    source_app = (DEV if dev_only else D.SHARED_APP) + "-" + code
    if dev_only:
        monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    else:
        monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    old = QSettings(D.LEGACY_SETTINGS_ORG, source_app)
    old.setValue("list_layout", '{"trace": []}')
    old.setValue("autobackup", True)
    old.sync()
    fail_copy(monkeypatch, source_app)
    window = request.getfixturevalue("main_window")
    assert window.series.code == code
    assert D.shared_copy_pending("-" + code)
    new = QSettings(D.SETTINGS_ORG, D.SHARED_APP + "-" + code)
    before = set(new.allKeys())
    assert before <= {D.LEGACY_COPY_MARKER}
    # the fixture turns layout capture off for test hygiene; the real method
    # is the close-time writer this checks
    MainWindow._captureListLayout(window)
    window.series.modified = False
    assert window.close()
    assert set(new.allKeys()) == before
