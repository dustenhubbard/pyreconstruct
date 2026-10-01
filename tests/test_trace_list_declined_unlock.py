"""Declining the unlock prompt from a trace list checkbox.

Ticking `Hidden` or `Closed` on a locked object's row asks to unlock it. A No
returned from `itemChanged` with the box left ticked and the recursion guard
still off, so the box no longer matched the trace and every later checkbox
click in the list was ignored. The real widget and real Qt items run here; only
the field is a stand-in.
"""
import pytest
from PySide6.QtCore import Qt

from test_data_lists_real_widget import (  # noqa: F401  (fixture)
    trace_table,
    list_mainwindow,
)

pytestmark = pytest.mark.gui


def _other_row(table, name):
    return next(
        r for r in range(table.rowCount()) if table.item(r, 0).text() != name
    )


@pytest.mark.parametrize("column", ["Hidden", "Closed"])
def test_a_declined_unlock_puts_the_box_back(trace_table, column):
    table = trace_table.table
    field = trace_table.mainwindow.field
    locked_name = table.item(0, 0).text()
    trace_table.series.setAttr(locked_name, "locked", True)
    field.notify_locked_response = False
    col = trace_table.horizontal_headers.index(column)
    item = table.item(0, col)
    before = item.checkState()
    after = (Qt.CheckState.Unchecked if before == Qt.CheckState.Checked
             else Qt.CheckState.Checked)

    item.setCheckState(after)

    assert field.notify_locked_calls == [locked_name]
    assert table.item(0, col).checkState() == before
    assert "hideTraces" not in field.calls
    assert "closeTraces" not in field.calls


def test_checkboxes_still_work_after_a_declined_unlock(trace_table):
    table = trace_table.table
    field = trace_table.mainwindow.field
    locked_name = table.item(0, 0).text()
    trace_table.series.setAttr(locked_name, "locked", True)
    field.notify_locked_response = False
    col = trace_table.horizontal_headers.index("Hidden")
    table.item(0, col).setCheckState(Qt.CheckState.Checked)

    row = _other_row(table, locked_name)
    table.item(row, col).setCheckState(Qt.CheckState.Checked)

    assert "hideTraces" in field.calls
