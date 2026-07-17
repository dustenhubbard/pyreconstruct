"""The Series > Options > Updates section (frozen builds) offers three update
channels -- Stable / Beta / Developer -- as a radio group that maps BY POSITION
to the stored ``update_channel`` value ("release" / "prerelease" / "developer").

These pin the round-trip both ways through the ACTUAL dialog widgets:
  1. Opening the dialog checks the radio matching the stored channel (including
     legacy values "stable"/"edge" from older installs).
  2. Applying the dialog writes the channel value for the checked radio.
The positional mapping is provided by updater.channel_radio_index /
radio_response_channel; this exercises them through the real QuickDialog radio.

The channel radios only exist on a frozen/installed build (source installs get a
git-branch field instead), so ``is_frozen`` is patched True for the build.
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

RADIO_LABELS = [
    "Stable (recommended)",
    "Beta (early features, may be unstable)",
    "Developer (every change, expect breakage)",
]


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
    """Build the dialog as if on an installed build (channel radios present)."""
    monkeypatch.setattr(AO, "is_frozen", lambda: True)
    return AllOptionsDialog(None, series)


def _radio_response(dlg):
    """The updates widget's radio row: list of (label, checked) from real widgets."""
    w = dlg.all_widgets["updates"]
    assert w.accept(close=False)      # populate w.responses from the actual widgets
    radio = w.responses[0]
    assert [lbl for lbl, _ in radio] == RADIO_LABELS
    return radio


@pytest.mark.parametrize("channel,checked_idx", [
    ("release", 0),
    ("prerelease", 1),
    ("developer", 2),
    ("stable", 0),     # legacy -> Stable
    ("edge", 1),       # legacy -> Beta
])
def test_dialog_opens_with_stored_channel_checked(qapp, tmp_path, monkeypatch, channel, checked_idx):
    series = _series(tmp_path)
    series.setOption("update_channel", channel)
    dlg = _frozen_dialog(monkeypatch, series)
    try:
        radio = _radio_response(dlg)
        assert [checked for _, checked in radio] == [i == checked_idx for i in range(3)]
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("checked_idx,channel", [
    (0, "release"),
    (1, "prerelease"),
    (2, "developer"),
])
def test_dialog_setter_persists_selected_channel(qapp, tmp_path, monkeypatch, checked_idx, channel):
    series = _series(tmp_path)
    dlg = _frozen_dialog(monkeypatch, series)
    try:
        w = dlg.all_widgets["updates"]
        assert w.accept(close=False)             # capture real responses first
        responses = list(w.responses)
        # select exactly one radio, leaving the startup-check row (index 1) intact
        responses[0] = [(RADIO_LABELS[i], i == checked_idx) for i in range(3)]
        w.responses = tuple(responses)
        w.set()                                  # runs the dialog's setOption closure
        assert series.getOption("update_channel") == channel
    finally:
        dlg.deleteLater()


def test_dialog_preserves_startup_check_alongside_channel(qapp, tmp_path, monkeypatch):
    """Changing the channel radio must not disturb the sibling 'check on startup'
    checkbox (the other response index in the same widget)."""
    series = _series(tmp_path)
    series.setOption("update_check_on_startup", True)
    dlg = _frozen_dialog(monkeypatch, series)
    try:
        w = dlg.all_widgets["updates"]
        assert w.accept(close=False)
        responses = list(w.responses)
        responses[0] = [(RADIO_LABELS[i], i == 2) for i in range(3)]  # Developer
        w.responses = tuple(responses)
        w.set()
        assert series.getOption("update_channel") == "developer"
        assert series.getOption("update_check_on_startup") is True
    finally:
        dlg.deleteLater()
