"""Update settings have left Series Options entirely.

The channel is pinned per build (updater.pinned_channel), the Updates tab is
gone, "Check for updates on startup" is a checkable Help item resynced from
the open series on every Help open, and the source-install branch is asked
for by the reinstall prompt instead of stored-only. These pin the removal and
the Help toggle round trip.
"""
import os
import shutil

import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)

pytestmark = pytest.mark.gui


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


def test_series_options_has_no_updates_tab(qapp, tmp_path):
    series = _series(tmp_path)
    dlg = AllOptionsDialog(None, series)
    assert "updates" not in dlg.all_widgets
    from PySide6.QtWidgets import QTabWidget
    (tabs,) = dlg.findChildren(QTabWidget)
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert "Updates" not in labels
    series.close()


def test_help_toggle_round_trips_the_startup_check(main_window):
    mw = main_window
    stored = bool(mw.series.getOption("update_check_on_startup"))

    # the resync reflects the stored option on the checkable
    mw.syncUpdateCheckToggle()
    assert mw.toggleupdatecheck_act.isChecked() == stored

    # flipping the checkable persists the option
    mw.toggleupdatecheck_act.setChecked(not stored)
    mw.toggleUpdateCheckOnStartup()
    assert bool(mw.series.getOption("update_check_on_startup")) == (not stored)

    # and the resync agrees with what was just written
    mw.syncUpdateCheckToggle()
    assert mw.toggleupdatecheck_act.isChecked() == (not stored)
