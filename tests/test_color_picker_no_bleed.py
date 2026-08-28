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

# How much of the picker may be painted in the swatch color. A scoped rule
# measures exactly 0.0 here; the bleed measures 0.53. The margin is for
# antialiasing on platforms with a different style, not for a real bleed.
MAX_SWATCH_FRACTION = 0.01


@pytest.fixture
def button(qapp):
    from PyReconstruct.modules.gui.dialog.color_button import ColorButton

    button = ColorButton(SWATCH, None)
    button.resize(60, 30)
    button.show()
    yield button
    button.deleteLater()


def swatch_fraction(button):
    """How much of the picker dialog is painted in the swatch color.

    Counted across the whole grab rather than sampled at one point, and that
    is the whole point of this helper. This file used to read the dialog's
    center pixel, which lands on the hue-gradient child: that child paints
    its own content over anything it inherits, so the pixel read (200, 183,
    190) whether or not the bleed was there. Three of the four tests below
    therefore passed with the bug present, against what this module's
    docstring promised (found 2026-08-27).

    Measured on this branch, same dialog, strided by 3: a scoped rule gives
    0.0, and the pre-#329 unscoped rule gives 0.53.
    """
    from PySide6.QtWidgets import QColorDialog

    dialog = QColorDialog(button)
    dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
    dialog.resize(400, 300)
    dialog.show()
    try:
        image = dialog.grab().toImage()
        hits = total = 0
        for y in range(0, image.height(), 3):
            for x in range(0, image.width(), 3):
                color = image.pixelColor(x, y)
                total += 1
                if (color.red(), color.green(), color.blue()) == SWATCH:
                    hits += 1
        return hits / total if total else 0.0
    finally:
        dialog.deleteLater()


def assert_no_bleed(button, where):
    fraction = swatch_fraction(button)
    assert fraction <= MAX_SWATCH_FRACTION, (
        f"{fraction:.0%} of the picker is painted in the swatch color "
        f"({where}); the style rule lost its class scope and cascaded into "
        "the dialog parented to the button"
    )


def test_the_style_rule_is_scoped_to_the_class(button):
    sheet = button.styleSheet()
    assert "background-color" in sheet
    assert sheet.strip().startswith("ColorButton {"), (
        "the rule lost its class scope; unscoped it cascades into the "
        "picker dialog parented to this button (the original bleed)"
    )


def test_the_picker_does_not_inherit_the_swatch_color(qapp, button):
    assert_no_bleed(button, "default theme")


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
        assert_no_bleed(button, "qdark theme")
    finally:
        app.setStyleSheet(old)
        qapp.processEvents()


def test_mixed_split_rule_is_scoped_too(qapp, button):
    button.setColor(SWATCH, mixed=True)
    assert button.styleSheet().strip().startswith("ColorButton {")
    assert_no_bleed(button, "mixed split rule")


def test_the_probe_can_actually_see_a_bleed(qapp, button):
    """The guard on the guard: prove the probe fails when the bug is present.

    Without this, a probe that always reads clean is indistinguishable from
    a picker that is always clean, which is exactly the trap the center-pixel
    version fell into. The pre-#329 rule is applied here deliberately, on a
    throwaway button, and the probe must light up.
    """
    button.setStyleSheet(f"background-color: rgb{SWATCH}")  # unscoped: the bug

    assert swatch_fraction(button) > 0.25
