"""Tests that need the real top-level window.

Until now the suite could build the four data-list widgets against a stub main
window, but not `MainWindow` itself: opening a real `.jser` offscreen stalled on
the first of three startup prompts and had to be killed. Everything that only
the real window owns (the populated menubar, the context menus, `checkActions`,
the recent-series submenu) was therefore verified by hand.

The three blockers, all reached from `MainWindow.openSeries` and each confirmed
to stall on its own under `QT_QPA_PLATFORM=offscreen`:

  * `changeSrcDir(notify=True)` -> "Images Not Found", when
    `field.section_layer.image_found` is False and the images are not beside the
    `.jser`. The fixture series ships no images, so this is the first one hit.
  * `setSeriesCode(cancelable=False)` -> the "Series Code" `QuickDialog`, when
    the series has no code. Not cancelable, and wrapped in
    `while not code_is_valid`, so offscreen it cannot be answered *or* escaped.
  * `notifyNewEditor()` -> `notify()`, when the series has more than two
    alignments. `notify` does have an offscreen branch, but it ends in
    `input("Press Enter to continue...")`.

`user_is_present()` is the seam: the predicate `notify` and `notifyConfirm` were
already applying inline, named once and consulted at those sites too.

See the `main_window` fixture in `conftest.py` for what is real and what is
neutralized.
"""

import pytest

from PyReconstruct.modules.gui.utils import utils as gui_utils

pytestmark = pytest.mark.gui


# --- the seam ----------------------------------------------------------------

def test_user_is_present_false_offscreen(qapp):
    """Offscreen means nobody can answer a modal, and the seam says so.

    A QApplication exists (`qapp`) and the platform is `offscreen`, which is how
    the whole suite runs. If this ever returns True the startup prompts come
    back and `main_window` hangs, so it is worth asserting directly.
    """
    assert gui_utils.qt_offscreen is True
    assert gui_utils.user_is_present() is False


def test_user_is_present_true_on_a_real_platform(qapp, monkeypatch):
    """The interactive branch is still reachable, so production still prompts.

    `qt_offscreen` is read at call time, which is what makes this checkable
    without a display. `PYRECON_UNATTENDED` is the other half of the predicate
    and is cleared for the same reason: it is an environment variable, so a
    developer who exported it for a scripted GUI run would otherwise see this
    fail here rather than where they set it. See
    `tests/test_unattended_gui_prompts.py`.
    """
    monkeypatch.delenv(gui_utils.UNATTENDED_ENV_VAR, raising=False)
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)
    assert gui_utils.user_is_present() is True


def test_notify_new_editor_is_a_no_op_offscreen(main_window, main_window_dialogs):
    """`notifyNewEditor` returns before touching `notify` when nobody is there.

    The fixture series has more than two alignments, so on a real display this
    would show the multiple-alignments notice.
    """
    assert len(main_window.series.getAlignments()) > 2
    main_window_dialogs.notices.clear()
    main_window.notifyNewEditor()
    assert main_window_dialogs.notices == []


# --- construction ------------------------------------------------------------

def test_main_window_constructs_over_a_real_series(
    main_window, main_window_dialogs, series_jser
):
    """The window comes up fully, with no prompt raised on the way.

    The whole point of the fixture. Asserting on the pieces rather than just on
    "did not raise" so that a partially built window is a failure too.

    `main_window_dialogs` is installed before the window is built, so the
    emptiness of its three logs is the real regression guard: drop any of the
    `user_is_present()` guards in `openSeries` and the corresponding prompt is
    recorded here.
    """
    window = main_window

    assert window.series is not None
    assert window.series.isWelcomeSeries() is False
    assert window.series.jser_fp == str(series_jser)

    assert window.field is not None
    assert window.mouse_palette is not None
    assert window.menubar is not None
    assert window.actions_initialized is True

    # the startup prompts stayed down
    assert main_window_dialogs.message_boxes == []
    assert main_window_dialogs.dialogs == []
    assert main_window_dialogs.notices == []


