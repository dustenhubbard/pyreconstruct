"""The native macOS menu bar at the top of the screen (Dev builds only).

A second, parentless QMenuBar. A row that is also in the in-window menu
reuses the main window's own action, so a key fires one action whichever bar
shows it, and a remap in the shortcuts dialog shows up in both. Every row
carries an explicit menu role: Qt's default guess from the text moved
"Options..." into the app menu and let "About this series..." take the About
slot. The in-window menu bar keeps its rows; on macOS Dev only, the shared
Save and Save as turn off at once for the welcome series.

Offscreen there is no native bar, so the global bar is an ordinary hidden
QMenuBar here; the tests read its rows, roles and wiring, not the Cocoa side.
"""
import sys
import types

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from conftest import menu_leaf_paths, same_action, submenu_at

from PyReconstruct.modules.constants import build_flavor, repo_info
from PyReconstruct.modules.gui.main import mac_menubar

pytestmark = pytest.mark.gui

Role = QAction.MenuRole


@pytest.fixture
def mac_dev(monkeypatch):
    """Pretend this is the macOS Dev app."""
    monkeypatch.setattr(mac_menubar, "_isMac", lambda: True)
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)


@pytest.fixture
def bar(main_window, mac_dev):
    """The global bar, built from the live window the way createMenuBar does."""
    main_window.createMenuBar()
    QApplication.processEvents()
    built = mac_menubar.globalBar()
    assert built is not None
    return built


# what each row is, in order, with the main window attribute it reuses
EXPECTED_ROWS = {
    "File > New series > From images...": "newfromimages_act",
    "File > New series > From scaled images...": "newfromzarr_act",
    "File > New series > From legacy .ser...": "newfromxml_act",
    "File > New series > From neuroglancer zarr...": "newfromngzarr_act",
    "File > Open series...": "open_act",
    "File > Close series": None,
    "File > Save": "save_act",
    "File > Save as...": "saveas_act",
    "File > Options...": "alloptions_act",
    "File > Quit": "quit_act",
    "Edit > Undo": "undo_act",
    "Edit > Redo": "redo_act",
    "Edit > Cut": "cut_act",
    "Edit > Copy": "copy_act",
    "Edit > Paste": "paste_act",
    "Edit > Select all traces": "selectall_act",
    "Window > Minimize": None,
    "Window > Zoom": None,
    "Window > Bring all to front": None,
    "Help > PyReconstruct user guide": "openwiki_act",
    "Help > Shortcuts list": "shortcutshelp_act",
    "Help > What's new?": "whatsnew_act",
    "Help > Report a bug...": "submitissue_act",
    "Help > About PyReconstruct": None,
    "Help > Check for updates...": "checkupdates_act",
}

APP_MENU_ROLES = {
    "File > Options...": Role.PreferencesRole,
    "File > Quit": Role.QuitRole,
    "Help > About PyReconstruct": Role.AboutRole,
    "Help > Check for updates...": Role.ApplicationSpecificRole,
}


def _rows(bar):
    """Every clickable row except the open-recent and open-window lists."""
    return {
        path: action for path, action in menu_leaf_paths(bar).items()
        if not path.startswith("File > Open recent series")
    }


# --- where the bar exists --------------------------------------------------

def test_no_bar_off_macos(main_window, monkeypatch):
    monkeypatch.setattr(mac_menubar, "_isMac", lambda: False)
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)
    mac_menubar.clear()
    main_window.createMenuBar()
    assert mac_menubar.globalBar() is None


def test_no_bar_in_the_stable_mac_app(main_window, monkeypatch):
    monkeypatch.setattr(mac_menubar, "_isMac", lambda: True)
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: False)
    mac_menubar.clear()
    main_window.createMenuBar()
    assert mac_menubar.globalBar() is None


def test_bar_is_parentless_and_the_window_bar_stays_in_the_window(main_window, bar):
    assert bar.parent() is None
    assert bar is not main_window.menubar
    assert main_window.menubar.isNativeMenuBar() is False
    assert [a.text() for a in main_window.menubar.actions()] == [
        "File", "Edit", "Series", "Section", "Lists", "Alignments", "View", "Help",
    ]


# --- rows and roles ---------------------------------------------------------

def test_menus_and_rows(bar):
    assert [a.text() for a in bar.actions()] == ["File", "Edit", "Window", "Help"]
    assert list(_rows(bar)) == list(EXPECTED_ROWS)
    assert submenu_at(bar, "File > Open recent series") is not None


def test_every_row_has_an_explicit_role(bar):
    for path, action in menu_leaf_paths(bar).items():
        want = APP_MENU_ROLES.get(path, Role.NoRole)
        assert action.menuRole() == want, path


