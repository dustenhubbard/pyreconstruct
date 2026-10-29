"""The menu bar at the top of the screen on macOS, in Dev builds only.

Every PyReconstruct window keeps its own in-window menu bar
(setNativeMenuBar(False)), so the top of the screen used to show only the app
menu Qt makes by itself. This adds one more bar: a parentless QMenuBar, which
Qt shows at the top of the screen for every window that has no native bar of
its own, and every window here has none. The in-window bars keep their rows.
They share Save and Save as with this bar, so those two now turn off at once
for the welcome series in both.

A row that is also in the in-window menu reuses the main window's own QAction,
never a copy, so a key still belongs to one action (Qt fires neither of two
actions that share a key) and a remap in the shortcuts dialog shows up in both
bars. createMenuBar and createContextMenus delete and remake those actions,
and a deleted action drops out of every menu it was in, so the bar is rebuilt
after each pass (MainWindow.createContextMenus, which also ends every
createMenuBar).

The new rows (About, Close series, Open recent series, the Window menu) are
this bar's own. Only Minimize has a key, and it gives Cmd+M up while a user
binding holds it (claimKeys, after every rebuild and every remap).

Every row gets an explicit menu role. Qt's default guesses from the text:
measured, "Options..." became Preferences, and "About this series..." took the
About slot even over an action set to AboutRole.
"""
import sys

import shiboken6
from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QMenuBar, QMessageBox

from PyReconstruct.modules.constants import build_flavor

Role = QAction.MenuRole

# the rows each menu reuses, by the main window attribute; None is a separator
FILE_ROWS = ["open_act", "close", None, "save_act", "saveas_act", "alloptions_act", "quit_act"]
NEW_SERIES_ROWS = ["newfromimages_act", "newfromzarr_act", "newfromxml_act", "newfromngzarr_act"]
EDIT_ROWS = ["undo_act", "redo_act", None, "cut_act", "copy_act", "paste_act", None, "selectall_act"]
HELP_ROWS = ["openwiki_act", "openclass_act", "shortcutshelp_act", "whatsnew_act", "submitissue_act", "about", "checkupdates_act"]

# the four rows macOS moves into the app menu; everything else is NoRole
APP_MENU_ROLES = {
    "about": Role.AboutRole,
    "checkupdates_act": Role.ApplicationSpecificRole,
    "alloptions_act": Role.PreferencesRole,
    "quit_act": Role.QuitRole,
}

MINIMIZE_KEY = QKeySequence("Ctrl+M")

_bar = None
_owner = None
_translator = None
# (row, key) for each new row that has a key of its own
_own_keys = []


def _isMac() -> bool:
    return sys.platform == "darwin"


def wanted() -> bool:
    """True in the macOS Dev app; the stable app and other platforms get no bar."""
    return _isMac() and build_flavor.is_dev_build()


def globalBar():
    """The bar, or None when this build has none."""
    return _bar if _alive(_bar) else None


def _alive(obj) -> bool:
    """False for None and for a wrapper whose Qt object is already deleted.

    The bar has no parent, so at quit Qt can delete it before its owner, and
    the owner's destroyed signal then reaches clear() with a dead bar.
    """
    return obj is not None and shiboken6.isValid(obj)


def clear():
    """Drop the bar and every row in it."""
    global _bar, _owner
    if _alive(_bar):
        _clearMenus(_bar)
        _bar.deleteLater()
    _bar = None
    _owner = None
    _own_keys.clear()


