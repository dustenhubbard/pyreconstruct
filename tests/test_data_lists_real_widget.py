"""Real-widget selection tests for the trace, z-trace, flag and object lists.

PR #117 fixed per-cell duplication in all five data lists via the shared
``DataTable.selectedRows()``, but only the section list got real-widget tests
(``test_section_list_real_widget.py``); the other four were covered only via
the shared helper. This file closes that gap: each of the four remaining lists
is built as the REAL widget over a real Series (a writable copy of the
checked-in ``class_series.jser``), a real row selection is made through the
widget's selection model, and ``getSelected()`` is asserted to return one
de-duplicated, order-preserving entry per selected row.

Why per-widget tests when the helper is shared: ``getSelected()`` is
overridden in every list and each override maps rows to a different payload
through a different surface -- the trace list to ``(name, index)`` tuples via
``self.rows`` plus a lock check, the z-trace list to names via
``table.item(r, 0)``, the flag list to Flag objects via ``displayed_flags``,
and the object list to names via ``model.nameAt(r)`` on a lazy
QAbstractTableModel (it is the one list that is model-backed rather than
QTableWidget-backed). A regression in any of those mappings -- or a list that
stops routing through ``selectedRows()`` -- is invisible to a test that only
exercises the helper on the section list.

Fixture data: the checked-in series has 8 objects and sections with up to five
traces, so the trace and object lists populate from the file as-is. It ships
with no z-traces and no flags, so those two fixtures first create a handful on
the writable copy through the ordinary datatype APIs (``series.ztraces``,
``Section.addFlag`` + ``save()``) before building the widget -- the widgets
then populate from the same series-data paths the app uses.

The stub main window / manager recipe follows ``tests/conftest.py``. The one
extension is the field stub: these widgets build their context menus through
``field.getTraceMenu`` / ``getZtraceMenu`` / ``getObjMenu``, so the field here
runs the REAL menu builders (``context_menu_list``) with no-op handlers --
the widgets' own ``createMenus`` paths execute unmodified.
"""

import pytest

# No `importorskip("pytestqt")` here on purpose. See the same note in
# tests/test_section_list_real_widget.py: the skip is what let a mis-synced
# .venv drop every widget test and still report a green run. The guard now lives
# in tests/conftest.py and errors instead.
pytestmark = pytest.mark.gui


# The densest section in the fixture series: five traces across three
# contours (d03 x3, d03p12, d03sp12), so the trace list shows five rows.
TRACE_SECTION = 44

# Deliberately out of ascending order. A bare set() of these iterates
# 0, 2, 4 (small ints hash to themselves), so an implementation that loses
# the selection order is caught; a contiguous ascending pick would not be.
UNORDERED_ROWS = (4, 0, 2)


def select_rows(table, rows):
    """Select whole rows, in the given order, through the selection model.

    Works for both QTableWidget (trace/ztrace/flag) and QTableView (object):
    both expose model() and selectionModel(). selectRow() replaces the
    selection rather than extending it, so multi-row selections go through
    QItemSelection; Qt reports selectedIndexes() in the order the ranges were
    added, which is what lets the order-preservation tests discriminate.
    """
    from PySide6.QtCore import QItemSelection, QItemSelectionModel

    model = table.model()
    last_col = model.columnCount() - 1
    selection = QItemSelection()
    for row in rows:
        selection.select(model.index(row, 0), model.index(row, last_col))
    table.selectionModel().select(
        selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
    )


def assert_cellwise_multiselect(table):
    """The premise every test here rests on: a multi-column list selected
    cell-wise with extended selection. If a list ever switches to SelectRows,
    the duplicate rows stop arriving and the de-dup becomes belt-and-braces --
    worth knowing deliberately."""
    from PySide6.QtWidgets import QAbstractItemView

    assert table.model().columnCount() > 1
    assert (
        table.selectionBehavior()
        == QAbstractItemView.SelectionBehavior.SelectItems
    )
    assert (
        table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    )


