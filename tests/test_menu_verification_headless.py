"""Menu verification against the live widget tree, including real key presses.

Everything here was a manual click-through before `MainWindow` became
constructible offscreen. Three claims are made, and they are deliberately not
the same claim:

  WIRING     a row exists at a menu path, is the same `QAction` the window
             exposes by name, and carries the shortcut string its option holds.
             The suite already covered part of this against the menu
             *definitions* (`test_menubar_labels.py`, `test_menu_restructure.py`,
             `test_context_menu_frequency.py`). Those read the nested dicts
             `return_menubar` returns; they never run `populateMenu`, so they
             cannot see a menu dropped on the way to the widget, a row wired to a
             different action than the attribute `checkActions` gates, or a
             shortcut whose option lookup came back empty.

  GATING     an action's enabled state at a path follows `checkActions` and the
             optional-dependency probe. Only observable on a real window,
             because the action objects are created by `createContextMenus`.

  FIRING     pressing the key actually reaches the action, and reaches its slot.
             A different and stronger claim than WIRING, and the one that was
             genuinely unavailable: a test named for a key press that calls
             `trigger()` proves nothing about the key.

FIRING is real here, not simulated. Measured under `QT_QPA_PLATFORM=offscreen`
with PySide6 6.5.2: `MainWindow` comes up visible and `isActiveWindow()` is True
without any `show()` or `activateWindow()` call, so `Qt.WindowShortcut` actions
are in scope and `QTest.keySequence` is dispatched through Qt's real shortcut
map. `test_the_key_that_fires_an_action_is_the_one_its_option_names` is what
distinguishes that from a disguised `trigger()`: it rebinds the option, rebuilds
the menus, and asserts the *old* sequence stops working. A `trigger()` in
disguise cannot fail that way.

Note the wrapper-ownership constraint recorded above `menu_leaf_paths` in
`conftest.py`. It is the reason identity is compared with `same_action` rather
than `is`, the reason anything read off a `MainWindow` attribute is read before
the walk, and the reason no test here rebuilds the menubar after walking it.

What is still not covered, and cannot be from here:

  * Which physical key a sequence reaches a user's fingers as. `Ctrl` is
    `Command` on macOS, and a settings string says nothing about what a given
    desktop environment has already claimed. That needs a Windows or Linux box.
  * Whether a menu is legible, or whether a row is where a user expects to find
    it. Position and label are assertable; discoverability is not.
  * Pointer input into a modal dialog. `QTest.mouseClick` does work offscreen
    (measured, including that a `Qt.NoFocus` button leaves the caret where it
    was), but a dialog opened with `exec()` spins a loop with nobody to dismiss
    it, so anything behind a real modal stays a click-through.
"""

from collections import defaultdict

import pytest
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from conftest import menu_action, menu_leaf_paths, same_action, submenu_at

pytestmark = pytest.mark.gui


def _cpp(obj):
    import shiboken6

    return shiboken6.Shiboken.getCppPointer(obj)[0]


# --- the helper itself, so nothing below can pass vacuously -------------------

def test_menu_action_resolves_a_path_to_the_windows_own_action(main_window):
    """`menu_action` finds the row a user reads off the screen.

    Asserted against the window's named action, not against the label: the point
    of a path lookup is to catch a row that shows the right text while pointing
    somewhere else.

    The attribute addresses are taken first, before any walk, for the reason in
    `conftest.py`: walking creates new wrappers and can invalidate the ones the
    window is holding.
    """
    wanted = {
        name: _cpp(getattr(main_window, name))
        for name in ("save_act", "open_act", "newfromimages_act", "objectlist_act")
    }
    paths = menu_leaf_paths(main_window.menubar)

    assert _cpp(paths["File > Save"]) == wanted["save_act"]
    assert _cpp(paths["File > Open series..."]) == wanted["open_act"]
    assert (
        _cpp(paths["File > New series > From images..."])
        == wanted["newfromimages_act"]
    )
    assert _cpp(paths["Lists > Object list"]) == wanted["objectlist_act"]


