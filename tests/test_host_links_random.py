"""Host links under random actions, undone and redone out of order.

Draws and erases on random sections, and object deletes, renames, imports that
empty an object, and host links set and cleared, as series actions. Undo and
redo are taken on a random section the way the main window takes them: the
section's own step, or the series step it belongs to, so steps on separate
sections are undone in any order. Section deletes start the history over, as
they do in the app.

Each step records the host links it added and removed, and the objects it
made appear or disappear. Undoing a step must remove exactly the links it
added and bring back exactly the ones it removed, and redoing it the reverse,
unless another step changed one of those links or touched an object at either
end of one since this step was made, or the undo makes objects appear or
disappear differently from the way the step did (its object had traces on
another section that a later step took away). A section of a series step
undone or redone on its own leaves the links of objects the step did not
touch alone, and once every section of the step has been undone (or redone)
that way, the links are as a whole undo (or redo) would leave them. Objects
emptied by an unlogged update between steps, as a refresh does, belong to no
step. After every step the ids must match the traces, and what the tree shows
must be what it saves.
"""
import os
import random

import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series, Trace

NAMES = ["hr_t1", "hr_t2", "hr_h1", "hr_h2"]
STEPS = 70


def _square(series, offset):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.05
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


class Step:
    """One undoable action and the host links it changed."""

    def __init__(self, kind, touched, before, after, clock, snum=None, pos=None,
                 series_state=None, existed=(), exists=()):
        self.kind = kind
        # the objects the step made appear or disappear
        self.flipped = set(existed) ^ set(exists)
        self.touched = set(touched)
        self.added = after - before
        self.removed = before - after
        self.names = {n for pair in self.added | self.removed for n in pair}
        self.snum = snum
        self.pos = pos
        self.series_state = series_state
        self.applied = True
        self.broken = False
        # False once the stacks no longer hold the step (a new action ended
        # its redo); it still counts for the checks of older steps
        self.alive = True
        # when the step was made, and when it was last made, undone or redone
        self.made = clock
        self.at = clock


