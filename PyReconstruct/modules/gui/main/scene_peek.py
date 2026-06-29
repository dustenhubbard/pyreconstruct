"""UI v1 — the right-edge "3D Scene" slide-over ("peek").

A quick 3D peek that slides in over the field (the 2D stage) with a dimming
scrim, without leaving the 2D view. Mirrors the v1 prototype's ``.slideover``:

    header  (3D icon + "3D Scene" title + reset + close)
    body    (the 3D area — a faithful static preview in this slice; see the
             EMBEDDING SEAM note below for dropping in the live viewer)
    footer  ("drag to orbit · scroll to zoom" hint + "Open full 3D ↗")

Overlay convention (matches the mouse/zarr palettes): the panel and its scrim
are children of the MainWindow, positioned over ``mainwindow.field``'s rect and
repositioned whenever the field geometry changes. They are raised above the
palettes when open.

EMBEDDING SEAM
--------------
``ScenePeek.body`` is a container with ``setSceneWidget(w)`` / ``clearSceneWidget()``.
To host the real ``CustomPlotter`` (a ``QVTKRenderWindowInteractor``), build it
parented to ``body`` instead of its own ``Container`` window and hand it to
``setSceneWidget``. That requires letting ``CustomPlotter`` accept an external
parent (today it always creates its own ``Container`` QMainWindow); the precise
refactor is documented in the slice's report. Live VTK rendering needs a real GL
context and cannot be exercised offscreen, so this slice ships the static
preview by default and the footer "Open full 3D" hands off to the existing
window-based viewer.
"""

import os

from PySide6.QtWidgets import (
    QWidget,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QGraphicsOpacityEffect,
    QApplication,
)
from PySide6.QtCore import (
    Qt,
    QRect,
    QEvent,
    QAbstractAnimation,
    QPropertyAnimation,
    QEasingCurve,
    QSettings,
    Signal,
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QLinearGradient,
    QRadialGradient,
    QPen,
    QBrush,
    QPainterPath,
    QPolygonF,
)
from PySide6.QtCore import QPointF


# ---- geometry / motion constants (faithful to the prototype) -------------------
PANEL_MAX_W = 460          # .slideover width: min(460px, 62%)
PANEL_W_FRAC = 0.62
ANIM_MS = 280              # .slideover transition: transform .28s
SCRIM_ANIM_MS = 260        # .scrim transition: opacity .26s (settles ~20ms ahead)
SCRIM_RGBA = (3, 5, 8, 107)  # rgba(3,5,8,.42) -> .42*255 ~= 107

# Legend entries mirror the prototype's so-legend (chrome only; not live data).
_LEGEND = [
    ("#ff5d9e", "d001 · dendrite"),
    ("#42e08b", "a014 · axon"),
    ("#ffb347", "mito_233"),
]


def reduced_motion() -> bool:
    """True when slide animation should be skipped (the reduced-motion case).

    The prototype honors ``@media (prefers-reduced-motion: reduce)``. PySide6
    6.5 exposes no OS reduced-motion hint, so this resolves, in order:

      1. ``PYRECONSTRUCT_REDUCED_MOTION`` env var (truthy) — also used by tests/CI;
      2. the global ``reduce_motion`` preference in QSettings("KHLab","PyReconstruct");
      3. otherwise False (animate).

    Wiring (1)/(2) to a real OS preference is a clean follow-up once Qt exposes one.
    """
    val = os.environ.get("PYRECONSTRUCT_REDUCED_MOTION")
    if val is not None:
        return val.strip().lower() in ("1", "true", "yes", "on")
    try:
        return bool(
            QSettings("KHLab", "PyReconstruct").value("reduce_motion", False, type=bool)
        )
    except Exception:
        return False


def _is_dark() -> bool:
    """Whether the active app theme is dark.

    Uses the theme module's authoritative scheme (the app themes via a
    qdarkstyle *stylesheet*, which does not reliably update ``QPalette``, so
    palette lightness alone is unreliable). Falls back to palette lightness only
    if the theme module is unavailable."""
    try:
        from PyReconstruct.modules.gui.utils import theme
        return theme.current_scheme() == "dark"
    except Exception:
        app = QApplication.instance()
        if app is None:
            return True
        return app.palette().window().color().lightness() < 128