def test_rows_reuse_the_window_actions(main_window, bar):
    for path, attr in EXPECTED_ROWS.items():
        if attr is None:
            continue
        assert same_action(_rows(bar)[path], getattr(main_window, attr)), path


def test_about_this_series_stays_out_of_the_bar(main_window, bar):
    rows = list(menu_leaf_paths(bar).values())
    assert not any(same_action(row, main_window.about_act) for row in rows)


def test_settings_label_for_the_preferences_slot(bar):
    assert QCoreApplication.translate(
        "MAC_APPLICATION_MENU", "Preferences...") == "Settings…"


# --- rebuilds ----------------------------------------------------------------

def test_rebuild_follows_the_window_menubar(main_window, bar, local_series_settings):
    local_series_settings(main_window)  # rebuilds both menus
    rebuilt = mac_menubar.globalBar()
    assert rebuilt is bar
    rows = _rows(rebuilt)
    assert list(rows) == list(EXPECTED_ROWS)
    assert all(shiboken6.isValid(a) for a in rows.values())
    assert same_action(rows["Edit > Undo"], main_window.undo_act)
    assert same_action(rows["Edit > Select all traces"], main_window.selectall_act)


# --- each row runs its existing handler --------------------------------------

def test_rows_trigger_the_existing_actions(main_window, bar):
    fired = []
    for path, attr in EXPECTED_ROWS.items():
        if attr is None:
            continue
        action = getattr(main_window, attr)
        action.triggered.connect(lambda *_, p=path: fired.append(p))
    for path in ("Edit > Select all traces", "Help > Report a bug..."):
        main_window.openWebsite = lambda *_: None
        _rows(bar)[path].trigger()
    assert fired == ["Edit > Select all traces", "Help > Report a bug..."]


def test_edit_copy_routes_to_a_focused_list(main_window, bar, monkeypatch):
    main_window.field.openList("object")
    table = main_window.field.table_manager.tables["object"][0]
    copied = []
    monkeypatch.setattr(table, "copy", lambda: copied.append("table"))
    monkeypatch.setattr(main_window, "getFocusWidget", lambda: table)
    _rows(bar)["Edit > Copy"].trigger()
    assert copied == ["table"]


def test_close_series_runs_close(main_window, bar, monkeypatch):
    calls = []
    main_window.close_act.triggered.connect(lambda *_: calls.append("close"))
    monkeypatch.setattr(main_window, "openSeries", lambda **kw: None)
    _rows(bar)["File > Close series"].trigger()
    assert calls == ["close"]


def test_open_recent_rows_open_the_series(main_window, mac_dev, tmp_path, monkeypatch):
    other = tmp_path / "other.jser"
    other.write_text("{}")
    main_window.series.setOption("recently_opened_series", [str(other)])
    main_window.createMenuBar()
    recent = submenu_at(mac_menubar.globalBar(), "File > Open recent series")
    opened = []
    monkeypatch.setattr(main_window, "openSeries", lambda **kw: opened.append(kw))
    rows = [a for a in recent.actions() if not a.isSeparator()]
    assert [a.text() for a in rows] == [str(other), "Clear recents"]
    assert all(a.menuRole() == Role.NoRole for a in rows)
    rows[0].trigger()
    assert opened == [{"jser_fp": str(other)}]


def test_about_box_names_the_build(main_window, bar):
    box = mac_menubar.aboutBox(main_window)
    # a macOS message box has no title bar text, so the name is in the body
    assert box.text().startswith("PyReconstruct")
    assert build_flavor.running_version() in box.text()
    assert sorted(b.text() for b in box.buttons()) == ["Copy commit", "OK"]
    box.deleteLater()


def _about_commit(main_window):
    """The Commit line of the About box, and what Copy commit copies."""
    box = mac_menubar.aboutBox(main_window)
    line = box.text().splitlines()[-1]
    QApplication.clipboard().clear()
    next(b for b in box.buttons() if b.text() == "Copy commit").click()
    copied = QApplication.clipboard().text()
    box.deleteLater()
    return line, copied


def test_about_box_shows_the_baked_commit_in_a_built_app(main_window, bar, monkeypatch):
    # a built app: repo_info's "commit" is the version, _version.py has the commit
    version = "1.26.0.dev202610201708+g0c2734b59"
    monkeypatch.setitem(repo_info, "branch", "PyReconstruct")
    monkeypatch.setitem(repo_info, "commit", version)
    baked = types.ModuleType("PyReconstruct._version")
    baked.version = version
    baked.commit_id = "g0c2734b59"
    monkeypatch.setitem(sys.modules, "PyReconstruct._version", baked)
    assert _about_commit(main_window) == ("Commit 0c2734b59", "0c2734b59")


