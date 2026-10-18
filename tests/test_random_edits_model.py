"""Random edits through the main window, checked against a plain model.

A run opens a real MainWindow on a copy of shapes1 and takes a random list
of steps through the field and the window, the way the menus and keys do:
draw, delete, move, hide, unhide all, merge, rename traces, rename and delete
objects, change section, undo and redo. Beside it, the model holds the same
series as plain lists of traces per section, in field coordinates, with no Qt
and no files. Each step is done to both, and after every step the two must
hold the same traces on every section, and the series data must list each
object on exactly the sections it has traces on.

Undo in the model follows the rules the app documents in state_manager.py,
in plain terms:

- Each section has its own undo and redo stacks. An edit on a section is one
  step there, and a new edit ends that section's redos.
- An object rename or delete is a series step: one step on each section it
  changed, grouped. A new series step ends every redo.
- A series step can be undone (or redone) whole only while it is the newest
  one and each of its sections still has its part on top.
- When the section's own newest step is part of that series step, the app
  asks whether to undo the whole step or the section only. The run answers
  at random, and taking one section alone dissolves the series step into
  plain section steps.
- Otherwise, when both are possible, the newer one wins.
- A section edit that lands where the newest series step's part was undone
  takes that series step away, and a section edit ends the series redos and
  the redos of their sections.

The model cannot know where a merge puts its points. So after a merge it
checks the result against the two traces it merged, not against the app:
the new traces have their name, there is one for each separate piece (one if
the two touch, overlap or nest, else two), their bounds are the traces'
bounds to within MERGE_TOL, and on a grid of points MERGE_TOL / 2 apart they
cover the same points as the two traces. A point counts as covered when a
trace winds around it. The only points let off are those with a grid point
within MERGE_TOL that the two traces cover differently, so they lie within
MERGE_TOL of the outside edge of the two together; an edge of one trace that
runs inside the other lets off nothing. A gain or loss narrower than the grid
step can fall between the points and pass. Then the model takes the new
points from the app, and every later step is checked exactly. When the app
refuses a merge, the model takes the refusal and does not check that it was
right.

A failing run prints its seed and every step. To replay one, run the slow
test for that seed, for example `-k "test_many_random_edit_runs and 17-"`,
or set MODEL_SEEDS and MODEL_STEPS.
"""
import os
import random

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import Trace

# two short runs that between them reach every kind of undo and redo but a
# whole redo, which the long runs reach, and that each merge traces that
# touch; each names what it must reach, so a change to the steps that loses
# one fails here
FAST_SEEDS = [
    (211, {
        "undo whole", "undo all", "undo section", "undo cancel", "redo section",
        "delete object", "merge touching", "merge apart",
    }),
    (223, {"redo all", "rename object", "merge touching"}),
]
FAST_STEPS = 40
# one placeholder seed, skipped, unless MODEL_SEEDS asks for a real run
SLOW_SEEDS = int(os.environ.get("MODEL_SEEDS", "1"))
SLOW_STEPS = int(os.environ.get("MODEL_STEPS", "150"))

DRAWN = ["m_a", "m_b", "m_c"]
TOL = 1e-6
# a merge redraws its outline on a grid; its edges may move this far
MERGE_TOL = 0.05


class Shape:
    """One trace as the user sees it: field coordinates, not section ones."""

    __slots__ = ("name", "points", "hidden", "closed")

    def __init__(self, name, points, hidden=False, closed=True):
        self.name = name
        self.points = tuple((float(x), float(y)) for x, y in points)
        self.hidden = hidden
        self.closed = closed

    def copy(self, **changes):
        shape = Shape(self.name, self.points, self.hidden, self.closed)
        for key, value in changes.items():
            setattr(shape, key, value)
        return shape

    def same(self, other):
        return (
            self.name == other.name
            and self.hidden == other.hidden
            and self.closed == other.closed
            and len(self.points) == len(other.points)
            and all(
                abs(a - c) <= TOL and abs(b - d) <= TOL
                for (a, b), (c, d) in zip(self.points, other.points)
            )
        )

    def __repr__(self):
        x, y = self.points[0]
        flag = " hidden" if self.hidden else ""
        return f"{self.name}{flag} at ({x:.2f}, {y:.2f})"


