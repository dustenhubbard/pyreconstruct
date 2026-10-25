import os
import re
import math

from PySide6.QtWidgets import QWidget, QSlider
from PySide6.QtGui import QIcon, QPixmap, QFont
from PySide6.QtCore import QSize, Qt, QSettings
from PyReconstruct.modules.constants.settings_domain import domain_for

# Palette-visibility preferences are global (a UI choice, not per-series) and
# persist across launches. Map each in-memory flag to its QSettings key.
PALETTE_VIS_KEYS = {
    "palette_hidden": "palette/trace_hidden",
    "inc_hidden":     "palette/inc_hidden",
    "bc_hidden":      "palette/bc_hidden",
    "sb_hidden":      "palette/sb_hidden",
}


def _visibility_settings():
    """The store the visibility flags live in (shared between the two apps)."""
    return QSettings(*domain_for(*PALETTE_VIS_KEYS.values()))


def load_palette_visibility(settings : QSettings) -> dict:
    """Read the persisted palette-visibility flags (default: all shown)."""
    return {
        attr: settings.value(key, False, type=bool)
        for attr, key in PALETTE_VIS_KEYS.items()
    }


def save_palette_visibility(settings : QSettings, state : dict) -> None:
    """Persist the palette-visibility flags."""
    for attr, key in PALETTE_VIS_KEYS.items():
        settings.setValue(key, bool(state[attr]))


# Each moveable palette group stores its position as a fraction (0..1) of the
# field bounds. Like the visibility flags, positions are a global UI choice and
# persist across launches -- one ``palette/<group>_<axis>`` key per group.
PALETTE_POS_GROUPS = ("mode", "trace", "inc", "bc", "sb")

# Where each group sits until the user drags it (x, y fractions).
DEFAULT_POSITIONS = {
    "mode":  (0.99, 0.01),
    "trace": (0.51, 0.99),
    "inc":   (0.99, 0.99),
    "bc":    (0.99, 0.8),
    "sb":    (0.01, 0.99),
}


def set_default_positions(palette) -> None:
    """Put every group of `palette` at its default spot."""
    for group, (x, y) in DEFAULT_POSITIONS.items():
        setattr(palette, f"{group}_x", x)
        setattr(palette, f"{group}_y", y)


def _palette_pos_key(group : str, axis : str) -> str:
    return f"palette/{group}_{axis}"


PALETTE_POS_KEYS = tuple(
    _palette_pos_key(group, axis)
    for group in PALETTE_POS_GROUPS for axis in ("x", "y")
)


def _position_settings():
    """The store the palette positions live in (shared between the two apps)."""
    return QSettings(*domain_for(*PALETTE_POS_KEYS))


def load_palette_positions(settings : QSettings) -> dict:
    """Read persisted palette positions as ``{"<group>_<axis>": float}``.

    Absent (or unreadable) groups/axes are omitted so the caller keeps its code
    defaults rather than being forced to a stored value.
    """
    positions = {}
    for group in PALETTE_POS_GROUPS:
        for axis in ("x", "y"):
            raw = settings.value(_palette_pos_key(group, axis), None)
            if raw is None:
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(val):
                continue  # a corrupt nan/inf would break placement on the next resize
            positions[f"{group}_{axis}"] = val
    return positions


def save_palette_positions(settings : QSettings, positions : dict) -> None:
    """Persist palette positions (coerced to float) under ``palette/<group>_<axis>``."""
    for group in PALETTE_POS_GROUPS:
        for axis in ("x", "y"):
            name = f"{group}_{axis}"
            if name in positions:
                settings.setValue(_palette_pos_key(group, axis), float(positions[name]))


def clear_palette_positions(settings : QSettings) -> None:
    """Forget any persisted palette positions, so a reset stays the default."""
    for group in PALETTE_POS_GROUPS:
        for axis in ("x", "y"):
            settings.remove(_palette_pos_key(group, axis))