def test_menu_action_returns_none_for_anything_that_is_not_a_row(main_window):
    """A miss is None, and a submenu is a miss.

    Three ways to be wrong, all of which a laxer lookup would let through: a
    label that does not exist, a real label under the wrong parent, and a path
    that stops on a submenu. The last one matters most. A submenu is not
    clickable, and a lookup that returned it would let a test "find" an action
    that is really a folder.
    """
    menubar = main_window.menubar

    assert menu_action(menubar, "File > Sav") is None
    assert menu_action(menubar, "Edit > Save") is None
    assert menu_action(menubar, "File > New series") is None
    assert menu_action(menubar, "Series > Trace palette") is None

    # ...and the submenus those last two name are really there
    assert submenu_at(menubar, "File > New series") is not None
    assert submenu_at(menubar, "Series > Trace palette") is not None
    assert submenu_at(menubar, "File > Nope") is None


def test_same_action_is_not_python_identity(main_window):
    """`same_action` matches across wrappers; `is` does not.

    Guards the comparison every WIRING test below depends on. If a future PySide6
    ever makes `is` work, this test is where that shows up, and the tests that
    use `same_action` keep passing either way.
    """
    from_walk = menu_leaf_paths(main_window.menubar)["File > Quit"]
    from_attribute = main_window.quit_act

    assert same_action(from_walk, from_attribute) is True
    assert same_action(from_walk, main_window.save_act) is False
    assert same_action(from_walk, None) is False


def test_every_top_level_menu_contributes_rows(main_window):
    """All eight menus reach the leaf map, and no leaf has an empty label.

    `test_menubar_has_every_top_level_menu` (in `test_main_window_headless.py`)
    pins the eight titles. This pins that each of them actually has reachable
    content under it, which is the failure a dropped `opts` list would produce.
    An empty final segment would mean a separator leaked in as a row.
    """
    paths = menu_leaf_paths(main_window.menubar)

    for menu_title in (
        "File", "Edit", "Series", "Section", "Lists", "Alignments", "View",
        "Help",
    ):
        assert any(path.startswith(f"{menu_title} > ") for path in paths), (
            f"no rows under {menu_title}"
        )

    assert all(path.split(" > ")[-1] for path in paths)
    assert len(paths) > 100


# --- WIRING: the widget tree, addressed by path -------------------------------

# (path, attribute name). Spread across menus and depths on purpose, including
# one row whose shortcut is hardcoded in `menubar.py` rather than read from an
# option (`Align by correlation`), since that takes a different branch of
# `newAction`, and one three levels deep.
MENUBAR_ROWS = (
    ("File > Quit", "quit_act"),
    ("File > Backup > Backup now...", "manualbackup_act"),
    ("Edit > Undo", "undo_act"),
    ("Edit > Brightness/contrast > Increase brightness", "incbr_act"),
    ("Series > Options...", "alloptions_act"),
    ("Section > Go to section...", "goto_act"),
    ("Lists > Flag list", "flaglist_act"),
    ("Alignments > Edit alignments...", "changealignment_act"),
    ("Alignments > Align by correlation", "aligncorrelation_act"),
    ("View > Set view to image", "homeview_act"),
    ("View > Palette > Increment palette buttons > Up", "incpaletteup_act"),
    ("Help > Shortcuts list", "shortcutshelp_act"),
)


@pytest.mark.parametrize("path,attr_name", MENUBAR_ROWS)
def test_a_menubar_row_is_the_action_the_window_names(
    main_window, path, attr_name
):
    """The row at `path` is the same `QAction` as `window.<attr_name>`.

    `newAction` does `setattr(widget, act_name, action)` on the action it just
    added to the menu, so these are the same object by construction. Which is
    exactly why it is worth pinning: every gate in `checkActions` and every
    shortcut rebind addresses the action by attribute, and a refactor that
    rebuilt one without the other leaves a menu row that looks right and is never
    enabled.
    """
    expected = _cpp(getattr(main_window, attr_name))
    row = menu_action(main_window.menubar, path)

    assert row is not None, f"no row at {path!r}"
    assert _cpp(row) == expected


# --- the 2026-08-06 hoist: four toggles out of View > Palette > Visibility ----

# (label under View, attribute name). These were at
# "View > Palette > Visibility > <label>" until 2026-08-06.
HOISTED_VISIBILITY_ROWS = (
    ("Trace palette", "togglepalette_act"),
    ("Section increment buttons", "toggleinc_act"),
    ("Brightness/contrast sliders", "togglebc_act"),
    ("Scale bar", "togglesb_act"),
)


