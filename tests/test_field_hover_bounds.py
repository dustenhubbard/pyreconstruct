"""The hover lookup skips far traces by the store's bounds and finds the same trace.

paintText asks the trace layer for the closest trace on every paint. With the
bounds of each trace from the section's store, findClosest drops the traces
whose box misses the search window before it reads their points. The answer
must not change: the same trace (the same object, ties included) at every
cursor, and after an edit, an undo, a hide or show, a palette paste and a
section change.
"""

import math
import random

import numpy as np
import pytest

from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Trace, Transform
from PyReconstruct.modules.datatypes import section as section_module


pytestmark = pytest.mark.gui

FIELD_SIZE = (480, 320)
NAME = "hover-bounds"
CLEAR = (6, 4)


@pytest.fixture
def field(main_window):
    """The field at a fixed size over a section of dense, mixed traces."""
    field = main_window.field
    series = main_window.series
    # options set here live in the settings store; a store of this series'
    # own keeps them from reaching later tests
    series.setSettingsStore(DictSettingsStore())
    try:
        field.setFixedSize(*FIELD_SIZE)
        main_window.resize(FIELD_SIZE[0] + 600, FIELD_SIZE[1] + 400)
        QApplication.processEvents()
        series.setOption("show_ztraces", False)
        series.setOption("show_flags", "none")
        # the windows below are in trace units
        field.section.tforms[series.alignment] = Transform.identity()
        field.test_traces = _fill(field.section, random.Random(1003))
        # an undo state with these traces, so an undo in a test stops there
        field.saveState()
        yield field
    finally:
        series.setSettingsStore(None)


def _circle(x, y, r, k):
    return [
        (x + r * math.cos(t), y + r * math.sin(t))
        for t in (j * 2 * math.pi / k for j in range(k))
    ]


def _fill(section, rng):
    # only these traces: the fixture series' own would crowd the spots below
    for trace in section.tracesAsList():
        section.removeTrace(trace, log_event=False)
    ours = []

    def add(trace):
        section.addTrace(trace, log_event=False)
        ours.append(trace)
        return trace

    i = 0
    while i < 400:
        x, y, r = rng.uniform(0, 12), rng.uniform(0, 8), rng.uniform(0.01, 1.5)
        # a clear disk around CLEAR, where the tests below place their traces
        if math.dist((x, y), CLEAR) < r + 2:
            continue
        trace = Trace(f"{NAME}-{i % 25}", (rng.randrange(256), 90, 200), i % 9 != 0)
        points = _circle(x, y, r, rng.randrange(3, 60))
        if i % 13 == 0:
            # integer points, as a trace drawn on screen can carry
            points = [(round(px), round(py)) for px, py in points]
        trace.points = points
        trace.negative = i % 7 == 0
        trace.fill_mode = (
            ("transparent", "always"),
            ("solid", "always"),
            ("none", "none"),
        )[i % 3]
        trace.hidden = i % 11 == 5
        add(trace)
        i += 1
    # exact copies at one place, filled and not: a tie the first must win
    for fill in (("transparent", "always"), ("transparent", "always"), ("none", "none")):
        trace = Trace(f"{NAME}-tie", (10, 200, 10))
        trace.points = _circle(6, 4, 0.7, 24)
        trace.fill_mode = fill
        add(trace)
    # long thin lines whose box is wide, open and closed
    for closed, (x0, y0, x1, y1) in ((False, (-1, 1.1, 13, 1.2)), (True, (9.9, -1, 10.0, 9))):
        trace = Trace(f"{NAME}-line", (255, 0, 0), closed)
        trace.points = [(x0, y0), (x1, y1)]
        add(trace)
    return ours


def _rotate_shear(angle, shear, dx, dy):
    c, s = math.cos(angle), math.sin(angle)
    return Transform([c, -s + shear, dx, s, c, dy])


TFORMS = {
    "identity": Transform.identity(),
    "rotate-shear": _rotate_shear(0.5, 0.3, 0.4, -0.6),
}