class Run:

    def __init__(self, series, rng):
        self.series = series
        self.rng = rng
        self.names = list(NAMES)
        self.renamed = 0
        self.clock = 0
        # the checks that ran: of whole steps, of section steps alone, of a
        # section of a series step alone, and of a series step undone or
        # redone section by section to the end
        self.checked = 0
        self.checked_sections = 0
        self.checked_parts = 0
        self.checked_whole_parts = 0
        self.restart()

    def restart(self):
        """What the app does after a section delete: the undo history starts
        over."""
        self.states = SeriesStates(self.series)
        self.steps = []

    def pairs(self):
        return {
            (t, h) for t, hosts in self.series.host_tree.getDict().items()
            for h in hosts
        }

    def objects(self):
        return [n for n in self.names if n in self.series.data["objects"]]

    def existing(self):
        ids = self.series.data.object_ids
        return {n for n in self.names if ids.live(n)}

    def tick(self):
        self.clock += 1
        return self.clock

    def prune(self):
        """Mark the steps the undo stacks no longer hold (a new action ends
        the redos) as gone, and a series step one of its sections was undone
        alone from as broken."""
        states = self.states
        for step in self.steps:
            if not step.alive:
                continue
            if step.kind == "series":
                if step.series_state in states.undos or step.series_state in states.redos:
                    continue
                if step.applied:
                    step.broken = True
                else:
                    step.alive = False
            elif not step.applied:
                section_states = states.section_states_dict.get(step.snum)
                if section_states is None or step.pos > (
                    len(section_states.undo_states) + len(section_states.redo_states)
                ):
                    step.alive = False

    # actions
    def section_action(self, snum, name, edit):
        series = self.series
        before, existed = self.pairs(), self.existing()
        series.current_section = snum
        section = series.loadSection(snum)
        states = self.states[section]
        edit(section)
        states.addState(section, series)
        series.data.updateSection(section, update_traces=True, all_traces=False)
        section.clearTracking()
        self.states.checkOverwrite(snum)
        section.save()
        pos = len(states.undo_states)
        for s in self.steps:
            if s.kind == "section" and s.snum == snum and s.pos >= pos:
                s.alive = False
        self.steps.append(Step(
            "section", {name}, before, self.pairs(), self.tick(), snum=snum, pos=pos,
            existed=existed, exists=self.existing(),
        ))
        self.prune()

    def series_action(self, touched, perform):
        before, existed = self.pairs(), self.existing()
        undos = len(self.states.undos)
        perform()
        assert len(self.states.undos) == undos + 1, "no series undo state"
        self.steps.append(Step(
            "series", touched, before, self.pairs(), self.tick(),
            series_state=self.states.undos[-1], existed=existed,
            exists=self.existing(),
        ))
        self.prune()

    def draw(self):
        snum = self.rng.choice(sorted(self.series.sections))
        name = self.rng.choice(self.names)

        def edit(section):
            trace = Trace(name, (0, 255, 0), True)
            trace.points = _square(self.series, self.rng.uniform(0.1, 0.8))
            section.addTrace(trace)

        self.section_action(snum, name, edit)

    def erase(self):
        snum = self.rng.choice(sorted(self.series.sections))
        section = self.series.loadSection(snum)
        names = sorted(n for n, c in section.contours.items() if len(c) and n in self.names)
        if not names:
            return
        name = self.rng.choice(names)

        def edit(section):
            for trace in list(section.contours[name]):
                section.removeTrace(trace)

        self.section_action(snum, name, edit)

    def delete_object(self):
        names = self.objects()
        if names:
            name = self.rng.choice(names)
            self.series_action({name}, lambda: self.series.deleteObjects(
                [name], series_states=self.states
            ))

    def rename(self):
        names = self.objects()
        if not names:
            return
        old = self.rng.choice(names)
        self.renamed += 1
        new = f"hr_r{self.renamed}"
        self.names.append(new)
        self.series_action({old, new}, lambda: self.series.editObjectAttributes(
            [old], name=new, series_states=self.states
        ))

    def import_empty(self):
        """What an import does when the other series deleted an object:
        the sections are saved with object logging off."""
        names = self.objects()
        if not names:
            return
        name = self.rng.choice(names)
        series = self.series

        def perform():
            series.data.supress_logging = True
            try:
                for snum, section in series.enumerateSections(
                    show_progress=False, series_states=self.states
                ):
                    if name in section.contours:
                        for trace in list(section.contours[name]):
                            section.removeTrace(trace)
                        del section.contours[name]
                        section.save()
            finally:
                series.data.supress_logging = False

        self.series_action({name}, perform)

    def link(self):
        """Set a host from the object list: a series action."""
        names = self.objects()
        if len(names) >= 2:
            traveler, host = self.rng.sample(names, 2)

            def perform():
                self.states.addState()
                self.series.host_tree.add(traveler, [host])

            self.series_action({traveler, host}, perform)

    def unlink(self):
        names = self.objects()
        if names:
            name = self.rng.choice(names)

            def perform():
                self.states.addState()
                self.series.clearObjHosts([name])

            self.series_action({name}, perform)

    def group(self):
        """Add an object to a group from the object list: a series action
        that changes no link."""
        names = self.objects()
        if names:
            name = self.rng.choice(names)

            def perform():
                self.states.addState()
                self.series.object_groups.add(group="hr_group", obj=name)

            self.series_action(set(), perform)

    def unlogged_empty(self):
        """Empty an object on one section with an unlogged update, as a
        refresh would: no undoable step. Only on a section with no undo
        history, whose first undo state would otherwise put the traces back
        behind the series data's back."""
        fresh = [
            n for n in sorted(self.series.sections)
            if not self.states.section_states_dict[n].initialized
        ]
        if not fresh:
            return
        snum = self.rng.choice(fresh)
        section = self.series.loadSection(snum)
        names = sorted(n for n, c in section.contours.items() if len(c) and n in self.names)
        if not names:
            return
        name = self.rng.choice(names)
        for trace in list(section.contours[name]):
            section.removeTrace(trace)
        del section.contours[name]
        section.save(update_series_data=False)
        self.series.data.updateSection(section, update_traces=True, log_events=False)

    # undo and redo, on a random section
    def independent(self, step, partial=False):
        """True if no step changed its links, touched an object at either
        end of one, or linked an object the step made or deleted (undoing
        it deletes or brings back that object's newer links too) since this
        step was made. A step last made, undone or redone before that is
        part of what this step was recorded against; one toggled since is
        not, whatever the order the two were made in.

            Params:
                partial (bool): True for a series step undone or redone one
                    section at a time (see undo)
        """
        if step.broken and not partial:
            return False
        changed = step.added | step.removed
        for other in self.steps:
            if other is step:
                continue
            if other.at <= step.made:
                continue
            if (other.added | other.removed) & changed:
                return False
            if other.touched & step.names:
                return False
            if (other.touched | other.names) & step.flipped:
                return False
            # a newer step made an object this step touched appear or go
            # (undoing this step can bring back part of the old one)
            if other.flipped & step.touched:
                return False
            # a series undo or redo puts back the whole host tree it stored,
            # so a newer step's link changes still in place go too
            if (step.kind == "series" and (other.added or other.removed)
                    and (other.applied or other.broken)):
                return False
        return True

    def find_section_step(self, snum, pos):
        for step in self.steps:
            if step.alive and step.kind == "section" and step.snum == snum and step.pos == pos:
                return step
        return None

    def find_series_step(self, series_state):
        for step in self.steps:
            if step.alive and step.kind == "series" and step.series_state is series_state:
                return step
        return None

    def find_series_part(self, snum, pos):
        """The series step a section's state at this position belongs to:
        the newest one still on the stacks or broken into its sections."""
        for step in reversed(self.steps):
            if (step.kind == "series" and (step.alive or step.broken)
                    and step.series_state.undo_lens.get(snum) == pos):
                return step
        return None

    def near(self, step):
        """The objects a section of the step can change the links of: the
        ones it touched or linked, and those linked to them through others
        (a link shows only while it is not redundant through a chain of
        hosts, so a change reaches a link through the chain)."""
        pairs = self.pairs()
        near = set(step.touched | step.names)
        grown = True
        while grown:
            grown = False
            for t, h in pairs:
                if (t in near) != (h in near):
                    near |= {t, h}
                    grown = True
        return near

    def unrelated(self, near):
        return {p for p in self.pairs() if not (set(p) & near)}

    def complete(self, step, redo):
        """True once every section of the series step has been undone (or
        redone) on its own."""
        return all(
            len(self.states.section_states_dict[snum].undo_states) == n - (0 if redo else 1)
            for snum, n in step.series_state.undo_lens.items()
        )

    def undo(self, redo=False):
        series, states = self.series, self.states
        snum = self.rng.choice(sorted(series.sections))
        series.current_section = snum
        section = series.loadSection(snum)
        states[section]
        can_3d, can_2d, linked = states.canUndo(snum, redo)
        if can_3d and can_2d:
            whole = self.rng.random() < 0.5 if linked else states.favor3D(snum, redo)
        else:
            whole = can_3d
        if not (can_3d or can_2d):
            return

        word = "redo" if redo else "undo"
        part = None
        if whole:
            step = self.find_series_step(states.redos[-1] if redo else states.undos[-1])
        else:
            section_states = states.section_states_dict[snum]
            pos = len(section_states.undo_states) + (1 if redo else 0)
            step = self.find_section_step(snum, pos)
            if step is None:
                # a section of a series step, undone or redone alone
                part = self.find_series_part(snum, pos)
                if part is not None:
                    part.broken = True
                    part.at = self.tick()
        expected = None
        existed = self.existing()
        if step is not None and self.independent(step):
            gone, back = (step.removed, step.added) if redo else (step.added, step.removed)
            expected = (self.pairs() - gone) | back
        part_expected = None
        if part is not None:
            near = self.near(part)
            unrelated = self.unrelated(near)
            if self.independent(part, partial=True):
                gone, back = (part.removed, part.added) if redo else (part.added, part.removed)
                part_expected = (self.pairs() - gone) | back

        if whole:
            states.undoState(redo=redo)
        else:
            states.undoSection(section, redo)
            series.data.updateSection(section, update_traces=True, all_traces=False)
            section.clearTracking()
            section.save()

        if expected is not None and (existed ^ self.existing()) != step.flipped:
            expected = None  # objects came or went the step did not make
        if step is not None:
            step.applied = redo
            step.at = self.tick()
        if part is not None and self.complete(part, redo):
            part.applied = redo
        self.prune()
        if expected is not None:
            self.checked += 1
            if step.kind == "section":
                self.checked_sections += 1
            assert self.pairs() == expected, (
                f"{word} of a {step.kind} step on {step.snum} did not restore its links"
            )
        if part is not None:
            self.checked_parts += 1
            assert self.unrelated(near) == unrelated, (
                f"{word} of one section of a series step changed the links of "
                "objects it did not touch"
            )
            if part_expected is not None and self.complete(part, redo):
                self.checked_whole_parts += 1
                assert self.pairs() == part_expected, (
                    f"{word} of a series step section by section did not restore its links"
                )

    def redo(self):
        self.undo(redo=True)

    # a step that starts the history over
    def delete_section(self):
        series = self.series
        if len(series.sections) <= 3:
            return
        series.deleteSections([self.rng.choice(sorted(series.sections))])
        if series.current_section not in series.sections:
            series.current_section = min(series.sections)
        series.data.refresh()
        self.restart()

    # the check
    def check(self, label):
        series = self.series
        present = {
            (snum, name)
            for snum in series.sections
            for name, contour in series.loadSection(snum).contours.items()
            if len(contour)
        }
        assert set(series.data.object_ids.placed) == present, label
        tree = series.host_tree
        shown = {
            name: sorted(tree.getHosts(name)) for name in self.names
            if tree.getHosts(name)
        }
        saved = {n: h for n, h in tree.getDict().items() if n in self.names}
        assert shown == saved, label


