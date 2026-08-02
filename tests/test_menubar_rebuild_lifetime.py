"""Rebuilding a menubar in place must not leave the widget holding dead actions.

Two menu rows rebuild the whole list -- and therefore the whole menubar those
rows live in -- from inside their own handler: the flag list's
"Display resolved flags" (`toggleDisplayResolved` -> `createTable` ->
`createMenus`) and each row of the object list's "Categorical column filters"
(`toggleUserColFilter` -> `recreateTable` -> `createTable` -> `createMenus`).

Before `clearMenuBar`, the rebuild raised `RuntimeError: Internal C++ object
(PySide6.QtGui.QAction) already deleted` on the *first* click of either row,
and left the menubar half-built. `menubar.clear()` was dropping the menubar's
last claim on that generation of menus and actions, while the table widget was
still holding them in its own action list and in its `<name>_act` attributes;
`newAction`'s "remove previous action" step then reached a dead wrapper.

The dependency is on the menu having been *shown*, not on it still being open:
every test here closes the menu and drains the event queue before the toggle
runs, and the crash reproduced anyway. Deferring the rebuild to after the menu
closes would not have fixed it.

Handlers are called directly rather than through `QAction.trigger()` on
purpose. A `RuntimeError` raised inside a slot is caught by the process-wide
`customExcepthook` that `MainWindow.__init__` installs, which writes the real
user log and opens a modal dialog that never returns offscreen -- the failure
would hang the run instead of reporting. Called directly, the same handler runs
the same code and the error is observed by the test.
"""

import pytest
import shiboken6
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from conftest import submenu_at

pytestmark = pytest.mark.gui


def _show_and_close(menu):
    """Pop `menu` up and close it again, leaving nothing on screen."""
    menu.popup(QPoint(0, 0))
    QApplication.processEvents()
    menu.close()
    QApplication.processEvents()
    assert QApplication.activePopupWidget() is None


def _flag_table(main_window, qapp):
    main_window.field.table_manager.newTable("flag")
    qapp.processEvents()
    return main_window.field.table_manager.tables["flag"][-1]


def _object_table(main_window, qapp):
    main_window.field.table_manager.newTable("object")
    qapp.processEvents()
    return main_window.field.table_manager.tables["object"][-1]


def test_flag_display_resolved_survives_its_own_menu_having_been_shown(
    main_window, qapp, local_series_settings
):
    """The flag list's "Display resolved flags" row, clicked once."""
    local_series_settings(main_window)
    table = _flag_table(main_window, qapp)
    _show_and_close(submenu_at(table.menubar, "Filter"))

    action = table.displayresolved_act
    action.setChecked(True)
    table.toggleDisplayResolved()  # raised RuntimeError before the fix

    assert table.show_resolved is True
    # the menubar is fully rebuilt, not left half-built at the crash point
    assert [a.text() for a in table.menubar.actions()] == ["List", "Filter"]
    rebuilt = submenu_at(table.menubar, "Filter")
    assert rebuilt is not None
    assert "Display resolved flags" in [a.text() for a in rebuilt.actions()]


def test_object_user_column_filter_survives_its_own_menu_having_been_shown(
    main_window, qapp, local_series_settings
):
    """One row of the object list's "Categorical column filters", clicked once."""
    series = local_series_settings(main_window)
    series.user_columns["Stage"] = ["early", "late"]
    table = _object_table(main_window, qapp)
    table.createMenus()
    qapp.processEvents()

    path = "Filter > Categorical column filters > Stage"
    _show_and_close(submenu_at(table.menubar, path))

    table.toggleUserColFilter("Stage", "early")  # raised RuntimeError before the fix

    assert table.user_col_filters == {"Stage": ["early"]}
    rebuilt = submenu_at(table.menubar, path)
    assert rebuilt is not None
    assert [a.text() for a in rebuilt.actions()] == ["early", "late"]


def test_repeated_rebuilds_leave_no_dead_actions_on_the_widget(
    main_window, qapp, local_series_settings
):
    """Every action the widget holds after a rebuild is a live object."""
    local_series_settings(main_window)
    table = _flag_table(main_window, qapp)

    for _ in range(3):
        _show_and_close(submenu_at(table.menubar, "Filter"))
        table.createMenus()
        qapp.processEvents()

    dead = [a for a in table.actions() if not shiboken6.isValid(a)]
    assert dead == []
    assert shiboken6.isValid(table.displayresolved_act)


def test_clear_menu_bar_drops_the_generation_it_clears(main_window, qapp):
    """`clearMenuBar` detaches the old actions and forgets their attributes."""
    from PyReconstruct.modules.gui.utils import clearMenuBar

    table = _flag_table(main_window, qapp)
    old_action = table.displayresolved_act
    assert old_action in table.actions()

    clearMenuBar(table, table.menubar)

    assert old_action not in table.actions()
    assert not hasattr(table, "displayresolved_act")
    assert not hasattr(table, "filtermenu")
    assert table.menubar.actions() == []
    # the context menu is a separate surface and is left alone
    assert hasattr(table, "editattribtues_act")


def test_clear_menu_bar_leaves_other_widgets_attributes_alone(main_window, qapp):
    """Only attributes pointing into *this* menubar are dropped."""
    from PyReconstruct.modules.gui.utils import clearMenuBar

    table = _flag_table(main_window, qapp)
    sentinel = object()
    table.some_unrelated_attr = sentinel

    clearMenuBar(table, table.menubar)

    assert table.some_unrelated_attr is sentinel
