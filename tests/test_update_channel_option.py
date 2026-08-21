"""The Series > Options > Updates section no longer offers a channel radio.

The update channel is pinned per build (updater.pinned_channel: the stable app
follows the release channel, the Dev flavor the prerelease channel), so the
frozen-build Updates section holds only the "Check for updates on startup"
check. These pin that shape and that applying the dialog leaves the stored
update_channel value untouched, whatever a pre-pin install had wandered it to.
"""
import os
import shutil

import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog import all_options as AO
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def _series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(DictSettingsStore())
    return series


def _frozen_dialog(monkeypatch, series):
    monkeypatch.setattr(AO, "is_frozen", lambda: True)
    return AllOptionsDialog(None, series)


def _updates_widget(dlg):
    return dlg.all_widgets["updates"]


def test_no_channel_radio_on_frozen_build(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QRadioButton
    series = _series(tmp_path)
    dlg = _frozen_dialog(monkeypatch, series)
    w = _updates_widget(dlg)
    assert w.findChildren(QRadioButton) == []
    series.close()


def test_apply_keeps_stored_channel_and_saves_startup_check(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QCheckBox
    series = _series(tmp_path)
    # a pre-pin install that had wandered onto the beta channel
    series.setOption("update_channel", "prerelease")
    dlg = _frozen_dialog(monkeypatch, series)
    w = _updates_widget(dlg)
    (check,) = w.findChildren(QCheckBox)
    check.setChecked(not series.getOption("update_check_on_startup"))
    expected = check.isChecked()
    assert w.accept(close=False)   # populate w.responses from the real widgets
    w.set()                        # run the dialog's setOption closure
    assert series.getOption("update_check_on_startup") == expected
    assert series.getOption("update_channel") == "prerelease"
    series.close()
