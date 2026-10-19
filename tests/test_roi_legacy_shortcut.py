"""B still picks the ROI mode tool on a machine that ran an older Dev build.

Dev builds from 2026-10-16 to 2026-10-18 put B on Toggle ROI mode
(``roibox_act``), and `Series.getOption` stored it. B now belongs to the ROI
mode tool (``useroi_act``). Left alone, a stored ``roibox_act = "B"`` puts B
on two actions, Qt reports the shortcut as ambiguous and fires neither. The
fix runs once at startup, before the shortcuts are built
(`settings_migrations.settle_legacy_roi_shortcut`).

The window tests press the real key, because ``QAction.trigger()`` cannot see
an ambiguous shortcut. Every one runs against an in-memory `DictSettingsStore`
set as the process-wide default, and checks that the session's `QSettings`
did not gain or lose the two keys.
"""
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from PyReconstruct.modules.backend import settings_migrations as M
from PyReconstruct.modules.backend.settings_store import (
    DictSettingsStore,
    set_default_settings_store,
)
from PyReconstruct.modules.gui.main.field_widget_5_mouse import POINTER, ROI_BOX

ORG = "KHLab"
APP = "PyReconstruct"
TOGGLE = M.ROI_TOGGLE_KEY
TOOL = M.ROI_TOOL_KEY


# --- the migration on its own -------------------------------------------------

def _store(**values):
    store = DictSettingsStore()
    for key, value in values.items():
        store.set_value(None, key, value)
    return store


def test_a_stored_b_on_the_toggle_is_cleared():
    store = _store(**{TOGGLE: "B"})
    assert M.settle_legacy_roi_shortcut(store) is True
    assert store.value(None, TOGGLE, str) == ""
    assert not store.contains(None, TOOL)


@pytest.mark.parametrize("stored", ["", "Shift+R", "Ctrl+B"])
def test_any_other_toggle_key_is_left_alone(stored):
    store = _store(**{TOGGLE: stored})
    assert M.settle_legacy_roi_shortcut(store) is False
    assert store.value(None, TOGGLE, str) == stored


def test_nothing_stored_writes_nothing():
    store = _store()
    assert M.settle_legacy_roi_shortcut(store) is False
    assert store._data.get(None, {}) == {}


def test_a_b_set_after_this_build_ran_is_the_users_choice():
    store = _store(**{TOGGLE: "B", TOOL: "Shift+B"})
    assert M.settle_legacy_roi_shortcut(store) is False
    assert store.value(None, TOGGLE, str) == "B"


def test_unreadable_settings_do_not_raise():
    class Broken(DictSettingsStore):
        def contains(self, code, key):
            raise OSError("read-only preferences")

    assert M.settle_legacy_roi_shortcut(Broken()) is False


# --- the real window and the real key -----------------------------------------

@pytest.fixture
def legacy_window(request, qapp, series_jser, main_window_dialogs):
    """A `MainWindow` built on settings an older Dev build left behind."""
    import sys

    from PyReconstruct.modules.gui.dialog.whats_new import current_version_str
    from PyReconstruct.modules.gui.main import MainWindow
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    session = QSettings(ORG, APP)
    session.setValue(WHATSNEW_KEY, current_version_str())
    before = {k: session.value(k) for k in (TOGGLE, TOOL)}

    store = _store(**{TOGGLE: request.param})
    set_default_settings_store(store)
    excepthook = sys.excepthook
    window = MainWindow(str(series_jser))
    window._captureListLayout = lambda: None
    try:
        yield window, store
    finally:
        sys.excepthook = excepthook
        window.series.modified = False
        window.close()
        window.deleteLater()
        set_default_settings_store(None)
        after = QSettings(ORG, APP)
        assert {k: after.value(k) for k in (TOGGLE, TOOL)} == before


@pytest.mark.parametrize("legacy_window", ["B", ""], indirect=True)
def test_pressing_b_picks_the_roi_mode_tool(legacy_window, qapp):
    window, store = legacy_window
    assert window.field.mouse_mode == POINTER
    assert store.value(None, TOGGLE, str) == ""
    assert store.value(None, TOOL, str) == "B"
    with_b = [
        a for a in window.findChildren(QAction)
        if "B" in [s.toString() for s in a.shortcuts()]
    ]
    assert with_b == [window.useroi_act]

    window.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(window.field, Qt.Key_B)
    qapp.processEvents()

    assert window.field.mouse_mode == ROI_BOX