class StubListManager:
    """The manager surface DataTable and the list slots actually use.

    Mirrors conftest.StubTableManager (which is deliberately not a fixture):
    the real TableManager owns every list in the app plus the undo stack, and
    building it would drag in the whole main window.
    """

    def __init__(self):
        self.series_states = {}
        self.tables = {
            "section": [], "trace": [], "ztrace": [], "flag": [], "object": [],
        }
        self.updated_sections = []

    def updateSections(self, section_numbers, *args, **kwargs):
        self.updated_sections.append(list(section_numbers))

    def updateObjects(self, *args, **kwargs):
        pass

    def refresh(self):
        pass

    def recreateTable(self, table=None):
        pass

    def recreateTables(self, refresh_data=False):
        pass


class MenuStubField:
    """A field stand-in whose menu builders are the real ones.

    The trace/ztrace/object lists build their context menus by calling
    ``mainwindow.field.get*Menu(...)``, and the returned structures reference
    dozens of field slots (``self.editAttributes``, ``self.mergeTraces``, ...).
    Running the real builders keeps the widgets' createMenus paths intact;
    the __getattr__ fallback supplies a no-op for every field slot a menu
    entry references, so triggering one in a test is a no-op rather than a
    crash. Attributes that selection paths read for real (series, section,
    notifyLocked) are defined explicitly and are NOT no-ops.

    ``notifyLocked`` is configurable rather than a bare stub: per the
    2026-08-06 "split notifyLocked" decision, the trace list's
    ``itemChanged``/``getSelected`` keep the ask-to-unlock idiom (unlike the
    mouse/scissors gestures, which now notify-and-stop instead and no longer
    call ``notifyLocked`` at all). ``notify_locked_response`` scripts the
    user's answer and ``notify_locked_calls`` records every call, so a test
    can pin both halves: the list asks, and it acts on what it's told.
    """

    def __init__(self, series, section):
        self.series = series
        self.section = section
        self.notify_locked_response = False
        self.notify_locked_calls = []
        self.calls = {}

    def reload(self):
        pass

    def clearStates(self):
        pass

    def notifyLocked(self, *args, **kwargs):
        self.notify_locked_calls.append(args[0] if args else kwargs)
        return self.notify_locked_response

    def getTraceMenu(self, is_in_field=True, list_ops=None, find_in_field=None):
        from PyReconstruct.modules.gui.main.context_menu_list import (
            get_context_menu_list_trace,
        )

        return get_context_menu_list_trace(
            self, is_in_field, list_ops=list_ops, find_in_field=find_in_field
        )

    def getObjMenu(self, list_ops=None, is_in_field=True):
        from PyReconstruct.modules.gui.main.context_menu_list import (
            get_context_menu_list_obj,
        )

        return get_context_menu_list_obj(
            self, list_ops=list_ops, is_in_field=is_in_field
        )

    def getZtraceMenu(self, list_ops=None):
        from PyReconstruct.modules.gui.main.field_widget_2_trace import (
            FieldWidgetTrace,
        )

        return FieldWidgetTrace.getZtraceMenu(self, list_ops=list_ops)

    def __getattr__(self, name):
        if name.startswith("_"):  # never fake dunders/privates
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.setdefault(name, []).append((args, kwargs))

        return _record


@pytest.fixture
def list_mainwindow(stub_mainwindow):
    """conftest's stub main window, with the menu-building field swapped in."""
    series = stub_mainwindow.series
    first = sorted(series.sections)[0]
    stub_mainwindow.field = MenuStubField(series, series.loadSection(first))
    return stub_mainwindow


# --------------------------------------------------------------------------
# Trace list: rows map to (name, index) tuples via self.rows + a lock check.
# --------------------------------------------------------------------------

@pytest.fixture
def trace_table(qapp, list_mainwindow, gui_dialogs):
    from PyReconstruct.modules.gui.table.trace import TraceTableWidget

    series = list_mainwindow.series
    section = series.loadSection(TRACE_SECTION)
    widget = TraceTableWidget(series, section, list_mainwindow, StubListManager())
    yield widget
    widget.deleteLater()


def expected_trace_items(widget, rows):
    return [
        (widget.table.item(r, 0).text(), widget.rows[r].index) for r in rows
    ]


def test_trace_table_is_cell_selectable_and_populated(trace_table):
    assert_cellwise_multiselect(trace_table.table)
    assert trace_table.table.rowCount() == 5  # section 44's five traces


def test_trace_row_selection_yields_one_item(trace_table):
    table = trace_table.table
    table.clearSelection()
    table.selectRow(0)

    # the row really is selected across multiple columns
    assert len(table.selectedIndexes()) > 1

    assert trace_table.getSelected() == expected_trace_items(trace_table, [0])


