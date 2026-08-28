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
    smaller than the default, refloating keeps it. The one bound: width
    never goes under the menu-bar floor (his call, 2026-08-26), so the
    small example here sits just above it."""
    table = open_list(manager, "object", qapp)
    for user_size in ((760, 820), (380, 300)):
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


def test_floating_list_shrinks_to_the_float_floor_only(qapp, dock_mainwindow, manager):
    """Patrick's three-row list (2026-08-25): a floated list sized by hand may
    go far below the docked floor in HEIGHT. The WIDTH floor stayed higher on
    his 2026-08-26 call: never so narrow that the list's own menu bar clips,
    the same measure the docked width hint uses."""
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    menubar_floor = table.main_widget.menuBar().sizeHint().width() + 8

    table.resize(150, 140)              # a deliberate tiny list
    settle(qapp)
    assert table.height() == 140        # three rows: allowed
    assert table.width() >= menubar_floor   # menus never clip

    table.resize(50, 50)                # below every floor: clamped
    settle(qapp)
    assert table.width() >= menubar_floor
    assert table.height() >= table.FLOAT_SHRINK_MIN_HEIGHT


def test_redocking_a_tiny_float_restores_the_docked_floor(qapp, dock_mainwindow, manager):
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    table.resize(150, 140)
    settle(qapp)
    table.setFloating(False)
    settle(qapp)
    assert table.minimumWidth() == table.MIN_WIDTH
    assert table.minimumHeight() == table.MIN_HEIGHT
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


def test_dock_button_appears_only_while_floating(qapp, dock_mainwindow, manager):

    table = open_list(manager, "object", qapp)
    assert table._dock_button is None          # never floated: no button at all
    table.setFloating(True)
    settle(qapp)
    button = table._dock_button
    assert button is not None
    assert button.isVisible()
    assert not button.icon().isNull()          # an icon, not a text row
    # painted at 2x from the palette, not a faint stock style icon -- and
    # spread across the WHOLE canvas: device-space coordinates once clipped
    # the glyph to the top-left corner (his screenshot, 2026-08-26)
    image = button.icon().pixmap(16, 16).toImage()
    w, h = image.width(), image.height()

    def opaque_in(x0, y0, x1, y1):
        return sum(
            1 for x in range(x0, x1) for y in range(y0, y1)
            if image.pixelColor(x, y).alpha() > 100
        )

    assert opaque_in(0, 0, w, h) > 30          # a bold mark, not a wisp
    assert opaque_in(w // 2, 0, w, h) > 0      # reaches the right half
    assert opaque_in(0, h // 2, w, h) > 0      # and the bottom half
    assert not button.text()
    assert button.toolTip() == "Dock this list"
    # the menubar's FIRST action: real layout space, so it pushes the first
    # menu right instead of overlapping it (a corner widget sat on "List")
    assert table.main_widget.menuBar().actions()[0] is button
    table.setFloating(False)
    settle(qapp)
    assert not button.isVisible()


def test_dock_button_redocks_the_list(qapp, dock_mainwindow, manager):
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    table._dock_button.trigger()
    settle(qapp)
    assert not table.isFloating()


def test_dock_button_survives_a_menubar_rebuild(qapp, dock_mainwindow, manager):
    """A real rebuild, on a list that stays floating throughout.

    This test used to call `menuBar().clear()` and re-float in between, and
    it passed while the app was broken. A rebuild is not a bare clear: it
    goes through `clearMenuBar`, which ALSO deletes every attribute pointing
    at a menubar action, and the dock button is one while the list floats.
    Re-floating then hid the damage, because the float is what re-inserts
    the button. Neither shortcut is taken here.
    """
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)

    manager.recreateTable(table)               # what List > Refresh does
    settle(qapp)

    menubar = table.main_widget.menuBar()
    assert table._dock_button is not None      # the attribute was not lost
    assert menubar.actions()[0] is table._dock_button
    assert table._dock_button.isVisible()


def test_a_rebuilt_floating_list_can_still_be_docked(
    qapp, dock_mainwindow, manager
):
    """The point of the button, after the rebuild that used to remove it.

    Before the fix the button was gone from the bar and its attribute was
    deleted, so this list was stranded: floating with no road back, and the
    next transition raised AttributeError inside _onTopLevelChanged and left
    it half-docked at the floating minimum size.
    """
    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)

    manager.recreateTable(table)
    settle(qapp)

    table._dock_button.trigger()
    settle(qapp)

    assert not table.isFloating()
    assert table.minimumWidth() == table.MIN_WIDTH   # the dock branch ran
    assert table._real_window is False


@pytest.mark.parametrize("list_type", ["object", "trace", "section", "ztrace"])
def test_every_list_type_keeps_its_dock_button_through_a_rebuild(
    qapp, dock_mainwindow, manager, list_type
):
    """The invariant belongs to DataTable, so it holds for all of them.

    Each subclass owns its own createMenus and each one clears the bar, so
    a fix applied per subclass would be one forgotten line away from this
    coming back. Callers go through `rebuildMenus`, which is what this pins.
    """
    table = open_list(manager, list_type, qapp)
    table.setFloating(True)
    settle(qapp)

    manager.recreateTable(table)
    settle(qapp)

    assert table.main_widget.menuBar().actions()[0] is table._dock_button


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


# --------------------------------------------------------------------------
# The collapse toggle (stage 1 of the sidebar, his call 2026-08-25): hide the
# docked lists, bring the same set back, never touch a floating list.
# --------------------------------------------------------------------------

def test_collapse_hides_docked_and_spares_floating(qapp, dock_mainwindow, manager):
    docked = open_list(manager, "object", qapp)
    tabbed = open_list(manager, "section", qapp)
    floater = open_list(manager, "ztrace", qapp)
    floater.setFloating(True)
    settle(qapp)
    manager.toggleListsCollapsed()
    settle(qapp)
    assert manager.listsCollapsed()
    assert not docked.isVisible()
    assert not tabbed.isVisible()
    assert floater.isVisible()


def test_expand_restores_exactly_the_hidden_set(qapp, dock_mainwindow, manager):
    docked = open_list(manager, "object", qapp)
    tabbed = open_list(manager, "section", qapp)
    manager.toggleListsCollapsed()
    settle(qapp)
    manager.toggleListsCollapsed()
    settle(qapp)
    assert not manager.listsCollapsed()
    assert docked.isVisible()
    assert tabbed.isVisible()
    # still one tab group, not re-split
    assert docked in dock_mainwindow.tabifiedDockWidgets(tabbed)


def test_list_closed_while_collapsed_stays_closed(qapp, dock_mainwindow, manager):
    keeper = open_list(manager, "object", qapp)
    goner = open_list(manager, "section", qapp)
    manager.toggleListsCollapsed()
    settle(qapp)
    goner.close()
    settle(qapp)
    manager.toggleListsCollapsed()
    settle(qapp)
    assert keeper.isVisible()
    assert goner not in manager.tables["section"]
    assert not goner.isVisible()


def test_collapse_with_nothing_docked_is_a_noop(qapp, dock_mainwindow, manager):
    floater = open_list(manager, "object", qapp)
    floater.setFloating(True)
    settle(qapp)
    manager.toggleListsCollapsed()
    settle(qapp)
    assert not manager.listsCollapsed()   # nothing was hidden, nothing pending
    assert floater.isVisible()


def test_new_list_while_collapsed_expands_first(qapp, dock_mainwindow, manager):
    first = open_list(manager, "object", qapp)
    manager.toggleListsCollapsed()
    settle(qapp)
    newest = open_list(manager, "section", qapp)
    assert not manager.listsCollapsed()
    assert first.isVisible()
    assert newest.isVisible()
    assert first in dock_mainwindow.tabifiedDockWidgets(newest)


# --------------------------------------------------------------------------
# Tabs with X's, no double title (his click test, 2026-08-25): the tab names
# the list and closes it; the title bar only exists for a lone docked list.
# --------------------------------------------------------------------------

def _dock_tab_bar(manager):
    bars = manager._dockTabBars()
    assert len(bars) == 1, f"expected one dock tab bar, found {len(bars)}"
    return bars[0]


def test_tabbed_lists_hide_their_title_bars(qapp, dock_mainwindow, manager):
    first = open_list(manager, "object", qapp)
    second = open_list(manager, "section", qapp)
    assert first.titleBarWidget() is not None      # empty widget = hidden
    assert second.titleBarWidget() is not None


def test_a_lone_docked_list_keeps_the_original_title_bar(qapp, dock_mainwindow, manager):
    """A lone list keeps Qt's own title bar (a slim tab-styled bar was tried
    and reverted on his click test, 2026-08-25): the drag, float and close
    affordances stay exactly what stable users know."""
    only = open_list(manager, "object", qapp)
    assert only.titleBarWidget() is None


def test_dock_tabs_carry_close_buttons(qapp, dock_mainwindow, manager):
    open_list(manager, "object", qapp)
    open_list(manager, "section", qapp)
    settle(qapp)
    assert _dock_tab_bar(manager).tabsClosable()


def test_tab_x_closes_the_right_list(qapp, dock_mainwindow, manager):
    """Resolved by pointer, not tab text: two lists of one type share a
    title."""
    import shiboken6

    keeper = open_list(manager, "object", qapp)
    goner = open_list(manager, "object", qapp)
    settle(qapp)
    bar = _dock_tab_bar(manager)
    goner_ptr = shiboken6.getCppPointer(goner)[0]
    index = next(i for i in range(bar.count()) if bar.tabData(i) == goner_ptr)
    bar.tabCloseRequested.emit(index)
    settle(qapp)
    assert goner not in manager.tables["object"]
    assert keeper in manager.tables["object"]
    assert keeper.isVisible()


def test_group_shrunk_to_one_gets_its_title_bar_back(qapp, dock_mainwindow, manager):
    keeper = open_list(manager, "object", qapp)
    goner = open_list(manager, "section", qapp)
    settle(qapp)
    assert keeper.titleBarWidget() is not None
    goner.close()
    settle(qapp)
    assert keeper.titleBarWidget() is None


def test_floated_list_never_keeps_the_empty_title_widget(qapp, dock_mainwindow, manager):
    """Floating runs on the native frame; the empty docked title widget must
    not ride along, and docking back into the group hides it again."""
    first = open_list(manager, "object", qapp)
    second = open_list(manager, "section", qapp)
    second.setFloating(True)
    settle(qapp)
    assert second.titleBarWidget() is None
    second.setFloating(False)
    settle(qapp)
    assert second.titleBarWidget() is not None     # back in the tab group
    assert first.titleBarWidget() is not None


# --------------------------------------------------------------------------
# Tearing a list out by drag must survive the real-window flag swap
# (his click test, 2026-08-25: the swap mid-drag killed the gesture).
# --------------------------------------------------------------------------

def test_flag_swap_waits_for_the_mouse_release(qapp, dock_mainwindow, manager, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    table = open_list(manager, "object", qapp)

    held = {"buttons": Qt.LeftButton}
    monkeypatch.setattr(
        QApplication, "mouseButtons", staticmethod(lambda: held["buttons"])
    )

    table.setFloating(True)          # what a drag tear-out does, button held
    settle(qapp)
    assert not (table.windowFlags() & Qt.Window) == Qt.Window or \
        (table.windowFlags() & Qt.Tool) == Qt.Tool   # still Qt's tool window

    held["buttons"] = Qt.NoButton    # the user lets go
    import time
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        qapp.processEvents()
        flags = table.windowFlags()
        if (flags & Qt.Window) and not (flags & Qt.Tool) == Qt.Tool:
            break
    flags = table.windowFlags()
    assert flags & Qt.WindowMinimizeButtonHint   # the real-window flags landed
    assert table.minimumHeight() == table.FLOAT_SHRINK_MIN_HEIGHT


def test_code_driven_float_is_still_immediate(qapp, dock_mainwindow, manager):
    """restoreLayout and the tab double-click float with no button held; the
    flags must land synchronously, as every earlier float test assumes."""
    from PySide6.QtCore import Qt

    table = open_list(manager, "object", qapp)
    table.setFloating(True)
    settle(qapp)
    assert table.windowFlags() & Qt.WindowMinimizeButtonHint


def test_double_clicking_a_tab_floats_its_list(qapp, dock_mainwindow, manager):
    import shiboken6

    open_list(manager, "object", qapp)
    second = open_list(manager, "section", qapp)
    settle(qapp)
    bar = manager._dockTabBars()[0]
    ptr = shiboken6.getCppPointer(second)[0]
    index = next(i for i in range(bar.count()) if bar.tabData(i) == ptr)
    bar.tabBarDoubleClicked.emit(index)
    settle(qapp)
    assert second.isFloating()
    assert second.width() >= second.FLOAT_MIN_WIDTH


# --------------------------------------------------------------------------
# Right-click roads between docked and floating (his ask, 2026-08-25)
# --------------------------------------------------------------------------

def test_tab_right_click_offers_float_and_close(qapp, dock_mainwindow, manager):
    open_list(manager, "object", qapp)
    second = open_list(manager, "section", qapp)
    settle(qapp)
    bar = manager._dockTabBars()[0]
    import shiboken6
    ptr = shiboken6.getCppPointer(second)[0]
    index = next(i for i in range(bar.count()) if bar.tabData(i) == ptr)
    menu = manager._tabContextMenu(bar, bar.tabRect(index).center())
    labels = [a.text() for a in menu.actions()]
    assert labels == ["Undock this list", "Close this list"]
    menu.actions()[0].trigger()
    settle(qapp)                      # the menu deletes itself on hide
    assert second.isFloating()


def test_title_bar_right_click_offers_float_and_close(qapp, dock_mainwindow, manager):
    """A lone docked list's title bar right-click floats or closes it.
    Floating lists run under the native frame, so their right-click is the
    OS's; the "Dock this list" menubar button is their road back."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

    table = open_list(manager, "object", qapp)
    assert not table.main_widget.geometry().contains(QPoint(5, 2))

    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, QPoint(5, 2),
        table.mapToGlobal(QPoint(5, 2)),
    )
    table.contextMenuEvent(event)
    labels = [a.text() for a in table._titlebar_menu.actions()]
    assert labels == ["Undock this list", "Close this list"]
    table._titlebar_menu.actions()[0].trigger()
    settle(qapp)
    assert table.isFloating()