def test_menubar_has_every_top_level_menu(main_window):
    """The real menubar is populated, in order.

    `test_menubar_labels.py` and friends check the menu *definition* (the dicts
    `return_menubar` builds). This checks the widget those dicts produced, which
    is a different failure: `populateMenuBar` silently dropping a menu.
    """
    titles = [action.text() for action in main_window.menubar.actions()]
    assert titles == [
        "File", "Edit", "Series", "Section", "Lists", "Alignments",
        "View", "Help",
    ]


def test_series_code_is_detected_without_prompting(main_window):
    """The regex fallback in `openSeries` still runs when the dialog does not.

    `openSeries` derives a code from the series name before offering the dialog.
    Guarding only the dialog keeps that, so the window comes up with a usable
    code rather than an empty one (per-series options are keyed by it).
    """
    assert main_window.series.code


# --- checkActions, the trace/ztrace gate -------------------------------------

def test_check_actions_disables_trace_actions_with_nothing_selected(main_window):
    """Nothing selected disables both the trace and the ztrace actions.

    `checkActions` is the enable/disable pass behind every context menu, and its
    first branch is an XOR: exactly one of traces/ztraces selected, or nothing is
    enabled. Reachable only from a real window, because the action objects are
    created by `createContextMenus`.
    """
    section = main_window.field.section
    section.selected_traces.clear()
    section.selected_ztraces.clear()

    main_window.checkActions()

    assert all(not action.isEnabled() for action in main_window.trace_actions)
    assert all(not action.isEnabled() for action in main_window.ztrace_actions)


def _select_one_trace(window):
    """Select the first trace on the field's current section. Returns it."""
    section = window.field.section
    contour_name = next(iter(section.contours))
    trace = section.contours[contour_name][0]
    section.selected_traces.clear()
    section.selected_ztraces.clear()
    section.selected_traces.append(trace)
    return trace


def test_check_actions_enables_trace_actions_with_a_trace_selected(main_window):
    """A selected trace (and no ztrace) enables the trace actions only.

    `pasteattributes_act` is the documented exception: the trace block enables
    it, then the clipboard block further down disables it again because there is
    nothing to paste. Two passes over the same action in one call, which is only
    observable on a real window.

    Note that `trace_actions` is a mixed list of `QAction` and `QMenu`, which is
    why membership is compared by identity rather than by label.
    """
    _select_one_trace(main_window)
    assert main_window.field.clipboard == []

    main_window.checkActions()

    disabled = [
        action for action in main_window.trace_actions
        if not action.isEnabled()
    ]
    assert disabled == [main_window.pasteattributes_act]
    assert all(not action.isEnabled() for action in main_window.ztrace_actions)


def test_paste_attributes_follows_the_clipboard_not_the_selection(main_window):
    """`pasteattributes_act` needs a selected trace *and* a full clipboard.

    Pins the interaction between `checkActions`' trace block and its clipboard
    block: the second overrides the first, so filling the clipboard is what
    actually enables the action.
    """
    trace = _select_one_trace(main_window)

    main_window.field.clipboard = [trace.copy()]
    main_window.checkActions()
    assert main_window.pasteattributes_act.isEnabled() is True
    assert main_window.paste_act.isEnabled() is True

    main_window.field.clipboard = []
    main_window.checkActions()
    assert main_window.pasteattributes_act.isEnabled() is False
    assert main_window.paste_act.isEnabled() is False


def test_check_actions_is_inert_before_actions_exist(main_window):
    """`checkActions` short-circuits on `actions_initialized`.

    It is called from field interactions, some of which can fire while a series
    is still opening. The guard is the reason that is safe, so pin it: with the
    flag down the call must not raise even though the actions are real.
    """
    main_window.actions_initialized = False
    main_window.checkActions()  # must not raise
    main_window.actions_initialized = True


