"""Real-widget tests for the section list's selection and its menu wiring.

Why these are real-widget tests. The existing coverage for this area replaces
``getSelected`` with a lambda and the main window with a ``SimpleNamespace``,
which is fine for testing a slot's *logic* but means the selection path itself
-- ``QTableWidget.selectedIndexes()`` -> row numbers -> section numbers -- was
never executed by a test. A bug lived in exactly that gap: the lists are
``SelectItems``/``ExtendedSelection`` over a six-column table, so selecting one
row yields five indexes, and ``getSelected`` returned the same section number
five times. Nothing that stubs ``getSelected`` can see that. So these tests
build the actual widget over an actual Series and drive the actual slots.

The multiplication was not cosmetic: ``setBC(inc=True)`` -- the "Increment
values..." menu item -- reloads the section from disk and does
``section.brightness += b`` once per returned entry, so asking for +10 on one
selected row moved brightness by 50.
"""

import pytest

# No `importorskip("pytestqt")` here on purpose. It used to be, and it meant a
# .venv without the `test` extra dropped this whole module and the suite still
# said green. The `gui` mark plus the guard in tests/conftest.py
# (`pytest_collection_modifyitems`) turns that same environment into a hard
# error, while leaving `-m "not gui"` working.
pytestmark = pytest.mark.gui


# The section list's six columns, five of which are selectable. This is what
# turns one selected row into several indexes; if it ever changes, the
# multiplication factor changes with it, and test_row_selection_yields_indexes
# is the test that will say so.
EXPECTED_COLUMNS = 6


def first_section_number(widget):
    """The section number shown in row 0 of the list."""
    return int(widget.table.item(0, 0).text().split()[0])


def set_bc(series, snum, brightness=0, contrast=0):
    """Write brightness/contrast straight onto a section, bypassing the slots."""
    section = series.loadSection(snum)
    section.brightness = brightness
    section.contrast = contrast
    section.save()


# --------------------------------------------------------------------------
# The selection model itself: the premise the rest of the file rests on.
# --------------------------------------------------------------------------

def test_table_is_cell_selectable(section_table):
    """The premise: this is a multi-column, cell-wise, multi-select table.

    Guards the assumption behind every other test here. If someone switches the
    list to SelectRows, the duplicate rows stop arriving and the dedup becomes
    belt-and-braces -- worth knowing deliberately rather than discovering when a
    regression test quietly stops testing anything.
    """
    from PySide6.QtWidgets import QAbstractItemView

    table = section_table.table
    assert table.columnCount() == EXPECTED_COLUMNS
    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectItems
    assert table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection


def test_row_selection_yields_several_indexes_but_one_section(section_table):
    """One selected row: several cell indexes, exactly one section number.

    This is the regression test for the de-duplication. Before the fix
    `getSelected()` returned `[n, n, n, n, n]` for a single selected row.
    """
    table = section_table.table
    table.clearSelection()
    table.selectRow(0)

    # The row really is selected across multiple columns -- otherwise this test
    # would pass for the wrong reason.
    assert len(table.selectedIndexes()) > 1

    selected = section_table.getSelected()
    assert selected == [first_section_number(section_table)]


def test_single_cell_selection_yields_one_section(section_table):
    """A one-cell selection was always correct; keep it that way."""
    table = section_table.table
    table.clearSelection()
    table.setCurrentCell(0, 0)

    assert len(table.selectedIndexes()) == 1
    assert section_table.getSelected() == [first_section_number(section_table)]


def test_getSelected_reads_the_live_selection(section_table):
    """getSelected() reflects the widget's current selection, in row order.

    Not a stub: the section numbers come back because the QTableWidget's
    selection model says those rows are selected.
    """
    table = section_table.table
    expected = [
        int(table.item(r, 0).text().split()[0]) for r in (0, 1, 2)
    ]

    select_rows(table, (0, 1, 2))

    assert len(table.selectedIndexes()) > 3  # genuinely cell-wise
    assert section_table.getSelected() == expected


def test_empty_selection_returns_nothing(section_table):
    """No selection is falsy, which is what every caller guards on."""
    section_table.table.clearSelection()
    assert not section_table.getSelected()


def test_invert_selection_returns_each_section_once(section_table):
    """Invert selection selects whole rows; each section must appear once."""
    table = section_table.table
    table.clearSelection()
    section_table.invertSelection()

    selected = section_table.getSelected()
    assert len(table.selectedIndexes()) > len(selected)  # cells > rows
    assert len(selected) == table.rowCount()
    assert len(set(selected)) == len(selected)


def select_rows(table, rows):
    """Select whole rows, in the given order, through the selection model.

    selectRow() replaces the selection rather than extending it, so anything
    multi-row has to go through QItemSelection. Qt reports selectedIndexes() in
    the order the ranges were added, which is what lets the order-preservation
    test below actually discriminate.
    """
    from PySide6.QtCore import QItemSelection, QItemSelectionModel

    model = table.model()
    last_col = table.columnCount() - 1
    selection = QItemSelection()
    for row in rows:
        selection.select(model.index(row, 0), model.index(row, last_col))
    table.selectionModel().select(
        selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
    )


