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


def sweep_positions(groups):
    """No saved spots, each group alone at each spot, then every group together at it."""
    return [{}] + [
        {f"{group}_x": x, f"{group}_y": y} for group in groups for x, y in SWEEP_SPOTS
    ] + [
        {f"{group}_{axis}": v for group in groups for axis, v in (("x", x), ("y", y))}
        for x, y in SWEEP_SPOTS
    ]


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
    saved = sweep_positions(mouse_palette.DEFAULT_POSITIONS)
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


def bar_preview(width, thickness, pinned=None):
    """The settings the scale bar dialog previews, numbers and ticks shown."""
    return {"show_scale_bar_text": True, "show_scale_bar_ticks": True,
            "scale_bar_mode": "micron_pinned" if pinned else "screen_fraction",
            "scale_bar_width": width, "scale_bar_length_um": pinned or 1.0,
            "scale_bar_thickness": thickness}


# the allowed sizes' ends and middle, at the thinnest and thickest bar, and
# a pinned length that fills its room
SWEEP_PREVIEWS = [bar_preview(100, 3), bar_preview(60, 25), bar_preview(100, 25),
                  bar_preview(100, 25, pinned=100.0)]


@pytest.mark.parametrize("window", SWEEP_WINDOWS)
def test_a_scale_bar_preview_leaves_every_control_reachable(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path, window):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    main_window.resize(*window)
    main_window.show()
    qapp.processEvents()
    series = main_window.series
    stored = {key: series.getOption(key) for key in SWEEP_PREVIEWS[0]}
    failures = []
    for rows in SWEEP_ROWS:
        for cols in SWEEP_COLS:
            series.setOption("trace_palette_per_row", rows)
            series.setOption("tool_palette_cols", cols)
            palette = main_window.mouse_palette
            palette.reset()
            for positions in sweep_positions(mouse_palette.DEFAULT_POSITIONS):
                mouse_palette.save_palette_positions(settings, positions)
                mouse_palette.set_default_positions(palette)
                palette.loadPositionState()
                palette.resize()
                # the Options slider, then the scale bar settings dialog
                palette.previewScaleBarWidth(100)
                checks = [("slider 100", missed_controls(main_window, palette))]
                for preview in SWEEP_PREVIEWS:
                    palette.previewScaleBar(preview)
                    checks.append((preview, missed_controls(main_window, palette)))
                palette.restoreScaleBar()
                checks.append(("restored", missed_controls(main_window, palette)))
                failures += [(rows, cols, positions, what, missed) for what, missed in checks if missed]
                for key in mouse_palette.PALETTE_POS_KEYS:
                    settings.remove(key)
    assert {key: series.getOption(key) for key in stored} == stored
    assert not failures, f"{window}: {len(failures)}: {failures[:5]}"


@pytest.mark.parametrize("window", [(100, 100), (1280, 800)])
def test_a_large_stored_scale_bar_leaves_every_control_reachable(
        main_window, local_series_settings, monkeypatch, qapp, window):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    monkeypatch.setattr(mouse_palette, "load_palette_positions", lambda settings: {})
    main_window.resize(*window)
    main_window.show()
    qapp.processEvents()
    series = main_window.series
    series.setOption("scale_bar_width", 100)
    series.setOption("scale_bar_thickness", 25)
    palette = main_window.mouse_palette
    palette.reset()
    qapp.processEvents()
    assert missed_controls(main_window, palette) == []
    assert series.getOption("scale_bar_width") == 100
    narrowed = palette.sb.width()
    # a window with more room gives the bar more of its share again
    main_window.resize(1600, 1000)
    qapp.processEvents()
    assert missed_controls(main_window, palette) == []
    assert palette.sb.width() > narrowed


def type_length(monkeypatch, palette, answers):
    """Run "Set the scale bar length..." with these answers, in order; the
    dialog's lines and the refusals it shows are returned."""
    from PyReconstruct.modules.gui.palette import mouse_palette

    asked, refused = [], []
    queue = list(answers)
    monkeypatch.setattr(mouse_palette.QuickDialog, "get", staticmethod(
        lambda parent, structure, title: (asked.append(structure), ([queue.pop(0)], True))[1]))
    monkeypatch.setattr(mouse_palette, "notify", refused.append)
    palette.setSBLength()
    return asked, refused


