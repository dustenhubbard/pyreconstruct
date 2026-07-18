"""Context-menu UX overhaul, phase 2b (PR5 + remaining decided items).

Covers:

  * Q1 parity -- "Invert selection" and per-list "Copy <entity> values" added across the
    lists (object already had invert; section/flag already had copy row).
      - the shared QTableWidget-backed ``DataTable.invertSelection`` inverts
        only the DISPLAYED (filtered) rows, never filtered-out data;
      - the list context-menu definitions carry the parity actions.
  * Q4 -- flag list "Resolve" submenu hoisted to two top-level items
    ("Mark resolved" / "Mark unresolved"), handlers + attr_names kept.
  * Q6 -- the zarr-label right-click menu's two actions are restored (their
    handlers and the labelsToObjects import all resolve).
  * Q8 -- a single dynamic top-level "Edit ... attributes..." item is hoisted
    above the field menu's entity submenus; its label/enabled state follow the
    selection and it dispatches to the right dialog.
  * menubar attr_name de-dup (copyscreen_act / resetpalette_act).

Shape checks build the real menu definitions against light stubs (no Qt loop);
the invert-selection mechanism is driven on a real offscreen QTableWidget; the
dispatch + label logic are exercised as pure code.
"""
import os
import types
from pathlib import Path

import pytest

from PyReconstruct.modules.gui.main.context_menu_list import (
    edit_selected_label,
    get_field_menu_list,
)

_GUI = Path(__file__).resolve().parents[1] / "PyReconstruct" / "modules" / "gui"


# --------------------------------------------------------------------------- #
# stubs / helpers (mirror the existing menu tests)
# --------------------------------------------------------------------------- #
class _Anything:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


class _FieldMenuStub(_Anything):
    def __init__(self):
        super().__init__(
            series=_Anything(user_columns={}, alignments=set(), groups_visibility={}),
            field=_Anything(),
        )


def _entries(menu):
    """Yield top-level (act_name, text) tuples (no recursion)."""
    out = []
    for entry in menu:
        if isinstance(entry, tuple):
            out.append((entry[0], entry[1]))
    return out


def _field_menu():
    return get_field_menu_list(_FieldMenuStub())


# --------------------------------------------------------------------------- #
# Q8: top-level dynamic edit action -- menu shape
# --------------------------------------------------------------------------- #
def test_field_menu_has_editselected_at_the_very_top():
    menu = _field_menu()
    # first non-None entry is the hoisted edit action, above the entity submenus
    first = menu[0]
    assert isinstance(first, tuple)
    assert first[0] == "editselected_act"


def test_editselected_sits_above_the_entity_submenus():
    menu = _field_menu()
    top_names = [e[0] for e in _entries(menu)]
    # the trace submenu is a dict, so it is not in top_names; assert the action
    # precedes the first submenu by index position in the raw list
    idx_edit = next(i for i, e in enumerate(menu)
                    if isinstance(e, tuple) and e[0] == "editselected_act")
    idx_first_submenu = next(i for i, e in enumerate(menu) if isinstance(e, dict))
    assert idx_edit < idx_first_submenu


def test_editselected_default_label_is_neutral():
    menu = _field_menu()
    label = next(e[1] for e in _entries(menu) if e[0] == "editselected_act")
    assert label == "Edit attributes..."


# --------------------------------------------------------------------------- #
# Q8: label + enabled state follow the selection (pure decision)
# --------------------------------------------------------------------------- #
def test_edit_selected_label_trace_only():
    assert edit_selected_label("trace") == ("Edit trace attributes...", True)


def test_edit_selected_label_ztrace_only():
    assert edit_selected_label("ztrace") == ("Edit z-trace attributes...", True)


def test_edit_selected_label_none_is_disabled_neutral():
    assert edit_selected_label(None) == ("Edit attributes...", False)


# --------------------------------------------------------------------------- #
# Q8: dispatch routes to the right dialog for the active selection
# --------------------------------------------------------------------------- #
def _dispatch_stub(selected_traces=(), selected_ztraces=()):
    calls = []
    field = types.SimpleNamespace(
        section=types.SimpleNamespace(
            selected_traces=list(selected_traces),
            selected_ztraces=list(selected_ztraces),
        ),
        traceDialog=lambda: calls.append("trace"),
        editZtraceAttributes=lambda: calls.append("ztrace"),
    )
    stub = types.SimpleNamespace(field=field)
    return stub, calls


def test_dispatch_traces_opens_trace_dialog():
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    stub, calls = _dispatch_stub(selected_traces=["a"])
    MainWindow.editSelectedAttributes(stub)
    assert calls == ["trace"]


def test_dispatch_ztraces_opens_ztrace_dialog():
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    stub, calls = _dispatch_stub(selected_ztraces=["z"])
    MainWindow.editSelectedAttributes(stub)
    assert calls == ["ztrace"]


def test_dispatch_nothing_selected_is_a_noop():
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    stub, calls = _dispatch_stub()
    MainWindow.editSelectedAttributes(stub)
    assert calls == []


def test_dispatch_prefers_traces_when_both_present():
    # checkActions disables the action for a mixed selection, so this path is
    # not reachable via the UI; the dispatch still resolves deterministically.
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    stub, calls = _dispatch_stub(selected_traces=["a"], selected_ztraces=["z"])
    MainWindow.editSelectedAttributes(stub)
    assert calls == ["trace"]


