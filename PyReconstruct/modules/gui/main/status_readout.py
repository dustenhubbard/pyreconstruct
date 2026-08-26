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
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QVBoxLayout, QWidget,
)


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

    lists_clicked = Signal()
    section_clicked = Signal()
    alignment_clicked = Signal()
    bc_profile_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # The one segment with fixed text: it names an action (show/hide the
        # docked lists), not a current value, so setReadout never rewrites it
        # and it stays out of self._segments. The text is a sidebar glyph
        # (U+25E7, square with left half filled), not a word, on his click
        # test call (2026-08-25); the word lives in the hover.
        self.lists_segment = StatusSegment(
            "Lists", self
        )
        self.lists_segment.setText("\u25e7")

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
        layout.addWidget(self.lists_segment)
        self._separators.append(QLabel(SEPARATOR, self))
        layout.addWidget(self._separators[-1])
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

        self.lists_segment.clicked.connect(self.lists_clicked)
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


class SectionListPopup(QWidget):
    """The section segment's popup: a jump field over a scrollable list.

    A QMenu cannot scroll inside a bounded height (its only overflow handling
    engages at screen height, which for a large series meant a popup as tall
    as the display). This is the pattern menu_search.py already proved: a
    plain Qt.Popup window holding a line edit and a QListWidget, which
    scrolls at any height. The list carries the WHOLE series; the visible
    height is capped at about twelve rows; the current section starts
    selected and centered.

    Keyboard contract, matching the old jump row: typed digits select the
    first section whose number starts with them; Up and Down move the
    selection; Return jumps to the selected row once the user has arrowed,
    else to the exactly typed number; Escape and clicking outside close
    (Qt.Popup behavior). Clicking a row jumps.
    """

    VISIBLE_ROWS = 12

    def __init__(self, numbers, current, jump, parent=None):
        super().__init__(parent, Qt.Popup)
        self._jump = jump
        self._arrowed = False

        self.field = QLineEdit(self)
        if numbers:
            # the placeholder is just the range: it is what sets the popup's
            # width, and a sentence made the whole popup far wider than the
            # menus beside it. The explanation lives in the tooltip.
            self.field.setPlaceholderText(f"{numbers[0]}-{numbers[-1]}")
            self.field.setToolTip("Type a section number and press Enter")
        self.list = QListWidget(self)
        current_item = None
        for number in numbers:
            item = QListWidgetItem(str(number), self.list)
            if number == current:
                current_item = item
        if current_item is not None:
            self.list.setCurrentItem(current_item)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)
        layout.addWidget(self.field)
        layout.addWidget(self.list)

        # Visually a sibling of the QMenus beside it (his call: the first cut
        # was too wide, sharp-cornered, and obviously a different species).
        # Rounded translucent frame in the menu's palette roles, menu-shaped
        # rows with the highlight color, and a width fitted to the content
        # instead of whatever a QListWidget defaults to.
        self.setAttribute(Qt.WA_TranslucentBackground)
        # The frame is painted in paintEvent with plain QPainter, the same
        # mechanism the pills use, because stylesheet backgrounds on a
        # translucent top-level popup are unreliable on macOS: with
        # WA_StyledBackground unset nothing painted (black), and with it set
        # the background still failed to composite. Only the CHILD list keeps
        # a stylesheet; children of a translucent window paint normally.
        pal = self.palette()
        self.setStyleSheet(
            "QListWidget {{ background: transparent; border: none; }}"
            "QListWidget::item {{ padding: 3px 14px; border-radius: 4px; }}"
            "QListWidget::item:selected {{ background: {hl}; color: {hlt}; }}"
            .format(
                hl=pal.highlight().color().name(),
                hlt=pal.highlightedText().color().name(),
            )
        )
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # a bare width override strips the native handle styling and leaves
        # a ghost of a scrollbar; paint the handle from the text color so it
        # holds contrast in both themes
        line = pal.windowText().color()
        self.list.verticalScrollBar().setStyleSheet(
            "QScrollBar:vertical {{ width: 8px; background: transparent;"
            "  margin: 0; }}"
            "QScrollBar::handle:vertical {{"
            "  background: rgba({r},{g},{b},110); border-radius: 4px;"
            "  min-height: 24px; }}"
            "QScrollBar::handle:vertical:hover {{"
            "  background: rgba({r},{g},{b},170); }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
            "  height: 0; }}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{"
            "  background: transparent; }}"
            .format(r=line.red(), g=line.green(), b=line.blue())
        )

        row_h = self.list.sizeHintForRow(0) if numbers else 18
        self.list.setFixedHeight(row_h * min(self.VISIBLE_ROWS, max(len(numbers), 1)) + 6)
        # width follows the widest number, like the menus beside it: digits
        # plus the row padding, the thin scrollbar, and the frame margins
        digits = self.fontMetrics().horizontalAdvance(str(numbers[-1]) if numbers else "0000")
        self.setFixedWidth(max(digits + 56, 84))

        self.field.textEdited.connect(self._typeSelect)
        self.field.installEventFilter(self)
        self.list.itemClicked.connect(self._rowChosen)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPainterPath, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6.0, 6.0)
        painter.fillPath(path, self.palette().window().color())
        painter.setPen(QPen(self.palette().mid().color(), 1))
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)

    def showAnchored(self, segment):
        top_left = segment.mapToGlobal(segment.rect().topLeft())
        hint = self.sizeHint()
        self.move(top_left - QPoint(0, hint.height() + 2))
        self.show()
        if self.list.currentItem() is not None:
            self.list.scrollToItem(self.list.currentItem(),
                                   QListWidget.PositionAtCenter)
        self.field.setFocus()

    def hideEvent(self, event):
        self.closed()
        super().hideEvent(event)

    def closed(self):
        pass  # rebound to the segment's popupClosed by the caller

    def _typeSelect(self, text):
        self._arrowed = False
        text = text.strip()
        if not text.isdigit():
            return
        matches = self.list.findItems(text, Qt.MatchStartsWith)
        if matches:
            self.list.setCurrentItem(matches[0])
            self.list.scrollToItem(matches[0], QListWidget.PositionAtCenter)

    def _rowChosen(self, item):
        self.hide()
        self._jump(int(item.text()))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Up, Qt.Key_Down):
                self._arrowed = True
                QApplication.sendEvent(self.list, event)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                item = self.list.currentItem()
                if self._arrowed and item is not None:
                    self.hide()
                    self._jump(int(item.text()))
                    return True
                text = self.field.text().strip()
                if text.isdigit():
                    exact = self.list.findItems(text, Qt.MatchExactly)
                    if exact:
                        self.hide()
                        self._jump(int(exact[0].text()))
                return True   # consumed either way
        return super().eventFilter(obj, event)
