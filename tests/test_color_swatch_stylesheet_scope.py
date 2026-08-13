"""The swatch's style rule must stay on the swatch.

The bug this pins, reported with screenshots from three users on Windows and
macOS: pick a color for a trace or a flag, reopen the picker, and the picker's
entire window is painted the color that was applied last (solid yellow, solid
green, solid purple). One report had circulated for a week as a suspected
Windows platform defect before this explanation was found; the purple
screenshot was that report.

The mechanism is Qt's stylesheet cascade. ``ColorButton.setColor`` painted the
swatch with a bare ``background-color:rgb(...)`` declaration, and a
selector-less declaration applies to the widget *and every descendant*.
``selectColor`` parents its ``QColorDialog`` to the button on purpose (the
parenting is load-bearing; see that method's docstring), which makes the
picker a descendant, so the whole dialog inherited the swatch's background.
The fix scopes the declaration with a class selector, which matches only
``ColorButton`` itself.

These tests render real widgets offscreen and read pixels back, because the
inherited background never appears in the dialog's own ``styleSheet()``
property; the cascade is only visible in what actually gets painted.
"""

import pytest

# No `importorskip("pytestqt")`: see tests/conftest.py's collection guard.
pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QColorDialog, QWidget

from PyReconstruct.modules.gui.dialog.color_button import ColorButton

YELLOW = (255, 255, 0)
RED = (255, 0, 0)


def _rgb(image, x, y):
    c = image.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


@pytest.fixture
def parent(qapp):
    w = QWidget()
    yield w
    w.deleteLater()


def test_picker_does_not_inherit_the_swatch_color(parent):
    """A picker parented to a yellow swatch must not open painted yellow.

    The dialog is constructed exactly as ``selectColor`` constructs it:
    parented to the button, native dialog off. Its corner pixels are dialog
    background (no child widget is laid out flush into a corner), so under
    the cascade every one of them read back as the swatch color.
    """
    button = ColorButton(YELLOW, parent)
    dlg = QColorDialog(button)
    dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
    try:
        dlg.resize(600, 420)
        img = dlg.grab().toImage()
        w, h = img.width(), img.height()
        corners = [(1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)]
        leaked = [xy for xy in corners if _rgb(img, *xy) == YELLOW]
        assert not leaked, (
            f"picker background inherited the swatch color at {leaked}"
        )
    finally:
        dlg.deleteLater()


def _dist(rgb_a, rgb_b):
    return sum((a - b) ** 2 for a, b in zip(rgb_a, rgb_b)) ** 0.5


def test_swatch_itself_still_paints_the_color(parent):
    """Scoping must not cost the swatch its fill; its face reads as the color.

    Not pixel-equality: button styles blend a bevel into the fill (measured
    offscreen, a yellow swatch's center reads back around (252, 252, 87)).
    The property that matters is that a yellow swatch is unmistakably yellow,
    so its center must sit far closer to yellow than a blank swatch's center
    does.
    """
    blank = ColorButton(None, parent)
    blank.resize(48, 24)
    blank_center = _rgb(blank.grab().toImage(), 24, 12)

    button = ColorButton(YELLOW, parent)
    button.resize(48, 24)
    center = _rgb(button.grab().toImage(), 24, 12)

    assert _dist(center, YELLOW) < 120
    assert _dist(center, YELLOW) < _dist(blank_center, YELLOW) / 2


def test_the_rule_always_declares_a_border(parent):
    """Every colored rule carries a border declaration. Load-bearing.

    With only ``background-color`` set, Qt's stylesheet renderer delegates
    the button bezel to the underlying style, and under the app's real
    style stack (cocoa's "macos" style wrapped in run.py's
    MenuShortcutSpacingStyle proxy) the native bezel is drawn OVER the
    fill: measured on the live app's screen pixels, a yellow swatch read
    back as plain button gray while its picker opened correctly seeded,
    which is exactly the user report. The offscreen platform this suite
    runs on paints the background-only rule fine, proxy installed or not
    (measured: (252, 252, 87) both ways), so no pixel assertion here can
    catch the regression; the border's presence in the rule is the
    property that defeats the failure mode, so that is what gets pinned.
    Same blind-spot pattern as RecordingColorDialog.setOption in
    test_color_picker_dismissal.py.
    """
    solid = ColorButton(YELLOW, parent)
    assert "border" in solid.styleSheet()
    split = ColorButton(YELLOW, parent, mixed=True)
    assert "border" in split.styleSheet()


def test_blank_color_clears_the_previous_rule(parent):
    """A swatch handed a blank color must not keep showing the old one.

    ``setColor`` used to return early on a falsy color, leaving the previous
    stylesheet (and so the previous color) in place on a swatch whose stored
    attribute was by then blank.
    """
    button = ColorButton(RED, parent)
    button.setColor(None)
    assert button.styleSheet() == ""
    button.resize(48, 24)
    img = button.grab().toImage()
    assert _rgb(img, img.width() // 2, img.height() // 2) != RED
