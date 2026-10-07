"""Saving, closing or reloading in the middle of a scissors cut keeps the trace.

The scissors pickup takes the clicked trace out of the section, logs nothing and
saves no undo state; until the cut ends the trace exists only as the line being
edited. Cmd+S in that window wrote the section without it, marked the series
saved, and Close then deleted the working folder. Reopening the file found no
trace, and undo had nothing to bring back.

Anything that writes or rereads the section now backs the open cut out first,
the same as Backspace does, so the trace goes back exactly as it was. A jump to
another section finishes the cut first instead, on the section it was open on,
the way paging always has; the 3D scene's double-click used to skip that.

Undo saves before it undoes, so it settles the cut before that save: it
finishes the cut and takes that back, rather than letting the save back it out
and then taking the edit made before it. Redo backs the cut out, since
finishing it would end the redo.

Driven through the live `MainWindow`: a real left click with the Scissors tool,
then the real Save action, a real close and a fresh `Series.openJser`.
"""
import os
import shutil

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.trace import Trace
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


def _neighbor(series, snum):
    numbers = sorted(series.sections)
    i = numbers.index(snum)
    return numbers[i + 1] if i + 1 < len(numbers) else numbers[i - 1]


def _bounds(trace):
    xs = [x for x, _ in trace.points]
    ys = [y for _, y in trace.points]
    return min(xs), min(ys), max(xs), max(ys)


@pytest.mark.parametrize("jump", ["3d_scene", "paging"])
def test_a_jump_to_another_section_finishes_the_cut_where_it_was_open(
    main_window, qapp, jump
):
    """A section change with a cut open finishes the cut first, on the section
    it was open on, the way paging has always done through endPendingEvents.

    The 3D scene's double-click (moveTo) reached the field's changeSection
    without that step, so the cut stayed open across the jump. Backing it out
    at the next save then put the trace into the section on screen, and the
    section it came from was written without it. Paging is the control.
    """
    field = main_window.field
    trace = _pick_trace(field, True)
    name = trace.name
    a = field.section.n
    before_a = _count(field.section, name)
    undo_before = len(field.series_states[a].undo_states)
    b = _neighbor(field.series, a)
    before_b = _count(field.series.loadSection(b), name)

    _pickup(main_window, qapp, trace)

    if jump == "3d_scene":
        # the double-click in custom_plotter.leftButtonClickEvent, landing on
        # a point of the object in field coordinates
        x, y = trace.points[0]
        field.moveTo(b, x, y)
    else:
        main_window.incrementSection(down=(b < a))
    qapp.processEvents()

    assert field.section.n == b
    assert not field.is_scissoring
    assert not field.is_line_tracing
    assert field.mouse_mode == SCISSORS

    # the cut finished on its own section (now the flickered-away one), with
    # the undo state a finished cut gets, and the new section was left alone
    assert _count(field.b_section, name) == before_a
    assert _count(field.section, name) == before_b
    assert len(field.series_states[a].undo_states) == undo_before + 1

    main_window.saveAllData()
    assert _count(main_window.series.loadSection(a), name) == before_a
    assert _count(main_window.series.loadSection(b), name) == before_b


def test_a_jump_within_the_section_finishes_the_cut_before_the_view_moves(
    main_window, qapp
):
    """A 3D double-click on the section already shown only moves the view, but
    the cut's points are in pixels of the view it was open in: finished after
    the move, it would land wherever those pixels now point."""
    field = main_window.field
    trace = _pick_trace(field, True)
    name = trace.name
    a = field.section.n
    others = [t for t in field.section.contours[name].getTraces() if t is not trace]
    x0, y0, x1, y1 = _bounds(trace)
    # a field unit per pixel at the current zoom, for the tolerance below
    per_pixel = field.section.mag / field.section_layer.scaling

    _pickup(main_window, qapp, trace)
    field.moveTo(a, x1 + 5.0, y1 + 5.0)
    qapp.processEvents()

    assert field.section.n == a
    assert not field.is_scissoring
    assert not field.is_line_tracing
    (kept,) = [
        t for t in field.section.contours[name].getTraces()
        if not any(t is o for o in others)
    ]
    for got, want in zip(_bounds(kept), (x0, y0, x1, y1)):
        assert abs(got - want) <= 2 * per_pixel


