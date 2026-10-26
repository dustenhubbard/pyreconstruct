"""In combo trace mode, a press that barely moves is a click, however long.

Combo mode reads a click as the start of a point-by-point trace and a drag as
a scribble. A click used to count only if it lasted at most `max_click_time`
(0.15 s) or had no move event at all. A slower click with a pixel or two of
drift, from a trackpad or a hand on the mouse, became a two-point scribble and
drew nothing. Now a press whose pointer stays within `click_tolerance` pixels
of the press point starts point-by-point tracing at any length.
"""

import time

import pytest
from PySide6.QtCore import Qt

from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    CLOSEDTRACE,
    OPENTRACE,
)
from test_lasso_ends_on_tool_change_and_pinch import (
    HELD,
    UP,
    FakeMouseEvent,
    _box_around,
    _hold_then_release,
    _visible_trace,
    field_notices,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.gui

X, Y = 200, 200


def _press_drift_release(field, path, slow=True):
    """Press at (X, Y), move along `path` (offsets), release at the last one.

    `slow` puts the press past the 0.15 s single-click window.
    """
    field.mousePressEvent(FakeMouseEvent(X, Y, HELD))
    if slow:
        field.click_time = 0
    dx, dy = 0, 0
    for dx, dy in path:
        field.mouseMoveEvent(FakeMouseEvent(X + dx, Y + dy, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(X + dx, Y + dy, UP))


def _field(window, mode, trace_mode):
    field = window.field
    field.series.setOption("trace_mode", trace_mode)
    field.setMouseMode(mode)
    assert not field.is_line_tracing
    return field


def _drop_line(field):
    field.is_line_tracing = False
    field.current_trace = []
    field.deactivateMouseBoundaryTimer()


def _traces(field):
    """Every trace on the section, by name and points."""
    return sorted(
        (t.name, tuple(map(tuple, t.points)))
        for t in field.section.tracesAsList()
    )


STILL, DRIFT, DRAG = [], [(1, 0)], [(10, 0), (20, 5), (30, 10)]


@pytest.mark.parametrize("mode", [CLOSEDTRACE, OPENTRACE])
@pytest.mark.parametrize("path", [[(1, 0)], [(2, 1), (-1, 3), (4, -4)]])
def test_slow_still_press_starts_line_tracing(main_window, mode, path):
    field = _field(main_window, mode, "combo")
    _press_drift_release(field, path)
    try:
        assert field.is_line_tracing
        assert field.current_trace == [(X, Y)]
    finally:
        _drop_line(field)


def test_fast_click_with_drift_still_starts_line_tracing(main_window):
    field = _field(main_window, CLOSEDTRACE, "combo")
    _press_drift_release(field, [(30, 0)], slow=False)
    try:
        assert field.is_line_tracing
    finally:
        _drop_line(field)


@pytest.mark.parametrize("path", [[(5, 0)], [(0, -5)], [(20, 20), (0, 1)]])
def test_slow_drag_past_tolerance_scribbles(main_window, path):
    """A drag past the tolerance scribbles, even one that comes back."""
    field = _field(main_window, OPENTRACE, "combo")
    _press_drift_release(field, path)
    assert not field.is_line_tracing


def test_scribble_mode_never_starts_line_tracing(main_window):
    field = _field(main_window, CLOSEDTRACE, "scribble")
    _press_drift_release(field, [(1, 0)])
    assert not field.is_line_tracing


def test_poly_mode_starts_line_tracing_on_press(main_window):
    field = _field(main_window, CLOSEDTRACE, "poly")
    field.mousePressEvent(FakeMouseEvent(X, Y, HELD))
    try:
        assert field.is_line_tracing
    finally:
        field.mouseReleaseEvent(FakeMouseEvent(X, Y, UP))
        _drop_line(field)


@pytest.mark.parametrize("path", [[], [(1, 0)]])
def test_release_after_field_menu_does_not_start_line(
    main_window, monkeypatch, path
):
    """A right press opens the field menu; its release is no trace click.

    The menu takes the press, so no trace was started. A slow release that
    barely moved used to reach the line start with an empty trace.
    """
    monkeypatch.setattr(main_window.field_menu, "exec", lambda *a: None)
    field = _field(main_window, CLOSEDTRACE, "combo")
    field.current_trace = []
    field.mousePressEvent(FakeMouseEvent(X, Y, Qt.RightButton))
    field.click_time = 0
    for dx, dy in path:
        field.mouseMoveEvent(FakeMouseEvent(X + dx, Y + dy, Qt.RightButton))
    field.mouseReleaseEvent(FakeMouseEvent(X + 1, Y, UP))
    assert not field.is_line_tracing
    assert field.current_trace == []


@pytest.mark.parametrize("slow", [False, True], ids=["fast", "slow"])
@pytest.mark.parametrize("tool", ["usepointer_act", "useknife_act"])
def test_release_of_another_tools_press_adds_nothing(
    main_window, field_notices, tool, slow  # noqa: F811
):
    """A press made in another tool is no trace press after a tool change.

    The pointer and the knife leave their points in the trace buffer. The
    release used to start a line from one of them, or draw them as a trace.
    """
    field = _field(main_window, CLOSEDTRACE, "combo")
    getattr(main_window, tool).trigger()
    before = _traces(field)
    field.current_trace = []
    field.mousePressEvent(FakeMouseEvent(X, Y, HELD))
    field.mouseMoveEvent(FakeMouseEvent(X + 1, Y, HELD))
    field.mouseMoveEvent(FakeMouseEvent(X + 2, Y, HELD))
    assert field.current_trace[-2:] == [(X + 1, Y), (X + 2, Y)]
    main_window.usectrace_act.trigger()
    field.click_time = 0 if slow else time.time()
    field.mouseReleaseEvent(FakeMouseEvent(X + 2, Y, UP))
    try:
        assert not field.is_line_tracing
        assert len(field.section.tracesAsList()) == len(before)
        assert _traces(field) == before
        assert field.current_trace == []
        assert field_notices == []
    finally:
        _drop_line(field)


@pytest.mark.parametrize("slow", [False, True], ids=["fast", "slow"])
@pytest.mark.parametrize(
    "path", [STILL, DRIFT, DRAG], ids=["still", "drift", "drag"]
)
@pytest.mark.parametrize(
    "mode, switch",
    [(CLOSEDTRACE, "useotrace_act"), (OPENTRACE, "usectrace_act")],
    ids=["closed-to-open", "open-to-closed"],
)
def test_tool_change_mid_trace_press_adds_no_trace(
    main_window, mode, switch, path, slow
):
    """A tool change ends a trace press; its release adds nothing.

    The other trace tool used to finish the press: a drift became a two-point
    trace and a drag a scribble, in a tool the press did not start in.
    """
    field = _field(main_window, mode, "combo")
    before = _traces(field)
    field.mousePressEvent(FakeMouseEvent(X, Y, HELD))
    dx, dy = 0, 0
    for dx, dy in path:
        field.mouseMoveEvent(FakeMouseEvent(X + dx, Y + dy, HELD))
    getattr(main_window, switch).trigger()
    after_switch = list(field.current_trace)
    field.mouseMoveEvent(FakeMouseEvent(X + dx, Y + dy, HELD))
    field.click_time = 0 if slow else time.time()
    field.mouseReleaseEvent(FakeMouseEvent(X + dx, Y + dy, UP))
    try:
        assert not field.is_line_tracing
        assert len(field.section.tracesAsList()) == len(before)
        assert _traces(field) == before
        assert after_switch == []
        assert field.current_trace == []
    finally:
        _drop_line(field)


@pytest.mark.parametrize("slow", [False, True], ids=["fast", "slow"])
@pytest.mark.parametrize(
    "tool",
    ["useknife_act", "usestamp_act", "usepointer_act", "usehost_act"],
)
def test_other_tool_does_not_finish_a_trace_press(
    main_window, main_window_dialogs, field_notices, tool, slow  # noqa: F811
):
    """The tool a trace press is handed to on a tool change finishes nothing.

    It used to act on the press: the knife cut along the stroke, a stamp
    went down, the pointer selected the trace under the release.
    """
    field = _field(main_window, CLOSEDTRACE, "combo")
    trace = _visible_trace(field)
    field.section.selected_traces[:] = [trace]
    (x0, y0), (x1, _), (_, y1), _ = _box_around(field, trace)
    y = (y0 + y1) // 2
    before = _traces(field)
    field.mousePressEvent(FakeMouseEvent(x0, y, HELD))
    for x in range(x0, x1 + 1, 5):
        field.mouseMoveEvent(FakeMouseEvent(x, y, HELD))
    getattr(main_window, tool).trigger()
    if not slow:
        field.click_time = time.time()
    _hold_then_release(field, trace)
    try:
        assert len(field.section.tracesAsList()) == len(before)
        assert _traces(field) == before
        assert field.section.selected_traces == [trace]
        assert field.hosted_trace is None
        assert main_window_dialogs.dialogs == []
        assert field_notices == []
    finally:
        _drop_line(field)


@pytest.mark.parametrize(
    "path, line", [(DRIFT, True), (DRAG, False)], ids=["still", "drag"]
)
def test_reselecting_the_trace_tool_mid_press_keeps_the_press(
    main_window, path, line
):
    """Choosing the tool already in use is no tool change; the press goes on."""
    field = _field(main_window, CLOSEDTRACE, "combo")
    field.series.setOption("auto_merge", False)
    count = len(field.section.tracesAsList())
    field.mousePressEvent(FakeMouseEvent(X, Y, HELD))
    field.click_time = 0
    for dx, dy in path:
        field.mouseMoveEvent(FakeMouseEvent(X + dx, Y + dy, HELD))
    main_window.usectrace_act.trigger()
    field.mouseReleaseEvent(FakeMouseEvent(X + dx, Y + dy, UP))
    try:
        assert field.is_line_tracing is line
        assert len(field.section.tracesAsList()) == count + (not line)
    finally:
        _drop_line(field)
