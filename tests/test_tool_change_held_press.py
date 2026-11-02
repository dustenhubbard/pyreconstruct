"""A tool change cannot transfer a held press to the new tool."""

from copy import deepcopy
from itertools import permutations

import pytest
from PySide6.QtCore import Qt

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.gui.main.field_widget_5_mouse import (
    CLOSEDTRACE,
    OPENTRACE,
    POINTER,
)
from test_lasso_ends_on_tool_change_and_pinch import (
    HELD,
    FakeMouseEvent,
    _add_square,
    field_menu,  # noqa: F401  (fixture)
    field_notices,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.gui

TOOLS = (
    "Pointer", "Pan/Zoom", "Knife", "Scissors", "Closed Trace", "Open Trace",
    "Stamp", "Grid", "Flag", "Host", "Ztool", "ROI mode",
)


@pytest.fixture(autouse=True)
def roi_tool(monkeypatch):
    monkeypatch.setenv("PYRECON_ROI_MODE", "1")


def _state(field):
    return deepcopy((
        field.section.getDict(),
        [trace.name for trace in field.section.selected_traces],
        {name: trace.getDict() for name, trace in field.series.ztraces.items()},
        field.series.host_tree.getDict(),
        field.series.window,
        field.roi_box_on, field.roi_box_center, field.roi_box_size,
        field.hosted_trace.name if field.hosted_trace else None,
        field.current_trace, field.current_ztrace,
        field.is_line_tracing, field.is_z_tracing,
    ))


@pytest.mark.parametrize("source,target", list(permutations(TOOLS, 2)))
def test_every_tool_pair_ignores_the_old_press(
    main_window, main_window_dialogs, field_notices, source, target  # noqa: F811
):
    field = main_window.field
    palette = main_window.mouse_palette
    field.series.setOption("trace_mode", "combo")
    field.series.setOption("auto_merge", False)
    field.series.setOption("roll_average", False)
    field.series.setOption("grid", [1, 1, 1, 1, 1, 1])
    field.tracing_trace = Trace("tool_change", (255, 0, 255))
    # The destination stroke crosses this trace, so Knife and Host have a
    # real target. The source press is outside it, including for Scissors.
    _add_square(field, "target", 240, 180, 280, 220)
    field.section.selected_traces.clear()
    palette.activateModeButton(source)
    assert field.mouse_mode == TOOLS.index(source)
    field.mousePressEvent(FakeMouseEvent(200, 200, HELD))
    field.max_click_time = 60
    field.mouseMoveEvent(FakeMouseEvent(210, 200, HELD))
    palette.activateModeButton(target)
    assert field.mouse_mode == TOOLS.index(target)
    before = _state(field)
    dialogs_before = list(main_window_dialogs.dialogs)
    notices_before = list(field_notices)

    field.click_time = 0
    for x in (230, 250, 280):
        field.mouseMoveEvent(FakeMouseEvent(x, 200, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(280, 200))

    assert _state(field) == before
    assert main_window_dialogs.dialogs == dialogs_before
    assert field_notices == notices_before

    # A new press is accepted after the old one ends.
    palette.activateModeButton("ROI mode")
    field.mousePressEvent(FakeMouseEvent(350, 300, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(350, 300))
    assert field.roi_box_on


def test_still_pointer_press_cannot_start_a_trace(main_window):
    field = main_window.field
    field.series.setOption("trace_mode", "combo")
    field.setMouseMode(POINTER)
    field.mousePressEvent(FakeMouseEvent(200, 200, HELD))
    field.setMouseMode(CLOSEDTRACE)
    field.mouseReleaseEvent(FakeMouseEvent(200, 200))
    assert not field.is_line_tracing
    assert field.current_trace == []


@pytest.mark.parametrize("source,target", [(CLOSEDTRACE, OPENTRACE), (OPENTRACE, CLOSEDTRACE)])
@pytest.mark.parametrize("line_under_way", [False, True])
def test_trace_tool_change_does_not_reuse_a_still_or_line_press(
    main_window, source, target, line_under_way
):
    field = main_window.field
    field.series.setOption("trace_mode", "combo")
    field.series.setOption("auto_merge", False)
    field.setMouseMode(source)
    if line_under_way:
        for x in (150, 170):
            field.mousePressEvent(FakeMouseEvent(x, 150, HELD))
            field.mouseReleaseEvent(FakeMouseEvent(x, 150))
    field.mousePressEvent(FakeMouseEvent(200, 200, HELD))
    field.setMouseMode(target)
    before = _state(field)
    field.mouseReleaseEvent(FakeMouseEvent(200, 200))
    assert not field.is_line_tracing
    assert _state(field) == before


@pytest.mark.parametrize("mode", [CLOSEDTRACE, OPENTRACE])
def test_combo_menu_release_does_not_start_a_trace(
    main_window, field_menu, mode  # noqa: F811
):
    field = main_window.field
    field.series.setOption("trace_mode", "combo")
    field.setMouseMode(mode)
    field.mousePressEvent(FakeMouseEvent(200, 200, Qt.RightButton))
    assert len(field_menu) == 1
    field.mouseReleaseEvent(FakeMouseEvent(200, 200))
    assert not field.is_line_tracing
    assert field.current_trace == []


@pytest.mark.parametrize("target", [tool for tool in TOOLS if tool != "Ztool"])
def test_unfinished_ztrace_survives_a_tool_change_while_held(main_window, target):
    field = main_window.field
    palette = main_window.mouse_palette
    field.tracing_trace = Trace("kept_ztrace", (255, 0, 255))
    palette.activateModeButton("Ztool")
    field.mousePressEvent(FakeMouseEvent(150, 150, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(150, 150))
    field.mousePressEvent(FakeMouseEvent(170, 170, HELD))
    points = list(field.current_ztrace)
    assert len(points) == 2

    palette.activateModeButton(target)
    field.mouseMoveEvent(FakeMouseEvent(200, 200, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(200, 200))
    palette.activateModeButton("Ztool")
    field.mousePressEvent(FakeMouseEvent(200, 200, Qt.RightButton))
    field.mouseReleaseEvent(FakeMouseEvent(200, 200))

    assert field.series.ztraces["kept_ztrace"].points == points
    assert not field.is_z_tracing


@pytest.mark.parametrize("target", ["Closed Trace", "Knife", "Stamp", "Host", "Pan/Zoom"])
@pytest.mark.parametrize("button", [Qt.MiddleButton, Qt.RightButton, Qt.XButton1])
def test_secondary_button_cannot_restore_a_transferred_press(
    main_window, field_menu, target, button  # noqa: F811
):
    field = main_window.field
    field.closed_trace_shape = "rect"
    field.mousePressEvent(FakeMouseEvent(200, 200, HELD))
    main_window.mouse_palette.activateModeButton(target)
    before = _state(field)
    field.mousePressEvent(FakeMouseEvent(220, 220, HELD | button, button=button))
    field.mouseMoveEvent(FakeMouseEvent(240, 240, HELD | button))
    field.mouseReleaseEvent(FakeMouseEvent(240, 240, HELD, button=button))
    field.mouseMoveEvent(FakeMouseEvent(250, 250, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(250, 250))
    assert _state(field) == before
    assert field_menu == []
