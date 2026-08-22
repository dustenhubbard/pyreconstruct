"""The 2D field's status readout, and the three ways it used to misbehave.

The readout is the "Section: 5  |  Alignment: default  |  ...  |  x = ..." line
the field composes in ``FieldWidget.updateStatusBar``. It used to be posted with
``statusbar.showMessage()``, which is the API for a *transient* notice, and all
three defects below follow from that one choice:

1. **A trip to the menu bar blanked it.** ``QMainWindow`` turns an incoming
   ``QStatusTipEvent`` into ``statusBar()->showMessage(tip)``. Hovering any
   ``QAction`` sends one, and an action with no status tip sends the empty
   string, so the bar dutifully displayed nothing. Nothing in this tree calls
   ``clearMessage`` or sets a status tip; it was Qt doing exactly what the API
   asks for. The readout is now a permanent widget, which status-tip events do
   not touch.

2. **It rewrote the bar on every paint.** ``paintText`` calls
   ``updateStatusBar`` from every paint event, and the old code wrote the string
   unconditionally, so a repaint with an unmoved cursor still cost a status-bar
   write and relayout -- and, worse, destroyed anything another caller had put
   there. The write is now conditional on the text having changed.

3. **A latent ``IndexError``.** ``self.current_trace[-1]`` sat under a bare
   ``if self.is_line_tracing:``. No caller reaches that state today (every site
   that empties ``current_trace`` either clears the flag first or runs in a
   mouse mode that never sets it), which is precisely why it is worth pinning:
   the invariant is unenforced and the failure would surface as a traceback out
   of a paint event.

The permanent widget also settles the coexistence question, which is the point
of test ``test_a_transient_message_appears_and_expires_beside_the_readout``:
``MainWindow._onStartupCheck`` posts a real transient notice with
``showMessage(..., 15000)``, and that notice and this readout are no longer
competing for the same slot.
"""
import pytest

from PySide6.QtGui import QStatusTipEvent
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.gui.main.status_readout import FieldStatusReadout

pytestmark = pytest.mark.gui


def record_writes(monkeypatch, window):
    """Record every ``setText`` the readout's own widgets receive.

    The readout is four widgets now, not one label, so the recorder wraps each
    of them in place rather than standing in for the whole thing. That is
    strictly closer to what ships: the writes counted are the writes Qt is
    actually asked to make, on the widgets actually in the status bar.

        Returns:
            (list): ``(name, text)`` for each write, in order
    """
    writes = []
    readout_widget = window.status_readout
    for name in ("section_segment", "alignment_segment", "bc_profile_segment",
                 "detail_label"):
        widget = getattr(readout_widget, name)
        original = widget.setText

        def record(text, name=name, original=original):
            writes.append((name, text))
            original(text)

        monkeypatch.setattr(widget, "setText", record)
    return writes


def readout(window):
    return window.status_readout.text()


def paint_the_field(window):
    """Drive the real ``paintText`` writer without a paint event.

    Offscreen widgets are not repainted on demand, so the production caller is
    invoked directly against a painter on an off-widget pixmap. This is the same
    code path ``FieldWidget.paintEvent`` takes.
    """
    from PySide6.QtGui import QPainter, QPixmap

    field = window.field
    pixmap = QPixmap(max(field.width(), 1), max(field.height(), 1))
    painter = QPainter(pixmap)
    try:
        field.paintText(painter)
    finally:
        painter.end()


# ---- 1. the reported bug ---------------------------------------------------

def test_the_readout_is_a_permanent_widget_not_a_temporary_message(main_window):
    """The structural claim the other tests rest on."""
    main_window.field.updateStatusBar()

    assert isinstance(main_window.status_readout, FieldStatusReadout)
    assert main_window.status_readout.parent() is main_window.statusbar
    assert readout(main_window).startswith("Section: ")
    # nothing of the readout leaks into the temporary-message slot
    assert main_window.statusbar.currentMessage() == ""


def test_an_empty_status_tip_event_does_not_blank_the_readout(main_window):
    """Hovering a menu action with no status tip must leave the readout alone.

    ``QStatusTipEvent("")`` is exactly what Qt sends the window when the pointer
    enters a ``QAction`` that has no ``statusTip``, which is every action in
    this tree.
    """
    main_window.field.updateStatusBar()
    before = readout(main_window)
    assert before

    QApplication.sendEvent(main_window, QStatusTipEvent(""))

    assert readout(main_window) == before


def test_a_real_menu_action_hover_does_not_blank_the_readout(main_window):
    """The same thing again, with the tip taken from a real menu action.

    ``File > Save`` is reached through the attribute the window already holds
    rather than by walking the menubar, because walking builds new wrappers and
    can invalidate the ones the window is holding (see the note above
    ``menu_leaf_paths`` in ``conftest.py``).

    Reading the tip off a live action instead of writing ``""`` is what keeps
    this test honest: it is currently empty, and if status tips are ever added
    the test starts exercising the case that actually has one.
    """
    action = main_window.save_act

    main_window.field.updateStatusBar()
    before = readout(main_window)
    assert before

    QApplication.sendEvent(main_window, QStatusTipEvent(action.statusTip()))

    assert readout(main_window) == before