def drawn_as_labeled(bar):
    """True if the typed bar's label is the length its pixels measure."""
    real_len, pix_len, _ = bar.pinnedRender()
    return pix_len > 0 and abs(real_len / bar.scale - pix_len) <= 1


def test_a_typed_length_leaves_every_control_reachable(
        main_window, local_series_settings, monkeypatch, qapp):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    monkeypatch.setattr(mouse_palette, "load_palette_positions", lambda settings: {})
    main_window.resize(100, 100)
    main_window.show()
    qapp.processEvents()
    series = main_window.series
    series.setOption("trace_palette_per_row", 1)
    series.setOption("tool_palette_cols", 1)
    palette = main_window.mouse_palette
    palette.reset()
    palette.previewScaleBar(bar_preview(100, 25))
    assert missed_controls(main_window, palette) == []
    lo, hi = palette.sbLengthRange()
    # the field could hold a longer bar than the buttons leave room for
    assert hi < mouse_palette.drawableLengths(palette.sb.scale, main_window.field.width())[1]
    # one past the longest is refused and the dialog asks again
    asked, refused = type_length(monkeypatch, palette, [hi * 1.01, hi])
    assert len(asked) == 2 and len(refused) == 1
    assert ["A longer bar would cover the palette buttons."] in asked[0]
    assert palette.sb.currentLength()[0] == hi and drawn_as_labeled(palette.sb)
    assert missed_controls(main_window, palette) == []
    palette.previewScaleBarWidth(60)
    assert palette.sb.currentLength()[0] == hi
    assert missed_controls(main_window, palette) == []
    # a larger window and back, and an Options OK rebuild, keep it clear
    main_window.resize(1280, 800)
    qapp.processEvents()
    assert missed_controls(main_window, palette) == []
    main_window.resize(100, 100)
    qapp.processEvents()
    assert missed_controls(main_window, palette) == [] and drawn_as_labeled(palette.sb)
    palette.reset()
    palette = main_window.mouse_palette
    assert palette.sb.override_length == hi
    assert missed_controls(main_window, palette) == [] and drawn_as_labeled(palette.sb)
    # typed in a large window, then the window made as small as it goes
    main_window.resize(1280, 800)
    qapp.processEvents()
    hi = palette.sbLengthRange()[1]
    type_length(monkeypatch, palette, [hi])
    assert palette.sb.currentLength()[0] == hi
    assert missed_controls(main_window, palette) == []
    main_window.resize(100, 100)
    qapp.processEvents()
    assert missed_controls(main_window, palette) == [] and drawn_as_labeled(palette.sb)


@pytest.mark.parametrize("window", [(100, 100), (360, 400), (600, 400), (1280, 800)])
def test_a_typed_length_and_later_previews_leave_every_control_reachable(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path, window):
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    main_window.resize(*window)
    main_window.show()
    qapp.processEvents()
    series = main_window.series
    stored = {key: series.getOption(key) for key in SWEEP_PREVIEWS[0]}
    zoom = series.window[2]
    failures = []

    def check(what, palette, typed=None):
        missed = missed_controls(main_window, palette)
        if typed is not None and palette.sb.currentLength()[0] != typed:
            missed.append("typed length not drawn")
        if not drawn_as_labeled(palette.sb):
            missed.append("label is not the drawn length")
        return what, missed

    for rows in SWEEP_ROWS:
        for cols in SWEEP_COLS:
            series.setOption("trace_palette_per_row", rows)
            series.setOption("tool_palette_cols", cols)
            palette = main_window.mouse_palette
            palette.reset()
            for positions in sweep_positions(mouse_palette.DEFAULT_POSITIONS):
                mouse_palette.save_palette_positions(settings, positions)
                mouse_palette.set_default_positions(palette)
                palette.loadPositionState()
                palette.restoreScaleBar()
                palette.clearSBLength()
                palette.resize()
                # the thinnest bar, so the thicker previews leave it less room
                palette.previewScaleBar(SWEEP_PREVIEWS[0])
                # the longest length the dialog offers is drawn as typed;
                # later previews and zooms keep it, a decade shorter if the
                # buttons need the room, as a zoom already steps it
                hi = palette.sbLengthRange()[1]
                type_length(monkeypatch, palette, [hi])
                checks = [check("typed", palette, hi)]
                for preview in SWEEP_PREVIEWS:
                    palette.previewScaleBar(preview)
                    checks.append(check(preview, palette))
                for factor in (0.25, 4.0):
                    series.window[2] = zoom * factor
                    palette.setScale()
                    checks.append(check(f"zoom {factor}", palette))
                series.window[2] = zoom
                palette.setScale()
                # back at the bar it was typed for, it is drawn as typed again
                palette.previewScaleBar(SWEEP_PREVIEWS[0])
                checks.append(check("typed again", palette, hi))
                palette.restoreScaleBar()
                checks.append(check("restored", palette))
                failures += [(rows, cols, positions, what, missed) for what, missed in checks if missed]
                for key in mouse_palette.PALETTE_POS_KEYS:
                    settings.remove(key)
    assert {key: series.getOption(key) for key in stored} == stored
    assert not failures, f"{window}: {len(failures)}: {failures[:5]}"