# Deliberately out of ascending order and not contiguous. A bare set() would
# reorder these to [5, 100, 197] (small ints hash to themselves, so a set of a
# contiguous low range such as {0,1,2} iterates in order and would NOT catch
# the mistake -- these three do).
UNORDERED_ROWS = (197, 5, 100)


def test_selectedRows_preserves_order_without_repeats(section_table):
    """The shared helper: ordered, de-duplicated row indices.

    Order matters -- callers read element [0] to prefill dialogs and iterate the
    list into the series log, so a bare set() would make both non-deterministic.
    """
    table = section_table.table
    assert table.rowCount() > max(UNORDERED_ROWS)
    select_rows(table, UNORDERED_ROWS)

    assert section_table.selectedRows() == list(UNORDERED_ROWS)


def test_getSelected_preserves_selection_order(section_table):
    """The section numbers come back in the order Qt reported the rows."""
    table = section_table.table
    select_rows(table, UNORDERED_ROWS)
    expected = [int(table.item(r, 0).text().split()[0]) for r in UNORDERED_ROWS]

    assert section_table.getSelected() == expected


# --------------------------------------------------------------------------
# The user-visible consequence: "Increment values..." on one row.
# --------------------------------------------------------------------------

def test_increment_on_a_row_moves_brightness_by_the_requested_delta(
    unlocked_section_table,
):
    """The measured bug: +10 on one selected ROW gave +50.

    Five selectable columns -> five entries -> five `brightness += 10`, each
    reloading the section from disk, so the increment compounded.
    """
    widget = unlocked_section_table
    series = widget.series
    snum = first_section_number(widget)
    set_bc(series, snum, brightness=0)

    widget.table.clearSelection()
    widget.table.selectRow(0)
    widget.setBC(b=10, c=0, inc=True)

    assert series.loadSection(snum).brightness == 10


def test_increment_on_a_cell_moves_brightness_by_the_requested_delta(
    unlocked_section_table,
):
    """The cell case was already correct; pin it so a fix cannot invert it."""
    widget = unlocked_section_table
    series = widget.series
    snum = first_section_number(widget)
    set_bc(series, snum, brightness=0)

    widget.table.clearSelection()
    widget.table.setCurrentCell(0, 0)
    widget.setBC(b=10, c=0, inc=True)

    assert series.loadSection(snum).brightness == 10


def test_increment_is_applied_once_per_section_not_once_per_cell(
    unlocked_section_table,
):
    """Contrast increments once too, and the manager is told once per section."""
    widget = unlocked_section_table
    series = widget.series
    snum = first_section_number(widget)
    set_bc(series, snum, brightness=0, contrast=0)

    widget.table.clearSelection()
    widget.table.selectRow(0)
    widget.setBC(b=5, c=7, inc=True)

    section = series.loadSection(snum)
    assert (section.brightness, section.contrast) == (5, 7)
    assert widget.manager.updated_sections[-1] == [snum]


def test_absolute_set_bc_is_unaffected_by_the_number_of_selected_cells(
    unlocked_section_table,
):
    """Absolute (non-increment) B/C was never multiplied; confirm it still isn't."""
    widget = unlocked_section_table
    series = widget.series
    snum = first_section_number(widget)
    set_bc(series, snum, brightness=0, contrast=0)

    widget.table.clearSelection()
    widget.table.selectRow(0)
    widget.setBC(b=37, c=23)

    section = series.loadSection(snum)
    assert (section.brightness, section.contrast) == (37, 23)


# --------------------------------------------------------------------------
# The other user-visible consequence: "Delete sections" on one row crashed.
# --------------------------------------------------------------------------

def test_delete_sections_on_a_row_deletes_exactly_one_section(
    unlocked_section_table,
):
    """Deleting one selected ROW removes one section, and does not raise.

    This was the nastier half of the same bug. Series.deleteSections does
    `os.remove(...)` then `del self.sections[snum]` per entry, so the duplicated
    section number made the second pass raise KeyError -- *after* the file was
    already gone and after the user had accepted the irreversible-change
    warning, leaving the series half-updated. Measured before the fix:
    `getSelected()` returned [0, 0, 0, 0, 0] and the call raised `KeyError: 0`.
    """
    widget = unlocked_section_table
    series = widget.series
    snum = first_section_number(widget)
    before = len(series.sections)

    widget.table.clearSelection()
    widget.table.selectRow(0)
    widget.deleteSections()  # must not raise

    assert len(series.sections) == before - 1
    assert snum not in series.sections


# --------------------------------------------------------------------------
# single=True: a one-row selection is one section.
# --------------------------------------------------------------------------

