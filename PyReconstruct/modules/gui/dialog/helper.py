
from PySide6.QtWidgets import (
    QWidget,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QRadioButton,
    QLabel,
    QApplication,
    QSlider,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QPainter,
    QPalette,
)

from .file_dialog import FileDialog

from PyReconstruct.modules.gui.utils import CompleterBox

def resizeLineEdit(le : QLineEdit, text : str):
    """Resize a line edit to fit a specific string.
    
        Params:
            le (QLineEdit): the widget to modify
            text (str): the string to resize the line edit
    """
    w = le.fontMetrics().boundingRect(text).width() + 10
    le.setFixedWidth(w)

class BrowseWidget(QWidget):

    def __init__(self, parent, type="file", default_fp="", filter=None):
        """Create the browse widget."""
        super().__init__(parent)
        self.type = type
        self.filter = filter
        self.le = QLineEdit(self, text=default_fp)
        self.bttn = QPushButton(self, text="Browse")
        self.bttn.clicked.connect(self.browse)
        layout = QHBoxLayout()
        layout.addWidget(self.le)
        layout.addWidget(self.bttn)
        self.setLayout(layout)
    
    def browse(self):
        """Change the selected folder."""
        response = None
        if self.type == "file":
            response = FileDialog.get(
                "file",
                self,
                "Find File",
                filter=self.filter
            )
        elif self.type == "dir":
            response = FileDialog.get(
                "dir",
                self,
                "Find Folder"
            )
        if response:
            self.le.setText(response)
    
    def text(self):
        """Get the displayed text."""
        return self.le.text()

class MultiInput(QWidget):

    def __init__(self, parent : QWidget, entries : list = None, combo=False, combo_items : list = [], restrict_to_opts=True):
        """Create the multi line edit widget."""
        super().__init__(parent)
        self.container = parent
        self.is_combo = combo

        # attributes only applicable to combobox
        self.combo_items = combo_items
        self.restrict_to_opts = restrict_to_opts

        vbl = QVBoxLayout()
        self.input_layout = QVBoxLayout()

        if not entries:
            entries = [""]
        
        self.inputs = []
        for entry in entries:
            if self.is_combo:
                w = CompleterBox(self, self.combo_items, allow_new=(not restrict_to_opts))
                w.setCurrentText(entry)
            else:
                w = QLineEdit(self, text=entry)
            self.input_layout.addWidget(w)
            self.inputs.append(w)
        vbl.addLayout(self.input_layout)

        # create the add/remove buttons
        #
        # Both take no focus on purpose: "-" removes the row the user is
        # editing, and it can only know which row that is if clicking the
        # button leaves the caret where it was.
        ar_row = QHBoxLayout()
        ar_row.addStretch(10)
        remove = QPushButton(self, text="-")
        remove.setFocusPolicy(Qt.NoFocus)
        remove.clicked.connect(self.remove)
        ar_row.addWidget(remove)
        add = QPushButton(self, text="+")
        add.setFocusPolicy(Qt.NoFocus)
        add.clicked.connect(self.add)
        ar_row.addWidget(add)
        vbl.addLayout(ar_row)

        self.setLayout(vbl)
    
    def add(self):
        """Add a line edit row to the field."""
        if self.is_combo:
            w = CompleterBox(self, self.combo_items, allow_new=(not self.restrict_to_opts))
        else:
            w = QLineEdit(self)
        self.input_layout.addWidget(w)
        self.inputs.append(w)
    
    def currentIndex(self):
        """Index of the row the user is editing, or the last row.

            Returns:
                (int) the index into self.inputs, -1 if the field has no rows
        """
        # an editable combobox is focused through its own line edit, so walk up
        # from the focused widget until the row itself is found
        w = QApplication.focusWidget()
        while w is not None:
            if w in self.inputs:
                return self.inputs.index(w)
            w = w.parentWidget()
        return len(self.inputs) - 1

    def remove(self):
        """Remove the row the user is editing (the last row by default).

        "-" used to pop the final row wherever the caret was, so fixing the
        first of several entries meant deleting every row after it and typing
        them again. The field also keeps one row alive: removing the only row
        clears its text instead, because a field with no line edit in it cannot
        be typed into at all.
        """
        if not self.inputs:
            return

        if len(self.inputs) == 1:
            if self.is_combo:
                self.inputs[0].setCurrentText("")
            else:
                self.inputs[0].setText("")
            return

        w = self.inputs.pop(self.currentIndex())
        self.input_layout.removeWidget(w)
        w.deleteLater()

        # Give the row's height back on this press rather than the next one.
        # removeWidget() only marks the layouts dirty and posts a layout
        # request, so both this field's size hint and the container's still
        # describe the layout with the removed row in it until that request is
        # delivered, which is after this slot has returned. adjustSize() on its
        # own therefore resizes to the previous row count's hint and leaves the
        # dialog one row too tall, showing a band of unused space. Activating
        # both layouts first makes the hints current: this field's so its own
        # hint drops, the container's so the window minimum drops with it.
        self.layout().activate()
        container_layout = self.container.layout()
        if container_layout is not None:
            container_layout.activate()
        self.container.adjustSize()

    def getEntries(self):
        """Get the strings input by the user."""
        l = []
        for w in self.inputs:
            t = w.currentText() if self.is_combo else w.text()
            if t: l.append(t)
        return l

