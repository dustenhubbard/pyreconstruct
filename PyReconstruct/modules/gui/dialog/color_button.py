from PySide6.QtWidgets import QColorDialog, QDialog, QPushButton
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
        """
        initial = QColor(*self.color) if self.color else QColor(Qt.white)
        dlg = QColorDialog(self)
        dlg.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dlg.setCurrentColor(initial)
        try:
            confirmed = dlg.exec() == QDialog.DialogCode.Accepted
            color = dlg.selectedColor()
        finally:
            # parented to the button, so without this every click on the swatch
            # leaves another dialog alive for as long as the button is
            dlg.deleteLater()
        if confirmed and color.isValid():
            self.setColor((color.red(), color.green(), color.blue()))
    
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