def test_restore_previous_visibility_is_disabled_until_an_isolate_runs(main_window):
    """"Restore previous visibility" is unreachable with no snapshot behind it.

    Only reachable on a real window: the action object is created by
    `createContextMenus`, and the field object menu is populated onto the window,
    so `mainwindow.restorevisibility_act` is the copy the field's right-click
    shows. `checkActions` runs on every context-menu open, which is what makes a
    build-once menu track runtime state.

    The alternative to disabling is an enabled row that silently does nothing,
    which teaches the user the command is broken rather than that it is not
    applicable yet.
    """
    field = main_window.field
    assert field.visibility_snapshot is None, "a fresh field has no snapshot"

    main_window.checkActions()
    assert not main_window.restorevisibility_act.isEnabled()

    ## the shape hideOtherObjects leaves behind, without driving the isolate
    field.visibility_snapshot = {"whatever": {field.section.n: [False]}}
    main_window.checkActions()
    assert main_window.restorevisibility_act.isEnabled()

    ## and the restore consumes it, so the row goes back to disabled
    field.visibility_snapshot = None
    main_window.checkActions()
    assert not main_window.restorevisibility_act.isEnabled()


def test_the_object_list_has_its_own_two_copies_of_the_restore_action(main_window):
    """Three surfaces offer the command and each has its own QAction object.

    The object list carries two of them: `restorevisibility_act` in its right-click
    menu and `restorevisibility_act1` in its own `Selection` menubar menu, which is
    where "Hide other objects" is also offered. Pinned because the failure mode is
    invisible: the field copy would track state correctly while a list copy stayed
    at whatever it was built with.
    """
    main_window.field.openList("object")
    table = main_window.field.table_manager.tables["object"][-1]

    copies = [
        main_window.restorevisibility_act,
        table.restorevisibility_act,
        table.restorevisibility_act1,
    ]
    assert len({id(a) for a in copies}) == 3
    assert all(a.text() == "Restore previous visibility" for a in copies)


def test_the_object_lists_selection_menu_carries_the_same_visibility_labels(main_window):
    """The third surface, previously pinned nowhere.

    The object list's own `Selection` menubar menu duplicates three visibility
    commands with `_act1` names, and it said `Show all objects` after the context
    menu's copy became `Unhide all objects`. One verb means one thing on every
    surface, so this pins the labels and the pairing of the isolate with its
    inverse.
    """
    main_window.field.openList("object")
    table = main_window.field.table_manager.tables["object"][-1]

    labels = [
        a.text() if not a.isSeparator() else "-----"
        for a in table.selectionmenu.actions()
    ]
    assert labels == [
        "Invert selection",
        "-----",
        "Hide other objects",
        "Restore previous visibility",
        "Hide all objects",
        "Unhide all objects",
    ]


def test_the_object_lists_menubar_restore_follows_the_live_snapshot(main_window):
    """Driven through the real signal, not by calling the sync helper.

    A menubar menu is always on screen, so `aboutToShow` is its equivalent of the
    context menu's open event. Emitting it is what a user opening `Selection` does.
    """
    main_window.field.openList("object")
    table = main_window.field.table_manager.tables["object"][-1]

    main_window.field.visibility_snapshot = None
    table.selectionmenu.aboutToShow.emit()
    assert not table.restorevisibility_act1.isEnabled()

    main_window.field.visibility_snapshot = {"a": {0: [True]}}
    table.selectionmenu.aboutToShow.emit()
    assert table.restorevisibility_act1.isEnabled()

    main_window.field.visibility_snapshot = None
    table.selectionmenu.aboutToShow.emit()
    assert not table.restorevisibility_act1.isEnabled()