from .buttons import PaletteButton, ModeButton, MoveableButton
from .scale_bar import ScaleBar, drawableLengths, formatLength
from .outlined_label import OutlinedLabel
from .help import palette_help
from .default_rows import shownButtonCount
from . import line_icons

from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.constants.roi_mode import roi_mode_enabled
from PyReconstruct.modules.datatypes import Series, Trace
from PyReconstruct.modules.datatypes.trace import copyObjDefaults
from PyReconstruct.modules.datatypes.default_settings import pinnedLengthFor
from PyReconstruct.modules.constants import (
    locations as loc
)
from PyReconstruct.modules.gui.dialog import TracePaletteDialog, QuickDialog
from PyReconstruct.modules.gui.dialog.scale_bar_settings import ScaleBarSettingsDialog
from PyReconstruct.modules.gui.popup import TextWidget
from PyReconstruct.modules.gui.utils import notify
from PyReconstruct.modules.gui.utils.fonts import uiFamily, uiFont


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
        
        self.mblen = 40  # mode button size
        self.pblen = 40  # palette button size
        self.ibw = 90  # inc button width
        self.ibh = 35  # inc button height
        self.bcsize = 30  # brightness/contrast button size

        self.is_dragging = False

        # Moveable palette-group positions (fractions 0..1 of the field bounds).
        # Set every default first, then override with any persisted positions, so
        # each group renders in its saved spot. Saved on drag end (MoveableButton)
        # and cleared by resetPos().
        set_default_positions(self)
        self.loadPositionState()

        # create mode buttons; macOS Dev builds draw them as line icons
        self.line_icons = line_icons.wanted()
        self.mode_buttons = {}
        self.createModeButton("Pointer", 0)
        self.createModeButton("Pan/Zoom", 1)
        self.createModeButton("Knife", 2)
        self.createModeButton("Scissors", 3)
        self.createModeButton("Closed Trace", 4)
        self.createModeButton("Open Trace", 5)
        self.createModeButton("Stamp", 6)
        self.createModeButton("Grid", 7)
        self.createModeButton("Flag", 8)
        self.createModeButton("Host", 9)
        self.createModeButton("Ztool", 10)
        # held: shown only with PYRECON_ROI_MODE=1 (constants/roi_mode.py)
        if roi_mode_enabled():
            self.createModeButton("ROI mode", 11)
        # Placed only now, once every button exists, the z-trace tool's
        # included. The column's bounds shrink by one button height per
        # button already made (getBounds), so placing
        # each one as it was created gave every button a different origin:
        # with the column dragged down from its default the buttons piled up
        # at half spacing until the next resize, a squished tool bar at
        # startup.
        self.placeModeButtons()
        if self.line_icons:
            self.tintModeIcons()
            line_icons.Retinter(self.mode_buttons["Pointer"][0], self.tintModeIcons)

        # create palette buttons; a Dev build leaves off trailing rows that
        # copy the standard buttons (default_rows), and the series keeps them
        traces = self.shownTraces(self.series.palette_traces[self.series.palette_index[0]])
        self.palette_buttons = [None] * len(traces)
        for i, trace in enumerate(traces):  # create all the palette buttons
            self.createPaletteButton(trace, i)
        self.palette_buttons[self.selectedPos()].setChecked(True)

        # create palette increments
        self.createPaletteSideButtons()
        
        self.selected_mode = "pointer"

        # create label
        self.label = OutlinedLabel(self.mainwindow)
        font = self.label.font()
        font.setFamily(uiFamily())
        font.setWeight(uiFont().weight())
        font.setPointSize(16)
        self.label.setFont(font)
        self.updateLabel()
        self.label.show()

        # create increment buttons
        self.createIncrementButtons()

        # create brightness/contrast buttons
        self.createBCButtons()

        # restore persisted palette-visibility preferences (global, across launches)
        self.loadVisibilityState()

        self.help_widget = None

        # create scale palette
        self.createSB()

        # apply the restored visibility now that every palette widget exists
        self.applyVisibilityState()
        self.installHideMenus()
    
    def placeModeButtons(self):
        """Place every mode button; the bounds depend on the full count."""
        for button, mode, pos in self.mode_buttons.values():
            self.placeModeButton(button, pos)

    def placeModeButton(self, button, pos : int):
        """Place the mode button in the main window.
        
            Params:
                button (ModeButton): the button to place
                pos (int): the position of the button
        """
        x, y = self.getButtonCoords("mode")
        y += (10 + self.mblen) * pos
        button.setGeometry(x, y, self.mblen, self.mblen)
    
    def createModeButton(self, name : str, pos : int):
        """Creates a new mouse mode button.
        
            Params:
                name (str): the name of the button (and PNG file)
                pos (int): the position of the button
        """
        b = ModeButton(self.mainwindow, self)
        mouse_mode = pos

        # filter name to get filename
        stripped_name = name
        characters_to_remove = (" ", "/")
        for c in characters_to_remove:
            stripped_name = stripped_name.replace(c, "")
        stripped_name = stripped_name.lower()
        # open the icon file
        icon_fp = os.path.join(loc.img_dir, stripped_name + ".png")
        pixmap = QPixmap(icon_fp)

        # format the button
        b.setIcon(QIcon(pixmap))
        b.setIconSize(QSize(self.mblen, self.mblen))
        # b.setText(name)
        b.setToolTip(f"{name}")

        b.setCheckable(True)
        if pos == 0:  # make the first button selected by default
            b.setChecked(True)
        b.clicked.connect(lambda : self.activateModeButton(name))
        # dictionary -- name : (button object, mouse mode, position)
        self.mode_buttons[name] = (b, mouse_mode, pos)

        # manually enter dialog function for pointer and grid
        if name == "Pointer":
            b.setRightClickEvent(self.mainwindow.modifyPointer)
        elif name == "Closed Trace" or name == "Open Trace":
            b.setRightClickEvent(self.mainwindow.changeTraceMode)
        elif name == "Grid":
            b.setRightClickEvent(self.mainwindow.modifyGrid)
        elif name == "Flag":
            b.setRightClickEvent(self.modifyFlag)
            # manually set the flag text and color
            self.setFlag()
        elif name == "Knife":
            b.setRightClickEvent(self.mainwindow.modifyKnife)
        elif name == "Host":
            f = b.font()
            f.setPointSize(25)
            b.setFont(f)
            b.setText("⎋")
        elif name == "ROI mode":
            # right-click sets the box's width and height
            b.setRightClickEvent(lambda: self.mainwindow.field.setRoiBoxSize())
            f = b.font()
            f.setBold(True)
            b.setFont(f)
            b.setText("ROI")

        b.show()
    
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

    @staticmethod
    def shownTraces(traces : list) -> list:
        """The traces that get a button: all of them, less a Dev build's
        trailing copies of the standard rows."""
        if build_flavor.is_dev_build():
            return traces[:shownButtonCount(traces)]
        return traces

    def selectedPos(self) -> int:
        """The button shown as selected: the series' current button, or the
        last button on show when a Dev build leaves the current one off.
        palette_index is not changed, so a save writes it as it was."""
        return min(self.series.palette_index[1], len(self.palette_buttons) - 1)

    def selectedTrace(self) -> Trace:
        """The trace of the button shown as selected."""
        g = self.series.palette_index[0]
        return self.series.palette_traces[g][self.selectedPos()]

    def updateLabel(self):
        """Update the name of the trace palette label."""
        selected_trace = self.selectedTrace()
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
                    return

        for name, button_info in self.mode_buttons.items():
            button, mode, pos = button_info
            if name == bname:
                button.setChecked(True)
                self.mainwindow.changeMouseMode(mode)
                self.selected_mode = name
            else:
                button.setChecked(False)      
    
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
        bpos = self.selectedPos()
        if use_shape:
            t = trace.copy()
            t.centerAtOrigin()
            # a section trace carries no object defaults; the button keeps its
            # own groups and custom columns (fork #419)
            t.obj_defaults = copyObjDefaults(self.palette_buttons[bpos].trace.obj_defaults)
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
        # check and draw with the shown button without a click: a click
        # writes palette_index, which a Dev build may have moved off a
        # hidden button (selectedPos)
        pos = self.selectedPos()
        for i, button in enumerate(self.palette_buttons):
            button.setChecked(i == pos)
        self.mainwindow.changeTracingTrace(self.selectedTrace())
        self.updateLabel()
    
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

        # The sliders only show the section's values here. Unblocked, a moved
        # slider fires setBrightness/setContrast, which square and round its
        # position and write that back: 99 shows as 99 and comes back as 98.
        b_bttn, b_slider = self.bc_widgets[0]
        b_bttn.setText(str(b))
        b_blocked = b_slider.blockSignals(True)
        b_slider.setValue(b_slider_value)
        b_slider.blockSignals(b_blocked)

        c_bttn, c_slider = self.bc_widgets[1]
        c_bttn.setText(str(c))
        c_blocked = c_slider.blockSignals(True)
        c_slider.setValue(c_slider_value)
        c_slider.blockSignals(c_blocked)
    
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
        if group in ("inc", "bc") and self.atDefaultPosition(group):
            x = self.clearOfTools(group, x, y)
        return x, y

    def atDefaultPosition(self, group):
        """True if the user has not dragged the group from its default spot."""
        x = getattr(self, f"{group}_x")
        y = getattr(self, f"{group}_y")
        return (x, y) == DEFAULT_POSITIONS[group]

    def clearOfTools(self, group, x, y):
        """The x for a group at (x, y) that keeps it clear of the tool column.

        The section buttons and the sliders default to the field's right edge,
        under the tool column. In a short window the column reaches down to
        them and they cover its last buttons, so a group that would touch
        the column moves left of it. Only a group at its default spot moves:
        one the user dragged stays where it was put.
        """
        w, h = {
            "inc": (self.ibw, self.ibh*2 + 15),
            "bc": (self.bcsize*6 + 5, self.bcsize*2 + 20),
        }[group]
        gap = 10
        tx, ty = self.getButtonCoords("mode")
        th = (self.mblen + 10) * len(self.mode_buttons) - 10
        touches = (
            x < tx + self.mblen + gap and tx < x + w + gap and
            y < ty + th + gap and ty < y + h + gap
        )
        if not touches:
            return x
        return max(self.mainwindow.field.x(), tx - gap - w)

    def moveButton(self, dx, dy, group):
        """Move a button group.
        
            Params:
                dx (int): the x-value movement for the button
                dy (int): the y-value movement for the button
                group (str): the name of the button group
        """
        x1, x2, y1, y2 = self.getBounds()[group]
        current_x, current_y = self.getButtonCoords(group)
        if group == "sb" and self.sb.x() < int(current_x):
            # the bar is drawn left of its saved spot (see placeSB), so a drag
            # starts from the drawn position; from the saved spot the bar would
            # not move until that spot was on screen again
            current_x = self.sb.x()
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
            # the bar's height follows its thickness option
            "sb": (fx1, fx2 - 10, fy1, fy2 - (self.sb.height() if "sb" in dir(self) else 50))
        }

    def loadVisibilityState(self):
        """Restore palette-visibility flags from the persisted preferences."""
        for attr, value in load_palette_visibility(_visibility_settings()).items():
            setattr(self, attr, value)

    def saveVisibilityState(self):
        """Persist the current palette-visibility flags so they survive a restart."""
        state = {attr: getattr(self, attr) for attr in PALETTE_VIS_KEYS}
        save_palette_visibility(_visibility_settings(), state)
        # every toggle road ends here, so this is where the View menu's
        # checkboxes learn about a change they did not make
        self.notifyVisibilityChanged()

    def loadPositionState(self):
        """Restore persisted palette positions over the in-memory defaults."""
        saved = load_palette_positions(_position_settings())
        for attr, value in saved.items():
            setattr(self, attr, value)

    def savePositionState(self):
        """Persist the current palette positions so they survive a restart."""
        positions = {
            f"{group}_{axis}": getattr(self, f"{group}_{axis}")
            for group in PALETTE_POS_GROUPS for axis in ("x", "y")
        }
        save_palette_positions(_position_settings(), positions)

    # Right-click to hide, group by group: the View
    # menu keeps every toggle, and this adds the direct road from the widget
    # itself. One installer per group, run wherever the widgets are (re)built,
    # so a rebuilt slider is still armed.
    HIDE_LABELS = {
        "palette": "Hide the trace palette",
        "inc": "Hide the section increment buttons",
        "bc": "Hide the brightness/contrast sliders",
        "sb": "Hide the scale bar",
    }

    def installHideMenus(self):
        """Give every palette group a right-click "Hide ..." menu.

        The trace-palette BUTTONS are deliberately not armed: right-click on
        a button already opens its attributes dialog (rc_act in buttons.py,
        and the palette help documents it), and arming both on one widget
        made the two fight -- on macOS the hide menu's grab swallowed the
        release so the documented editor stopped opening, on Windows both
        fired from a single click (found 2026-08-28). The palette's LABEL
        carries the hide menu for that group instead.
        """
        groups = (
            ("palette", [self.label], self.togglePalette),
            ("inc", list(self.inc_buttons), self.toggleIncrement),
            ("bc", [w for pair in self.bc_widgets for w in pair], self.toggleBC),
            ("sb", [self.sb], self.toggleSB),
        )
        # the scale bar's own items go in its one menu; a second menu on the
        # same widget would open two menus on one click
        extras = {"sb": self.sbMenuActions}
        for key, widgets, toggle in groups:
            for widget in widgets:
                if widget is None:
                    continue
                self._installHideMenu(
                    widget, self.HIDE_LABELS[key], toggle, extras.get(key)
                )

    def _installHideMenu(self, widget, label, toggle, extras=None):
        """Arm one widget. Idempotent: the palettes rebuild, and a second
        connect on the same widget would open two menus on one click.

        `extras`, if given, returns (label, slot) pairs to list above the
        hide item. It is called each time the menu opens, so an item can
        depend on the widget's state.
        """
        from PySide6.QtCore import Qt

        if widget.property("pyrecon_hide_menu"):
            return
        widget.setProperty("pyrecon_hide_menu", True)
        widget.setContextMenuPolicy(Qt.CustomContextMenu)

        def show(pos, widget=widget, label=label, toggle=toggle, extras=extras):
            from PySide6.QtWidgets import QMenu

            menu = QMenu(widget)
            menu.aboutToHide.connect(menu.deleteLater)
            if extras is not None:
                for extra_label, slot in extras():
                    menu.addAction(extra_label, slot)
                menu.addSeparator()
            menu.addAction(label, toggle)
            self._hide_menu = menu   # reachable for the tests
            menu.popup(widget.mapToGlobal(pos))

        widget.customContextMenuRequested.connect(show)

    def notifyVisibilityChanged(self):
        """Tell the main window to re-read the View checkboxes.

        Every visibility change lands here through saveVisibilityState, so
        the menu stays in step with a right-click hide as well as its own
        toggles.
        """
        sync = getattr(self.mainwindow, "syncPaletteToggles", None)
        if sync is not None:
            sync()

    def applyVisibilityState(self):
        """Show/hide palette widgets to match the current visibility flags."""
        for w in (self.palette_buttons + [self.label]):
            w.hide() if self.palette_hidden else w.show()
        for b in self.inc_buttons:
            b.hide() if self.inc_hidden else b.show()
        for b, slider in self.bc_widgets:
            b.hide() if self.bc_hidden else b.show()
            slider.hide() if self.bc_hidden else slider.show()
        self.sb.hide() if self.sb_hidden else self.sb.show()

    def togglePalette(self):
        """Hide/Unhide the mouse palette."""
        self.palette_hidden = not self.palette_hidden
        for w in (self.palette_buttons + [self.label]):
            w.hide() if self.palette_hidden else w.show()
        self.saveVisibilityState()

    def toggleIncrement(self):
        """Hide/Unhide the increment buttons."""
        self.inc_hidden = not self.inc_hidden
        for b in self.inc_buttons:
            b.hide() if self.inc_hidden else b.show()
        self.saveVisibilityState()

    def toggleBC(self):
        """Hide/Unhide the brightness/contrast buttons."""
        self.bc_hidden = not self.bc_hidden
        for b, s in self.bc_widgets:
            b.hide() if self.bc_hidden else b.show()
            s.hide() if self.bc_hidden else s.show()
        self.saveVisibilityState()

    def toggleSB(self):
        """Hide/Unhide the scale bar."""
        self.sb_hidden = not self.sb_hidden
        self.sb.hide() if self.sb_hidden else self.sb.show()
        self.saveVisibilityState()
    
    def resetPos(self):
        """Reset every palette group to its default spot and forget saved positions."""
        set_default_positions(self)
        clear_palette_positions(_position_settings())
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
            i = self.selectedPos()
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
            bpos = self.selectedPos()


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
        
        # the dialog can make a palette of another length current, by
        # switching to its tab or by removing the current one
        self.series.clampPaletteIndex()
        g = self.series.palette_index[0]
        traces = self.shownTraces(self.series.palette_traces[g])
        if len(traces) == len(self.palette_buttons):
            self.modifyPalette(traces)
        else:
            # the buttons belong to the old palette: build new ones, and draw
            # with the new current button, which reset() checks but not clicks
            self.reset()
            self.mainwindow.changeTracingTrace(self.selectedTrace())
    
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
        button.setFont(QFont("Courier New", 25, QFont.Bold))
        button.setText("⚑")
        s = f"({','.join(map(str, color))})"
        # button.setStyleSheet(f"color:rgb{s}")
        if self.line_icons:
            self.tintModeIcons()
    
    def tintModeIcons(self):
        """Draw the mode buttons' line icons in the current colors (macOS Dev)."""
        line_icons.tint(self.mode_buttons, self.series.getOption("flag_color"))
    
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
            self.placeSB()   # a pinned bar's width follows the zoom

    def followZoom(self, zoom_factor):
        """Show the scale of a zoom that is still in progress.

        A pinch, Ctrl+scroll or right-drag zoom stretches a copy of the field
        and only redraws it on release, so the series window, and with it
        getScale, still has the scale from before the zoom. The stretched
        view is zoom_factor times larger, so it shows getScale() / zoom_factor
        units per pixel. Only the bar repaints; nothing here touches the field.
        """
        if "sb" not in dir(self) or not zoom_factor:
            return
        scale = self.getScale() / zoom_factor
        if scale != self.sb.scale:
            self.sb.setScale(scale)
            self.placeSB()
    
    def getPinnedLength(self):
        """The real-world length the scale bar is pinned to, or None.

        None means the historic screen-fraction sizing, which is what an
        installation that has never touched the new control gets: the mode
        option ships as "screen_fraction", so a stored scale_bar_width goes on
        meaning exactly what it meant before.
        """
        if self.series.getOption("scale_bar_mode") != "micron_pinned":
            return None
        return pinnedLengthFor(
            "micron_pinned", self.series.getOption("scale_bar_length_um"))

    def sbWidth(self, percent=None):
        """The widest the scale bar may be drawn, in pixels.

        Both modes are limited to the "Scale bar size" share of the field. The
        screen-fraction bar fills between 40 and 100 percent of it, and a pinned
        bar steps a decade before it would outgrow it.
        """
        if percent is None:
            percent = self.series.getOption("scale_bar_width")
        return int(percent / 100 * self.mainwindow.field.width())

    def createSB(self):
        """Create the scale bar."""
        sb_w = self.sbWidth()
        self.sb = ScaleBar(
            self.mainwindow, self, sb_w,
            self.series.getOption("scale_bar_thickness"), 1,
            micron_length=self.getPinnedLength(),
            max_pixel_length=sb_w,
        )
        self.setScale()
        self.placeSB()
        self.sb.show()

    def previewScaleBarWidth(self, percent):
        """Show the bar at `percent` of the field width without storing it.

        Series > Options drives this from its slider as the handle moves, so
        the size can be judged before OK without closing and reopening the
        window. Nothing is written: OK stores the option and rebuilds the
        palette; Cancel calls restoreScaleBar. A bar pinned to a micron
        length takes the width as the most it may grow to, exactly as the
        stored option does.
        """
        sb_w = self.sbWidth(percent)
        if sb_w > 0:
            self.sb.setMaxPixelLength(sb_w)
            self.placeSB()

    def sbMenuActions(self):
        """The scale bar's own right-click items, above "Hide the scale bar".

        Settings first: it is the one place every scale bar option can be
        changed from the bar itself. The length items are for a figure and
        are not stored.
        """
        actions = [
            ("Scale bar settings...", self.openSBSettings),
            ("Set the scale bar length...", self.setSBLength),
        ]
        if self.sb.override_length:
            actions.append(("Size the scale bar automatically", self.clearSBLength))
        return actions

    def openSBSettings(self):
        """Every scale bar option in one dialog, previewed on the bar as it
        changes; OK stores them, Cancel puts the bar back."""
        ScaleBarSettingsDialog(self.mainwindow, self.series, self).exec()

    def sbLengthRange(self):
        """The shortest and longest lengths, in µm, you can type for a bar
        drawn exactly at the current zoom, with the field width as its room.
        The first is larger when there is none (see drawableLengths)."""
        return drawableLengths(self.sb.scale, self.mainwindow.field.width())

    def setSBLength(self):
        """Ask for a length and draw the bar at it until told otherwise.

        For figures. The length set here is not stored anywhere, so the
        stored mode and size are untouched and a new series, or picking
        "Size the scale bar automatically", brings the automatic bar back.
        """
        lo, hi = self.sbLengthRange()
        if lo > hi:
            notify(
                "At this zoom and window width there is no scale bar length "
                "that can be drawn. Zoom in or out, or widen the window, then "
                "try again."
            )
            return
        length = self.sb.currentLength()[0]
        while True:
            structure = [
                ["Length (µm):", ("float", round(length, 10))],
                [f"At this zoom the bar can be {formatLength(lo)} to "
                 f"{formatLength(hi)} µm long."],
                ["It keeps this length until you choose"],
                ["\"Size the scale bar automatically\" or open another series."],
            ]
            response, confirmed = QuickDialog.get(
                self.mainwindow, structure, "Scale Bar Length"
            )
            if not confirmed:
                return
            length = response[0]
            if length is not None and lo <= length <= hi:
                break
            notify(
                f"Please enter a length from {formatLength(lo)} to "
                f"{formatLength(hi)} µm, or zoom first to draw a "
                "longer or shorter bar."
            )
            if length is None or not length > 0:
                length = self.sb.currentLength()[0]
        self.sb.setOverride(float(length), self.mainwindow.field.width())
        self.placeSB()

    def clearSBLength(self):
        """Go back to the bar the stored mode and size draw."""
        self.sb.setOverride(None)
        self.placeSB()

    def previewScaleBarThickness(self, thickness):
        """Show the bar at `thickness` pixels without storing it; the
        thickness slider's counterpart of previewScaleBarWidth."""
        self.sb.setThickness(thickness)
        self.placeSB()

    def previewScaleBar(self, settings):
        """Show the bar as `settings` would draw it, without storing anything.

        `settings` maps option names to values, as the scale bar settings
        page reads them (see scale_bar_settings.readScaleBarSettings); a key
        left out keeps what the bar shows now. The bar is changed in place, so
        its position, visibility, hide menu and any length set for a figure
        are kept. Cancel calls restoreScaleBar.
        """
        sb = self.sb
        if "show_scale_bar_text" in settings or "show_scale_bar_ticks" in settings:
            sb.previewDisplay(
                settings.get("show_scale_bar_text",
                             sb.displayOption("show_scale_bar_text")),
                settings.get("show_scale_bar_ticks",
                             sb.displayOption("show_scale_bar_ticks")),
            )
        if "scale_bar_thickness" in settings:
            sb.setThickness(settings["scale_bar_thickness"])
        if "scale_bar_width" in settings:
            sb_w = self.sbWidth(settings["scale_bar_width"])
            if sb_w > 0:
                sb.setMaxPixelLength(sb_w)
        if "scale_bar_mode" in settings:
            sb.setPinnedLength(pinnedLengthFor(
                settings["scale_bar_mode"],
                settings.get("scale_bar_length_um", sb.micron_length),
            ))
        self.placeSB()

    def restoreScaleBar(self):
        """Show the stored options again, in place, preserving visibility and
        hide controls. After a preview's Cancel, or after its OK stored them."""
        self.sb.previewDisplay(None, None)
        self.sb.setThickness(self.series.getOption("scale_bar_thickness"))
        self.previewScaleBarWidth(self.series.getOption("scale_bar_width"))
        self.sb.setPinnedLength(self.getPinnedLength())
        self.placeSB()

    def hoverObstacles(self):
        """What the field's hover box should not cover, in main window
        coordinates: the scale bar's rect (None while hidden), then the rects
        of the other palette widgets on show."""
        def shown(widget):
            return widget is not None and not widget.isHidden()

        sb = self.sb.geometry() if shown(self.sb) else None
        others = [button for button, _mode, _ in self.mode_buttons.values()]
        others += list(self.palette_buttons) + list(self.palette_side_buttons)
        others += [self.label] + list(self.inc_buttons)
        others += [w for pair in self.bc_widgets for w in pair]
        return sb, [w.geometry() for w in others if shown(w)]

    def placeSB(self):
        """Place the scale bar.

        The bar can be wider than the room to the right of where it was
        left. This happens with a long length you typed, a pinned bar the zoom
        has grown, or a size near 100 percent. It is then drawn as far left
        as it must be to fit in the field. The saved position is kept, so a
        shorter bar goes back to it.
        """
        x, y = self.getButtonCoords("sb")
        field = self.mainwindow.field
        x = max(field.x(), min(x, field.x() + field.width() - self.sb.width()))
        self.sb.move(x, y)
        
    def resize(self):
        """Move the buttons to fit the main window."""
        # cheap and idempotent: a palette group rebuilt since the last pass
        # (the trace palette on a series change, the sliders on a B/C reset)
        # gets its right-click hide menu here
        self.installHideMenus()
        self.placeModeButtons()
        for i, pb in enumerate(self.palette_buttons):
            self.placePaletteButton(pb, i)
        self.placePaletteSideButtons()
        self.placeLabel()
        self.placeIncrementButtons()
        self.placeBCButtons()
        # the field may have changed width, and the bar's room is a share of
        # it (all of it for a length you typed); a no-op when unchanged
        self.sb.setMaxPixelLength(self.sbWidth())
        if self.sb.override_length:
            self.sb.setOverride(self.sb.override_length, self.mainwindow.field.width())
        self.placeSB()

    def reset(self):
        """Reset the mouse palette when opening a new series."""
        mode = self.mainwindow.field.mouse_mode
        # a length you type lasts until another series opens; Options OK
        # and a palette import rebuild the palette on the same series
        override = None
        if self.mainwindow.series is self.series:
            override = self.sb.override_length
        self.close()
        self.__init__(self.mainwindow)
        if override:
            self.sb.setOverride(override, self.mainwindow.field.width())
            self.placeSB()
        # the new buttons start on Pointer, but the field keeps its mode
        for name, (button, mouse_mode, _) in self.mode_buttons.items():
            button.setChecked(mouse_mode == mode)
            if mouse_mode == mode:
                self.selected_mode = name

    def close(self):
        """Close all buttons"""
        for bname in self.mode_buttons:
            button, _, __ = self.mode_buttons[bname]
            button.close()
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
        
