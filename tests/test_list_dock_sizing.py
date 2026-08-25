"""Dock and float sizing for the five data lists.

Users on 1.21.0 stable with several lists and a 3D scene open reported new
lists spawning tiny. Measured on a 1600x1000 window before the fix: every
list docks into the left area, Qt splits the area evenly (1 list 858px wide,
3 lists ~180px each, floor 90x129), and a list dragged out to float KEEPS the
squeezed size. Three fixes land together and this file covers all three:

1. A new list tabs onto an existing docked list (``TableManager.newTable`` via
   ``_dockedAnchor``) instead of splitting the area, so every docked list gets
   the full area width. Floating and closed lists are not anchors.
2. The first float of a list raises it to at least 500x640
   (``DataTable._applyFloatSize``); later floats keep the user's size.
3. ``DataTable`` has a real minimum (200x250) docked or floating.

The main window here is a REAL QMainWindow -- dock areas, tabify, and
floating geometry are exactly what is under test, so the QWidget stub the
other list tests use is not enough. The field is the menu-building stub from
test_data_lists_real_widget so the widgets' createMenus paths run unmodified,
and the manager is the REAL TableManager: the tabify decision lives in it.

Geometry notes for maintainers: offscreen Qt lays docks out synchronously
after processEvents, but a settle() of a few event-loop passes is needed
after show/float/dock for sizes to be final. A single real list docks at its
own size hint (~256px on offscreen), NOT the full window -- so the docked
assertions are invariance ones (opening more lists never shrinks any list
below the single-list baseline) rather than absolute widths, which would
flake across styles and fonts.
"""

import pytest

from test_data_lists_real_widget import MenuStubField

pytestmark = pytest.mark.gui

LIST_TYPES = ["object", "section", "ztrace", "flag"]


def settle(qapp, rounds=5):
    """Let dock layout finish. One pass is not always enough offscreen."""
    for _ in range(rounds):
        qapp.processEvents()


@pytest.fixture
def dock_mainwindow(qapp, real_series, gui_dialogs):
    """A real QMainWindow the lists dock into, sized like a real session."""
    from PySide6.QtWidgets import QMainWindow, QWidget

    class DockMainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.series = real_series
            first = sorted(real_series.sections)[0]
            self.section = real_series.loadSection(first)
            self.field = MenuStubField(real_series, self.section)
            self.viewer = None
            self.modified = False

        def saveAllData(self):
            pass

        def seriesModified(self, modified=True):
            self.modified = modified

        def checkActions(self, *args, **kwargs):
            pass

        def changeSection(self, snum, save=False):
            pass

    window = DockMainWindow()
    window.setCentralWidget(QWidget())
    window.resize(1600, 1000)
    window.show()
    settle(qapp)
    yield window
    window.close()
    window.deleteLater()


@pytest.fixture
def manager(dock_mainwindow):
    from PyReconstruct.modules.backend.table.manager import TableManager

    return TableManager(
        dock_mainwindow.series, dock_mainwindow.section, {}, dock_mainwindow
    )


def open_list(manager, table_type, qapp):
    section = manager.section if table_type == "trace" else None
    manager.newTable(table_type, section=section)
    settle(qapp)
    return manager.tables[table_type][-1]


# --------------------------------------------------------------------------
# Fix 1: tabify instead of split
# --------------------------------------------------------------------------

def test_first_list_docks_plain(qapp, dock_mainwindow, manager):
    """With nothing to tab onto, the first list docks left, untabbed."""
    from PySide6.QtCore import Qt

    table = open_list(manager, "object", qapp)
    assert not table.isFloating()
    assert dock_mainwindow.dockWidgetArea(table) == Qt.LeftDockWidgetArea
    assert dock_mainwindow.tabifiedDockWidgets(table) == []
    assert table.width() >= table.MIN_WIDTH