class _Scrim(QWidget):
    """Dimming overlay behind the panel; a click on it closes the peek."""

    def __init__(self, peek: "ScenePeek"):
        super().__init__(peek.parentWidget())
        self._peek = peek
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setCursor(Qt.ArrowCursor)
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(*SCRIM_RGBA))

    def mousePressEvent(self, event):
        self._peek.close()


class _PlaceholderScene(QWidget):
    """A faithful static preview of the 3D scene (mirrors the prototype so-body).

    Painted, not live: a radial-lit stage, a faint teal floor grid, a dashed
    bounding box, and a few organic "mesh" blobs in the legend colors. Replaced
    by the real viewer via ``ScenePeek.setSceneWidget`` (see module docstring).
    """

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        dark = _is_dark()

        # radial-lit background (prototype: radial-gradient at 50% 12%)
        bg = QRadialGradient(w * 0.5, h * 0.12, max(w, h) * 1.1)
        if dark:
            bg.setColorAt(0.0, QColor("#131a26"))
            bg.setColorAt(0.7, QColor("#0a0e15"))
        else:
            bg.setColorAt(0.0, QColor("#e9eef7"))
            bg.setColorAt(0.75, QColor("#d6deea"))
        p.fillRect(self.rect(), QBrush(bg))

        cx = w * 0.5
        # floor grid (teal, faint) — a few perspective lines
        teal = QColor("#2bd4b8")
        teal.setAlphaF(0.16)
        p.setPen(QPen(teal, 1))
        fy = h * 0.78
        for i, frac in enumerate((0.0, 0.06, 0.12)):
            yy = fy - h * frac
            half = w * (0.34 - i * 0.05)
            p.drawLine(int(cx - half), int(yy), int(cx + half), int(yy))
        for fx in (-0.18, 0.0, 0.18):
            p.drawLine(int(cx + w * fx * 0.5), int(fy + h * 0.05),
                       int(cx + w * fx), int(fy - h * 0.16))

        # dashed bounding box (perspective-ish parallelogram)
        box = QColor("#3a4655")
        box.setAlphaF(0.6)
        pen = QPen(box, 1.1)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        bx, by, bw, bh = w * 0.16, h * 0.18, w * 0.5, h * 0.46
        off = w * 0.06
        front = QPolygonF([
            QPointF(bx, by), QPointF(bx + bw, by - h * 0.05),
            QPointF(bx + bw, by + bh), QPointF(bx, by + bh + h * 0.05),
        ])
        p.drawPolygon(front)
        p.drawLine(QPointF(bx, by), QPointF(bx - off, by + h * 0.07))
        p.drawLine(QPointF(bx - off, by + h * 0.07), QPointF(bx - off, by + bh + h * 0.03))

        # mesh blobs (legend colors), with a soft highlight to read as 3D
        def blob(path, color):
            grad = QLinearGradient(path.boundingRect().topLeft(),
                                   path.boundingRect().bottomRight())
            c = QColor(color)
            grad.setColorAt(0.0, c.lighter(135))
            grad.setColorAt(1.0, c.darker(125))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(grad))
            p.drawPath(path)

        # dendrite (pink), tall tube
        den = QPainterPath()
        den.moveTo(w * 0.26, h * 0.66)
        den.cubicTo(w * 0.20, h * 0.40, w * 0.30, h * 0.27, w * 0.46, h * 0.27)
        den.cubicTo(w * 0.66, h * 0.27, w * 0.70, h * 0.43, w * 0.62, h * 0.56)
        den.cubicTo(w * 0.55, h * 0.66, w * 0.40, h * 0.62, w * 0.26, h * 0.66)
        blob(den, "#ff5d9e")

        # axon (green)
        ax = QPainterPath()
        ax.addEllipse(QPointF(w * 0.62, h * 0.62), w * 0.13, h * 0.12)
        blob(ax, "#42e08b")

        # mitochondrion (orange)
        mito = QPainterPath()
        mito.addEllipse(QPointF(w * 0.42, h * 0.40), w * 0.10, h * 0.055)
        blob(mito, "#ffb347")

        # legend (bottom-left), mirrors so-legend
        p.setRenderHint(QPainter.Antialiasing, True)
        lx, ly = 14, h - 14 - len(_LEGEND) * 20
        f = p.font()
        f.setPointSizeF(8.5)
        p.setFont(f)
        for i, (col, label) in enumerate(_LEGEND):
            yy = ly + i * 20
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRect(lx, yy, 9, 9), 2, 2)
            p.setPen(QColor("#9aa7bb") if dark else QColor("#54627a"))
            p.drawText(lx + 16, yy + 9, label)


