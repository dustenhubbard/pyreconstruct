"""`Optimize...` keeps unsaved traces.

`MainWindow.optimizeBC` hands the sections to `optimizeSeriesBC`, which loads
each one from disk, sets its brightness and contrast, and saves it, and then
calls `field.reload()`, which swaps the disk copies of the current and
flickered sections into the field. It never saved the field first, so traces
drawn since the last save vanished from both sections.
"""
import pytest

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.gui.main import main_window as mw

NAME = "optimize_bc_unsaved"
SQUARE = [(100, 300), (200, 300), (200, 200), (100, 200)]


@pytest.fixture
def confirmed(monkeypatch):
    monkeypatch.setattr(
        mw.QuickDialog, "get",
        staticmethod(lambda *a, **k: ([128, 60.0, [(None, True)]], True)),
    )
    monkeypatch.setattr(mw, "noUndoWarning", lambda *a, **k: True)


def _draw(field):
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(SQUARE, field.tracing_trace, closed=True)


def _count(section):
    return len(section.contours.get(NAME, []))


@pytest.mark.parametrize("from_list", [False, True], ids=["series", "section_list"])
def test_optimize_bc_keeps_unsaved_trace_on_current_section(main_window, confirmed, from_list):
    field, series = main_window.field, main_window.series
    _draw(field)
    current = series.current_section

    main_window.optimizeBC([current] if from_list else None)

    assert _count(field.section) == 1, "the unsaved trace vanished from the field"
    assert _count(series.loadSection(current)) == 1, "the trace never reached disk"


def test_optimize_bc_keeps_unsaved_trace_on_flickered_section(main_window, confirmed):
    field, series = main_window.field, main_window.series
    first = series.current_section
    other = next(n for n in sorted(series.sections) if n != first)

    _draw(field)
    field.changeSection(other)  # parks the unsaved first section as b_section
    assert field.b_section is not None and field.b_section.n == first
    _draw(field)

    main_window.optimizeBC([first, other])

    assert field.section.n == other
    assert _count(field.section) == 1
    assert field.b_section is not None and field.b_section.n == first
    assert _count(field.b_section) == 1, "the flickered section lost its trace"
    for snum in (first, other):
        assert _count(series.loadSection(snum)) == 1
