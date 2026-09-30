"""What `SectionStates.undoState` and `redoState` do, pinned end to end.

These tests describe the two restore paths as they behave today, so the paths
can share code without anything a user sees changing. Each step checks the
whole result, not one field of it: the section's traces, the series' z-traces,
the section's transforms and flags, the names marked modified, the log lines
written (and their order), the undo and redo stacks, and the columnar store
resync that closes every restore.

Two branches of undo are covered separately because they restore traces in
different ways. With one undo state left, undo replaces the section's contours
wholesale with the baseline. With several, it walks back through the states
for each name the current state touched, and a name no earlier state holds is
left behind as an empty contour.
"""

import pytest

from PyReconstruct.modules.backend.func.state_manager import SectionStates
from PyReconstruct.modules.datatypes import Flag, Trace, Transform, Ztrace

SNUM = 0          # section 0 of the fixture has no traces and no flags
OTHER = 1         # a second section the z-trace crosses

BASE_TFORM = [1.0, 0.0, 5.5738052399999996, 0.0, 1.0, 18.29052076]

A1 = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]
A2 = [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)]
B1 = [(3.0, 3.0), (4.0, 3.0), (4.0, 4.0)]
Z_START = [(0.0, 0.0, SNUM), (0.5, 0.5, OTHER)]


class Bench:
    """A section, its states, and a record of every log line and resync."""

    def __init__(self, series):
        self.series = series
        series.ztraces["z1"] = Ztrace("z1", (255, 0, 255), list(Z_START))
        self.section = series.loadSection(SNUM)
        assert self.section.contours == {}, "fixture section 0 changed"
        assert self.section.flags == [], "fixture section 0 changed"
        assert self.section.tforms["default"].getList() == BASE_TFORM
        self.states = SectionStates(self.section, series)
        self.calls = []

        real_add_log = series.addLog

        def add_log(obj_name, snum, event):
            self.calls.append((obj_name, snum, event))
            real_add_log(obj_name, snum, event)

        series.addLog = add_log

        real_resync = self.section.resyncColumnarStore

        def resync():
            self.calls.append("resync")
            real_resync()

        self.section.resyncColumnarStore = resync

    # -- an edit, recorded the way the field records one --------------------- #
    def edit(self, add=(), ztrace_point=None, tform=None, flag=None):
        section, series = self.section, self.series
        for name, points in add:
            trace = Trace(name, (0, 255, 0), True)
            trace.points = list(points)
            section.addTrace(trace, log_event=False)
        if ztrace_point is not None:
            self.setZtracePoint(SNUM, ztrace_point)
            series.modified_ztraces.add("z1")
        if tform is not None:
            section.tform = Transform(list(tform))
        if flag is not None:
            section.addFlag(Flag(flag, 1, 1, SNUM, (255, 0, 0)), log_event=False)
        self.states.addState(section, series)
        self.settle()

    def settle(self):
        """What the tables do after every edit, undo and redo."""
        self.section.clearTracking()
        self.series.modified_ztraces = set()
        self.calls = []

    def setZtracePoint(self, snum, xy):
        z = self.series.ztraces["z1"]
        z.points = [(xy[0], xy[1], snum) if p[2] == snum else p for p in z.points]

    # -- what a restore left behind ------------------------------------------ #
    def contours(self):
        return {
            name: [list(t.points) for t in contour.getTraces()]
            for name, contour in self.section.contours.items()
        }

    def ztrace(self):
        return list(self.series.ztraces["z1"].points)

    def tform(self):
        return self.section.tforms["default"].getList()

    def flags(self):
        return [f.name for f in self.section.flags]

    def stacks(self):
        return len(self.states.undo_states), len(self.states.redo_states)


def shifted(dx):
    t = list(BASE_TFORM)
    t[2] += dx
    return t


@pytest.fixture
def bench(real_series):
    return Bench(real_series)


