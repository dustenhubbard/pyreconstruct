"""The field's status-bar readout, split into clickable segments.

The readout is the "Section: 5  |  Alignment: default  |  B/C Profile: default
|  x = ..." line the field composes in `FieldWidget.updateStatusBar`. It used
to be a single flat `QLabel`, which meant the three values a user changes most
often -- section, alignment, brightness/contrast profile -- were displayed
inches from the pointer and reachable only through a menu.

`QStatusBar` has no notion of a segment: it lays out whole widgets, and
`showMessage` writes one string. Per-segment clicks therefore need real
widgets, one per segment, which is what `FieldStatusReadout` builds. The
alternative -- one rich-text `QLabel` with `<a href>` links and
`linkActivated` -- was rejected because hit-testing a link is text-metrics
dependent and cannot be driven from a test without reproducing the metrics the
production code uses; a click at the centre of a child widget can.

Two properties of the old flat label are kept deliberately:

  * `text()` still returns the whole readout as the one joined string, so the
    readout can be asserted on in one piece.
  * a write only happens when that segment's text actually changed.
    `paintText` calls `updateStatusBar` from every paint event, so an
    unconditional write cost a `setText` and a status-bar relayout per frame.
    Splitting the readout makes that guard finer rather than coarser: moving
    the cursor now rewrites only the coordinates segment, and leaves the three
    clickable ones untouched.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


SEPARATOR = "  |  "


class StatusSegment(QLabel):
    """A readout segment that reports a left-click.

    `QLabel` has no `clicked` signal; a label is not a button and Qt will not
    pretend otherwise. Overriding `mousePressEvent` is the documented way to
    give a plain widget a press, and press (not release) is what the rest of
    this application's popups use.
    """

    clicked = Signal()

    def __init__(self, tooltip: str, parent=None):
        super().__init__(parent)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        # Visual affordance beyond the hover cursor is an open design
        # question (his call: not link-blue; something shaped like a
        # button, with the segment popups anchored and styled to match).
        # The plan for that is being reviewed; until it lands the segment
        # signals clickability by cursor and tooltip alone.

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class FieldStatusReadout(QWidget):
    """The permanent status-bar widget: three clickable segments and the rest.

    The three segments carry section, alignment and brightness/contrast
    profile. Everything else the field reports -- cursor coordinates, the line
    distance while line tracing, the closest trace -- is a single plain label,
    because none of it names a thing the user can switch to.
    """

    section_clicked = Signal()
    alignment_clicked = Signal()
    bc_profile_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.section_segment = StatusSegment(
            "Jump to a section", self
        )
        self.alignment_segment = StatusSegment(
            "Switch alignment", self
        )
        self.bc_profile_segment = StatusSegment(
            "Switch brightness/contrast profile", self
        )
        self.detail_label = QLabel(self)

        self._segments = (
            self.section_segment,
            self.alignment_segment,
            self.bc_profile_segment,
            self.detail_label,
        )
        self._separators = []

        layout = QHBoxLayout(self)
        # zero margins: the status bar supplies its own, and a second set makes
        # the readout sit visibly higher than a `showMessage` notice beside it.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for i, widget in enumerate(self._segments):
            if i:
                separator = QLabel(SEPARATOR, self)
                self._separators.append(separator)
                layout.addWidget(separator)
            layout.addWidget(widget)

        # Left-mounted (a normal status-bar widget), so the anchored edge is
        # the left one and the per-mouse-move coordinate rewrites grow and
        # shrink rightward into empty bar. The minimum width still steadies
        # the detail span so the text does not slide under a pointer parked
        # right of it; left alignment keeps short text in place.
        fm = self.detail_label.fontMetrics()
        self.detail_label.setMinimumWidth(
            fm.horizontalAdvance("x = 99999.99, y = 99999.99  |  Closest trace: a_typical_name")
        )
        self.detail_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self.section_segment.clicked.connect(self.section_clicked)
        self.alignment_segment.clicked.connect(self.alignment_clicked)
        self.bc_profile_segment.clicked.connect(self.bc_profile_clicked)

    def setReadout(self, section: str, alignment: str, bc_profile: str, detail: str):
        """Write the four parts of the readout, skipping the unchanged ones.

            Params:
                section (str): e.g. "Section: 5"
                alignment (str): e.g. "Alignment: default"
                bc_profile (str): e.g. "B/C Profile: default"
                detail (str): the already-joined remainder of the readout
        """
        for widget, text in zip(self._segments, (section, alignment, bc_profile, detail)):
            if widget.text() != text:
                widget.setText(text)

        # a trailing "  |  " with nothing after it, on a readout that has never
        # been written or is momentarily detail-free
        self._separators[-1].setVisible(bool(detail))

    def text(self) -> str:
        """The whole readout as one string, the way the flat label read."""
        return SEPARATOR.join(
            widget.text() for widget in self._segments if widget.text()
        )
