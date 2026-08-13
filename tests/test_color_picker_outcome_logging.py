"""How the colour picker was closed must be readable from the log afterwards.

A Windows user reported, against the Set Attributes dialog: "The color remains
blank even though I set a color green." The report could not be diagnosed from
here, and the reason is structural: every way of closing the picker without OK
-- the Cancel button, the title-bar close, Esc -- comes back from
``QColorDialog`` as the same invalid colour, and ``ColorButton.selectColor``
then (correctly, for Cancel) does nothing, silently. "The user cancelled",
"the user picked a colour and the dismissal discarded it", and "OK itself
misbehaved" were all indistinguishable, both in the app and in the log.

These tests pin the diagnostic contract that closes that gap: every picker
interaction writes exactly one line to the log (via ``log_note``, so it lands
in the per-user log file the Help menu exposes), the line names how the dialog
was closed, and a dismissal's line records the colour the picker was showing
at that moment. That last datum is the discriminator: a future "I set green
and nothing happened" report either shows ``dismissed ... showing
rgb(0,255,0)`` (the colour reached the dialog and the dismissal dropped it),
or ``accepted, applying rgb(0,255,0)`` (the picker did its job and the fault
is in the swatch), or an ``accepted but the colour is invalid`` line (the
platform dialog broke its own contract). One log line replaces a guessing
game.

The Cancel-vs-close distinction is read from the widget dialog's own Cancel
button, which exists whenever Qt's own dialog is in use. The offscreen
platform this suite runs on has no native colour dialog, so it builds the Qt
widget dialog through the identical no-platform-helper branch Windows takes
(Qt 6.5.2 ships no native colour dialog on Windows; the ``ChooseColorW``
wrapper is compiled out) -- which makes these offscreen runs exercise the
Windows-relevant paths, not an approximation of them.

The dialogs driven here are real ``QColorDialog``s: the gestures click the
dialog's actual OK/Cancel buttons or call ``reject()``, which is the slot
both Esc (``QDialog::keyPressEvent``) and the title-bar close
(``QDialog::closeEvent``) invoke. Only ``exec()`` is overridden, to perform
one gesture instead of blocking on a modal loop.
"""

import pytest

# No `importorskip("pytestqt")`: see tests/conftest.py's collection guard.
pytestmark = pytest.mark.gui

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialogButtonBox, QWidget

from PyReconstruct.modules.gui.dialog import color_button as color_button_module
from PyReconstruct.modules.gui.dialog.color_button import ColorButton

GREEN = (0, 255, 0)
RED = (255, 0, 0)


class DrivenColorDialog(QColorDialog):
    """A real ``QColorDialog`` whose ``exec()`` performs one gesture and returns.

    Everything else -- the button box, the accept/reject slots,
    ``selectedColor()``'s set-on-accept/invalid-on-reject behaviour -- is Qt's
    own, so what the tests exercise is the dialog's real closing machinery,
    not a stub's imitation of it.
    """

    gesture = None  # set per test: a callable taking the dialog

    def exec(self):
        type(self).gesture(self)
        return self.result()


def _button(dlg, which):
    return dlg.findChild(QDialogButtonBox).button(which)


def press_ok(dlg):
    """Pick green, then click the dialog's real OK button."""
    dlg.setCurrentColor(QColor(*GREEN))
    _button(dlg, QDialogButtonBox.StandardButton.Ok).click()


def press_cancel(dlg):
    """Pick green, then click the dialog's real Cancel button."""
    dlg.setCurrentColor(QColor(*GREEN))
    _button(dlg, QDialogButtonBox.StandardButton.Cancel).click()


def dismiss_without_buttons(dlg):
    """Pick green, then close the dialog the way Esc and the title-bar X do."""
    dlg.setCurrentColor(QColor(*GREEN))
    dlg.reject()


@pytest.fixture
def pick_with(qapp, monkeypatch):
    """Route ``selectColor`` through a driven dialog performing one gesture."""

    def _pick_with(gesture):
        monkeypatch.setattr(DrivenColorDialog, "gesture", gesture)
        monkeypatch.setattr(
            color_button_module, "QColorDialog", DrivenColorDialog
        )

    return _pick_with


@pytest.fixture
def parent(qapp):
    w = QWidget()
    yield w
    w.deleteLater()


def _picker_lines(capsys):
    err = capsys.readouterr().err
    return [line for line in err.splitlines() if "Colour picker:" in line]


# --- one line per interaction, naming how the dialog was closed ------------


def test_ok_logs_the_applied_colour(pick_with, parent, capsys):
    pick_with(press_ok)
    button = ColorButton(RED, parent)

    button.selectColor()

    lines = _picker_lines(capsys)
    assert len(lines) == 1, lines
    assert "accepted, applying rgb(0,255,0)" in lines[0]
    # and the behaviour the line reports actually happened
    assert button.getColor() == GREEN


def test_cancel_is_named_as_cancel(pick_with, parent, capsys):
    pick_with(press_cancel)
    button = ColorButton(RED, parent)

    button.selectColor()

    lines = _picker_lines(capsys)
    assert len(lines) == 1, lines
    assert "Cancel pressed" in lines[0]
    assert "dismissed" not in lines[0], (
        "an explicit Cancel must not be reported as an ambiguous dismissal, "
        "or the line stops discriminating anything"
    )
    assert button.getColor() == RED


def test_dismissal_records_the_colour_it_discarded(pick_with, parent, capsys):
    """The line that turns the reported symptom into a diagnosis.

    ``reject()`` is what both Esc and the title-bar close invoke, and it is
    indistinguishable from Cancel in the dialog's return value. The log line
    is the only artifact that (a) says the close was not the Cancel button and
    (b) records that green was showing when it happened -- which is exactly
    the "I set a color green and it remains blank" scenario, witnessed.
    """
    pick_with(dismiss_without_buttons)
    button = ColorButton(RED, parent)

    button.selectColor()

    lines = _picker_lines(capsys)
    assert len(lines) == 1, lines
    assert "dismissed without OK or Cancel" in lines[0]
    assert "rgb(0,255,0)" in lines[0], (
        "the dismissal line must record the colour the picker was showing, "
        "or it cannot distinguish 'discarded a picked colour' from 'closed "
        "an untouched picker'"
    )
    assert "NOT applied" in lines[0]
    assert button.getColor() == RED


# --- the logging is an observer: behaviour itself is unchanged -------------


def test_ok_still_applies_and_paints(pick_with, parent):
    pick_with(press_ok)
    button = ColorButton(RED, parent)

    button.selectColor()

    assert button.getColor() == GREEN
    assert "background-color:rgb(0,255,0)" in button.styleSheet()


def test_cancel_still_leaves_the_colour_alone(pick_with, parent):
    pick_with(press_cancel)
    button = ColorButton(RED, parent)

    button.selectColor()

    assert button.getColor() == RED
    assert "background-color:rgb(255,0,0)" in button.styleSheet()


def test_dismissal_still_leaves_a_blank_swatch_blank(pick_with, parent):
    pick_with(dismiss_without_buttons)
    button = ColorButton(None, parent)

    button.selectColor()

    assert button.getColor() is None


def test_picker_still_opens_on_the_buttons_colour(pick_with, parent):
    """The explicit dialog must mirror the getColor() static it replaced."""
    seen = []

    def record_and_cancel(dlg):
        seen.append(dlg.currentColor().getRgb()[:3])
        _button(dlg, QDialogButtonBox.StandardButton.Cancel).click()

    pick_with(record_and_cancel)
    button = ColorButton(RED, parent)

    button.selectColor()

    assert seen == [RED]
