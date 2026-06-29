"""UI v1 — 3D-scene slide-over ("peek") behavior (headless, offscreen).

The look is signed off interactively; these cover BEHAVIOR only:
open/close/visibility/geometry/state, the reduced-motion case, the slide
animation's targets, the field-resize re-pin, and the menu/shortcut/hand-off
wiring. QSettings is isolated to a temp dir by the session-autouse fixture in
conftest.py, so the reduce_motion round-trips never touch real preferences.
"""

import types

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QRect, QSize, QSettings, QAbstractAnimation  # noqa: E402
from PySide6.QtGui import QResizeEvent, QKeyEvent, QAction  # noqa: E402
from PySide6.QtWidgets import QMainWindow, QWidget  # noqa: E402

import PyReconstruct.modules.gui.main.scene_peek as sp  # noqa: E402
from PyReconstruct.modules.gui.main.scene_peek import ScenePeek  # noqa: E402


FIELD = QRect(40, 30, 900, 760)


@pytest.fixture(autouse=True)
def _flush_widgets(qapp):
    """Tear down leftover top-level widgets after each test and flush pending
    events, so an installed field event-filter can't fire on a half-deleted
    ScenePeek during the next test's setup."""
    yield
    for w in qapp.topLevelWidgets():
        w.close()
        w.deleteLater()
    qapp.processEvents()


def _win_with_field(rect=FIELD):
    """A real QMainWindow (a valid QWidget parent) with a fixed-geometry field.

    Geometry is set explicitly (not via the layout) so the overlay math is
    deterministic without showing windows."""
    win = QMainWindow()
    win.resize(1200, 820)
    field = QWidget(win)
    field.setGeometry(rect)
    win.field = field
    return win, field


def _peek(monkeypatch, reduced=True, rect=FIELD):
    # default to the reduced-motion path so state lands synchronously
    monkeypatch.setattr(sp, "reduced_motion", lambda: reduced)
    win, field = _win_with_field(rect)
    return win, field, ScenePeek(win)


# --- reduced_motion() helper ------------------------------------------------------

def test_reduced_motion_env_truthy(monkeypatch):
    for v in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("PYRECONSTRUCT_REDUCED_MOTION", v)
        assert sp.reduced_motion() is True


def test_reduced_motion_env_falsy(monkeypatch):
    for v in ("0", "false", "no", ""):
        monkeypatch.setenv("PYRECONSTRUCT_REDUCED_MOTION", v)
        assert sp.reduced_motion() is False


def test_reduced_motion_default_is_false(monkeypatch):
    monkeypatch.delenv("PYRECONSTRUCT_REDUCED_MOTION", raising=False)
    s = QSettings("KHLab", "PyReconstruct")
    s.remove("reduce_motion"); s.sync()
    assert sp.reduced_motion() is False


def test_reduced_motion_reads_global_qsettings(monkeypatch):
    monkeypatch.delenv("PYRECONSTRUCT_REDUCED_MOTION", raising=False)
    s = QSettings("KHLab", "PyReconstruct")
    s.setValue("reduce_motion", True); s.sync()
    try:
        assert sp.reduced_motion() is True
    finally:
        s.remove("reduce_motion"); s.sync()


# --- geometry: pinned to the field's right edge -----------------------------------

