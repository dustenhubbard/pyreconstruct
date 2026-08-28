"""A menubar rebuild must not orphan the actions the context menus share.

The field's right-click menu reuses menubar QActions (cut, copy, paste
attributes), and `createContextMenus` stores them in `trace_actions`, which
`checkActions` walks on every field interaction. `createMenuBar` destroys its
previous generation, so any rebuild NOT followed by a context-menu rebuild
left `trace_actions` full of dead wrappers: the next field click raised
`RuntimeError: Internal C++ object already deleted` from `checkActions`, and
kept raising until something else rebuilt the context menus (found
2026-08-28; Clear recents and add-to-a-new-group were the reachable paths).

`createMenuBar` now rebuilds the context menus itself whenever they exist,
so the two generations can no longer drift apart.
"""

import pytest

from shiboken6 import isValid

pytestmark = pytest.mark.gui


def test_check_actions_survives_a_menubar_only_rebuild(main_window):
    """The exact user path: a menubar rebuild, then a field interaction."""
    window = main_window
    assert window.trace_actions, "the context menus were never built"

    window.createMenuBar()          # what Clear recents / add-to-group do

    for action in window.trace_actions:
        assert isValid(action), "trace_actions still holds a dead wrapper"
    window.checkActions()           # raised RuntimeError before the fix


def test_context_menu_shells_do_not_pile_up(main_window, qapp):
    """Each rebuild retires the previous field and label menus.

    They are parented to the window, so before the deleteLater they simply
    accumulated: one pair per menubar rebuild for the life of the window.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu

    window = main_window

    def direct_menu_children():
        ## Direct children only: the menubar's own menus are parented to the
        ## menubar, so the window's direct QMenu children are exactly the
        ## context-menu shells (plus anything else that leaks the same way).
        return len(window.findChildren(
            QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly
        ))

    window.createMenuBar()
    qapp.processEvents()            # drain the deleteLater queue
    baseline = direct_menu_children()

    for _ in range(3):
        window.createMenuBar()
    qapp.processEvents()

    assert direct_menu_children() == baseline, (
        "context-menu shells accumulate across menubar rebuilds"
    )