def smallest_window(main_window, local_series_settings, monkeypatch, qapp, tmp_path,
                    rows, cols, spot=None, thickness=3):
    """The palette in the smallest window, at 0.01 µm a pixel, with every
    group saved at `spot` (None: no saved spots) and a bar this thick."""
    from PyReconstruct.modules.gui.palette import mouse_palette

    local_series_settings(main_window)
    settings = QSettings(str(tmp_path / "positions.ini"), QSettings.IniFormat)
    monkeypatch.setattr(mouse_palette, "_position_settings", lambda: settings)
    if spot is not None:
        mouse_palette.save_palette_positions(settings, {
            f"{group}_{axis}": v for group in mouse_palette.DEFAULT_POSITIONS
            for axis, v in (("x", spot[0]), ("y", spot[1]))})
    main_window.resize(100, 100)
    main_window.show()
    qapp.processEvents()
    series = main_window.series
    series.setOption("trace_palette_per_row", rows)
    series.setOption("tool_palette_cols", cols)
    palette = main_window.mouse_palette
    palette.reset()
    series.window[2] = 0.01 * main_window.field.pixmap_dim[0]
    palette.setScale()
    palette.previewScaleBar(bar_preview(100, thickness))
    assert missed_controls(main_window, palette) == []
    return palette


def clear_widths(main_window, palette):
    """Every bar width up to the field's that leaves every group a clear
    spot, each found by placing all the groups for it."""
    from PyReconstruct.modules.gui.palette import mouse_palette

    return {width for width in range(1, main_window.field.width() + 1)
            if any(palette.arrange(fractions, bar_width=width) is not None
                   for fractions in (palette.savedFractions(), mouse_palette.DEFAULT_POSITIONS))}


def test_a_typed_length_that_would_cover_a_button_is_drawn_a_decade_shorter(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path):
    palette = smallest_window(main_window, local_series_settings, monkeypatch, qapp,
                              tmp_path, 1, 1, spot=(0.0, 0.0))
    # 179 px falls between widths that are clear: 1.79 µm is offered, but
    # drawn as typed it would cover buttons
    lo, hi = palette.sbLengthRange()
    assert lo <= 1.79 <= hi
    clear = clear_widths(main_window, palette)
    assert 179 not in clear and max(clear) == 320
    asked, refused = type_length(monkeypatch, palette, [1.79])
    assert refused == []
    assert ["A length that would cover the palette buttons is drawn"] in asked[0]
    assert palette.sb.override_length == 1.79
    assert palette.sb.currentLength()[0] == pytest.approx(0.179)
    assert drawn_as_labeled(palette.sb)
    assert missed_controls(main_window, palette) == []


def test_the_longest_clear_typed_length_is_offered_and_drawn_as_typed(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path):
    palette = smallest_window(main_window, local_series_settings, monkeypatch, qapp,
                              tmp_path, 1, 1)
    # clear widths stop at 161 px and start again at 219: the longest clear
    # bar is past the gap
    clear = clear_widths(main_window, palette)
    assert 180 not in clear and max(clear) == 228
    assert palette.sbTypedRoom() == 228
    assert palette.sbLengthRange()[1] == 2.28
    asked, refused = type_length(monkeypatch, palette, [2.28])
    assert refused == []
    assert ["A longer bar would cover the palette buttons."] in asked[0]
    assert palette.sb.currentLength()[0] == 2.28 and drawn_as_labeled(palette.sb)
    assert missed_controls(main_window, palette) == []