@pytest.mark.parametrize("label,attr_name", HOISTED_VISIBILITY_ROWS)
def test_a_hoisted_visibility_toggle_is_directly_under_view(
    main_window, label, attr_name
):
    """The row is at "View > <label>" in the built widget tree, and is checkable.

    Asserted against the real menubar rather than the menu definitions, because
    the definitions are what `test_menubar_labels.py` already reads: a hoist that
    edited the dict and never reached `populateMenu` would pass there and fail
    here. Checkability is asserted with it because it is the reason these four
    were worth hoisting -- a toggle is set in combination with its neighbours,
    and `newAction` keys the keep-open filter off exactly this flag.
    """
    row = menu_action(main_window.menubar, f"View > {label}")

    assert row is not None, f"no row at 'View > {label}'"
    assert _cpp(row) == _cpp(getattr(main_window, attr_name))
    assert row.isCheckable(), f"'View > {label}' stopped being a toggle"


def test_the_visibility_submenu_is_gone_and_palette_kept_its_own_rows(main_window):
    """The emptied submenu is removed; the Palette submenu around it survives.

    Both halves matter. Leaving "Visibility" in place as an empty submenu would
    satisfy the test above while still showing the user a dead row, and removing
    "Palette" along with it would take out "Increment palette buttons" and
    "Reset palette position", which the decision did not touch.
    """
    assert submenu_at(main_window.menubar, "View > Palette > Visibility") is None
    assert submenu_at(main_window.menubar, "View > Palette") is not None

    paths = menu_leaf_paths(main_window.menubar)
    for label, _attr in HOISTED_VISIBILITY_ROWS:
        assert f"View > Palette > Visibility > {label}" not in paths

    assert "View > Palette > Increment palette buttons > Up" in paths
    assert "View > Palette > Reset palette position" in paths


def test_view_keeps_its_order_with_the_four_inserted_after_show_z_traces(
    main_window,
):
    """The whole of View, in order, as the one guard that the hoist moved only
    the four rows it was supposed to move.

    Separators are not visible to `menu_leaf_paths`, so this is the clickable
    order. The four land immediately after "Show z-traces" because that is the
    same question -- what is currently visible -- and everything before and after
    them is byte-identical to the pre-hoist order, which is what the standing
    rule about not reordering View requires.

    One sanctioned addition since (2026-08-12, his placement call): "Recolor
    all objects from palette..." directly under "Edit fill opacity...", the
    series-wide sibling of the object menus' "Reapply palette colors...".
    Nothing else moved; tests/test_menubar_labels.py holds the structure guard
    and tests/test_autoseg_reapply_colors.py pins its semantics.
    """
    view = submenu_at(main_window.menubar, "View")
    assert view is not None

    order = [p for p in menu_leaf_paths(view) if " > " not in p]

    assert order == [
        "Copy view to clipboard",
        "Save view to file",
        "Change theme...",
        "Edit fill opacity...",
        # the 2026-08-12 addition, and the only change to this list since the
        # hoist below
        "Recolor all objects from palette...",
        "Set view to image",
        "View magnification...",
        "Set zoom when finding contours...",
        "Show z-traces",
        # the four hoisted rows
        "Trace palette",
        "Section increment buttons",
        "Brightness/contrast sliders",
        "Scale bar",
        "Reset window",
        "Left handed",
        "Toggle curation in object lists",
    ]


def test_the_field_object_menu_keeps_add_and_remove_reachable(main_window):
    """`Add to 3D scene` and `Remove from scene` are both reachable.

    The field's `Object >` context menu, which only a real window has: it is
    built by `createContextMenus` from `get_context_menu_list_obj`, and nothing
    outside the widget tree can tell you where a row ended up.

    Deliberately asserts reachability and identity, not position, and does not
    assert that `Add to 3D scene` is absent from `3D >`. Placement in that menu
    is an open product question; what must not break is that both halves of the
    pair can be found at all, and that they are the actions the window names.
    """
    wanted_add = _cpp(main_window.addobjto3D_act)
    wanted_remove = _cpp(main_window.removeobj3D_act)

    object_menu = submenu_at(main_window.field_menu, "Object")
    assert object_menu is not None

    paths = menu_leaf_paths(object_menu)

    assert _cpp(paths["Add to 3D scene"]) == wanted_add
    assert _cpp(paths["3D > Remove from scene"]) == wanted_remove


