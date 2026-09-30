"""Section list `Modify ▸ Edit all image sources...` keeps unsaved traces.

`modifyAllSrc` loads every section from disk, sets its source, saves it, and
then calls `field.reload()`, which swaps the disk copies of the current and
flickered sections into the field. It never saved the field first, so traces
drawn since the last save vanished from both sections.
"""
import pytest

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.gui.table import section as section_mod
from PyReconstruct.modules.gui.table.section import SectionTableWidget

NAME = "edit_all_src_unsaved"
SQUARE = [(100, 300), (200, 300), (200, 200), (100, 200)]


@pytest.fixture
def table(main_window, monkeypatch):
    series = main_window.series
    # the fixture ships every section locked, and modifyAllSrc refuses locked
    # sections, so unlock them on disk and reload the field
    for snum in list(series.sections):
        s = series.loadSection(snum)
        s.align_locked = False
        s.save()
    main_window.field.reload()
    monkeypatch.setattr(
        section_mod.QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("img_#.tif", True)),
    )
    return SectionTableWidget(series, main_window, main_window.field.table_manager)


def _draw(field):
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(SQUARE, field.tracing_trace, closed=True)


def _count(section):
    return len(section.contours.get(NAME, []))


def test_edit_all_src_keeps_unsaved_trace_on_current_section(main_window, table):
    field, series = main_window.field, main_window.series
    _draw(field)
    assert _count(field.section) == 1
    current = series.current_section

    table.modifyAllSrc()

    assert field.section.src.startswith("img_")
    assert _count(field.section) == 1, "the unsaved trace vanished from the field"
    assert _count(series.loadSection(current)) == 1, "the trace never reached disk"


def test_edit_all_src_keeps_unsaved_trace_on_flickered_section(main_window, table):
    field, series = main_window.field, main_window.series
    first = series.current_section
    other = next(n for n in sorted(series.sections) if n != first)

    _draw(field)
    field.changeSection(other)  # parks the unsaved first section as b_section
    assert field.b_section is not None and field.b_section.n == first
    _draw(field)

    table.modifyAllSrc()

    assert field.section.n == other
    assert _count(field.section) == 1
    assert field.b_section is not None and field.b_section.n == first
    assert _count(field.b_section) == 1, "the flickered section lost its trace"
    for snum in (first, other):
        disk = series.loadSection(snum)
        assert disk.src.startswith("img_")
        assert _count(disk) == 1
