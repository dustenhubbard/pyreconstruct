"""Per-user palette dimensions control the real buttons' placement."""

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest

from PyReconstruct.modules.backend.settings_store import QSettingsStore
from PyReconstruct.modules.constants.settings_domain import shared_domain
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def palette(main_window, local_series_settings, monkeypatch):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    monkeypatch.setattr(mouse_palette, "load_palette_positions", lambda settings: {})
    main_window.field.setGeometry(0, 30, 1280, 662)
    main_window.mouse_palette.reset()
    return main_window.mouse_palette


def test_trace_buttons_use_the_requested_row_length(main_window, palette):
    main_window.series.setOption("trace_palette_per_row", 5)
    palette.reset()
    palette.resize()
    buttons = palette.palette_buttons
    assert len({b.x() for b in buttons}) == 5
    assert len({b.y() for b in buttons}) == 4


def test_tools_use_the_requested_columns(main_window, palette):
    main_window.series.setOption("tool_palette_cols", 3)
    palette.reset()
    palette.resize()
    buttons = [b for b, _, _ in palette.mode_buttons.values()]
    assert len({b.x() for b in buttons}) == 3
    assert len({b.y() for b in buttons}) == 4


def test_an_exact_fit_tool_row_can_still_be_dragged_vertically(main_window, palette):
    main_window.series.setOption("tool_palette_cols", 11)
    palette.reset()
    main_window.field.setGeometry(0, 30, 540, 662)
    palette.resize()
    x, y = palette.getButtonCoords("mode")
    palette.moveButton(10, 10, "mode")
    palette.resize()
    assert palette.getButtonCoords("mode") == pytest.approx((x, y + 10))


def test_wide_trace_palettes_do_not_cover_default_controls(main_window, palette, qapp):
    main_window.series.setOption("trace_palette_per_row", 20)
    palette.reset()
    main_window.resize(1000, 800)
    main_window.show()
    qapp.processEvents()
    main_window.field.setGeometry(0, 30, 800, 662)
    palette.resize()
    traces = [*palette.palette_buttons, *palette.palette_side_buttons]
    tools = [b for b, _, _ in palette.mode_buttons.values()]
    sliders = [w for pair in palette.bc_widgets for w in pair]
    groups = [traces, tools, sliders, palette.inc_buttons, [palette.sb]]
    for i, group in enumerate(groups):
        for button in group:
            assert main_window.field.geometry().contains(button.geometry())
            assert main_window.childAt(button.geometry().center()) is button
            for other_group in groups[i + 1:]:
                assert all(not button.geometry().intersects(other.geometry()) for other in other_group)


@pytest.mark.parametrize("trace_x,trace_y,mode_x,mode_y", [
    (0.51, 0.01, 0.99, 0.01),
    (0.51, 0.99, 0.99, 0.99),
    (0.01, 0.01, 0.01, 0.01),
    (0.99, 0.99, 0.99, 0.99),
    (0.5, 0.5, 0.5, 0.5),
])
def test_saved_positions_keep_both_palettes_reachable(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path,
        trace_x, trace_y, mode_x, mode_y):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    positions = {
        f"{group}_{axis}": value
        for group, xy in mouse_palette.DEFAULT_POSITIONS.items()
        for axis, value in zip(("x", "y"), xy)
    }
    positions.update(trace_x=trace_x, trace_y=trace_y, mode_x=mode_x, mode_y=mode_y)
    mouse_palette.save_palette_positions(settings, positions)
    main_window.resize(1280, 800)
    main_window.show()
    qapp.processEvents()
    palette = main_window.mouse_palette
    palette.reset()

    series = main_window.series
    series.setOption("trace_palette_per_row", 20)
    series.setOption("tool_palette_cols", 12)
    palette.reset()
    for window in [(1280, 800), (800, 600), (1280, 800)]:
        main_window.resize(*window)
        qapp.processEvents()
        palette.resize()
        widgets = [
            *palette.palette_buttons, *palette.palette_side_buttons,
            *(b for b, _, _ in palette.mode_buttons.values()),
            *palette.inc_buttons, *(w for pair in palette.bc_widgets for w in pair),
            palette.label, palette.sb,
        ]
        for widget in widgets:
            assert not widget.isHidden()
            assert main_window.field.geometry().contains(widget.geometry())
            assert main_window.childAt(widget.geometry().center()) is widget

    for i, button in enumerate(palette.palette_buttons):
        QTest.mouseClick(main_window.childAt(button.geometry().center()), Qt.LeftButton)
        assert series.palette_index[1] == i
    for button, mode, _ in palette.mode_buttons.values():
        QTest.mouseClick(main_window.childAt(button.geometry().center()), Qt.LeftButton)
        assert main_window.field.mouse_mode == mode
    assert series.getOption("trace_palette_per_row") == 20
    assert series.getOption("tool_palette_cols") == 12
    assert mouse_palette.load_palette_positions(settings) == positions
    assert {key: getattr(palette, key) for key in positions} == positions


