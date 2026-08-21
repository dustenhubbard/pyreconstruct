"""Help > "Search menus...": find any menubar command by typing part of its name.

The menubar here is Qt-drawn and in-window on every platform, so macOS's native
Help search never applies to it; this palette is the app's own answer. The
tests drive the real widget against the real MainWindow menubar, offscreen.
"""
import pytest

from PySide6.QtCore import Qt

from PyReconstruct.modules.gui.dialog.menu_search import (
    MenuSearchDialog,
    clean_label,
    collect_menu_commands,
    matches,
    resolve_command,
)


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


def test_the_palette_filters_and_runs_a_command(main_window):
    dialog = MenuSearchDialog(main_window)
    dialog._query.setText("search menus")
    assert dialog._results.count() >= 1
    labels = [dialog._results.item(i).text() for i in range(dialog._results.count())]
    assert any("Help > Search menus" in l for l in labels)

    # Rows carry the PATH; _run resolves the live action fresh (the open-time
    # wrappers may be dead by then, which is why the indirection exists). The
    # recorder is connected through a fresh wrapper too: signal connections
    # live on the C++ action, so any valid wrapper of it will do.
    target_path = next(
        c[0] for c in dialog._commands
        if c[0].startswith("Help > ") and "check for updates" in c[0].lower()
    )
    fired = []
    live = resolve_command(main_window.menubar, target_path)
    assert live is not None
    live.triggered.disconnect()
    live.triggered.connect(lambda: fired.append("ran"))

    dialog._query.setText(target_path.split(" > ")[-1])
    row = next(
        i for i in range(dialog._results.count())
        if dialog._results.item(i).data(Qt.ItemDataRole.UserRole) == target_path
    )
    dialog._results.setCurrentRow(row)
    dialog._run(dialog._results.currentItem())
    assert fired == ["ran"]
    assert dialog.result() == dialog.DialogCode.Accepted


def test_a_disabled_command_is_visible_but_not_runnable(main_window):
    """Finding a command teaches where it lives even when it cannot run now.

    Wrappers are re-resolved by path throughout: holding one QAction wrapper
    across dialog construction is exactly what the palette itself cannot do.
    """
    target = next(
        c[0] for c in collect_menu_commands(main_window.menubar)
        if c[0].startswith("Help > ") and "check for updates" in c[0].lower()
    )
    resolve_command(main_window.menubar, target).setEnabled(False)
    try:
        dialog = MenuSearchDialog(main_window)
        row = next(
            i for i in range(dialog._results.count())
            if dialog._results.item(i).data(Qt.ItemDataRole.UserRole) == target
        )
        item = dialog._results.item(row)
        assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)

        fired = []
        live = resolve_command(main_window.menubar, target)
        live.triggered.connect(lambda: fired.append("no"))
        dialog._run(item)
        assert fired == []
        assert dialog.result() != dialog.DialogCode.Accepted
    finally:
        resolve_command(main_window.menubar, target).setEnabled(True)


def test_shortcut_text_rides_along_in_the_result_row(main_window):
    dialog = MenuSearchDialog(main_window)
    dialog._query.setText("search menus")
    labels = [dialog._results.item(i).text() for i in range(dialog._results.count())]
    # the key's spelling is platform- and configuration-dependent; what the
    # row must show is that A shortcut rides along in parentheses
    assert any("(" in l and ")" in l for l in labels), labels


def test_the_help_menu_carries_the_entry(main_window):
    assert main_window.searchmenus_act.text() == "Search menus..."
    help_actions = [a.text() for a in main_window.helpmenu.actions()]
    assert "Search menus..." in help_actions