def test_new_lists_tab_onto_the_first(qapp, dock_mainwindow, manager):
    """Lists two through four tab onto the first instead of splitting."""
    tables = [open_list(manager, tt, qapp) for tt in LIST_TYPES]
    first = tables[0]
    for later in tables[1:]:
        assert first in dock_mainwindow.tabifiedDockWidgets(later)


def test_more_lists_never_shrink_a_list(qapp, dock_mainwindow, manager):
    """The complaint itself: opening more lists used to squeeze all of them
    (~180px each at four open). Tabbed lists share the area, so every list
    keeps at least the width the first list got alone."""
    first = open_list(manager, LIST_TYPES[0], qapp)
    baseline = first.width()
    tables = [first] + [open_list(manager, tt, qapp) for tt in LIST_TYPES[1:]]
    for table in tables:
        assert table.width() >= baseline - 10, (
            f"{table.name} list shrank to {table.width()}px "
            f"(single-list baseline {baseline}px)"
        )


def test_six_lists_stay_usable(qapp, dock_mainwindow, manager):
    """Duplicates included -- the report was 'a bunch' of lists, not four."""
    first = open_list(manager, LIST_TYPES[0], qapp)
    baseline = first.width()
    types = LIST_TYPES[1:] + ["object", "section"]
    tables = [first] + [open_list(manager, tt, qapp) for tt in types]
    assert len(tables) == 6
    for table in tables:
        assert table.width() >= baseline - 10
        assert table.height() >= table.MIN_HEIGHT


def test_newest_list_is_the_raised_tab(qapp, dock_mainwindow, manager):
    """Opening a list must show that list, not bury it behind older tabs."""
    open_list(manager, "object", qapp)
    newest = open_list(manager, "section", qapp)
    assert newest.isVisible()
    # The raised tab is the one that is not obscured by a sibling.
    assert not newest.visibleRegion().isEmpty()


def test_floating_list_is_not_an_anchor(qapp, dock_mainwindow, manager):
    """A new list never tabs onto a floating one."""
    from PySide6.QtCore import Qt

    floater = open_list(manager, "object", qapp)
    floater.setFloating(True)
    settle(qapp)
    docked = open_list(manager, "section", qapp)
    assert not docked.isFloating()
    assert dock_mainwindow.dockWidgetArea(docked) == Qt.LeftDockWidgetArea
    assert floater not in dock_mainwindow.tabifiedDockWidgets(docked)


def test_closed_list_is_not_an_anchor(qapp, dock_mainwindow, manager):
    """Closing the only list, then opening one, docks it plainly."""
    first = open_list(manager, "object", qapp)
    first.close()
    settle(qapp)
    second = open_list(manager, "section", qapp)
    assert not second.isFloating()
    assert second.isVisible()
    assert second.width() >= second.MIN_WIDTH


def test_stub_mainwindows_without_tabify_still_work(qapp, real_series):
    """newTable on a plain-QWidget main window (other test suites, embedders)
    must not crash on the tabify path."""
    from PyReconstruct.modules.backend.table.manager import TableManager

    class Recorder:
        def __init__(self):
            self.docked = []

        def addDockWidget(self, area, widget):
            self.docked.append(widget)

    recorder = Recorder()
    manager = TableManager(real_series, None, {}, recorder)
    assert manager._dockedAnchor(None) is None


# --------------------------------------------------------------------------
# Fix 2: floating lists get a real size, the user's size wins after that
# --------------------------------------------------------------------------

def test_first_float_gets_default_size(qapp, dock_mainwindow, manager):
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    assert table.width() >= table.FLOAT_MIN_WIDTH
    assert table.height() >= table.FLOAT_MIN_HEIGHT