# --------------------------------------------------------------------------- #
# one undo state: the wholesale branch                                         #
# --------------------------------------------------------------------------- #
def test_undo_with_one_state_restores_traces_ztraces_tforms_and_flags(bench):
    bench.edit(add=[("a", A1)], ztrace_point=(9.0, 9.0), tform=shifted(3.0),
               flag="f1")
    # another section moves its own z-trace point after the edit; undo on
    # this section must not take it back
    bench.setZtracePoint(OTHER, (7.0, 7.0))
    pushed = bench.states.current_state
    baseline = bench.states.undo_states[0]
    assert bench.stacks() == (1, 0)

    result = bench.states.undoState(bench.section, bench.series)

    assert result is None
    assert bench.contours() == {}, "the whole dict is replaced by the baseline"
    assert bench.ztrace() == [(0.0, 0.0, SNUM), (7.0, 7.0, OTHER)]
    assert bench.tform() == BASE_TFORM
    assert bench.flags() == []
    assert bench.section.modified_contours == {"a"}
    assert bench.series.modified_ztraces == {"z1"}
    assert bench.calls == [
        ("a", SNUM, "Modify trace(s)"),
        ("z1", SNUM, "Modify ztrace"),
        (None, SNUM, "Modify transform"),
        (None, SNUM, "Modify flag(s)"),
        "resync",
    ]
    assert bench.stacks() == (0, 1)
    assert bench.states.redo_states[-1] is pushed
    assert bench.states.current_state is not baseline, "undo pops a copy"
    assert bench.states.current_state.contours_fp == baseline.contours_fp


def test_redo_after_one_undo_brings_everything_back(bench):
    bench.edit(add=[("a", A1)], ztrace_point=(9.0, 9.0), tform=shifted(3.0),
               flag="f1")
    bench.states.undoState(bench.section, bench.series)
    bench.settle()
    bench.setZtracePoint(OTHER, (7.0, 7.0))
    redo_state = bench.states.redo_states[-1]
    undone_to = bench.states.current_state

    result = bench.states.redoState(bench.section, bench.series)

    assert result is None
    assert bench.contours() == {"a": [A1]}
    assert bench.ztrace() == [(9.0, 9.0, SNUM), (7.0, 7.0, OTHER)]
    assert bench.tform() == shifted(3.0)
    assert bench.flags() == ["f1"]
    assert bench.section.modified_contours == {"a"}
    assert bench.series.modified_ztraces == {"z1"}
    assert bench.calls == [
        ("a", SNUM, "Modify trace(s)"),
        ("z1", SNUM, "Modify ztrace"),
        (None, SNUM, "Modify transform"),
        (None, SNUM, "Modify flag(s)"),
        "resync",
    ]
    assert bench.stacks() == (1, 0)
    assert bench.states.undo_states[-1] is undone_to
    assert bench.states.current_state is redo_state, "redo pops the state itself"


# --------------------------------------------------------------------------- #
# several undo states: the walk-back branch                                    #
# --------------------------------------------------------------------------- #
def _three_edits(bench):
    bench.edit(add=[("a", A1)])                                    # s1
    bench.edit(add=[("b", B1)], ztrace_point=(9.0, 9.0), flag="f1")  # s2
    bench.edit(add=[("a", A2)], tform=shifted(3.0))                # s3
    assert bench.stacks() == (3, 0)
    assert bench.contours() == {"a": [A1, A2], "b": [B1]}


def test_undo_with_several_states_takes_each_name_from_its_latest_state(bench):
    _three_edits(bench)

    bench.states.undoState(bench.section, bench.series)

    assert bench.contours() == {"a": [A1], "b": [B1]}, "a comes back from s1"
    assert bench.ztrace() == [(9.0, 9.0, SNUM), (0.5, 0.5, OTHER)]
    assert bench.tform() == BASE_TFORM
    assert bench.flags() == ["f1"]
    assert bench.section.modified_contours == {"a"}
    assert bench.series.modified_ztraces == set()
    assert bench.calls == [
        ("a", SNUM, "Modify trace(s)"),
        (None, SNUM, "Modify transform"),
        "resync",
    ]
    assert bench.stacks() == (2, 1)


def test_undo_leaves_a_name_no_earlier_state_holds_as_an_empty_contour(bench):
    _three_edits(bench)
    bench.states.undoState(bench.section, bench.series)
    bench.settle()

    bench.states.undoState(bench.section, bench.series)

    assert bench.contours() == {"a": [A1], "b": []}
    assert bench.ztrace() == Z_START, "z1 comes back from the baseline"
    assert bench.tform() == BASE_TFORM
    assert bench.flags() == []
    assert bench.section.modified_contours == {"b"}
    assert bench.series.modified_ztraces == {"z1"}
    assert bench.calls == [
        ("b", SNUM, "Modify trace(s)"),
        ("z1", SNUM, "Modify ztrace"),
        (None, SNUM, "Modify flag(s)"),
        "resync",
    ]
    assert bench.stacks() == (1, 2)


