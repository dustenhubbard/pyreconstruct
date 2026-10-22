"""The new macOS look is held (2026-10-21): a macOS Dev build with
PYRECON_MAC_UI unset draws what it drew before. Courier New and the yellow
frame on the palette, the PNG and character tool icons, Default and Dark in
Options and Change theme, and a launch that neither changes the stored theme
nor forces a color scheme. With the switch set, the look is on.

The tests that drive the look set the switch (test_mac_system_fonts.py,
test_mac_appearance.py, test_mouse_palette_line_icons.py).
"""
import sys

import pytest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.backend.settings_store import (
    DictSettingsStore,
    set_default_settings_store,
)
from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.constants.mac_ui import ENV_SWITCH, mac_ui_enabled
from PyReconstruct.modules.gui.palette import line_icons
from PyReconstruct.modules.gui.palette.mouse_palette import MousePalette
from PyReconstruct.modules.gui.utils import appearance, fonts

from test_mac_appearance import restore_look  # noqa: F401  (fixture)
from test_mac_system_fonts import YELLOW, _button, _rgb
from test_mouse_palette_line_icons import DEV, STABLE, _assert_today


@pytest.fixture
def mac_dev(monkeypatch):
    """Run as a macOS Dev build with the switch unset."""
    monkeypatch.delenv(ENV_SWITCH, raising=False)
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(build_flavor, "running_version", lambda: DEV)


def _gates():
    return [fonts.macLook(), appearance.native(), line_icons.wanted()]


@pytest.mark.parametrize("platform, version, value, shown", [
    ("darwin", DEV, None, False),
    ("darwin", DEV, "", False),
    ("darwin", DEV, "0", False),
    ("darwin", DEV, "true", False),
    ("darwin", DEV, "1", True),
    ("darwin", STABLE, "1", False),
    ("linux", DEV, "1", False),
    ("win32", DEV, "1", False),
])
def test_only_1_on_mac_dev_shows_the_look(
        mac_dev, monkeypatch, platform, version, value, shown):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(build_flavor, "running_version", lambda: version)
    if value is not None:
        monkeypatch.setenv(ENV_SWITCH, value)
    assert mac_ui_enabled() is shown
    assert _gates() == [shown] * 3


def test_fonts_stay_courier_new(qapp, mac_dev):
    assert fonts.monoFamily() == "Courier New"
    assert fonts.uiFamily() == "Courier New"
    assert fonts.monoFont(12) == QFont("Courier New", 12, QFont.Bold)
    assert fonts.uiFont(16) == QFont("Courier New", 16, QFont.Bold)


def test_the_selected_trace_keeps_the_yellow_frame(qapp, mac_dev):
    button = _button(qapp)
    try:
        image = button.grab().toImage()
        assert _rgb(image, 0, 20) == YELLOW
        assert _rgb(image, 20, 0) == YELLOW
    finally:
        button.deleteLater()


@pytest.mark.gui
def test_the_tools_keep_their_pngs_and_characters(main_window, mac_dev, monkeypatch):
    monkeypatch.setenv("PYRECON_ROI_MODE", "1")
    _assert_today(MousePalette(main_window))


@pytest.fixture
def window(main_window, local_series_settings):
    local_series_settings(main_window)
    return main_window


def test_options_offers_default_and_dark(qapp, window, mac_dev):
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
    dlg = AllOptionsDialog(None, window.series)
    try:
        w = dlg.all_widgets["theme"]
        assert w.accept(close=False)
        assert [label for label, _ in w.responses[0]] == ["default", "dark"]
    finally:
        dlg.deleteLater()


def test_change_theme_offers_default_and_dark(qapp, window, mac_dev, monkeypatch):
    from PyReconstruct.modules.gui.main import main_window as mw
    seen = {}

    def cancel(parent, structure, title, *args, **kwargs):
        seen["labels"] = [label for label, _ in structure[1][0][1:]]
        return None, False

    monkeypatch.setattr(mw.QuickDialog, "get", staticmethod(cancel))
    window.setTheme()
    assert seen["labels"] == ["Default", "Dark"]


def _launch(series_jser):
    """Build a real `MainWindow`, menus and all, on the store already set."""
    from PyReconstruct.modules.gui.main import MainWindow

    excepthook = sys.excepthook
    window = MainWindow(str(series_jser))
    window._captureListLayout = lambda: None
    return window, excepthook


def _close(window, excepthook):
    sys.excepthook = excepthook
    window.series.modified = False
    window.close()
    window.deleteLater()
    QApplication.processEvents()


def test_a_hidden_launch_leaves_the_theme_then_a_shown_one_applies_it(
    qapp, series_jser, main_window_dialogs, mac_dev, restore_look,  # noqa: F811
    monkeypatch,
):
    """Settings a launch with the switch left (Light): a launch without it
    draws the default look, keeps "light" stored and forces no scheme; the
    next launch with the switch set draws Light again."""
    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.dialog.whats_new import current_version_str
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    asked = []
    monkeypatch.setattr(appearance, "setColorScheme", asked.append)
    QSettings("KHLab", "PyReconstruct").setValue(WHATSNEW_KEY, current_version_str())
    store = DictSettingsStore()
    store.set_value(None, "theme", "light")
    set_default_settings_store(store)
    try:
        window, hook = _launch(series_jser)
        try:
            assert qapp.styleSheet() == ""
            assert not appearance.qdarkstyleApplied()
        finally:
            _close(window, hook)
        assert store.value(None, "theme", str) == "light"
        assert asked == []

        monkeypatch.setenv(ENV_SWITCH, "1")
        window, hook = _launch(series_jser)
        _close(window, hook)
        assert store.value(None, "theme", str) == "light"
        assert asked == ["light"]
    finally:
        set_default_settings_store(None)
