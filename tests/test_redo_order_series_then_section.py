"""Redo replays a series step and a section step in the reverse of the undo order.

When a series undo and a section undo are both available and not linked,
`favor3D` picks the newer one by comparing `SeriesState.time` with the time on
the section's top state. `SectionStates` restamps a state each time it moves
between its undo and redo stacks. `SeriesStates.undoState` did not, so a
series state kept the time it was first made.

Undo came out right, but redo did not. Add an object to a group (series step
S), move a z-trace point on the current section (section step B), undo twice,
redo twice: B was redone first because its stamp came from the first undo,
which is newer than S's birth time. S's snapshot of the series z-traces then
put the point back where it started, and B's move was lost.

The stamps used to be the wall clock in tenths of a second, so two undos inside
one tenth (a held Cmd+Z) or a clock set back gave the same wrong order. The
tests run with the clock held still or running backward, and no sleeps.
"""

import shutil
import time

import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates

OBJECT = "d03"


@pytest.fixture(autouse=True, params=["still", "backward"])
def clock(request, monkeypatch):
    """Hold `time.time` still, or make every call return an earlier time."""
    now = [1_000_000.0]

    def fake_time():
        if request.param == "backward":
            now[0] -= 1.0
        return now[0]

    monkeypatch.setattr(time, "time", fake_time)


def step(series_states, section, redo=False):
    """What `MainWindow.undo` does when the two undos are not linked."""
    can_3D, can_2D, linked = series_states.canUndo(redo=redo)
    assert not linked
    if can_3D and (not can_2D or series_states.favor3D(redo=redo)):
        series_states.undoState(redo=redo)
    else:
        series_states.undoSection(section, redo=redo)


@pytest.fixture
def states(real_series):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    real_series.setProgressReporter(NullProgressReporter)
    yield SeriesStates(real_series)
    real_series.setProgressReporter(None)


def test_redo_replays_the_series_step_before_the_section_step(
    states, real_series
):
    series = real_series
    snum = series.current_section
    zname = "Z"
    index = [p[2] for p in series.ztraces[zname].points].index(snum)
    start = tuple(series.ztraces[zname].points[index])
    section = series.loadSection(snum)
    section_states = states[section]

    # S: a series step with no part on any section
    states.addState()
    series.object_groups.add("G", OBJECT)

    # B: move the z-trace point on this section
    x, y, _ = start
    moved = (x + 4.0, y + 4.0, snum)
    series.ztraces[zname].points[index] = moved
    series.modified_ztraces = {zname}
    section_states.addState(section, series)
    states.checkOverwrite(snum)

    for _ in range(2):
        step(states, section)
    assert tuple(series.ztraces[zname].points[index]) == start
    assert "G" not in series.object_groups.getObjectGroups(OBJECT)

    assert states.favor3D(redo=True) is True, "the first redo must be S"
    step(states, section, redo=True)
    step(states, section, redo=True)

    assert "G" in series.object_groups.getObjectGroups(OBJECT)
    assert tuple(series.ztraces[zname].points[index]) == moved, (
        "the z-trace move was lost after two redos"
    )


def test_undo_after_the_redos_takes_the_section_step_first(states, real_series):
    """Once both are redone, B is again the newer one and Ctrl+Z takes it."""
    series = real_series
    snum = series.current_section
    zname = "Z"
    index = [p[2] for p in series.ztraces[zname].points].index(snum)
    section = series.loadSection(snum)
    section_states = states[section]

    start = tuple(series.ztraces[zname].points[index])

    states.addState()
    series.object_groups.add("G", OBJECT)
    x, y, _ = start
    moved = (x + 4.0, y + 4.0, snum)
    series.ztraces[zname].points[index] = moved
    series.modified_ztraces = {zname}
    section_states.addState(section, series)
    states.checkOverwrite(snum)

    for redo in (False, False, True, True):
        step(states, section, redo=redo)
    assert tuple(series.ztraces[zname].points[index]) == moved
    assert "G" in series.object_groups.getObjectGroups(OBJECT)

    assert states.favor3D() is False
    step(states, section)
    assert tuple(series.ztraces[zname].points[index]) == start, (
        "the first undo after the redos must take back the z-trace move"
    )
    assert "G" in series.object_groups.getObjectGroups(OBJECT)
    step(states, section)
    assert "G" not in series.object_groups.getObjectGroups(OBJECT)


@pytest.fixture
def series_jser(tmp_path):
    """The fixture series with a z-trace that has a point on every section."""
    from PyReconstruct.modules.datatypes import Series, Ztrace
    from conftest import SERIES_FIXTURE

    destination = tmp_path / "series.jser"
    shutil.copy(SERIES_FIXTURE, destination)
    series = Series.openJser(str(destination))
    series.ztraces["Z"] = Ztrace(
        "Z", (255, 0, 0), [(1.0, 1.0, n) for n in sorted(series.sections)]
    )
    series.save()
    series.saveJser()
    series.close()
    return destination


@pytest.mark.gui
def test_redo_order_through_the_window(main_window, monkeypatch):
    """The reported steps, through the object menu and `MainWindow.undo`."""
    from PyReconstruct.modules.gui.main import field_widget_3_object as fw3

    window, field, series = main_window, main_window.field, main_window.series

    class ScriptedGroupDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return "G", True

    monkeypatch.setattr(fw3, "ObjectGroupDialog", ScriptedGroupDialog)

    snum = field.section.n
    index = [p[2] for p in series.ztraces["Z"].points].index(snum)
    trace = field.section.tracesAsList()[0]
    name = trace.name

    field.section.selected_traces = [trace]
    field.addToGroup()
    field.section.selected_traces = []

    field.section.selected_ztraces = [(series.ztraces["Z"], index)]
    field.translate(4.0, 4.0)
    field.section.selected_ztraces = []
    moved = tuple(series.ztraces["Z"].points[index])
    assert moved != (1.0, 1.0, snum)

    for redo in (False, False, True, True):
        window.undo(redo=redo)

    assert "G" in series.object_groups.getObjectGroups(name)
    assert tuple(series.ztraces["Z"].points[index]) == moved