@pytest.mark.parametrize("group,wrapped_x", [("inc", 0.94), ("bc", 0.94), ("sb", 0.7)])
@pytest.mark.parametrize("layout", ["configured", "wrapped"])
def test_saved_controls_stay_reachable_after_layout_changes(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path, group, wrapped_x, layout):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    positions = {
        f"{group}_x": 0.7 if layout == "configured" else wrapped_x,
        f"{group}_y": 0.01,
    }
    mouse_palette.save_palette_positions(settings, positions)
    main_window.resize(1280, 800)
    main_window.show()
    qapp.processEvents()
    palette = main_window.mouse_palette
    palette.reset()

    def assert_reachable():
        widgets = [
            *palette.palette_buttons, *palette.palette_side_buttons,
            *(b for b, _, _ in palette.mode_buttons.values()),
            *palette.inc_buttons, *(w for pair in palette.bc_widgets for w in pair),
            palette.label, palette.sb,
        ]
        for widget in widgets:
            assert not widget.isHidden()
            assert main_window.field.geometry().contains(widget.geometry())
            assert main_window.childAt(widget.geometry().center()) is widget

    assert_reachable()
    series = main_window.series
    trace_cols, tool_cols = (20, 12) if layout == "configured" else (10, 1)
    series.setOption("tool_palette_cols", tool_cols)
    series.setOption("trace_palette_per_row", trace_cols)
    palette.reset()
    windows = [(1280, 800), (800, 600), (1280, 800)] if layout == "configured" else [
        (1280, 800), (1280, 550), (1280, 800),
    ]
    for window in windows:
        main_window.resize(*window)
        qapp.processEvents()
        palette.resize()
        assert_reachable()
        for button, mode, _ in palette.mode_buttons.values():
            QTest.mouseClick(main_window.childAt(button.geometry().center()), Qt.LeftButton)
            assert main_window.field.mouse_mode == mode

    assert series.getOption("tool_palette_cols") == tool_cols
    assert series.getOption("trace_palette_per_row") == trace_cols
    assert mouse_palette.load_palette_positions(settings) == positions
    assert {key: getattr(palette, key) for key in positions} == positions


@pytest.mark.parametrize("window,trace_cols,tool_cols,saved", [
    ((600, 400), 1, 1, {}),
    ((600, 400), 1, 1, {"bc_x": 0.5, "bc_y": 0.5}),
    ((600, 400), 1, 2, {"inc_x": 0.5, "inc_y": 0.5}),
    ((600, 400), 2, 2, {"sb_x": 0.5, "sb_y": 0.5}),
    ((600, 400), 3, 1, {"trace_x": 0.75, "trace_y": 0.99}),
    ((550, 800), 1, 12, {"trace_x": 0.01, "trace_y": 0.01}),
])
def test_saved_controls_leave_presets_reachable_in_a_small_window(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path,
        window, trace_cols, tool_cols, saved):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    mouse_palette.save_palette_positions(settings, saved)
    main_window.resize(*window)
    main_window.show()
    qapp.processEvents()
    palette = main_window.mouse_palette
    series = main_window.series
    series.setOption("trace_palette_per_row", trace_cols)
    series.setOption("tool_palette_cols", tool_cols)
    palette.reset()
    palette.resize()
    qapp.processEvents()

    widgets = [
        *palette.palette_buttons, *palette.palette_side_buttons,
        *(b for b, _, _ in palette.mode_buttons.values()),
        *palette.inc_buttons, *(w for pair in palette.bc_widgets for w in pair),
    ]
    for widget in widgets:
        assert main_window.field.geometry().contains(widget.geometry())
        assert main_window.childAt(widget.geometry().center()) is widget
    for i, button in enumerate(palette.palette_buttons):
        QTest.mouseClick(main_window.childAt(button.geometry().center()), Qt.LeftButton)
        assert series.palette_index[1] == i
    for button, mode, _ in palette.mode_buttons.values():
        QTest.mouseClick(main_window.childAt(button.geometry().center()), Qt.LeftButton)
        assert main_window.field.mouse_mode == mode
    assert mouse_palette.load_palette_positions(settings) == saved
    assert {key: getattr(palette, key) for key in saved} == saved


