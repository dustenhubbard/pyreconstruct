"""The flag and trace lists keep a parallel row -> data list that outlives the table.

Both lists map a table row to its Python payload through a plain list held
beside the QTableWidget: ``FlagTableWidget.displayed_flags`` (row -> Flag) and
``TraceTableWidget.rows`` (row -> trace data). Both are created empty in
``__init__`` and both grow in ``setRow``::

    while len(self.displayed_flags) <= row:
        self.displayed_flags.append(None)
    self.displayed_flags[row] = flag

``DataTable.createTable`` builds a BRAND-NEW ``CopyTableWidget`` sized to the
filtered data and then calls ``setRow`` for rows 0..N-1 only. It never resets
the parallel list. So a rebuild that shrinks the table -- a regex filter, a
color filter, a comment filter, turning "Display resolved flags" back off,
changing section for the trace list -- overwrites the first N entries and
leaves every entry past N in place, pointing at rows that no longer exist. The
lists only ever grow.

No user-visible defect follows from this. Every read is an indexed lookup at a
row the live table reports (``getSelected`` maps ``selectedRows()``, which comes
from ``table.selectedIndexes()``; ``TraceTableWidget.itemChanged`` uses
``item.row()``), and rows 0..N-1 are rewritten on every rebuild, so the stale
tail is unaddressable. Nothing iterates either list, nothing takes its ``len``
as a row count, and nothing zips it against the table. The insert/remove pair
in ``updateData`` shifts list and table by the same index, so the alignment of
the live prefix survives an over-long list too -- that is asserted below rather
than assumed.

What it does cost is retention: the tail holds Flag and trace-data objects
alive for rows the user filtered away, including ones whose underlying traces
or flags have since been deleted, for as long as the list widget is open. On a
series with thousands of traces, filtering down to a handful frees nothing.

These tests pin both halves: the list is truncated with the table, AND the
live rows still map to the right payload afterwards.
"""

import pytest

# No importorskip("pytestqt") -- see tests/test_data_lists_real_widget.py: the
# skip is what let a mis-synced .venv drop every widget test and still report
# green. tests/conftest.py errors instead.
pytestmark = pytest.mark.gui


from tests.test_data_lists_real_widget import (  # noqa: E402
    flag_table,  # noqa: F401  (fixture)
    list_mainwindow,  # noqa: F401  (fixture)
    trace_table,  # noqa: F401  (fixture)
)


# One of the six flags the flag_table fixture creates ("flag00".."flag05",
# two per section on 3, 4 and 5). Matching a single name is the smallest
# shrink that still leaves a live row to check the mapping against.
ONE_FLAG_RE = "flag04"

# The trace fixture's section 44 shows five rows: d03, d03p12, and d03sp12 x3.
# Filtering to the one multi-trace contour shrinks five rows to three and
# leaves rows whose (name, index) pairs differ only in the index -- so a
# mapping that survived the truncation by luck rather than by index shows up.
MULTI_TRACE_CONTOUR = "d03sp12"
MULTI_TRACE_ROWS = 3


def test_flag_list_starts_in_sync(flag_table):  # noqa: F811
    """The premise: before any filter, list length == row count."""
    assert flag_table.table.rowCount() == 6
    assert len(flag_table.displayed_flags) == 6


def test_flag_list_truncates_when_a_filter_shrinks_the_table(flag_table):  # noqa: F811
    """The defect. Six rows down to one must leave one entry, not six."""
    flag_table.re_filters = {ONE_FLAG_RE}
    flag_table.createTable()

    assert flag_table.table.rowCount() == 1
    assert len(flag_table.displayed_flags) == flag_table.table.rowCount()


def test_flag_list_still_maps_every_live_row_after_shrinking(flag_table):  # noqa: F811
    """Truncating must not disturb the rows that remain.

    Reads through the real selection path, one row at a time, so a truncation
    that chopped the wrong end would show up as the wrong Flag rather than as
    an IndexError only.
    """
    flag_table.re_filters = {ONE_FLAG_RE}
    flag_table.createTable()

    for r in range(flag_table.table.rowCount()):
        flag_table.table.clearSelection()
        flag_table.table.selectRow(r)
        assert flag_table.getSelected(single=True).name == ONE_FLAG_RE


def test_flag_list_stays_in_sync_across_a_shrink_then_a_section_update(
    flag_table,  # noqa: F811
):
    """``updateData`` after a shrink: still one entry per row.

    ``updateData`` removes and re-inserts the rows of one section through
    ``removeRow``/``insertRow``, which pop and insert the parallel list at the
    same index. Widening the filter back out grows the table again; the list
    must track it in both directions.
    """
    series = flag_table.series

    flag_table.re_filters = {ONE_FLAG_RE}
    flag_table.createTable()

    flag_table.re_filters = {".*"}
    flag_table.createTable()
    assert flag_table.table.rowCount() == 6
    assert len(flag_table.displayed_flags) == 6

    flag_table.updateData(series.loadSection(4))
    assert len(flag_table.displayed_flags) == flag_table.table.rowCount()

    for r in range(flag_table.table.rowCount()):
        flag_table.table.clearSelection()
        flag_table.table.selectRow(r)
        selected = flag_table.getSelected(single=True)
        assert selected is not None
        assert str(selected.snum) == flag_table.table.item(r, 0).text()


def test_trace_list_starts_in_sync(trace_table):  # noqa: F811
    """The same premise for the trace list's ``rows``."""
    assert trace_table.table.rowCount() == 5
    assert len(trace_table.rows) == 5


def test_trace_list_truncates_when_a_filter_shrinks_the_table(trace_table):  # noqa: F811
    """The same defect in ``TraceTableWidget.rows``, which the backlog item
    for ``displayed_flags`` does not name."""
    trace_table.re_filters = {MULTI_TRACE_CONTOUR}
    trace_table.createTable(trace_table.section)

    assert trace_table.table.rowCount() == MULTI_TRACE_ROWS
    assert len(trace_table.rows) == trace_table.table.rowCount()


def test_trace_list_still_maps_every_live_row_after_shrinking(trace_table):  # noqa: F811
    """Every remaining row still resolves to its own trace.

    ``getSelected`` returns ``(name, index)`` pairs; the indices must be the
    distinct per-contour indices of the three surviving d03sp12 traces, not a
    repeat or a stale one.
    """
    trace_table.re_filters = {MULTI_TRACE_CONTOUR}
    trace_table.createTable(trace_table.section)

    selected = []
    for r in range(trace_table.table.rowCount()):
        trace_table.table.clearSelection()
        trace_table.table.selectRow(r)
        got = trace_table.getSelected()
        assert len(got) == 1
        assert got[0][0] == trace_table.table.item(r, 0).text()
        selected.append(got[0])

    assert len(set(selected)) == trace_table.table.rowCount()