class ScenePeek(QWidget):
    """The right-edge 3D slide-over panel (+ its scrim + open-pill affordance)."""

    # emitted when open/closed state changes (so the menu checkbox can sync)
    toggled = Signal(bool)

    def __init__(self, mainwindow):
        super().__init__(mainwindow)
        self.mainwindow = mainwindow
        self.is_open = False

        self.setObjectName("scenePeek")
        self.setAutoFillBackground(True)

        # scrim (sibling, painted behind the panel)
        self.scrim = _Scrim(self)
        self._scrim_fx = QGraphicsOpacityEffect(self.scrim)
        self._scrim_fx.setOpacity(0.0)
        self.scrim.setGraphicsEffect(self._scrim_fx)

        # persistent animations, reused across every open/close so stopped
        # QPropertyAnimation objects never accumulate on this long-lived widget
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setDuration(ANIM_MS)
        self._scrim_anim = QPropertyAnimation(self._scrim_fx, b"opacity", self)
        self._scrim_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._scrim_anim.setDuration(SCRIM_ANIM_MS)

        self._buildUi()
        self._applyStyle()

        # open affordance: a floating "3D Scene" pill over the field's top-right
        self.pill = QPushButton("◈  3D Scene", mainwindow)
        self.pill.setObjectName("scenePeekPill")
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.setToolTip("Show the 3D scene peek  (Ctrl+Shift+D)")
        self.pill.clicked.connect(self.open)
        self._stylePill()

        # keep pinned to the field; reposition when its geometry changes
        self.mainwindow.field.installEventFilter(self)

        self.hide()
        self.reposition()

    # ---- construction ----------------------------------------------------------

    def _buildUi(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header
        header = QWidget(self)
        header.setObjectName("soHead")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 11, 12, 11)
        hl.setSpacing(8)
        title = QLabel("◈  3D Scene", header)
        title.setObjectName("soTitle")
        self.reset_btn = QPushButton("⟲", header)   # ⟲ reset
        self.reset_btn.setObjectName("soIconBtn")
        self.reset_btn.setToolTip("Reset view")
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.clicked.connect(self.resetView)
        self.close_btn = QPushButton("✕", header)    # ✕ close
        self.close_btn.setObjectName("soIconBtn")
        self.close_btn.setToolTip("Close  (Esc)")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.close)
        hl.addWidget(title)
        hl.addStretch(1)
        hl.addWidget(self.reset_btn)
        hl.addWidget(self.close_btn)

        # body (the 3D area / embedding seam)
        self.body = QWidget(self)
        self.body.setObjectName("soBody")
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        self._scene = _PlaceholderScene(self.body)
        bl.addWidget(self._scene)

        # footer
        footer = QWidget(self)
        footer.setObjectName("soFoot")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(14, 9, 14, 9)
        fl.setSpacing(8)
        hint = QLabel("⟲  drag to orbit · scroll to zoom", footer)
        hint.setObjectName("soHint")
        self.full_btn = QPushButton("Open full 3D ↗", footer)
        self.full_btn.setObjectName("soFullBtn")
        self.full_btn.setCursor(Qt.PointingHandCursor)
        self.full_btn.clicked.connect(self._openFull)
        fl.addWidget(hint)
        fl.addStretch(1)
        fl.addWidget(self.full_btn)

        root.addWidget(header, 0)
        root.addWidget(self.body, 1)
        root.addWidget(footer, 0)

    # ---- embedding seam --------------------------------------------------------

    def setSceneWidget(self, widget: QWidget):
        """Swap the static preview for a live scene widget (e.g. CustomPlotter)."""
        layout = self.body.layout()
        self.clearSceneWidget()
        widget.setParent(self.body)
        layout.addWidget(widget)
        self._scene = widget

    def clearSceneWidget(self):
        """Remove and destroy the current scene widget (the placeholder, or a
        previously embedded viewer). Ownership contract: clearing destroys the
        widget; a caller that needs to re-host a live viewer elsewhere should
        hold its own reference before calling setSceneWidget/clearSceneWidget."""
        layout = self.body.layout()
        if self._scene is not None:
            layout.removeWidget(self._scene)
            self._scene.setParent(None)
            self._scene.deleteLater()
            self._scene = None

    # ---- styling ---------------------------------------------------------------

    def _applyStyle(self):
        dark = _is_dark()
        if dark:
            panel, hair, txt, dim, accent = "#161b22", "#2a313c", "#e6eaf0", "#9aa7bb", "#4c8dff"
            teal, btn_bg = "#2bd4b8", "#1d232c"
        else:
            panel, hair, txt, dim, accent = "#ffffff", "#dbe1ea", "#16202e", "#54627a", "#2f6fe0"
            teal, btn_bg = "#0f9e88", "#f4f6fa"
        self.setStyleSheet(f"""
            #scenePeek {{ background: {panel}; border-left: 1px solid {hair}; }}
            #soHead {{ background: {panel}; border-bottom: 1px solid {hair}; }}
            #soFoot {{ background: {panel}; border-top: 1px solid {hair}; }}
            #soTitle {{ color: {teal}; font-size: 13px; font-weight: 650; }}
            #soHint {{ color: {dim}; font-size: 11px; }}
            #soIconBtn {{
                background: {btn_bg}; color: {dim}; border: 1px solid {hair};
                border-radius: 7px; min-width: 28px; min-height: 26px; font-size: 13px;
            }}
            #soIconBtn:hover {{ color: {txt}; border-color: {accent}; }}
            #soFullBtn {{
                background: {btn_bg}; color: {dim}; border: 1px solid {hair};
                border-radius: 8px; padding: 5px 12px; font-size: 12px; font-weight: 550;
            }}
            #soFullBtn:hover {{ color: {txt}; border-color: {teal}; }}
        """)

    def _stylePill(self):
        dark = _is_dark()
        if dark:
            bg, hair, dim, txt, teal = "#1d232c", "#2a313c", "#9aa7bb", "#e6eaf0", "#2bd4b8"
            teal_weak = "#10322e"
        else:
            bg, hair, dim, txt, teal = "#f4f6fa", "#dbe1ea", "#54627a", "#16202e", "#0f9e88"
            teal_weak = "#d2f1ea"
        self.pill.setStyleSheet(f"""
            #scenePeekPill {{
                background: {bg}; color: {dim}; border: 1px solid {hair};
                border-radius: 8px; padding: 6px 11px; font-size: 12px; font-weight: 550;
            }}
            #scenePeekPill:hover {{ color: {txt}; border-color: {teal}; background: {teal_weak}; }}
        """)

    def refreshTheme(self):
        """Re-apply theme-derived styling (call after an app theme change)."""
        self._applyStyle()
        self._stylePill()
        if isinstance(self._scene, _PlaceholderScene):
            self._scene.update()

    # ---- geometry --------------------------------------------------------------

    def _fieldRect(self) -> QRect:
        """The field's rect in MainWindow coordinates (the stage to overlay)."""
        f = self.mainwindow.field
        return QRect(f.x(), f.y(), f.width(), f.height())

    def _panelWidth(self, field_w: int) -> int:
        return max(1, min(PANEL_MAX_W, int(field_w * PANEL_W_FRAC)))

    def targetGeometry(self) -> QRect:
        """Docked (open) geometry: pinned to the field's right edge, full height."""
        r = self._fieldRect()
        pw = self._panelWidth(r.width())
        return QRect(r.x() + r.width() - pw, r.y(), pw, r.height())

    def offscreenGeometry(self) -> QRect:
        """Hidden (closed) geometry: fully off the field's right edge."""
        r = self._fieldRect()
        pw = self._panelWidth(r.width())
        return QRect(r.x() + r.width(), r.y(), pw, r.height())

    def reposition(self):
        """Re-pin scrim + panel + pill to the current field geometry.

        If a slide is in flight, retarget it (setEndValue) rather than snapping,
        so a resize/maximize during the ~280ms animation still settles flush to
        the new right edge instead of finishing at a stale target."""
        r = self._fieldRect()
        self.scrim.setGeometry(r)
        target = self.targetGeometry() if self.is_open else self.offscreenGeometry()
        if self._anim.state() == QAbstractAnimation.Running:
            self._anim.setEndValue(target)
        else:
            self.setGeometry(target)
        # pill sits at the field's TOP-LEFT: the top-right is the mouse palette's
        # mode-button column, so the left corner keeps both affordances clear
        pw = self.pill.sizeHint().width()
        self.pill.setGeometry(r.x() + 12, r.y() + 10, pw, 30)
        self.pill.setVisible(not self.is_open)

    # ---- open / close ----------------------------------------------------------

    def open(self):
        if self.is_open:
            return
        self.is_open = True
        r = self._fieldRect()
        self.scrim.setGeometry(r)
        self.scrim.show()
        self.scrim.raise_()
        self.show()
        self.raise_()
        self.pill.setVisible(False)
        self.setFocus(Qt.OtherFocusReason)

        target = self.targetGeometry()
        if reduced_motion():
            self._stopAnims()
            self.setGeometry(target)
            self._scrim_fx.setOpacity(1.0)
        else:
            self.setGeometry(self.offscreenGeometry())
            self._animateTo(target, fade_in=True)
        self.toggled.emit(True)

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        if reduced_motion():
            self._stopAnims()
            self.setGeometry(self.offscreenGeometry())
            self._scrim_fx.setOpacity(0.0)
            self._afterClose()
        else:
            self._animateTo(self.offscreenGeometry(), fade_in=False,
                            on_done=self._afterClose)
        self.toggled.emit(False)

    def _afterClose(self):
        self.hide()
        self.scrim.hide()
        self.pill.setVisible(True)

    def toggle(self):
        self.close() if self.is_open else self.open()

    def _stopAnims(self):
        """Stop both animations and drop any pending finished callback, so a
        stopped close animation can't later fire _afterClose out of turn."""
        self._anim.stop()
        self._scrim_anim.stop()
        try:
            self._anim.finished.disconnect()
        except (RuntimeError, TypeError):
            pass

    def _animateTo(self, geom: QRect, fade_in: bool, on_done=None):
        self._stopAnims()
        # panel slide — reuse the persistent animation (no per-call allocation)
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(geom)
        if on_done is not None:
            self._anim.finished.connect(on_done)
        # scrim fade
        self._scrim_anim.setStartValue(self._scrim_fx.opacity())
        self._scrim_anim.setEndValue(1.0 if fade_in else 0.0)
        self._anim.start()
        self._scrim_anim.start()

    # ---- actions ---------------------------------------------------------------

    def resetView(self):
        """Reset the scene view. No-op for the static preview; when a live scene
        widget is embedded, this is where its camera reset is invoked."""
        scene = self._scene
        reset = getattr(scene, "resetCamera", None) or getattr(scene, "home", None)
        if callable(reset):
            reset()
        elif isinstance(scene, _PlaceholderScene):
            scene.update()

    def _openFull(self):
        """Hand off to the existing full 3D window, then dismiss the peek."""
        self.close()
        self.mainwindow.openFullScene()

    # ---- events ----------------------------------------------------------------

    def eventFilter(self, obj, event):
        # getattr guard: a deferred field event can arrive after this peek has
        # been torn down (its Python attrs cleared), so skip rather than raise.
        mw = getattr(self, "mainwindow", None)
        if mw is not None and obj is mw.field and event.type() in (
            QEvent.Resize, QEvent.Move, QEvent.Show
        ):
            self.reposition()
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
