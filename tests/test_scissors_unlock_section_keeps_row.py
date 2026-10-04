"""Unlocking the section in the middle of a scissors cut keeps the object row.

The scissors pickup takes the clicked trace out of the section until the cut
ends. `Unlock current section` refreshed every list from the section, so it
saw the object without its trace: the Object List dropped the row and the
history logged the object as deleted. Backing out of the cut put the trace
back without a refresh, so the row stayed gone. The unlock now refreshes only
the section list.

Driven through the live `MainWindow`: a real left click with the Scissors
tool, then the field's `unlockSection`, the slot behind the menu item.
"""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.gui.main.field_widget_5_mouse import SCISSORS

pytestmark = pytest.mark.gui

NAME = "scissors_unlock_probe"


def _square(series):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.2
    x0, y0 = wx + ww * 0.3, wy + wh * 0.3
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


def _locked_section_with_object(main_window, qapp):
    """A one-trace object on a locked section, with an Object List open."""
    field = main_window.field
    field.setTracingTrace(Trace(NAME, (0, 255, 0), True))
    field.newTrace(_square(main_window.series), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)
    field.section.align_locked = True
    field.table_manager.newTable("object")
    qapp.processEvents()
    table = field.table_manager.tables["object"][-1]
    trace = [t for t in field.section.tracesAsList() if t.name == NAME][0]
    return table, trace


def _has_row(table):
    return table.model.rowOf(NAME)[1]


def _pickup(main_window, qapp, trace):
    field = main_window.field
    main_window.mouse_palette.activateModeButton("Scissors")
    qapp.processEvents()
    assert field.mouse_mode == SCISSORS
    x, y = [int(round(v)) for v in field.section_layer.traceToPix(trace)[0]]
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    qapp.processEvents()


def _deleted_logs(series):
    return [
        log for log in series.log_set.all_logs
        if log.obj_name == NAME and "Delete" in log.event
    ]


@pytest.mark.parametrize("ending", ["finish", "cancel"])
def test_unlock_during_a_scissors_cut_keeps_the_object_row(main_window, qapp, ending):
    field = main_window.field
    table, trace = _locked_section_with_object(main_window, qapp)
    assert _has_row(table)

    _pickup(main_window, qapp, trace)
    assert field.is_scissoring

    field.unlockSection()
    qapp.processEvents()

    assert not field.section.align_locked
    assert field.series.data["sections"][field.section.n]["locked"] is False
    # the cut is still open, and the object is only borrowed by it
    assert field.is_scissoring
    assert _has_row(table)

    if ending == "finish":
        field.lineRelease(override=True)
    else:
        field.cancelScissors()
    qapp.processEvents()

    assert not field.is_scissoring
    assert any(t.name == NAME for t in field.section.tracesAsList())
    assert _has_row(table)
    assert _deleted_logs(field.series) == []