def _bounds(shapes):
    xs = [x for s in shapes for x, _ in s.points]
    ys = [y for s in shapes for _, y in s.points]
    return min(xs), min(ys), max(xs), max(ys)


def _edges(shape):
    points = shape.points
    return zip(points, points[1:] + points[:1])


def _inside(shape, x, y):
    """Whether the closed shape winds around each point (x, y arrays)."""
    wind = np.zeros(np.shape(x), int)
    for (x1, y1), (x2, y2) in _edges(shape):
        cross = (x2 - x1) * (y - y1) - (x - x1) * (y2 - y1)
        wind += (y1 <= y) & (y2 > y) & (cross > 0)
        wind -= (y2 <= y) & (y1 > y) & (cross < 0)
    return wind != 0


def _touch(a, b):
    """Whether two closed shapes touch, overlap or nest."""
    if _inside(a, *np.array(b.points).T).any() or _inside(b, *np.array(a.points).T).any():
        return True

    def side(p, q, r):
        cross = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (cross > 0) - (cross < 0)

    def overlap(p, q, r, s, i):
        return min(p[i], q[i]) <= max(r[i], s[i]) and min(r[i], s[i]) <= max(p[i], q[i])

    for p, q in _edges(a):
        for r, s in _edges(b):
            if (
                overlap(p, q, r, s, 0) and overlap(p, q, r, s, 1)
                and side(p, q, r) * side(p, q, s) <= 0
                and side(r, s, p) * side(r, s, q) <= 0
            ):
                return True
    return False


def _area_off(picked, made):
    """The points of a grid over the merged traces where the merge result and
    the traces before it disagree on what is covered, leaving out the points
    with a grid point within MERGE_TOL that the traces before it cover
    differently. Those are near the outside edge of the traces together, and
    an edge of one trace that runs inside the other is not."""
    x0, y0, x1, y1 = _bounds(picked)
    step = MERGE_TOL / 2
    # off the round numbers traces are drawn at, so no grid point lands on
    # an edge, and wide enough that the edge of the grid is never covered
    x, y = np.meshgrid(
        np.arange(x0 - 2 * MERGE_TOL + 0.37 * step, x1 + 2 * MERGE_TOL, step),
        np.arange(y0 - 2 * MERGE_TOL + 0.37 * step, y1 + 2 * MERGE_TOL, step),
    )
    want = np.zeros(x.shape, bool)
    for shape in picked:
        want |= _inside(shape, x, y)
    got = np.zeros(x.shape, bool)
    for shape in made:
        got |= _inside(shape, x, y)
    reach = round(MERGE_TOL / step)
    rows, cols = want.shape
    padded = np.pad(want, reach)
    near = np.zeros(x.shape, bool)
    for i in range(-reach, reach + 1):
        for j in range(-reach, reach + 1):
            if i * i + j * j <= reach * reach:
                near |= want != padded[reach + i:reach + i + rows, reach + j:reach + j + cols]
    off = (want != got) & ~near
    return [(round(float(a), 2), round(float(b), 2)) for a, b in zip(x[off], y[off])]


class Entry:
    """One step on a section's undo or redo stack: the section's traces on
    the other side of the step, the series step it belongs to, and when it
    went onto the stack."""

    def __init__(self, shapes, group, time):
        self.shapes = shapes
        self.group = group
        self.time = time


class Group:
    """A series step: its part on each section, by stack position."""

    def __init__(self, time):
        self.time = time
        self.pos = {}