def _windows(field):
    w, h = FIELD_SIZE
    mag = field.section.mag
    return {
        "whole": [-1.5, -1.5, 15, 15 * h / w],
        "mid": [4.5, 2.5, 3, 3 * h / w],
        "1to1": [6 - w * mag / 2, 4 - h * mag / 2, w * mag, h * mag],
        "empty": [500, 500, 2, 2 * h / w],
    }


def _sweep_windows(field):
    """The views of the sweep, away from the clear disk."""
    w, h = FIELD_SIZE
    mag = field.section.mag
    cx, cy = 2.5, 2.5
    return {
        "whole": [-1.5, -1.5, 15, 15 * h / w],
        "mid": [cx - 1.5, cy - 1.5 * h / w, 3, 3 * h / w],
        "1to1": [cx - w * mag / 2, cy - h * mag / 2, w * mag, h * mag],
        "empty": [500, 500, 2, 2 * h / w],
    }


def _draw(field, window):
    field.series.window = list(window)
    field.generateView()


def _ask(field, x, y, bounds=True):
    """What the hover finds at a screen point: with the store's bounds, or as
    before them (findClosest then reads every trace's points)."""
    layer = field.section_layer
    if bounds:
        return layer.getTrace(x, y)
    layer._rawBounds = lambda traces: None
    try:
        return layer.getTrace(x, y)
    finally:
        del layer._rawBounds


def _same(field, x, y):
    new = _ask(field, x, y)
    old = _ask(field, x, y, bounds=False)
    assert new[1] == old[1], (x, y)
    assert new[0] is old[0], (x, y)
    return new


def _cursors(field, n=24):
    w, h = FIELD_SIZE
    grid = [(int((i + 0.5) * w / n), int((j + 0.5) * h / n)) for j in range(n) for i in range(n)]
    layer = field.section_layer
    # every trace's first point on screen, where the answers crowd
    near = [tuple(layer.traceToPix(t)[0]) for t in field.test_traces]
    return grid + near


def _screen(field, x, y):
    """The screen point of a field point."""
    layer = field.section_layer
    return layer.pointToPix((x, y), apply_tform=False)


@pytest.mark.parametrize("show_all", [False, True])
@pytest.mark.parametrize("tform", TFORMS)
@pytest.mark.parametrize("view", ["whole", "mid", "1to1", "empty"])
def test_every_cursor_finds_the_same_trace(field, monkeypatch, view, tform, show_all):
    section = field.section
    section.tforms[field.series.alignment] = TFORMS[tform]
    field.show_all_traces = show_all
    _draw(field, _sweep_windows(field)[view])

    calls = {"n": 0}
    real = section_module.getDistanceFromTrace

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(section_module, "getDistanceFromTrace", counting)
    found = set()
    new_calls = old_calls = 0
    for x, y in _cursors(field):
        calls["n"] = 0
        new = _ask(field, x, y)
        new_calls += calls["n"]
        calls["n"] = 0
        old = _ask(field, x, y, bounds=False)
        old_calls += calls["n"]
        assert new[1] == old[1], (x, y)
        assert new[0] is old[0], (x, y)
        found.add(id(new[0]))
    # same number of exact tests: the bounds drop only traces the loop drops
    assert new_calls == old_calls
    # not an empty comparison
    if view == "empty":
        assert not field.section_layer.traces_in_view
    else:
        assert len(found) > {"whole": 40, "mid": 10, "1to1": 2}[view]


def test_the_bounds_skip_reading_far_traces(field, monkeypatch):
    """The point of the change: at the whole field, a hover reads the points
    of only the traces near the cursor."""
    _draw(field, _windows(field)["whole"])
    layer = field.section_layer
    assert len(layer.traces_in_view) > 300
    read = []
    real_zip = zip

    def counting_zip(*a):
        read.append(1)
        return real_zip(*a)

    monkeypatch.setattr(section_module, "zip", counting_zip, raising=False)
    x, y = _screen(field, 6, 4)
    _ask(field, x, y)
    with_bounds = len(read)
    read.clear()
    _ask(field, x, y, bounds=False)
    assert with_bounds < len(read) / 4


