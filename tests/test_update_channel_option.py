"""Update settings have left Series Options entirely.

The channel is pinned per build (updater.pinned_channel), the Updates tab is
gone, "Automatically check for updates" is a checkable Help item resynced from
the open series on every Help open, and the source-install branch is asked
for by the reinstall prompt instead of stored-only. These pin the removal and
the Help toggle round trip.
"""
import pytest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


@pytest.fixture
def series(series_jser):
    s = Series.openJser(str(series_jser))
    s.setSettingsStore(DictSettingsStore())
    yield s
    s.close()


def test_series_options_has_no_updates_tab(qapp, series):
    dlg = AllOptionsDialog(None, series)
    assert "updates" not in dlg.all_widgets
    from PySide6.QtWidgets import QTabWidget
    (tabs,) = dlg.findChildren(QTabWidget)
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert "Updates" not in labels


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