def test_the_scale_bar_leaves_the_contrast_control_reachable(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    main_window.resize(1280, 800)
    main_window.show()
    qapp.processEvents()
    main_window.series.setOption("tool_palette_cols", 12)
    main_window.resize(500, 360)
    qapp.processEvents()
    palette = main_window.mouse_palette
    palette.reset()
    palette.resize()
    qapp.processEvents()
    for widget in [*(w for pair in palette.bc_widgets for w in pair), palette.sb]:
        assert main_window.childAt(widget.geometry().center()) is widget
    assert not palette.sb.geometry().intersects(palette.bc_widgets[1][0].geometry())
    assert mouse_palette.load_palette_positions(settings) == {}


@pytest.mark.parametrize("tool_cols", [1, 5, 12])
@pytest.mark.parametrize("copies", [1, 3, 5, 10])
def test_resizing_fits_large_palettes_without_changing_the_preferences(main_window, palette, qapp, tool_cols, copies):
    series = main_window.series
    series.setOption("trace_palette_per_row", 1)
    series.setOption("tool_palette_cols", tool_cols)
    traces = series.palette_traces[series.palette_index[0]]
    series.palette_traces[series.palette_index[0]] = [t.copy() for _ in range(copies) for t in traces]
    palette.reset()
    main_window.resize(800, 600)
    main_window.show()
    qapp.processEvents()
    main_window.field.setGeometry(0, 30, 600, 400)
    palette.resize()
    field = main_window.field.geometry()
    buttons = [
        *palette.palette_buttons, *(b for b, _, _ in palette.mode_buttons.values()),
        *palette.palette_side_buttons, *palette.inc_buttons,
        *(w for pair in palette.bc_widgets for w in pair), palette.sb,
    ]
    for button in buttons:
        assert field.contains(button.geometry())
        assert main_window.childAt(button.geometry().center()) is button
    if copies == 10:
        assert palette.palette_buttons[0].width() < palette.pblen
    assert series.getOption("trace_palette_per_row") == 1
    assert series.getOption("tool_palette_cols") == tool_cols
    sizes = [b.size() for b in palette.palette_buttons]
    columns = len({b.x() for b in palette.palette_buttons})
    palette.moveButton(2, -2, "trace")
    palette.resize()
    assert [b.size() for b in palette.palette_buttons] == sizes
    assert len({b.x() for b in palette.palette_buttons}) == columns


@pytest.mark.parametrize("trace_cols,tool_cols", [(1, 1), (7, 3), (20, 12), (100, 2)])
@pytest.mark.parametrize("corner", [0, 1])
def test_partial_rows_and_controls_stay_reachable(main_window, palette, trace_cols, tool_cols, corner):
    series = main_window.series
    series.setOption("trace_palette_per_row", trace_cols)
    series.setOption("tool_palette_cols", tool_cols)
    name = series.palette_index[0]
    series.palette_traces[name] = [Trace(f"button{i}", [255, 0, 0]) for i in range(23)]
    for trace in series.palette_traces[name]:
        trace.points = [(-1, -1), (1, -1), (0, 1)]
    palette.reset()
    palette.trace_x = palette.trace_y = corner
    palette.mode_x = palette.mode_y = corner
    palette.resize()
    field = main_window.field.geometry()
    tools = [b for b, _, _ in palette.mode_buttons.values()]
    for group in (palette.palette_buttons, tools):
        for i, button in enumerate(group):
            assert not button.isHidden()
            assert field.contains(button.geometry()), (field, button.geometry())
            assert all(not button.geometry().intersects(other.geometry()) for other in group[i + 1:])
    for control in [*palette.palette_side_buttons, palette.label]:
        assert field.contains(control.geometry()), (field, control.geometry())
        assert all(not control.geometry().intersects(b.geometry()) for b in palette.palette_buttons)
    for i, button in enumerate(palette.palette_buttons):
        QTest.mouseClick(button, Qt.LeftButton)
        assert series.palette_index[1] == i
        assert palette.selectedTrace().name == f"button{i}"
    for button, mode, _ in palette.mode_buttons.values():
        QTest.mouseClick(button, Qt.LeftButton)
        assert main_window.field.mouse_mode == mode


# it writes both options to the shared user store on purpose, and removes them
@pytest.mark.shared_settings_store
def test_options_apply_cancel_reset_and_persist_per_user(main_window, palette, qtbot):
    series = main_window.series
    dialog = AllOptionsDialog(main_window, series)
    qtbot.addWidget(dialog)
    inputs = dialog.all_widgets["palette_layout"].inputs
    assert [i.widget.text() for i in inputs] == ["10", "1"]
    inputs[0].widget.setText("7")
    inputs[1].widget.setText("3")
    assert dialog.accept()
    palette.reset()
    palette.resize()
    assert len({b.x() for b in palette.palette_buttons}) == 7
    assert len({b.x() for b, _, _ in palette.mode_buttons.values()}) == 3

    # A new store instance reads the same user options without a series code.
    settings = QSettings(*shared_domain())
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(series, "_settingsStore", QSettingsStore)
        try:
            series.setOption("trace_palette_per_row", 7)
            series.setOption("tool_palette_cols", 3)
            assert QSettingsStore().value(None, "trace_palette_per_row", int) == 7
            assert QSettingsStore().value(None, "tool_palette_cols", int) == 3
            palette.reset()
            assert len({b.x() for b in palette.palette_buttons}) == 7
        finally:
            settings.remove("trace_palette_per_row")
            settings.remove("tool_palette_cols")

    canceled = AllOptionsDialog(main_window, series)
    qtbot.addWidget(canceled)
    canceled.all_widgets["palette_layout"].inputs[0].widget.setText("2")
    canceled.reject()
    assert series.getOption("trace_palette_per_row") == 7
    reset = AllOptionsDialog(main_window, series)
    qtbot.addWidget(reset)
    reset.resetDefaults()
    assert [i.widget.text() for i in reset.all_widgets["palette_layout"].inputs] == ["10", "1"]
    reset.reject()


@pytest.mark.parametrize("index,value", [(0, ""), (0, "0"), (0, "-1"), (0, "1.5"), (0, "101"), (1, "13")])
def test_invalid_dimensions_do_not_save(main_window, palette, qtbot, monkeypatch, index, value):
    from PyReconstruct.modules.gui.dialog import quick_dialog

    notices = []
    monkeypatch.setattr(quick_dialog, "notify", notices.append)
    dialog = AllOptionsDialog(main_window, main_window.series)
    qtbot.addWidget(dialog)
    dialog.all_widgets["palette_layout"].inputs[index].widget.setText(value)
    assert dialog.accept() is False
    assert notices
    assert main_window.series.getOption("trace_palette_per_row") == 10
    dialog.reject()


SWEEP_ROWS = (1, 2, 7, 20, 100)
SWEEP_COLS = (1, 3, 5, 6, 12)
SWEEP_SPOTS = ((0.001, 0.001), (0.999, 0.001), (0.5, 0.5), (0.001, 0.999), (0.999, 0.999))
# the selected preset's name: short, and long enough that small windows cut it
SWEEP_NAMES = ("d03", "a_long_trace_name")
# the smallest window first: a smaller request gets the minimum size
SWEEP_WINDOWS = [(100, 100), (321, 383), (330, 390), (360, 400), (450, 382),
                 (500, 400), (600, 400), (800, 600), (1280, 800)]


def missed_controls(main_window, palette):
    """Names of the clickable controls whose center does not hit them."""
    field = main_window.field.geometry()
    targets = [(f"preset {i}", b) for i, b in enumerate(palette.palette_buttons)]
    targets += [(f"side {i}", b) for i, b in enumerate(palette.palette_side_buttons)]
    targets += [("label", palette.label)]
    targets += [(f"tool {name}", b) for name, (b, _, _) in palette.mode_buttons.items()]
    targets += [(f"section {i}", b) for i, b in enumerate(palette.inc_buttons)]
    targets += [(f"bc {i}", w) for i, w in enumerate(w for pair in palette.bc_widgets for w in pair)]
    targets += [("scale bar", palette.sb)]
    missed = []
    for name, widget in targets:
        center = widget.mapTo(main_window, widget.rect().center())
        if (widget.isHidden() or not field.contains(center)
                or main_window.childAt(center) is not widget):
            missed.append(name)
    return missed


def test_the_window_cannot_shrink_below_the_palette_minimum(main_window, qapp):
    main_window.resize(100, 100)
    main_window.show()
    qapp.processEvents()
    field = main_window.field.size().toTuple()
    assert field == main_window.field.minimumSize().toTuple() == (320, 340)
    assert main_window.size().toTuple() == main_window.minimumSize().toTuple()


@pytest.mark.parametrize("window", SWEEP_WINDOWS)
def test_every_control_is_reachable_across_layouts(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path, window):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    main_window.resize(*window)
    main_window.show()
    qapp.processEvents()
    expected = (max(window[0], main_window.minimumWidth()), max(window[1], main_window.minimumHeight()))
    assert main_window.size().toTuple() == expected
    series = main_window.series
    groups = mouse_palette.DEFAULT_POSITIONS
    # each group alone at each spot, then every group together at it
    saved = [{}] + [
        {f"{group}_x": x, f"{group}_y": y} for group in groups for x, y in SWEEP_SPOTS
    ] + [
        {f"{group}_{axis}": v for group in groups for axis, v in (("x", x), ("y", y))}
        for x, y in SWEEP_SPOTS
    ]
    selected = series.palette_traces[series.palette_index[0]][series.palette_index[1]]
    # each layout is reached by resizing the window from another size, as a
    # user does, with nothing else asking the palette to place itself
    away = (600, 400) if window == (1280, 800) else (1280, 800)
    failures = []
    for name in SWEEP_NAMES:
        selected.name = name
        for rows in SWEEP_ROWS:
            for cols in SWEEP_COLS:
                series.setOption("trace_palette_per_row", rows)
                series.setOption("tool_palette_cols", cols)
                palette = main_window.mouse_palette
                palette.reset()
                for positions in saved:
                    mouse_palette.save_palette_positions(settings, positions)
                    mouse_palette.set_default_positions(palette)
                    palette.loadPositionState()
                    main_window.resize(*away)
                    qapp.processEvents()
                    main_window.resize(*window)
                    qapp.processEvents()
                    missed = missed_controls(main_window, palette)
                    if missed:
                        failures.append((name, rows, cols, positions, missed))
                    assert mouse_palette.load_palette_positions(settings) == positions
                    assert {key: getattr(palette, key) for key in positions} == positions
                    for key in mouse_palette.PALETTE_POS_KEYS:
                        settings.remove(key)
    total = len(SWEEP_NAMES) * len(SWEEP_ROWS) * len(SWEEP_COLS) * len(saved)
    assert not failures, f"{window}: {len(failures)} of {total}: {failures[:5]}"


@pytest.mark.parametrize("window", [(320, 362), (340, 362), (360, 400), (450, 362)])
def test_a_fallback_layout_draws_the_label_where_it_left_room(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path, window):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    # every group saved at the center: they cannot all go there, so the
    # default arrangement is drawn, with the label above the buttons
    saved = {f"{group}_{axis}": 0.5 for group in mouse_palette.DEFAULT_POSITIONS for axis in "xy"}
    mouse_palette.save_palette_positions(settings, saved)
    main_window.resize(*window)
    main_window.show()
    qapp.processEvents()
    series = main_window.series
    series.setOption("trace_palette_per_row", 1)
    series.setOption("tool_palette_cols", 1)
    palette = main_window.mouse_palette
    palette.reset()
    palette.resize()
    qapp.processEvents()
    assert palette.arrange(palette.savedFractions()) is None
    assert palette.label.geometry().bottom() < palette.palette_buttons[0].geometry().top()
    assert missed_controls(main_window, palette) == []
    assert mouse_palette.load_palette_positions(settings) == saved


def test_selecting_a_preset_with_a_longer_name_keeps_every_control_reachable(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    main_window.resize(340, 362)
    main_window.show()
    qapp.processEvents()
    series = main_window.series
    series.setOption("trace_palette_per_row", 1)
    series.setOption("tool_palette_cols", 5)
    palette = main_window.mouse_palette
    palette.reset()
    palette.resize()
    qapp.processEvents()
    assert missed_controls(main_window, palette) == []
    for i, button in enumerate(palette.palette_buttons):
        QTest.mouseClick(button, Qt.LeftButton, Qt.NoModifier, button.rect().center())
        qapp.processEvents()
        assert series.palette_index[1] == i
        assert missed_controls(main_window, palette) == [], button.trace.name
    assert mouse_palette.load_palette_positions(settings) == {}


@pytest.mark.parametrize("window, shortened", [((1280, 800), False), ((320, 382), True)])
def test_a_long_name_keeps_its_number_in_view(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path, window, shortened):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    main_window.resize(*window)
    main_window.show()
    qapp.processEvents()
    main_window.series.setOption("trace_palette_per_row", 1)
    main_window.series.setOption("tool_palette_cols", 5)
    palette = main_window.mouse_palette
    palette.reset()
    trace = palette.selectedTrace().copy()
    trace.name = "dendrite_shaft_spine_{01}"
    palette.modifyPaletteButton(palette.selectedPos(), trace)
    shown = []
    for number in ("01", "02"):
        if number == "02":
            palette.incrementPalette(True)
        qapp.processEvents()
        name = f"dendrite_shaft_spine_{number}"
        assert main_window.field.tracing_trace.name == name
        if shortened:
            # cut in the middle: the start and the number both show
            assert palette.label.text() != name
            assert palette.label.text().startswith("dend")
            assert palette.label.text().endswith(f"_{number}")
        else:
            assert palette.label.text() == name
        assert palette.label.toolTip() == name
        assert missed_controls(main_window, palette) == []
        shown.append(palette.label.text())
    assert shown[0] != shown[1]


def test_a_short_name_is_shown_whole(main_window, palette):
    series = main_window.series
    selected = series.palette_traces[series.palette_index[0]][series.palette_index[1]]
    selected.name = "d03"
    palette.reset()
    assert palette.label.text() == "d03"
    assert palette.label.toolTip() == "d03"


RESIZE_STEPS = [(320, 382), (600, 400), (1280, 800), (450, 382), (330, 390), (800, 600)]


@pytest.mark.parametrize("rows, cols", [(1, 1), (1, 5), (7, 3), (20, 12)])
def test_resizing_the_window_keeps_every_control_reachable(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path, rows, cols):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    main_window.resize(1280, 800)
    main_window.show()
    qapp.processEvents()
    main_window.series.setOption("trace_palette_per_row", rows)
    main_window.series.setOption("tool_palette_cols", cols)
    palette = main_window.mouse_palette
    palette.reset()
    qapp.processEvents()
    assert missed_controls(main_window, palette) == []
    # only the window is resized: the palette places itself from that alone
    for size in RESIZE_STEPS:
        main_window.resize(*size)
        qapp.processEvents()
        expected = (max(size[0], main_window.minimumWidth()), max(size[1], main_window.minimumHeight()))
        assert main_window.size().toTuple() == expected
        assert missed_controls(main_window, palette) == [], size