def test_squeezed_list_floats_usable(qapp, dock_mainwindow, manager):
    """The reported bug: drag a squeezed list out and it stayed squeezed.

    Squeeze is forced here by splitting by hand (the app no longer splits on
    its own): dock two lists side by side, shrink one, then float it."""
    from PySide6.QtCore import Qt

    left = open_list(manager, "object", qapp)
    right = open_list(manager, "section", qapp)
    # un-tab: put the second list beside the first, then squeeze it
    dock_mainwindow.splitDockWidget(left, right, Qt.Horizontal)
    dock_mainwindow.resizeDocks([right], [right.MIN_WIDTH], Qt.Horizontal)
    settle(qapp)
    assert right.width() < right.FLOAT_MIN_WIDTH  # genuinely squeezed
    right.setFloating(True)
    settle(qapp)
    assert right.width() >= right.FLOAT_MIN_WIDTH
    assert right.height() >= right.FLOAT_MIN_HEIGHT


def test_hand_set_float_size_survives_refloat(qapp, dock_mainwindow, manager):
    """After the first float, the size belongs to the user -- bigger or
    smaller than the default, refloating keeps it."""
    table = open_list(manager, "object", qapp)
    for user_size in ((760, 820), (320, 300)):
        table.setFloating(True)
        settle(qapp)
        table.resize(*user_size)
        settle(qapp)
        table.setFloating(False)
        settle(qapp)
        table.setFloating(True)
        settle(qapp)
        assert abs(table.width() - user_size[0]) <= 20, (
            f"hand-set width {user_size[0]} came back as {table.width()}"
        )
        assert abs(table.height() - user_size[1]) <= 20


def test_list_spawned_while_others_float(qapp, dock_mainwindow, manager):
    """The reported setup: several floating lists, then a new one spawns.
    It must dock at full width, and floating it must give a usable size."""
    for tt in ("object", "section", "ztrace"):
        floater = open_list(manager, tt, qapp)
        floater.setFloating(True)
        settle(qapp)
    newest = open_list(manager, "flag", qapp)
    assert not newest.isFloating()
    assert newest.width() >= newest.MIN_WIDTH
    newest.setFloating(True)
    settle(qapp)
    assert newest.width() >= newest.FLOAT_MIN_WIDTH
    assert newest.height() >= newest.FLOAT_MIN_HEIGHT


# --------------------------------------------------------------------------
# Fix 3: the minimum, docked or floating
# --------------------------------------------------------------------------

def test_minimum_is_set_on_every_list_type(qapp, dock_mainwindow, manager):
    for tt in LIST_TYPES:
        table = open_list(manager, tt, qapp)
        assert table.minimumWidth() == table.MIN_WIDTH
        assert table.minimumHeight() == table.MIN_HEIGHT


def test_floating_list_cannot_shrink_below_minimum(qapp, dock_mainwindow, manager):
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    table.resize(50, 50)
    settle(qapp)
    assert table.width() >= table.MIN_WIDTH
    assert table.height() >= table.MIN_HEIGHT


def test_docked_split_cannot_squeeze_below_minimum(qapp, dock_mainwindow, manager):
    """Even a hand-made side-by-side split respects the floor Qt used to
    ignore (old floor: 90px)."""
    from PySide6.QtCore import Qt

    left = open_list(manager, "object", qapp)
    right = open_list(manager, "section", qapp)
    dock_mainwindow.splitDockWidget(left, right, Qt.Horizontal)
    dock_mainwindow.resizeDocks([right], [10], Qt.Horizontal)
    settle(qapp)
    assert right.width() >= right.MIN_WIDTH


# --------------------------------------------------------------------------
# Layout round-trip
# --------------------------------------------------------------------------

def test_layout_state_roundtrip_keeps_lists_usable(qapp, dock_mainwindow, manager):
    """saveState/restoreState (what Qt session restore runs on) must not
    bring lists back tiny."""
    tables = [open_list(manager, tt, qapp) for tt in LIST_TYPES]
    state = dock_mainwindow.saveState()
    tables[1].setFloating(True)
    settle(qapp)
    assert dock_mainwindow.restoreState(state)
    settle(qapp)
    for table in tables:
        assert not table.isFloating()
        assert table.width() >= table.MIN_WIDTH