@pytest.mark.parametrize("shape", [(1, 1), (3, 2), (100, 12)])
def test_every_typed_length_at_the_smallest_window_leaves_every_control_reachable(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path, shape):
    """Each whole-pixel length the dialog offers, in each arrangement: drawn
    as typed when that bar is clear, else at the first clear decade below."""
    from PyReconstruct.modules.gui.palette import mouse_palette

    failures = []
    for spot in (None, (0.0, 0.0), (1.0, 1.0), (0.5, 0.5)):
        palette = smallest_window(main_window, local_series_settings, monkeypatch, qapp,
                                  tmp_path, *shape, spot=spot)
        for thickness in (3, 25):
            palette.clearSBLength()
            palette.previewScaleBar(bar_preview(100, thickness))
            clear = clear_widths(main_window, palette)
            scale = palette.sb.scale
            lo, hi = palette.sbLengthRange()
            # the longest offered is drawn as typed; nothing longer is clear
            assert palette.sbBarWidth(hi) in clear
            assert not any(palette.sbBarWidth(round(w * scale, 10)) in clear
                           for w in range(round(hi / scale) + 1, main_window.field.width() + 1))
            for pixels in range(round(lo / scale), round(hi / scale) + 1):
                length = round(pixels * scale, 10)
                decades = next((k for k in range(4)
                                if palette.sbBarWidth(length / 10 ** k) in clear), None)
                asked, refused = type_length(monkeypatch, palette, [length, hi])
                drawn = palette.sb.currentLength()[0]
                missed = missed_controls(main_window, palette)
                if (decades is None) != bool(refused) or missed or not drawn_as_labeled(palette.sb) \
                        or (decades is not None and drawn != pytest.approx(length / 10 ** decades)):
                    failures.append((shape, spot, thickness, length, decades, drawn, refused, missed))
        for key in mouse_palette.PALETTE_POS_KEYS:
            mouse_palette._position_settings().remove(key)
    assert not failures, f"{len(failures)}: {failures[:5]}"


@pytest.mark.parametrize("pinned", [None, 3.0])
def test_a_shortened_bar_is_labeled_with_the_length_it_draws(
        main_window, local_series_settings, monkeypatch, qapp, pinned):
    from PySide6.QtGui import QPainter, QPixmap
    from PyReconstruct.modules.gui.palette import mouse_palette, scale_bar

    local_series_settings(main_window)
    monkeypatch.setattr(mouse_palette, "load_palette_positions", lambda settings: {})
    main_window.resize(100, 100)
    main_window.show()
    qapp.processEvents()
    series = main_window.series
    series.setOption("trace_palette_per_row", 1)
    series.setOption("tool_palette_cols", 1)
    palette = main_window.mouse_palette
    palette.reset()
    series.window[2] = 0.01 * main_window.field.pixmap_dim[0]
    palette.setScale()
    stored = {key: series.getOption(key) for key in bar_preview(100, 25, pinned)}
    palette.previewScaleBar(bar_preview(100, 25, pinned))
    qapp.processEvents()
    assert missed_controls(main_window, palette) == []
    chosen = pinned or scale_bar.niceLength(palette.sbWidth(100) * palette.sb.scale)[0]
    rects, labels = [], []
    draw_rect, draw_text = QPainter.drawRect, scale_bar.drawOutlinedText
    monkeypatch.setattr(QPainter, "drawRect", lambda painter, *args: (
        rects.append(args) if len(args) == 4 else None, draw_rect(painter, *args))[1])
    monkeypatch.setattr(scale_bar, "drawOutlinedText", lambda painter, x, y, text: (
        labels.append(text), draw_text(painter, x, y, text))[1])
    pixmap = QPixmap(palette.sb.size())
    pixmap.fill()
    palette.sb.render(pixmap)
    # the buttons need the room, so the whole bar is drawn shorter than the
    # size chosen, and its label is the length drawn
    assert rects[0][2] <= palette.sb.width()
    drawn = rects[0][2] * palette.sb.scale
    assert drawn < chosen
    assert float(labels[0].split()[0]) == pytest.approx(drawn, abs=palette.sb.scale)
    assert {key: series.getOption(key) for key in stored} == stored


