"""Trackpad section direction is independent of mouse wheels and zoom."""
import pytest

from PyReconstruct.modules.gui.main.wheel_steps import WheelSteps
from trackpad_replay import NativeEvents, notch
from test_wheel_steps import scroll, swipe

pytestmark = pytest.mark.gui


@pytest.fixture
def window(main_window, local_series_settings, qtbot):
    local_series_settings(main_window)
    main_window.native = NativeEvents()
    main_window.wheel_steps = WheelSteps(read_native=main_window.native)
    main_window.show()
    qtbot.waitExposed(main_window)
    return main_window


@pytest.mark.parametrize("delta,expected", [(150, 49), (-150, 55)])
def test_reverse_trackpad_sections_without_reversing_mouse_wheels(window, delta, expected):
    window.series.setOption("reverse_trackpad_scroll", True)
    assert scroll(window, [notch(1, pixel=20), notch(-1)]) == [53, 52]
    assert scroll(window, swipe([delta]))[-1] == expected


@pytest.mark.parametrize("platform,expected", [("darwin", True), ("linux", False), ("win32", False)])
def test_trackpad_default_is_reversed_only_on_macos(window, monkeypatch, platform, expected):
    import runpy
    import sys
    from pathlib import Path

    path = Path(__file__).parents[1] / "PyReconstruct/modules/datatypes/default_settings.py"
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", platform)
        defaults = runpy.run_path(str(path))["default_settings"]
    assert defaults["reverse_trackpad_scroll"] is expected
    from PyReconstruct.modules.datatypes.series import Series

    monkeypatch.setitem(Series.qsettings_defaults, "reverse_trackpad_scroll",
                        defaults["reverse_trackpad_scroll"])
    assert scroll(window, swipe([150]))[-1] == (49 if expected else 55)


def reverse_checkbox(dialog):
    from PySide6.QtWidgets import QCheckBox

    return next(
        box for box in dialog.findChildren(QCheckBox)
        if box.text() == "Reverse trackpad section scrolling"
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_options_save_direction_across_series_and_settings_store_instances(
    window, real_series, qtbot, reverse,
):
    from PyReconstruct.modules.backend.settings_store import QSettingsStore
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

    # conftest redirects QSettings to temporary files before importing PyReconstruct.
    window.series.setSettingsStore(QSettingsStore())
    window.series.setOption("reverse_trackpad_scroll", not reverse)
    dialog = AllOptionsDialog(window, window.series)
    qtbot.addWidget(dialog)
    reverse_checkbox(dialog).setChecked(reverse)
    assert dialog.accept()

    real_series.code = "another-series"
    real_series.setSettingsStore(QSettingsStore())
    reopened = AllOptionsDialog(None, real_series)
    qtbot.addWidget(reopened)
    assert reverse_checkbox(reopened).isChecked() is reverse
    assert real_series.getOption("reverse_trackpad_scroll") is reverse
    assert scroll(window, swipe([150]))[-1] == (49 if reverse else 55)


def test_cancel_keeps_direction_and_reset_defaults_waits_for_ok(window, qtbot):
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

    default = window.series.getOption("reverse_trackpad_scroll", get_default=True)
    window.series.setOption("reverse_trackpad_scroll", not default)
    dialog = AllOptionsDialog(window, window.series)
    qtbot.addWidget(dialog)
    assert reverse_checkbox(dialog).isChecked() is not default
    dialog.resetDefaults()
    assert reverse_checkbox(dialog).isChecked() is default
    assert window.series.getOption("reverse_trackpad_scroll") is not default
    dialog.reject()
    assert window.series.getOption("reverse_trackpad_scroll") is not default


@pytest.mark.parametrize("reverse,expected", [(False, 54), (True, 50)])
@pytest.mark.parametrize("busy", [False, True])
def test_direction_option_preserves_momentum_filter(window, reverse, expected, busy):
    from test_wheel_steps import after_lift

    window.series.setOption("reverse_trackpad_scroll", reverse)
    events = swipe([12] * 9, momentum=[50, 16, 12, 8, 4], busy=busy)
    sections = scroll(window, events)
    assert sections[-1] == expected
    assert after_lift(events, sections) == 0


def test_reverse_direction_with_only_qt_phases(window):
    window.wheel_steps.read_native = lambda event: None
    window.series.setOption("reverse_trackpad_scroll", True)
    assert scroll(window, swipe([12] * 9, busy=False))[-1] == 50


@pytest.mark.parametrize("reverse", [False, True])
def test_direction_option_leaves_zoom_unchanged(window, reverse):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window.series.setOption("reverse_trackpad_scroll", reverse)
    scroll(window, swipe([12] * 5, momentum=[40, 30, 20]), Qt.ControlModifier)
    assert window.zoom_factor == pytest.approx(1.1)
    QTest.keyRelease(window, Qt.Key_Control)
    scroll(window, [notch(-1)], Qt.ControlModifier)
    assert window.zoom_factor == pytest.approx(0.9)
    assert window.series.current_section == 52
    QTest.keyRelease(window, Qt.Key_Control)
