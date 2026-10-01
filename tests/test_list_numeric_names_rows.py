"""Lists keep one row per item when object names are numbers.

The trace and z-trace lists are sorted with `sortList`, which orders "1",
"10", "2" as text. A single-row update then placed the name with `lessThan`,
which compared numeric names as numbers, so it looked for "2" before "10",
did not find it, and inserted a second row. A deleted "2" was never found
either, so its row stayed. `lessThan` now uses the order `sortList` uses.
"""
import pytest

from PyReconstruct.modules.datatypes import Trace, Ztrace
from PyReconstruct.modules.gui.utils import lessThan, sortList

from test_data_lists_real_widget import (  # noqa: F401  (fixture)
    StubListManager,
    list_mainwindow,
)

pytestmark = pytest.mark.gui

NAMES = ("1", "2", "10")


def _rows(table):
    return [table.item(r, 0).text() for r in range(table.rowCount())]


def test_lessThan_agrees_with_sortList():
    names = ["1", "2", "10", "a", "B", "b2", "b10", "20x"]
    ordered = sortList(names)
    for i, earlier in enumerate(ordered):
        for later in ordered[i + 1:]:
            assert lessThan(earlier, later), (earlier, later)
            assert not lessThan(later, earlier), (later, earlier)


@pytest.fixture
def numeric_trace_table(qapp, list_mainwindow, gui_dialogs):
    from PyReconstruct.modules.gui.table.trace import TraceTableWidget
    series = list_mainwindow.series
    snum = sorted(series.sections)[1]
    section = series.loadSection(snum)
    for name in NAMES:
        trace = Trace(name, (0, 255, 0))
        trace.points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        section.addTrace(trace, log_event=False)
    section.save()
    series.data.updateSection(section, update_traces=True, log_events=False)
    widget = TraceTableWidget(series, section, list_mainwindow,
                              StubListManager())
    yield widget, section
    widget.deleteLater()


def test_updating_a_numeric_trace_keeps_one_row(numeric_trace_table):
    widget, section = numeric_trace_table
    series = widget.series
    for _ in range(2):
        trace = section.contours["2"][0]
        trace.points = [(x + 1, y) for x, y in trace.points]
        series.data.updateSection(section, update_traces=True,
                                  log_events=False)
        widget.updateData({"2"})
    assert [n for n in _rows(widget.table) if n.isnumeric()] == ["1", "10", "2"]


def test_deleting_a_numeric_trace_removes_its_row(numeric_trace_table):
    widget, section = numeric_trace_table
    section.removeTrace(section.contours["2"][0], log_event=False)
    widget.series.data.updateSection(section, update_traces=True,
                                     log_events=False)
    widget.updateData({"2"})
    assert [n for n in _rows(widget.table) if n.isnumeric()] == ["1", "10"]


@pytest.fixture
def numeric_ztrace_table(qapp, list_mainwindow, gui_dialogs):
    from PyReconstruct.modules.gui.table.ztrace import ZtraceTableWidget
    series = list_mainwindow.series
    for name in NAMES:
        series.ztraces[name] = Ztrace(
            name, (255, 0, 0), [(0.1, 0.2, s) for s in (3, 4, 5)]
        )
    widget = ZtraceTableWidget(series, list_mainwindow, StubListManager())
    yield widget
    widget.deleteLater()


def test_updating_and_deleting_a_numeric_ztrace(numeric_ztrace_table):
    widget = numeric_ztrace_table
    widget.updateData({"2"})
    widget.updateData({"2"})
    assert _rows(widget.table) == ["1", "10", "2"]

    del widget.series.ztraces["2"]
    widget.updateData({"2"})
    assert _rows(widget.table) == ["1", "10"]
