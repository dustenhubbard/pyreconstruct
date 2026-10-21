"""ROI mode is held (2026-10-21): with PYRECON_ROI_MODE unset, a user sees no
ROI mode tool on the mouse palette, no View menu item, no shortcuts row, and B
picks nothing. Its two settings keys stay in the defaults, so a stored binding
is kept, and the startup migration writes nothing while it is hidden.

The tests that drive ROI mode set the switch (test_roi_box.py,
test_roi_legacy_shortcut.py).
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest

from PyReconstruct.modules.backend.settings_store import (
    DictSettingsStore,
    set_default_settings_store,
)
from PyReconstruct.modules.constants.roi_mode import ENV_SWITCH, roi_mode_enabled
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.gui.dialog.shortcuts import ShortcutsDialog
from PyReconstruct.modules.gui.main.field_widget_5_mouse import POINTER

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def roi_mode_unset(monkeypatch):
    monkeypatch.delenv(ENV_SWITCH, raising=False)


@pytest.mark.parametrize("value, shown", [
    (None, False), ("", False), ("0", False), ("true", False), ("1", True),
])
def test_only_1_shows_roi_mode(monkeypatch, value, shown):
    if value is not None:
        monkeypatch.setenv(ENV_SWITCH, value)
    assert roi_mode_enabled() is shown


def test_no_palette_tool_menu_item_or_action(main_window):
    assert "ROI mode" not in main_window.mouse_palette.mode_buttons
    assert not hasattr(main_window, "roibox_act")
    assert not hasattr(main_window, "useroi_act")
    texts = [a.text() for a in main_window.findChildren(QAction)]
    assert not [t for t in texts if "ROI mode" in t]


def test_b_picks_nothing(main_window, qapp):
    with_b = [
        a for a in main_window.findChildren(QAction)
        if "B" in [s.toString() for s in a.shortcuts()]
    ]
    assert with_b == []
    main_window.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(main_window.field, Qt.Key_B)
    qapp.processEvents()
    assert main_window.field.mouse_mode == POINTER


def test_shortcuts_dialog_has_no_roi_rows(main_window):
    dialog = ShortcutsDialog(main_window, main_window.series)
    try:
        assert "roibox_act" not in dialog.act_widgets
        assert "useroi_act" not in dialog.act_widgets
        labels = [w.text() for w in dialog.findChildren(QLabel)]
        assert not [t for t in labels if "ROI" in t]
    finally:
        dialog.deleteLater()


def test_settings_keys_stay_in_the_defaults():
    assert "roibox_act" in default_settings
    assert default_settings["useroi_act"] == "B"


def test_startup_migration_writes_nothing_while_hidden(main_window):
    store = DictSettingsStore()
    store.set_value(None, "roibox_act", "B")
    set_default_settings_store(store)
    try:
        main_window.settleLegacyRoiShortcutStartup()
        assert store.value(None, "roibox_act", str) == "B"
        assert not store.contains(None, "useroi_act")
    finally:
        set_default_settings_store(None)