def test_trace_multi_row_selection_preserves_order_without_repeats(trace_table):
    assert trace_table.table.rowCount() > max(UNORDERED_ROWS)
    select_rows(trace_table.table, UNORDERED_ROWS)

    assert trace_table.getSelected() == expected_trace_items(
        trace_table, UNORDERED_ROWS
    )


def test_trace_empty_selection_is_falsy(trace_table):
    trace_table.table.clearSelection()
    assert not trace_table.getSelected()


def test_trace_single_accepts_a_one_row_selection(trace_table, gui_dialogs):
    trace_table.table.clearSelection()
    trace_table.table.selectRow(0)

    assert trace_table.getSelected(single=True) == expected_trace_items(
        trace_table, [0]
    )[0]
    assert gui_dialogs.notices == []


def test_trace_single_still_rejects_two_rows(trace_table, gui_dialogs):
    select_rows(trace_table.table, (0, 1))

    assert trace_table.getSelected(single=True) is None
    assert gui_dialogs.notices == [
        "Please select only one trace for this option."
    ]


# --------------------------------------------------------------------------
# Locked rows: table/trace.py keeps the ask-to-unlock idiom (unlike the
# mouse/scissors gestures -- see test_locked_object_field_guards.py and
# test_locked_gesture_notify_and_stop.py, which now notify-and-stop and never
# call notifyLocked at all). Corrected 2026-08-06 ("split notifyLocked",
# DECISIONS.md): a dispatched fixup found notifyLocked has four real call
# sites, not two, and the trace list's two (itemChanged, getSelected)
# genuinely unlock-and-proceed on "Yes", by original design (73f54794). These
# pin that half so a future change collapsing the two idioms into one
# regresses loudly instead of silently.
# --------------------------------------------------------------------------

def test_trace_get_selected_proceeds_when_unlock_is_accepted(trace_table):
    """getSelected() on a locked row must include it if the user says Yes."""
    table = trace_table.table
    field = trace_table.mainwindow.field
    locked_name = table.item(0, 0).text()
    trace_table.series.setAttr(locked_name, "locked", True)
    field.notify_locked_response = True

    table.clearSelection()
    table.selectRow(0)

    assert trace_table.getSelected() == expected_trace_items(trace_table, [0])
    assert field.notify_locked_calls == [{locked_name}]


def test_trace_get_selected_stops_when_unlock_is_refused(trace_table):
    """The same locked row, but the user says No: selection must be refused."""
    table = trace_table.table
    field = trace_table.mainwindow.field
    locked_name = table.item(0, 0).text()
    trace_table.series.setAttr(locked_name, "locked", True)
    field.notify_locked_response = False

    table.clearSelection()
    table.selectRow(0)

    assert trace_table.getSelected() is None
    assert field.notify_locked_calls == [{locked_name}]


class _FakeCheckItem:
    """The three accessors `itemChanged` reads off a `QTableWidgetItem`."""

    def __init__(self, column, row, checked):
        from PySide6.QtCore import Qt

        self._column = column
        self._row = row
        self._state = (
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )

    def column(self):
        return self._column

    def row(self):
        return self._row

    def checkState(self):
        return self._state


def test_trace_item_changed_proceeds_when_unlock_is_accepted(trace_table):
    """Checking a locked row's Hidden box must act on it if the user says Yes."""
    table = trace_table.table
    field = trace_table.mainwindow.field
    locked_name = table.item(0, 0).text()
    trace_table.series.setAttr(locked_name, "locked", True)
    field.notify_locked_response = True

    col = trace_table.horizontal_headers.index("Hidden")
    trace_table.itemChanged(_FakeCheckItem(col, 0, checked=True))

    assert field.notify_locked_calls == [locked_name]
    assert "hideTraces" in field.calls


def test_trace_item_changed_stops_when_unlock_is_refused(trace_table):
    """The same locked row's Hidden box, refused: nothing must be acted on."""
    table = trace_table.table
    field = trace_table.mainwindow.field
    locked_name = table.item(0, 0).text()
    trace_table.series.setAttr(locked_name, "locked", True)
    field.notify_locked_response = False

    col = trace_table.horizontal_headers.index("Hidden")
    trace_table.itemChanged(_FakeCheckItem(col, 0, checked=True))

    assert field.notify_locked_calls == [locked_name]
    assert "hideTraces" not in field.calls


