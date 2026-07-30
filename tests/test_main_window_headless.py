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
    without a display.
    """
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


# --- the recent-series submenu ------------------------------------------------

def test_clear_recents_rebuilds_the_menubar_from_inside_its_own_action(
    main_window, tmp_path
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

    main_window.series.setOption(
        "recently_opened_series", [str(first), str(second)]
    )
    main_window.createMenuBar()

    assert main_window.series.getOption("recently_opened_series") == [
        str(first), str(second)
    ]
    rows = [action.text() for action in main_window.openrecentmenu.actions()]
    assert str(first) in rows and str(second) in rows

    main_window.clearrecents_act.trigger()

    assert main_window.series.getOption("recently_opened_series") == []
    # the submenu was rebuilt in place, not left showing the stale rows
    assert [
        action.text() for action in main_window.openrecentmenu.actions()
    ] == ["Clear recents"]


def test_recent_series_prunes_paths_that_no_longer_exist(main_window, tmp_path):
    """A remembered series that has been deleted is dropped, not listed.

    `getOpenRecentMenu` prunes as a side effect of building the submenu, so this
    needs the menubar actually rebuilt to observe it.
    """
    present = tmp_path / "still_here.jser"
    present.write_text("{}")
    missing = tmp_path / "deleted.jser"

    main_window.series.setOption(
        "recently_opened_series", [str(present), str(missing)]
    )
    main_window.createMenuBar()

    assert main_window.series.getOption("recently_opened_series") == [
        str(present)
    ]
    rows = [action.text() for action in main_window.openrecentmenu.actions()]
    assert str(missing) not in rows
