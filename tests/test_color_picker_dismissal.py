"""``ColorButton`` must own the colour picker it opens.

The bug this pins, reported by a user against the "Set Attributes" dialog and
reproduced on macOS before the fix: *"The color remains blank even though I set
a color green."*

``selectColor`` called ``QColorDialog.getColor()``. On macOS that static does
not open a Qt dialog at all -- Qt hands the request to the platform theme, which
shows the shared system "Colors" panel (verified on PySide6 6.5.2, cocoa: the
``QColorDialog`` widget comes up carrying ``Qt.WA_DontShowOnScreen`` while an
``NSColorPanel`` titled "Colors" appears elsewhere on screen). That panel is the
live-apply picker every other Mac app uses, so the gesture it invites is "click
a colour, close the panel". Driven exactly that way through the real widget --
pick the "Spring" crayon, which is pure green, then close the panel with its
close button -- ``getColor()`` returned an **invalid** ``QColor``, ``selectColor``
silently did nothing, and the swatch stayed blank. Confirmed the same run that
the OK button Qt bolts onto the panel does work: the same crayon plus a click on
OK came back as ``(0, 249, 0)`` and painted the swatch. So nothing was corrupted
and nothing about green was special -- the colour simply never entered the
application, for any colour, on any dismissal that was not that one button.

That is not fixable while the platform owns the dialog: "closed the panel" and
"pressed Cancel" arrive as the same rejection, so keeping the first would break
the second. The fix is for this widget to open Qt's own dialog, which is modal,
parented, and carries OK inside its own window.

These tests therefore assert the property that the platform panel cannot have:
the dialog ``selectColor`` opens is one this code constructed, with the native
dialog turned off, parented to the button. Plus the two end-to-end behaviours
that property exists to protect -- an accepted colour reaches both the stored
attribute and the painted swatch, and a dismissed one changes neither.

The offscreen platform used by the suite has no native colour dialog, so a test
that merely drove the picker here would have passed against the broken code.
Asserting the option is what makes this catch the macOS bug from Linux and CI.

That same blind spot bites a second time, one layer up, and the tests under
"the picker must open on the colour it is editing" are the answer to it.
Switching off the native dialog is only half the job: the Qt dialog has to be
seeded with the colour the swatch already holds, and on macOS a dialog
constructed *before* the native path is switched off loses that seed and opens
on white. Pressing OK without changing anything then repaints the trace white,
which is the reported symptom again by another route -- and worse than the
original, which at least left the stored colour alone. Because offscreen has no
native dialog to switch away from, every ordering looks correct here, so
``RecordingColorDialog.setOption`` reproduces the discard rather than the tests
merely asserting around it. See that method's docstring for the measurements.
"""

import pytest

# No `importorskip("pytestqt")`: see tests/conftest.py's collection guard.
pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialog, QWidget

from PyReconstruct.modules.gui.dialog import color_button as color_button_module
from PyReconstruct.modules.gui.dialog.color_button import ColorButton

GREEN = (0, 255, 0)
RED = (255, 0, 0)


class RecordingColorDialog(QColorDialog):
    """A real ``QColorDialog`` whose ``exec`` returns instead of blocking.

    A subclass and not a stub, so ``setOption``/``options`` are Qt's own and the
    assertion about the native-dialog flag is about the real dialog state.

    ``getColor`` is overridden as well, and that override is the trap: it is the
    static the broken version called. If ``selectColor`` ever routes back
    through it the call is recorded, and it returns the invalid ``QColor`` that
    a dismissed platform panel returns, so the failure is the real one rather
    than a test that hangs on a modal loop.

    ``setOption`` reproduces one cocoa behaviour the suite's platform cannot
    show; see its docstring, which is what lets the sequencing bug below be
    caught from CI.
    """

    static_calls = []
    execs = []
    chosen = QColor(*GREEN)
    result_code = QDialog.DialogCode.Accepted

    def setOption(self, option, on=True):
        """Model cocoa discarding the seed when the native path is switched off.

        On macOS a ``QColorDialog`` constructed while the native path is still
        allowed routes its initial colour into the platform helper. Turning
        ``DontUseNativeDialog`` on *afterwards* switches to the Qt widget
        implementation, which was never seeded and sits at its own default of
        white. Measured on cocoa, PySide6 6.5.2 / Qt 6.5.2: constructing with
        ``(0, 249, 0)`` and then flipping the option leaves ``currentColor()``
        at ``(255, 255, 255)``, and the same for every other seed tried.

        This has to be modelled rather than merely asserted around, because the
        offscreen platform the suite runs on has **no** native colour dialog, so
        there the flip is a no-op and every constructor ordering preserves the
        colour. Measured, same script, ``QT_QPA_PLATFORM=offscreen``: all four
        orderings return ``(0, 249, 0)``. So a test that only asserted
        ``currentColor()`` at ``exec()`` time -- the obvious pin, and the one a
        review of this fix proposed -- would have passed against the broken
        order under CI and caught nothing. Reproducing the discard is what makes
        the ordering visible from a platform that has no native dialog to lose.

        This is the same blind spot the module docstring describes for the
        original bug, one layer up: the platform difference is invisible here,
        so the test has to encode it.
        """
        super().setOption(option, on)
        if on and option == QColorDialog.ColorDialogOption.DontUseNativeDialog:
            super().setCurrentColor(QColor(Qt.white))

    def exec(self):
        type(self).execs.append(
            {
                "options": self.options(),
                "parent": self.parent(),
                # what the picker actually opened on, i.e. what the user sees
                "currentColor": self.currentColor().getRgb()[:3],
            }
        )
        # ``chosen = None`` means "the user changed nothing and pressed OK",
        # which is the gesture that loses the colour when the seeding is wrong.
        if type(self).chosen is not None:
            self.setCurrentColor(type(self).chosen)
        self.done(type(self).result_code)
        return type(self).result_code

    @staticmethod
    def getColor(*args, **kwargs):
        RecordingColorDialog.static_calls.append(args)
        return QColor()


