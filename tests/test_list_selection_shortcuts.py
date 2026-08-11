"""The selection trio follows focus instead of always acting on the field.

``Select all`` / ``Deselect all`` / ``Invert selection`` (Ctrl+A / Ctrl+D /
Ctrl+Shift+I by default, Command on macOS) were wired straight to the field's
methods. Every data list is a ``QDockWidget`` *inside* the main window, so those
actions' default ``Qt::WindowShortcut`` scope claimed the sequences for the whole
window and consumed them before the focused list's view saw the key: pressing
Ctrl+A over the object list selected traces in the field and did nothing to the
list, even though ``QAbstractItemView`` handles ``QKeySequence::SelectAll``
itself and the list's own context menu advertises "Invert selection".

The fix is a focus dispatch in ``MainWindow`` (``selectAll`` / ``deselectAll`` /
``invertSelection``), the rule ``copy()`` and ``backspace()`` already follow via
``getFocusWidget()``. It is deliberately NOT a second, list-scoped QAction on the
same sequence: ``test_invert_selection_shortcut`` pins that Qt fires *neither* of
an ambiguous pair, so a second claimant would kill the key on both surfaces.

What is pinned here:

1. over a focused list the key acts on that list's rows and leaves the field's
   trace selection alone (the uncoupling itself, both directions);
2. over the field the key still selects traces (no regression on the surface
   that already worked);
3. every list type answers all three, not just the object list.

The sequences are read from the live series options rather than written in, so a
rebound key is still exercised -- and so this file does not hardcode a string
that ``test_invert_selection_shortcut``'s "bound nowhere else" scan looks for.
"""
import pytest

from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

gui = pytest.mark.gui

# Every list type, and the argument newTable needs for it: the trace list is
# built per section, the rest are series-wide.
LIST_TYPES = ["object", "trace", "ztrace", "section", "flag"]


def _open_list(main_window, table_type):
    """Open a data list, show it, and give its view keyboard focus."""
    manager = main_window.field.table_manager
    if table_type == "trace":
        manager.newTable(table_type, main_window.field.section)
    else:
        manager.newTable(table_type)

    table = manager.tables[table_type][-1]
    table.show()
    table.table.setFocus()
    return table


def _key(main_window, act_name):
    """The sequence currently bound to an action, as the user has it."""
    return QKeySequence(main_window.series.getOption(act_name))


def _selected_rows(table):
    return {i.row() for i in table.table.selectionModel().selectedRows()}


def _all_rows(table):
    return set(range(table.table.model().rowCount()))


@gui
@pytest.mark.parametrize("table_type", LIST_TYPES)
def test_select_all_over_a_focused_list_selects_its_rows(
    main_window, qapp, table_type
):
    """Ctrl+A with a list focused selects every row the list is showing.

    Parametrized over all five list types because the dispatch is on the shared
    ``DataTable``, so a list that fails here is one whose ``self.table`` is not
    the view the manager checks for focus -- exactly the kind of drift the
    object list's move from QTableWidget to a model-backed QTableView could
    have introduced.
    """
    main_window.show()
    table = _open_list(main_window, table_type)
    qapp.processEvents()

    rows = _all_rows(table)
    if not rows:
        pytest.skip(f"the fixture series has no {table_type} rows to select")
    assert _selected_rows(table) == set(), "the list did not start unselected"

    QTest.keySequence(main_window, _key(main_window, "selectall_act"))
    qapp.processEvents()

    assert _selected_rows(table) == rows


@gui
def test_select_all_over_a_focused_list_leaves_the_field_alone(
    main_window, qapp
):
    """The uncoupling proper: the list's rows move, the field's traces do not.

    This is the half a "make Ctrl+A work in the list" fix could get wrong by
    selecting the rows AND pushing a trace selection into the field. Selecting
    rows in a list has never done that when clicked, and the key must not
    differ from the click.
    """
    main_window.show()
    table = _open_list(main_window, "object")
    qapp.processEvents()

    field = main_window.field
    assert not field.section.selected_traces, "the field did not start clear"

    QTest.keySequence(main_window, _key(main_window, "selectall_act"))
    qapp.processEvents()

    assert _selected_rows(table), "the key never reached the list"
    assert not field.section.selected_traces, (
        "selecting every row in the object list also selected traces in the "
        "field -- the two selections are supposed to be independent"
    )


