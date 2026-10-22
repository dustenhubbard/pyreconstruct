"""System, Light and Dark in the macOS Dev app; Default and Dark elsewhere.

The macOS Dev app offers macOS's own three appearance choices, all with the
native controls: System (stored "default") follows macOS, Light (stored
"light") and Dark (stored "qdark") force the scheme in-process with
QStyleHints.setColorScheme. The stable app, Windows and Linux keep Default
and Dark (qdarkstyle), and read "light" as "default". The tests set
PYRECON_MAC_UI=1; test_mac_ui_hidden.py covers the switch unset.
"""
import sys

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.gui.utils import appearance

from test_list_dock_sizing import settle


@pytest.fixture
def restore_look(qapp):
    """Leave the app's sheet, palette and scheme as the test found them."""
    hints = QApplication.styleHints()
    sheet, scheme = qapp.styleSheet(), hints.colorScheme()
    yield
    qapp.setStyleSheet(sheet)
    qapp.setProperty(appearance.QDARKSTYLE_PROPERTY, False)
    hints.unsetColorScheme()
    qapp.setPalette(qapp.style().standardPalette())
    assert hints.colorScheme() == scheme


MAC_DEV = ("darwin", True)
# every other pair of platform and build: these keep Default and Dark
OTHER_BUILDS = [
    ("darwin", False), ("win32", True), ("win32", False),
    ("linux", True), ("linux", False),
]


@pytest.fixture
def build(monkeypatch, restore_look):
    """Call with (platform, dev) to run as that build; native() decides.

    Returns the list of themes setColorScheme was asked for."""
    asked = []
    real = appearance.setColorScheme

    def record(theme):
        asked.append(theme)
        real(theme)

    monkeypatch.setattr(appearance, "setColorScheme", record)
    monkeypatch.delenv("PYRECON_APP_NAME", raising=False)
    monkeypatch.setenv("PYRECON_MAC_UI", "1")

    def pick(platform, dev):
        monkeypatch.setattr(sys, "platform", platform)
        version = "1.25.0.dev5+g0123abc" if dev else "1.24.0"
        monkeypatch.setattr(build_flavor, "running_version", lambda: version)
        return asked
    return pick


@pytest.fixture
def window(main_window, local_series_settings):
    local_series_settings(main_window)
    return main_window


def test_mac_dev_offers_three(build):
    build(*MAC_DEV)
    assert appearance.native()
    assert appearance.choices() == [
        ("System", "default"), ("Light", "light"), ("Dark", "qdark")
    ]


@pytest.mark.parametrize("platform, dev", OTHER_BUILDS)
def test_other_builds_offer_default_and_dark(build, platform, dev):
    build(platform, dev)
    assert not appearance.native()
    assert appearance.choices() == [("Default", "default"), ("Dark", "qdark")]
    assert appearance.choices(("default", "dark")) == [
        ("default", "default"), ("dark", "qdark")
    ]


@pytest.mark.parametrize("platform, dev", OTHER_BUILDS)
def test_unknown_values_resolve_to_default(build, platform, dev):
    build(platform, dev)
    assert appearance.resolve("light") == "default"
    assert appearance.resolve("bogus") == "default"
    assert appearance.resolve(None) == "default"
    assert appearance.resolve("qdark") == "qdark"
    build(*MAC_DEV)
    assert appearance.resolve("light") == "light"


def test_mac_dev_switches_live_with_native_controls(qapp, window, build):
    """Dark, Light and System switch in place with no sheet, each asking for
    its scheme; System hands the scheme back to the OS."""
    asked = build(*MAC_DEV)

    window.setTheme("qdark")
    assert asked == ["qdark"]
    assert qapp.styleSheet() == ""
    assert not appearance.qdarkstyleApplied()
    assert window.series.getOption("theme") == "qdark"

    window.setTheme("light")
    assert asked == ["qdark", "light"]
    assert qapp.styleSheet() == ""
    assert window.series.getOption("theme") == "light"

    window.setTheme("default")
    assert asked == ["qdark", "light", "default"]
    assert window.series.getOption("theme") == "default"


def test_set_color_scheme_forces_and_releases(qapp, restore_look, monkeypatch):
    """Light and Dark force the scheme; System unsets it."""
    hints = QApplication.styleHints()
    calls = []
    monkeypatch.setattr(type(hints), "setColorScheme",
                        lambda self, s: calls.append(s))
    monkeypatch.setattr(type(hints), "unsetColorScheme",
                        lambda self: calls.append("unset"))
    appearance.setColorScheme("light")
    appearance.setColorScheme("qdark")
    appearance.setColorScheme("default")
    assert calls == [Qt.ColorScheme.Light, Qt.ColorScheme.Dark, "unset"]


