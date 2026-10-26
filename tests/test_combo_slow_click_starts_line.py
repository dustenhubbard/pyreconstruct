"""In combo trace mode, a press that barely moves is a click, however long.

Combo mode reads a click as the start of a point-by-point trace and a drag as
a scribble. A click used to count only if it lasted at most `max_click_time`
(0.15 s) or had no move event at all. A slower click with a pixel or two of
drift, from a trackpad or a hand on the mouse, became a two-point scribble and
drew nothing. Now a press whose pointer stays within `click_tolerance` pixels
of the press point starts point-by-point tracing at any length.

Driven against a real `MainWindow` and `FieldWidget`, through the field's own
`mousePressEvent`, `mouseMoveEvent` and `mouseReleaseEvent`.
"""

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
