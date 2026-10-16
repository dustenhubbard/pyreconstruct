
from PySide6.QtWidgets import (
    QInputDialog, 
)

from PyReconstruct.modules.datatypes import Trace, Ztrace
from PyReconstruct.modules.calc import pixmapPointToField, distance
from PyReconstruct.modules.gui.dialog import QuickDialog
from PyReconstruct.modules.gui.utils import notify

from .field_widget_5_mouse import (
    CLOSEDTRACE, 
    OPENTRACE,
    ROI_BOX
)
from .field_widget_6_paint import FieldWidgetPaint
from .status_readout import SEPARATOR


def viewMissesBounds(window : list, bounds : tuple) -> bool:
    """Whether a view window and a bounding box share no area.

    A window that only touches an edge of the box shows none of it, so that
    counts as missing too.

        Params:
            window (list): the x, y, w, h of the field view
            bounds (tuple): min_x, min_y, max_x, max_y of the box
        Returns:
            (bool): True if the window shows no part of the box
    """
    wx, wy, ww, wh = tuple(window)
    min_x, min_y, max_x, max_y = bounds
    return (
        wx + ww <= min_x or wx >= max_x or
        wy + wh <= min_y or wy >= max_y
    )


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
    
    def toggleRoiBox(self):
        """Turn the ROI box on or off.

        On asks for the size, then the next click in the field sets the
        center. Off shows every trace again. Neither saves an undo state or
        marks the series modified: the box only changes what is drawn.
        """
        if self.roi_box_on:
            self.roi_box_on = False
            self.roi_box_center = None
            if self.mouse_mode == ROI_BOX:
                self.mainwindow.mouse_palette.activateModeButton("Pointer")
            self.generateView()
            return

        if not self.setRoiBoxSize():
            return
        self.roi_box_on = True
        self.roi_box_center = None
        self.moveRoiBox()

    def setRoiBoxSize(self) -> bool:
        """Ask for the ROI box's width and height (kept for the session).

            Returns:
                (bool): True if the user confirmed a size
        """
        w, h = self.roi_box_size
        structure = [
            ["Width (μm):", (True, "float", w, (1e-6, 1e6))],
            ["Height (μm):", (True, "float", h, (1e-6, 1e6))],
        ]
        response, confirmed = QuickDialog.get(self, structure, "ROI box size")
        if not confirmed:
            return False
        self.roi_box_size = (float(response[0]), float(response[1]))
        if self.roiBox() is not None:
            self.generateView()
        return True

    def moveRoiBox(self):
        """Switch to the ROI box mouse mode: each click sets the center, and
        each drag sets the center and the size."""
        if not self.roi_box_on:
            return
        self.setMouseMode(ROI_BOX)
        # no palette button owns this mode
        for button, _, __ in self.mainwindow.mouse_palette.mode_buttons.values():
            button.setChecked(False)
        self.update()

    def roiBoxStatus(self) -> str:
        """The status-bar text for the ROI box, or None while it is off."""
        if not self.roi_box_on:
            return None
        w, h = self.roi_box_size
        size = f"{w:g} x {h:g} μm"
        if self.roi_box_center is None:
            return f"ROI box {size}: click or drag to place"
        return f"ROI box {size}"

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
        `showMessage` (the curation acknowledgment, for one) -- the two now sit side by
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

        # say the box is on, so a user never wonders where the traces went
        roi_box_status = self.roiBoxStatus()
        if roi_box_status:
            detail_list.insert(0, roi_box_status)

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

        # an ROI box drag ends the same way, with the box as it was
        self.cancelRoiBoxDrag()
    
    def backspace(self):
        """Called when backspace OR Del is pressed: either delete traces or undo line trace."""
        if self.is_line_tracing and len(self.current_trace) > 1:
            self.current_trace.pop()
            self.update()
            
        elif self.is_scissoring:
            # backing a scissors cut down to one point cancels the cut, and
            # the trace it picked up goes back as it was
            self.cancelScissors()

        elif len(self.current_trace) == 1:
            self.is_line_tracing = False
            self.deactivateMouseBoundaryTimer()
            self.update()
            
        else:
            self.deleteTraces()
    
    def imageBounds(self):
        """The section image's bounding box in field coordinates.

            Returns:
                (tuple): min_x, min_y, max_x, max_y of the image after the
                    section transform, or None when no image is loaded
        """
        if not self.section_layer.image_found:
            return None

        tform = self.section.tform
        xvals = []
        yvals = []
        # get the field location of the image
        for p in self.section_layer.base_corners:
            x, y = [n*self.section.mag for n in p]
            x, y = tform.map(x, y)
            xvals.append(x)
            yvals.append(y)
        return min(xvals), min(yvals), max(xvals), max(yvals)

    def home(self):
        """Set the view to the image."""
        bounds = self.imageBounds()
        # check is an image has been loaded
        if bounds is None:
            return

        min_x, min_y, max_x, max_y = bounds
        self.series.window = [
            min_x,
            min_y,
            max_x - min_x,
            max_y - min_y
        ]
        self.generateView()

    def viewIsOffImage(self) -> bool:
        """Whether the view window misses the section image entirely.

        The reported case was a saved window of [-9.07, -0.94, 1, 1] on an
        image at the origin, which opened to a black field with the traces
        off screen as well. False when no image is loaded: a series without
        images is viewed by its traces, and that view is wherever the user
        left it.
        """
        bounds = self.imageBounds()
        if bounds is None:
            return False
        return viewMissesBounds(self.series.window, bounds)

    def viewIsOffTraces(self) -> bool:
        """Whether the view window misses every shown trace on the section.

        A trace counts as in view when its bounding box, after the section
        transform, shares any area with the window, which is the box the
        field draws it in. Hidden traces and traces of a hidden group are
        not drawn, so they do not count: a view over nothing but hidden
        traces shows a black field. A section with no shown traces is off
        traces.

        One pass over the section's points, the same mapping the trace
        layer uses, stopping at the first trace in view.
        """
        window = self.series.window
        tform = self.section.tform
        group_hidden = self.section.groupHiddenNames()
        for trace in self.section.tracesAsList():
            if trace.hidden or not trace.points or trace.name in group_hidden:
                continue
            points = tform.mapPointsArray(trace.points)
            bounds = (
                points[:, 0].min(), points[:, 1].min(),
                points[:, 0].max(), points[:, 1].max(),
            )
            if not viewMissesBounds(window, bounds):
                return False
        return True

    def viewShowsNothing(self) -> bool:
        """Whether the view window misses both the section image and every
        shown trace on the section, so the field is black.

        A view that shows traces outside the image is one the user may have
        chosen, since the 3D scene's double-click writes a one-micron view
        at the point clicked, so it is not treated as lost.
        """
        return self.viewIsOffImage() and self.viewIsOffTraces()

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

        # A gesture still open ends first, as paging does
        # (MainWindow.changeSection). This is the one jump that reaches the
        # field's changeSection without going through there, and a scissors
        # cut left open across it belonged to the section the field has left:
        # the next save backed it out into the section on screen, and wrote
        # the one it came from without the trace. Within the section the view
        # still moves, and the cut's points are pixels of the view it was
        # open in, so it ends here too rather than landing where those pixels
        # point afterwards.
        self.endPendingEvents()

        # Through the main window, as paging goes, so the section being left
        # is saved first. The field holds one section besides the one on
        # screen, and the field's own changeSection drops the older of the
        # two: called here directly, a second jump threw away the unsaved
        # edits of the section two jumps back.
        if self.series.current_section != snum:
            self.mainwindow.changeSection(snum)
        
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

    def configureHoverColumns(self):
        """Open dialog to configure which columns appear in hover tooltip."""
        from PyReconstruct.modules.gui.dialog.hover_columns import HoverColumnsDialog

        columns, confirmed = HoverColumnsDialog(self, self.hover_columns).exec()
        if confirmed:
            self.hover_columns = columns
            self.series.setOption("hover_columns", columns)
