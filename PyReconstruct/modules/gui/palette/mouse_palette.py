import os
import re

from PySide6.QtWidgets import (
    QWidget, QStyle, QSlider, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
)
from PySide6.QtGui import (
    QIcon, QPixmap, QColor, QFont, QPainter, QPen, QPainterPath,
)
from PySide6.QtCore import QSize, Qt, QRectF

from .buttons import PaletteButton, ModeButton, MoveableButton
from .scale_bar import ScaleBar
from .outlined_label import OutlinedLabel
from .help import palette_help

from PyReconstruct.modules.datatypes import Series, Trace
from PyReconstruct.modules.constants import (
    locations as loc
)
from PyReconstruct.modules.gui.dialog import TracePaletteDialog, QuickDialog
from PyReconstruct.modules.gui.popup import TextWidget
from PyReconstruct.modules.gui.utils import icons as icon_utils
from PyReconstruct.modules.gui.utils import theme


class PaletteCard(QFrame):
    """The floating tool-palette card — the v1 prototype's ``.palette``.

    A rounded, faintly translucent panel that holds the mode buttons. Everything
    is hand-painted in :meth:`paintEvent` (no ``QGraphicsEffect``, which Qt does
    not apply under ``QWidget.render``/``grab`` and so would not show in the
    offscreen preview): a layered soft drop shadow for the floating lift, the
    rounded translucent body + hairline border (the translucency lets the field
    show faintly through, standing in for the prototype's ``backdrop-filter:
    blur`` — which Qt has no native equivalent for), and a soft accent halo
    behind the active tool (the prototype's ``.tool.active`` glow).

    The widget is larger than the visible card by :data:`SHADOW_MARGIN` on every
    side so the cast shadow has room to fall without being clipped to the body.
    """

    #: transparent padding around the visible body, holding the cast shadow
    SHADOW_MARGIN = 16

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.tool_buttons = []   # mode buttons, for drawing the active halo
        self.dividers = []       # thin group separators
        self.header = None       # the "TOOLS" caption
        self._radius = 14.0      # prototype --r-lg
        self._bg = QColor("#161b22")
        self._bg.setAlphaF(0.92)
        self._border = QColor("#2a313c")
        self._accent = QColor(theme.ACCENT)
        self._shadow_strength = 140  # peak shadow alpha (tuned per scheme)

    def bodyRect(self) -> QRectF:
        """The visible (rounded) card rect inside the shadow padding."""
        m = self.SHADOW_MARGIN
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def applyTheme(self, tokens: dict, accent_hex: str,
                   alpha: float = 0.92, shadow_alpha: int = 140):
        """Recolor the card, header, and dividers for the active theme."""
        self._bg = QColor(tokens["panel"])
        self._bg.setAlphaF(alpha)
        self._border = QColor(tokens["hair"])
        self._accent = QColor(accent_hex)
        self._shadow_strength = shadow_alpha
        if self.header is not None:
            self.header.setStyleSheet(
                "color: %s; background: transparent;" % tokens["txt_faint"]
            )
        for d in self.dividers:
            line = getattr(d, "line", d)  # recolor the inset hairline
            line.setStyleSheet(
                "background-color: %s; border: 0px;" % tokens["hair"]
            )
        self.update()

    @staticmethod
    def _rounded(rect: QRectF, radius: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        body = self.bodyRect()

        # soft drop shadow (prototype --shadow): layered, offset-down rounded
        # rects painted largest/faintest first.
        steps = 12
        for i in range(steps, 0, -1):
            frac = i / steps
            grow = frac * 7.0
            dy = frac * 9.0 + 2.0
            alpha = int(self._shadow_strength * (1.0 - frac) * 0.5) + 3
            col = QColor(0, 0, 0, max(0, min(255, alpha)))
            sr = body.adjusted(-grow, -grow + dy, grow, grow + dy)
            p.fillPath(self._rounded(sr, self._radius + grow), col)

        inner = body.adjusted(0.5, 0.5, -0.5, -0.5)
        path = self._rounded(inner, self._radius)

        # translucent body
        p.fillPath(path, self._bg)

        # active-tool halo, clipped to the body so it never bleeds past the
        # rounded corners; the button paints its opaque accent fill on top,
        # leaving the halo as a glow rim.
        p.save()
        p.setClipPath(path)
        for b in self.tool_buttons:
            if b.isChecked():
                base = QRectF(b.geometry())
                for grow, a in ((7.0, 42), (4.0, 70), (1.5, 105)):
                    c = QColor(self._accent)
                    c.setAlpha(a)
                    gl = base.adjusted(-grow, -grow + 3.0, grow, grow + 3.0)
                    p.fillPath(self._rounded(gl, 12.0), c)
                break
        p.restore()

        # hairline border on top of body + halo
        pen = QPen(self._border)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()


class MousePalette():

    def __init__(self, mainwindow : QWidget):
        """Create the mouse dock widget object.
        
            Params:
                palette_traces (list): list of traces to include on palette
                selected_trace (Trace): the trace that is selected on the palette
                mainwindow (MainWindow): the parent main window of the dock
        """
        self.mainwindow = mainwindow
        self.series = self.mainwindow.series
        self.series : Series
        
        self.mblen = 38  # mode (tool) button size — prototype .tool is 38px
        self.pblen = 40  # palette button size
        self.ibw = 90  # inc button width
        self.ibh = 35  # inc button height
        self.bcsize = 30  # brightness/contrast button size

        self.is_dragging = False

        # active theme tokens for the floating tool-palette chrome
        self._tokens = theme.tokens()

        # create the floating tool palette (mode buttons in a docked card).
        # mode_x/mode_y record which field edge the card is docked to (right by
        # default, left when left-handed); the field's corner-text painter reads
        # mode_x to stay clear of the palette, so it is kept in sync here.
        self.mode_x = 0.99
        self.mode_y = 0.01
        self.mode_buttons = {}
        self.createPaletteCard()

        # create palette buttons
        self.trace_x = 0.51
        self.trace_y = 0.99
        traces = self.series.palette_traces[self.series.palette_index[0]]
        self.palette_buttons = [None] * len(traces)
        for i, trace in enumerate(traces):  # create all the palette buttons
            self.createPaletteButton(trace, i)
        self.palette_buttons[self.series.palette_index[1]].setChecked(True)

        # create palette increments
        self.createPaletteSideButtons()
        
        self.selected_mode = "pointer"

        # create label
        self.label = OutlinedLabel(self.mainwindow)
        font = self.label.font()
        font.setFamily("Courier New")
        font.setBold(True)
        font.setPointSize(16)
        self.label.setFont(font)
        self.updateLabel()
        self.label.show()

        # create increment buttons
        self.inc_x = 0.99
        self.inc_y = 0.99
        self.createIncrementButtons()

        # create brightness/contrast buttons
        self.bc_x = 0.99
        self.bc_y = 0.8
        self.createBCButtons()

        self.palette_hidden = False
        self.inc_hidden = False
        self.bc_hidden = False
        self.sb_hidden = False
        
        self.help_widget = None

        # create scale palette
        self.sb_x = 0.01
        self.sb_y = 0.99
        self.createSB()
    
    @staticmethod
    def _stripped(name : str) -> str:
        """Tool name -> icon key/filename (lower-cased, spaces/slashes removed)."""
        stripped = name
        for c in (" ", "/"):
            stripped = stripped.replace(c, "")
        return stripped.lower()

    def _mode_icon_px(self) -> int:
        """Render size for a mode icon — 20px line icons inside the 38px tool
        button, matching the prototype's ``.tool svg{width:20px}``."""
        return 20

    # tool display name -> the series option holding its keyboard shortcut, so
    # the keycap hint + tooltip show the user's *current* (override-aware) key.
    # Scissors and Ztool have no shortcut option (and so no keycap).
    _SHORTCUT_OPTS = {
        "Pointer": "usepointer_act",
        "Pan/Zoom": "usepanzoom_act",
        "Knife": "useknife_act",
        "Closed Trace": "usectrace_act",
        "Open Trace": "useotrace_act",
        "Stamp": "usestamp_act",
        "Grid": "usegrid_act",
        "Flag": "useflag_act",
        "Host": "usehost_act",
    }

    def _modeShortcut(self, name : str) -> str:
        """The current keyboard shortcut for a mode (or "" if it has none)."""
        opt = self._SHORTCUT_OPTS.get(name)
        if not opt:
            return ""
        try:
            return self.series.getOption(opt) or ""
        except Exception:
            return ""

    def createPaletteCard(self):
        """Build the floating tool-palette card and its mode buttons.

        Buttons keep their original top-to-bottom order (which also encodes the
        mouse-mode index); thin dividers separate them into the prototype's tool
        families: navigate · cut · trace · annotate.
        """
        self.tool_card = PaletteCard(self.mainwindow)
        sm = PaletteCard.SHADOW_MARGIN
        # pin to the button width + 7px padding (prototype --pal-w:52px) plus the
        # transparent shadow margin, so the header caption can never widen the
        # visible card past the prototype.
        self.tool_card.setFixedWidth(self.mblen + 14 + 2 * sm)
        layout = QVBoxLayout(self.tool_card)
        layout.setContentsMargins(7 + sm, 6 + sm, 7 + sm, 7 + sm)
        layout.setSpacing(3)

        # "TOOLS" caption (prototype .ph)
        header = QLabel("TOOLS", self.tool_card)
        hf = QFont()
        hf.setPixelSize(9)
        hf.setBold(True)
        hf.setLetterSpacing(QFont.AbsoluteSpacing, 0.7)
        header.setFont(hf)
        header.setAlignment(Qt.AlignHCenter)
        header.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.tool_card.header = header
        layout.addWidget(header)

        # groups preserve the legacy order; (name, mouse_mode) — mouse_mode is
        # the int passed to changeMouseMode and must stay 0..10 as before.
        groups = [
            [("Pointer", 0), ("Pan/Zoom", 1)],                       # navigate
            [("Knife", 2), ("Scissors", 3)],                         # cut
            [("Closed Trace", 4), ("Open Trace", 5), ("Stamp", 6)],  # trace
            [("Grid", 7), ("Flag", 8), ("Host", 9), ("Ztool", 10)],  # annotate
        ]
        for gi, group in enumerate(groups):
            if gi > 0:
                div = self._makeDivider()
                layout.addWidget(div)
                self.tool_card.dividers.append(div)
            for name, mouse_mode in group:
                b = self.createModeButton(name, mouse_mode)
                layout.addWidget(b, 0, Qt.AlignHCenter)
                self.tool_card.tool_buttons.append(b)

        # initial styling + placement
        self.refreshModeIcons()
        self.tool_card.show()
        self.placePaletteCard()

    def _makeDivider(self) -> QWidget:
        """A thin, inset group separator (prototype .palette .div: 1px hairline
        inset 6px from each edge). The hairline lives inside a transparent
        wrapper whose layout supplies the inset (a bare QWidget's contentsMargins
        do not inset its background fill)."""
        wrap = QWidget(self.tool_card)
        wrap.setFixedHeight(1)
        wrap.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h = QHBoxLayout(wrap)
        h.setContentsMargins(6, 0, 6, 0)
        h.setSpacing(0)
        line = QWidget(wrap)
        line.setFixedHeight(1)
        line.setStyleSheet(
            "background-color: %s; border: 0px;" % self._tokens["hair"]
        )
        h.addWidget(line)
        wrap.line = line  # the colored hairline (recolored on theme change)
        return wrap

    def createModeButton(self, name : str, pos : int):
        """Create one mouse-mode button for the tool-palette card.

            Params:
                name (str): the mode display name (and icon key)
                pos (int): the mouse-mode index passed to changeMouseMode
        """
        b = ModeButton(self.tool_card, self)
        b.mode_name = name
        b.setFixedSize(self.mblen, self.mblen)
        mouse_mode = pos

        stripped_name = self._stripped(name)

        # prefer the modern theme-tinted SVG icon; Flag/Host fall back to a glyph
        if icon_utils.has_icon(stripped_name):
            icon_px = self._mode_icon_px()
            b.setIcon(icon_utils.tool_icon(
                stripped_name, icon_px, self._tokens["txt_dim"]))
            b.setIconSize(QSize(icon_px, icon_px))

        b.setCheckable(True)

        # tooltip (name + shortcut) and the small bottom-right keycap hint
        key = self._modeShortcut(name)
        if key:
            b.setToolTip("%s  (%s)" % (name, key))
            kc = QLabel(key, b)
            kf = QFont("Monospace")
            kf.setStyleHint(QFont.Monospace)
            kf.setPixelSize(9)
            kc.setFont(kf)
            kc.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            kc.setAlignment(Qt.AlignRight | Qt.AlignBottom)
            kc.setGeometry(2, 2, self.mblen - 5, self.mblen - 4)
            b.keycap = kc
        else:
            b.setToolTip(name)

        if pos == 0:  # Pointer selected by default
            b.setChecked(True)
        b.clicked.connect(lambda : self.activateModeButton(name))
        # dictionary -- name : (button object, mouse mode, position)
        self.mode_buttons[name] = (b, mouse_mode, pos)

        # right-click dialogs / glyph tools (unchanged behavior)
        if name == "Pointer":
            b.setRightClickEvent(self.mainwindow.modifyPointer)
        elif name == "Closed Trace" or name == "Open Trace":
            b.setRightClickEvent(self.mainwindow.changeTraceMode)
        elif name == "Grid":
            b.setRightClickEvent(self.mainwindow.modifyGrid)
        elif name == "Flag":
            b.setRightClickEvent(self.modifyFlag)
            self.setFlag()  # sets the flag glyph + color
        elif name == "Knife":
            b.setRightClickEvent(self.mainwindow.modifyKnife)
        elif name == "Host":
            # glyph tool (no SVG): size it like the 20px line icons so the
            # centered ⎋ doesn't crowd the corner keycap
            f = b.font()
            f.setPointSize(15)
            b.setFont(f)
            b.setText("⎋")

        b.show()
        return b

    def styleModeButton(self, button):
        """Style one mode button for its current state (resting/hover/active)
        and theme.

        Resting = transparent with a ``txt_dim`` icon; hover = faint ``panel_2``
        fill + brighter ``txt`` icon; active = accent fill + white icon (the soft
        glow is painted by the card behind it). Flag/Host are glyph tools, so
        their color rides on the button ``color`` rather than an icon tint.
        """
        t = self._tokens
        active = button.isChecked()
        if active:
            button.setStyleSheet(
                "QPushButton { background-color: %s; border: 0px; "
                "border-radius: 10px; color: %s; }"
                % (theme.ACCENT, theme.ACCENT_TEXT)
            )
        else:
            button.setStyleSheet(
                "QPushButton { background-color: transparent; border: 0px; "
                "border-radius: 10px; color: %s; }"
                "QPushButton:hover { background-color: %s; color: %s; }"
                % (t["txt_dim"], t["panel_2"], t["txt"])
            )

        stripped = self._stripped(button.mode_name)
        if icon_utils.has_icon(stripped):
            if active:
                color = theme.ACCENT_TEXT
            elif getattr(button, "_hovered", False):
                color = t["txt"]
            else:
                color = t["txt_dim"]
            px = self._mode_icon_px()
            button.setIcon(icon_utils.tool_icon(stripped, px, color))
            button.setIconSize(QSize(px, px))

        if button.keycap is not None:
            if active:
                button.keycap.setStyleSheet(
                    "color: rgba(255, 255, 255, 0.72); background: transparent;")
            else:
                button.keycap.setStyleSheet(
                    "color: %s; background: transparent;" % t["txt_faint"])

    def refreshModeIcons(self):
        """Re-style the tool palette for the current theme / active tool.

        Called on theme changes and after the active tool changes so the card,
        icons, keycaps, dividers, and the active-tool accent all follow
        light/dark (prototype: active = accent bg + white icon + glow; resting
        tools at the theme icon color).
        """
        self._tokens = theme.tokens()
        card = getattr(self, "tool_card", None)
        if card is not None:
            # lighter cast shadow on light chrome (prototype's light --shadow)
            shadow_alpha = 55 if theme.current_scheme() == "light" else 140
            card.applyTheme(self._tokens, theme.ACCENT, shadow_alpha=shadow_alpha)
        for _name, (b, _mode, _pos) in self.mode_buttons.items():
            self.styleModeButton(b)
        if card is not None:
            card.update()

    def _fieldRect(self):
        """Field bounds in main-window coordinates: (x1, x2, y1, y2)."""
        field = self.mainwindow.field
        fx1 = field.x()
        fy1 = field.y()
        return fx1, fx1 + field.width(), fy1, fy1 + field.height()

    def placePaletteCard(self):
        """Dock the tool-palette card to a field edge, vertically centered.

        Right edge by default; the left edge when the user is left-handed. The
        chosen side is mirrored into mode_x so the field's corner-text painter
        keeps clear of the palette.
        """
        card = getattr(self, "tool_card", None)
        if card is None:
            return
        # width is pinned (setFixedWidth); height hugs the laid-out content. The
        # widget extends past the visible body by SHADOW_MARGIN on each side, so
        # dock the *body* (not the widget) to the field edge.
        cw = card.width()
        ch = card.sizeHint().height()
        sm = card.SHADOW_MARGIN
        fx1, fx2, fy1, fy2 = self._fieldRect()
        margin = 14  # prototype right:14px
        left_handed = bool(self.series.getOption("left_handed"))
        if left_handed:
            x = fx1 + margin - sm           # body left -> fx1 + margin
            self.mode_x = 0.01
        else:
            x = fx2 - margin + sm - cw      # body right -> fx2 - margin
            self.mode_x = 0.99
        y = fy1 + (fy2 - fy1 - ch) / 2
        if y < fy1:
            y = fy1
        card.setGeometry(int(round(x)), int(round(y)), cw, ch)
        card.raise_()

    def toggleHandedness(self):
        """Flip the tool palette to the other field edge and persist it."""
        self.series.setOption(
            "left_handed", not bool(self.series.getOption("left_handed")))
        self.applyHandedness()

    def applyHandedness(self):
        """Reposition the palette for the current left_handed setting and keep
        the View-menu checkbox in sync."""
        self.placePaletteCard()
        act = getattr(self.mainwindow, "lefthanded_act", None)
        if act is not None:
            blocked = act.blockSignals(True)
            act.setChecked(bool(self.series.getOption("left_handed")))
            act.blockSignals(blocked)
    
    def placePaletteButton(self, button : PaletteButton, pos : int):
        """Place the palette button in the main window.
        
            Params:
                button (PaletteButton): the palette button to move
                pos (int): its position
        """
        # place the palette button in the middle of the FIELD (not mainwindow)
        x, y = self.getButtonCoords("trace")
        if pos % 10 // 5 > 0:
            x_offset = 1
        else:
            x_offset = -1
        x_offset += (-5 + pos % 10) * self.pblen
        x += x_offset

        if pos//10 > 0:
            y_offset = 1
        else:
            y_offset = -1
        y_offset += (pos//10 - 1) * self.pblen
        y += y_offset

        button.setGeometry(x, y, self.pblen, self.pblen)
    
    def placePaletteSideButtons(self):
        x, y = self.getButtonCoords("trace")

        up, down, all, ind, opts, help = tuple(self.palette_side_buttons)

        x1 = x + 3 + 5 * self.pblen
        y1 = y - self.pblen
        up.setGeometry(x1, y1, self.pblen // 2, self.pblen // 2)

        x2 = x1 + self.pblen // 2 + 1
        all.setGeometry(x2, y1, self.pblen // 2, self.pblen // 2)

        y1 += self.pblen // 2
        down.setGeometry(x1, y1, self.pblen // 2, self.pblen // 2)

        ind.setGeometry(x2, y1, self.pblen // 2, self.pblen // 2)

        y1 += self.pblen // 2 + 1
        opts.setGeometry(x1, y1, self.pblen // 2, self.pblen // 2)

        y1 += self.pblen // 2
        help.setGeometry(x1, y1, self.pblen // 2, self.pblen // 2)
    
    def setPaletteButtonTip(self, b : PaletteButton, pos : int):
        """Set the tool tip for a palette button.
        
            Params:
                b (PaletteButton): the palette button to modify
                pos (int): the position of the button
        """
        kbd = ""
        if pos // 10 > 0:
            kbd += "Shift+"
        kbd += str((pos + 1) % 10)
        tooltip = f"{b.trace.name} ({kbd})"
        b.setToolTip(tooltip)

    def createPaletteButton(self, trace : Trace, pos : int):
        """Create a palette button on the dock.
        
            Params:
                trace (Trace): the trace to go on the button
                pos (int): the position of the button (assumes 20 buttons)
        """
        b = PaletteButton(self.mainwindow, manager=self)
        self.placePaletteButton(b, pos)
        b.setTrace(trace)
        b.setCheckable(True)
        self.setPaletteButtonTip(b, pos)
        b.clicked.connect(lambda : self.activatePaletteButton(pos))
        self.palette_buttons[pos] = b
        b.show()
    
    def createPaletteSideButtons(self):
        """Create the palette increment buttons."""
        b_up = MoveableButton(self.mainwindow, self, "trace")
        b_up.setText("+")
        f = b_up.font()
        f.setBold(True)
        b_up.setFont(f)
        b_up.clicked.connect(lambda : self.incrementPalette(True))
        b_up.setToolTip("+1 to {#}")
        b_up.show()

        b_down = MoveableButton(self.mainwindow, self, "trace")
        b_down.setText("-")
        b_down.setFont(f)
        b_down.clicked.connect(lambda : self.incrementPalette(False))
        b_down.setToolTip("-1 to {#}")
        b_down.show()

        b_all = MoveableButton(self.mainwindow, self, "trace")
        b_all.setText("⚭")
        b_all.setFont(f)
        b_all.setCheckable(True)
        b_all.clicked.connect(lambda : self.setPaletteIncMode(True))
        b_all.setToolTip("Increment all")
        b_all.show()

        b_ind = MoveableButton(self.mainwindow, self, "trace")
        b_ind.setText("⚬")
        b_ind.setFont(f)
        b_ind.setCheckable(True)
        b_ind.clicked.connect(lambda : self.setPaletteIncMode(False))
        b_ind.setToolTip("Increment active only")
        b_ind.show()

        b_opts = MoveableButton(self.mainwindow, self, "trace")
        b_opts.setText("☰")
        b_opts.clicked.connect(self.modifyAllPaletteButtons)
        b_opts.setToolTip("Modify all palettes")
        b_opts.show()

        b_help = MoveableButton(self.mainwindow, self, "trace")
        b_help.setText("?")
        b_help.setFont(f)
        b_help.clicked.connect(self.displayHelp)
        b_help.setToolTip("Help")
        b_help.show()

        self.palette_side_buttons = [b_up, b_down, b_all, b_ind, b_opts, b_help]
        self.placePaletteSideButtons()
        self.setPaletteIncMode(self.series.getOption("palette_inc_all"))
    
    def placeLabel(self):
        """Place the trace palette label."""
        x, y = self.getButtonCoords("trace")
        self.label.resize(self.label.sizeHint())
        x -= self.label.width() / 2
        if self.trace_y > 0.5:
            y -= self.pblen + self.label.height() + 5
        else:
            y += self.pblen + 5
        self.label.move(x, y)

    def updateLabel(self):
        """Update the name of the trace palette label."""
        g, i = tuple(self.series.palette_index)
        selected_trace = self.series.palette_traces[g][i]
        n = selected_trace.name
        for c in "{}<>":
            n = n.replace(c, "")
        self.label.setText(n)

        c = selected_trace.color
        self.label.setTextColor(c)
        black_outline = c[0] + 3*c[1] + c[2] > 400
        if black_outline:
            self.label.setOutlineColor((0,0,0))
        else:
            self.label.setOutlineColor((255,255,255))
        self.placeLabel()
    
    def activateModeButton(self, bname : str):
        """Executed when any mouse mode button is clicked: changes mouse mode.
        
            Params:
                bname (str): the name of the clicked button
        """
        if self.is_dragging:
            for name, button_info in self.mode_buttons.items():
                button, mode, pos = button_info
                if name == bname:
                    button.setChecked(not button.isChecked())
                    self.refreshModeIcons()
                    return

        for name, button_info in self.mode_buttons.items():
            button, mode, pos = button_info
            if name == bname:
                button.setChecked(True)
                self.mainwindow.changeMouseMode(mode)
                self.selected_mode = name
            else:
                button.setChecked(False)
        # re-tint so the active tool gets the accent bg + white icon and the
        # rest return to the resting theme color (prototype's active state).
        self.refreshModeIcons()
    
    def activatePaletteButton(self, bpos : int):
        """Executed when palette button is clicked: changes mouse trace.
        
            Params:
                bpos (int): the position of the palette button
        """
        if self.is_dragging:
            for i, button in enumerate(self.palette_buttons):
                if i == bpos:
                    button.setChecked(not button.isChecked())    
                    return
        
        for i, button in enumerate(self.palette_buttons):
            if i == bpos:
                if self.is_dragging:
                    button.setChecked(not button.isChecked())
                    return
                button.setChecked(True)
                self.mainwindow.changeTracingTrace(button.trace)
                self.series.palette_index[1] = i
                self.updateLabel()
            else:
                button.setChecked(False)
    
    def paletteButtonChanged(self, button : PaletteButton):
        """Executed when user changes palette trace: ensure that tracing pencil is updated.
        
            Params:
                button (PaletteButton): the button that was changed
        """
        for pos, b in enumerate(self.palette_buttons):
            if b == button:
                self.setPaletteButtonTip(b, pos)
                if b.isChecked():
                    self.mainwindow.changeTracingTrace(button.trace)
        self.updateLabel()
    
    def pasteAttributesToButton(self, trace : Trace, use_shape=False):
        """Paste the attributes of a trace to the current button.
        
            Params:
                trace (Trace): the trace to paste
        """
        bpos = self.series.palette_index[1]
        if use_shape:
            t = trace.copy()
            t.centerAtOrigin()
        else:
            name = trace.name
            color = trace.color
            radius = trace.getRadius()
            bttn = self.palette_buttons[bpos]
            t = bttn.trace.copy()
            t.name, t.color = name, color
            t.resize(radius)
        self.modifyPaletteButton(bpos, t)
    
    def modifyPaletteButton(self, bpos : int, trace : Trace = None):
        """Opens dialog to modify palette button.
        
            Params:
                bpos (int): the position of the palette button
        """
        b = self.palette_buttons[bpos]
        if not trace:
            b.openDialog()
        else:
            b.setTrace(trace)
        g = self.series.palette_index[0]
        self.series.palette_traces[g][bpos] = b.trace
        self.paletteButtonChanged(b)
    
    def modifyPalette(self, trace_list : list):
        """Modify all of the palette traces.
        
            Params:
                trace_list (list): the list of traces to set the palette buttons
        """
        for bpos, trace in enumerate(trace_list):
            self.modifyPaletteButton(bpos, trace)
        self.activatePaletteButton(self.series.palette_index[1])
    
    def resetPalette(self):
        """Reset the palette to the default traces."""
        self.modifyPalette(Series.getDefaultPaletteTraces())
    
    def placeIncrementButtons(self):
        """Place the increment buttons on the field"""
        x, y = self.getButtonCoords("inc")
        self.up_bttn.setGeometry(x, y, self.ibw, self.ibh)
        y = y + self.ibh + 15
        self.down_bttn.setGeometry(x, y, self.ibw, self.ibh)
    
    def createIncrementButtons(self):
        """Create the section increment buttons."""        
        self.up_bttn = MoveableButton(self.mainwindow, self, "inc")
        self.up_bttn.setText("▲")
        self.up_bttn.clicked.connect(self.incrementSection)
        self.up_bttn.setToolTip("Next section (PgUp)")

        self.down_bttn = MoveableButton(self.mainwindow, self, "inc")
        self.down_bttn.setText("▼")
        self.down_bttn.clicked.connect(lambda : self.incrementSection(down=True))
        self.down_bttn.setToolTip("Previous section (PgDown)")

        self.placeIncrementButtons()

        self.up_bttn.show()
        self.down_bttn.show()

        self.inc_buttons = [self.up_bttn, self.down_bttn]
    
    def incrementSection(self, down=False):
        """Increment the section."""
        if self.is_dragging:
            return
        self.mainwindow.incrementSection(down)
    
    def placeBCButtons(self):
        """Place the brightness/contrast buttons."""
        bcx, bcy = self.getButtonCoords("bc")
        for i, (bttn, slider) in enumerate(self.bc_widgets):
            x, y = bcx, bcy
            y += (self.bcsize + 20) * i
            bttn.setGeometry(x, y, self.bcsize*2, self.bcsize)
            slider.setGeometry(x + self.bcsize*2 + 5, y, self.bcsize*4, self.bcsize)
        self.updateBC()
    
    def updateBC(self):
        """Update the brightness/contrast on the slider to the section."""
        b = self.mainwindow.field.section.brightness
        c = self.mainwindow.field.section.contrast

        b_slider_value = round((abs(b)/100) ** (1/2) * 100) * (-1 if b < 0 else 1)
        c_slider_value = round((abs(c)/100) ** (1/2) * 100) * (-1 if c < 0 else 1)

        b_bttn, b_slider = self.bc_widgets[0]
        b_bttn.setText(str(b))
        b_slider.setValue(b_slider_value)

        c_bttn, c_slider = self.bc_widgets[1]
        c_bttn.setText(str(c))
        c_slider.setValue(c_slider_value)
    
    def createBCButtons(self):
        """Create the brightnes/contrast buttons."""
        # create the brightness/contrast button/slider
        self.bc_widgets = []
        for option in ("brightness", "contrast"):
            # create button
            b = MoveableButton(self.mainwindow, self, "bc")
            icon_fp = os.path.join(loc.img_dir, f"{option}_up.png")
            pixmap = QPixmap(icon_fp)
            b.setIcon(QIcon(pixmap))
            b.setIconSize(QSize(self.bcsize*2/3, self.bcsize*2/3))
            b.show()
            # create slider
            s = QSlider(Qt.Horizontal, self.mainwindow)
            s.setMinimum(-100)
            s.setMaximum(100)
            s.setStyleSheet("QSlider { background-color: transparent; }")
            s.show()
            self.bc_widgets.append((b, s))
        self.placeBCButtons()
        # connect functions
        self.bc_widgets[0][1].valueChanged.connect(
                self.setBrightness
        )
        self.bc_widgets[1][1].valueChanged.connect(
                self.setContrast
        )
    
    def setBrightness(self, b : int):
        """Set the brightness for the current section."""
        b = round((b/100) ** 2 * 100) * (-1 if b < 0 else 1)
        if b == self.mainwindow.field.section.brightness:
            return
        self.mainwindow.field.setBrightness(b)
        self.updateBC()
    
    def setContrast(self, c : int):
        """Set the contrast for the current section."""
        c = round((c/100) ** 2 * 100) * (-1 if c < 0 else 1)
        if c == self.mainwindow.field.section.contrast:
            return
        self.mainwindow.field.setContrast(c)
        self.updateBC()
    
    def getButtonCoords(self, group):
        """Get the coordinates for a button group.
        
            Params:
                group (str): the name of the button group.
        """
        x1, x2, y1, y2 = self.getBounds()[group]
        x = getattr(self, f"{group}_x")
        y = getattr(self, f"{group}_y")
        x = (x * (x2 - x1)) + x1
        y = (y * (y2 - y1)) + y1
        return x, y

    def moveButton(self, dx, dy, group):
        """Move a button group.
        
            Params:
                dx (int): the x-value movement for the button
                dy (int): the y-value movement for the button
                group (str): the name of the button group
        """
        x1, x2, y1, y2 = self.getBounds()[group]
        current_x, current_y = self.getButtonCoords(group)
        new_x = ((current_x + dx) - x1) / (x2 - x1)
        if new_x < 0: new_x = 0
        elif new_x > 1: new_x = 1
        new_y = ((current_y + dy) - y1) / (y2 - y1)
        if new_y < 0: new_y = 0
        elif new_y > 1: new_y = 1
        setattr(self, f"{group}_x", new_x)
        setattr(self, f"{group}_y", new_y)

        # special case: move selected traces if needed
        if group == "mode":
            self.mainwindow.field.update()

    def getBounds(self):
        """Get the bounds for the buttons."""

        field    = self.mainwindow.field
        
        fx1      = field.x()
        fx2      = fx1 + field.width()
        fy1      = field.y()
        fy2      = fy1 + field.height()

        mblen    = self.mblen
        buttons  = self.mode_buttons
        pblen    = self.pblen
        ibw      = self.ibw
        ibh      = self.ibh
        bcsize   = self.bcsize

        return {
            "mode": (fx1, fx2 - mblen, fy1, fy2 - (mblen + 10) * len(buttons) + 10),
            "trace": (fx1 + pblen*5, fx2 - pblen*6 - 3, fy1 + pblen, fy2 - pblen),
            "inc": (fx1, fx2 - ibw, fy1, fy2 - ibh*2 - 15),
            "bc": (fx1, fx2 - 6*bcsize - 5, fy1, fy2 - 2*bcsize - 20),
            "sb": (fx1, fx2 - 10, fy1, fy2 - 50)
        }

    def togglePalette(self):
        """Hide/Unhide the mouse palette."""
        self.palette_hidden = not self.palette_hidden
        for w in (self.palette_buttons + [self.label]):
            w.hide() if self.palette_hidden else w.show()
    
    def toggleIncrement(self):
        """Hide/Unhide the increment buttons."""
        self.inc_hidden = not self.inc_hidden
        for b in self.inc_buttons:
            b.hide() if self.inc_hidden else b.show()
    
    def toggleBC(self):
        """Hide/Unhide the brightness/contrast buttons."""
        self.bc_hidden = not self.bc_hidden
        for b, s in self.bc_widgets:
            b.hide() if self.bc_hidden else b.show()
            s.hide() if self.bc_hidden else s.show()
    
    def toggleSB(self):
        """Hide/Unhide the scale bar."""
        self.sb_hidden = not self.sb_hidden
        self.sb.hide() if self.sb_hidden else self.sb.show()
    
    def resetPos(self):
        """Reset the positions of the buttons."""
        # the tool card docks by handedness (placePaletteCard recomputes this);
        # kept here so mode_x reflects the docked side immediately.
        self.mode_x = 0.01 if self.series.getOption("left_handed") else 0.99
        self.mode_y = 0.01

        self.trace_x = 0.51
        self.trace_y = 0.99

        self.inc_x = 0.99
        self.inc_y = 0.99

        self.bc_x = 0.99
        self.bc_y = 0.8

        self.resize()
    
    def setPaletteIncMode(self, all : bool):
        """Set the mode for incrementing the palette buttons.
        
            Params:
                all (bool): True if all palette buttons should be incremented at once
        """
        b_all, b_inc = self.palette_side_buttons[2:4]
        self.series.setOption("palette_inc_all", all)
        if all:
            b_all.setChecked(True)
            b_inc.setChecked(False)
        else:
            b_inc.setChecked(True)
            b_all.setChecked(False)

    def incrementPalette(self, up):
        """Increment the palette.
            
            Params:
                up (bool): True if increment higher, False if increment lower
        """
        if self.is_dragging:
            return
        
        def incStr(s):
            min = 0
            max = 10**len(s) - 1
            n = int(s) + (1 if up else -1)
            if n < min: n = max
            elif n > max: n = min
            return str(n).rjust(len(s), "0")
        
        def replace(match):
            return "{" + incStr(match.group(1)) + "}"
        
        pattern = r"\{(\d+)\}"

        if self.series.getOption("palette_inc_all"):
            buttons = enumerate(self.palette_buttons)
        else:
            i = self.series.palette_index[1]
            buttons = [(i, self.palette_buttons[i])]
        for bpos, w in buttons:
            n = re.sub(pattern, replace, w.trace.name)
            new_trace = w.trace.copy()
            new_trace.name = n
            self.modifyPaletteButton(bpos, new_trace)
    
    def incrementButton(self, bpos : int = None, up=True):
        """Increment a specific button.
        
            Params:
                bpos (int): the position of the button to increment
                up (bool): True if increment the number higher
        """
        if self.is_dragging:
            return
        
        if not bpos:
            bpos = self.series.palette_index[1]


        pattern = r"\<(\d+)\>"
        name = self.palette_buttons[bpos].trace.name
        if not re.search(pattern, name):
            return
        
        def incStr(s):
            min = 0
            max = 10**len(s) - 1
            n = int(s) + (1 if up else -1)
            if n < min: n = max
            elif n > max: n = min
            return str(n).rjust(len(s), "0")

        def replace(match):
            return "<" + incStr(match.group(1)) + ">"
        
        n = re.sub(pattern, replace, name)
        new_trace = self.palette_buttons[bpos].trace.copy()
        new_trace.name = n
        self.modifyPaletteButton(bpos, new_trace)
        
    def modifyAllPaletteButtons(self):
        """Modify all the palette buttons through a single dialog."""
        if self.is_dragging:
            return
               
        # run the widget
        response, confirmed = TracePaletteDialog(self.mainwindow, self.series).exec()
        if not confirmed:
            return
        
        self.modifyPalette(self.series.palette_traces[self.series.palette_index[0]])
        self.activatePaletteButton(self.series.palette_index[1])
    
    def setFlag(self, name : str = None, color : tuple = None, font_size : int = None, display_flags : str = None):
        """Set the default flag in the palette."""
        regenerate_view = False
        if name is not None:
            self.series.setOption("flag_name", name)
        
        if color is None:
            color = self.series.getOption("flag_color")
        else:
            self.series.setOption("flag_color", color)
        
        if font_size is None:
            font_size = self.series.getOption("flag_size")
        elif font_size != self.series.getOption("flag_size"):
            self.series.setOption("flag_size", font_size)
            regenerate_view = True
        
        if display_flags is not None and display_flags != self.series.getOption("show_flags"):
            self.series.setOption("show_flags", display_flags)
            self.mainwindow.field.section.selected_flags = []
            regenerate_view = True
        
        if regenerate_view:
            self.mainwindow.field.generateView(generate_image=False)
        
        button = self.mode_buttons["Flag"][0]
        # glyph tool (no SVG): size the ⚑ like the 20px line icons so it sits
        # cleanly beside the corner keycap
        button.setFont(QFont("Courier New", 15, QFont.Bold))
        button.setText("⚑")
        s = f"({','.join(map(str, color))})"
        # button.setStyleSheet(f"color:rgb{s}")
    
    def modifyFlag(self):
        """Modify the default flag."""
        show_flags = self.series.getOption("show_flags")
        structure = [
            ["Default name:", ("text", self.series.getOption("flag_name"))],
            ["Default color:", ("color", self.series.getOption("flag_color"))],
            ["Size of all flags: ", ("int", self.series.getOption("flag_size"), tuple(range(1, 100)))],
            ["Display"],
            [("radio",
              ("All flags", show_flags == "all"),
              ("Only unresolved flags", show_flags == "unresolved"),
              ("No flags", show_flags == "none")
            )]
        ]
        response, confirmed = QuickDialog.get(self.mainwindow, structure, "Flag")
        if not confirmed:
            return
        
        if response[3][0][1]: show_flags = "all"
        elif response[3][2][1]: show_flags = "none"
        else: show_flags = "unresolved"
        
        self.setFlag(response[0], response[1], response[2], show_flags)
    
    def displayHelp(self):
        """Display the help associated with the trace palette."""
        if self.help_widget and self.help_widget.isVisible():
            self.help_widget.close()
        self.help_widget = TextWidget(
            self.mainwindow, 
            palette_help, 
            "Palette Help", 
            html=True
        )
    
    def getScale(self):
        """Get the scale from the mainwindow."""
        real_width = self.mainwindow.series.window[2]
        pix_width = self.mainwindow.field.pixmap_dim[0]
        return real_width / pix_width
    
    def setScale(self):
        if "sb" in dir(self):
            self.sb.setScale(self.getScale())
    
    def createSB(self):
        """Create the scale bar."""
        sb_w = int(self.series.getOption("scale_bar_width") / 100 * self.mainwindow.field.width())
        self.sb = ScaleBar(self.mainwindow, self, sb_w, 50, 1)
        self.setScale()
        self.placeSB()
        self.sb.show()
    
    def placeSB(self):
        """Place the scale bar."""
        x, y = self.getButtonCoords("sb")
        self.sb.move(x, y)
        
    def resize(self):
        """Move the buttons to fit the main window."""
        self.placePaletteCard()
        for i, pb in enumerate(self.palette_buttons):
            self.placePaletteButton(pb, i)
        self.placePaletteSideButtons()
        self.placeLabel()
        self.placeIncrementButtons()
        self.placeBCButtons()
        self.placeSB()
    
    def reset(self):
        """Reset the mouse palette when opening a new series."""
        self.close()
        self.__init__(self.mainwindow)

    def close(self):
        """Close all buttons"""
        # closing the card closes its child mode buttons, keycaps, and dividers
        self.tool_card.close()
        for pb in self.palette_buttons:
            pb.close()
        for b in self.palette_side_buttons:
            b.close()
        self.label.close()
        for b in self.inc_buttons:
            b.close()
        for b, s in self.bc_widgets:
            b.close()
            s.close()
        self.sb.close()
        