def first_clear_decade(main_window, palette, length):
    """The length a typed bar must be drawn at: as typed (or the decade a
    zoom moves it to), or the first decade below whose bar leaves every
    group clear (by brute force)."""
    from PyReconstruct.modules.gui.palette.scale_bar import pinnedLength

    clear = clear_widths(main_window, palette)
    length = pinnedLength(length, palette.sb.scale, main_window.field.width())[0]
    return next(length / 10 ** k for k in range(6)
                if palette.sbBarWidth(length / 10 ** k) in clear)


def check_typed(main_window, palette, typed):
    """What is wrong with a typed bar: a covered control, a label that is not
    the drawn length, a typed length forgotten, or not the first clear decade."""
    wrong = list(missed_controls(main_window, palette))
    if palette.sb.override_length != typed:
        wrong.append("typed length forgotten")
    if not drawn_as_labeled(palette.sb):
        wrong.append("label is not the drawn length")
    if palette.sb.currentLength()[0] != pytest.approx(first_clear_decade(main_window, palette, typed)):
        wrong.append(f"drawn {palette.sb.currentLength()[0]} µm")
    return wrong


def test_resetting_palette_positions_refits_a_typed_length(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path):
    from PyReconstruct.modules.gui.palette import mouse_palette

    palette = smallest_window(main_window, local_series_settings, monkeypatch, qapp,
                              tmp_path, 1, 1, spot=(0.0, 0.0))
    type_length(monkeypatch, palette, [3.2])
    assert palette.sb.currentLength()[0] == 3.2 and palette.sb.width() == 320
    assert check_typed(main_window, palette, 3.2) == []
    # View > Palette > Reset palette position: the default spots leave no
    # room for a 320 px bar, so it is drawn a decade shorter
    main_window.resetpalette_act.trigger()
    qapp.processEvents()
    assert mouse_palette.load_palette_positions(mouse_palette._position_settings()) == {}
    assert palette.sb.currentLength()[0] == pytest.approx(0.32)
    assert check_typed(main_window, palette, 3.2) == []