# --------------------------------------------------------------------------
# Floating lists are real windows (2026-08-25, his beta-2 report): a floated
# list used to be a Qt TOOL window, pinned above the main window forever.
# --------------------------------------------------------------------------

def test_floated_list_is_a_real_window_not_a_tool(qapp, dock_mainwindow, manager):
    from PySide6.QtCore import Qt

    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    flags = table.windowFlags()
    assert not (flags & Qt.Tool) == Qt.Tool
    assert flags & Qt.Window
    assert flags & Qt.WindowMinimizeButtonHint
    assert flags & Qt.WindowCloseButtonHint
    assert table.isVisible()


def test_floated_list_redocks_under_the_swapped_flags(qapp, dock_mainwindow, manager):
    from PySide6.QtCore import Qt

    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    table.setFloating(False)
    settle(qapp)
    assert not table.isFloating()
    assert dock_mainwindow.dockWidgetArea(table) == Qt.LeftDockWidgetArea
    assert table.isVisible()
    assert table.width() >= table.MIN_WIDTH


def test_dock_action_appears_only_while_floating(qapp, dock_mainwindow, manager):
    table = open_list(manager, "object", qapp)
    assert table._dock_action is None          # never floated: no action at all
    table.setFloating(True)
    settle(qapp)
    action = table._dock_action
    assert action is not None
    assert action.isVisible()
    assert action in table.main_widget.menuBar().actions()
    table.setFloating(False)
    settle(qapp)
    assert not action.isVisible()


def test_dock_action_redocks_the_list(qapp, dock_mainwindow, manager):
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    table._dock_action.trigger()
    settle(qapp)
    assert not table.isFloating()


def test_dock_action_survives_a_menubar_rebuild(qapp, dock_mainwindow, manager):
    """The object list rebuilds its menubar on column changes, which drops
    added actions; the next float must re-attach the action."""
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    table.main_widget.menuBar().clear()        # what a rebuild does to it
    table.setFloating(False)
    settle(qapp)
    table.setFloating(True)
    settle(qapp)
    assert table._dock_action in table.main_widget.menuBar().actions()
    assert table._dock_action.isVisible()


def test_refloat_keeps_hand_set_size_with_real_window_flags(qapp, dock_mainwindow, manager):
    """The flag swap must not break the size promise from the first fix."""
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    table.resize(720, 780)
    settle(qapp)
    table.setFloating(False)
    settle(qapp)
    table.setFloating(True)
    settle(qapp)
    assert abs(table.width() - 720) <= 20
    assert abs(table.height() - 780) <= 20


def test_close_while_floating_still_unregisters(qapp, dock_mainwindow, manager):
    """The native close button routes through closeEvent like the dock X."""
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    table.close()
    settle(qapp)
    assert table not in manager.tables["object"]


def test_float_from_tab_group_and_back(qapp, dock_mainwindow, manager):
    """Float a tabbed list, dock it back, and the tab group takes it again."""
    first = open_list(manager, "object", qapp)
    second = open_list(manager, "section", qapp)
    second.setFloating(True)
    settle(qapp)
    second.setFloating(False)
    settle(qapp)
    assert not second.isFloating()
    assert first in dock_mainwindow.tabifiedDockWidgets(second)


# --------------------------------------------------------------------------
# Tabs sit along the top of the list area (his call, 2026-08-25)
# --------------------------------------------------------------------------

def test_list_tabs_sit_on_top(qapp, dock_mainwindow, manager):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTabWidget

    open_list(manager, "object", qapp)
    open_list(manager, "section", qapp)
    assert dock_mainwindow.tabPosition(Qt.LeftDockWidgetArea) == QTabWidget.TabPosition.North
    assert dock_mainwindow.tabPosition(Qt.RightDockWidgetArea) == QTabWidget.TabPosition.North