# Every option-backed action now applies the key its option holds. `sethosts_act`
# was the last exemption: it was built with `""` in `get_context_menu_list_obj`,
# so its `Ctrl+Shift+H` default and its shortcuts-dialog row bound nothing. It
# passes the series now, and the test below covers it from a cold store.
KNOWN_UNAPPLIED_SHORTCUTS = set()


def _configurable_actions(window):
    """Every option-backed `<name>_act` that is a real `QAction` on `window`."""
    from PyReconstruct.modules.datatypes import Series

    return [
        name for name in Series.qsettings_defaults
        if name.endswith("_act")
        and isinstance(getattr(window, name, None), QAction)
    ]


def test_every_configurable_action_carries_the_shortcut_its_option_holds(
    main_window, local_series_settings
):
    """The widget's shortcut is the option's value, for all ~60 of them.

    `newAction` resolves a shortcut three ways: a literal string, a `Series`
    (look the option up by `act_name`), and a `(series, "checkbox")` tuple. Only
    the last two are user-configurable, and only the widget can say whether the
    lookup landed. An option renamed on one side of that lookup yields an action
    with no shortcut at all, which is silent in the menu and reads to a user as
    "this feature has no key".

    Runs against an in-memory store, so the option reads cannot leave keys in the
    developer's real settings (`getOption` writes the default back for any key it
    does not find).
    """
    series = local_series_settings(main_window)

    configurable = _configurable_actions(main_window)
    assert len(configurable) > 50  # guard against the filter matching nothing

    mismatched = {
        name: (
            getattr(main_window, name).shortcut().toString(),
            series.getOption(name),
        )
        for name in configurable
        if name not in KNOWN_UNAPPLIED_SHORTCUTS
        and getattr(main_window, name).shortcut()
        != QKeySequence(series.getOption(name))
    }
    assert mismatched == {}


def test_set_hosts_carries_its_shortcut_from_a_cold_settings_store(
    main_window, local_series_settings
):
    """`Set hosts...` binds `Ctrl+Shift+H` with nothing stored and no dialog.

    The regression this pins is specifically a COLD one. `sethosts_act` was
    built with `""`, so its key was dead on a fresh install. But
    `resetShortcuts` writes straight onto the built QAction, so anyone who
    opened the shortcuts dialog and pressed OK repaired it in passing and could
    never reproduce the report. The repair lasted until the next
    `createContextMenus`, which re-applied the `""`.

    So this asserts the state a new user actually gets: an empty
    `DictSettingsStore` (the option resolves to its default, nothing stored),
    menus built by the real `createContextMenus`, and no dialog anywhere in the
    path. Reverting the one-word fix fails the first assertion, not the second.

    No other action in this window claims `Ctrl+Shift+H` (the 3D scene popup
    hardcodes it for `organize_act`, but that is a different top-level window,
    and the object list's copy of this row is built without the key on purpose).
    The two tests below are what hold that second half up: this one builds no
    dock, so on its own it cannot see an ambiguous pair.
    """
    series = local_series_settings(main_window)  # cold store + real menu rebuild

    assert main_window.sethosts_act.shortcut() == QKeySequence("Ctrl+Shift+H"), (
        "Set hosts... does not carry its default key from a cold store; the "
        "construction site in get_context_menu_list_obj is passing '' again"
    )
    assert series.getOption("sethosts_act") == "Ctrl+Shift+H"

    # and it survives the rebuild that used to wipe the dialog's repair
    main_window.createContextMenus()

    assert main_window.sethosts_act.shortcut() == QKeySequence("Ctrl+Shift+H")


# --- the object list is a dock in this window, so it shares its shortcut scope -
#
# `ObjectTableWidget` is a `QDockWidget` parented to `MainWindow`, and it builds
# its right-click menu from the same `get_context_menu_list_obj` the field uses.
# `newAction` adds every action it builds to the widget it is handed, so a row
# that carries a key produces two QActions with the same sequence and the default
# `Qt.WindowShortcut` context inside one top-level window. Qt calls that pair
# ambiguous and fires NEITHER, so a key that works with the list closed goes dead
# the moment the list is opened. That is invisible to every test above, all of
# which build no dock.
#
# Both tests below open the list, because that is the only state the defect
# exists in.