def drag_group(main_window, qapp, monkeypatch, button, dx, dy):
    """Drag a palette group by one of its buttons, with real mouse events."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(main_window.field, "max_click_time", -1)

    def send(kind, global_pos, buttons):
        local = button.mapFromGlobal(global_pos)
        QApplication.sendEvent(button, QMouseEvent(
            kind, QPointF(local), QPointF(global_pos), Qt.LeftButton, buttons, Qt.NoModifier))

    start = button.mapToGlobal(button.rect().center())
    end = start + type(start)(dx, dy)
    send(QEvent.MouseButtonPress, start, Qt.LeftButton)
    send(QEvent.MouseMove, end, Qt.LeftButton)
    send(QEvent.MouseButtonRelease, end, Qt.NoButton)
    qapp.processEvents()


def road_reset_menu(main_window, palette, qapp, monkeypatch):
    main_window.resetpalette_act.trigger()


def road_drag_tools(main_window, palette, qapp, monkeypatch):
    button = next(iter(palette.mode_buttons.values()))[0]
    drag_group(main_window, qapp, monkeypatch, button, 150, 150)


def road_drag_sections(main_window, palette, qapp, monkeypatch):
    drag_group(main_window, qapp, monkeypatch, palette.inc_buttons[0], 150, 150)


def road_drag_bar(main_window, palette, qapp, monkeypatch):
    drag_group(main_window, qapp, monkeypatch, palette.sb, 0, 300)


def road_window(main_window, palette, qapp, monkeypatch):
    main_window.resize(1280, 800)
    qapp.processEvents()
    main_window.resize(100, 100)


def road_long_name(main_window, palette, qapp, monkeypatch):
    trace = palette.selectedTrace().copy()
    trace.name = "dendrite_shaft_spine_long_name_01"
    palette.modifyPaletteButton(palette.selectedPos(), trace)


def road_preset(main_window, palette, qapp, monkeypatch):
    series = main_window.series
    traces = series.palette_traces[series.palette_index[0]]
    series.palette_traces["more"] = [t.copy() for t in traces * 3]
    series.palette_index[0] = "more"
    palette.reset()


def road_tool_columns(main_window, palette, qapp, monkeypatch):
    main_window.series.setOption("tool_palette_cols", 5)
    palette.reset()


def road_zoom(main_window, palette, qapp, monkeypatch):
    series = main_window.series
    zoom = series.window[2]
    series.window[2] = zoom * 4
    palette.setScale()
    series.window[2] = zoom
    palette.setScale()


def road_thicker_bar(main_window, palette, qapp, monkeypatch):
    palette.previewScaleBar(bar_preview(100, 25))


PLACEMENT_ROADS = [road_reset_menu, road_drag_tools, road_drag_sections, road_drag_bar,
                   road_window, road_long_name, road_preset, road_tool_columns,
                   road_zoom, road_thicker_bar]


@pytest.mark.parametrize("road", PLACEMENT_ROADS, ids=lambda road: road.__name__[5:])
def test_every_placement_road_refits_a_typed_length(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path, road):
    """A typed bar that fills the field, then each road that places the
    palette groups again: the bar is drawn at the first clear decade."""
    palette = smallest_window(main_window, local_series_settings, monkeypatch, qapp,
                              tmp_path, 1, 1, spot=(0.0, 0.0))
    type_length(monkeypatch, palette, [3.2])
    assert palette.sb.currentLength()[0] == 3.2
    road(main_window, palette, qapp, monkeypatch)
    qapp.processEvents()
    palette = main_window.mouse_palette
    assert check_typed(main_window, palette, 3.2) == []


def pan_zoom_to(main_window, palette, qapp, scale):
    """Zoom the field to `scale` µm a pixel with real pan-zoom drags, each
    at most 100 times in or out, as a hand would."""
    field = main_window.field
    for _ in range(40):
        if palette.getScale() == pytest.approx(scale):
            break
        factor = min(max(palette.getScale() / scale, 0.01), 100)
        field.panzoomPress(100, 100)
        field.panzoomMove(zoom_factor=factor)
        field.panzoomRelease(zoom_factor=factor)
        qapp.processEvents()
    assert palette.sb.scale == pytest.approx(scale)


def test_a_typed_bar_with_no_room_at_any_length_is_hidden_until_the_room_returns(
        main_window, local_series_settings, monkeypatch, qapp, tmp_path):
    from PyReconstruct.modules.gui.palette import mouse_palette

    palette = smallest_window(main_window, local_series_settings, monkeypatch, qapp,
                              tmp_path, 1, 1, thickness=25)
    typed = 1.234567891
    type_length(monkeypatch, palette, [typed])
    assert check_typed(main_window, palette, typed) == []
    visibility = mouse_palette.load_palette_visibility(mouse_palette._visibility_settings())
    # so far out that the bar's number alone is wider than any clear spot,
    # at every length it can be drawn
    pan_zoom_to(main_window, palette, qapp, 1e16)
    assert palette.sbTypedFit(typed)[1] is None
    assert palette.sb.isHidden() and not palette.sb_hidden
    assert missed_controls(main_window, palette) == ["scale bar"]
    # the View menu's toggle does not show a bar that has no room
    palette.toggleSB()
    palette.toggleSB()
    assert palette.sb.isHidden()
    # a larger window has room again, and the smallest one has not
    main_window.resize(1280, 800)
    qapp.processEvents()
    assert check_typed(main_window, palette, typed) == []
    main_window.resize(100, 100)
    qapp.processEvents()
    assert palette.sb.isHidden()
    assert missed_controls(main_window, palette) == ["scale bar"]
    # zoomed back in, the typed length is drawn again
    pan_zoom_to(main_window, palette, qapp, 0.01)
    assert not palette.sb.isHidden()
    assert palette.sb.currentLength()[0] == typed
    assert check_typed(main_window, palette, typed) == []
    assert mouse_palette.load_palette_visibility(mouse_palette._visibility_settings()) == visibility
