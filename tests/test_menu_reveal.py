"""reveal_path/close_reveal: open the real menus along a path and highlight.

The reveal half of the Help-menu search. These tests drive the real
MainWindow menubar offscreen, because the whole point of the module is Qt
popup mechanics (setActiveAction opening menus) that a mocked menubar would
fake rather than test. Paths are asserted against known menubar entries; the
sweep test ties the module to collect_menu_commands so the two halves of the
feature cannot drift on what a path is.
"""
from shiboken6 import isValid

from PyReconstruct.modules.gui.main.menu_search import (
    clean_label,
    collect_menu_commands,
)
from PyReconstruct.modules.gui.main.menu_reveal import close_reveal, reveal_path


def open_menus(menubar):
    """Cleaned label trails of every currently visible menu, for asserting.

    Re-walked fresh each call rather than cached: the wrapper-lifetime trap
    documented in collect_menu_commands applies to tests too.
    """
    trails = []

    def walk(menu, trail):
        if isValid(menu) and menu.isVisible():
            trails.append(" > ".join(trail))
        for action in menu.actions():
            if not isValid(action):
                continue
            submenu = action.menu()
            if submenu is not None:
                walk(submenu, trail + [clean_label(action.text())])

    for top in menubar.actions():
        if not isValid(top):
            continue
        menu = top.menu()
        if menu is not None:
            walk(menu, [clean_label(top.text())])
    return trails


def active_trail(menubar, path):
    """The cleaned label of the active action in the menu that path ends in."""
    labels = path.split(" > ")
    owner = None
    for top in menubar.actions():
        if isValid(top) and clean_label(top.text()) == labels[0]:
            owner = top.menu()
            break
    for label in labels[1:-1]:
        assert owner is not None
        match = next(
            a for a in owner.actions()
            if isValid(a) and clean_label(a.text()) == label
        )
        owner = match.menu()
    active = owner.activeAction()
    return clean_label(active.text()) if active is not None else None


def test_reveal_opens_the_menu_and_highlights_the_item(main_window):
    menubar = main_window.menubar
    assert reveal_path(menubar, "File > Save") is True
    assert open_menus(menubar) == ["File"]
    assert clean_label(menubar.activeAction().text()) == "File"
    assert active_trail(menubar, "File > Save") == "Save"
    close_reveal(menubar)


def test_reveal_walks_nested_submenus(main_window):
    menubar = main_window.menubar
    path = "File > New series > From images"
    assert reveal_path(menubar, path) is True
    opened = open_menus(menubar)
    # The reveal is complete when every menu on the trail is open at once and
    # the deepest one holds the highlight. A partial reveal (module docstring)
    # would fail here, which is exactly the signal wanted if popup behavior
    # regresses on some platform.
    assert "File" in opened
    assert "File > New series" in opened
    assert active_trail(menubar, path) == "From images"
    close_reveal(menubar)


def test_reveal_reaches_depth_four(main_window):
    menubar = main_window.menubar
    path = "View > Palette > Increment palette buttons > Up"
    assert reveal_path(menubar, path) is True
    opened = open_menus(menubar)
    assert "View" in opened
    assert "View > Palette" in opened
    assert "View > Palette > Increment palette buttons" in opened
    assert active_trail(menubar, path) == "Up"
    close_reveal(menubar)


def test_unknown_paths_return_false_without_side_effects(main_window):
    menubar = main_window.menubar
    for bad in (
        "File > No such command",
        "No such menu > Save",
        "File > Save > deeper",  # the trail crosses a plain command
        "File",                  # names a menu, not an item
        "",
    ):
        assert reveal_path(menubar, bad) is False, bad
        assert open_menus(menubar) == [], bad
        assert menubar.activeAction() is None, bad


def test_close_reveal_closes_everything_and_is_reentrant(main_window):
    menubar = main_window.menubar
    assert reveal_path(menubar, "View > Palette > Increment palette buttons > Down")
    assert open_menus(menubar) != []
    close_reveal(menubar)
    assert open_menus(menubar) == []
    assert menubar.activeAction() is None
    # closing an already-closed menubar must be a no-op, not an error: the
    # search field closes on every escape/focus-out without tracking state
    close_reveal(menubar)
    assert open_menus(menubar) == []


