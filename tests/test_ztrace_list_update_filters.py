"""A z-trace list update keeps the list's regex and group filters.

`ZtraceTableWidget.updateData` inserted a row for every name it was handed, so
an update that named every z-trace (editing section thickness does) or one
hidden z-trace brought filtered-out z-traces into a filtered list.
"""
import pytest

from PyReconstruct.modules.datatypes import Ztrace

from test_data_lists_real_widget import (  # noqa: F401  (fixture)
    StubListManager,
    list_mainwindow,
)

pytestmark = pytest.mark.gui

NAMES = ("axon01", "axon02", "dend01", "dend02")


def _rows(widget):
    return [widget.table.item(r, 0).text() for r in range(widget.table.rowCount())]


@pytest.fixture
def ztrace_widget(qapp, list_mainwindow, gui_dialogs):
    from PyReconstruct.modules.gui.table.ztrace import ZtraceTableWidget
    series = list_mainwindow.series
    for name in NAMES:
        series.ztraces[name] = Ztrace(
            name, (255, 0, 0), [(0.1, 0.2, s) for s in (3, 4, 5)]
        )
    widget = ZtraceTableWidget(series, list_mainwindow, StubListManager())
    yield widget
    widget.deleteLater()


def test_a_regex_filter_survives_an_update_of_every_ztrace(ztrace_widget):
    widget = ztrace_widget
    widget.re_filters = {"axon.*"}
    widget.createTable()
    assert _rows(widget) == ["axon01", "axon02"]

    widget.updateData(set(widget.series.ztraces))

    assert _rows(widget) == ["axon01", "axon02"]


def test_a_group_filter_survives_an_update_of_a_hidden_ztrace(ztrace_widget):
    widget = ztrace_widget
    widget.series.ztrace_groups.add("G", "axon01")
    widget.group_filters = {"G"}
    widget.createTable()
    assert _rows(widget) == ["axon01"]

    widget.updateData({"dend01"})

    assert _rows(widget) == ["axon01"]


def test_a_ztrace_that_stops_passing_leaves_the_list(ztrace_widget):
    widget = ztrace_widget
    widget.series.ztrace_groups.add("G", "axon01")
    widget.series.ztrace_groups.add("G", "axon02")
    widget.group_filters = {"G"}
    widget.createTable()

    widget.series.ztrace_groups.remove("G", "axon02")
    widget.updateData({"axon02"})

    assert _rows(widget) == ["axon01"]


def test_a_ztrace_that_starts_passing_joins_the_list(ztrace_widget):
    widget = ztrace_widget
    widget.series.ztrace_groups.add("G", "axon01")
    widget.group_filters = {"G"}
    widget.createTable()

    widget.series.ztrace_groups.add("G", "dend02")
    widget.updateData({"dend02"})

    assert _rows(widget) == ["axon01", "dend02"]
