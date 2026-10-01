"""A new action ends every redo, the way it does in any editor.

Two stacks carry redo: the series stack (`SeriesStates.redos`) and each
section's own (`SectionStates.redo_states`). `SectionStates.addState` has
always cleared its section's stack, but nothing else cleared anything:

* `SeriesStates.addState` left both kinds of redo in place. Add an object to
  group G, undo, add it to group H, redo: the series redo restored its whole
  snapshot and the object ended up in {G} with H gone.
* `checkOverwrite`, run after every section action, dropped only the series
  redos that touched that section, so a series-only redo (groups, attributes,
  z-traces) survived every later edit too.
* A section redo that moved a z-trace point survived a series action that
  deleted or renamed that z-trace, and redoing it raised KeyError.

Dropping a series redo from a section action also drops its per-section parts
on the other sections it touched, so none of them is left behind as a loose
section redo.
"""

import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates

OBJECT = "d03"


@pytest.fixture
def states(real_series):
    """Series states on the fixture series, with the progress dialog stubbed."""
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    real_series.setProgressReporter(NullProgressReporter)
    yield SeriesStates(real_series)
    real_series.setProgressReporter(None)


def add_to_group(series_states, series, group):
    """A series action: one undo state, then the edit."""
    series_states.addState()
    series.object_groups.add(group, OBJECT)


def groups(series):
    return set(series.object_groups.getObjectGroups(OBJECT))


def test_a_new_series_action_clears_the_series_redo(states, real_series):
    add_to_group(states, real_series, "G")
    states.undoState()
    assert groups(real_series) == set()
    assert len(states.redos) == 1

    add_to_group(states, real_series, "H")

    assert states.redos == []
    assert states.canUndo(redo=True)[0] is False
    states.undoState(redo=True)
    assert groups(real_series) == {"H"}


def test_a_new_section_action_clears_a_series_only_redo(states, real_series):
    """The redo touched no section, so the old per-section check kept it."""
    add_to_group(states, real_series, "G")
    states.undoState()
    assert len(states.redos) == 1

    snum = real_series.current_section
    section = real_series.loadSection(snum)
    section.modified_contours.add(OBJECT)
    states[section].addState(section, real_series)
    states.checkOverwrite(snum)

    assert states.redos == []
    assert groups(real_series) == set()


def test_a_new_series_action_clears_section_redos(states, real_series):
    """A section redo naming a deleted z-trace used to raise KeyError."""
    snum = real_series.current_section
    real_series.createZtrace(OBJECT, True)
    zname = next(iter(real_series.ztraces))
    section = real_series.loadSection(snum)
    section_states = states[section]

    # move the z-trace's point on this section, then undo the move
    ztrace = real_series.ztraces[zname]
    index = [p[2] for p in ztrace.points].index(snum)
    x, y, _ = ztrace.points[index]
    ztrace.points[index] = (x + 1, y, snum)
    real_series.modified_ztraces = {zname}
    section_states.addState(section, real_series)
    states.undoSection(section)
    assert len(section_states.redo_states) == 1

    # delete the z-trace as a series action
    states.addState()
    real_series.deleteZtraces([zname])

    assert section_states.redo_states == []
    assert states.canUndo(redo=True) == (False, False, False)
    states.undoSection(section, redo=True)  # nothing to redo, and no KeyError
    assert zname not in real_series.ztraces


def test_dropped_series_redo_takes_its_section_parts(states, real_series):
    """No part of a dropped series redo is left to be redone on its own."""
    first, second = sorted(real_series.sections)[:2]
    real_series.current_section = first

    # a series action with a per-section part on the first section
    states.addState()
    section = real_series.loadSection(first)
    section.modified_contours.add(OBJECT)
    states[section].addState(section, real_series)
    states.addSectionUndo(first)
    section.save()
    states.undoState()
    assert len(states.redos) == 1
    assert len(states[first].redo_states) == 1

    # a new action on the second section
    real_series.current_section = second
    other = real_series.loadSection(second)
    other.modified_contours.add(OBJECT)
    states[other].addState(other, real_series)
    states.checkOverwrite(second)

    assert states.redos == []
    assert states[first].redo_states == []


@pytest.mark.gui
def test_redo_after_a_new_group_action_through_the_window(
    main_window, monkeypatch
):
    """The reported steps: group G, Ctrl+Z, group H, redo. H must survive."""
    from PyReconstruct.modules.gui.main import field_widget_3_object as fw3

    window, field, series = main_window, main_window.field, main_window.series
    answers = ["G", "H"]

    class ScriptedGroupDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return answers.pop(0), True

    monkeypatch.setattr(fw3, "ObjectGroupDialog", ScriptedGroupDialog)

    trace = field.section.tracesAsList()[0]
    name = trace.name
    field.section.selected_traces = [trace]
    field.addToGroup()
    assert set(series.object_groups.getObjectGroups(name)) == {"G"}

    window.undo()
    assert set(series.object_groups.getObjectGroups(name)) == set()

    field.section.selected_traces = [
        t for t in field.section.tracesAsList() if t.name == name
    ][:1]
    field.addToGroup()
    assert set(series.object_groups.getObjectGroups(name)) == {"H"}

    window.undo(redo=True)

    assert set(series.object_groups.getObjectGroups(name)) == {"H"}


def test_cancelled_curation_dialog_keeps_redo(qapp, states, real_series):
    """Cancelling the `Assign to` dialog on the CR box is not an action, so
    both the series redo and the section redo survive it."""
    from unittest import mock

    from PySide6.QtCore import Qt

    from PyReconstruct.modules.gui.table.object import ObjectTableWidget

    snum = real_series.current_section
    section = real_series.loadSection(snum)

    # a series step, then a section step, both undone
    add_to_group(states, real_series, "G")
    section.modified_contours.add(OBJECT)
    states[section].addState(section, real_series)
    states.checkOverwrite(snum)
    states.undoSection(section)
    states.undoState()
    assert len(states.redos) == 1
    assert len(states[section].redo_states) == 1

    table = ObjectTableWidget.__new__(ObjectTableWidget)
    table.horizontal_headers = ["CR"]
    table.model = mock.Mock()
    table.model.nameAt.return_value = OBJECT
    table.series = real_series
    table.series_states = states
    table.manager = mock.Mock()
    table.mainwindow = mock.Mock()

    with mock.patch(
        "PyReconstruct.modules.gui.table.object.QInputDialog.getText",
        return_value=("", False),
    ):
        accepted = table.onCheckStateChanged(
            0, 0, Qt.CheckState.PartiallyChecked
        )

    assert accepted is False
    assert len(states.redos) == 1
    assert len(states[section].redo_states) == 1