@pytest.fixture
def picker(qapp, monkeypatch):
    """Drive ``ColorButton.selectColor`` without a modal loop."""
    RecordingColorDialog.static_calls = []
    RecordingColorDialog.execs = []
    RecordingColorDialog.chosen = QColor(*GREEN)
    RecordingColorDialog.result_code = QDialog.DialogCode.Accepted
    monkeypatch.setattr(
        color_button_module, "QColorDialog", RecordingColorDialog
    )
    return RecordingColorDialog


@pytest.fixture
def parent(qapp):
    w = QWidget()
    yield w
    w.deleteLater()


def _painted_channel(button):
    """Which channel dominates the colour actually painted on the swatch.

    Not an exact pixel match, deliberately. The swatch is a ``QPushButton``
    whose colour is a ``background-color`` stylesheet, and how much of the
    button's own painting survives on top of it is a style decision: under the
    macOS style the centre pixel is the requested colour exactly, while under
    Fusion (which is what the offscreen platform gives the suite) the button
    gradient lightens pure green to ``(99, 252, 99)``. The dominant channel is
    the part that is about the colour rather than about the style, and it is
    what a user means by "the swatch is green".
    """
    button.resize(40, 24)
    image = button.grab().toImage()
    rgb = image.pixelColor(image.width() // 2, image.height() // 2).getRgb()[:3]
    return rgb.index(max(rgb)), rgb


# --- the property the platform panel cannot have ---------------------------


def test_picker_is_a_dialog_this_code_owns(picker, parent):
    """Not the platform's panel: Qt's, non-native, parented to the button."""
    button = ColorButton(None, parent)

    button.selectColor()

    assert not picker.static_calls, (
        "selectColor went back through the static QColorDialog.getColor(), "
        "which on macOS opens the system Colors panel instead of a Qt dialog"
    )
    assert len(picker.execs) == 1
    opened = picker.execs[0]
    assert opened["options"] & QColorDialog.ColorDialogOption.DontUseNativeDialog, (
        "the picker may use the platform's colour panel, whose close button "
        "discards the colour the user picked"
    )
    assert opened["parent"] is button, (
        "an unparented picker opens wherever the system last left it, not over "
        "the dialog that spawned it"
    )


# --- the picker must open on the colour it is editing ----------------------
#
# Switching the picker off the platform's panel is only half the job: the Qt
# dialog has to be *seeded* with the colour the swatch already holds, and the
# seeding has to survive turning the native path off. Get the order wrong and
# the picker opens on white, so the most natural gesture in the dialog -- open
# it, see the colour is fine, press OK -- silently repaints the trace white.
# From the user's chair that is the reported bug again: the swatch went blank.
# Worse, in fact, than the original, which at least left the stored colour
# alone; this writes a wrong one.


def test_picker_opens_on_the_buttons_current_colour(picker, parent):
    """Not on white: the colour the user is about to edit."""
    button = ColorButton(RED, parent)

    button.selectColor()

    assert picker.execs[0]["currentColor"] == RED, (
        "the picker opened on the wrong colour, so the trace's own colour is "
        "not what the user is offered -- set DontUseNativeDialog before "
        "seeding the colour, not after"
    )


def test_ok_without_changing_anything_leaves_the_colour_alone(picker, parent):
    """The whole point: OK on an untouched picker is not a colour change."""
    picker.chosen = None  # the user changed nothing, then pressed OK
    button = ColorButton(RED, parent)

    button.selectColor()

    assert button.getColor() == RED, (
        "pressing OK without touching anything rewrote the trace's colour"
    )
    assert button.styleSheet() == "ColorButton { background-color:rgb(255,0,0) }"
    channel, rgb = _painted_channel(button)
    assert channel == 0, f"the swatch is no longer red: {rgb}"


# --- what that property protects -------------------------------------------


def test_accepted_colour_is_stored_and_painted(picker, parent):
    button = ColorButton(None, parent)

    button.selectColor()

    assert button.getColor() == GREEN
    assert button.styleSheet() == "ColorButton { background-color:rgb(0,255,0) }"
    channel, rgb = _painted_channel(button)
    assert channel == 1, f"the swatch is not green: {rgb}"


def test_accepted_colour_replaces_an_existing_one(picker, parent):
    button = ColorButton(RED, parent)

    button.selectColor()

    assert button.getColor() == GREEN
    assert button.styleSheet() == "ColorButton { background-color:rgb(0,255,0) }"
    channel, rgb = _painted_channel(button)
    assert channel == 1, f"the swatch is not green: {rgb}"


def test_dismissed_picker_leaves_a_blank_swatch_blank(picker, parent):
    picker.result_code = QDialog.DialogCode.Rejected
    button = ColorButton(None, parent)

    button.selectColor()

    assert button.getColor() is None


def test_dismissed_picker_leaves_an_existing_colour_alone(picker, parent):
    picker.result_code = QDialog.DialogCode.Rejected
    button = ColorButton(RED, parent)

    button.selectColor()

    assert button.getColor() == RED
    assert button.styleSheet() == "ColorButton { background-color:rgb(255,0,0) }"
    channel, rgb = _painted_channel(button)
    assert channel == 0, f"the swatch is no longer red: {rgb}"