def test_the_tie_goes_to_the_first_copy(field):
    _draw(field, _windows(field)["mid"])
    ties = [t for t in field.test_traces if t.name == f"{NAME}-tie"]
    # on the shared edge of the three copies, and in their middle
    for fx, fy in ((6.7, 4), (6, 4)):
        trace, kind = _same(field, *_screen(field, fx, fy))
        assert kind == "trace"
        assert trace is ties[0]


def _far_trace(field):
    """A small trace on screen at the whole field, far from (6, 4)."""
    for trace in field.test_traces:
        xs = [p[0] for p in trace.points]
        ys = [p[1] for p in trace.points]
        if (
            not trace.hidden and len(set(trace.points)) > 4 and
            max(xs) - min(xs) < 0.3 and
            (min(xs) > 9 or max(xs) < 3) and len(trace.points) > 4
        ):
            return trace
    raise AssertionError("no small far trace")


def test_a_moved_trace_is_found_where_it_went(field):
    """translateTraces rewrites the points in place: the same trace and list.
    The store's generation moves, so its bounds are read again."""
    _draw(field, _windows(field)["whole"])
    trace = _far_trace(field)
    target = (6.0, 5.6)
    x, y = _screen(field, *target)
    assert _same(field, x, y)[0] is not trace
    cx = sum(p[0] for p in trace.points) / len(trace.points)
    cy = sum(p[1] for p in trace.points) / len(trace.points)
    points = trace.points
    original = list(points)
    field.section.selected_traces = [trace]
    field.translate(target[0] - cx, target[1] - cy)
    assert trace.points is points
    assert _same(field, x, y)[0] is trace

    # and back again on undo, the old place first answering it again
    field.undoState()
    moved_back = _same(field, x, y)[0]
    assert moved_back is not trace
    restored = [t for t in field.section.tracesAsList() if t.name == trace.name
                and len(t.points) == len(original) and np.allclose(t.points, original)]
    assert restored
    px, py = _screen(field, *restored[0].points[0])
    assert _same(field, px, py)[0] is restored[0]

    # redo puts it back under the cursor
    field.undoState(redo=True)
    found = _same(field, x, y)[0]
    assert found is not None and found.name == trace.name


def test_a_moved_trace_is_found_before_a_redraw(field):
    _draw(field, _windows(field)["whole"])
    trace = _far_trace(field)
    target = (6.0, 5.6)
    cx = sum(p[0] for p in trace.points) / len(trace.points)
    cy = sum(p[1] for p in trace.points) / len(trace.points)
    field.section.selected_traces = [trace]
    # the section's edit alone, with no generateView after it
    field.section.translateTraces(target[0] - cx, target[1] - cy, log_event=False)
    field.section.selected_traces = []
    got = _same(field, *_screen(field, *target))[0]
    assert got is trace


def test_points_replaced_outside_the_section_are_read_from_the_trace(field):
    """A trace given a new list of another length, with no section edit,
    takes its bounds from its own points, as the draw's cull does."""
    _draw(field, _windows(field)["whole"])
    trace = _far_trace(field)
    target = (6.0, 5.6)
    trace.points = _circle(*target, 0.1, len(trace.points) + 3)
    try:
        assert _same(field, *_screen(field, *target))[0] is trace
    finally:
        field.section.resyncColumnarStore()


def test_hide_and_show(field):
    _draw(field, _windows(field)["mid"])
    ties = [t for t in field.test_traces if t.name == f"{NAME}-tie"]
    # a point all three copies share
    xy = _screen(field, 6.7, 4)
    field.section.selected_traces = [ties[0]]
    field.hideTraces()
    assert _same(field, *xy)[0] is ties[1]
    # hidden without a redraw: the loop reads the flag itself
    field.section.hideTraces([ties[1]])
    assert _same(field, *xy)[0] is ties[2]
    field.section.selected_traces = [ties[0], ties[1]]
    field.hideTraces(hide=False)
    assert _same(field, *xy)[0] is ties[0]
    # show all draws and finds the hidden traces
    hidden = [t for t in field.test_traces if t.hidden]
    assert hidden
    field.show_all_traces = True
    field.generateView()
    p = hidden[0].points[0]
    trace, _ = _same(field, *_screen(field, *p))
    assert trace is not None


