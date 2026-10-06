"""Object ids under random section edits, with no refresh in between.

Draws, erases, undos and redos on random sections, mixed with section
deletes, inserts and reorders. After every step the registry must hold
exactly the (section, name) pairs that have traces, its live counts must
match its placements, and a name with no live id must get a fresh one.
"""
import random

import pytest

from PyReconstruct.modules.backend.func.state_manager import SectionStates
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series, Trace

NAMES = ["rnd_a", "rnd_b", "square"]
STEPS = 80


def _square(series, offset):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.05
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


class Run:

    def __init__(self, series, rng):
        self.series = series
        self.rng = rng
        self.states = {}

    @property
    def ids(self):
        return self.series.data.object_ids

    # -- what the field does -------------------------------------------------- #
    def act(self, snum, edit):
        series = self.series
        section = series.loadSection(snum)
        states = self.states.get(snum)
        if states is None:
            states = self.states[snum] = SectionStates(section, series)
        edit(section)
        states.addState(section, series)
        series.data.updateSection(section, update_traces=True, all_traces=False)
        section.clearTracking()
        section.save()

    def step(self, snum, redo):
        series = self.series
        section = series.loadSection(snum)
        states = self.states[snum]
        if redo:
            states.redoState(section, series)
        else:
            states.undoState(section, series)
        series.data.updateSection(section, update_traces=True, all_traces=False)
        section.clearTracking()
        section.save()

    # -- the operations ------------------------------------------------------- #
    def draw(self):
        snum = self.rng.choice(sorted(self.series.sections))
        name = self.rng.choice(NAMES)
        had = self.ids.live(name)
        issued = set(self.ids.name_of)
        placed = self.ids.peek(snum, name)

        def edit(section):
            trace = Trace(name, (0, 255, 0), True)
            trace.points = _square(self.series, self.rng.uniform(0.1, 0.8))
            section.addTrace(trace)

        self.act(snum, edit)
        oid = self.ids.peek(snum, name)
        if placed is not None:
            assert oid == placed
        elif had:
            assert oid == max(had)
        else:
            assert oid not in issued, "a name with no live id reused an old one"

    def erase(self):
        snum = self.rng.choice(sorted(self.series.sections))
        section = self.series.loadSection(snum)
        names = [n for n, c in section.contours.items() if len(c)]
        if not names:
            return
        name = self.rng.choice(sorted(names))

        def edit(section):
            for trace in list(section.contours[name]):
                section.removeTrace(trace)

        self.act(snum, edit)

    def undo(self, redo=False):
        candidates = [
            snum for snum, st in self.states.items()
            if (st.redo_states if redo else st.undo_states)
        ]
        if candidates:
            self.step(self.rng.choice(sorted(candidates)), redo)

    def redo(self):
        self.undo(redo=True)

    def delete(self):
        series = self.series
        if len(series.sections) <= 2:
            return
        snum = self.rng.choice(sorted(series.sections))
        series.deleteSections([snum])
        if series.current_section not in series.sections:
            series.current_section = min(series.sections)
        self.states.clear()  # the section list clears the undo history

    def insert(self):
        series = self.series
        index = self.rng.randrange(0, max(series.sections) + 4)
        series.insertSection(index, "no-image", 0.00254, 0.05)
        self.states.clear()

    def reorder(self):
        series = self.series
        if self.rng.random() < 0.5:
            series.reorderSections()
        else:
            numbers = sorted(series.sections)
            shuffled = numbers[:]
            self.rng.shuffle(shuffled)
            series.reorderSections(dict(zip(numbers, shuffled)))
        self.states.clear()

    # -- the check ------------------------------------------------------------ #
    def check(self, label):
        series = self.series
        present = {
            (snum, name)
            for snum in series.sections
            for name, contour in series.loadSection(snum).contours.items()
            if len(contour)
        }
        ids = self.ids
        assert set(ids.placed) == present, label

        counts = {}
        for (snum, name), oid in ids.placed.items():
            assert ids.name_of[oid] == name, label
            per_name = counts.setdefault(name, {})
            per_name[oid] = per_name.get(oid, 0) + 1
        assert ids._live == counts, f"{label}: an id outlived its traces"


@pytest.mark.parametrize("seed", range(16))
def test_random_section_edits_keep_the_ids_exact(shapes1_jser, seed):
    series = Series.openJser(str(shapes1_jser))
    series.setProgressReporter(NullProgressReporter)
    try:
        rng = random.Random(seed)
        run = Run(series, rng)
        run.check("open")
        ops = (
            ["draw"] * 5 + ["erase"] * 4 + ["undo"] * 4 + ["redo"] * 2
            + ["delete", "insert", "reorder"]
        )
        history = []
        for i in range(STEPS):
            op = rng.choice(ops)
            history.append(op)
            getattr(run, op)()
            run.check(f"seed {seed}, step {i}: {history[-6:]}")
    finally:
        series.close()
