"""TraceTableWidget.getTraces() during the series-data / section desync window.

The trace list's rows come from ``series.data``, not from the section it is
displaying: ``getPassingTraces`` calls
``self.series.data.getTraceData(name, self.section.n)``. A series-wide operation
writes its sections and updates ``series.data``, then repaints the lists
(``table_manager.updateObjects`` in ``object_function``'s wrapper, and the same
sequence in ``copyObjects``), and only *afterwards* calls ``field.reload()`` to
swap in a section object containing the new traces. Between those two steps the
table can hold a row for a trace the displayed ``Section`` does not have.

``getFeret`` used to crash in exactly this window and was fixed in #98 by
returning ``None`` so the cell renders blank and refills on the next section
change. ``getTraces`` had the same unguarded lookup:

    traces.append(self.section.contours[name][index])

which raises ``KeyError`` when the section has no contour of that name and
``IndexError`` when it has the contour but not that many traces. It is reached
by every trace-list context-menu action -- ``trace_function`` in
field_widget_2_trace.py calls ``data_table.getTraces(data_table.getSelected())``
-- so clicking such a row and picking any action raises.

The fix follows #98: a row that does not resolve on the displayed section is
skipped. ``trace_function`` already returns early on an empty list, so the
action becomes a no-op rather than a traceback, and the reload rebuilds the
table against the section that does have the trace.
"""

import os
import shutil
import types

import pytest

from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.contour import Contour
from PyReconstruct.modules.gui.table.trace import TraceTableWidget


FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets", "checker",
    "files", "shapes1.jser"
)


def _qapp():
    return QApplication.instance() or QApplication(["test"])


def _trace(name, dx=0.0):
    t = Trace(name, (0, 255, 0))
    t.points = [(dx, 0.0), (dx + 1.0, 0.0), (dx + 1.0, 1.0), (dx, 1.0)]
    return t


def _section_with(**counts):
    """The only attribute getTraces touches on its section is ``contours``.

    ``counts`` maps a contour name to how many traces it holds; Contour rejects
    traces whose name does not match, so they are built per contour.
    """
    contours = {}
    traces = {}
    for name, n in counts.items():
        traces[name] = [_trace(name, dx=float(i)) for i in range(n)]
        contours[name] = Contour(name, traces[name])
    return types.SimpleNamespace(contours=contours), traces


def _table(section):
    """A stand-in for the widget: getTraces reads only ``self.section``.

    Same technique as tests/test_perf_equivalence.py, which calls
    ``TraceTableWidget.getItems`` unbound against a SimpleNamespace. Building a
    real TraceTableWidget needs a MainWindow and a TableManager, and would test
    Qt rather than the lookup.
    """
    return types.SimpleNamespace(section=section)


class _RowBuildingTable:
    """The real row-building and lookup methods, without the Qt widget.

    ``getPassingTraces``/``passesFilters``/``getTraces`` are taken off the class
    unchanged, so the row this builds is the row the widget builds.
    """

    getPassingTraces = TraceTableWidget.getPassingTraces
    passesFilters = TraceTableWidget.passesFilters
    getTraces = TraceTableWidget.getTraces

    def __init__(self, series, section):
        self.series = series
        self.section = section
        self.re_filters = {".*"}
        self.tag_filters = set()
        self.group_filters = set()
        self.hide_filter = "all"


# ---------------------------------------------------------------------------
# the crash
# ---------------------------------------------------------------------------

def test_row_for_a_contour_the_section_lacks_is_skipped():
    """KeyError before the fix: the section has no contour of that name."""
    section, _ = _section_with(present=1)
    assert TraceTableWidget.getTraces(_table(section), [("ghost", 0)]) == []


def test_row_past_the_end_of_an_existing_contour_is_skipped():
    """IndexError before the fix: the contour exists but is shorter."""
    section, _ = _section_with(obj=1)
    table = _table(section)
    assert TraceTableWidget.getTraces(table, [("obj", 1)]) == []
    assert TraceTableWidget.getTraces(table, [("obj", 7)]) == []


def test_resolvable_rows_are_still_returned_in_order():
    """No behaviour change for rows the section does have."""
    section, traces = _section_with(a=1, multi=2)
    a = traces["a"][0]
    b, c = traces["multi"]
    got = TraceTableWidget.getTraces(
        _table(section), [("multi", 1), ("a", 0), ("multi", 0)]
    )
    assert [id(g) for g in got] == [id(c), id(a), id(b)]


def test_a_mix_returns_only_the_rows_the_section_can_resolve():
    section, traces = _section_with(a=1, b=1)
    a, b = traces["a"][0], traces["b"][0]
    got = TraceTableWidget.getTraces(
        _table(section), [("a", 0), ("ghost", 0), ("b", 0), ("b", 3)]
    )
    assert [id(g) for g in got] == [id(a), id(b)]


def test_empty_item_list_is_still_an_empty_result():
    section, _ = _section_with()
    assert TraceTableWidget.getTraces(_table(section), []) == []


# ---------------------------------------------------------------------------
# the desync window itself, on a real series
# ---------------------------------------------------------------------------

def test_the_table_really_does_build_a_row_the_displayed_section_lacks(tmp_path):
    """The premise, not the symptom: series.data gains a trace row while the
    displayed Section object does not have the trace.

    Reproduces what a series-wide operation does -- write the new traces into
    the sections it loaded and update series.data -- while the table still holds
    the Section object it was created with, which is a *different* object and
    has no such trace. The row exists, and resolving it is what used to raise.
    """
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")

    _qapp()
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.datatypes.series_data import SeriesData
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(FIXTURE, fp)

    series = Series.openJser(fp)
    series.setProgressReporter(NullProgressReporter)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd

    try:
        snum = sorted(series.sections)[0]

        ## the section object the trace list is displaying
        displayed = series.loadSection(snum)

        ## what a series-wide operation does: load its own section object, add
        ## the traces, update the series data. field.reload() has not run, so
        ## `displayed` is untouched.
        written = series.loadSection(snum)
        ghost = _trace("zzz_ghost")
        written.addTrace(ghost, log_event=False)
        sd.updateSection(written, update_traces=True, log_events=False)

        assert "zzz_ghost" not in displayed.contours

        ## the table builds its rows from series.data for this section number
        table = _RowBuildingTable(series, displayed)
        passing = table.getPassingTraces("zzz_ghost")
        assert len(passing) == 1, "no row was built: the desync premise is stale"

        items = [(name, td.index) for name, td in passing]
        assert items == [("zzz_ghost", 0)]

        ## this is the call every trace-list context-menu action makes
        assert table.getTraces(items) == []

        ## and once the field reloads, the same row resolves
        table.section = written
        assert [id(t) for t in table.getTraces(items)] == [id(ghost)]
    finally:
        series.close()