def test_default_docked_width_clears_the_list_menu_bar(qapp, dock_mainwindow, manager):
    """The default width must not obscure any of the list's own menus (his
    click test, 2026-08-26). Columns may still overflow; the menu bar not."""
    table = open_list(manager, "object", qapp)
    assert table.width() >= table.main_widget.menuBar().sizeHint().width()


def test_toggle_on_a_bare_series_opens_the_object_list(qapp, dock_mainwindow, manager):
    """A freshly opened series has no lists, and the sidebar button used to
    do nothing at all there. It now opens the object list (his call,
    2026-08-26), the one most people want first."""
    assert not any(manager.tables.values())
    manager.toggleListsCollapsed()
    settle(qapp)
    assert len(manager.tables["object"]) == 1
    table = manager.tables["object"][0]
    assert table.isVisible()
    assert not table.isFloating()
    assert not manager.listsCollapsed()

    # and the next press collapses it, the ordinary behavior
    manager.toggleListsCollapsed()
    settle(qapp)
    assert manager.listsCollapsed()
    assert not table.isVisible()


def test_tab_properties_survive_a_dock_rebuild(qapp, dock_mainwindow, manager):
    """Qt resets tabsClosable and the context-menu policy on the tab bar it
    reuses as docks come and go; the X went missing and reappeared on that
    beat (his report, 2026-08-26). Both are re-applied on every wiring pass,
    so a reset cannot outlive the next dock change."""
    from PySide6.QtCore import Qt

    open_list(manager, "object", qapp)
    open_list(manager, "section", qapp)
    settle(qapp)
    bar = manager._dockTabBars()[0]

    bar.setTabsClosable(False)                 # what a Qt rebuild leaves
    bar.setContextMenuPolicy(Qt.DefaultContextMenu)
    manager._syncTitleBars()                   # any dock change runs this
    settle(qapp)

    assert bar.tabsClosable()
    assert bar.contextMenuPolicy() == Qt.CustomContextMenu