def test_a_palette_paste_is_found_by_its_new_name(field):
    """Pasting a palette trace's attributes replaces each trace with a copy;
    the copy has no store row of its own until the store says so."""
    _draw(field, _windows(field)["mid"])
    ties = [t for t in field.test_traces if t.name == f"{NAME}-tie"]
    xy = _screen(field, 6, 4)
    palette_trace = Trace("palette-pick", (1, 2, 3))
    palette_trace.fill_mode = ("transparent", "always")
    field.clipboard = [palette_trace]
    field.section.selected_traces = list(ties)
    field.pasteAttributes()
    trace, kind = _same(field, *xy)
    assert kind == "trace" and trace.name == "palette-pick"
    assert trace not in ties
    field.undoState()
    trace, _ = _same(field, *xy)
    assert trace.name == f"{NAME}-tie"


def test_a_deleted_trace_is_not_found(field):
    _draw(field, _windows(field)["mid"])
    ties = [t for t in field.test_traces if t.name == f"{NAME}-tie"]
    xy = _screen(field, 6, 4)
    field.section.removeTrace(ties[0], log_event=False)
    field.generateView()
    assert _same(field, *xy)[0] is ties[1]


def test_a_section_change_finds_the_new_sections_traces(field):
    series = field.series
    first = field.section.n
    others = [n for n in sorted(series.sections) if n != first]
    assert others
    _draw(field, _windows(field)["mid"])
    xy = _screen(field, 6, 4)
    assert _same(field, *xy)[0] in field.test_traces

    field.changeSection(others[0])
    QApplication.processEvents()
    other = field.section
    assert other.n == others[0]
    other.tforms[series.alignment] = Transform.identity()
    for t in other.tracesAsList():
        other.removeTrace(t, log_event=False)
    trace = Trace("other-section", (5, 5, 5))
    trace.points = _circle(6, 4, 0.5, 12)
    trace.fill_mode = ("transparent", "always")
    other.addTrace(trace, log_event=False)
    field.series.window = _windows(field)["mid"]
    field.generateView()
    found, _ = _same(field, *xy)
    assert found is trace
    for x, y in _cursors(field, n=12)[:144]:
        hit = _same(field, x, y)[0]
        assert hit is None or hit not in field.test_traces

    field.changeSection(first)
    QApplication.processEvents()
    field.series.window = _windows(field)["mid"]
    field.generateView()
    assert _same(field, *xy)[0] in field.test_traces


def test_a_section_without_a_store_still_finds(field, monkeypatch):
    _draw(field, _windows(field)["mid"])
    xy = _screen(field, 6, 4)
    expected = _same(field, *xy)
    monkeypatch.setattr(field.section, "_columns", None)
    layer = field.section_layer
    assert layer._rawBounds(layer.traces_in_view) is None
    assert _ask(field, *xy)[0] is expected[0]


def test_bounds_keep_a_nan_box_and_an_edge_touch(field, monkeypatch):
    """findClosest's own array test: a NaN box and a box that ends exactly
    on the search window's edge still reach the exact test, as the loop
    keeps them; a box clear of the window does not."""
    section = field.section
    section.tforms[field.series.alignment] = Transform.identity()
    trace = Trace("edge", (0, 0, 0))
    trace.points = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]
    radius = 0.5
    # the trace's xmin sits exactly on the search window's right edge
    fx = 1.0 - (radius + 2 * section.mag)
    tested = []
    real = section_module.getDistanceFromTrace

    def counting(*a, **k):
        tested.append(1)
        return real(*a, **k)

    monkeypatch.setattr(section_module, "getDistanceFromTrace", counting)
    boxes = {
        None: 1,
        "nan": 1,
        "edge": 1,
        "far": 0,
    }
    arrays = {
        None: None,
        "nan": np.full((1, 4), np.nan),
        "edge": np.array([[1.0, 1.0, 2.0, 2.0]]),
        "far": np.array([[50.0, 50.0, 51.0, 51.0]]),
    }
    for name, expected in boxes.items():
        tested.clear()
        section.findClosest(
            fx, 1.5, radius=radius, traces_in_view=[trace], trace_bounds=arrays[name]
        )
        assert len(tested) == expected, name
