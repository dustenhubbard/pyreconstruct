"""The color picker must never inherit its swatch's color.

An unverified 1.22.0 report says the "entire picker painted in the swatch
color" bug is back. The 1.21.2 fix (#329) scoped ColorButton's style rule to
the class, and that rule is what keeps the picker clean: the picker dialog is
PARENTED to the button (load-bearing for modality), so an unscoped
background-color would cascade into it.

These tests would fail if the bleed existed, on the default theme and under
the qdark stylesheet, and they pin the scoping itself so a future edit that
drops the class selector fails here rather than in a user's screenshot.
"""

import pytest

pytestmark = pytest.mark.gui

SWATCH = (0, 249, 0)   # the lurid green from the original report


@pytest.fixture
def button(qapp):
    from PyReconstruct.modules.gui.dialog.color_button import ColorButton

    button = ColorButton(SWATCH, None)
    button.resize(60, 30)
    button.show()
    yield button
    button.deleteLater()


def _dialog_center_is_not_swatch(button):
    from PySide6.QtWidgets import QColorDialog

    dialog = QColorDialog(button)
    dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
    dialog.resize(400, 300)
    dialog.show()
    try:
        image = dialog.grab().toImage()
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        return (center.red(), center.green(), center.blue()) != SWATCH
    finally:
        dialog.deleteLater()


def test_the_style_rule_is_scoped_to_the_class(button):
    sheet = button.styleSheet()
    assert "background-color" in sheet
    assert sheet.strip().startswith("ColorButton {"), (
        "the rule lost its class scope; unscoped it cascades into the "
        "picker dialog parented to this button (the original bleed)"
    )


def test_the_picker_does_not_inherit_the_swatch_color(qapp, button):
    assert _dialog_center_is_not_swatch(button)


def test_no_bleed_under_the_dark_theme_either(qapp, button):
    """The dark theme swaps the app stylesheet wholesale; the swatch rule
    must stay scoped there too."""
    qdarkstyle = pytest.importorskip("qdarkstyle")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    old = app.styleSheet()
    try:
        app.setStyleSheet(qdarkstyle.load_stylesheet_pyside6())
        qapp.processEvents()
        button.setColor(SWATCH)
        assert _dialog_center_is_not_swatch(button)
    finally:
        app.setStyleSheet(old)
        qapp.processEvents()


def test_mixed_split_rule_is_scoped_too(qapp, button):
    button.setColor(SWATCH, mixed=True)
    assert button.styleSheet().strip().startswith("ColorButton {")
    assert _dialog_center_is_not_swatch(button)