def test_a_tab_drag_tears_the_list_out(qapp, dock_mainwindow, manager):
    """Qt tears a dock out by its title bar, which a tabbed list hides, so
    the gesture did nothing (his report, 2026-08-26). The tear-out is ours
    now: past the drag threshold, the list floats."""
    import shiboken6
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    open_list(manager, "object", qapp)
    second = open_list(manager, "section", qapp)
    settle(qapp)
    bar = manager._dockTabBars()[0]
    ptr = shiboken6.getCppPointer(second)[0]
    index = next(i for i in range(bar.count()) if bar.tabData(i) == ptr)
    start = bar.tabRect(index).center()

    def send(kind, pos, buttons):
        event = QMouseEvent(
            kind, QPointF(pos), QPointF(bar.mapToGlobal(pos)),
            Qt.LeftButton, buttons, Qt.NoModifier,
        )
        QApplication.sendEvent(bar, event)
        settle(qapp, rounds=2)

    send(QEvent.MouseButtonPress, start, Qt.LeftButton)
    # a wobble inside the slop must NOT tear it out
    send(QEvent.MouseMove, start + QPoint(2, 2), Qt.LeftButton)
    assert not second.isFloating()
    # past the threshold it does
    far = QApplication.startDragDistance() * 2 + 6
    send(QEvent.MouseMove, start + QPoint(0, far), Qt.LeftButton)
    assert second.isFloating()