OPS = (
    ["draw"] * 7 + ["erase"] * 3 + ["undo"] * 8 + ["redo"] * 4
    + ["link"] * 3 + ["unlink", "delete_object", "rename", "import_empty"]
    + ["group", "unlogged_empty", "delete_section"]
)


def _run(jser_path, seed) -> Run:
    series = Series.openJser(str(jser_path))
    series.setProgressReporter(NullProgressReporter)
    try:
        rng = random.Random(seed)
        run = Run(series, rng)
        history = []
        for i in range(STEPS):
            op = rng.choice(OPS)
            history.append(op)
            getattr(run, op)()
            run.check(f"seed {seed}, step {i}: {history[-8:]}")
        return run
    finally:
        series.close()


@pytest.mark.parametrize("seed", range(int(os.environ.get("HR_SEEDS", "100"))))
def test_undo_and_redo_in_any_order_restore_the_links(shapes1_jser, seed):
    _run(shapes1_jser, seed)


@pytest.mark.parametrize("seed", [2747, 2877])
def test_orders_found_by_a_wider_run_restore_the_links(shapes1_jser, seed):
    """Two orders a run of thousands of seeds found: a link step redone
    after the draw of its host was undone (2747), and a rename undone after
    one section of an earlier rename was undone alone (2877). Each is a step
    toggled after the checked step was made, which the checks must count
    whatever the order the two steps were made in."""
    _run(shapes1_jser, seed)


def test_sections_of_series_steps_are_checked(shapes1_jser):
    """The runs above check section steps undone alone, sections of series
    steps undone alone, and series steps undone section by section to the
    end, not only whole steps."""
    counts = {"sections": 0, "parts": 0, "whole_parts": 0}
    for seed in range(40):
        run = _run(shapes1_jser, seed)
        counts["sections"] += run.checked_sections
        counts["parts"] += run.checked_parts
        counts["whole_parts"] += run.checked_whole_parts
    assert all(counts.values()), counts