class Model:

    def __init__(self, sections):
        self.sections = {n: list(shapes) for n, shapes in sections.items()}
        self.undo = {n: [] for n in sections}
        self.redo = {n: [] for n in sections}
        self.series_undo = []
        self.series_redo = []
        self.clock = 0

    def tick(self):
        self.clock += 1
        return self.clock

    def objects(self):
        found = {}
        for n, shapes in self.sections.items():
            for s in shapes:
                found.setdefault(s.name, set()).add(n)
        return found

    # edits
    def section_edit(self, n, shapes):
        self.redo[n] = []
        self.undo[n].append(Entry(self.sections[n], None, self.tick()))
        self.sections[n] = shapes
        top = self.series_undo[-1] if self.series_undo else None
        if top is not None and top.pos.get(n) == len(self.undo[n]):
            self.series_undo.pop()
        for group in self.series_redo:
            for m in group.pos:
                self.redo[m] = []
        self.series_redo = []

    def series_edit(self, changes):
        """changes: section number -> its traces after the step, for the
        sections the step changed."""
        self.series_redo = []
        for n in self.redo:
            self.redo[n] = []
        group = Group(self.tick())
        for n in sorted(changes):
            self.undo[n].append(Entry(self.sections[n], group, self.tick()))
            self.sections[n] = changes[n]
            group.pos[n] = len(self.undo[n])
        self.series_undo.append(group)

    # undo and redo
    def _stacks(self, redo):
        return (self.redo, self.series_redo) if redo else (self.undo, self.series_undo)

    def choice(self, current, redo):
        """What an undo (or redo) on the current section does: "whole",
        "section", "ask" (both, and linked), or None."""
        stacks, series = self._stacks(redo)
        group = series[-1] if series else None
        whole = group is not None and all(
            stacks[n] and stacks[n][-1].group is group for n in group.pos
        )
        own = stacks[current]
        if whole and own:
            if own[-1].group is group:
                return "ask"
            return "whole" if group.time > own[-1].time else "section"
        if whole:
            return "whole"
        if own:
            return "section"
        return None

    def _move(self, n, redo):
        source, _ = self._stacks(redo)
        target, _ = self._stacks(not redo)
        entry = source[n].pop()
        target[n].append(Entry(self.sections[n], entry.group, self.tick()))
        self.sections[n] = entry.shapes

    def undo_whole(self, redo):
        _, series = self._stacks(redo)
        _, other = self._stacks(not redo)
        group = series[-1]
        for n in sorted(group.pos):
            self._move(n, redo)
        group.time = self.tick()
        other.append(series.pop())

    def undo_section(self, n, redo):
        stacks, series = self._stacks(redo)
        group = stacks[n][-1].group
        if group in series:
            series.remove(group)  # taken one section alone, it dissolves
        self._move(n, redo)


class FakeTraceDialog:
    """The attribute dialog, answered with a new name and nothing else."""

    answer = None

    def __init__(self, *args, is_obj_list=False, **kwargs):
        self.is_obj_list = is_obj_list
        self.tag_choices = None

    def exec(self):
        trace = Trace(FakeTraceDialog.answer, None)
        trace.color = None
        trace.tags = None
        trace.fill_mode = None
        if self.is_obj_list:
            return (trace, None), True
        return trace, True


