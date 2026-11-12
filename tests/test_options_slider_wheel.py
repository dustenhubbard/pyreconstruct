"""Scrolling options changes a slider only after it has focus."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QStyle, QStyleOptionSlider

from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog
from PyReconstruct.modules.gui.dialog.helper import SliderWidget
from tests.test_options_window_shape import series  # noqa: F401 (fixture)

pytestmark = pytest.mark.gui


@pytest.fixture(params=[("scale_bar", 0), ("scale_bar", 1), ("smoothing_3D", 0)])
def options_slider(qtbot, series, request):  # noqa: F811 (fixture)
    dialog = AllOptionsDialog(None, series)
    qtbot.addWidget(dialog)
    dialog.resize(dialog.width(), 450)
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    dialog.activateWindow()
    name, index = request.param
    wrapper = dialog.all_widgets[name].findChildren(SliderWidget)[index]
    slider = wrapper.slider
    wrapper.setValue((slider.minimum() + slider.maximum()) // 2)
    page = dialog.tabs.currentWidget()
    qtbot.wait(1)
    page.ensureWidgetVisible(slider)
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel).setFocus()
    qtbot.wait(1)
    assert not slider.hasFocus()
    yield dialog, page, wrapper


def _wheel(slider):
    window = slider.window()
    point = slider.mapTo(window, slider.rect().center())
    QTest.wheelEvent(window.windowHandle(), point, QPoint(0, -120))


def test_unfocused_slider_leaves_wheel_to_page(options_slider):
    dialog, page, wrapper = options_slider
    before = wrapper.value()
    position = page.verticalScrollBar().value()
    assert position < page.verticalScrollBar().maximum()
    _wheel(wrapper.slider)
    assert wrapper.value() == before
    assert not wrapper.slider.hasFocus()
    assert page.verticalScrollBar().value() > position


def test_click_drag_and_focused_wheel_still_change_slider(qtbot, options_slider):
    dialog, page, wrapper = options_slider
    slider = wrapper.slider
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(
        QStyle.CC_Slider, option, QStyle.SC_SliderHandle, slider,
    ).center()
    before = wrapper.value()
    qtbot.mousePress(slider, Qt.LeftButton, pos=handle)
    qtbot.mouseMove(slider, handle + QPoint(30, 0))
    qtbot.mouseRelease(slider, Qt.LeftButton, pos=handle + QPoint(30, 0))
    assert wrapper.value() > before
    assert slider.hasFocus()
    before = wrapper.value()
    qtbot.keyClick(slider, Qt.Key_Right)
    assert wrapper.value() == before + 1
    before = wrapper.value()
    position = page.verticalScrollBar().value()
    _wheel(slider)
    assert wrapper.value() < before
    assert page.verticalScrollBar().value() == position

    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel).setFocus()
    before = wrapper.value()
    _wheel(slider)
    assert wrapper.value() == before
    assert page.verticalScrollBar().value() > position