def test_target_geometry_pinned_right_full_height(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    tg = peek.targetGeometry()
    assert tg.y() == FIELD.y()
    assert tg.height() == FIELD.height()
    assert tg.width() == min(460, int(FIELD.width() * 0.62))     # min(460, 558) -> 460
    assert tg.x() + tg.width() == FIELD.x() + FIELD.width()        # flush to the right edge


def test_panel_width_uses_fraction_when_narrow(qapp, monkeypatch):
    narrow = QRect(0, 0, 500, 400)   # 62% -> 310, below the 460 cap
    _, _, peek = _peek(monkeypatch, rect=narrow)
    assert peek.targetGeometry().width() == int(500 * 0.62)


def test_offscreen_geometry_is_just_past_right_edge(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    og = peek.offscreenGeometry()
    assert og.x() == FIELD.x() + FIELD.width()
    assert og.width() == peek.targetGeometry().width()


def test_scrim_covers_the_field(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    assert peek.scrim.geometry() == FIELD


def test_starts_closed_and_hidden(qapp, monkeypatch):
    # isHidden (not isVisible): offscreen tests never show the top-level window,
    # so isVisible() is always False — mirrors the lists-panel suite's convention.
    _, _, peek = _peek(monkeypatch)
    assert peek.is_open is False
    assert peek.isHidden() is True
    assert peek.scrim.isHidden() is True


# --- open / close / toggle (reduced-motion path: synchronous) ---------------------

def test_open_docks_panel_shows_scrim_hides_pill(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    peek.open()
    assert peek.is_open is True
    assert peek.isHidden() is False and peek.scrim.isHidden() is False
    assert peek.geometry() == peek.targetGeometry()
    assert peek._scrim_fx.opacity() == 1.0
    assert peek.pill.isHidden() is True


def test_close_hides_panel_and_scrim_restores_pill(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    peek.open()
    peek.close()
    assert peek.is_open is False
    assert peek.isHidden() is True and peek.scrim.isHidden() is True
    assert peek._scrim_fx.opacity() == 0.0
    assert peek.pill.isHidden() is False


def test_toggle_alternates(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    peek.toggle(); assert peek.is_open is True
    peek.toggle(); assert peek.is_open is False


def test_open_is_idempotent(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    seen = []
    peek.toggled.connect(seen.append)
    peek.open(); peek.open()
    assert seen == [True]            # the second open is a no-op (no extra signal)


def test_close_is_idempotent(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    seen = []
    peek.toggled.connect(seen.append)
    peek.open(); peek.close(); peek.close()
    assert seen == [True, False]


def test_toggled_signal_reports_state(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    seen = []
    peek.toggled.connect(seen.append)
    peek.open(); peek.close()
    assert seen == [True, False]


# --- close triggers: scrim click, Escape, close button ----------------------------

def test_scrim_click_closes(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    peek.open()
    # the scrim closes on any press and ignores the event object
    peek.scrim.mousePressEvent(None)
    assert peek.is_open is False


def test_escape_closes(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    peek.open()
    from PySide6.QtCore import QEvent
    peek.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert peek.is_open is False


def test_close_button_closes(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    peek.open()
    peek.close_btn.click()
    assert peek.is_open is False


# --- field-resize re-pin (event filter) -------------------------------------------

def test_eventfilter_repins_to_new_right_edge_on_field_resize(qapp, monkeypatch):
    _, field, peek = _peek(monkeypatch)
    peek.open()
    field.setGeometry(40, 30, 1100, 760)              # field grows
    peek.eventFilter(field, QResizeEvent(QSize(1100, 760), QSize(900, 760)))
    assert peek.geometry() == peek.targetGeometry()
    assert peek.geometry().x() + peek.geometry().width() == 40 + 1100
    assert peek.scrim.geometry() == QRect(40, 30, 1100, 760)


def test_eventfilter_keeps_panel_offscreen_when_closed(qapp, monkeypatch):
    _, field, peek = _peek(monkeypatch)
    field.setGeometry(40, 30, 1100, 760)
    peek.eventFilter(field, QResizeEvent(QSize(1100, 760), QSize(900, 760)))
    assert peek.geometry() == peek.offscreenGeometry()  # still parked off-edge


# --- slide animation (the non-reduced-motion path) --------------------------------

def test_animated_open_targets_docked_geometry(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch, reduced=False)
    peek.open()
    assert peek._anim is not None
    assert peek._anim.state() == QAbstractAnimation.Running
    assert peek._anim.startValue() == peek.offscreenGeometry()
    assert peek._anim.endValue() == peek.targetGeometry()
    assert peek._scrim_anim.endValue() == 1.0
    peek._anim.setCurrentTime(peek._anim.duration())     # jump to the end
    assert peek.geometry() == peek.targetGeometry()


def test_animated_close_targets_offscreen_and_hides(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch, reduced=True)
    peek.open()                                          # instant open
    monkeypatch.setattr(sp, "reduced_motion", lambda: False)
    peek.close()                                         # animated close
    assert peek._anim.endValue() == peek.offscreenGeometry()
    assert peek._scrim_anim.endValue() == 0.0
    # drive the close animation to completion, bounded so an unattended run can't hang
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    peek._anim.finished.connect(loop.quit)
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    # the load-bearing checks: the close animation actually ran to completion
    # and _afterClose hid the panel + scrim (is_open is set synchronously in
    # close(), so it is already covered by the reduced-motion close tests).
    assert peek._anim.state() == QAbstractAnimation.Stopped
    assert peek.isHidden() is True and peek.scrim.isHidden() is True


# --- embedding seam ---------------------------------------------------------------

def test_set_scene_widget_swaps_body_content(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    w = QWidget()
    peek.setSceneWidget(w)
    assert peek._scene is w
    assert w.parent() is peek.body
    assert peek.body.layout().indexOf(w) >= 0


def test_clear_scene_widget_empties_body(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    peek.setSceneWidget(QWidget())
    peek.clearSceneWidget()
    assert peek._scene is None
    assert peek.body.layout().count() == 0


def test_reset_invokes_embedded_scene_reset_hook(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    calls = []

    class FakeViewer(QWidget):
        def resetCamera(self):
            calls.append("reset")

    peek.setSceneWidget(FakeViewer())
    peek.resetView()
    assert calls == ["reset"]


def test_reset_on_placeholder_is_safe(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    peek.resetView()        # placeholder body: must not raise


# --- MainWindow wiring: toggle flips state + syncs the menu checkbox ---------------

def _bind_mainwindow_methods(mw, *names):
    """Bind the genuine MainWindow methods onto a real QMainWindow so they run
    against a valid QWidget (ScenePeek parents itself to the main window, which
    MainWindow.__new__ — an uninitialised QWidget — cannot serve as)."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    for n in names:
        setattr(mw, n, types.MethodType(getattr(MainWindow, n), mw))


def test_mainwindow_toggle_builds_opens_and_syncs_checkbox(qapp, monkeypatch):
    monkeypatch.setattr(sp, "reduced_motion", lambda: True)
    mw, _ = _win_with_field()
    mw.scene_peek = None
    mw.threedscene_act = QAction(); mw.threedscene_act.setCheckable(True)
    _bind_mainwindow_methods(mw, "_ensureScenePeek", "_onScenePeekToggled", "toggleScenePeek")

    mw.toggleScenePeek()
    assert isinstance(mw.scene_peek, ScenePeek)
    assert mw.scene_peek.is_open is True
    assert mw.threedscene_act.isChecked() is True            # checkbox follows open state

    mw.toggleScenePeek()
    assert mw.scene_peek.is_open is False
    assert mw.threedscene_act.isChecked() is False


def test_mainwindow_toggle_show_forces_state(qapp, monkeypatch):
    monkeypatch.setattr(sp, "reduced_motion", lambda: True)
    mw, _ = _win_with_field()
    mw.scene_peek = None
    mw.threedscene_act = QAction(); mw.threedscene_act.setCheckable(True)
    _bind_mainwindow_methods(mw, "_ensureScenePeek", "_onScenePeekToggled", "toggleScenePeek")

    mw.toggleScenePeek(show=False)        # already closed -> stays closed
    assert mw.scene_peek.is_open is False
    mw.toggleScenePeek(show=True)
    assert mw.scene_peek.is_open is True
    mw.toggleScenePeek(show=True)         # idempotent
    assert mw.scene_peek.is_open is True


def test_closing_peek_externally_unchecks_menu(qapp, monkeypatch):
    # closing via the panel (not the menu) must still uncheck the menu action
    monkeypatch.setattr(sp, "reduced_motion", lambda: True)
    mw, _ = _win_with_field()
    mw.scene_peek = None
    mw.threedscene_act = QAction(); mw.threedscene_act.setCheckable(True)
    _bind_mainwindow_methods(mw, "_ensureScenePeek", "_onScenePeekToggled", "toggleScenePeek")

    mw.toggleScenePeek()                  # open
    assert mw.threedscene_act.isChecked() is True
    mw.scene_peek.close_btn.click()       # close from the panel
    assert mw.scene_peek.is_open is False
    assert mw.threedscene_act.isChecked() is False


# --- MainWindow wiring: "Open full 3D" hand-off -----------------------------------

def _mw_for_handoff(viewer):
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    mw = MainWindow.__new__(MainWindow)   # no widget creation here -> __new__ is fine
    mw.viewer = viewer
    calls = []

    class Field:
        def addTo3D(self):
            calls.append("addTo3D")

    mw.field = Field()
    return mw, calls


def test_openfullscene_raises_existing_open_viewer(qapp):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    calls = []

    class Viewer:
        is_closed = False
        def activateWindow(self): calls.append("activate")
        def setFocus(self): calls.append("focus")

    mw, field_calls = _mw_for_handoff(Viewer())
    MainWindow.openFullScene(mw)
    assert "activate" in calls
    assert field_calls == []              # does not spawn a new scene


def test_openfullscene_opens_for_selection_when_no_viewer(qapp):
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    mw, field_calls = _mw_for_handoff(None)
    MainWindow.openFullScene(mw)
    assert field_calls == ["addTo3D"]


def test_openfullscene_opens_when_viewer_closed(qapp):
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    class Viewer:
        is_closed = True

    mw, field_calls = _mw_for_handoff(Viewer())
    MainWindow.openFullScene(mw)
    assert field_calls == ["addTo3D"]


def test_full_button_closes_peek_then_hands_off(qapp, monkeypatch):
    _, _, peek = _peek(monkeypatch)
    calls = []
    peek.mainwindow.openFullScene = lambda: calls.append("full")
    peek.open()
    peek.full_btn.click()
    assert peek.is_open is False
    assert calls == ["full"]


# --- review hardening: menu/shortcut wiring, real event delivery, regressions ----

def test_menu_action_built_via_newAction_toggles_and_syncs(qapp, monkeypatch):
    # exercise the REAL menubar tuple through newAction (the "checkbox" branch +
    # the trigger->slot connection), not a hand-built QAction.
    from PySide6.QtWidgets import QMenu
    from PyReconstruct.modules.gui.utils.utils import newAction

    monkeypatch.setattr(sp, "reduced_motion", lambda: True)
    mw, _ = _win_with_field()
    mw.scene_peek = None
    _bind_mainwindow_methods(mw, "_ensureScenePeek", "_onScenePeekToggled", "toggleScenePeek")

    newAction(mw, QMenu(mw), ("threedscene_act", "3D scene peek", "checkbox", mw.toggleScenePeek))
    assert mw.threedscene_act.isCheckable() is True

    mw.threedscene_act.trigger()
    assert mw.scene_peek.is_open is True
    assert mw.threedscene_act.isChecked() is True
    mw.threedscene_act.trigger()
    assert mw.scene_peek.is_open is False
    assert mw.threedscene_act.isChecked() is False


def test_scenePeekIsOpen_guard_is_safe_before_built(qapp, monkeypatch):
    # checkActions reads this on every refresh, before the peek exists -> must
    # return False without raising (regression guard for the bool() short-circuit).
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    monkeypatch.setattr(sp, "reduced_motion", lambda: True)
    mw, _ = _win_with_field()
    mw.scene_peek = None
    assert MainWindow.scenePeekIsOpen(mw) is False        # not built yet

    mw.threedscene_act = QAction(); mw.threedscene_act.setCheckable(True)
    _bind_mainwindow_methods(mw, "_ensureScenePeek", "_onScenePeekToggled", "toggleScenePeek")
    mw.toggleScenePeek()                                  # build + open
    assert MainWindow.scenePeekIsOpen(mw) is True
    mw.toggleScenePeek()
    assert MainWindow.scenePeekIsOpen(mw) is False


def test_ctrl_shift_d_shortcut_binds_and_toggles(qapp, monkeypatch):
    # replicate createShortcuts' production idiom and verify the binding + toggle.
    # NOTE: keep this string identical to main_window.createShortcuts.
    from PySide6.QtGui import QKeySequence
    monkeypatch.setattr(sp, "reduced_motion", lambda: True)
    mw, _ = _win_with_field()
    mw.scene_peek = None
    _bind_mainwindow_methods(mw, "_ensureScenePeek", "_onScenePeekToggled", "toggleScenePeek")

    mw.addAction("", "Ctrl+Shift+D", lambda: mw.toggleScenePeek())
    bound = [a for a in mw.actions() if a.shortcut() == QKeySequence("Ctrl+Shift+D")]
    assert len(bound) == 1
    bound[0].trigger(); assert mw.scene_peek.is_open is True
    bound[0].trigger(); assert mw.scene_peek.is_open is False


def test_scrim_close_dispatches_through_event(qapp, monkeypatch):
    # route a real press through QApplication.sendEvent -> scrim.event() ->
    # mousePressEvent (catches a handler that event() never reaches).
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    _, _, peek = _peek(monkeypatch)
    peek.open()
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(peek.scrim, ev)
    assert peek.is_open is False


def test_escape_close_dispatches_through_event(qapp, monkeypatch):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    _, _, peek = _peek(monkeypatch)
    peek.open()
    peek.setFocus(Qt.OtherFocusReason)
    QApplication.sendEvent(peek, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert peek.is_open is False


def test_inflight_resize_retargets_running_animation(qapp, monkeypatch):
    # geom-1: resizing the field mid-slide must retarget the animation's end
    # value, not let it finish at the stale (old right-edge) geometry.
    _, field, peek = _peek(monkeypatch, reduced=False)
    peek.open()
    assert peek._anim.state() == QAbstractAnimation.Running
    field.setGeometry(40, 30, 1000, 760)                 # shrink during the slide
    peek.eventFilter(field, QResizeEvent(QSize(1000, 760), QSize(900, 760)))
    assert peek._anim.endValue() == peek.targetGeometry()
    peek._anim.setCurrentTime(peek._anim.duration())     # finish
    assert peek.geometry().x() + peek.geometry().width() == 40 + 1000


def test_animations_are_reused_not_accumulated(qapp, monkeypatch):
    # lifecycle: open/close reuses the two persistent animations rather than
    # allocating (and leaking) a fresh pair each cycle.
    from PySide6.QtCore import QPropertyAnimation
    _, _, peek = _peek(monkeypatch, reduced=False)
    a, s = peek._anim, peek._scrim_anim
    for _ in range(3):
        peek.open(); peek.close()
    assert peek._anim is a and peek._scrim_anim is s
    kids = [c for c in peek.children() if isinstance(c, QPropertyAnimation)]
    assert len(kids) == 2


def test_pill_rests_top_left_clear_of_palette(qapp, monkeypatch):
    # geom-2: the resting pill must not sit in the top-right mode-button column.
    _, _, peek = _peek(monkeypatch)
    assert peek.pill.x() == FIELD.x() + 12
    assert peek.pill.y() == FIELD.y() + 10
    assert peek.pill.geometry().right() < FIELD.x() + FIELD.width() // 2


def test_scrim_fade_is_faster_than_panel_slide(qapp, monkeypatch):
    # FID-1: the prototype's scrim (.26s) settles ahead of the sheet (.28s).
    _, _, peek = _peek(monkeypatch, reduced=False)
    assert peek._scrim_anim.duration() == sp.SCRIM_ANIM_MS == 260
    assert peek._anim.duration() == sp.ANIM_MS == 280
    assert peek._scrim_anim.duration() < peek._anim.duration()


def test_clear_scene_widget_destroys_previous(qapp, monkeypatch):
    # orphan fix: clearing must destroy the swapped-out widget, not leave it as
    # a parentless top-level that survives at the C++ level.
    from PySide6.QtCore import QEvent
    _, _, peek = _peek(monkeypatch)
    old = peek._scene
    peek.clearSceneWidget()
    assert peek._scene is None
    # deleteLater posts a DeferredDelete event; flush it explicitly (a plain
    # processEvents does not dispatch deferred deletes at this loop level).
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    try:
        import shiboken6
        assert shiboken6.isValid(old) is False
    except ImportError:
        assert old not in qapp.topLevelWidgets()