# --------------------------------------------------------------------------
# Z-trace list: rows map to names via table.item(r, 0). The fixture series
# ships without z-traces, so the fixture creates six on the writable copy.
# --------------------------------------------------------------------------

@pytest.fixture
def ztrace_table(qapp, list_mainwindow, gui_dialogs):
    from PyReconstruct.modules.datatypes import Ztrace
    from PyReconstruct.modules.gui.table.ztrace import ZtraceTableWidget

    series = list_mainwindow.series
    for i in range(6):
        name = f"zt{i:02d}"
        points = [(0.1 * i, 0.2 * i, snum) for snum in (3, 4, 5)]
        series.ztraces[name] = Ztrace(name, (255, 0, 0), points)

    widget = ZtraceTableWidget(series, list_mainwindow, StubListManager())
    yield widget
    widget.deleteLater()


def expected_ztrace_names(widget, rows):
    return [widget.table.item(r, 0).text() for r in rows]


def test_ztrace_table_is_cell_selectable_and_populated(ztrace_table):
    assert_cellwise_multiselect(ztrace_table.table)
    assert ztrace_table.table.rowCount() == 6


def test_ztrace_row_selection_yields_one_name(ztrace_table):
    table = ztrace_table.table
    table.clearSelection()
    table.selectRow(0)

    assert len(table.selectedIndexes()) > 1
    assert ztrace_table.getSelected() == expected_ztrace_names(ztrace_table, [0])


def test_ztrace_multi_row_selection_preserves_order_without_repeats(ztrace_table):
    assert ztrace_table.table.rowCount() > max(UNORDERED_ROWS)
    select_rows(ztrace_table.table, UNORDERED_ROWS)

    assert ztrace_table.getSelected() == expected_ztrace_names(
        ztrace_table, UNORDERED_ROWS
    )


def test_ztrace_empty_selection_is_falsy(ztrace_table):
    ztrace_table.table.clearSelection()
    assert not ztrace_table.getSelected()


def test_ztrace_single_accepts_a_one_row_selection(ztrace_table, gui_dialogs):
    ztrace_table.table.clearSelection()
    ztrace_table.table.selectRow(0)

    assert ztrace_table.getSelected(single=True) == expected_ztrace_names(
        ztrace_table, [0]
    )[0]
    assert gui_dialogs.notices == []


def test_ztrace_single_still_rejects_two_rows(ztrace_table, gui_dialogs):
    select_rows(ztrace_table.table, (0, 1))

    assert ztrace_table.getSelected(single=True) is None
    assert gui_dialogs.notices == [
        "Please select only one ztrace for this option."
    ]


# --------------------------------------------------------------------------
# Flag list: rows map to Flag objects via displayed_flags. The fixture series
# ships without flags, so the fixture creates six through Section.addFlag +
# save() -- the same path the app uses, which also updates series.data, the
# source the list populates from.
# --------------------------------------------------------------------------

@pytest.fixture
def flag_table(qapp, list_mainwindow, gui_dialogs):
    from PyReconstruct.modules.datatypes import Flag
    from PyReconstruct.modules.gui.table.flag import FlagTableWidget

    series = list_mainwindow.series
    for i, snum in enumerate((3, 3, 4, 4, 5, 5)):
        section = series.loadSection(snum)
        section.addFlag(Flag(f"flag{i:02d}", i, i, snum, (255, 0, 0)))
        section.save()

    widget = FlagTableWidget(series, list_mainwindow, StubListManager())
    yield widget
    widget.deleteLater()


def expected_flag_keys(widget, rows):
    return [
        (widget.displayed_flags[r].name, widget.displayed_flags[r].snum)
        for r in rows
    ]


def flag_keys(flags):
    return [(f.name, f.snum) for f in flags]


def test_flag_table_is_cell_selectable_and_populated(flag_table):
    assert_cellwise_multiselect(flag_table.table)
    assert flag_table.table.rowCount() == 6


def test_flag_row_selection_yields_one_flag(flag_table):
    table = flag_table.table
    table.clearSelection()
    table.selectRow(0)

    assert len(table.selectedIndexes()) > 1
    assert flag_keys(flag_table.getSelected()) == expected_flag_keys(
        flag_table, [0]
    )


