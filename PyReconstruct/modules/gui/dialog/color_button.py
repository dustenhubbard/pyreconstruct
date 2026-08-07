from PySide6.QtWidgets import QColorDialog, QDialog, QDialogButtonBox, QPushButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

class ColorButton(QPushButton):

    def __init__(self, color : tuple, parent):
        """Create the color button widget.

            Params:
                color (tuple): the color for the button
                parent (QWidget): the parent widget for the button
        """
        super().__init__(parent)
        self.color = color
        self.setColor(color)
        self.clicked.connect(self.selectColor)

    def selectColor(self):
        """Called when button is clicked: prompts user to change color.

        Qt's own dialog, never the platform's, and that is the whole point of
        this method rather than a one-line ``QColorDialog.getColor()``.

        On macOS ``getColor()`` substitutes the shared system "Colors" panel.
        That panel is the one every other Mac app uses as a *live-apply* picker:
        you click a colour and the thing you are colouring changes immediately,
        so you close the panel when you are done. Here nothing changes as you
        click -- the swatch behind it is only repainted from the return value --
        and closing the panel is a dismissal, so ``getColor()`` hands back an
        invalid ``QColor`` and the colour that was picked is dropped on the
        floor with no error and no visible effect. Reported by a user in exactly
        those terms: "the color remains blank even though I set a color green."
        Qt bolts OK/Cancel onto the bottom of that panel, so the choice *can* be
        confirmed, but the panel opens wherever the system last left it (a
        screen corner, far from this dialog) and looks like every live-apply
        colour panel on the machine, so the confirming click is the one step
        nothing prompts you to take.

        The Qt dialog has none of that: it is application-modal, it is parented
        to this button so it opens over the dialog that spawned it, and its OK
        button is inside its own window, so "picked a colour and left" is not a
        gesture it offers. It is also what Windows and Linux users already get,
        which is why this is the behaviour worth converging on rather than a
        macOS special case.

        The colour is still only committed on an accepted dialog: dismissing it
        leaves the swatch as it was, which is what Cancel has always meant here.

        The order below is load-bearing and is the reason this is not
        ``QColorDialog(initial, self)`` followed by ``setOption``. On macOS a
        ``QColorDialog`` constructed while the native path is still allowed
        routes its initial colour into the platform helper; turning
        ``DontUseNativeDialog`` on *afterwards* switches to the Qt widget
        implementation, which was never seeded and sits at its own default.
        Measured on cocoa, PySide6 6.5.2 -- constructing with ``(0, 249, 0)``
        and then flipping the option leaves ``currentColor()`` at
        ``(255, 255, 255)``, and the same holds for every seed tried, so the
        trace's colour is simply gone. A user who opened the picker on a green
        trace, saw the colour was fine and pressed OK got a white trace and a
        blank swatch -- the reported bug again, by another route, and worse,
        because this one *writes* the wrong colour rather than dropping the
        right one. So: turn the option off first, then seed.

        Diagnostics, added on top of the above and changing none of it: one log
        line is written per picker interaction (via ``log_note``, so it lands in
        the per-user log file Help > View log file... opens), saying how the
        picker was closed and what that did. It exists because the report above
        could not be diagnosed from the log -- every way of closing the picker
        without OK (the Cancel button, the title-bar close, Esc) comes back as
        the same invalid colour, so "cancelled on purpose", "picked a colour the
        dismissal discarded", and "OK misbehaved" were indistinguishable. A
        dismissal's line records the colour the picker was showing at that
        moment, which is the datum that separates them:

        - ``dismissed without OK ... showing rgb(0,255,0)``: the picked colour
          reached the dialog and was discarded by the dismissal; working as
          designed, but the user expected the close to commit.
        - ``accepted ... applying rgb(0,255,0)`` yet the swatch stayed blank:
          the picker is fine and the fault is in this widget's painting.
        - ``accepted but the colour is invalid``: the platform dialog broke its
          own contract; report to Qt.

        The Cancel-vs-close distinction is read from the dialog's own Cancel
        button, because both a Cancel click and a window close end in the same
        ``reject()``. ``DontUseNativeDialog`` is set above, so Qt's widget dialog
        -- and its ``QDialogButtonBox`` Cancel button -- is what is in use on
        every platform, macOS included; the button is therefore found and the
        distinction is available everywhere. The final ``else`` branch of
        ``_logPickerOutcome`` (a dismissal on a dialog with no Cancel button of
        Qt's to listen to) is a defensive fallback that is not reached while the
        option above holds.
        """
        initial = QColor(*self.color) if self.color else QColor(Qt.white)
        dlg = QColorDialog(self)
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dlg.setCurrentColor(initial)

        # The widget dialog's own Cancel button. Its clicked signal is the only
        # place "the user pressed Cancel" is distinguishable from "the user
        # closed the window" (title-bar close or Esc), because both end in the
        # same reject(). DontUseNativeDialog is on above, so Qt's widget dialog
        # -- and this button -- is in use on every platform, macOS included.
        cancel_clicked = []
        buttonbox = dlg.findChild(QDialogButtonBox)
        cancel_button = (
            buttonbox.button(QDialogButtonBox.StandardButton.Cancel)
            if buttonbox is not None else None
        )
        if cancel_button is not None:
            cancel_button.clicked.connect(lambda: cancel_clicked.append(True))

        try:
            confirmed = dlg.exec() == QDialog.DialogCode.Accepted
            color = dlg.selectedColor()
            showing = dlg.currentColor()
        finally:
            # parented to the button, so without this every click on the swatch
            # leaves another dialog alive for as long as the button is
            dlg.deleteLater()
        self._logPickerOutcome(
            confirmed, color, showing,
            explicit_cancel=bool(cancel_clicked),
            widget_dialog=cancel_button is not None,
        )
        if confirmed and color.isValid():
            self.setColor((color.red(), color.green(), color.blue()))

    @staticmethod
    def _logPickerOutcome(confirmed, color, showing, explicit_cancel, widget_dialog):
        """One line in the per-user log for each way the picker can close."""
        from PyReconstruct.modules.backend.func.logging_setup import log_note
        shown = f"rgb({showing.red()},{showing.green()},{showing.blue()})"
        if confirmed and color.isValid():
            log_note(
                "Colour picker: accepted, applying "
                f"rgb({color.red()},{color.green()},{color.blue()})"
            )
        elif confirmed:
            # Accepted dialogs return their current colour, which QColor can
            # always represent -- so this line means the colour dialog broke
            # its own contract, and a report containing it should go to Qt.
            log_note(
                "Colour picker: accepted but the colour is invalid -- "
                f"platform dialog fault, nothing applied (was showing {shown})"
            )
        elif explicit_cancel:
            log_note(
                f"Colour picker: Cancel pressed, nothing applied (was showing {shown})"
            )
        elif widget_dialog:
            log_note(
                "Colour picker: dismissed without OK or Cancel (title-bar "
                f"close or Esc) while showing {shown} -- that colour was NOT "
                "applied; only OK applies a colour"
            )
        else:
            # No Cancel button of Qt's to listen to, so a dismissal's source
            # cannot be identified, only its effect. Not reached while
            # DontUseNativeDialog is set in selectColor (Qt's widget dialog is
            # then always in use); kept as a defensive fallback.
            log_note(
                f"Colour picker: dismissed (no Cancel button) while showing {shown} "
                "-- that colour was NOT applied; only OK applies a colour"
            )

    def setColor(self, color):
        """Sets the visual color for the button."""
        self.color = color
        if color:
            s = f"({','.join(map(str,self.color))})"
            self.setStyleSheet(f"background-color:rgb{s}")

    def getColor(self):
        return self.color

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMaximumWidth(self.height() * 2)