class Run:

    def __init__(self, window, recorder, rng):
        self.window = window
        self.field = window.field
        self.series = window.series
        self.recorder = recorder
        self.rng = rng
        self.renamed = 0
        self.history = []
        # the kinds of step the run took, for the fast seeds' coverage
        self.reached = set()
        self.model = Model({n: self.app_shapes(n) for n in self.series.sections})
        self.names = sorted(set(DRAWN) | set(self.model.objects()))

    # reading the app
    def section(self, n):
        if n == self.field.section.n:
            return self.field.section
        return self.series.loadSection(n)

    def app_shapes(self, n, section=None):
        section = section or self.section(n)
        tform = section.tform
        return [
            Shape(t.name, [tform.map(*p) for p in t.points], t.hidden, t.closed)
            for traces in section.contours.values() for t in traces
        ]

    def app_trace(self, shape, taken=()):
        section = self.field.section
        tform = section.tform
        for trace in section.contours.get(shape.name, ()):
            if any(trace is t for t in taken):
                continue
            seen = Shape(trace.name, [tform.map(*p) for p in trace.points],
                         trace.hidden, trace.closed)
            if seen.same(shape):
                return trace
        raise AssertionError(f"no trace in the app for {shape}")

    @property
    def current(self):
        return self.field.section.n

    def visible(self, name=None):
        return [
            s for s in self.model.sections[self.current]
            if not s.hidden and (name is None or s.name == name)
        ]

    def select(self, shapes):
        traces = []
        for shape in shapes:
            traces.append(self.app_trace(shape, traces))
        self.field.deselectAllTraces()
        self.field.selectTraces(traces, [])

    def note(self, text):
        self.history.append(f"s{self.current} {text}")

    # actions
    def goto(self):
        n = self.rng.choice(sorted(self.series.sections))
        self.history.append(f"go to section {n}")
        self.window.changeSection(n)

    def draw(self):
        wx, wy, ww, wh = self.series.window
        side = round(min(ww, wh) * 0.12, 2)
        x0 = round(wx + ww * self.rng.choice([0.1, 0.2, 0.3, 0.4, 0.5]), 2)
        y0 = round(wy + wh * self.rng.choice([0.1, 0.2, 0.3, 0.4, 0.5]), 2)
        points = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
        name = self.rng.choice(DRAWN)
        self.note(f"draw {name} at ({x0}, {y0})")
        self.field.deselectAllTraces()
        self.field.newTrace(
            points, Trace(name, (0, 200, 0), True),
            points_as_pix=False, reduce_points=False,
        )
        n = self.current
        self.model.section_edit(n, self.model.sections[n] + [Shape(name, points)])

    def _pick(self, most):
        shapes = self.visible()
        if not shapes:
            return []
        return self.rng.sample(shapes, self.rng.randint(1, min(most, len(shapes))))

    def _replace(self, picked, made):
        n = self.current
        kept = [s for s in self.model.sections[n] if not any(s is p for p in picked)]
        self.model.section_edit(n, kept + made)

    def delete(self):
        picked = self._pick(2)
        if not picked:
            return
        self.note(f"delete {picked}")
        self.select(picked)
        self.field.deleteTraces()
        self._replace(picked, [])

    def move(self):
        picked = self._pick(2)
        if not picked:
            return
        dx, dy = self.rng.choice([-0.5, -0.25, 0.25, 0.5]), self.rng.choice([-0.5, 0.25, 0.5])
        self.note(f"move {picked} by ({dx}, {dy})")
        self.select(picked)
        self.field.translate(dx, dy)
        self._replace(picked, [
            s.copy(points=tuple((x + dx, y + dy) for x, y in s.points)) for s in picked
        ])

    def hide(self):
        picked = self._pick(2)
        if not picked:
            return
        self.note(f"hide {picked}")
        self.select(picked)
        self.field.hideTraces()
        self._replace(picked, [s.copy(hidden=True) for s in picked])

    def unhide_all(self):
        n = self.current
        if not any(s.hidden for s in self.model.sections[n]):
            return
        self.note("unhide all")
        self.field.unhideAllTraces()
        self.model.section_edit(n, [s.copy(hidden=False) for s in self.model.sections[n]])

    def rename_traces(self):
        picked = self._pick(2)
        if not picked:
            return
        name = self.new_name()
        self.note(f"rename {picked} to {name}")
        self.select(picked)
        FakeTraceDialog.answer = name
        self.field.traceDialog()
        self._replace(picked, [s.copy(name=name) for s in picked])

    def merge(self):
        pairs = []
        for name in sorted({s.name for s in self.visible()}):
            shapes = [s for s in self.visible(name) if s.closed]
            pairs += [(a, b) for i, a in enumerate(shapes) for b in shapes[i + 1:]]
        if not pairs:
            return
        # traces that touch merge into one, which is the case worth checking
        touching = [pair for pair in pairs if _touch(*pair)]
        picked = list(self.rng.choice(touching or pairs))
        name = picked[0].name
        self.note(f"merge {picked}")
        self.select(picked)
        notices = len(self.recorder.notices)
        self.field.mergeTraces()
        if len(self.recorder.notices) > notices:
            self.history[-1] += " (refused)"
            return  # a refused merge changes nothing
        n = self.current
        kept = [s for s in self.model.sections[n] if not any(s is p for p in picked)]
        # the new traces are the ones in the app that match no kept trace
        unmatched = list(kept)
        made = []
        for shape in self.app_shapes(n, self.field.section):
            match = next((k for k in unmatched if shape.same(k)), None)
            if match is None:
                made.append(shape)
            else:
                unmatched.remove(match)
        assert all(s.name == name and not s.hidden and s.closed for s in made), made
        groups = 2 - bool(touching)
        assert len(made) == groups, (
            f"the merge made {len(made)} traces from {groups} separate pieces"
        )
        want, got = _bounds(picked), _bounds(made)
        assert all(abs(a - b) <= MERGE_TOL for a, b in zip(want, got)), (
            f"the merge outline {got} is not the outline of the traces {want}"
        )
        wrong = _area_off(picked, made)
        assert not wrong, (
            f"the merge covers the wrong area at {len(wrong)} points away "
            f"from the outside edge of the traces, first at {wrong[0]}"
        )
        self.model.section_edit(n, kept + made)
        self.reached.add("merge touching" if touching else "merge apart")

    def new_name(self):
        if self.rng.random() < 0.5:
            return self.rng.choice(self.names)
        self.renamed += 1
        name = f"m_r{self.renamed}"
        self.names.append(name)
        return name

    def _object(self):
        shapes = self.visible()
        return self.rng.choice(shapes) if shapes else None

    def rename_object(self):
        shape = self._object()
        if shape is None:
            return
        old, new = shape.name, self.new_name()
        if old == new:
            return
        self.note(f"rename object {old} to {new}")
        self.select([shape])
        FakeTraceDialog.answer = new
        self.field.editAttributes()
        self.reached.add("rename object")
        self.model.series_edit({
            n: [s.copy(name=new) if s.name == old else s for s in shapes]
            for n, shapes in self.model.sections.items()
            if any(s.name == old for s in shapes)
        })

    def delete_object(self):
        shape = self._object()
        if shape is None:
            return
        name = shape.name
        self.note(f"delete object {name}")
        self.select([shape])
        self.field.deleteObjects()
        self.reached.add("delete object")
        self.model.series_edit({
            n: [s for s in shapes if s.name != name]
            for n, shapes in self.model.sections.items()
            if any(s.name == name for s in shapes)
        })

    def undo(self, redo=False):
        word = "redo" if redo else "undo"
        n = self.current
        choice = self.model.choice(n, redo)
        answer = None
        if choice == "ask":
            answer = self.rng.choice(["all", "section", "cancel"])
            self.recorder.linked_undo_responses[:] = [answer]
        self.note(f"{word} ({choice}{', ' + answer if answer else ''})")
        prompts = self.recorder.linked_undo_prompts
        self.window.undo(redo)
        asked = self.recorder.linked_undo_prompts - prompts
        assert asked == (choice == "ask"), (
            f"the app {'asked' if asked else 'did not ask'} whether to {word} "
            "the whole series step"
        )
        if choice is not None:
            self.reached.add(f"{word} {answer or choice}")
        if choice == "whole" or answer == "all":
            self.model.undo_whole(redo)
        elif choice == "section" or answer == "section":
            self.model.undo_section(n, redo)

    def redo(self):
        self.undo(redo=True)

    # the check
    def check(self):
        for n in sorted(self.series.sections):
            want = self.model.sections[n]
            got = self.app_shapes(n)
            unmatched = list(got)
            missing = []
            for shape in want:
                match = next((g for g in unmatched if shape.same(g)), None)
                if match is None:
                    missing.append(shape)
                else:
                    unmatched.remove(match)
            assert not missing and not unmatched, (
                f"section {n}: the model has {missing} that the app does not, "
                f"and the app has {unmatched} that the model does not"
            )
        objects = self.series.data["objects"]
        want = self.model.objects()
        got = {name: set(objects[name].traces) for name in objects}
        got = {name: snums for name, snums in got.items() if snums or name in want}
        assert got == want, "the series data lists objects on the wrong sections"