def test_flag_multi_row_selection_preserves_order_without_repeats(flag_table):
    assert flag_table.table.rowCount() > max(UNORDERED_ROWS)
    select_rows(flag_table.table, UNORDERED_ROWS)

    assert flag_keys(flag_table.getSelected()) == expected_flag_keys(
        flag_table, UNORDERED_ROWS
    )


def test_flag_empty_selection_is_falsy(flag_table):
    flag_table.table.clearSelection()
    assert not flag_table.getSelected()


def test_flag_single_accepts_a_one_row_selection(flag_table, gui_dialogs):
    flag_table.table.clearSelection()
    flag_table.table.selectRow(0)

    selected = flag_table.getSelected(single=True)
    assert selected is flag_table.displayed_flags[0]
    assert gui_dialogs.notices == []


def test_flag_single_still_rejects_two_rows(flag_table, gui_dialogs):
    select_rows(flag_table.table, (0, 1))

    assert flag_table.getSelected(single=True) is None
    assert gui_dialogs.notices == [
        "Please select only one flag for this option."
    ]


# --------------------------------------------------------------------------
# Object list: the one MODEL-backed list (lazy QAbstractTableModel behind a
# QTableView). Its selection path differs from the QTableWidget lists --
# selectedIndexes() comes from the view's selection model over virtual rows,
# and getSelected() resolves rows through model.nameAt(r) rather than
# table.item(r, 0) -- so these tests drive exactly that: real view, real
# model, selection made through the selection model.
# --------------------------------------------------------------------------

@pytest.fixture
def object_table(qapp, list_mainwindow, gui_dialogs):
    from PyReconstruct.modules.gui.table.object import ObjectTableWidget

    widget = ObjectTableWidget(
        list_mainwindow.series, list_mainwindow, StubListManager()
    )
    yield widget
    widget.deleteLater()


def expected_object_names(widget, rows):
    return [widget.model.nameAt(r) for r in rows]


def test_object_table_is_cell_selectable_and_populated(object_table):
    assert_cellwise_multiselect(object_table.table)
    # the fixture series' eight objects, through the lazy model
    assert object_table.model.rowCount() == 8


def test_object_view_is_model_backed(object_table):
    """Pin the premise of this block: a QTableView over the lazy model, not a
    QTableWidget. If the list ever moves back, these tests still pass but the
    'differs from the others' rationale is void -- fail loudly instead."""
    from PySide6.QtWidgets import QTableView, QTableWidget

    assert isinstance(object_table.table, QTableView)
    assert not isinstance(object_table.table, QTableWidget)
    assert object_table.table.model() is object_table.model


def test_object_row_selection_yields_one_name(object_table):
    table = object_table.table
    table.clearSelection()
    table.selectRow(0)

    # several cell indexes from the view's selection model...
    assert len(table.selectedIndexes()) > 1
    # ...one name, resolved through model.nameAt
    assert object_table.getSelected() == expected_object_names(object_table, [0])


def test_object_multi_row_selection_preserves_order_without_repeats(object_table):
    assert object_table.model.rowCount() > max(UNORDERED_ROWS)
    select_rows(object_table.table, UNORDERED_ROWS)

    assert object_table.getSelected() == expected_object_names(
        object_table, UNORDERED_ROWS
    )


def test_object_empty_selection_is_falsy(object_table):
    object_table.table.clearSelection()
    assert not object_table.getSelected()


def test_object_single_accepts_a_one_row_selection(object_table, gui_dialogs):
    object_table.table.clearSelection()
    object_table.table.selectRow(0)

    assert object_table.getSelected(single=True) == object_table.model.nameAt(0)
    assert gui_dialogs.notices == []


def test_object_single_still_rejects_two_rows(object_table, gui_dialogs):
    select_rows(object_table.table, (0, 1))

    assert object_table.getSelected(single=True) is None
    assert gui_dialogs.notices == [
        "Please select only one object for this option."
    ]


def test_object_invert_selection_returns_each_name_once(object_table):
    """The object list overrides invertSelection() with a selection-model
    implementation over the lazy model; inverting an empty selection selects
    every row, each exactly once."""
    object_table.table.clearSelection()
    object_table.invertSelection()

    selected = object_table.getSelected()
    assert len(selected) == object_table.model.rowCount()
    assert len(set(selected)) == len(selected)
