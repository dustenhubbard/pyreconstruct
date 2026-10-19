"""The "Fast local copy for large series" row of Series > Options (Dev builds only).

A Dev build has a Files tab holding the row; a stable build has neither the
tab nor the row, and writes no setting. The check box waits for OK. The
Remove button removes clean local copies only, and shows the folder's size.
"""
import os

import pytest

from PyReconstruct.modules.backend import settings_store
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.datatypes import local_stores
from PyReconstruct.modules.datatypes.local_stores import ENV_SWITCH, SETTING
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from PyReconstruct.modules.gui.dialog.local_store_option import (
    EXPLAIN, LocalStoreOptionWidget, sizeText,
)

from test_hybrid_store import store_root  # noqa: F401  (fixture)
from test_local_stores import _pending, make_store

pytestmark = pytest.mark.gui


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


@pytest.fixture
def settings(monkeypatch):
    store = DictSettingsStore()
    monkeypatch.setattr(settings_store, "_DEFAULT_STORE", store)
    return store


@pytest.fixture
def series(series_jser, settings, monkeypatch):
    monkeypatch.delenv(ENV_SWITCH, raising=False)
    s = Series.openJser(str(series_jser))
    s.setSettingsStore(settings)
    yield s
    s.close()


def _tabs(dlg):
    return [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]


def test_a_dev_build_shows_the_row_on_a_files_tab(qapp, series, settings, store_root, monkeypatch):  # noqa: F811
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    dlg = AllOptionsDialog(None, series)
    assert _tabs(dlg) == ["Mouse Tools", "View", "Colors", "User/Series", "Backup", "Files", "Lists"]
    page = dlg.all_widgets["local_store"]
    assert isinstance(page, LocalStoreOptionWidget)
    assert page.check.text() == "Fast local copy for large series"
    assert not page.check.isChecked()
    texts = [w.text() for w in page.findChildren(type(page.size_label))]
    assert EXPLAIN in texts
    assert EXPLAIN == (
        "Keeps a copy of each series on this computer so it opens in seconds. "
        "The .jser file stays the one you share."
    )
    assert page.size_label.text() == "Local copies on this computer: none"
    assert not page.remove_button.isEnabled()


def test_a_stable_build_has_no_row_no_tab_and_writes_no_setting(qapp, series, settings, monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: False)
    dlg = AllOptionsDialog(None, series)
    assert "Files" not in _tabs(dlg)
    assert "local_store" not in dlg.all_widgets
    assert dlg.accept() is True
    assert not settings.contains(None, SETTING)


def test_the_setting_waits_for_ok(qapp, series, settings, store_root, monkeypatch):  # noqa: F811
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    dlg = AllOptionsDialog(None, series)
    dlg.all_widgets["local_store"].check.setChecked(True)
    assert not local_stores.enabled()
    dlg.reject()
    assert not local_stores.enabled()

    dlg = AllOptionsDialog(None, series)
    assert not dlg.all_widgets["local_store"].check.isChecked()
    dlg.all_widgets["local_store"].check.setChecked(True)
    assert dlg.accept() is True
    assert settings.value(None, SETTING, bool) is True
    assert local_stores.enabled()

    # and it shows as on next time, and turns off the same way
    dlg = AllOptionsDialog(None, series)
    assert dlg.all_widgets["local_store"].check.isChecked()
    dlg.all_widgets["local_store"].check.setChecked(False)
    assert dlg.accept() is True
    assert not local_stores.enabled()


def test_reset_defaults_shows_it_off(qapp, series, settings, store_root, monkeypatch):  # noqa: F811
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    settings.set_value(None, SETTING, True)
    dlg = AllOptionsDialog(None, series)
    assert dlg.all_widgets["local_store"].check.isChecked()
    dlg.resetDefaults()
    assert not dlg.all_widgets["local_store"].check.isChecked()


def test_the_row_says_when_the_switch_decides(qapp, series, store_root, monkeypatch):  # noqa: F811
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    monkeypatch.setenv(ENV_SWITCH, "1")
    page = LocalStoreOptionWidget(None, series)
    texts = [w.text() for w in page.findChildren(type(page.size_label))]
    assert "PYRECON_HYBRID_STORE is set, so it decides for now: the copy is on." in texts


def test_remove_takes_clean_copies_only_and_shows_the_size(qapp, series, tmp_path, store_root, monkeypatch):  # noqa: F811
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    _, clean = make_store(tmp_path / "a", monkeypatch)
    _, work = make_store(tmp_path / "b", monkeypatch)
    _pending(work)
    page = LocalStoreOptionWidget(None, series)
    assert page.remove_button.isEnabled()
    before = local_stores.folderSize()
    assert page.size_label.text() == f"Local copies on this computer: {sizeText(before)}"

    page.remove_button.click()
    assert not os.path.exists(clean)
    assert os.path.isfile(work)
    assert page.result_label.text() == "Removed 1 local copy. Kept 1: holds work its .jser lacks."
    assert local_stores.folderSize() < before
    assert page.size_label.text() == (
        f"Local copies on this computer: {sizeText(local_stores.folderSize())}"
    )


@pytest.mark.parametrize("n, text", [
    (0, "none"), (1, "under 1 MB"), (5 * 1024 ** 2, "5 MB"), (int(1.46 * 1024 ** 3), "1.5 GB"),
])
def test_size_text(n, text):
    assert sizeText(n) == text
