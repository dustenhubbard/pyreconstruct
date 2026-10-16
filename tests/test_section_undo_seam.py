"""The section-edit undo path through its one seam, with no Qt.

`SeriesStates.commitSection` records a section edit and `undoSection` takes a
section undo or redo. Each does all the data work (the undo state, the series
data, emptied groups, alignment pins, the Section and Series tracking) and
returns a `SectionStep` naming what changed, so the field only refreshes its
lists and menus from it. These tests drive both on a real Series and Section,
with no application, widget or table.
"""

import ast
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.func.state_manager import (
    SectionStep,
    SeriesStates,
)
from PyReconstruct.modules.backend.table.manager import TableManager
from PyReconstruct.modules.datatypes import Flag, Trace, Transform, Ztrace

SNUM = 0  # section 0 of the fixture has no traces and no flags
NAME = "seam_obj"
POINTS = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]
MORE = [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)]
ZNAME = "seam_z"


@pytest.fixture
def bench(real_series):
    """The fixture series on section 0, with its states initialized."""
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    real_series.setProgressReporter(NullProgressReporter)
    real_series.current_section = SNUM
    real_series.ztraces[ZNAME] = Ztrace(ZNAME, (255, 0, 255), [(0.0, 0.0, SNUM)])
    section = real_series.loadSection(SNUM)
    assert section.contours == {}, "fixture section 0 changed"
    states = SeriesStates(real_series)
    states[section]  # initialize, as the field does when it opens a section
    yield real_series, section, states
    real_series.setProgressReporter(None)


def draw(section, name=NAME, points=POINTS):
    trace = Trace(name, (0, 255, 0), True)
    trace.points = list(points)
    section.addTrace(trace, log_event=False)
    return trace


def tracked(series, section):
    return (
        section.isModified(),
        set(section.getAllModifiedNames()),
        set(series.modified_ztraces),
    )


CLEAR = (False, set(), set())


def test_a_commit_does_the_data_work_and_names_what_changed(bench):
    series, section, states = bench
    draw(section)

    step = states.commitSection(section)

    assert isinstance(step, SectionStep)
    assert step.objects == {NAME}
    assert step.ztraces == set()
    assert step.groups_changed is False
    assert step.tform_moved is False
    assert SNUM in series.data["objects"][NAME].traces
    assert len(states[SNUM].undo_states) == 1
    assert tracked(series, section) == CLEAR


def test_undo_and_redo_do_the_data_work_and_name_what_changed(bench):
    series, section, states = bench
    draw(section)
    states.commitSection(section)

    step = states.undoSection(section)

    assert step.objects == {NAME}
    assert NAME not in series.data["objects"]
    assert len(section.contours.get(NAME, [])) == 0
    assert tracked(series, section) == CLEAR

    step = states.undoSection(section, redo=True)

    assert step.objects == {NAME}
    assert SNUM in series.data["objects"][NAME].traces
    assert tracked(series, section) == CLEAR


def test_a_commit_names_the_ztraces_it_changed(bench):
    series, section, states = bench
    series.modified_ztraces.add(ZNAME)

    step = states.commitSection(section)

    assert step.ztraces == {ZNAME}
    assert series.modified_ztraces == set()


def test_a_merged_commit_is_taken_back_with_the_step_before_it(bench):
    """A draw and the merge that follows it are one undo step (autoMerge)."""
    series, section, states = bench
    draw(section)
    states.commitSection(section)
    draw(section, points=MORE)

    states.commitSection(section, merge=True)

    assert len(states[SNUM].undo_states) == 1
    states.undoSection(section)
    assert len(section.contours.get(NAME, [])) == 0
    assert NAME not in series.data["objects"]


def test_an_unmerged_commit_is_a_step_of_its_own(bench):
    series, section, states = bench
    draw(section)
    states.commitSection(section)
    draw(section, points=MORE)

    states.commitSection(section)

    assert len(states[SNUM].undo_states) == 2
    states.undoSection(section)
    assert len(section.contours[NAME]) == 1