def defaultTickInterval(minimum : int, maximum : int) -> int:
    """Pick a readable tick spacing for a slider range.

    Aims for roughly ten ticks across the groove and then rounds up to a round
    number, so an 0-100 slider ticks every 10 and a 20-100 slider every 10 as
    well, rather than at some spacing nobody would choose by hand.
    """
    span = abs(maximum - minimum)
    if span <= 0:
        return 1
    rough = span / 10
    for candidate in (1, 2, 5, 10, 20, 25, 50, 100):
        if rough <= candidate:
            return candidate
    return span


class SliderWidget(QWidget):
    """A horizontal slider that shows its tick marks and its current value.

    A bare QSlider tells the user nothing: the handle sits somewhere along a
    blank groove and the number actually being set is invisible. This pairs the
    slider with tick marks and a live readout in the *caller's* units, updated on
    every valueChanged, so what the handle means is on screen while it moves.

    `value()` and `setValue()` mirror QSlider, so this is a drop-in for callers
    that only ever asked the slider for its number.

        Params:
            parent (QWidget): the parent widget
            value (int): the starting value, in the caller's own units
            minimum (int): the smallest value the slider can take
            maximum (int): the largest value the slider can take
            tick_interval (int): spacing of the tick marks; computed from the
                                 range when None
            suffix (str): appended to the number in the readout (e.g. "%")
            fmt (callable): given the value, returns the whole readout string.
                            Overrides suffix; for units that are not a plain
                            number, such as "50% (5 of 10 workers)".
    """

    def __init__(
            self,
            parent=None,
            value : int = 0,
            minimum : int = 0,
            maximum : int = 100,
            tick_interval : int = None,
            suffix : str = "",
            fmt=None,
    ):
        super().__init__(parent)

        self.suffix = suffix
        self.fmt = fmt

        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setMinimum(minimum)
        self.slider.setMaximum(maximum)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(
            tick_interval if tick_interval else defaultTickInterval(minimum, maximum)
        )
        self.slider.setValue(int(value) if value is not None else minimum)

        self.readout = QLabel(self)
        # reserve room for the longest readout the range can produce, so the
        # slider does not shift sideways as the number grows a digit
        widest = max(
            (self.formatValue(v) for v in (minimum, maximum, self.slider.value())),
            key=len,
        )
        self.readout.setMinimumWidth(
            self.readout.fontMetrics().boundingRect(widest).width() + 10
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.slider)
        layout.addWidget(self.readout)
        self.setLayout(layout)

        self.slider.valueChanged.connect(self.updateReadout)
        self.updateReadout(self.slider.value())

    def formatValue(self, value : int) -> str:
        """Render a value the way the caller wants it read."""
        if self.fmt:
            return self.fmt(value)
        return f"{value}{self.suffix}"

    def updateReadout(self, value : int):
        """Put the current value on screen."""
        self.readout.setText(self.formatValue(value))

    def text(self) -> str:
        """The readout text currently displayed."""
        return self.readout.text()

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value : int):
        self.slider.setValue(value)


class BorderedWidget(QWidget):

    def paintEvent(self, event):
        super().paintEvent(event)
        # draw the border manually
        painter = QPainter(self)
        painter.setPen(QApplication.palette().color(QPalette.WindowText))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))  # Adjust the rectangle to draw inside the border
    
    def addTitle(self, title : str):
        if not isinstance(self.layout(), QVBoxLayout):
            return
        
        hlayout = QHBoxLayout()
        hlayout.addStretch()
        lbl = QLabel(self.parent(), text=title)
        f = lbl.font()
        f.setBold(True)
        lbl.setFont(f)
        hlayout.addWidget(lbl)
        hlayout.addStretch()
        l : QVBoxLayout = self.layout()
        l.insertLayout(0, hlayout)


class RadioButtonGroup(QWidget):

    def __init__(self, parent, options : list, selected_option=None, horizontal=False):
        """Create the radio button group.
        
            Params:
                parent (QWidget): the parent widget
                options (list): the list of strings for the radio buttons
                selected_option(str): the selected option
                horizontal (bool): True if buttons should be arranged horizontally
        """
        super().__init__(parent)
        if horizontal:
            layout = QHBoxLayout()
        else:
            layout = QVBoxLayout()
        
        self.bttns = []
        for opt in options:
            bttn = QRadioButton(self, text=opt)
            if opt == selected_option:
                bttn.setChecked(True)
            self.bttns.append(bttn)
            layout.addWidget(bttn)
        
        self.setLayout(layout)
    
    def getSelectedIndex(self):
        """Get the index of the selected button."""
        for i, bttn in enumerate(self.bttns):
            if bttn.isChecked():
                return i