def test_single_accepts_a_one_row_selection(section_table, gui_dialogs):
    """`single=True` rejected a legitimately single row selection.

    It counted cells, so one row looked like five sections and the user got
    "Please select only one section for this option." for a perfectly ordinary
    click-and-drag across a row.
    """
    table = section_table.table
    table.clearSelection()
    table.selectRow(0)

    assert section_table.getSelected(single=True) == first_section_number(section_table)
    assert gui_dialogs.notices == []


def test_single_accepts_a_one_cell_selection(section_table, gui_dialogs):
    table = section_table.table
    table.clearSelection()
    table.setCurrentCell(0, 0)

    assert section_table.getSelected(single=True) == first_section_number(section_table)
    assert gui_dialogs.notices == []


def test_single_still_rejects_two_rows(section_table, gui_dialogs):
    """The guard must keep working -- dedup must not make it permissive."""
    select_rows(section_table.table, (0, 1))

    assert section_table.getSelected(single=True) is None
    assert gui_dialogs.notices == [
        "Please select only one section for this option."
    ]


# --------------------------------------------------------------------------
# Menu wiring: the actions exist, are connected, and reach the real slot.
# --------------------------------------------------------------------------

# (attribute, menu text) for the context-menu actions this list exposes. The
# attribute names are how the rest of the app reaches these actions, so a typo
# in one is a silently unreachable action -- `incbc_act` was spelled
# `incbc_acrt` until this test was written.
CONTEXT_MENU_ACTIONS = [
    ("lock_act", "Lock sections"),
    ("unlock_act", "Unlock sections"),
    ("setbc_act", "Set values..."),
    ("incbc_act", "Increment values..."),
    ("matchbc_act", "Match section in view"),
    ("optimizebc_act", "Optimize..."),
    ("thickness_act", "Edit thickness..."),
    ("editsrc_act", "Edit image source..."),
    ("insertabove_act", "Above"),
    ("insertbelow_act", "Below"),
    ("invertsectionselection_act", "Invert selection"),
    ("copy_act", "Copy section values"),
    ("delete_act", "Delete sections"),
]


@pytest.mark.parametrize("attr,text", CONTEXT_MENU_ACTIONS)
def test_context_menu_action_exists_with_expected_text(section_table, attr, text):
    from PySide6.QtGui import QAction

    action = getattr(section_table, attr, None)
    assert isinstance(action, QAction), f"{attr} is not a QAction"
    assert action.text() == text


def is_triggered_connected(action):
    """True if `action.triggered` has at least one receiver.

    QObject.receivers() only takes a C++ signal string in PySide6, so go via the
    meta-object: isSignalConnected(QMetaMethod) is the supported way to ask.
    """
    meta = action.metaObject()
    index = meta.indexOfSignal("triggered(bool)")
    assert index >= 0, "QAction.triggered(bool) not found in the meta-object"
    return action.isSignalConnected(meta.method(index))


@pytest.mark.parametrize("attr,_text", CONTEXT_MENU_ACTIONS)
def test_context_menu_action_is_connected(section_table, attr, _text):
    """Every action has at least one receiver on `triggered`.

    A QAction that was built and added to the menu but never connected is
    indistinguishable from a working one by eye; it just does nothing when
    clicked.
    """
    assert is_triggered_connected(getattr(section_table, attr))


def test_increment_action_triggers_the_real_increment(
    unlocked_section_table, gui_dialogs
):
    """Trigger the menu QAction and watch the section change.

    End to end: QAction.trigger() -> the lambda in getContextMenuList ->
    setBC(inc=True) -> QuickDialog (scripted) -> the real getSelected() -> the
    section on disk. This is the exact path the reported bug took.
    """
    widget = unlocked_section_table
    series = widget.series
    snum = first_section_number(widget)
    set_bc(series, snum, brightness=0, contrast=0)

    widget.table.clearSelection()
    widget.table.selectRow(0)
    widget.manager.updated_sections.clear()

    # setBC(inc=True) with no b/c prompts QuickDialog; answer +10 brightness.
    gui_dialogs.responses.append(((10, 0), True))

    widget.incbc_act.trigger()

    assert gui_dialogs.dialogs == ["Brightness/Contrast"]
    assert series.loadSection(snum).brightness == 10
    assert widget.manager.updated_sections == [[snum]]


def test_context_menu_is_populated(section_table):
    """The right-click menu is built, not empty."""
    actions = section_table.context_menu.actions()
    assert len([a for a in actions if not a.isSeparator()]) > 0


def test_notify_is_neutralised(section_table, gui_dialogs):
    """Meta-test: the modal guard is actually in force.

    If this ever fails, the rest of the file is one bad selection away from
    hanging CI instead of failing it.
    """
    from PyReconstruct.modules.gui.table import section as section_module

    section_module.notify("probe")
    assert gui_dialogs.notices == ["probe"]