def _window_shortcut_counts(window):
    """How many actions in `window` claim each non-empty key sequence."""
    counts = defaultdict(list)
    seen = set()
    for widget in [window] + window.findChildren(QWidget):
        for action in widget.actions():
            if id(action) in seen:
                continue
            seen.add(id(action))
            sequence = action.shortcut().toString()
            if sequence:
                counts[sequence].append(action.text())
    return counts


def test_the_open_object_list_adds_no_second_claimant_to_any_shortcut(main_window):
    """Opening the object list leaves every key sequence with one owner.

    The structural half of the claim. The list's menu is the field's menu built
    a second time onto a dock in the same window, so any row that carries a key
    on the list side is a duplicate claim by construction. Asserted over the
    whole window rather than over the two known rows, so a keyed row added to
    this menu later is caught by the same test.
    """
    before = {
        sequence: texts
        for sequence, texts in _window_shortcut_counts(main_window).items()
        if len(texts) > 1
    }
    assert before == {}, f"the window is already ambiguous before any list: {before}"

    main_window.field.openList("object")

    after = {
        sequence: texts
        for sequence, texts in _window_shortcut_counts(main_window).items()
        if len(texts) > 1
    }
    assert after == {}, (
        "the open object list claims a key the main window already owns, so Qt "
        f"will fire neither action: {after}"
    )


def test_the_object_menu_keys_still_fire_with_the_object_list_open(main_window):
    """`Ctrl+Shift+H` and `Ctrl+Shift+D` reach their slots with the list docked.

    The behavioral half, and the reason the fix is a dropped key on one side
    rather than a shortcut context on the other: the surviving copy is on the
    main window with `Qt.WindowShortcut`, so it is in scope for the dock too.
    Pressed twice, once with focus on the window and once with focus inside the
    list's own view, because a per-widget context would pass the first and fail
    the second.

    Both handlers are replaced before the menus are built. `setHosts` opens a
    dialog and `addTo3D` opens the 3D scene, and neither is what is under test.
    """
    fired = []
    main_window.field.setHosts = lambda *a, **k: fired.append("setHosts")
    main_window.field.addTo3D = lambda *a, **k: fired.append("addTo3D")
    main_window.createContextMenus()

    main_window.field.openList("object")
    table = main_window.field.table_manager.tables["object"][0]

    def press(target):
        fired.clear()
        QTest.keySequence(target, QKeySequence("Ctrl+Shift+H"))
        QTest.keySequence(target, QKeySequence("Ctrl+Shift+D"))
        return list(fired)

    main_window.setFocus()
    assert press(main_window) == ["setHosts", "addTo3D"], (
        "an object menu key did not fire with the object list open; the list is "
        "claiming it too and Qt is refusing the ambiguous pair"
    )

    table.table.setFocus()
    assert press(table.table) == ["setHosts", "addTo3D"], (
        "an object menu key did not fire while the object list held focus"
    )


# --- GATING: enabled state, no modal loop needed ------------------------------

def test_a_trace_row_in_the_menubar_is_gated_by_the_selection(main_window):
    """`Edit > Cut` follows `checkActions`, read at its menu path.

    `test_main_window_headless.py` asserts the same gate by identity over
    `trace_actions`. This asserts it at the path, which is the other half: an
    action correctly disabled is no use if the row the user clicks is a different
    object.
    """
    section = main_window.field.section
    expected = _cpp(main_window.cut_act)
    row = menu_action(main_window.menubar, "Edit > Cut")
    assert _cpp(row) == expected

    section.selected_traces.clear()
    section.selected_ztraces.clear()
    main_window.checkActions()
    assert row.isEnabled() is False

    contour_name = next(iter(section.contours))
    section.selected_traces.append(section.contours[contour_name][0])
    main_window.checkActions()
    assert row.isEnabled() is True


