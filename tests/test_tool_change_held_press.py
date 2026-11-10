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
        field.is_line_tracing, field.is_z_tracing, field.is_panzooming,
    ))


@pytest.mark.parametrize("source,target", list(permutations(TOOLS, 2)))
def test_every_tool_pair_ignores_the_old_press(
    main_window, main_window_dialogs, field_notices, local_series_settings,  # noqa: F811
    source, target,
):
    local_series_settings(main_window)
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


def test_still_pointer_press_cannot_start_a_trace(main_window, local_series_settings):
    local_series_settings(main_window)
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
    main_window, local_series_settings, source, target, line_under_way
):
    local_series_settings(main_window)
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


@pytest.fixture
def isolated_field_menu(main_window, local_series_settings, monkeypatch):
    """`field_menu` after the settings swap, which rebuilds the context menus."""
    local_series_settings(main_window)
    shown = []
    monkeypatch.setattr(
        main_window.field_menu, "exec", lambda *a, **kw: shown.append(a)
    )
    return shown


@pytest.mark.parametrize("mode", [CLOSEDTRACE, OPENTRACE])
def test_combo_menu_release_does_not_start_a_trace(
    main_window, isolated_field_menu, mode
):
    field = main_window.field
    field.series.setOption("trace_mode", "combo")
    field.setMouseMode(mode)
    field.mousePressEvent(FakeMouseEvent(200, 200, Qt.RightButton))
    assert len(isolated_field_menu) == 1
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


@pytest.mark.parametrize("source,button", [
    ("Pointer", Qt.MiddleButton),
    ("Pan/Zoom", Qt.MiddleButton),
    ("Pan/Zoom", Qt.LeftButton),
    ("Pan/Zoom", Qt.RightButton),
])
def test_tool_change_cancels_mouse_pan_or_zoom(main_window, source, button):
    field = main_window.field
    palette = main_window.mouse_palette
    palette.activateModeButton(source)
    field.generateView()
    original_window = list(field.series.window)
    original_image = field.field_pixmap.toImage()
    field.mousePressEvent(FakeMouseEvent(200, 200, button))
    field.mouseMoveEvent(FakeMouseEvent(280, 260, button))
    assert field.is_panzooming
    assert field.field_pixmap.toImage() != original_image

    palette.activateModeButton("Closed Trace")

    assert not field.is_panzooming
    assert field.series.window == original_window
    assert field.field_pixmap.toImage() == original_image
    before = _state(field)
    field.mouseMoveEvent(FakeMouseEvent(320, 280, button))
    field.mouseReleaseEvent(FakeMouseEvent(320, 280, button=button))
    assert _state(field) == before
    assert field.field_pixmap.toImage() == original_image

    # The next middle-button drag pans from its own press.
    field.mousePressEvent(FakeMouseEvent(200, 200, Qt.MiddleButton))
    field.mouseMoveEvent(FakeMouseEvent(240, 220, Qt.MiddleButton))
    field.mouseReleaseEvent(FakeMouseEvent(240, 220, button=Qt.MiddleButton))
    x, y, width, height = original_window
    assert field.series.window == pytest.approx([
        x - 40 * width / field.pixmap_dim[0],
        y + 20 * height / field.pixmap_dim[1],
        width, height,
    ])
    assert not field.is_panzooming


@pytest.mark.parametrize("source,button", [
    ("Pointer", Qt.MiddleButton),
    ("Pan/Zoom", Qt.LeftButton),
    ("Pan/Zoom", Qt.RightButton),
])
def test_reselecting_tool_keeps_mouse_pan_or_zoom(main_window, source, button):
    field = main_window.field
    palette = main_window.mouse_palette
    palette.activateModeButton(source)
    original_window = list(field.series.window)
    field.mousePressEvent(FakeMouseEvent(200, 200, button))
    field.mouseMoveEvent(FakeMouseEvent(280, 260, button))
    preview = field.field_pixmap.toImage()

    palette.activateModeButton(source)

    assert field.is_panzooming
    assert field.field_pixmap.toImage() == preview
    field.mouseReleaseEvent(FakeMouseEvent(280, 260, button=button))
    assert not field.is_panzooming
    assert field.series.window != original_window


@pytest.mark.parametrize("gesture", ["pinch", "wheel"])
def test_tool_change_preserves_independent_zoom(main_window, gesture):
    field = main_window.field
    original_window = list(field.series.window)
    field.panzoomPress(200, 200)
    if gesture == "pinch":
        field.is_gesturing = True
    else:
        main_window.is_zooming = True
    field.panzoomMove(zoom_factor=1.5)
    preview = field.field_pixmap.toImage()

    main_window.mouse_palette.activateModeButton("Closed Trace")

    assert field.is_panzooming
    assert field.field_pixmap.toImage() == preview
    assert field.series.window == original_window
    field.panzoomRelease(zoom_factor=1.5)
    field.is_gesturing = False
    main_window.is_zooming = False
    assert not field.is_panzooming
    assert field.series.window[2:] == pytest.approx([
        original_window[2] / 1.5, original_window[3] / 1.5,
    ])


