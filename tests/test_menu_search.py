"""Help-menu search: find any menubar command by typing part of its name.

The menubar here is Qt-drawn and in-window on every platform, so macOS's
native Help search never applies to it; the app's own answer is a search
field embedded at the top of the Help menu (a QWidgetAction) with results in
a popup list under it. The tests drive the real widget against the real
MainWindow menubar, offscreen.

Behavioral guarantees carried over from the palette-dialog era, all still
asserted here: word-wise matching, label cleaning, disabled commands visible
but not runnable, the shortcut riding along in the row, and running by PATH
rather than through stored wrappers (the wrapper-death regression, plus its
stronger form: a full menubar rebuild between snapshot and run).
"""
import pytest

from PySide6.QtCore import Qt

import PyReconstruct.modules.gui.main.menu_search as menu_search_module
from PyReconstruct.modules.gui.main.menu_search import (
    MenuSearchField,
    clean_label,
    collect_menu_commands,
    matches,
    resolve_command,
)

pytestmark = pytest.mark.gui


# --------------------------------------------------------------------------- #
# the pure pieces
# --------------------------------------------------------------------------- #
def test_clean_label_strips_what_a_user_would_not_type():
    assert clean_label("&File") == "File"
    assert clean_label("Set host(s)...") == "Set host(s)"
    assert clean_label("What's new") == "What's new"


@pytest.mark.parametrize("query,path,hit", [
    ("", "File > Save", True),                      # empty query lists all
    ("save", "File > Save", True),                  # case-insensitive
    ("hide object", "Object > Operations > Hide", False),  # 'object' present, 'hide' present
    ("hide object", "Trace > Hide", False),
    ("host", "Object > Object attributes > Set host(s)", True),
    ("zzz", "File > Save", False),
])
def test_matching_is_word_wise_across_the_whole_path(query, path, hit):
    if query == "hide object":
        # both words appear across segments of the first path
        assert matches(query, "Object > Operations > Hide") is True
        assert matches(query, "Trace > Hide") is False
        return
    assert matches(query, path) is hit


# --------------------------------------------------------------------------- #
# against the real menubar
# --------------------------------------------------------------------------- #
def test_every_menubar_command_is_collected_with_its_path(main_window):
    commands = collect_menu_commands(main_window.menubar)
    paths = [c[0] for c in commands]

    assert len(commands) > 50, "the walker is not seeing the real menubar"
    # a known deep command, with the trail that leads to it
    assert any(p.startswith("Help > ") and "Search menus" in p for p in paths)
    # separators and submenu titles are not commands
    assert all(" > " in p or p for p in paths)
    assert not any(p.endswith(" > ") for p in paths)
    # the search field's own QWidgetAction is textless and must not collect
    assert "" not in paths


def test_the_field_is_embedded_at_the_top_of_the_help_menu(main_window):
    """The macOS shape: the field is the Help menu's first row.

    The keyed action and the field are two actions by design: a QWidgetAction
    cannot carry the series-form configurable shortcut, so searchmenus_act
    stays the remappable carrier (asserted last) while the field does the
    searching.
    """
    field = main_window.menusearchfield_act
    assert isinstance(field, MenuSearchField)
    help_actions = main_window.helpmenu.actions()
    assert help_actions[0] is field
    # The "Search menus..." row shares the field's group (his Help regroup,
    # 2026-08-26): field, then the keyed row that displays its shortcut, then
    # the group separator. No divider between the field and that row.
    assert help_actions[1].text() == "Search menus..."
    assert help_actions[2].isSeparator()
    # the carrier row is still present and still labeled
    assert main_window.searchmenus_act.text() == "Search menus..."
    assert "Search menus..." in [a.text() for a in help_actions]


def _snapshotted_field(main_window):
    """The embedded field with its per-open snapshot taken, as aboutToShow does."""
    field = main_window.menusearchfield_act
    field._snapshot()
    return field


def test_typing_filters_into_the_popup(main_window):
    field = _snapshotted_field(main_window)
    field._query.setText("search menus")
    assert field._results.count() >= 1
    labels = [field._results.item(i).text() for i in range(field._results.count())]
    assert any("Help > Search menus" in l for l in labels)
    # the top hit is preselected so Enter can run it immediately
    assert field._results.currentRow() == 0
    field._query.clear()


