"""Host links under random actions and undo, with one linear history.

Draws, erases, object deletes, renames and imports that empty an object, each
an undoable action, mixed with section deletes and host links set and cleared,
which start the history over as they do in the app. Undo always takes the
newest action and redo the newest undone one, so each must leave the saved
host links exactly as they were before that action, or after it.

After every step the ids must match the traces, and what the tree shows must
be what it saves.
"""
import random

import pytest

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series, Trace

NAMES = ["hr_t1", "hr_t2", "hr_h1", "hr_h2"]
STEPS = 60


def _square(series, offset):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.05
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


class Run:

    def __init__(self, series, rng):
        self.series = series
        self.rng = rng
        self.names = list(NAMES)
        self.renamed = 0
        self.restart()

    def restart(self):
        """What the app does after a section delete or a host change here:
        the undo history starts over."""
        self.states = SeriesStates(self.series)
        self.history = []
        self.redos = []

    def links(self):
        return self.series.host_tree.getDict()

    def objects(self):
        return [n for n in self.names if n in self.series.data["objects"]]

    # -- actions ---------------------------------------------------------------- #
    def record(self, kind, perform):
        before = self.links()
        perform()
        self.history.append((kind, before, self.links()))
        self.redos = []

    def section_action(self, snum, edit):
        series = self.series
        series.current_section = snum
        section = series.loadSection(snum)
        states = self.states[section]
        edit(section)
        states.addState(section, series)
        series.data.updateSection(section, update_traces=True, all_traces=False)
        section.clearTracking()
        self.states.checkOverwrite(snum)
        section.save()

    def draw(self):
        snum = self.rng.choice(sorted(self.series.sections))
        name = self.rng.choice(self.names)

        def edit(section):
            trace = Trace(name, (0, 255, 0), True)
            trace.points = _square(self.series, self.rng.uniform(0.1, 0.8))
            section.addTrace(trace)

        self.record(("section", snum), lambda: self.section_action(snum, edit))

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

        self.record(("section", snum), lambda: self.section_action(snum, edit))

    def delete_object(self):
        names = self.objects()
        if names:
            name = self.rng.choice(names)
            self.record("series", lambda: self.series.deleteObjects(
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
        self.record("series", lambda: self.series.editObjectAttributes(
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

        self.record("series", perform)

    # -- undo and redo ------------------------------------------------------------ #
    def step(self, kind, redo):
        series = self.series
        if kind == "series":
            self.states.undoState(redo=redo)
            return
        snum = kind[1]
        series.current_section = snum
        section = series.loadSection(snum)
        self.states.undoSection(section, redo)
        series.data.updateSection(section, update_traces=True, all_traces=False)
        section.clearTracking()
        section.save()

    def undo(self):
        if not self.history:
            return
        kind, before, after = self.history.pop()
        self.step(kind, redo=False)
        assert self.links() == before, f"undo of {kind} did not restore the links"
        self.redos.append((kind, before, after))

    def redo(self):
        if not self.redos:
            return
        kind, before, after = self.redos.pop()
        self.step(kind, redo=True)
        assert self.links() == after, f"redo of {kind} did not restore the links"
        self.history.append((kind, before, after))

    # -- steps that start the history over ------------------------------------- #
    def delete_section(self):
        series = self.series
        if len(series.sections) <= 3:
            return
        series.deleteSections([self.rng.choice(sorted(series.sections))])
        if series.current_section not in series.sections:
            series.current_section = min(series.sections)
        series.data.refresh()
        self.restart()

    def link(self):
        names = self.objects()
        if len(names) >= 2:
            traveler, host = self.rng.sample(names, 2)
            self.series.host_tree.add(traveler, [host])
            self.restart()

    def unlink(self):
        names = self.objects()
        if names:
            self.series.clearObjHosts([self.rng.choice(names)])
            self.restart()

    # -- the check ------------------------------------------------------------- #
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


@pytest.mark.parametrize("seed", range(40))
def test_undo_and_redo_restore_the_saved_links(shapes1_jser, seed):
    series = Series.openJser(str(shapes1_jser))
    series.setProgressReporter(NullProgressReporter)
    try:
        rng = random.Random(seed)
        run = Run(series, rng)
        ops = (
            ["draw"] * 6 + ["erase"] * 3 + ["undo"] * 6 + ["redo"] * 3
            + ["link"] * 3 + ["unlink", "delete_object", "rename", "import_empty"]
            + ["delete_section"]
        )
        history = []
        for i in range(STEPS):
            op = rng.choice(ops)
            history.append(op)
            getattr(run, op)()
            run.check(f"seed {seed}, step {i}: {history[-8:]}")
    finally:
        series.close()
