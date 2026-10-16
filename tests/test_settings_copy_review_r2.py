"""Round 2 review of the settings move: a real window started and closed
during a session whose copy from ``KHLab`` failed fills none of the owed
preferences, the palette's increment mode among them, and a damaged old file
touched in a way Qt cannot see is still not taken as read.

The second concurrent-copy probe of that round is not kept, for the reason in
``test_settings_copy_review_r1.py``.
"""

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QFileInfo, QSettings

from PyReconstruct.modules.constants import settings_domain as D

from settings_copy_review import DEV, DAMAGED, fail_copy, review_store

pytestmark = pytest.mark.gui


@pytest.fixture
def setup_store(qapp, monkeypatch):
    yield from review_store(monkeypatch)


def _old_store(monkeypatch, old, dev_only):
    if not dev_only:
        return D.SHARED_APP, old
    monkeypatch.setenv("PYRECON_APP_NAME", DEV)
    return DEV, QSettings(D.LEGACY_SETTINGS_ORG, DEV)


@pytest.mark.parametrize("dev_only", [False, True])
def test_startup_and_unmoved_close_do_not_fill_pending_preferences(
    setup_store, monkeypatch, request, dev_only,
):
    series, old, new = setup_store
    app, old = _old_store(monkeypatch, old, dev_only)
    old.setValue("theme", "qdark")
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken, app)
        assert not D.copy_legacy_settings_once().complete
    window = request.getfixturevalue("main_window")
    window.series.modified = False
    assert window.close()
    # The fixture itself seeds last_whatsnew_version. A successful shared copy
    # during a failed Dev copy records its marker. Nothing else may be there.
    allowed = {"last_whatsnew_version", D.LEGACY_COPY_MARKER}
    assert set(new.allKeys()) <= allowed
    assert D.copy_legacy_settings_once().complete
    D.fold_flavor_settings_once()
    assert new.value("theme") == "qdark"


def test_corrupt_ini_is_not_certified_after_a_submillisecond_touch(setup_store):
    app = "PyReconstruct-CORRUPT_SUBMS_REVIEW"
    path = Path(QSettings(D.LEGACY_SETTINGS_ORG, app).fileName())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DAMAGED)
    assert not D.copy_legacy_series_settings_once("CORRUPT_SUBMS_REVIEW").complete
    before = path.stat()
    before_qt = QFileInfo(str(path)).lastModified().toMSecsSinceEpoch()
    # change only the part of the time below a millisecond, which Qt does not see
    ms_base = (before.st_mtime_ns // 1_000_000) * 1_000_000
    changed_ns = ms_base + (1 if before.st_mtime_ns != ms_base + 1 else 2)
    os.utime(path, ns=(before.st_atime_ns, changed_ns))
    assert path.stat().st_mtime_ns != before.st_mtime_ns
    assert path.read_text() == DAMAGED
    assert QFileInfo(str(path)).lastModified().toMSecsSinceEpoch() == before_qt
    result = D.copy_legacy_series_settings_once("CORRUPT_SUBMS_REVIEW")
    assert result.complete is False
    assert not QSettings(D.SETTINGS_ORG, app).contains(D.LEGACY_COPY_MARKER)


@pytest.mark.parametrize("dev_only", [False, True])
def test_palette_increment_choice_survives_failed_copy_and_startup(
    setup_store, monkeypatch, request, dev_only,
):
    series, old, new = setup_store
    app, old = _old_store(monkeypatch, old, dev_only)
    old.setValue("palette_inc_all", False)
    old.sync()
    with monkeypatch.context() as broken:
        fail_copy(broken, app)
        assert not D.copy_legacy_settings_once().complete
    request.getfixturevalue("main_window")
    assert D.copy_legacy_settings_once().complete
    D.fold_flavor_settings_once()
    assert new.value("palette_inc_all", type=bool) is False