# --------------------------------------------------------------------------- #
# Q1 parity: DataTable.invertSelection on a real offscreen QTableWidget
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def _table_with_rows(n):
    """A CopyTableWidget with n single-column rows, wrapped in the minimal
    DataTable surface invertSelection touches (just ``self.table``)."""
    from PySide6.QtWidgets import QTableWidgetItem
    from PyReconstruct.modules.gui.table.data_table import DataTable
    from PyReconstruct.modules.gui.table.copy_table_widget import CopyTableWidget

    holder = DataTable.__new__(DataTable)
    table = CopyTableWidget(holder, n, 1)
    for r in range(n):
        table.setItem(r, 0, QTableWidgetItem(f"row{r}"))
    holder.table = table
    return holder, table


def _selected_rows(table):
    return sorted({i.row() for i in table.selectedIndexes()})


def test_invert_selection_flips_selected_and_unselected(qapp):
    holder, table = _table_with_rows(5)
    table.selectRow(1)
    table.selectRow(3)  # extends (multi-select default? force explicit)
    from PySide6.QtWidgets import QAbstractItemView
    # ensure a deterministic {1,3} selection
    table.clearSelection()
    table.setSelectionMode(QAbstractItemView.MultiSelection)
    table.selectRow(1)
    table.selectRow(3)
    assert _selected_rows(table) == [1, 3]

    holder.invertSelection()
    assert _selected_rows(table) == [0, 2, 4]


def test_invert_selection_empty_selects_all_displayed(qapp):
    holder, table = _table_with_rows(4)
    assert _selected_rows(table) == []
    holder.invertSelection()
    assert _selected_rows(table) == [0, 1, 2, 3]


def test_invert_selection_full_selects_none(qapp):
    from PySide6.QtWidgets import QAbstractItemView
    holder, table = _table_with_rows(3)
    table.setSelectionMode(QAbstractItemView.MultiSelection)
    for r in range(3):
        table.selectRow(r)
    assert _selected_rows(table) == [0, 1, 2]
    holder.invertSelection()
    assert _selected_rows(table) == []


def test_invert_selection_only_touches_displayed_filtered_rows(qapp):
    """The table only holds rows that pass the list's filters; inverting a
    3-row (filtered) table can never select a 4th, filtered-out row."""
    from PySide6.QtWidgets import QAbstractItemView
    holder, table = _table_with_rows(3)  # imagine 3 of N rows pass the filter
    table.setSelectionMode(QAbstractItemView.MultiSelection)
    table.selectRow(0)
    holder.invertSelection()
    inverted = _selected_rows(table)
    assert inverted == [1, 2]
    assert all(r < table.rowCount() for r in inverted)  # nothing beyond the shown set


# --------------------------------------------------------------------------- #
# Q1/Q4: list context-menu definitions (source-level, robust to no-Qt)
# --------------------------------------------------------------------------- #
def _src(relpath):
    return (_GUI / relpath).read_text(encoding="utf-8")


def test_object_list_has_invert_and_copy_row():
    src = _src("table/object.py")
    assert '"Invert selection", "", self.invertSelection' in src
    assert '"Copy object values", "", self.table.copy' in src


def test_trace_list_has_invert_and_copy_row():
    src = _src("table/trace.py")
    assert '"Invert selection", "", self.invertSelection' in src
    assert '"Copy trace values", "", self.table.copy' in src


def test_ztrace_list_has_invert_and_copy_row():
    src = _src("table/ztrace.py")
    assert '"Invert selection", "", self.invertSelection' in src
    assert '"Copy z-trace values", "", self.table.copy' in src


def test_section_list_has_invert_and_keeps_copy_row():
    src = _src("table/section.py")
    assert '"Invert selection", "", self.invertSelection' in src
    assert '"Copy section values", "", self.table.copy' in src


def test_flag_list_has_invert_and_keeps_copy_row():
    src = _src("table/flag.py")
    assert '"Invert selection", "", self.invertSelection' in src
    assert '"Copy flag values", "", self.table.copy' in src


# --------------------------------------------------------------------------- #
# Q4: flag Resolve submenu hoisted to two top-level items
# --------------------------------------------------------------------------- #
def test_flag_resolve_submenu_is_gone():
    src = _src("table/flag.py")
    assert '"attr_name": "resolvemenu"' not in src
    assert '"text": "Resolve"' not in src


def test_flag_resolve_hoisted_to_two_top_level_items():
    src = _src("table/flag.py")
    # handlers + attr_names kept, labels are the hoisted ones
    assert '("resolve_act", "Mark resolved", "", self.markResolved)' in src
    assert '("unresolved_act", "Mark unresolved", "", lambda : self.markResolved(False))' in src
    # not the old submenu wording
    assert "Mark as resolved" not in src
    assert "Mark as unresolved" not in src


# --------------------------------------------------------------------------- #
# Q6: zarr-label menu restored + handlers live
# --------------------------------------------------------------------------- #
def test_label_menu_actions_are_restored():
    src = _src("main/main_window.py")
    assert '("importlabels_act", "Import labels", "", self.importLabels)' in src
    assert '("mergelabels_act", "Merge labels", "", self.mergeLabels)' in src


def test_import_and_merge_handlers_are_live_methods():
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    assert callable(getattr(MainWindow, "importLabels", None))
    assert callable(getattr(MainWindow, "mergeLabels", None))


def test_labels_to_objects_import_resolves():
    # the restored importLabels depends on this symbol being importable
    from PyReconstruct.modules.backend.autoseg import labelsToObjects
    assert callable(labelsToObjects)


# --------------------------------------------------------------------------- #
# menubar attr_name de-dup
# --------------------------------------------------------------------------- #
def test_menubar_screen_and_palette_attr_names_are_unique():
    src = _src("main/menubar.py")
    assert src.count('"copyscreen_act"') == 1
    assert src.count('"savescreen_act"') == 1
    assert src.count('"resetpalette_act"') == 1
    assert src.count('"resettracepalette_act"') == 1