def rebuild(mainwindow):
    """Fill the bar from the main window's current actions."""
    global _bar, _owner
    if not wanted() or not _hasMenus(mainwindow):
        return None
    if not _alive(_bar):
        _bar = QMenuBar(None)
        _installSettingsLabel()
    if _owner is not mainwindow:
        _owner = mainwindow
        # a restarted window builds the next bar before the old one dies
        mainwindow.destroyed.connect(lambda *_, mw=mainwindow: _ownerGone(mw))
    _clearMenus(_bar)
    _own_keys.clear()

    file_menu = _bar.addMenu("File")
    new_menu = file_menu.addMenu("New series")
    _addRows(mainwindow, new_menu, NEW_SERIES_ROWS)
    _addRows(mainwindow, file_menu, FILE_ROWS[:1])
    _addRecentMenu(mainwindow, file_menu)
    _addRows(mainwindow, file_menu, FILE_ROWS[1:])
    # checkActions' welcome-series rule, applied now: it first runs on a
    # field click, and until then Save was on with no series open
    has_series = not mainwindow.series.isWelcomeSeries()
    mainwindow.save_act.setEnabled(has_series)
    mainwindow.saveas_act.setEnabled(has_series)

    _addRows(mainwindow, _bar.addMenu("Edit"), EDIT_ROWS)

    window_menu = _bar.addMenu("Window")
    _fillWindowMenu(mainwindow, window_menu)
    window_menu.aboutToShow.connect(lambda: _listWindows(mainwindow, window_menu))

    _addRows(mainwindow, _bar.addMenu("Help"), HELP_ROWS)
    claimKeys(mainwindow)
    return _bar


def claimKeys(mainwindow):
    """Give each new row its key only while no window action has that key.

    A user binding wins: two actions on one key make Qt fire neither, and a
    row key that starts a user sequence (Cmd+M under Cmd+M, A) fires on the
    first press, so a shared start counts as taken. The shortcuts dialog
    remaps in place (MainWindow.resetShortcuts) with no rebuild, so that
    calls this too.
    """
    if _owner is not mainwindow:
        return
    for row, key in _own_keys:
        if not _alive(row):
            continue
        taken = any(
            _overlaps(key, seq)
            for a in mainwindow.actions() for seq in a.shortcuts()
        )
        row.setShortcut(QKeySequence() if taken else key)


def _overlaps(key, seq) -> bool:
    """True when one sequence equals the other or starts it."""
    no = QKeySequence.SequenceMatch.NoMatch
    return key.matches(seq) != no or seq.matches(key) != no


def _hasMenus(mainwindow) -> bool:
    """False for a window that built only part of the menus (a test stub)."""
    return getattr(mainwindow, "series", None) is not None and all(
        isinstance(getattr(mainwindow, name, None), QAction)
        for name in ("close_act", "save_act", "saveas_act")
    )


def _ownerGone(mainwindow):
    if _owner is mainwindow:
        clear()


def _clearMenus(bar):
    for action in bar.actions():
        menu = action.menu()
        bar.removeAction(action)
        if _alive(menu):
            menu.deleteLater()


def _addRows(mainwindow, menu, names):
    for name in names:
        if name is None:
            menu.addSeparator()
            continue
        action = _newRow(mainwindow, menu, name)
        if action is None:
            action = getattr(mainwindow, name, None)
            if not isinstance(action, QAction):
                continue
            menu.addAction(action)
        action.setMenuRole(APP_MENU_ROLES.get(name, Role.NoRole))


def _newRow(mainwindow, menu, name):
    """The two rows that are not an existing action, or None."""
    if name == "about":
        return _row(menu, "About PyReconstruct", lambda: showAbout(mainwindow))
    if name == "close":
        # close_act stays enabled in the window for the welcome series;
        # here it is off, like Save, when no real series is open
        row = _row(menu, "Close series", mainwindow.close_act.trigger)
        row.setEnabled(not mainwindow.series.isWelcomeSeries())
        return row
    return None


def _row(menu, text, handler):
    action = menu.addAction(text)
    action.triggered.connect(handler)
    action.setMenuRole(Role.NoRole)
    return action