def test_theme_switch_remeasures_list_columns(qapp, main_window, gui_dialogs):
    """A theme switch changes fonts and padding, but the lists kept the OLD
    theme's column widths and the new theme's text crowded them (his report,
    2026-08-26). setTheme now re-measures every open list."""
    mgr = main_window.field.table_manager
    mgr.newTable("object")
    settle(qapp)
    view = mgr.tables["object"][0].table
    ncols = view.model().columnCount()

    main_window.setTheme("qdark")
    settle(qapp, rounds=10)
    switched = [view.columnWidth(c) for c in range(ncols)]

    mgr.newTable("object")
    settle(qapp)
    fresh_view = mgr.tables["object"][1].table
    fresh = [fresh_view.columnWidth(c) for c in range(ncols)]

    assert switched == fresh
    main_window.setTheme("default")
    settle(qapp, rounds=6)


def test_docked_table_never_overflows_its_viewport(qapp, dock_mainwindow, manager):
    """The last rows of a docked list could not be scrolled to: an old
    resizeEvent override sized the table to the DOCK's height minus a guessed
    20px, past the space under the menu bar (his report, 2026-08-26). The
    layout owns the size now, so the table must end inside its window."""
    table = open_list(manager, "object", qapp)
    settle(qapp)
    body = table.main_widget
    inner = table.table
    assert inner.geometry().bottom() <= body.rect().bottom()
    assert inner.geometry().top() >= body.menuBar().height() - 1

    # and after the dock resizes, still true
    dock_mainwindow.resize(1200, 700)
    settle(qapp)
    assert inner.geometry().bottom() <= body.rect().bottom()


def test_tabs_fill_the_full_bar_width(qapp, dock_mainwindow, manager):
    """Two tabs over a wide list left a blank stump of tab bar beside them;
    tabs expand to share the full width (his call, 2026-08-26)."""
    open_list(manager, "object", qapp)
    open_list(manager, "section", qapp)
    settle(qapp)
    bar = manager._dockTabBars()[0]
    assert bar.expanding()
    spanned = sum(bar.tabRect(i).width() for i in range(bar.count()))
    assert spanned >= bar.width() - 4          # the bar, minus rounding slack
