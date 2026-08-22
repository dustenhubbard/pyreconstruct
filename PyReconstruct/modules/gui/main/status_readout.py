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

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QWidget


SEPARATOR = "  |  "


class StatusSegment(QLabel):
    """A readout segment that reports a left-click and looks pressable.

    `QLabel` has no `clicked` signal; a label is not a button and Qt will not
    pretend otherwise. Overriding `mousePressEvent` is the documented way to
    give a plain widget a press, and press (not release) is what the rest of
    this application's popups use.

    The affordance is shape, not color (his call: not link-blue): a rounded
    outline painted from the palette's text color at low alpha, a slightly
    stronger fill on hover, stronger again while the segment's popup is open.
    Palette-derived, so both themes are covered without theme code. The
    pressed look is owned by the POPUP helper through popupOpened() and
    popupClosed(), never by the press itself, so a click handler that opens
    no popup cannot strand the pill in its pressed state.
    """

    clicked = Signal()
    right_clicked = Signal()

    #: inner padding so the outline does not hug the glyphs; the vertical
    #: pixel is measured by test_pills_do_not_grow_the_status_bar
    H_PAD = 8
    V_PAD = 1

    def __init__(self, tooltip: str, parent=None):
        super().__init__(parent)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setContentsMargins(self.H_PAD, self.V_PAD, self.H_PAD, self.V_PAD)
        self._hovered = False
        self._popup_open = False
        self._popup_hidden_at = 0.0

    # -- pressed state, owned by the popup helper --------------------------
    def popupOpened(self):
        self._popup_open = True
        self.update()

    def popupClosed(self):
        import time
        self._popup_open = False
        self._popup_hidden_at = time.monotonic()
        self.update()

    def event(self, e):
        if e.type() in (QEvent.HoverEnter, QEvent.HoverLeave):
            self._hovered = e.type() == QEvent.HoverEnter
            self.update()
        return super().event(e)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Toggle explicitly instead of trusting the platform's
            # ReplayMousePressOutsidePopup style hint: where the dismissing
            # press is replayed, the click that closed the popup would
            # instantly reopen it and the pill could never dismiss its own
            # popup. A press arriving within the double-click interval of
            # the popup hiding IS that dismissing press; swallow it.
            import time
            from PySide6.QtWidgets import QApplication
            interval = QApplication.doubleClickInterval() / 1000.0
            self._pressed = time.monotonic() - self._popup_hidden_at >= interval
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # Emit on RELEASE, not press: a section menu taller than the screen
        # gets clamped over the segment itself, and a menu opened during the
        # press would receive the release on whatever row sits under the
        # pointer, jumping to a section nobody chose. Released with no button
        # down, the open menu waits for a real second click.
        if event.button() == Qt.LeftButton:
            if getattr(self, "_pressed", False) and self.rect().contains(event.position().toPoint()):
                self._pressed = False
                self.clicked.emit()
            self._pressed = False
            event.accept()
            return
        if event.button() == Qt.RightButton:
            if self.rect().contains(event.position().toPoint()):
                self.right_clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPainterPath, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        line = self.palette().windowText().color()
        outline = QPainterPath()
        radius = self.height() / 2.0 - 0.5
        rect = self.rect().adjusted(0, 0, -1, -1)
        outline.addRoundedRect(rect, radius, radius)
        if self._popup_open or self._hovered:
            fill = QColor(line)
            fill.setAlpha(40 if self._popup_open else 20)
            painter.fillPath(outline, fill)
        edge = QColor(line)
        edge.setAlpha(90)
        painter.setPen(QPen(edge, 1))
        painter.drawPath(outline)
        painter.end()
        super().paintEvent(event)


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
        # Margins: zero vertically (the status bar supplies its own, and a
        # second set makes the readout sit visibly higher than a showMessage
        # notice beside it), but 10 px on the left so the first pill clears
        # macOS's rounded window corner, which otherwise crowds it.
        layout.setContentsMargins(10, 0, 0, 0)
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


class SectionJumpField(QLineEdit):
    """The jump row at the top of the section popup.

    A pure jump field, never a filter: hiding actions in a shown QMenu is the
    live-mutation trap menu_search.py documents, so the list is never touched.
    Typed digits move the menu's active action to the first section whose
    number starts with them; Return jumps. Modeled on
    MenuSearchField.eventFilter: the filter consumes Return itself, prefers
    the menu's active action once the user has arrowed, falls back to the
    parsed number, and closes the menu, because a QLineEdit does not accept
    Return and the propagated event would also activate a menu row (one
    keystroke, two jumps).
    """

    def __init__(self, menu, acts_by_number, jump, parent=None, all_numbers=None):
        super().__init__(parent)
        self._menu = menu
        self._acts = acts_by_number      # list of (number, QAction), menu order
        self._jump = jump
        # the listed rows are a window sized to the space above the bar; the
        # typed jump reaches the whole series
        self._all_numbers = all_numbers if all_numbers is not None else [
            n for n, _ in acts_by_number
        ]
        self._arrowed = False
        if self._all_numbers:
            self.setPlaceholderText(
                f"Jump to section ({self._all_numbers[0]}-{self._all_numbers[-1]})"
            )
        self.textEdited.connect(self._moveActive)
        self.installEventFilter(self)

    def _moveActive(self, text):
        self._arrowed = False
        text = text.strip()
        if not text.isdigit():
            return
        for number, act in self._acts:
            if str(number).startswith(text):
                self._menu.setActiveAction(act)
                return

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Up, Qt.Key_Down):
                self._arrowed = True
                QApplication.sendEvent(self._menu, event)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                active = self._menu.activeAction()
                if self._arrowed and active is not None and active.isEnabled():
                    self._menu.close()
                    active.trigger()
                    return True
                text = self.text().strip()
                if text.isdigit() and int(text) in self._all_numbers:
                    self._menu.close()
                    self._jump(int(text))
                    return True
                return True   # consumed either way: never let Return reach the menu too
        return super().eventFilter(obj, event)