def _addRecentMenu(mainwindow, file_menu):
    """Open recent series, as rows of its own: one menu cannot sit in two bars.

    Read only: the window's own submenu already pruned the stored list.
    """
    recent = file_menu.addMenu("Open recent series")
    series = mainwindow.series
    for fp in series.getOption("recently_opened_series"):
        if fp != series.jser_fp:
            _row(recent, fp, lambda *_, fp=fp: mainwindow.openSeries(jser_fp=fp))
    if recent.actions():
        recent.addSeparator()
    _row(recent, "Clear recents", mainwindow.clearRecentSeries)


## --- the Window menu --------------------------------------------------------

def _activeWindow(mainwindow):
    return QApplication.activeWindow() or mainwindow


def _zoom(window):
    if window.isMaximized():
        window.showNormal()
    else:
        window.showMaximized()


def _openWindows():
    return [
        w for w in QApplication.topLevelWidgets()
        if w.isVisible() and w.windowTitle() and not isinstance(w, (QMenu, QMenuBar))
    ]


def _bringAllToFront(mainwindow):
    active = _activeWindow(mainwindow)
    for window in _openWindows():
        window.raise_()
    active.raise_()
    active.activateWindow()


def _show(window):
    if window.isMinimized():
        window.showNormal()
    window.raise_()
    window.activateWindow()


def _fillWindowMenu(mainwindow, menu):
    minimize = _row(menu, "Minimize", lambda: _activeWindow(mainwindow).showMinimized())
    _own_keys.append((minimize, MINIMIZE_KEY))
    _row(menu, "Zoom", lambda: _zoom(_activeWindow(mainwindow)))
    _row(menu, "Bring all to front", lambda: _bringAllToFront(mainwindow))
    menu.addSeparator()


def _listWindows(mainwindow, menu):
    """The open windows under the fixed rows, checked on the active one."""
    for action in menu.actions()[4:]:
        menu.removeAction(action)
        action.deleteLater()
    active = QApplication.activeWindow()
    for window in _openWindows():
        row = _row(menu, window.windowTitle(), lambda *_, w=window: _show(w))
        row.setCheckable(True)
        row.setChecked(window is active)


## --- the app menu -----------------------------------------------------------

def commitId():
    """The commit this build runs, or "unknown".

    repo_info has the git commit in a source checkout, but in a built app (and
    a plain pip install) its "commit" is the version. There the commit is the
    one setuptools-scm baked into PyReconstruct/_version.py, as "g" plus the
    hash; a checkout that never ran the build has no such file.
    """
    from PyReconstruct.modules.constants import repo_info

    if repo_info["branch"] not in ("PyReconstruct", "unknown"):
        return repo_info["commit"]
    try:
        from PyReconstruct._version import commit_id
    except ImportError:
        commit_id = None
    if not commit_id:
        return "unknown"
    return commit_id[1:] if commit_id.startswith("g") else commit_id


def aboutBox(mainwindow):
    """Name, version and commit, with a button that copies the commit."""
    from PyReconstruct.modules.datatypes.series_owner import app_display_name

    commit = commitId()
    box = QMessageBox(mainwindow)
    box.setWindowTitle("About PyReconstruct")
    box.setText(
        f"{app_display_name()}\n"
        f"Version {build_flavor.running_version()}\n"
        f"Commit {commit}"
    )
    copy = box.addButton("Copy commit", QMessageBox.ActionRole)
    copy.clicked.connect(lambda: QApplication.clipboard().setText(commit))
    box.addButton(QMessageBox.Ok)
    return box


def showAbout(mainwindow):
    aboutBox(mainwindow).exec()


class _SettingsLabel(QTranslator):
    """Qt labels the PreferencesRole row "Preferences..." whatever its text."""

    def translate(self, context, source, disambiguation=None, n=-1):
        if context == "MAC_APPLICATION_MENU" and source == "Preferences...":
            return "Settings…"
        return None


def _installSettingsLabel():
    global _translator
    if _translator is None:
        _translator = _SettingsLabel()
        QCoreApplication.installTranslator(_translator)