@gui
def test_select_all_over_the_field_still_selects_traces(main_window, qapp):
    """The other direction: with no list focused the key is unchanged.

    The dispatcher's fallback is the field, so an open-but-unfocused list must
    not steal the key either. The list is opened and left unfocused here for
    that reason.
    """
    main_window.show()
    table = _open_list(main_window, "object")
    main_window.field.setFocus()
    qapp.processEvents()

    field = main_window.field
    assert not field.section.selected_traces

    QTest.keySequence(main_window, _key(main_window, "selectall_act"))
    qapp.processEvents()

    assert field.section.selected_traces, (
        "Ctrl+A over the field stopped selecting traces"
    )
    assert not _selected_rows(table), "an unfocused list took the key"


@gui
def test_deselect_over_the_field_still_deselects_traces(main_window, qapp):
    """The field half of `Ctrl+D`, which nothing else in the suite covered.

    `selectAll`'s field branch is pinned by the test above and
    `invertSelection`'s by `test_invert_selection_shortcut`, but no test pressed
    `Ctrl+D` at a real window, so replacing that branch with `pass` left the
    whole suite green. It is not a one-liner to lose: `deselectAllTraces` has an
    independent zarr-layer half and section half, each with its own
    `generateView` call, and both sit behind it.
    """
    main_window.show()
    _open_list(main_window, "object")
    main_window.field.setFocus()
    main_window.field.selectAllTraces()
    qapp.processEvents()

    assert main_window.field.section.selected_traces, (
        "the fixture series has no traces to select"
    )

    QTest.keySequence(main_window, _key(main_window, "deselect_act"))
    qapp.processEvents()

    assert not main_window.field.section.selected_traces


@gui
def test_deselect_over_a_focused_list_clears_only_the_list(main_window, qapp):
    """Ctrl+D clears the list's rows and leaves the field's traces standing."""
    main_window.show()
    table = _open_list(main_window, "object")
    qapp.processEvents()

    field = main_window.field
    field.selectAllTraces()
    table.table.selectAll()
    qapp.processEvents()

    traces_before = {id(t) for t in field.section.selected_traces}
    assert traces_before, "the fixture series has no traces to select"
    assert _selected_rows(table), "the list did not start selected"

    QTest.keySequence(main_window, _key(main_window, "deselect_act"))
    qapp.processEvents()

    assert _selected_rows(table) == set()
    assert {id(t) for t in field.section.selected_traces} == traces_before, (
        "clearing the list's selection also cleared the field's"
    )


@gui
def test_invert_over_a_focused_list_inverts_only_the_list(main_window, qapp):
    """The third of the trio reaches each list's own invertSelection.

    Every list already offers "Invert selection" on its context menu, so this is
    the key finally reaching the command the focused surface advertises rather
    than the field's.
    """
    main_window.show()
    table = _open_list(main_window, "object")
    qapp.processEvents()

    rows = _all_rows(table)
    if len(rows) < 2:
        pytest.skip("need at least two rows for an inversion to be visible")

    field = main_window.field
    field.selectAllTraces()
    qapp.processEvents()
    traces_before = {id(t) for t in field.section.selected_traces}
    assert traces_before, "the fixture series has no traces to select"

    QTest.keySequence(main_window, _key(main_window, "invertselection_act"))
    qapp.processEvents()

    assert _selected_rows(table) == rows, (
        "inverting an empty list selection must select every row"
    )
    assert {id(t) for t in field.section.selected_traces} == traces_before, (
        "inverting the list's selection also inverted the field's"
    )


@gui
@pytest.mark.parametrize("table_type", LIST_TYPES)
def test_every_list_answers_the_three_dispatchers(main_window, table_type):
    """Each list type can be driven by MainWindow's three dispatchers.

    A structural companion to the key-delivery tests above: it fails loudly if a
    future list subclass shadows ``self.table`` with something that has no
    ``selectAll``/``clearSelection``, which would otherwise only show up as a
    dead key in one list.
    """
    table = _open_list(main_window, table_type)

    table.selectAll()
    table.invertSelection()
    table.deselectAll()

    assert _selected_rows(table) == set()