@pytest.mark.parametrize("platform, dev", OTHER_BUILDS)
def test_other_builds_keep_qdarkstyle(qapp, window, build, platform, dev):
    asked = build(platform, dev)
    window.setTheme("qdark")
    assert "QWidget" in qapp.styleSheet()
    assert appearance.qdarkstyleApplied()
    window.setTheme("default")
    assert qapp.styleSheet() == ""
    assert not appearance.qdarkstyleApplied()
    assert asked == []


@pytest.mark.parametrize("platform, dev", OTHER_BUILDS)
def test_stable_build_draws_a_stored_light_as_default(
        qapp, window, build, platform, dev):
    """A build that meets the macOS Dev app's "light" draws the default look,
    and leaves the value stored for the Dev app."""
    build(platform, dev)
    window.series.setOption("theme", "light")
    window.setTheme(window.series.getOption("theme"))
    assert qapp.styleSheet() == ""
    assert not appearance.qdarkstyleApplied()
    assert window.series.getOption("theme") == "light"


def test_change_theme_dialog_offers_three_on_mac_dev(qapp, window, build, monkeypatch):
    from PyReconstruct.modules.gui.main import main_window as mw
    asked = build(*MAC_DEV)
    seen = {}

    def pick_light(parent, structure, title, *args, **kwargs):
        radios = structure[1][0][1:]
        seen["labels"] = [label for label, _ in radios]
        seen["checked"] = [label for label, on in radios if on]
        return ([[(label, label == "Light") for label, _ in radios]], True)

    monkeypatch.setattr(mw.QuickDialog, "get", staticmethod(pick_light))
    window.setTheme()
    assert seen["labels"] == ["System", "Light", "Dark"]
    assert seen["checked"] == ["System"]
    assert window.series.getOption("theme") == "light"
    assert asked == ["light"]


def _theme_widget(series):
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
    dlg = AllOptionsDialog(None, series)
    return dlg, dlg.all_widgets["theme"]


def test_options_offers_three_on_mac_dev_and_stores_light(qapp, window, build):
    build(*MAC_DEV)
    dlg, w = _theme_widget(window.series)
    try:
        assert w.accept(close=False)
        assert [label for label, _ in w.responses[0]] == ["System", "Light", "Dark"]
        w.setOption([[("System", False), ("Light", True), ("Dark", False)]])
        assert window.series.getOption("theme") == "light"
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("platform, dev", OTHER_BUILDS)
def test_options_on_stable_shows_a_stored_light_as_default(
        qapp, window, build, platform, dev):
    build(platform, dev)
    window.series.setOption("theme", "light")
    dlg, w = _theme_widget(window.series)
    try:
        assert w.accept(close=False)
        assert w.responses[0] == [("default", True), ("dark", False)]
    finally:
        dlg.deleteLater()


def _object_widths(qapp, window):
    mgr = window.field.table_manager
    mgr.newTable("object")
    settle(qapp)
    view = mgr.tables["object"][-1].table
    return [view.columnWidth(c) for c in range(view.model().columnCount())]


def test_native_dark_gets_no_qdarkstyle_padding(qapp, window, build):
    """Native Dark is stored as "qdark" but draws no qdarkstyle cell padding,
    so the lists measure as in Light."""
    build(*MAC_DEV)
    window.setTheme("light")
    light = _object_widths(qapp, window)
    window.setTheme("qdark")
    settle(qapp, rounds=6)
    dark = _object_widths(qapp, window)
    assert dark == light


def test_qdarkstyle_still_pads_columns(qapp, window, build):
    build("darwin", False)
    window.setTheme("qdark")
    settle(qapp, rounds=6)
    mgr = window.field.table_manager
    mgr.newTable("object")
    settle(qapp)
    view = mgr.tables["object"][-1].table
    widths = [view.columnWidth(c) for c in range(view.model().columnCount())]
    view.resizeColumnsToContents()
    assert [view.columnWidth(c) for c in range(len(widths))] == widths
    QApplication.instance().setProperty(appearance.QDARKSTYLE_PROPERTY, False)
    view.resizeColumnsToContents()
    unpadded = [view.columnWidth(c) for c in range(len(widths))]
    assert [w - 8 for w in widths] == unpadded