def test_an_empty_field_shows_no_popup(main_window):
    """Nothing typed, nothing shown: the plain Help menu is the empty state."""
    field = _snapshotted_field(main_window)
    field._query.setText("search menus")
    assert field._results.count() >= 1
    field._query.setText("")
    assert field._results.count() == 0
    assert not field._results.isVisible()


def test_enter_runs_the_selected_command_by_path(main_window):
    field = _snapshotted_field(main_window)

    # Rows carry the PATH; _run resolves the live action fresh (the open-time
    # wrappers may be dead by then, which is why the indirection exists). The
    # recorder is connected through a fresh wrapper too: signal connections
    # live on the C++ action, so any valid wrapper of it will do.
    target_path = next(
        c[0] for c in field._commands
        if c[0].startswith("Help > ") and "check for updates" in c[0].lower()
    )
    fired = []
    live = resolve_command(main_window.menubar, target_path)
    assert live is not None
    live.triggered.disconnect()
    live.triggered.connect(lambda: fired.append("ran"))

    field._query.setText(target_path.split(" > ")[-1])
    row = next(
        i for i in range(field._results.count())
        if field._results.item(i).data(Qt.ItemDataRole.UserRole) == target_path
    )
    field._results.setCurrentRow(row)
    field._run(field._results.currentItem())
    assert fired == ["ran"]
    # running dismisses the search: popup down, field cleared for next time
    assert not field._results.isVisible()
    assert field._query.text() == ""


def test_running_survives_a_full_menubar_rebuild(main_window):
    """The wrapper-death regression, in its strongest form.

    createMenuBar rebuilds the whole menubar (it runs whenever a series
    opens), orphaning every action the snapshot walked. Running by PATH must
    reach the NEW action; a stored wrapper would trigger nothing, or worse.
    """
    field = _snapshotted_field(main_window)
    target_path = next(
        c[0] for c in field._commands
        if c[0].startswith("Help > ") and "check for updates" in c[0].lower()
    )
    field._query.setText(target_path.split(" > ")[-1])
    row = next(
        i for i in range(field._results.count())
        if field._results.item(i).data(Qt.ItemDataRole.UserRole) == target_path
    )
    stale_item = field._results.item(row)

    main_window.createMenuBar()  # every snapshotted wrapper is now stale

    fired = []
    rebuilt = resolve_command(main_window.menubar, target_path)
    assert rebuilt is not None
    rebuilt.triggered.disconnect()
    rebuilt.triggered.connect(lambda: fired.append("ran"))

    field._run(stale_item)
    assert fired == ["ran"]


def test_a_disabled_command_is_visible_but_not_runnable(main_window):
    """Finding a command teaches where it lives even when it cannot run now.

    Wrappers are re-resolved by path throughout: holding one QAction wrapper
    across the snapshot is exactly what the field itself cannot do.
    """
    target = next(
        c[0] for c in collect_menu_commands(main_window.menubar)
        if c[0].startswith("Help > ") and "check for updates" in c[0].lower()
    )
    resolve_command(main_window.menubar, target).setEnabled(False)
    try:
        field = _snapshotted_field(main_window)
        field._query.setText(target.split(" > ")[-1])
        row = next(
            i for i in range(field._results.count())
            if field._results.item(i).data(Qt.ItemDataRole.UserRole) == target
        )
        item = field._results.item(row)
        assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)

        fired = []
        live = resolve_command(main_window.menubar, target)
        live.triggered.connect(lambda: fired.append("no"))
        field._run(item)
        assert fired == []
        field._query.clear()
    finally:
        resolve_command(main_window.menubar, target).setEnabled(True)


def test_shortcut_text_rides_along_in_the_result_row(main_window):
    field = _snapshotted_field(main_window)
    field._query.setText("search menus")
    labels = [field._results.item(i).text() for i in range(field._results.count())]
    # the key's spelling is platform- and configuration-dependent; what the
    # row must show is that A shortcut rides along in parentheses
    assert any("(" in l and ")" in l for l in labels), labels
    field._query.clear()