OPS = (
    ["draw"] * 6 + ["delete"] * 2 + ["move"] * 2 + ["hide"] * 2
    + ["unhide_all", "merge", "merge", "rename_traces", "rename_traces"]
    + ["rename_object", "delete_object"] + ["goto"] * 4
    + ["undo"] * 7 + ["redo"] * 4
)


@pytest.fixture
def shapes_window(qapp, shapes1_jser, qsettings_snapshot, main_window_dialogs, monkeypatch):
    """A live MainWindow on a copy of shapes1, with the attribute dialog
    answered by FakeTraceDialog. Built the way the main_window fixture
    builds its window."""
    import sys

    from PySide6.QtCore import QSettings

    from PyReconstruct.modules.gui.dialog.whats_new import APP, ORG, current_version_str
    from PyReconstruct.modules.gui.main import (
        MainWindow,
        field_widget_2_trace,
        field_widget_3_object,
    )
    from PyReconstruct.modules.gui.main.first_launch import WHATSNEW_KEY

    monkeypatch.setattr(field_widget_2_trace, "TraceDialog", FakeTraceDialog)
    monkeypatch.setattr(field_widget_3_object, "TraceDialog", FakeTraceDialog)
    QSettings(ORG, APP).setValue(WHATSNEW_KEY, current_version_str())
    excepthook = sys.excepthook
    window = MainWindow(str(shapes1_jser))
    window._captureListLayout = lambda: None
    try:
        yield window, main_window_dialogs
    finally:
        sys.excepthook = excepthook
        window.series.modified = False
        window.close()
        window.deleteLater()


