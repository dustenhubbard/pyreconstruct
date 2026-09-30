from PySide6.QtWidgets import QTableWidget, QApplication
from PySide6.QtCore import Qt, QEvent

from PyReconstruct.modules.gui.utils import lessThan
from PyReconstruct.modules.backend.func import make_unique_id
    
ARROW_KEYS = (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down)


def claimsArrowKey(event) -> bool:
    """Claim an arrow key for a focused list before a window shortcut takes it.

    The field's nudge shortcuts (arrow keys, with or without Ctrl or Shift) are
    added to the main window, and every list is a dock inside that window, so
    they fired while a list had focus: the selected traces or the section
    transform moved and the list row did not. Accepting the ShortcutOverride
    tells Qt the focused list wants the key itself, so the shortcut does not
    fire and the key moves through the list as it does in any other view.

        Params:
            event (QEvent): the event the view received
        Returns:
            (bool): True if the event was an arrow key override and was accepted
    """
    if event.type() == QEvent.ShortcutOverride and event.key() in ARROW_KEYS:
        event.accept()
        return True
    return False


class CopyTableWidget(QTableWidget):

    def __init__(self, container, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.container = container
        self.id = make_unique_id()

    def event(self, event):
        if claimsArrowKey(event):
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        ret = super().keyPressEvent(event)
        # override the table copy function
        if event.key() == Qt.Key_C and (event.modifiers() & Qt.ControlModifier):
            self.copy()
        return ret

    def copy(self):
        """Copy table data onto the clipboard."""
        indexes = sorted(self.selectedIndexes())
        if indexes:
            clipboard_str = ""
            row = indexes[0].row()
            row_list = []
            for index in indexes:
                if index.row() > row:
                    clipboard_str += "\t".join(row_list) + "\n"
                    row_list = []
                    row = index.row()
                row_list.append(self.itemFromIndex(index).text())
            clipboard_str += "\t".join(row_list) + "\n"
            QApplication.clipboard().setText(clipboard_str)
    
    def getRowIndex(self, name : str):
        """Get the row index of an item in the table (or where it SHOULD be on the table).
        
            Parmas:
                name (str): the name of the item
            Returns:
                (int): the row index for that object in the table
                (bool): whether or not the object actually exists in the table
        """
        for row_index in range(self.rowCount()):
            row_name = self.item(row_index, 0).text()
            if lessThan(name, row_name):
                return row_index, False
            elif name == row_name:
                return row_index, True
        return self.rowCount(), False

    def backspace(self):
        """Called when backspace is pressed.

        Extended in container classes.
        """
        return
    
    def resizeColumnToContents(self, c : int):
        super().resizeColumnToContents(c)

        try:
            series = getattr(self.parent().parent(), "series")
        except AttributeError:
            return
        
        if series.getOption("theme") == "qdark":
            w = self.columnWidth(c)
            self.setColumnWidth(c, w + 8)
    
    def resizeColumnsToContents(self):
        super().resizeColumnsToContents()

        try:
            series = getattr(self.parent().parent(), "series")
        except AttributeError:
            return
        
        if series.getOption("theme") == "qdark":
            for c in range(self.columnCount()):
                w = self.columnWidth(c)
                self.setColumnWidth(c, w + 8)