def _draw_closed(main_window, qapp, name="scissors_undo_a", slot=0):
    """Draw a small closed trace with the Closed Trace tool, a click per
    corner and a right-click to finish, away from the fixture's traces. It
    gets an object of its own, so counting the picked-up trace's object
    does not count it. Each slot is a spot of its own along the top."""
    field = main_window.field
    field.series.setOption("trace_mode", "poly")
    main_window.mouse_palette.activateModeButton("Closed Trace")
    qapp.processEvents()
    field.setTracingTrace(Trace(name, (255, 0, 0), True))
    before = list(field.section.tracesAsList())
    x0, y0 = field.width() // 20 + 50 * slot, field.height() // 20
    corners = [(x0, y0), (x0 + 30, y0), (x0 + 30, y0 + 30), (x0, y0 + 30)]
    for x, y in corners:
        QTest.mouseClick(field, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.mouseClick(field, Qt.RightButton, Qt.NoModifier, QPoint(*corners[-1]))
    qapp.processEvents()
    (drawn,) = [
        t for t in field.section.tracesAsList()
        if not any(t is b for b in before)
    ]
    return drawn.name, list(drawn.points)


@pytest.mark.parametrize("closed", [True, False])
def test_undo_in_the_middle_of_a_cut_takes_back_the_cut_only(
    main_window, qapp, closed
):
    """Undo finishes the cut and takes it back, and Redo brings the cut back.
    Undo saves first; when that save backed the cut out, it left no state
    for the cut, and this Undo took the trace drawn before it instead."""
    field = main_window.field
    trace = _pick_trace(field, closed)
    name, points = trace.name, list(trace.points)
    before = _count(field.section, name)
    a_name, a_points = _draw_closed(main_window, qapp)
    states = field.series_states[field.section.n]
    undo_before = len(states.undo_states)

    _pickup(main_window, qapp, trace)
    main_window.undo_act.trigger()  # Cmd+Z
    qapp.processEvents()

    assert not field.is_scissoring
    assert not field.is_line_tracing
    assert field.mouse_mode == SCISSORS
    assert len(_matching(field.section, a_name, a_points)) == 1, (
        "Undo during the cut took the trace drawn before it"
    )
    assert _count(field.section, name) == before
    assert len(_matching(field.section, name, points)) == 1
    assert len(states.undo_states) == undo_before

    assert main_window.redo_act.isEnabled()
    main_window.redo_act.trigger()  # Cmd+Y
    qapp.processEvents()

    assert len(_matching(field.section, a_name, a_points)) == 1
    assert _count(field.section, name) == before
    assert len(states.undo_states) == undo_before + 1


def test_undo_in_the_middle_of_a_cut_leaves_a_series_edit_alone(
    main_window, qapp
):
    """With a series-wide edit as the newest undo, Undo during a cut takes
    back the cut and leaves the series edit for the next Undo."""
    field = main_window.field
    trace = _pick_trace(field, True)
    name, points = trace.name, list(trace.points)
    before = _count(field.section, name)
    other = next(
        n for n in field.section.contours
        if n != name and field.section.contours[n].getTraces()
        and not field.series.getAttr(n, "locked")
    )
    field.section.selected_traces = field.section.contours[other].getTraces()[:1]
    field.lockObjects()
    assert field.series.getAttr(other, "locked")

    _pickup(main_window, qapp, trace)
    main_window.undo_act.trigger()
    qapp.processEvents()

    assert not field.is_scissoring
    assert _count(field.section, name) == before
    assert len(_matching(field.section, name, points)) == 1
    assert field.series.getAttr(other, "locked"), (
        "Undo during the cut also undid the series edit before it"
    )

    main_window.undo_act.trigger()
    qapp.processEvents()
    assert not field.series.getAttr(other, "locked")
    assert len(_matching(field.section, name, points)) == 1


def test_redo_in_the_middle_of_a_cut_backs_the_cut_out_and_redoes(
    main_window, qapp
):
    """Redo backs the cut out, then redoes. Finishing the cut instead would be
    a new edit, and a new edit ends every redo, the one asked for included."""
    field = main_window.field
    trace = _pick_trace(field, True)
    name, points = trace.name, list(trace.points)
    before = _count(field.section, name)
    a_name, a_points = _draw_closed(main_window, qapp)
    main_window.undo_act.trigger()
    qapp.processEvents()
    assert not _matching(field.section, a_name, a_points)

    _pickup(main_window, qapp, trace)
    assert main_window.redo_act.isEnabled()
    main_window.redo_act.trigger()
    qapp.processEvents()

    assert not field.is_scissoring
    assert not field.is_line_tracing
    assert len(_matching(field.section, a_name, a_points)) == 1, (
        "Redo during the cut lost the redo"
    )
    assert _count(field.section, name) == before
    assert len(_matching(field.section, name, points)) == 1


def _history(field):
    states = field.series_states[field.section.n]
    return (
        len(states.undo_states), len(states.redo_states),
        len(field.series_states.undos), len(field.series_states.redos),
    )


@pytest.mark.parametrize("redo", [False, True])
def test_undo_or_redo_with_traces_hidden_leaves_the_history_alone(
    main_window, qapp, redo
):
    """With the trace layer hidden, a section Undo or Redo does nothing, and
    the cut cannot be finished either: newTrace refuses the trace. Finishing
    it anyway put the trace back with a state of its own, which ended the
    redo, and left an Undo that changes nothing once traces are shown. The
    cut is backed out instead, with no state, and the history stays as it
    was."""
    field = main_window.field
    trace = _pick_trace(field, True)
    name, points = trace.name, list(trace.points)
    before = _count(field.section, name)
    a_name, a_points = _draw_closed(main_window, qapp, "scissors_undo_a", 0)
    c_name, c_points = _draw_closed(main_window, qapp, "scissors_undo_c", 1)
    main_window.undo_act.trigger()
    qapp.processEvents()
    assert not _matching(field.section, c_name, c_points)
    history = _history(field)

    _pickup(main_window, qapp, trace)
    main_window.hideall_act.trigger()  # Toggle hide all
    qapp.processEvents()
    assert field.hide_trace_layer
    (main_window.redo_act if redo else main_window.undo_act).trigger()
    qapp.processEvents()

    assert not field.is_scissoring
    assert not field.is_line_tracing
    assert _count(field.section, name) == before
    assert len(_matching(field.section, name, points)) == 1
    assert len(_matching(field.section, a_name, a_points)) == 1
    assert not _matching(field.section, c_name, c_points)
    assert _history(field) == history, "the hidden Undo or Redo changed the history"

    main_window.hideall_act.trigger()
    qapp.processEvents()
    assert not field.hide_trace_layer
    main_window.redo_act.trigger()
    qapp.processEvents()
    assert len(_matching(field.section, c_name, c_points)) == 1, (
        "C could not be redone"
    )
    main_window.undo_act.trigger()
    main_window.undo_act.trigger()
    qapp.processEvents()
    assert not _matching(field.section, a_name, a_points), (
        "an Undo that changes nothing was left in the history"
    )
    assert len(_matching(field.section, name, points)) == 1


@pytest.mark.parametrize("edit", ["alignment", "paste"])
def test_an_edit_in_the_middle_of_a_cut_records_the_trace(
    main_window, qapp, edit
):
    """An edit made while a cut is open records an undo state, and that state
    held the section without the picked-up trace. Save put the trace back,
    then Undo and Redo replayed the state and took it out again, and the next
    save wrote the section without it. A state recorded during a cut now backs
    the cut out first, so it holds the trace.

    `Left` moves the alignment of an unlocked section. `Paste` adds a trace;
    its list refresh happened to clear the record of the pickup, so its state
    left the trace's object out, but it too was recorded with the cut open."""
    main_window.show()
    main_window.activateWindow()
    field = main_window.field
    field.section.align_locked = False
    trace = _pick_trace(field, True)
    name, points = trace.name, list(trace.points)
    snum = field.section.n
    before = _count(field.section, name)
    tform_before = field.section.tform.getList()
    if edit == "paste":
        other = next(
            t for t in field.section.tracesAsList() if t.name != name
        )
        field.section.selected_traces = [other]
        field.copy()
        field.deselectAllTraces()
    qapp.processEvents()

    _pickup(main_window, qapp, trace)
    if edit == "alignment":
        field.setFocus()
        qapp.processEvents()
        QTest.keyClick(field, Qt.Key_Left)
        assert field.section.tform.getList() != tform_before
    else:
        main_window.paste_act.trigger()
    qapp.processEvents()
    assert not field.is_scissoring
    assert not field.is_line_tracing
    assert len(_matching(field.section, name, points)) == 1

    main_window.save_act.trigger()
    qapp.processEvents()
    assert not field.is_scissoring
    assert len(_matching(field.section, name, points)) == 1

    main_window.undo_act.trigger()
    qapp.processEvents()
    assert len(_matching(field.section, name, points)) == 1
    main_window.redo_act.trigger()
    qapp.processEvents()
    if edit == "alignment":
        assert field.section.tform.getList() != tform_before
    assert _count(field.section, name) == before
    assert len(_matching(field.section, name, points)) == 1, (
        "Redo took the picked-up trace out again"
    )

    main_window.saveAllData()
    assert len(_matching(main_window.series.loadSection(snum), name, points)) == 1
