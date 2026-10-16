"""The section-edit undo path through its one seam, with no Qt.

`SeriesStates.commitSection` records a section edit and `undoSection` takes a
section undo or redo. Each does all the data work (the undo state, the series
data, emptied groups, alignment pins, the Section and Series tracking) and
returns a `SectionStep` naming what changed, so the field only refreshes its
lists and menus from it. These tests drive both on a real Series and Section,
with no application, widget or table.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.func.state_manager import (
    SectionStep,
    SeriesStates,
)
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


_NO_QT = """
import os, shutil, sys, tempfile
class Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6."):
            raise ImportError("PySide6 blocked")
sys.meta_path.insert(0, Block())
from PyReconstruct.modules.backend.settings_store import (
    DictSettingsStore, set_default_settings_store,
)
set_default_settings_store(DictSettingsStore())
sys.path.insert(0, sys.argv[1])
import test_section_undo_seam as seam
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series

copy = os.path.join(tempfile.mkdtemp(), "series.jser")
shutil.copy(sys.argv[2], copy)
series = Series.openJser(copy, progress=NullProgressReporter)
series.setProgressReporter(NullProgressReporter)
series.current_section = seam.SNUM
section = series.loadSection(seam.SNUM)
states = seam.SeriesStates(series)
states[section]
seam.draw(section)
assert states.commitSection(section).objects == {seam.NAME}
assert states.undoSection(section).objects == {seam.NAME}
assert seam.NAME not in series.data["objects"]
series.close()
assert not any(m.split(".")[0] == "PySide6" for m in sys.modules)
"""


def test_the_seam_tests_import_and_run_with_qt_blocked():
    """In a process where any PySide6 import fails, with no Qt platform set,
    this module imports and a commit and undo run on a real Series."""
    from conftest import SERIES_FIXTURE

    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run(
        [sys.executable, "-c", _NO_QT, str(Path(__file__).parent), str(SERIES_FIXTURE)],
        env=env, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
