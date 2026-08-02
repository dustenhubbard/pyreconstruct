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
from PySide6.QtWidgets import QApplication, QLabel

pytestmark = pytest.mark.gui


class RecordingLabel(QLabel):
    """A ``QLabel`` that remembers every ``setText`` call made from Python.

    ``updateStatusBar`` looks ``status_label`` up on the main window on every
    call, so swapping the attribute is enough of a seam; the recorder does not
    have to be the widget actually in the status bar's layout.
    """

    def __init__(self):
        super().__init__()
        self.writes = []

    def setText(self, text):
        self.writes.append(text)
        super().setText(text)


def readout(window):
    return window.status_label.text()


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

    assert isinstance(main_window.status_label, QLabel)
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


def test_repainting_a_still_field_does_not_rewrite_the_readout(main_window):
    """The label is written on change, not on every paint.

    ``paintText`` is the real per-frame caller, so it is what drives this rather
    than ``updateStatusBar`` directly.
    """
    field = main_window.field
    field.mouse_x, field.mouse_y = 60, 60
    field.updateStatusBar()

    recorder = RecordingLabel()
    recorder.setText(readout(main_window))
    recorder.writes.clear()
    main_window.status_label = recorder

    for _ in range(5):
        paint_the_field(main_window)

    assert recorder.writes == []

    field.mouse_x, field.mouse_y = 200, 200
    paint_the_field(main_window)

    assert len(recorder.writes) == 1
    assert recorder.writes[0].startswith("Section: ")


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