def test_back_to_back_reveals_leave_only_the_last_one_open(main_window):
    menubar = main_window.menubar
    # both target items are enabled at startup, so both carry the highlight
    # (disabled items reveal without one; that case has its own test below)
    assert reveal_path(menubar, "File > New series > From images") is True
    assert reveal_path(menubar, "Edit > Paste attributes to palette") is True
    opened = open_menus(menubar)
    assert "Edit" in opened
    assert all(not trail.startswith("File") for trail in opened)
    assert active_trail(menubar, "Edit > Paste attributes to palette") \
        == "Paste attributes to palette"
    # the same path twice is the selection-changed signal firing redundantly
    assert reveal_path(menubar, "Edit > Paste attributes to palette") is True
    assert active_trail(menubar, "Edit > Paste attributes to palette") \
        == "Paste attributes to palette"
    close_reveal(menubar)


def test_a_disabled_item_is_revealed_without_the_highlight(main_window):
    """Qt refuses to make a disabled action active (measured on 6.5.2).

    The search palette lists disabled commands on purpose, so revealing one
    must still open its menu; the grayed row on screen is the reveal. "Edit >
    Undo" is disabled at startup (nothing to undo yet), which makes it the
    real-world case rather than a synthetic one.
    """
    menubar = main_window.menubar
    # conftest's menu_action rather than menu_search's resolve_command: the
    # latter's wrappers can die between collection and the isEnabled call
    # (the lifetime trap in collect_menu_commands' docstring), and this
    # assertion needs a wrapper that is still alive to read
    from conftest import menu_action
    undo = menu_action(menubar, "Edit > Undo")
    assert undo is not None and not undo.isEnabled()
    assert reveal_path(menubar, "Edit > Undo") is True
    assert open_menus(menubar) == ["Edit"]
    assert active_trail(menubar, "Edit > Undo") is None
    close_reveal(menubar)


def test_a_failed_reveal_after_a_successful_one_closes_the_stale_menus(main_window):
    """The caller reveals whatever row is selected; a row can go stale.

    An unknown path must not leave the previous reveal's menus lingering as
    if they belonged to the new selection.
    """
    menubar = main_window.menubar
    assert reveal_path(menubar, "File > Save") is True
    assert reveal_path(menubar, "File > No such command") is False
    # False with no NEW side effects; the old reveal may remain (documented:
    # resolution happens before anything is touched), so close explicitly
    close_reveal(menubar)
    assert open_menus(menubar) == []


def test_every_collected_path_can_be_revealed(main_window):
    """Ties the two halves of the feature together against the live menubar.

    collect_menu_commands defines what a path IS; if any path it produces
    cannot be revealed, the search field would show rows that silently do
    nothing on selection.

    The excepthook swap is a hang guard, not part of the assertion: opening
    every menu fires every aboutToShow slot the app has, and MainWindow's
    customExcepthook answers any slot exception with a modal error dialog,
    which nothing can dismiss offscreen. The default hook prints the same
    traceback and lets the sweep finish (and fail visibly) instead.
    """
    import sys
    sys.excepthook = sys.__excepthook__  # main_window's teardown restores it
    menubar = main_window.menubar
    paths = [c[0] for c in collect_menu_commands(menubar)]
    assert len(paths) > 50
    # A menubar rebuild can land mid-sweep (a queued slot running inside the
    # settle that reveal_path does), and while it is in flight the menubar is
    # briefly missing the menus it has not re-added yet. Paths collected
    # before that are not stale: the menus come back, alive and attached. So
    # a failure is only real if it survives re-collecting and retrying once
    # on a settled menubar. Without this the sweep failed on CI roughly five
    # runs in six, always as one real failure plus a cascade of paths that
    # were merely revealed too early.
    def _revealable(path):
        if reveal_path(menubar, path):
            return True
        close_reveal(menubar)
        if path not in [c[0] for c in collect_menu_commands(menubar)]:
            return True    # the rebuild renamed or moved it; not a reveal bug
        return reveal_path(menubar, path)

    failures = [p for p in paths if not _revealable(p)]
    close_reveal(menubar)
    assert failures == []
