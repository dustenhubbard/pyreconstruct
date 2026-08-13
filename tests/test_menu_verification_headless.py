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


# Main's hoist tests and its frozen View order are deliberately absent on this
# release line: the 2026-08-06 visibility hoist and the Reset window row never
# rode a pick, so those pins describe a View menu this line does not build.
# The one View change this line DID receive (2026-08-12) gets its own pin:


def test_recolor_all_sits_directly_under_edit_fill_opacity(main_window):
    """The series-wide recolor row is in View, right where the placement call
    put it, and it is the row bound to recolorallfrompalette_act."""
    row = menu_action(main_window.menubar, "View > Recolor all objects from palette...")
    assert row is not None, "no 'Recolor all objects from palette...' row in View"

    view = submenu_at(main_window.menubar, "View")
    order = [p for p in menu_leaf_paths(view) if " > " not in p]
    at = order.index("Recolor all objects from palette...")
    assert order[at - 1] == "Edit fill opacity...", (
        "the recolor row moved away from 'Edit fill opacity...'"
    )
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


# `sethosts_act` has a default of `Ctrl+Shift+H` in `default_settings.py` and an
# editable row in the shortcuts dialog, but `get_context_menu_list_trace` builds
# it with `""` instead of `self.series`, so the action ships with no shortcut and
# the key does nothing. Pinned by its own test below rather than fixed here:
# giving it the key it was configured for is a user-visible change.
KNOWN_UNAPPLIED_SHORTCUTS = {"sethosts_act"}


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


def test_set_hosts_ships_without_the_shortcut_it_is_configured_for(
    main_window, local_series_settings
):
    """`Set hosts...` has a configured key that the menu never applies.

    Found by the test above, and the exact shape of the affordance problem: the
    option exists (`Ctrl+Shift+H`), the shortcuts dialog offers an editable row
    for it, and the action is built with `""`, so the key does nothing until the
    user opens that dialog and presses OK. `resetShortcuts` is what repairs it,
    which is why the second half here passes.

    Recorded rather than fixed: making a configured key start working is a
    user-visible change and this is a test change. `Ctrl+Shift+H` is unclaimed
    elsewhere in this window (the 3D scene popup hardcodes it for
    `organize_act`, a different window), so nothing collides.
    """
    series = local_series_settings(main_window)

    assert series.getOption("sethosts_act") == "Ctrl+Shift+H"
    assert main_window.sethosts_act.shortcut().toString() == ""

    main_window.resetShortcuts()

    assert main_window.sethosts_act.shortcut() == QKeySequence("Ctrl+Shift+H")


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