def test_an_export_format_with_no_backing_library_is_disabled(main_window):
    """A mesh format whose optional dependency is missing is grayed out.

    `disable_unavailable_export_formats` runs inside `createContextMenus`, so it
    has no effect on the menu definition and nothing short of the real widget
    tree can observe it. Collada needs `pycollada`, which the test extra does not
    install, so the row is present, relabelled, and disabled. The formats that
    need nothing beyond `trimesh` stay enabled, which is what makes this a gate
    rather than a blanket.
    """
    export_menu = submenu_at(main_window.field_menu, "Object > 3D > Export mesh as")
    assert export_menu is not None

    paths = menu_leaf_paths(export_menu)

    assert paths["Collada (.dae) (not installed)"].isEnabled() is False
    assert paths["STL (.stl)"].isEnabled() is True


# --- FIRING: a real key press -------------------------------------------------

def test_a_real_key_press_reaches_the_slot_and_opens_the_object_list(
    main_window, qapp
):
    """Pressing the object-list key builds the object list.

    End to end, with nothing stubbed on the path: synthetic key event, Qt's
    shortcut map, the `QAction`, `MainWindow.openObjectList`, a real
    `ObjectTableWidget` registered with the table manager. The assertion is on
    the widget that appeared, not on a signal count, so a shortcut that fires and
    does nothing fails here.
    """
    manager = main_window.field.table_manager
    assert manager.tables["object"] == []

    QTest.keySequence(main_window, main_window.objectlist_act.shortcut())
    qapp.processEvents()

    assert len(manager.tables["object"]) == 1


def test_the_key_that_fires_an_action_is_the_one_its_option_names(
    main_window, main_window_dialogs, local_series_settings, qapp
):
    """Rebind the option, and the old key stops working.

    The test that separates FIRING from a `trigger()` call wearing its name: a
    direct `trigger()` cannot tell two different key presses apart, so it cannot
    pass the third block below.

    `goto_act` because its slot ends in a `QuickDialog` that
    `main_window_dialogs` records by title, which makes "the slot ran" a fact
    about the app rather than about a counter attached to the signal.
    """
    series = local_series_settings(main_window)
    default_sequence = QKeySequence(series.getOption("goto_act"))
    rebound = QKeySequence("Ctrl+Alt+Shift+G")
    assert default_sequence != rebound

    main_window_dialogs.dialogs.clear()
    QTest.keySequence(main_window, default_sequence)
    qapp.processEvents()
    assert main_window_dialogs.dialogs == ["Go To Section"]

    series.setOption("goto_act", rebound.toString())
    main_window.createMenuBar()
    assert main_window.goto_act.shortcut() == rebound

    main_window_dialogs.dialogs.clear()
    QTest.keySequence(main_window, rebound)
    qapp.processEvents()
    assert main_window_dialogs.dialogs == ["Go To Section"]

    main_window_dialogs.dialogs.clear()
    QTest.keySequence(main_window, default_sequence)
    qapp.processEvents()
    assert main_window_dialogs.dialogs == []


def test_two_actions_sharing_a_sequence_fire_neither(
    main_window, main_window_dialogs, qapp
):
    """An ambiguous binding is not "first one wins", it is nothing.

    The platform behavior the app's one-shortcut-per-sequence rule rests on, and
    the reason a duplicate is a silent loss of a working key rather than a
    cosmetic clash. Qt logs `QAction::event: Ambiguous shortcut overload` and
    triggers neither action.

    Pinned here rather than taken on trust, because the rule it justifies is
    invisible in the source: a second menu row deliberately left without a
    shortcut reads as an oversight unless this is written down somewhere that
    fails when it changes.
    """
    sequence = main_window.goto_act.shortcut()
    assert not sequence.isEmpty()

    rival_fired = []
    rival = QAction("rival", main_window)
    rival.setShortcut(sequence)
    rival.triggered.connect(lambda: rival_fired.append(1))
    main_window.addAction(rival)
    qapp.processEvents()

    main_window_dialogs.dialogs.clear()
    QTest.keySequence(main_window, sequence)
    qapp.processEvents()

    assert rival_fired == []
    assert main_window_dialogs.dialogs == []

    main_window.removeAction(rival)
    qapp.processEvents()

    main_window_dialogs.dialogs.clear()
    QTest.keySequence(main_window, sequence)
    qapp.processEvents()
    assert main_window_dialogs.dialogs == ["Go To Section"]