# ---- 2. the every-paint rewrite -------------------------------------------

def test_the_readout_follows_the_cursor_across_the_field(main_window):
    """Moving the mouse in the field must still update the coordinates."""
    field = main_window.field
    field.mouse_x, field.mouse_y = 10, 10
    field.updateStatusBar()
    first = readout(main_window)

    field.mouse_x, field.mouse_y = 120, 140
    field.updateStatusBar()
    second = readout(main_window)

    assert "x = " in first and "x = " in second
    assert first != second


def test_repainting_a_still_field_does_not_rewrite_the_readout(
    main_window, monkeypatch
):
    """The readout is written on change, not on every paint.

    ``paintText`` is the real per-frame caller, so it is what drives this rather
    than ``updateStatusBar`` directly.

    Splitting the readout into segments makes this claim finer than it was: a
    mouse move must rewrite the coordinates and *only* the coordinates, leaving
    the three clickable segments alone.
    """
    field = main_window.field
    field.mouse_x, field.mouse_y = 60, 60
    field.updateStatusBar()

    writes = record_writes(monkeypatch, main_window)

    for _ in range(5):
        paint_the_field(main_window)

    assert writes == []

    field.mouse_x, field.mouse_y = 200, 200
    paint_the_field(main_window)

    assert len(writes) == 1
    name, text = writes[0]
    assert name == "detail_label"
    assert text.startswith("x = ")


def test_a_section_change_still_updates_the_readout(main_window):
    """The other event that legitimately moves the readout."""
    sections = sorted(main_window.series.sections.keys())
    if len(sections) < 2:
        pytest.skip("fixture series has a single section")

    main_window.changeSection(sections[0], save=False)
    first = readout(main_window)
    main_window.changeSection(sections[1], save=False)
    second = readout(main_window)

    assert first.startswith(f"Section: {sections[0]}")
    assert second.startswith(f"Section: {sections[1]}")


# ---- transient notices coexisting -----------------------------------------

def test_a_transient_message_appears_and_expires_beside_the_readout(
    main_window, qtbot
):
    """``showMessage`` still works, and neither side destroys the other.

    This is the shape ``MainWindow._onStartupCheck`` uses for the
    "Update available" banner. Before the readout moved to a permanent widget,
    the first repaint of the field overwrote that banner well inside its
    timeout.
    """
    main_window.field.updateStatusBar()
    before = readout(main_window)
    assert before

    main_window.statusbar.showMessage("Update available: 9.9.9", 120)
    assert main_window.statusbar.currentMessage() == "Update available: 9.9.9"
    assert readout(main_window) == before

    # a repaint underneath the notice leaves it alone
    paint_the_field(main_window)
    assert main_window.statusbar.currentMessage() == "Update available: 9.9.9"

    qtbot.waitUntil(
        lambda: main_window.statusbar.currentMessage() == "", timeout=3000
    )
    assert readout(main_window) == before


def test_the_update_banner_survives_a_repaint(main_window, monkeypatch):
    """The reported case, end to end through the real startup handler."""
    from PyReconstruct.modules.gui.main import main_window as mw

    monkeypatch.setattr(mw, "notifyConfirm", lambda *a, **k: False)
    main_window.field.updateStatusBar()

    main_window._onStartupCheck(
        {"asset": "x", "status": "newer", "remote_version": "9.9.9"}, "stable"
    )
    assert "9.9.9" in main_window.statusbar.currentMessage()

    main_window.field.mouse_x, main_window.field.mouse_y = 33, 44
    paint_the_field(main_window)

    assert "9.9.9" in main_window.statusbar.currentMessage()
    assert readout(main_window).startswith("Section: ")


# ---- 3. the latent IndexError ---------------------------------------------

def test_line_tracing_with_no_points_does_not_raise(main_window):
    """``current_trace[-1]`` under a bare ``is_line_tracing`` guard.

    Not reachable from the UI today. Pinned because nothing enforces the
    invariant it relies on, and the failure would be an ``IndexError`` raised
    out of a paint event -- the worst place to find one.
    """
    field = main_window.field
    field.is_line_tracing = True
    field.current_trace = []

    field.updateStatusBar()

    text = readout(main_window)
    assert text.startswith("Section: ")
    assert "Line distance" not in text


def test_line_tracing_with_points_still_reports_the_distance(main_window):
    """The guard must not have cost the feature it guards."""
    field = main_window.field
    field.is_line_tracing = True
    field.current_trace = [(10, 10), (40, 50)]
    field.mouse_x, field.mouse_y = 90, 90

    field.updateStatusBar()

    assert "Line distance: " in readout(main_window)