def _run(shapes_window, seed, steps):
    window, recorder = shapes_window
    rng = random.Random(seed)
    run = Run(window, recorder, rng)
    try:
        run.check()
        for _ in range(steps):
            op = rng.choice(OPS)
            # undo and redo come in short runs, as they do by hand, so redo
            # reaches what the undos before it took back
            for _ in range(rng.choice([1, 1, 2, 3]) if op in ("undo", "redo") else 1):
                getattr(run, op)()
                run.check()
        window.saveAllData()
        run.field.reload()
        run.check()
    except AssertionError as error:
        steps = "\n".join(f"  {i}: {step}" for i, step in enumerate(run.history))
        pytest.fail(f"seed {seed}, after these steps:\n{steps}\n{error}", pytrace=False)
    return run


@pytest.mark.gui
@pytest.mark.parametrize("seed, reaches", FAST_SEEDS)
def test_random_edits_match_the_model(shapes_window, seed, reaches):
    run = _run(shapes_window, seed, FAST_STEPS)
    assert reaches <= run.reached, sorted(reaches - run.reached)


# two squares a merge in seed 223 joins: they overlap, so the right edge of
# the second runs inside the first; and the outline of the two together
SQUARES = [
    Shape("m", [(0.33, 0.60), (1.36, 0.60), (1.36, 1.63), (0.33, 1.63)]),
    Shape("m", [(-0.60, 1.46), (0.43, 1.46), (0.43, 2.49), (-0.60, 2.49)]),
]
UNION = [
    (0.33, 0.60), (1.36, 0.60), (1.36, 1.63), (0.43, 1.63),
    (0.43, 2.49), (-0.60, 2.49), (-0.60, 1.46), (0.33, 1.46),
]


@pytest.mark.parametrize("points, right", [
    (UNION, True),
    ([(x + 0.03, y - 0.03) for x, y in UNION], True),
    ([(x + 0.07, y) for x, y in UNION], False),
    # a notch 0.08 wide and 0.15 deep along the edge inside the union
    (UNION[:3] + [(0.47, 1.63), (0.47, 1.48), (0.39, 1.48), (0.39, 1.71), (0.43, 1.71)]
     + UNION[4:], False),
    # the same notch in an outside edge
    (UNION[:1] + [(0.81, 0.60), (0.81, 0.75), (0.89, 0.75), (0.89, 0.60)] + UNION[1:], False),
    ([(-0.60, 0.60), (1.36, 0.60), (1.36, 2.49)], False),
])
def test_merge_check_finds_a_wrong_outline(points, right):
    assert (not _area_off(SQUARES, [Shape("m", points)])) == right


@pytest.mark.gui
@pytest.mark.slow
@pytest.mark.skipif(
    "MODEL_SEEDS" not in os.environ,
    reason="many seeds take minutes; set MODEL_SEEDS (200 is the usual run)",
)
@pytest.mark.parametrize("seed", range(SLOW_SEEDS))
def test_many_random_edit_runs(shapes_window, seed):
    _run(shapes_window, seed, SLOW_STEPS)
