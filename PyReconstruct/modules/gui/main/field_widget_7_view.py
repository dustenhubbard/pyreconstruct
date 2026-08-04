
from PySide6.QtWidgets import (
    QInputDialog, 
)

from PyReconstruct.modules.datatypes import Trace, Ztrace
from PyReconstruct.modules.calc import pixmapPointToField, distance
from PyReconstruct.modules.gui.dialog import QuickDialog
from PyReconstruct.modules.gui.utils import notify

from .field_widget_5_mouse import (
    CLOSEDTRACE, 
    OPENTRACE
)
from .field_widget_6_paint import FieldWidgetPaint
from .status_readout import SEPARATOR


class FieldWidgetView(FieldWidgetPaint):
    """
    VIEW FUNCTIONS
    --------------
    These are all the miscellaneous functions that are not directly
    called by signals in the GUI.
    """
    def toggleBlend(self):
        """Toggle blending sections."""
        self.blend_sections = not self.blend_sections
        self.generateView()
    
    def setViewMagnification(self, new_mag : float = None):
        """Set the scaling for the section view.
        
            Params:
                new_mag (float): the new magnification (pixels per micron)
        """
        if new_mag is None:
            new_mag, confirmed = QInputDialog.getText(
                self,
                "View Magnification",
                "Enter view magnification (pixels per micron):",
                text=str(round(1 / self.series.screen_mag, 6))
            )
            if not confirmed:
                return
            try:
                new_mag = float(new_mag)
            except ValueError:
                return
            if new_mag <= 0:  # magnification must be positive
                return
        else:
            new_mag = 1 / new_mag
        
        self.setView(new_mag)
    
    def findContourDialog(self):
        """Open a dilog to prompt user to find contour."""
        contour_name, confirmed = QInputDialog.getText(
            self,
            "Find Contour",
            "Enter the contour name:",
        )
        if not confirmed:
            return
        self.findContour(contour_name)

    def updateStatusBar(self, trace : Trace = None):
        """Update status bar with useful information.

        The readout goes into the main window's permanent status-bar label, not
        into `statusbar.showMessage()`. `showMessage` posts a *temporary*
        message, and Qt blanks temporary messages whenever a status-tip event
        reaches the window: hovering any `QAction` sends one, and an action
        without a status tip sends an empty string, so moving the pointer from
        the field up to the menu bar used to wipe the readout until the pointer
        came back. A permanent widget is untouched by that, and it also stops
        this readout from destroying genuine transient notices posted with
        `showMessage` (`MainWindow._onStartupCheck`) -- the two now sit side by
        side in the bar instead of overwriting each other.

        The first three parts are handed to the readout separately from the
        rest because each of them is its own clickable widget there; see
        `gui/main/status_readout.py`. `status_list` still holds the whole
        readout in order, because that is what `field_widget_1_base` builds
        when it has nothing else yet.

            Params:
                trace (Trace): optional trace to add to status bar
        """
        # display current section
        section = "Section: " + str(self.series.current_section)

        # display the alignment setting
        alignment = "Alignment: " + self.series.alignment

        # display the brightness/contrast setting
        bc_profile = "B/C Profile: " + self.series.bc_profile

        # display mouse position in the field
        x, y = pixmapPointToField(
            self.mouse_x,
            self.mouse_y,
            self.pixmap_dim,
            self.series.window,
            self.section.mag
        )
        position = "x = " + str("{:.4f}".format(x)) + ", "
        position += "y = " + str("{:.4f}".format(y))
        detail_list = [position]

        # display the distance between the current position and the last point if line tracing
        #
        # `self.current_trace` is checked as well as the flag: every caller that
        # empties `current_trace` today either clears `is_line_tracing` first or
        # runs in a mouse mode that never sets it, so the two are consistent, but
        # nothing enforces that and `self.current_trace[-1]` on an empty list is
        # an `IndexError` raised out of a paint event. Skipping the distance is
        # the right answer for a line trace with no points anyway.
        if self.is_line_tracing and self.current_trace:
            last_x, last_y = self.current_trace[-1]
            d = distance(last_x, last_y, self.mouse_x, self.mouse_y)
            d = d / self.scaling * self.section.mag
            dist = f"Line distance: {round(d, 5)}"
            detail_list.append(dist)
        elif trace is not None:
            if type(trace) is Trace:
                detail_list.append(f"Closest trace: {trace.name}")
            elif type(trace) is Ztrace:
                detail_list.append(f"Closest trace: {trace.name} (ztrace)")

        self.status_list = [section, alignment, bc_profile] + detail_list

        # `paintText` calls this from every paint event, so an unconditional
        # write meant a `setText` and a status-bar relayout per frame even when
        # not one character had changed. `setReadout` compares each part
        # against what is displayed, so the write is confined to the events
        # that actually move the readout -- and a mouse move, which is the
        # frequent one, now rewrites only the coordinates.
        readout = getattr(self.mainwindow, "status_readout", None)
        if readout is None:
            # a harness main window standing in for the real one, without the
            # permanent widget. Behave as the field always did.
            self.mainwindow.statusbar.showMessage(SEPARATOR.join(self.status_list))
        else:
            readout.setReadout(
                section, alignment, bc_profile, SEPARATOR.join(detail_list)
            )

    def ztraceDialog(self):
        """Opens a dialog to edit selected traces."""
        if not self.section.selected_ztraces:
            return
        
        # check only one ztrace selected
        first_ztrace, i = self.section.selected_ztraces[0]
        for ztrace, i in self.section.selected_ztraces:
            if ztrace != first_ztrace:
                notify("Please modify only one ztrace at a time.")
                return
        
        name = first_ztrace.name
        color = first_ztrace.color
        structure = [
            ["Name:", ("text", name)],
            ["Color:", ("color", color)]
        ]
        response, confirmed = QuickDialog.get(self, structure, "Set Attributes")
        if not confirmed:
            return
        
        # save the series state
        self.series_states.addState()
        
        new_name, new_color = response
        self.series.editZtraceAttributes(
            ztrace.name,
            new_name,
            new_color
        )

        self.updateData()

        self.generateView(generate_image=False)
    
    def setTracingTrace(self, trace : Trace):
        """Set the trace used by the pencil/line tracing/stamp.
        
            Params:
                trace (Trace): the new trace to use as refernce for further tracing
        """
        self.endPendingEvents()
        t = trace.copy()
        for c in "{}<>":  # increment characters
            t.name = t.name.replace(c, "")
        self.tracing_trace = t
    
    def setLeftHanded(self, left_handed=None):
        """Set the handedness of the user
        
            Params:
                left_handed (bool): True if user is left handed
        """
        if left_handed is not None:
            self.series.setOption("left_handed", left_handed)
        else:
            self.series.setOption("left_handed", self.mainwindow.lefthanded_act.isChecked())

        # adjust handedness of the cursor
        if (self.mouse_mode == OPENTRACE or
            self.mouse_mode == CLOSEDTRACE):
            cursor = self.pencil_l if self.series.getOption("left_handed") else self.pencil_r
            if cursor != self.cursor(): self.setCursor(cursor)
    
    def endPendingEvents(self):
        """End ongoing events that are connected to the mouse."""
        if self.is_line_tracing and not self.is_z_tracing:
            self.lineRelease(override=True)

        # A pointer drag is the other gesture that spans several events, and it
        # is the one whose callers reach here mid-gesture: the button can be held
        # while the wheel pages sections, while an undo runs, or while the tool
        # or palette trace changes under a shortcut. All of those invalidate the
        # drag, so it ends here rather than being committed later against
        # whatever the field has become (issue #108).
        self.cancelTraceMove()
    
    def backspace(self):
        """Called when backspace OR Del is pressed: either delete traces or undo line trace."""
        if self.is_line_tracing and len(self.current_trace) > 1:
            self.current_trace.pop()
            self.update()
            
        elif len(self.current_trace) == 1:
            self.is_line_tracing = False
            self.deactivateMouseBoundaryTimer()
            self.update()
            
        else:
            self.deleteTraces()
    
    def home(self):
        """Set the view to the image."""
        # check is an image has been loaded
        if not self.section_layer.image_found:
            return
        
        tform = self.section.tform
        xvals = []
        yvals = []
        # get the field location of the image
        for p in self.section_layer.base_corners:
            x, y = [n*self.section.mag for n in p]
            x, y = tform.map(x, y)
            xvals.append(x)
            yvals.append(y)
        self.series.window = [
            min(xvals),
            min(yvals),
            max(xvals) - min(xvals),
            max(yvals) - min(yvals)
        ]
        self.generateView()
    
    def moveTo(self, snum : int, x : float, y : float):
        """Move to a specified section number and coordinates (used from 3D scene).
        
            Params:
                snum (int): the section number to move to
                x (int): the x coordinate to focus on
                y (int): the y coordinate to focus on
        """
        # check for section number
        if snum not in self.series.sections:
            return

        if self.series.current_section != snum:
            self.changeSection(snum)
        
        # set one micron diameter around object
        self.series.window = [x-0.5, y-0.5, 1, 1]

        self.generateView()
    
    def changeBCProfile(self, new_profile):
        """Change the brightness/contrast profile for the series.
        
            Params:
                new_profile (str): the name of the profile to switch to
        """
        self.series.bc_profile = new_profile

        # update palette and tables
        self.mainwindow.mouse_palette.updateBC()
        self.table_manager.updateSections(self.series.sections.keys())

        self.generateView()
    
    def setView(self, mag : float):
        """Set the scaling value for the view.
        
            Params:
                scaling (float): the new scaling value
        """
        # calculate the scaling factor for the magnification
        factor = mag * self.series.screen_mag

        # reset the window
        w, h = self.series.window[2], self.series.window[3]
        new_w, new_h = w / factor, h / factor
        self.series.window[0] += (w - new_w) / 2
        self.series.window[1] += (h - new_h) / 2
        self.series.window[2] = new_w
        self.series.window[3] = new_h

        self.generateView()