def test_a_paint_with_no_points_does_not_raise(main_window):
    """The same state reached through the real per-frame caller."""
    field = main_window.field
    field.is_line_tracing = True
    field.current_trace = []

    paint_the_field(main_window)

    assert readout(main_window).startswith("Section: ")


# ---- 4. pixel-level regression: stretch=0 leaves the message area visible ---

def test_banner_paints(main_window, qtbot):
    """``showMessage`` must produce a visible pixel change in the status bar.

    With ``addPermanentWidget(label, stretch=1)`` the permanent widget absorbs
    all spare width, the temporary-message area collapses to ~0 px, and
    ``showMessage`` changes no pixels. With ``stretch=0`` the label sits at the
    right edge and the message area is wide enough to paint normally.

    This is a pixel-level regression guard: it fails with stretch=1 and passes
    with stretch=0, so the defect cannot return silently.

    The window is resized to 1200 px before the grab so the label's text
    (≈480 px sizeHint) leaves a genuine message area on the left; at the
    default 400 px width the readout text crowds out the message area for both
    stretch values and the comparison yields a false pass.
    """
    main_window.resize(1200, 600)
    sb = main_window.statusbar
    QApplication.processEvents()
    sb.repaint()
    before = sb.grab().toImage()
    sb.showMessage("Update available: 9.9.9", 15000)
    # qtbot.wait() gives the event loop real time to process the repaint,
    # which processEvents() alone does not guarantee in the offscreen platform.
    qtbot.wait(25)
    sb.repaint()
    assert before != sb.grab().toImage()


def test_mouse_move_width_changes_do_not_move_the_readout(main_window, qtbot):
    """The readout's geometry holds still while the coordinates rewrite.

    The readout is right-anchored (stretch=0, which test_banner_paints above
    protects), so any width change moves its left edge with the cursor: the
    jitter he saw on the first main-line click test. The detail label's
    minimum width absorbs ordinary coordinate churn.
    """
    readout = main_window.status_readout
    readout.setReadout("Section: 5", "Alignment: default", "B/C Profile: default",
                       "x = 1.11, y = 2.22")
    QApplication.processEvents()
    width_before = readout.sizeHint().width()
    for detail in ("x = 999.99, y = 888.88", "x = 3.1, y = 4.2",
                   "x = 12345.67, y = 8.9  |  Closest trace: d001"):
        readout.setReadout("Section: 5", "Alignment: default",
                           "B/C Profile: default", detail)
        QApplication.processEvents()
        assert readout.sizeHint().width() == width_before, detail


def test_pills_do_not_grow_the_status_bar(main_window):
    """The rounded outline must live inside the bar the text already needs."""
    from PySide6.QtWidgets import QLabel, QStatusBar
    plain = QStatusBar()
    plain.addWidget(QLabel("Section: 5"))
    assert main_window.statusbar.sizeHint().height() <= plain.sizeHint().height()


def test_popup_owns_the_pressed_state(main_window, qtbot):
    """popupOpened/popupClosed pair through a real anchored popup."""
    seg = main_window.status_readout.alignment_segment
    assert seg._popup_open is False
    menu = main_window.quickSwitchAlignment()
    assert seg._popup_open is True
    menu.close()
    qtbot.wait(10)
    assert seg._popup_open is False


