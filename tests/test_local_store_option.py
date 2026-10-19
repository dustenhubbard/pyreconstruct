"""The "Fast local copy for large series" row of Series > Options (Dev builds only).

A Dev build has a Files tab holding the row; a stable build has neither the
tab nor the row, and writes no setting. The check box waits for OK. The
Remove button removes clean local copies only, and shows the folder's size.
Unticking it in a window whose series saved to its local copy writes that
Save to the .jser with the window's automatic backup, and says which files
it wrote; a write that fails keeps the copy, and the close writes it.
"""
import os

import pytest

from PyReconstruct.modules.backend import settings_store
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.datatypes import local_stores, store_save
from PyReconstruct.modules.datatypes import series as series_module
from PyReconstruct.modules.datatypes.local_stores import ENV_SWITCH, SETTING
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from PyReconstruct.modules.gui.dialog import local_store_option
from PyReconstruct.modules.gui.dialog.local_store_option import (
    EXPLAIN, LocalStoreOptionWidget, sizeText,
)

from test_hybrid_store import store_root  # noqa: F401  (fixture)
from test_local_stores import _pending, make_store
from test_store_save_gui import (
    _disk_full, _saved_in_the_store, _store_mode, _window,
    kept,  # noqa: F401  (fixture)
)

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
    # showing the row writes nothing, not even the default
    assert not settings.contains(None, SETTING)
    dlg.all_widgets["local_store"].check.setChecked(True)
    assert not local_stores.enabled()
    dlg.reject()
    assert not local_stores.enabled()
    assert not settings.contains(None, SETTING)

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


# ---------------------------------------------------------------------------
# unticking it in the window
# ---------------------------------------------------------------------------

def _setting_on_and_saved(window, tmp_path, monkeypatch):
    """The window's series, saved to its store alone, with the setting deciding.

    Its backup goes to a folder of its own, on every save.
    """
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    assert store_save.heldStore(window.series) is not None
    snum, edited = _saved_in_the_store(window)
    settings = DictSettingsStore()
    settings.set_value(None, SETTING, True)
    window.series.setSettingsStore(settings)
    backups = tmp_path / "backups"
    backups.mkdir()
    window.series.setBackupUsesDefaults(False)
    window.series.setOption("backup_dir", str(backups))
    window.series.setOption("autobackup", True)
    monkeypatch.delenv(ENV_SWITCH)
    return snum, edited, backups


def _untick(window, monkeypatch):
    told = []
    monkeypatch.setattr(local_store_option, "notify", told.append)
    dlg = AllOptionsDialog(window, window.series)
    dlg.all_widgets["local_store"].check.setChecked(False)
    assert dlg.accept() is True
    return told


def _section_in_the_jser(fp, snum):
    plain = Series.openJser(str(fp))
    try:
        return plain.loadSection(snum).getDict()
    finally:
        plain.close()


def test_unticking_it_writes_the_save_to_the_jser_with_its_backup(kept, tmp_path, main_window_dialogs, monkeypatch):  # noqa: F811
    _store_mode(monkeypatch)
    window = _window(kept)
    try:
        snum, edited, backups = _setting_on_and_saved(window, tmp_path, monkeypatch)
        before = kept.read_bytes()
        told = _untick(window, monkeypatch)
        assert kept.read_bytes() != before
        written = sorted(backups.iterdir())
        assert len(written) == 1
        assert written[0].read_bytes() == kept.read_bytes()
        assert told == [
            "Fast local copy is off. The last Save in the local copy was written to:\n"
            f"{kept}\n{written[0]}"
        ]
        assert store_save.heldStore(window.series) is None
        saved = kept.read_bytes()
    finally:
        window.close()
    # the close had nothing more to write
    assert kept.read_bytes() == saved
    assert _section_in_the_jser(kept, snum) == edited


def test_unticking_it_when_the_write_fails_keeps_the_copy_and_the_close_writes_it(kept, tmp_path, main_window_dialogs, monkeypatch):  # noqa: F811
    _store_mode(monkeypatch)
    window = _window(kept)
    try:
        snum, edited, backups = _setting_on_and_saved(window, tmp_path, monkeypatch)
        before = kept.read_bytes()
        write = series_module._atomicWrite
        shown = _disk_full(window, monkeypatch)
        told = _untick(window, monkeypatch)
        assert len(shown) == 1
        assert kept.read_bytes() == before
        assert list(backups.iterdir()) == []
        assert len(told) == 1
        assert told[0].startswith(f"The local copy could not be written to:\n{kept}\n")
        assert store_save.heldStore(window.series) is not None
        assert store_save.ahead(window.series)
        monkeypatch.setattr(series_module, "_atomicWrite", write)
    finally:
        window.close()
    assert kept.read_bytes() != before
    assert _section_in_the_jser(kept, snum) == edited


def test_unticking_it_names_a_backup_made_in_a_folder_picked_then(kept, tmp_path, main_window_dialogs, monkeypatch):  # noqa: F811
    _store_mode(monkeypatch)
    window = _window(kept)
    try:
        _, _, backups = _setting_on_and_saved(window, tmp_path, monkeypatch)
        # the set folder is gone; the backup asks for one, and the user picks it
        window.series.setOption("backup_dir", str(tmp_path / "gone"))
        picked = tmp_path / "picked"
        picked.mkdir()
        monkeypatch.setattr(window, "setBackup", lambda: window.series.setOption("backup_dir", str(picked)))
        told = _untick(window, monkeypatch)
        written = sorted(picked.iterdir())
        assert len(written) == 1
        assert written[0].read_bytes() == kept.read_bytes()
        assert list(backups.iterdir()) == []
        assert told == [
            "Fast local copy is off. The last Save in the local copy was written to:\n"
            f"{kept}\n{written[0]}"
        ]
        assert store_save.heldStore(window.series) is None
    finally:
        window.close()


def test_a_parent_window_with_another_series_does_not_write_this_one(qapp, kept, tmp_path, main_window_dialogs, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QWidget

    class Other(QWidget):
        """A main window holding another series."""
        series = object()
        calls = []

        def _writeStoreSave(self, written=None):
            self.calls.append(written)
            return True

    _store_mode(monkeypatch)
    window = _window(kept)
    try:
        snum, edited, backups = _setting_on_and_saved(window, tmp_path, monkeypatch)
        before = kept.read_bytes()
        told = []
        monkeypatch.setattr(local_store_option, "notify", told.append)
        other = Other()
        dlg = AllOptionsDialog(other, window.series)
        dlg.all_widgets["local_store"].check.setChecked(False)
        assert dlg.accept() is True
        # this series' own write-out ran, with no backup: the other window's
        # writes its own series
        assert Other.calls == []
        assert kept.read_bytes() != before
        assert list(backups.iterdir()) == []
        assert told == [
            f"Fast local copy is off. The last Save in the local copy was written to:\n{kept}"
        ]
        assert store_save.heldStore(window.series) is None
    finally:
        window.close()
    assert _section_in_the_jser(kept, snum) == edited