def test_about_box_with_no_version_file(main_window, bar, monkeypatch):
    # a source checkout without git or a build: no _version.py to read
    monkeypatch.setitem(repo_info, "branch", "unknown")
    monkeypatch.setitem(repo_info, "commit", "unknown")
    monkeypatch.setitem(sys.modules, "PyReconstruct._version", None)
    assert _about_commit(main_window) == ("Commit unknown", "unknown")


def test_about_box_in_a_git_checkout(main_window, bar, monkeypatch):
    monkeypatch.setitem(repo_info, "branch", "main")
    monkeypatch.setitem(repo_info, "commit", "0c2734b")
    monkeypatch.setitem(sys.modules, "PyReconstruct._version", None)
    assert _about_commit(main_window) == ("Commit 0c2734b", "0c2734b")


# --- no series ---------------------------------------------------------------

def test_series_rows_are_off_with_no_series(main_window, bar):
    rows = _rows(bar)
    for path in ("File > Save", "File > Save as...", "File > Close series"):
        assert rows[path].isEnabled(), path

    main_window.series.modified = False
    main_window.openWelcomeSeries()
    QApplication.processEvents()
    assert main_window.series.isWelcomeSeries()
    rows = _rows(mac_menubar.globalBar())
    for path in ("File > Save", "File > Save as...", "File > Close series"):
        assert not rows[path].isEnabled(), path
    assert rows["File > Open series..."].isEnabled()


# --- the Window menu -----------------------------------------------------------

def test_window_menu_lists_the_open_windows(main_window, bar):
    window_menu = submenu_at(bar, "Window")
    window_menu.aboutToShow.emit()
    titles = [a.text() for a in window_menu.actions() if not a.isSeparator()]
    assert titles[:3] == ["Minimize", "Zoom", "Bring all to front"]
    assert main_window.windowTitle() in titles[3:]


def test_minimize_acts_on_the_active_window(main_window, bar, monkeypatch):
    calls = []
    monkeypatch.setattr(mac_menubar, "_activeWindow", lambda mw: main_window)
    monkeypatch.setattr(main_window, "showMinimized", lambda: calls.append("min"))
    _rows(bar)["Window > Minimize"].trigger()
    assert calls == ["min"]


def test_minimize_takes_cmd_m_only_when_free(main_window, bar, local_series_settings):
    assert _rows(bar)["Window > Minimize"].shortcut() == QKeySequence("Ctrl+M")
    series = local_series_settings(main_window)
    series.setOption("homeview_act", "Ctrl+M")
    main_window.createMenuBar()
    assert mac_menubar.globalBar() is bar
    assert _rows(bar)["Window > Minimize"].shortcut().isEmpty()


def _own_rows_with_keys(main_window, bar):
    """The bar's new rows that have a key: not one of the window's actions."""
    window_actions = list(main_window.actions())
    return {
        path: action for path, action in _rows(bar).items()
        if not action.shortcut().isEmpty()
        and not any(same_action(action, a) for a in window_actions)
    }


def test_a_remap_takes_the_bar_keys_at_once(main_window, bar, local_series_settings):
    """The shortcuts dialog remaps through resetShortcuts, with no rebuild."""
    local_series_settings(main_window)
    bar = mac_menubar.globalBar()
    own = _own_rows_with_keys(main_window, bar)
    assert list(own) == ["Window > Minimize"]
    first = main_window.homeview_act.shortcut().toString()
    for path, row in own.items():
        key = row.shortcut()
        main_window.resetShortcuts({"homeview_act": key.toString()})
        assert row.shortcut().isEmpty(), path
        assert main_window.homeview_act.shortcut() == key
        # the user's key moves on: the row has it back
        main_window.resetShortcuts({"homeview_act": first})
        assert row.shortcut() == key, path


# --- one trigger per key -------------------------------------------------------

def test_no_two_actions_share_a_key(main_window, bar):
    owners = {}
    actions = list(main_window.actions()) + list(menu_leaf_paths(bar).values())
    for action in actions:
        if not action.isEnabled() and not action.isVisible():
            continue
        for seq in action.shortcuts():
            key = seq.toString()
            if key in owners:
                assert same_action(owners[key], action), key
            owners[key] = action


@pytest.mark.parametrize("attr,key", [
    ("selectall_act", Qt.Key_A),
    ("copy_act", Qt.Key_C),
    ("undo_act", Qt.Key_Z),
])
def test_one_press_fires_once(main_window, bar, qapp, attr, key):
    action = getattr(main_window, attr)
    assert action.shortcut() == QKeySequence(Qt.ControlModifier | key)
    fired = []
    action.triggered.connect(lambda *_: fired.append(attr))
    main_window.activateWindow()
    main_window.field.setFocus()
    qapp.processEvents()
    try:
        QTest.keyClick(main_window.field, key, Qt.ControlModifier)
        qapp.processEvents()
    finally:
        QTest.keyRelease(main_window, Qt.Key_Control)
        qapp.processEvents()
    assert fired == [attr]
