"""Saving, closing or reloading in the middle of a scissors cut keeps the trace.

The scissors pickup takes the clicked trace out of the section, logs nothing and
saves no undo state; until the cut ends the trace exists only as the line being
edited. Cmd+S in that window wrote the section without it, marked the series
saved, and Close then deleted the working folder. Reopening the file found no
trace, and undo had nothing to bring back.

Anything that writes or rereads the section now backs the open cut out first,
the same as Backspace does, so the trace goes back exactly as it was.

Driven through the live `MainWindow`: a real left click with the Scissors tool,
then the real Save action, a real close and a fresh `Series.openJser`.
"""
import os
import shutil

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.main.field_widget_5_mouse import SCISSORS

pytestmark = pytest.mark.gui


def _pick_trace(field, closed):
    """An unlocked trace of at least three points, opened if asked.

    The fixture section has closed traces only, so the open case opens one
    and saves that as an ordinary edit first, so the file on disk has it.
    """
    for name, contour in field.section.contours.items():
        if field.series.getAttr(name, "locked"):
            continue
        for trace in contour.getTraces():
            if trace.closed and len(trace.points) >= 3:
                if not closed:
                    trace.closed = False
                    field.section.modified_contours.add(name)
                    field.saveState()
                field.generateView()
                return trace
    raise AssertionError("fixture section has no unlocked closed trace")


def _matching(section, name, points):
    contour = section.contours.get(name)
    if not contour:
        return []
    return [t for t in contour.getTraces() if t.points == points]


def _count(section, name):
    contour = section.contours.get(name)
    return len(contour.getTraces()) if contour else 0


def _pickup(main_window, qapp, trace):
    field = main_window.field
    main_window.mouse_palette.activateModeButton("Scissors")
    qapp.processEvents()
    assert field.mouse_mode == SCISSORS
    x, y = [int(round(v)) for v in field.section_layer.traceToPix(trace)[0]]
    QTest.mousePress(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseRelease(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    qapp.processEvents()
    assert field.is_scissoring
    assert field.is_line_tracing


@pytest.mark.parametrize("closed", [True, False])
def test_save_then_close_in_the_middle_of_a_cut_keeps_the_trace(
    main_window, qapp, tmp_path, closed
):
    field = main_window.field
    trace = _pick_trace(field, closed)
    name, points = trace.name, list(trace.points)
    snum = field.section.n
    before = _count(field.section, name)

    _pickup(main_window, qapp, trace)
    assert _count(field.section, name) == before - 1

    # Cmd+S, through the real action
    main_window.save_act.trigger()
    qapp.processEvents()

    assert not field.is_scissoring
    assert not field.is_line_tracing
    assert field.mouse_mode == SCISSORS
    assert not main_window.series.modified
    assert len(_matching(field.section, name, points)) == 1

    jser_fp = main_window.series.jser_fp
    hidden_dir = main_window.series.hidden_dir
    assert main_window.close() is True
    assert not os.path.isdir(hidden_dir), "close kept the working folder"

    # reopen a copy in its own folder, so the window's teardown close cannot
    # touch the reopened series' working folder
    copy = tmp_path / "reopened" / "series.jser"
    copy.parent.mkdir()
    shutil.copyfile(jser_fp, copy)
    reopened = Series.openJser(str(copy))
    try:
        section = reopened.loadSection(snum)
        assert _count(section, name) == before
        kept = _matching(section, name, points)
        assert len(kept) == 1
        assert kept[0].closed == closed
    finally:
        reopened.close()


def test_saving_in_the_middle_of_a_cut_is_not_an_edit(main_window, qapp):
    """Backing the cut out logs nothing and adds no undo state, as Backspace."""
    field = main_window.field
    trace = _pick_trace(field, True)
    states = field.series_states[field.series.current_section]
    undo_before = len(states.undo_states)
    log_before = len(field.series.log_set.all_logs)

    _pickup(main_window, qapp, trace)
    main_window.saveAllData()

    assert not field.is_scissoring
    assert len(states.undo_states) == undo_before
    assert len(field.series.log_set.all_logs) == log_before


def test_the_working_folder_keeps_the_trace(main_window, qapp):
    """saveAllData is the one write that Save, Save As, Close, Open and New all
    go through, and most series-wide actions call it before they reread the
    sections. What it leaves in the working folder is what they all see."""
    field = main_window.field
    trace = _pick_trace(field, True)
    name, points = trace.name, list(trace.points)
    snum = field.section.n
    before = _count(field.section, name)

    _pickup(main_window, qapp, trace)
    main_window.saveAllData()

    on_disk = main_window.series.loadSection(snum)
    assert _count(on_disk, name) == before
    assert len(_matching(on_disk, name, points)) == 1


def test_a_reload_in_the_middle_of_a_cut_keeps_the_trace(main_window, qapp):
    """A reload rereads the section from its file. The cut must not stay open
    across it, or finishing it later would add a second copy beside the one
    the reload read back."""
    field = main_window.field
    trace = _pick_trace(field, True)
    name, points = trace.name, list(trace.points)
    before = _count(field.section, name)
    main_window.saveAllData()

    _pickup(main_window, qapp, trace)
    field.reload()
    qapp.processEvents()

    assert not field.is_scissoring
    assert not field.is_line_tracing
    assert _count(field.section, name) == before
    assert len(_matching(field.section, name, points)) == 1


def test_propagating_in_the_middle_of_a_cut_keeps_the_trace(
    main_window, qapp, monkeypatch
):
    """Propagate writes the field's section itself, then reloads it from the
    file, so what the field holds afterwards is what was written."""
    from PyReconstruct.modules.gui.main import field_widget_4_data

    # the fixture has align-locked sections; go ahead past that prompt, so
    # the propagation and its reload both run
    monkeypatch.setattr(field_widget_4_data, "notifyConfirm", lambda *a, **k: True)
    field = main_window.field
    trace = _pick_trace(field, True)
    name, points = trace.name, list(trace.points)
    snum = field.section.n
    before = _count(field.section, name)

    _pickup(main_window, qapp, trace)
    field.propagateTo(True, log_event=False)
    qapp.processEvents()

    assert not field.is_scissoring
    assert _count(field.section, name) == before
    assert len(_matching(field.section, name, points)) == 1
    on_disk = main_window.series.loadSection(snum)
    assert len(_matching(on_disk, name, points)) == 1