@pytest.mark.parametrize("source", ["Closed Trace", "Open Trace", "Knife", "Stamp", "Host"])
def test_fresh_pointer_lasso_selects_only_what_it_encloses(
    main_window, local_series_settings, source
):
    local_series_settings(main_window)
    field = main_window.field
    palette = main_window.mouse_palette
    field.series.setOption("trace_mode", "combo")
    field.series.setOption("pointer", ["rect", "inc"])
    field.tracing_trace = Trace("abandoned_stroke", (255, 0, 255))
    _add_square(field, "outside", 240, 180, 280, 220)
    _add_square(field, "inside", 360, 310, 390, 340)
    field.section.selected_traces.clear()
    palette.activateModeButton(source)
    if source == "Host":
        # A link under way: the first click picked the trace to host.
        field.mousePressEvent(FakeMouseEvent(260, 180, HELD))
        field.mouseReleaseEvent(FakeMouseEvent(260, 180))
        assert field.current_trace
        palette.activateModeButton("Pointer")
    else:
        field.mousePressEvent(FakeMouseEvent(150, 150, HELD))
        field.click_time = 0
        field.mouseMoveEvent(FakeMouseEvent(180, 160, HELD))
        palette.activateModeButton("Pointer")
        field.mouseReleaseEvent(FakeMouseEvent(180, 160))
    assert field.current_trace == []
    assert field.hosted_trace is None

    field.mousePressEvent(FakeMouseEvent(350, 300, HELD))
    # Within the click tolerance, so the lasso keeps this point.
    field.mouseMoveEvent(FakeMouseEvent(351, 300, HELD))
    field.click_time = 0
    field.mouseMoveEvent(FakeMouseEvent(400, 350, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(400, 350))

    assert [trace.name for trace in field.section.selected_traces] == ["inside"]


@pytest.mark.parametrize("points", [1, 2])
def test_unfinished_ztrace_stays_out_of_a_fresh_pointer_lasso(
    main_window, local_series_settings, points
):
    local_series_settings(main_window)
    field = main_window.field
    palette = main_window.mouse_palette
    field.series.setOption("pointer", ["rect", "inc"])
    field.tracing_trace = Trace("kept_ztrace", (255, 0, 255))
    _add_square(field, "outside", 240, 180, 280, 220)
    _add_square(field, "inside", 360, 310, 390, 340)
    field.section.selected_traces.clear()
    palette.activateModeButton("Ztool")
    for i in range(points):
        field.mousePressEvent(FakeMouseEvent(150 + 20 * i, 150 + 20 * i, HELD))
        if i < points - 1:
            field.mouseReleaseEvent(FakeMouseEvent(150 + 20 * i, 150 + 20 * i))
    kept = list(field.current_ztrace)

    # The last Ztool press is still held when the tool changes.
    palette.activateModeButton("Pointer")
    field.mouseReleaseEvent(FakeMouseEvent(170, 170))
    assert field.current_trace == []
    field.mousePressEvent(FakeMouseEvent(350, 300, HELD))
    field.mouseMoveEvent(FakeMouseEvent(351, 300, HELD))
    field.click_time = 0
    field.mouseMoveEvent(FakeMouseEvent(400, 350, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(400, 350))
    assert [trace.name for trace in field.section.selected_traces] == ["inside"]

    # Back in Ztool, the z-trace goes on from its own points.
    palette.activateModeButton("Ztool")
    assert field.current_ztrace == kept
    field.mousePressEvent(FakeMouseEvent(200, 200, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(200, 200))
    field.mousePressEvent(FakeMouseEvent(200, 200, Qt.RightButton))
    field.mouseReleaseEvent(FakeMouseEvent(200, 200))
    saved = field.series.ztraces["kept_ztrace"].points
    assert saved[:points] == kept
    assert len(saved) == points + 1
    assert not field.is_z_tracing


@pytest.mark.parametrize("held", [False, True])
def test_tool_change_ends_a_host_link_under_way(
    main_window, local_series_settings, held
):
    local_series_settings(main_window)
    field = main_window.field
    palette = main_window.mouse_palette
    _add_square(field, "old_hosted", 240, 180, 280, 220)
    _add_square(field, "new_hosted", 360, 310, 390, 340)
    field.section.selected_traces.clear()
    palette.activateModeButton("Host")
    field.mousePressEvent(FakeMouseEvent(260, 180, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(260, 180))
    assert field.hosted_trace.name == "old_hosted"
    hosts = field.series.host_tree.getDict()

    if held:
        field.mousePressEvent(FakeMouseEvent(350, 300, HELD))
    palette.activateModeButton("Pointer")
    if held:
        field.mouseReleaseEvent(FakeMouseEvent(350, 300))
    palette.activateModeButton("Host")
    # This click starts a new link instead of finishing the old one.
    field.mousePressEvent(FakeMouseEvent(375, 310, HELD))
    field.mouseReleaseEvent(FakeMouseEvent(375, 310))

    assert field.hosted_trace.name == "new_hosted"
    assert field.series.host_tree.getDict() == hosts