def test_no_two_actions_on_the_window_share_a_shortcut(main_window):
    """Every bound sequence on the window is bound exactly once.

    The invariant that makes a new shortcut safe to add, and the one that had
    been checked by reading a list by hand. Given the preceding test, a collision
    here is a key that does nothing for either action rather than a key that does
    the wrong thing.

    Compares normalized portable text rather than the display strings, so one
    sequence written two ways still collides.
    """
    by_sequence = defaultdict(list)
    for action in main_window.actions():
        sequence = action.shortcut()
        if not sequence.isEmpty():
            by_sequence[sequence.toString(QKeySequence.PortableText)].append(
                action.text()
            )

    assert len(by_sequence) > 100  # guard: the window really is populated
    duplicates = {
        sequence: texts for sequence, texts in by_sequence.items()
        if len(texts) > 1
    }
    assert duplicates == {}


# --- the shortcuts dialog, built but never exec'd ------------------------------
#
# `ShortcutsDialog` is where a shortcut becomes user-configurable, and an action
# missing from it has no shortcut a user can assign. Constructing it needs a real
# MainWindow (it reads `mainwindow.<act_name>` for every row), so all of this was
# previously a click-through.


def _shortcut_rows():
    """The `_act` names `ShortcutsDialog` builds an editable row for."""
    from PyReconstruct.modules.gui.dialog.shortcuts import help_shortcuts

    return [
        tuple(item)[0] for item in help_shortcuts
        if item is not None and not isinstance(item, str)
        and tuple(item)[0].endswith("_act")
    ]


def test_the_shortcuts_dialog_builds_against_the_real_window(main_window):
    """It constructs, and every editable row is prefilled from the option.

    Construction only; `exec()` is the modal part and is not called. What that
    still covers is the whole of `__init__`, which is where a row naming a
    nonexistent action raises and where the prefill happens.
    """
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog

    dialog = ShortcutsDialog(main_window, main_window.series)
    try:
        assert set(dialog.act_widgets) == set(_shortcut_rows())
        for act_name, widget in dialog.act_widgets.items():
            assert widget.keySequence() == QKeySequence(
                main_window.series.getOption(act_name)
            )
    finally:
        dialog.deleteLater()


def test_every_shortcuts_dialog_row_names_an_action_the_window_has(main_window):
    """No row can name an action that is not there.

    `ShortcutsDialog.__init__` does a bare `getattr(self.mainwindow, sc)` with no
    default, so a row for an action that was renamed or removed raises
    `AttributeError` and the dialog cannot open at all.
    """
    for act_name in _shortcut_rows():
        action = getattr(main_window, act_name, None)
        assert isinstance(action, QAction), f"{act_name} is not an action"


def test_a_configurable_shortcut_missing_from_the_dialog_is_unassignable(
    main_window,
):
    """Every option-backed shortcut has a row, bar one known gap.

    A shortcut stored as an option but absent from `help_shortcuts` cannot be
    changed from inside the app, because the dialog only writes back the rows it
    built.

    `toggleztraces_act` is that gap today. It is recorded rather than fixed:
    adding a row is a user-visible change to a dialog, and this is a test change.
    A *second* name appearing in this set is what the assertion is for.
    """
    known_gaps = {"toggleztraces_act"}
    rows = set(_shortcut_rows())

    assert set(_configurable_actions(main_window)) - rows == known_gaps


def test_the_dialog_refuses_a_sequence_a_static_action_already_owns(
    main_window, monkeypatch
):
    """Rebinding onto a hardcoded shortcut is rejected, with a notice.

    `accept` collects the sequences held by actions the dialog cannot edit and
    refuses an entry that duplicates one. `Align by correlation` is such an
    action: its `Ctrl+\\` is written into `menubar.py` rather than stored as an
    option, so no row exists for it and nothing else stops a user from typing it
    into the box for something else.

    Given `test_two_actions_sharing_a_sequence_fire_neither`, letting this
    through would cost the user both keys.
    """
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog
    from PyReconstruct.modules.gui.dialog import shortcuts as shortcuts_module

    notices = []
    monkeypatch.setattr(
        shortcuts_module, "notify",
        lambda message, *args, **kwargs: notices.append(message),
    )

    static = main_window.aligncorrelation_act.shortcut()
    assert static.toString() == "Ctrl+\\"

    dialog = ShortcutsDialog(main_window, main_window.series)
    try:
        dialog.act_widgets["goto_act"].setKeySequence(static)
        dialog.accept()

        assert len(notices) == 1
        assert "used more than once" in notices[0]
        assert dialog.result() == 0  # not accepted
    finally:
        dialog.deleteLater()


