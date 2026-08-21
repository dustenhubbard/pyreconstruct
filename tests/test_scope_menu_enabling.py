"""When each entity scope's commands are live, and why the z-trace menu was not.

The report: "the z-trace submenu is empty so i don't know what was originally
intended to go here either". It holds nine rows. Every one of them was greyed
out unless the right-click had landed on an already-selected z-trace AND no
trace was selected at the same time, which is a narrow enough window that the
menu read as empty rather than as disabled.

Two rules produced that, and neither survived being written down:

  * An exclusive-or over the two selections. With traces AND z-traces both
    selected, BOTH scopes were switched off -- selecting more things made fewer
    commands available. Its only justification was the single top-level
    relabelling edit row, which names one entity and so needs an unambiguous
    winner. That row is one action; it was disabling two whole menus to protect
    itself.
  * A clicked-item test on the context-menu path: the scope was live only if
    the item under the cursor was in that scope's selection. But no command in
    either scope reads the clicked item. They are all wrapped in
    trace_function / ztrace_function, which take the selection (or the focused
    data table's rows) and return early when it is empty -- see
    test_ztrace_commands_read_the_selection_not_the_click below, which pins that
    against the real source rather than trusting this comment.

The rule now: a scope is live when that scope has a selection. The edit row
keeps the exclusive-or, alone, because it genuinely cannot serve a mixed one.
"""
import inspect

import pytest

from PyReconstruct.modules.gui.main.context_menu_list import (
    edit_selected_entity,
    edit_selected_label,
    scope_menus_enabled,
)


# --------------------------------------------------------------------------- #
# the scope rule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("traces,ztraces,expected", [
    # nothing selected: neither scope has anything to act on
    ([], [], (False, False)),
    # one kind selected: that scope only
    (["a"], [], (True, False)),
    ([], ["z"], (False, True)),
    # BOTH selected: both scopes live. This is the case the exclusive-or got
    # backwards -- it disabled both, so adding a selection removed commands.
    (["a"], ["z"], (True, True)),
])
def test_a_scope_is_live_when_it_has_a_selection(traces, ztraces, expected):
    assert scope_menus_enabled(traces, ztraces) == expected


def test_the_mixed_selection_no_longer_disables_everything():
    """The regression this fix is for, stated on its own.

    Selecting a z-trace while a trace is selected used to leave the user with
    both entity menus greyed. Nothing about either selection stopped being
    actionable when the other appeared.
    """
    trace_live, ztrace_live = scope_menus_enabled(["a"], ["z"])
    assert trace_live and ztrace_live


def test_the_clicked_item_is_not_part_of_the_rule():
    """scope_menus_enabled takes the two selections and nothing else.

    The old gate also took the clicked item and whether a context menu was being
    built. Keeping the signature honest is what stops that creeping back: there
    is no parameter to consult.
    """
    params = list(inspect.signature(scope_menus_enabled).parameters)
    assert params == ["selected_traces", "selected_ztraces"]


# --------------------------------------------------------------------------- #
# the one row that still needs an unambiguous winner
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("traces,ztraces,expected", [
    ([], [], None),
    (["a"], [], "trace"),
    ([], ["z"], "ztrace"),
    # a single action with a single label has nothing honest to say here
    (["a"], ["z"], None),
])
def test_the_edit_row_keeps_the_exclusive_or(traces, ztraces, expected):
    assert edit_selected_entity(traces, ztraces) == expected


def test_the_edit_row_goes_neutral_and_disabled_on_a_mixed_selection():
    """End to end through the label decision, so the pair is pinned together."""
    text, enabled = edit_selected_label(edit_selected_entity(["a"], ["z"]))
    assert (text, enabled) == ("Edit attributes...", False)


def test_the_edit_row_still_names_the_entity_when_there_is_one():
    assert edit_selected_label(edit_selected_entity(["a"], [])) == (
        "Edit trace attributes...", True,
    )
    assert edit_selected_label(edit_selected_entity([], ["z"])) == (
        "Edit z-trace attributes...", True,
    )


# --------------------------------------------------------------------------- #
# the premise the whole fix rests on
# --------------------------------------------------------------------------- #
def test_ztrace_commands_read_the_selection_not_the_click():
    """Every z-trace command is wrapped in ztrace_function, which resolves its
    targets from the focused z-trace table or the section's selected z-traces,
    and returns early on an empty one.

    This is the fact that makes gating on the clicked item wrong rather than
    merely strict: the clicked item never reaches a handler, so a gate built on
    it was answering a question nothing asks. Pinned against the source so the
    fix cannot outlive its own premise.
    """
    from PyReconstruct.modules.gui.main.field_widget_2_trace import FieldWidgetTrace

    src = inspect.getsource(FieldWidgetTrace.ztrace_function)
    assert "self.section.selected_ztraces" in src
    assert "if not selected_ztraces:" in src
    assert "clicked" not in src


def test_check_actions_no_longer_takes_the_clicked_trace():
    """The dead parameters are gone from the signature, not just unread.

    An unused `clicked_trace=None` left in place is an invitation to re-add a
    test against it, which is how the greyed menu would come back.
    """
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    params = list(inspect.signature(MainWindow.checkActions).parameters)
    assert params == ["self", "clicked_label"]


def test_check_actions_uses_the_shared_decision_functions():
    """The gating lives in the two pure functions above, so the rule has one
    home and this test file is testing the thing the app runs."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    src = inspect.getsource(MainWindow.checkActions)
    assert "scope_menus_enabled(" in src
    assert "edit_selected_entity(" in src

    # and neither replaced rule is lurking in the CODE. The docstring names both
    # on purpose -- it explains what they were -- so strip it before looking, or
    # this test would forbid the method from documenting its own history.
    body = src.split('"""')[2]
    assert "^" not in body, "the exclusive-or is back in checkActions"
    assert "clicked_trace" not in body, "the clicked-item test is back"