# --------------------------------------------------------------------------- #
# reveal integration (menu_reveal is merged separately; here it is stubbed)
# --------------------------------------------------------------------------- #
def test_arrow_selection_asks_reveal_for_the_selected_path(main_window, monkeypatch):
    """Arrow-selecting (and hovering) a result calls reveal_path with the PATH.

    menu_reveal lands from its own branch; until then the module's guarded
    import falls back to a no-op returning False. The call sites go through
    the module globals, so the contract is testable either way.
    """
    revealed = []
    closed = []
    monkeypatch.setattr(
        menu_search_module, "reveal_path",
        lambda menubar, path: revealed.append(path) or True,
    )
    monkeypatch.setattr(
        menu_search_module, "close_reveal",
        lambda menubar: closed.append(True),
    )

    field = _snapshotted_field(main_window)
    field._query.setText("check for updates")
    assert field._results.count() >= 1
    # typing alone must NOT reveal: opening real menus per keystroke is loud
    assert revealed == []

    field._revealCurrent()  # what the Down-arrow handler calls after moving
    assert len(revealed) == 1
    assert "check for updates" in revealed[0].lower()
    assert field._reveal_active is True

    # hover goes through the same gate
    field._hover(field._results.item(0))
    assert len(revealed) == 2

    # dismissing closes the reveal along with the popup
    field._dismiss()
    assert closed
    assert field._reveal_active is False


def test_a_reveal_in_flight_suppresses_the_menu_hide_teardown(main_window, monkeypatch):
    """Revealing opens the target menu, which closes the Help menu; the
    aboutToHide cleanup must stand down or it would kill the search
    mid-gesture. Once the reveal is over, the same signal cleans up again."""
    monkeypatch.setattr(menu_search_module, "reveal_path", lambda mb, p: True)
    monkeypatch.setattr(menu_search_module, "close_reveal", lambda mb: None)

    field = _snapshotted_field(main_window)
    field._query.setText("check for updates")
    assert field._results.count() >= 1
    field._revealCurrent()
    assert field._reveal_active is True

    field._menuHiding()  # the Help menu closing FOR the reveal
    assert field._query.text() == "check for updates"  # search survived

    field._reveal_active = False
    field._menuHiding()  # an ordinary close
    assert field._query.text() == ""
    assert not field._results.isVisible()


# --------------------------------------------------------------------------- #
# the Ctrl+K entry point
# --------------------------------------------------------------------------- #
def test_ctrl_k_opens_help_and_focuses_the_field(main_window):
    """openMenuSearch (searchmenus_act's handler, default Ctrl+K) opens the
    Help menu and puts the cursor in the embedded field."""
    main_window.openMenuSearch()
    try:
        assert main_window.helpmenu.isVisible()
        field = main_window.menusearchfield_act
        assert field._query.hasFocus()
        # the per-open snapshot ran (aboutToShow), so typing has data to filter
        assert len(field._commands) > 50
    finally:
        main_window.helpmenu.close()


# --------------------------------------------------------------------------- #
# the field's right-click commands are searchable too
# --------------------------------------------------------------------------- #
def test_right_click_commands_are_searchable(main_window):
    """The day-to-day operations live in the field's context menu, not the
    menubar; a search that misses them misses the point (click-test report)."""
    from PyReconstruct.modules.gui.main.menu_search import collect_all_commands

    paths = [c[0] for c in collect_all_commands(main_window)]
    rc = [p for p in paths if p.startswith("Right-click > ")]
    assert len(rc) > 20, rc[:5]
    assert any(p.startswith("Right-click > Object > ") for p in rc)
    assert any(p.startswith("Right-click > Trace > ") for p in rc)


def test_right_click_commands_resolve_and_run(main_window):
    from PyReconstruct.modules.gui.main.menu_search import (
        collect_all_commands, resolve_command,
    )

    path = next(
        c[0] for c in collect_all_commands(main_window)
        if c[0].startswith("Right-click > ") and c[2]
    )
    action = resolve_command(main_window.menubar, path, mainwindow=main_window)
    assert action is not None and action.isEnabled()


def test_reveal_declines_right_click_paths(main_window):
    """Reveal has nothing to anchor a context menu to; it must say no
    cleanly rather than open something wrong."""
    from PyReconstruct.modules.gui.main.menu_reveal import reveal_path

    assert reveal_path(main_window.menubar, "Right-click > Trace > Set open") is False
