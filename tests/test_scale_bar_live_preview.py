"""The scale bar size slider previews on the field as it moves.

His click test (2026-09-14): the size could only be judged after OK closed
Series > Options. Now the slider resizes the bar in the field live, nothing
is stored until OK, and Cancel puts the bar back to its stored size.
"""
import pytest

from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

pytestmark = pytest.mark.gui


def _slider(dlg):
    for field in dlg.all_widgets["scale_bar"].inputs:
        if field.type == "slider":
            return field.widget.slider
    raise AssertionError("no size slider on the scale bar page")


def _expected(main_window, percent):
    return int(percent / 100 * main_window.field.width())


def test_moving_the_slider_resizes_the_bar_without_storing(main_window, qapp):
    series = main_window.series
    stored = series.getOption("scale_bar_width")
    dlg = AllOptionsDialog(main_window, series)
    target = 60 if stored != 60 else 80

    _slider(dlg).setValue(target)
    qapp.processEvents()

    assert main_window.mouse_palette.sb.width() == _expected(main_window, target)
    assert series.getOption("scale_bar_width") == stored


def test_cancel_puts_the_bar_back(main_window, qapp):
    series = main_window.series
    stored = series.getOption("scale_bar_width")
    dlg = AllOptionsDialog(main_window, series)
    _slider(dlg).setValue(90 if stored != 90 else 40)
    qapp.processEvents()

    dlg.reject()
    qapp.processEvents()

    assert main_window.mouse_palette.sb.width() == _expected(main_window, stored)


def test_ok_keeps_the_previewed_size(main_window, qapp):
    series = main_window.series
    stored = series.getOption("scale_bar_width")
    target = 70 if stored != 70 else 35
    dlg = AllOptionsDialog(main_window, series)
    _slider(dlg).setValue(target)

    assert dlg.accept() is True
    main_window.mouse_palette.reset()       # what allOptions() runs after OK

    assert series.getOption("scale_bar_width") == target
    assert main_window.mouse_palette.sb.width() == _expected(main_window, target)


def test_a_pinned_bar_ignores_the_width_preview(main_window, qapp):
    series = main_window.series
    series.setOption("scale_bar_mode", "micron_pinned")
    series.setOption("scale_bar_length_um", 5.0)
    main_window.mouse_palette.reset()
    before = main_window.mouse_palette.sb.width()

    main_window.mouse_palette.previewScaleBarWidth(100)

    assert main_window.mouse_palette.sb.width() == before


def test_a_dialog_with_no_window_behind_it_does_not_mind(qapp, main_window):
    series = main_window.series
    dlg = AllOptionsDialog(None, series)   # tests build it this way
    _slider(dlg).setValue(50)
    dlg.reject()                            # must not raise


@pytest.mark.parametrize("hidden", [False, True])
@pytest.mark.parametrize("pinned", [False, True])
def test_cancel_preserves_scale_bar_and_visibility(main_window, qapp, qtbot, hidden, pinned):
    """Cancel restores size without replacing the bar or losing its hide menu."""
    from PySide6.QtCore import QCoreApplication, QEvent

    series = main_window.series
    if pinned:
        series.setOption("scale_bar_mode", "micron_pinned")
        series.setOption("scale_bar_length_um", 5.0)
        main_window.mouse_palette.reset()
    palette = main_window.mouse_palette
    if palette.sb_hidden != hidden:
        palette.toggleSB()
    original = palette.sb
    original_width = original.width()
    original_policy = original.contextMenuPolicy()
    count = len(main_window.findChildren(type(original)))
    assert original.property("pyrecon_hide_menu")
    assert original.isHidden() == hidden

    for _ in range(3):
        dialog = AllOptionsDialog(main_window, series)
        qtbot.addWidget(dialog)
        slider = _slider(dialog)
        slider.setValue(70 if slider.value() != 70 else 40)
        dialog.reject()
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        assert palette.sb.isHidden() == hidden
        assert palette.sb_hidden == hidden
        assert len(main_window.findChildren(type(original))) == count
        assert palette.sb is original
        assert original.width() == original_width
        assert original.contextMenuPolicy() == original_policy
        assert original.property("pyrecon_hide_menu")