def test_redo_walks_forward_through_every_undone_state(bench):
    _three_edits(bench)
    for _ in range(3):
        bench.states.undoState(bench.section, bench.series)
        bench.settle()
    assert bench.contours() == {}
    assert bench.stacks() == (0, 3)

    bench.states.redoState(bench.section, bench.series)
    assert bench.contours() == {"a": [A1]}
    assert bench.ztrace() == Z_START
    assert bench.calls == [("a", SNUM, "Modify trace(s)"), "resync"]
    bench.settle()

    bench.states.redoState(bench.section, bench.series)
    assert bench.contours() == {"a": [A1], "b": [B1]}
    assert bench.ztrace() == [(9.0, 9.0, SNUM), (0.5, 0.5, OTHER)]
    assert bench.flags() == ["f1"]
    assert bench.calls == [
        ("b", SNUM, "Modify trace(s)"),
        ("z1", SNUM, "Modify ztrace"),
        (None, SNUM, "Modify flag(s)"),
        "resync",
    ]
    bench.settle()

    bench.states.redoState(bench.section, bench.series)
    assert bench.contours() == {"a": [A1, A2], "b": [B1]}
    assert bench.tform() == shifted(3.0)
    assert bench.section.modified_contours == {"a"}
    assert bench.series.modified_ztraces == set()
    assert bench.calls == [
        ("a", SNUM, "Modify trace(s)"),
        (None, SNUM, "Modify transform"),
        "resync",
    ]
    assert bench.stacks() == (3, 0)


def test_modified_names_add_to_what_the_section_already_tracks(bench):
    _three_edits(bench)
    bench.section.modified_contours.add("already")
    bench.series.modified_ztraces.add("already_z")

    bench.states.undoState(bench.section, bench.series)
    assert bench.section.modified_contours == {"already", "a"}
    assert bench.series.modified_ztraces == {"already_z"}

    bench.states.redoState(bench.section, bench.series)
    assert bench.section.modified_contours == {"already", "a"}
    assert bench.series.modified_ztraces == {"already_z"}


# --------------------------------------------------------------------------- #
# redo's object snapshot and the empty stacks                                  #
# --------------------------------------------------------------------------- #
def test_redo_puts_groups_back_only_on_a_recreated_object(bench):
    series = bench.series
    existing = next(iter(series.data["objects"]))
    series.object_groups.add(group="g_new", obj="a")
    series.object_groups.add(group="g_old", obj=existing)
    bench.edit(add=[("a", A1), (existing, A2)])
    bench.states.undoState(bench.section, bench.series)
    bench.settle()
    series.object_groups.remove(group="g_new", obj="a")
    series.object_groups.remove(group="g_old", obj=existing)

    bench.states.redoState(bench.section, bench.series)

    assert "g_new" in series.object_groups.getObjectGroups("a")
    assert "g_old" not in series.object_groups.getObjectGroups(existing)


def test_undo_does_not_restore_an_object_snapshot(bench):
    series = bench.series
    series.object_groups.add(group="g_new", obj="a")
    bench.edit(add=[("a", A1)])
    bench.edit(add=[("a", A2)])
    series.object_groups.remove(group="g_new", obj="a")

    bench.states.undoState(bench.section, bench.series)

    assert "g_new" not in series.object_groups.getObjectGroups("a")


def test_undo_and_redo_on_empty_stacks_change_nothing(bench):
    before = (bench.contours(), bench.ztrace(), bench.tform(), bench.flags())
    current = bench.states.current_state

    assert bench.states.undoState(bench.section, bench.series) is None
    assert bench.states.redoState(bench.section, bench.series) is None

    assert (bench.contours(), bench.ztrace(), bench.tform(), bench.flags()) == before
    assert bench.calls == []
    assert bench.stacks() == (0, 0)
    assert bench.states.current_state is current