def test_rebinding_home_survives_the_next_menubar_rebuild(
    main_window, local_series_settings
):
    """A rebind of `Home` must still be there after `createMenuBar` runs again.

    `homeview_act` has had a `default_settings.py` entry and an editable dialog
    row since `2cea11bd`, but that commit left its `menubar.py` tuple carrying
    the literal `"Home"` while converting 44 others to pass the series. Of the 53
    defaults it added, `homeview_act` was the only menu-tuple action to get a
    default and keep its literal. `newAction` takes the string branch for a
    literal, so every rebind was stored and then overwritten on the next
    `createMenuBar`, which runs on every series open.

    Passing the series takes the `kbd.getOption(act_name)` branch instead, which
    is what the other configurable keys in this file already do.
    """
    series = local_series_settings(main_window)

    assert main_window.homeview_act.shortcut().toString() == "Home", (
        "the shipped default should still bind Home out of the box"
    )

    series.setOption("homeview_act", "Ctrl+Alt+F9")
    main_window.resetShortcuts()
    main_window.createMenuBar()

    assert main_window.homeview_act.shortcut() == QKeySequence("Ctrl+Alt+F9"), (
        "the menubar literal is still overwriting the user's choice"
    )


def test_moving_home_off_its_action_frees_it_for_another_command(
    main_window, local_series_settings, monkeypatch
):
    """Move `homeview_act` elsewhere, give `Home` away, and keep both keys.

    This is the end-to-end failure the literal caused. `accept` reserves each
    editable row as it walks them, so `Home` is refused for a second command
    while `homeview_act` still holds it, and released once it does not. Before
    the conversion the release was a trap: the dialog accepted the reassignment,
    then `createMenuBar` put the literal `Home` back on `homeview_act`, so two
    actions held `Home` and (see
    `test_two_actions_sharing_a_sequence_fire_neither`) neither fired. The user
    lost the command they had just bound as well as the one they moved.
    """
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog
    from PyReconstruct.modules.gui.dialog import shortcuts as shortcuts_module

    series = local_series_settings(main_window)

    notices = []
    monkeypatch.setattr(
        shortcuts_module, "notify",
        lambda message, *args, **kwargs: notices.append(message),
    )

    dialog = ShortcutsDialog(main_window, series)
    try:
        assert "homeview_act" in dialog.act_widgets, (
            "Home is configurable, so it must have an editable row"
        )

        dialog.act_widgets["homeview_act"].setKeySequence(
            QKeySequence("Ctrl+Alt+F9")
        )
        dialog.act_widgets["goto_act"].setKeySequence(QKeySequence("Home"))
        dialog.accept()

        assert notices == [], "Home is free once its own row gives it up"
        assert dialog.result() == 1

        for name, widget in dialog.act_widgets.items():
            series.setOption(name, widget.keySequence().toString())
    finally:
        dialog.deleteLater()

    main_window.resetShortcuts()
    main_window.createMenuBar()

    assert main_window.goto_act.shortcut() == QKeySequence("Home")
    assert main_window.homeview_act.shortcut() == QKeySequence("Ctrl+Alt+F9")


def test_home_is_still_reserved_while_its_own_row_holds_it(
    main_window, monkeypatch
):
    """The duplicate check covers `Home` like any other configurable key."""
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog
    from PyReconstruct.modules.gui.dialog import shortcuts as shortcuts_module

    notices = []
    monkeypatch.setattr(
        shortcuts_module, "notify",
        lambda message, *args, **kwargs: notices.append(message),
    )

    dialog = ShortcutsDialog(main_window, main_window.series)
    try:
        dialog.act_widgets["goto_act"].setKeySequence(QKeySequence("Home"))
        dialog.accept()

        assert len(notices) == 1
        assert "used more than once" in notices[0]
        assert dialog.result() == 0  # not accepted
    finally:
        dialog.deleteLater()