def test_the_object_lists_context_menu_restore_follows_the_live_snapshot(main_window):
    """The list's right-click copy, through `contextMenuEvent` itself.

    Driven with a real `QContextMenuEvent` and nothing selected: the base class
    returns before exec'ing the menu, so the test does not block on a modal, and
    that early-return path is exactly the one that must still have resynced. The
    event must be a real one -- `DataTable.contextMenuEvent` hands it to Qt, which
    segfaults on None.
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

    main_window.field.openList("object")
    table = main_window.field.table_manager.tables["object"][-1]
    table.table.clearSelection()
    assert not table.getSelected(), "an empty selection is what keeps this safe"

    def right_click():
        table.contextMenuEvent(QContextMenuEvent(
            QContextMenuEvent.Mouse, QPoint(1, 1), QPoint(1, 1)
        ))

    main_window.field.visibility_snapshot = None
    right_click()
    assert not table.restorevisibility_act.isEnabled()

    main_window.field.visibility_snapshot = {"a": {0: [True]}}
    right_click()
    assert table.restorevisibility_act.isEnabled()


# --- the recent-series submenu ------------------------------------------------

@pytest.fixture
def own_recents(main_window):
    """`main_window`, with the recents option scoped to this test alone.

    `recently_opened_series` is a *computer*-scoped option: `Series.setOption`
    resolves it to `Series.qsettings_defaults`, so it is addressed with
    `code=None` and lands in `QSettings("KHLab", "PyReconstruct")` under a bare
    key. That is one machine-wide slot shared by every reader on the box, which
    makes these two tests read and write state that nothing in the test session
    owns. Three consequences, the first two measured rather than argued:

      * Concurrent runs corrupt each other. Two `pytest` processes on one
        machine interleave `setOption` and `getOption` on the same key, and the
        loser reads the other process' value. Measured on this file: four
        concurrent `pytest tests/test_main_window_headless.py -k recent`
        processes, 11 of 12 test outcomes failed, one with
        `assert [] == [.../recent_one.jser, .../recent_two.jser]` -- the `[]`
        being another process' "Clear recents" landing between this process'
        write and its read. Ordinary for a machine running more than one
        checkout, and it presents as an unreproducible flake.
      * Every run edits the developer's own preferences. `openSeries` calls
        `addToRecentSeries`, so building `main_window` prepends a `tmp_path`
        `.jser` to their real recents list, and these tests then overwrite it.
        Measured by reading the key back through `QSettings` before and after a
        run: ten entries, every one of them a pytest `tmp_path`, which is the
        whole list (`addToRecentSeries` caps it at ten). Read it with `QSettings`
        and not `defaults read`: the domain on disk is `com.khlab.PyReconstruct`,
        and `defaults` writes to the name it is given rather than the name that
        exists, so a mixed-case `com.KHLab.PyReconstruct` reads through but
        writes somewhere the application never looks.
      * The result depends on what the store already held. Not observed to fail
        on its own here (the file passes 12 of 12 alone, and under `-m gui` in 8
        shuffled orders), because each test writes the option before it reads it.
        A test that is correct only because of the order of two statements is one
        edit away from not being.

    `DictSettingsStore` is the seam's own answer and the idiom the rest of the
    suite already uses for this (`test_menubar_labels.py`,
    `test_update_channel_option.py`, `test_curation_restore_assignee.py`). It is
    a per-test, in-memory store, so the option cannot be seen or written by
    anything outside the test.

    Injected after the window is built rather than before, on purpose. Before
    would also cover `openSeries`' own `addToRecentSeries` call, and it would
    mean the whole startup path read every one of its ~100 options out of an
    empty store instead of the developer's real one, which changes what
    `test_main_window_constructs_over_a_real_series` and the `checkActions` tests
    are exercising. The coupling being removed is between the *assertions* and
    the machine, and those all run after this point.

    Nothing about what these tests verify changes. The menubar, the submenu, the
    `QAction`, `clearRecentSeries` and `getOpenRecentMenu`'s pruning are all the
    real ones; only the backing store for one option is private.
    """
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore

    main_window.series.setSettingsStore(DictSettingsStore())
    return main_window


def test_clear_recents_rebuilds_the_menubar_from_inside_its_own_action(
    own_recents, tmp_path
):
    """"Clear recents" rebuilds the menubar while its own action is running.

    `clearRecentSeries` calls `createMenuBar`, which calls `menubar.clear()`. The
    `QAction` being triggered belongs to a submenu of that menubar, so the slot
    destroys the object that invoked it. Nothing in the suite had ever exercised
    it, and a use-after-free here is a crash rather than an exception.

    It survives. This test is what keeps it that way: a later refactor that
    rebuilds the menubar less carefully fails here instead of segfaulting on a
    user's machine.
    """
    first = tmp_path / "recent_one.jser"
    second = tmp_path / "recent_two.jser"
    for path in (first, second):
        path.write_text("{}")  # must exist; getOpenRecentMenu prunes missing paths

    own_recents.series.setOption(
        "recently_opened_series", [str(first), str(second)]
    )
    own_recents.createMenuBar()

    assert own_recents.series.getOption("recently_opened_series") == [
        str(first), str(second)
    ]
    rows = [action.text() for action in own_recents.openrecentmenu.actions()]
    assert str(first) in rows and str(second) in rows

    own_recents.clearrecents_act.trigger()

    assert own_recents.series.getOption("recently_opened_series") == []
    # the submenu was rebuilt in place, not left showing the stale rows
    assert [
        action.text() for action in own_recents.openrecentmenu.actions()
    ] == ["Clear recents"]


def test_recent_series_prunes_paths_that_no_longer_exist(own_recents, tmp_path):
    """A remembered series that has been deleted is dropped, not listed.

    `getOpenRecentMenu` prunes as a side effect of building the submenu, so this
    needs the menubar actually rebuilt to observe it.
    """
    present = tmp_path / "still_here.jser"
    present.write_text("{}")
    missing = tmp_path / "deleted.jser"

    own_recents.series.setOption(
        "recently_opened_series", [str(present), str(missing)]
    )
    own_recents.createMenuBar()

    assert own_recents.series.getOption("recently_opened_series") == [
        str(present)
    ]
    rows = [action.text() for action in own_recents.openrecentmenu.actions()]
    assert str(missing) not in rows


def test_the_recents_tests_own_the_option_they_assert_on(own_recents):
    """The two tests above cannot see, or be seen by, anything outside them.

    Without this the isolation is one careless edit from being undone: swapping
    `own_recents` back to `main_window` in either test above reintroduces the
    machine-wide coupling and both tests still pass on a quiet machine, which is
    exactly how it got here.

    The `default_settings` assertion covers the other direction: an in-memory
    store starts empty, and `getOption`'s store-miss branch returns
    `defaults[option_name]` *by reference*, so a miss on a container option hands
    out the module-level `default_settings` object itself. Callers that mutate the
    returned list in place (`addToRecentSeries`: `remove`, `insert`, `pop`) would
    then edit the process-wide default every later `Series` reads. The two tests
    above happen to write the option before they read it, so the miss branch is
    never reached and this holds; it is asserted rather than assumed because that
    is a property of the order of two statements, not of the fixture.
    """
    from PyReconstruct.modules.backend.settings_store import (
        DictSettingsStore, QSettingsStore,
    )
    from PyReconstruct.modules.datatypes.default_settings import default_settings

    store = own_recents.series._settingsStore()
    assert isinstance(store, DictSettingsStore)
    assert not isinstance(store, QSettingsStore)

    assert default_settings["recently_opened_series"] == []

    # and the option really does resolve to the private store, computer scope
    own_recents.series.setOption("recently_opened_series", ["/nonexistent.jser"])
    assert store.contains(None, "recently_opened_series")
    assert own_recents.series.getOption(
        "recently_opened_series"
    ) == ["/nonexistent.jser"]
