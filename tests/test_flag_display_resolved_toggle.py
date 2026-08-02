"""Regression tests for the flag list's "Display resolved flags" row.

The row was a one-way switch: it turned on, it never turned off, and its
checkmark never appeared.

One cause behind all three symptoms. ``toggleDisplayResolved`` calls
``createTable()``, which calls ``createMenus()``, so every toggle destroys the
menubar and builds a new one. The row was built from the literal ``"checkbox"``
and never from ``self.show_resolved``, so the replacement action was always
unchecked, and the handler then read ``self.displayresolved_act.isChecked()``
back off that replacement. On a click Qt toggles the (always unchecked) action
to checked before emitting, so the handler read True every time and the filter
could only ever be turned on.

The fix is the pattern the object list's categorical column filters already
use: render ``"checkbox-True"`` from the stored state, and flip the stored
state in the handler rather than reading the action back.

The tests drive ``toggleDisplayResolved`` the way a click does (Qt toggles the
QAction, then the slot runs) and also call the slot on its own, because a click
through ``trigger()`` on a row whose handler tears down the menu containing it
is exactly the teardown the menubar-lifetime work covers separately.
"""

import pytest

from PyReconstruct.modules.gui.table.flag import FlagTableWidget


# --------------------------------------------------------------------------
# The fixture series ships with no flags, so create six: three resolved and
# three not, spread over three sections. Section.addFlag + save() is the path
# the app uses and it is what updates series.data, which the list reads.
# --------------------------------------------------------------------------

RESOLVED_NAMES = {"flag01", "flag03", "flag05"}


class StubFlagManager:
    """The manager surface DataTable and the flag slots use."""

    def __init__(self):
        self.series_states = {}
        self.tables = {
            "section": [], "trace": [], "ztrace": [], "flag": [], "object": [],
        }

    def updateSections(self, *args, **kwargs):
        pass

    def updateObjects(self, *args, **kwargs):
        pass

    def updateFlags(self, *args, **kwargs):
        pass

    def refresh(self):
        pass

    def recreateTable(self, table=None):
        pass

    def recreateTables(self, refresh_data=False):
        pass


@pytest.fixture
def flag_table(qapp, real_series, stub_mainwindow, gui_dialogs):
    from PyReconstruct.modules.datatypes import Flag

    series = stub_mainwindow.series
    for i, snum in enumerate((3, 3, 4, 4, 5, 5)):
        section = series.loadSection(snum)
        name = f"flag{i:02d}"
        section.addFlag(
            Flag(name, i, i, snum, (255, 0, 0), resolved=name in RESOLVED_NAMES)
        )
        section.save()

    widget = FlagTableWidget(series, stub_mainwindow, StubFlagManager())
    yield widget
    widget.deleteLater()


def click(widget):
    """Toggle the row the way a real click on it does.

    Qt flips a checkable QAction's own state before it emits ``triggered``, so
    a test that only called the slot would not reproduce the click that made
    this a one-way switch.
    """
    action = widget.displayresolved_act
    action.setChecked(not action.isChecked())
    widget.toggleDisplayResolved()


def displayed_names(widget):
    """The flag names in the table's rows, read off the live table.

    Read from the widget rather than from ``displayed_flags``: that list is
    only ever grown, never truncated, so after the table shrinks it keeps
    trailing entries for rows that no longer exist. Unreachable through the
    widget (every lookup is indexed by a real row) but it makes the list the
    wrong thing to measure.
    """
    column = widget.horizontal_headers.index("Flag")
    return {
        widget.table.item(row, column).text()
        for row in range(widget.table.rowCount())
    }


# --- the round trip -------------------------------------------------------

@pytest.mark.gui
def test_display_resolved_round_trips_on_off_on(flag_table):
    assert flag_table.show_resolved is False

    click(flag_table)
    assert flag_table.show_resolved is True, "first click did not turn it on"

    click(flag_table)
    assert flag_table.show_resolved is False, "it never turned back off"

    click(flag_table)
    assert flag_table.show_resolved is True


@pytest.mark.gui
def test_checkmark_follows_the_state_across_the_rebuild(flag_table):
    assert flag_table.displayresolved_act.isChecked() is False

    click(flag_table)
    assert flag_table.displayresolved_act.isChecked() is True, (
        "the rebuilt row lost the checkmark"
    )

    click(flag_table)
    assert flag_table.displayresolved_act.isChecked() is False

    click(flag_table)
    assert flag_table.displayresolved_act.isChecked() is True


@pytest.mark.gui
def test_the_rows_the_user_sees_round_trip_too(flag_table):
    """The point of the switch, measured on the table rather than the flag."""
    unresolved_only = displayed_names(flag_table)
    assert unresolved_only and not (unresolved_only & RESOLVED_NAMES)

    click(flag_table)
    assert RESOLVED_NAMES <= displayed_names(flag_table)

    click(flag_table)
    assert displayed_names(flag_table) == unresolved_only


@pytest.mark.gui
def test_handler_is_authoritative_without_the_action(flag_table):
    """Calling the slot alone flips the state.

    Before the fix the handler took its value from the QAction, so a
    programmatic call could only ever read back whatever the freshly rebuilt
    action happened to be, which was always unchecked.
    """
    flag_table.toggleDisplayResolved()
    assert flag_table.show_resolved is True
    assert flag_table.displayresolved_act.isChecked() is True

    flag_table.toggleDisplayResolved()
    assert flag_table.show_resolved is False
    assert flag_table.displayresolved_act.isChecked() is False


@pytest.mark.gui
def test_an_unrelated_rebuild_does_not_clear_the_checkmark(flag_table):
    """Refresh, a table update, anything that rebuilds the menus."""
    click(flag_table)
    assert flag_table.show_resolved is True

    flag_table.createTable()

    assert flag_table.show_resolved is True
    assert flag_table.displayresolved_act.isChecked() is True


# --- the row is the only one of its kind in the five data lists -----------

def test_no_data_list_builds_a_checkable_row_from_a_constant():
    """This was the whole defect, so guard against it coming back.

    A bare ``"checkbox"`` in a list widget's menubar definition is a row whose
    checked state cannot survive that widget rebuilding its own menus, which
    all five of them do on every ``createTable()``. The object list's
    categorical column filters are the one other checkable row across the five,
    and they already build their flag from ``self.user_col_filters``.
    """
    import inspect

    from PyReconstruct.modules.gui.table import (
        flag, object as object_table, section, trace, ztrace,
    )

    offenders = []
    for module in (flag, object_table, section, trace, ztrace):
        for line in inspect.getsource(module).splitlines():
            # a menu row, not prose about one: the act_name is on the same line
            if '_act"' in line and '"checkbox"' in line:
                offenders.append(f"{module.__name__}: {line.strip()}")

    assert offenders == []
