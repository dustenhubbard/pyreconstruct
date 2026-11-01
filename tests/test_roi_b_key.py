"""ROI mode has no default key, and B left behind by older Dev builds goes.

Dev builds put B on Toggle ROI mode (``roibox_act``, 2026-10-16 to 10-18) and
then on the ROI mode tool (``useroi_act``), and `Series.getOption` stored it.
A stored B is a copy of an old default, so it is cleared once per machine at
startup, before the shortcuts are built (`settings_migrations.clear_roi_b_key`).
A marker records that it ran, so a B the user sets later is kept.

The window tests press the real key. Every one runs against an in-memory
`DictSettingsStore` set as the process-wide default, and checks that the
session's `QSettings` did not gain or lose the keys.
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
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.gui.main.field_widget_5_mouse import POINTER

ORG = "KHLab"
APP = "PyReconstruct"
TOGGLE = M.ROI_TOGGLE_KEY
TOOL = M.ROI_TOOL_KEY
MARKER = M.ROI_B_KEY_CLEARED_KEY


@pytest.fixture(autouse=True)
def roi_mode_shown(monkeypatch):
    """ROI mode is hidden unless PYRECON_ROI_MODE=1; these tests drive it."""
    monkeypatch.setenv("PYRECON_ROI_MODE", "1")


def test_roi_mode_has_no_default_key():
    assert default_settings[TOGGLE] == ""
    assert default_settings[TOOL] == ""


# --- the migration on its own -------------------------------------------------

def _store(**values):
    store = DictSettingsStore()
    for key, value in values.items():
        store.set_value(None, key, value)
    return store


@pytest.mark.parametrize("stored", [
    {TOGGLE: "B"}, {TOOL: "B"}, {TOGGLE: "B", TOOL: "B"}, {TOOL: " b "},
])
def test_a_stored_b_on_either_action_is_cleared(stored):
    store = _store(**stored)
    assert M.clear_roi_b_key(store) is True
    for key in stored:
        assert store.value(None, key, str) == ""
    assert store.contains(None, MARKER)


@pytest.mark.parametrize("stored", ["", "Shift+B", "Ctrl+B", "R"])
def test_any_other_key_is_left_alone(stored):
    store = _store(**{TOGGLE: stored, TOOL: stored})
    assert M.clear_roi_b_key(store) is False
    assert store.value(None, TOGGLE, str) == stored
    assert store.value(None, TOOL, str) == stored
    assert store.contains(None, MARKER)


def test_nothing_stored_writes_only_the_marker():
    store = _store()
    assert M.clear_roi_b_key(store) is False
    assert set(store._data.get(None, {})) == {MARKER}


def test_a_b_set_after_it_ran_is_the_users_choice():
    store = _store()
    M.clear_roi_b_key(store)
    store.set_value(None, TOOL, "B")
    assert M.clear_roi_b_key(store) is False
    assert store.value(None, TOOL, str) == "B"


def test_a_failed_write_leaves_no_marker():
    class ReadOnly(DictSettingsStore):
        def set_value(self, code, key, value):
            raise OSError("read-only preferences")

    store = ReadOnly()
    DictSettingsStore.set_value(store, None, TOOL, "B")
    assert M.clear_roi_b_key(store) is False
    assert not store.contains(None, MARKER)
    assert store.value(None, TOOL, str) == "B"


def test_unreadable_settings_do_not_raise():
    class Broken(DictSettingsStore):
        def contains(self, code, key):
            raise OSError("read-only preferences")

    assert M.clear_roi_b_key(Broken()) is False


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
    before = {k: session.value(k) for k in (TOGGLE, TOOL, MARKER)}

    store = _store(**request.param)
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
        assert {k: after.value(k) for k in (TOGGLE, TOOL, MARKER)} == before


@pytest.mark.parametrize("legacy_window", [
    {TOGGLE: "B"}, {TOOL: "B"}, {TOGGLE: "B", TOOL: "B"}, {},
], indirect=True)
def test_pressing_b_picks_nothing(legacy_window, qapp):
    window, store = legacy_window
    assert window.field.mouse_mode == POINTER
    assert store.value(None, TOGGLE, str) == ""
    assert store.value(None, TOOL, str) == ""
    with_b = [
        a for a in window.findChildren(QAction)
        if "B" in [s.toString() for s in a.shortcuts()]
    ]
    assert with_b == []

    window.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(window.field, Qt.Key_B)
    qapp.processEvents()

    assert window.field.mouse_mode == POINTER
