"""System, Light and Dark in the macOS Dev app; Default and Dark elsewhere.

The macOS Dev app offers macOS's own three appearance choices, all with the
native controls: System (stored "default") follows macOS, Light (stored
"light") and Dark (stored "qdark") force the scheme in-process with
QStyleHints.setColorScheme. The stable app, Windows and Linux keep Default
and Dark (qdarkstyle), and read "light" as "default".

Each test picks the build with the ``build`` fixture, so the suite covers both
on any platform. The offscreen platform the suite runs on ignores the color
scheme (it reports Unknown and draws Fusion), so the tests read the scheme
the app asks for; the native look itself is checked on the real screen (PR
captures). macOS's own setting is never touched.
"""
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

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


@pytest.fixture
def build(monkeypatch, restore_look):
    """Call with True for the macOS Dev app, False for every other build.

    Returns the list of themes setColorScheme was asked for."""
    asked = []
    real = appearance.setColorScheme

    def record(theme):
        asked.append(theme)
        real(theme)

    monkeypatch.setattr(appearance, "setColorScheme", record)

    def pick(mac_dev):
        monkeypatch.setattr(appearance, "native", lambda: mac_dev)
        return asked
    return pick


@pytest.fixture
def window(main_window, local_series_settings):
    local_series_settings(main_window)
    return main_window


def test_choices_per_build(build):
    build(True)
    assert appearance.choices() == [
        ("System", "default"), ("Light", "light"), ("Dark", "qdark")
    ]
    build(False)
    assert appearance.choices() == [("Default", "default"), ("Dark", "qdark")]
    assert appearance.choices(("default", "dark")) == [
        ("default", "default"), ("dark", "qdark")
    ]


def test_unknown_values_resolve_to_default(build):
    build(False)
    assert appearance.resolve("light") == "default"
    assert appearance.resolve("bogus") == "default"
    assert appearance.resolve(None) == "default"
    assert appearance.resolve("qdark") == "qdark"
    build(True)
    assert appearance.resolve("light") == "light"


def test_mac_dev_switches_live_with_native_controls(qapp, window, build):
    """Dark, Light and System switch in place with no sheet, each asking for
    its scheme; System hands the scheme back to the OS."""
    asked = build(True)

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


def test_other_builds_keep_qdarkstyle(qapp, window, build):
    asked = build(False)
    window.setTheme("qdark")
    assert "QWidget" in qapp.styleSheet()
    assert appearance.qdarkstyleApplied()
    window.setTheme("default")
    assert qapp.styleSheet() == ""
    assert not appearance.qdarkstyleApplied()
    assert asked == []


def test_stable_build_draws_a_stored_light_as_default(qapp, window, build):
    """A stable build that meets the Dev app's "light" draws the default look,
    and leaves the value stored for the Dev app."""
    build(False)
    window.series.setOption("theme", "light")
    window.setTheme(window.series.getOption("theme"))
    assert qapp.styleSheet() == ""
    assert not appearance.qdarkstyleApplied()
    assert window.series.getOption("theme") == "light"


def test_change_theme_dialog_offers_three_on_mac_dev(qapp, window, build, monkeypatch):
    from PyReconstruct.modules.gui.main import main_window as mw
    asked = build(True)
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
    build(True)
    dlg, w = _theme_widget(window.series)
    try:
        assert w.accept(close=False)
        assert [label for label, _ in w.responses[0]] == ["System", "Light", "Dark"]
        w.setOption([[("System", False), ("Light", True), ("Dark", False)]])
        assert window.series.getOption("theme") == "light"
    finally:
        dlg.deleteLater()


def test_options_on_stable_shows_a_stored_light_as_default(qapp, window, build):
    build(False)
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
    build(True)
    window.setTheme("light")
    light = _object_widths(qapp, window)
    window.setTheme("qdark")
    settle(qapp, rounds=6)
    dark = _object_widths(qapp, window)
    assert dark == light


def test_qdarkstyle_still_pads_columns(qapp, window, build):
    build(False)
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