def test_press_right_after_popup_close_is_swallowed(main_window, qtbot):
    """The click that dismissed the popup must not instantly reopen it."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    seg = main_window.status_readout.alignment_segment
    fired = []
    seg.clicked.connect(lambda: fired.append(1))

    def press():
        QApplication.sendEvent(seg, QMouseEvent(
            QEvent.MouseButtonPress, QPointF(3, 3), Qt.LeftButton,
            Qt.LeftButton, Qt.NoModifier))
        QApplication.sendEvent(seg, QMouseEvent(
            QEvent.MouseButtonRelease, QPointF(3, 3), Qt.LeftButton,
            Qt.LeftButton, Qt.NoModifier))

    press()
    assert fired == [1]
    seg.popupOpened()
    seg.popupClosed()          # popup just hid: the very next press is the dismisser
    press()
    assert fired == [1], "the dismissing press reopened the popup"
    seg._popup_hidden_at = 0.0  # far in the past: presses work again
    press()
    assert fired == [1, 1]


def test_section_popup_lists_everything_in_a_bounded_box(main_window, qtbot):
    """The whole series is in the list, the box never nears screen height,
    and the current section starts selected (his call: full range, bounded
    popup)."""
    popup = main_window.sectionJumpFromStatusBar()
    qtbot.wait(20)
    numbers = sorted(main_window.series.sections.keys())
    assert popup.list.count() == len(numbers)
    assert popup.list.currentItem() is not None
    assert popup.list.currentItem().text() == str(main_window.series.current_section)
    row_h = popup.list.sizeHintForRow(0)
    assert popup.height() <= row_h * (popup.VISIBLE_ROWS + 4)
    popup.hide()


def test_jump_field_return_jumps_by_number(main_window, qtbot, monkeypatch):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    jumped = []
    monkeypatch.setattr(main_window, "changeSection",
                        lambda n, **k: jumped.append(n))
    popup = main_window.sectionJumpFromStatusBar()
    qtbot.wait(20)
    target = str(sorted(main_window.series.sections.keys())[-1])
    popup.field.setText(target)
    QApplication.sendEvent(popup.field, QKeyEvent(
        QEvent.KeyPress, Qt.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert jumped == [int(target)]
    assert not popup.isVisible()


def test_opening_click_cannot_trigger_a_menu_row(main_window, qtbot):
    """The click that opens the section menu must never also choose a row.

    A 500-section menu is taller than the screen, so Qt clamps it over the
    segment itself; if the segment emitted on press, the release of that same
    click would land on whichever row Qt put under the pointer and jump
    there. Emitting on release means the menu opens with no button held.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    seg = main_window.status_readout.section_segment
    opened = []
    seg.clicked.connect(lambda: opened.append(1))
    QApplication.sendEvent(seg, QMouseEvent(
        QEvent.MouseButtonPress, QPointF(3, 3), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier))
    assert opened == [], "segment fired on press; the release would hit the menu"
    QApplication.sendEvent(seg, QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(3, 3), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier))
    assert opened == [1]


def test_right_click_opens_the_classic_dialog(main_window, main_window_dialogs):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    seg = main_window.status_readout.section_segment
    QApplication.sendEvent(seg, QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(3, 3), Qt.RightButton,
        Qt.RightButton, Qt.NoModifier))
    assert "Go To Section" in main_window_dialogs.dialogs


def test_section_menu_always_ends_above_the_pill(main_window, qtbot):
    """The menu's bottom edge must sit above the segment, never on it.

    A QMenu taller than the screen gets clamped to the full screen and its
    bottom scroll arrow lands exactly on the pill (his click-test report),
    so the row count is fitted to the space above the bar and the geometry
    is pinned here.
    """
    popup = main_window.sectionJumpFromStatusBar()
    qtbot.wait(20)
    seg = main_window.status_readout.section_segment
    seg_top = seg.mapToGlobal(seg.rect().topLeft()).y()
    popup_bottom = popup.pos().y() + popup.sizeHint().height()
    assert popup_bottom <= seg_top, (
        f"popup bottom {popup_bottom} covers the segment top {seg_top}"
    )
    screen_h = main_window.screen().availableGeometry().height()
    assert popup.sizeHint().height() < screen_h
    popup.hide()


def test_typing_accumulates_multi_digit_numbers(main_window, qtbot, monkeypatch):
    """Digits typed one at a time must build one number, then Enter jumps.

    The exact click-test failure: inside a QMenu, each digit fed the menu's
    single-keystroke type-select, so the highlight jumped on the first digit
    and a three-digit number could never be typed. The popup owns its own
    focus; the field is an ordinary line edit.
    """
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    numbers = sorted(main_window.series.sections.keys())
    target = next((n for n in reversed(numbers) if n >= 10), None)
    if target is None:
        pytest.skip("fixture series has no multi-digit section")

    jumped = []
    monkeypatch.setattr(main_window, "changeSection",
                        lambda n, **k: jumped.append(n))
    popup = main_window.sectionJumpFromStatusBar()
    qtbot.wait(20)

    for ch in str(target):
        QApplication.sendEvent(popup.field, QKeyEvent(
            QEvent.KeyPress, Qt.Key_0 + int(ch),
            Qt.KeyboardModifier.NoModifier, ch))
    assert popup.field.text() == str(target), (
        "digits did not accumulate in the field"
    )
    QApplication.sendEvent(popup.field, QKeyEvent(
        QEvent.KeyPress, Qt.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert jumped == [target]
    assert not popup.isVisible()


def test_popup_paints_real_pixels(main_window, qtbot):
    """The popup's center pixel must be the palette window color.

    Attribute pins were not enough: the frame shipped black once (nothing
    painted the translucent window) and transparent once (the stylesheet
    background failed to composite on the popup). Grabbing pixels is the
    assertion that fails when the user sees black."""
    popup = main_window.sectionJumpFromStatusBar()
    qtbot.wait(20)
    image = popup.grab().toImage()
    center = image.pixelColor(image.width() // 2, 2)
    expected = popup.palette().window().color()
    assert center == expected, (
        f"popup frame paints {center.name()} where the window color "
        f"{expected.name()} belongs"
    )
    popup.hide()