def test_emptying_a_group_is_reported_and_undone(bench):
    series, section, states = bench
    trace = draw(section)
    states.commitSection(section)
    series.object_groups.add(group="seam_group", obj=NAME)
    series.groups_visibility["seam_group"] = False

    section.removeTrace(trace, log_event=False)
    step = states.commitSection(section)

    assert step.groups_changed is True
    assert "seam_group" not in series.object_groups.getGroupList()
    assert "seam_group" not in series.groups_visibility

    step = states.undoSection(section)

    assert step.groups_changed is True
    assert series.object_groups.getObjectGroups(NAME) == {"seam_group"}
    assert series.groups_visibility["seam_group"] is False


def test_a_moved_transform_is_reported(bench):
    series, section, states = bench
    tform = section.tform.getList()
    tform[2] += 3.0
    section.tform = Transform(tform)

    step = states.commitSection(section)
    assert step.tform_moved is True

    step = states.undoSection(section)
    assert step.tform_moved is True
    assert tracked(series, section) == CLEAR


def test_undo_puts_back_the_pin_of_an_object_it_recreates(bench):
    """updateSection gives a new object the current alignment; the seam puts
    back the one the object had before the edit deleted it."""
    series, section, states = bench
    trace = draw(section)
    states.commitSection(section)
    series.setAttr(NAME, "alignment", "pinned")

    section.removeTrace(trace, log_event=False)
    states.commitSection(section)
    assert NAME not in series.data["objects"]

    step = states.undoSection(section)

    assert series.getAttr(NAME, "alignment") == "pinned"
    assert NAME in step.objects
    assert states[SNUM].restored_alignments == {}


def test_nothing_to_undo_still_brings_the_data_up_to_date(bench):
    series, section, states = bench
    draw(section)  # an edit in progress, never committed

    step = states.undoSection(section)

    assert step.objects == {NAME}
    assert SNUM in series.data["objects"][NAME].traces
    assert tracked(series, section) == CLEAR


def test_section_is_modified_covers_traces_transforms_and_flags(bench):
    series, section, states = bench
    assert section.isModified() is False

    draw(section)
    assert section.isModified() is True
    section.clearTracking()
    assert section.isModified() is False

    tform = section.tform.getList()
    tform[2] += 1.0
    section.tform = Transform(tform)
    assert section.isModified() is True
    section.clearTracking()

    section.addFlag(Flag("f", 1, 1, SNUM, (255, 0, 0)), log_event=False)
    assert section.isModified() is True
    section.clearTracking()
    assert section.isModified() is False


class _Tables:
    """TableManager's update methods on the attributes they read, so they
    run without a window."""

    updateObjects = TableManager.updateObjects
    updateSections = TableManager.updateSections
    updateZtraces = TableManager.updateZtraces
    updateFlags = TableManager.updateFlags
    updateAll = TableManager.updateAll

    def __init__(self, series, section):
        self.series = series
        self.section = section
        self.tables = {k: [] for k in ("object", "trace", "ztrace", "flag", "section")}
        self.mainwindow = None

    def _markViewerStale(self, *args, **kwargs):
        pass


def test_the_table_manager_reads_tracking_and_never_clears_it(bench):
    series, section, states = bench
    draw(section)
    series.modified_ztraces.add(ZNAME)
    tables = _Tables(series, section)

    tables.updateObjects()
    tables.updateZtraces()
    tables.updateAll()

    assert set(section.getAllModifiedNames()) == {NAME}
    assert series.modified_ztraces == {ZNAME}


def test_the_state_manager_imports_no_qt_and_no_tables():
    import PyReconstruct.modules.backend.func.state_manager as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any(n.startswith("PySide6") for n in imported)
    assert not any(".table" in n or ".gui" in n for n in imported)
