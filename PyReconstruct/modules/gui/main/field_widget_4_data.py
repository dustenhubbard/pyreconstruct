import os
import time
import math

import cv2

from PySide6.QtWidgets import (
    QInputDialog,
)

from PyReconstruct.modules.calc import (
    pixmapPointToField,
    centroid,
    lineDistance,
    correlate
)
from PyReconstruct.modules.datatypes import Transform
from PyReconstruct.modules.gui.utils import (
    notify, 
    notifyLocked, 
    notifyConfirm,
    getProgbar,
)

from PyReconstruct.modules.backend.func.state_manager import (
    FieldState, nextStamp, captureObjectIds
)

from .field_widget_3_object import FieldWidgetObject

class FieldWidgetData(FieldWidgetObject):
    """
    SECTION AND SERIES FUNCTIONS
    ---------------
    All of the field widget functions related to editing the section and series data.
    """
    def markTime(self):
        """Keep track of the time on the series file."""
        try:
            for f in os.listdir(self.series.getwdir()):
                if "." not in f and f.isnumeric():
                    os.remove(os.path.join(self.series.getwdir(), f))
                    break
            self.time = str(round(time.time()))
            open(os.path.join(self.series.getwdir(), self.time), "w").close()
        except FileNotFoundError:
            pass
    
    def unlockSection(self):
        """Unlock the current section."""
        self.section.align_locked = False
        # only the lock changed, so only the section list is refreshed. A
        # full updateData here would publish a scissors cut in progress: the
        # pickup has taken the trace out of the section, so the object's row
        # would leave the Object List and nothing would bring it back.
        self.series.data.updateSection(self.section, update_traces=False)
        self.table_manager.updateSections()
        self.mainwindow.seriesModified()
    
    def usingLocked(self):
        """Returns true if the current tracing trace is locked."""
        return self.series.getAttr(self.tracing_trace.name, "locked")
    
    def notifyLocked(self, names):
        """Notify to the user that a trace is locked."""
        if type(names) is str:
            names = [names]
        else:
            names = set(names)

        unlocked = notifyLocked(names, self.series, self.series_states)
        
        if unlocked:
            self.table_manager.updateObjects(names)

        return unlocked
    
    def setCuration(self, cr_status : str, traces : list = None):
        """Set the curation for the selected traces.
        
            Params:
                cr_status (str): the curation status to set for the traces
                traces (list): the list of traces to set
        """
        if not traces:
            traces = self.section.selected_traces.copy()

        if cr_status == "Needs curation":
            assign_to, confirmed = QInputDialog.getText(
                self,
                "Assign to",
                "Assign curation to username:\n(press enter to leave blank)"
            )
            if not confirmed:
                return
        else:
            assign_to = ""
        
        self.series.setCuration([t.name for t in traces], cr_status, assign_to)

        # manually mark as edited
        [self.section.modified_contours.add(t.name) for t in traces]

        self.saveState()
    
    def deleteAll(self, tags=False):
        """Delete all traces in the series that match the trace name (and possibly tags).
        
            Params:
                tags (bool): True if tags should be compared
        """
        if len(self.section.selected_traces) != 1:
            notify("Please select only one trace.")
            return
        trace = self.section.selected_traces[0]

        if tags:
            self.series.deleteAllTraces(trace.name, trace.tags, self.series_states)
        else:
            self.series.deleteAllTraces(trace.name, series_states=self.series_states)
        
        self.table_manager.updateObjects([trace.name])
        self.reload()
    
    def changeTform(self, new_tform):
        # check for section locked status
        if self.section.align_locked:
            return

        # check if propagating
        if self.propagate_tform:
            current_tform = self.section_layer.section.tform
            dtform = new_tform * current_tform.inverted()
            self.stored_tform = dtform * self.stored_tform
        else:
            # Remember where this section's transform stood before the latest
            # run of changes to it, so that starting propagation recording
            # afterward can pick up an alignment already made here.
            last = self.tform_before_change
            if last is None or last[0] != self.section.n:
                self.tform_before_change = (self.section.n, self.section.tform.copy())

        self.section.tform = new_tform
        self.series.addLog(None, self.section.n, "Modify transform")

        self.generateView()
        self.saveState()
    
    def setBrightness(self, b : int, log_event=True):
        """Set the brightness of the section."""
        self.section.brightness = b
        if self.section.brightness > 100:
            self.section.brightness = 100
        elif self.section.brightness < -100:
            self.section.brightness = -100

        # update the table
        self.series.data.updateSection(self.section)
        self.table_manager.updateSections([self.section.n])

        self.mainwindow.seriesModified(True)
        self.generateView(generate_traces=False)
        
        if log_event:
            self.series.addLog(None, self.series.current_section, "Modify brightness/contrast")
    
    def setContrast(self, c : int, log_event=True):
        """Set the contrast of the section."""
        self.section.contrast = c
        if self.section.contrast > 100:
            self.section.contrast = 100
        elif self.section.contrast < -100:
            self.section.contrast = -100

        # update the table
        self.series.data.updateSection(self.section)
        self.table_manager.updateSections([self.section.n])
        
        self.mainwindow.seriesModified(True)
        self.generateView(generate_traces=False)
        
        if log_event:
            self.series.addLog(None, self.series.current_section, "Modify brightness/contrast")
    
    def changeBrightness(self, change : int):
        """Change the brightness of the section.
        
            Params:
                change (int): the degree to which brightness is changed
        """
        self.setBrightness(self.section.brightness + change)
    
    def changeContrast(self, change : int):
        """Change the contrast of the section.
        
            Params:
                change (int): the degree to which contrast is changed"""
        self.setContrast(self.section.contrast + change)
    
    def setPropagationMode(self, propagate : bool):
        """Set the propagation mode.
        
            Params:
                propagate (bool): whether to begin or finish propagating
        """
        self.propagate_tform = propagate
        if self.propagate_tform:
            self.stored_tform = Transform([1,0,0,0,1,0])
            # include the alignment just made on this section, if the last
            # transform change was made here (an undo back to where it
            # started leaves nothing to include)
            last = self.tform_before_change
            if last is not None and last[0] == self.section.n:
                self.stored_tform = self.section.tform * last[1].inverted()
            self.propagated_sections = set([self.series.current_section])
        # a change is recorded or propagated at most once
        self.tform_before_change = None
        self.update()
        
    def propagateTo(self, to_end : bool = True, log_event=True):
        """Propagate the stored transform to the start/end of series.
        
            Params:
                to_end (bool): True propagates to the end, False propagates to beginning
        """
        # the field's section is written below without saveAllData, so an
        # open scissors cut has to put its trace back here
        self.cancelOpenScissorsCut()
        # Reading each candidate section can take time before propagation
        # itself begins. Acknowledge the command before even this preparation.
        checking = getProgbar("Checking sections for propagation...", cancel=False)
        try:
            self.section.save()
            # the flickered-away section can hold unsaved edits too, and the
            # reload at the end reads both sections back from their files
            if self.b_section:
                self.b_section.save()
            included_sections = []
            for snum in self.series.sections:
                if snum not in self.propagated_sections:
                    modify_section = (
                        (to_end and snum > self.series.current_section)
                        or
                        (not to_end and snum < self.series.current_section)
                    )
                    if modify_section: included_sections.append(snum)

            locked_sections = set()
            for index, snum in enumerate(included_sections):
                section = self.series.loadSection(snum)
                if section.align_locked:
                    locked_sections.add(snum)
                checking.setValue((index + 1) / len(included_sections) * 100)
        finally:
            checking.close()

        # Close preparation feedback before asking for confirmation.
        if locked_sections:
            if not notifyConfirm("Locked sections will not be modified.\nWould you still like to propagate the transform?"):
                return
            included_sections = [
                snum for snum in included_sections
                if snum not in locked_sections
            ]

        # create the progress bar
        if included_sections:
            progbar = getProgbar(
                text="Propagating transform...",
                cancel=False
            )
            progress = 0
            final_value = len(included_sections)
            progbar.setValue(0)

            # record a series-wide undo state for the propagation
            self.series_states.addState()

            try:
                for snum in included_sections:
                    section = self.series.loadSection(snum)
                    # capture the section's pre-modification state (no-op if
                    # its state tracking is already initialized)
                    self.series_states[section]
                    new_tform = self.stored_tform * section.tform
                    section.tform = new_tform
                    section.save()
                    # record the undo state so the propagation is undoable
                    self.series_states[snum].addState(section, self.series)
                    self.series_states.addSectionUndo(snum)
                    self.propagated_sections.add(snum)
                    if log_event:
                        self.series.addLog(None, snum, "Modify transform")
                    progress += 1
                    progbar.setValue(progress/final_value * 100)
            finally:
                progbar.close()

        self.reload()
    
    def changeAlignment(self, new_alignment : str, refresh_data=True):
        """Change the alignment setting for the series.
        
            Params:
                new_alignment (str): the name of the new alignment
        """
        self.series.alignment = new_alignment

        # turn off propagation
        self.setPropagationMode(False)
        
        self.reload()

        # refresh data and tables
        self.table_manager.recreateTables(refresh_data)
    
    def translateTform(self, dx : float, dy : float):
        """Translate the transform for the entire section.
            Params:
                dx (float): x-translate
                dy (float): y-translate
        """
        new_tform = self.section.tform.getList()
        new_tform[2] += dx
        new_tform[5] += dy
        new_tform = Transform(new_tform)
        self.changeTform(new_tform)
    
    def rotateTform(self, cc=True):
        """Rotate the section transform."""
        tform = self.section.tform
        tform_list = tform.getList()
        x, y = pixmapPointToField(
            self.mouse_x,
            self.mouse_y,
            self.pixmap_dim,
            self.series.window,
            self.section.mag
        )
        translate_tform = Transform([1, 0, x, 0, 1, y])
        t = math.pi / 720
        t *= 1 if cc else -1
        sin = math.sin(t)
        cos = math.cos(t)
        rotate_tform = Transform([
            cos, -sin, 0,
            sin, cos, 0
        ])
        new_tform = (
            (tform * translate_tform.inverted() * rotate_tform * translate_tform)
        )
        self.changeTform(new_tform)
    
    def scaleTform(self, sx : float = 1, sy : float = 1):
        """Scale a section transform.
        
            Params:
                sx (float): scaling factor in x
                sy (float): scaling factor in y
        """
        m = self.section.tform.getList()
        m[0] *= sx
        m[4] *= sy
        new_tform = Transform(m)
        self.changeTform(new_tform)
    
    def shearTform(self, sx : float = 0, sy : float = 0):
        """Shear a section transform.
        
            Params:
                sx (float): shear delta in x
                sy (float): shear delta in y
        """
        m = self.section.tform.getList()
        m[1] += sx
        m[3] += sy
        new_tform = Transform(m)
        self.changeTform(new_tform)
    
    def translate(self, dx : float, dy : float):
        """Translate the transform OR the selected traces.
        
            Params:
                dx (float): x-translate
                dy (float): y-translate
        """
        if self.section.selected_traces or self.section.selected_ztraces:
            # moving points is a modification to existing traces, so refuse it
            # for a locked object. Refusing the whole call rather than the
            # locked part of it keeps a mixed selection from being torn apart:
            # the ztraces would otherwise move while the traces stayed put.
            if self.refuseLockedTraces(self.section.selected_traces):
                return

            self.section.translateTraces(dx, dy)
            self.saveState()
            self.generateView()
        else:
            self.translateTform(dx, dy)
    
    def affineAlign(self):
        """Modify the linear transformation using points from the selected trace.
        """
        if not self.b_section or self.section.align_locked:
            return
        
        # gather traces
        a_traces = self.section.selected_traces.copy()
        b_traces = self.b_section.selected_traces.copy()

        # check number of selected traces
        alen = len(a_traces)
        blen = len(b_traces)
        if alen < 3:
            notify("Please select 3 or more traces for aligning.")
            return
        if alen != blen:
            notify("Please select the same number of traces on each section.")
            return
        contour_name = a_traces[0].name

        # check that all traces have same name
        for trace in (a_traces + b_traces):
            if trace.name != contour_name:
                notify("Please select traces of the same name on both sections.")
                return

        # gather points from each section
        centsA = []
        for trace in a_traces:
            centsA.append(centroid(trace.points))
        centsB = []
        tformB = self.b_section.tform
        for trace in b_traces:
            pts = tformB.map(trace.points)
            centsB.append(centroid(pts))
        
        # calculate the tform
        a2b_tform = Transform.estimateTform(centsA, centsB)

        # change the transform
        self.changeTform(a2b_tform)

    def corrAlign(self):
        """Align image by correlation using FFT."""

        if not self.b_section_layer or self.section.align_locked:
            if self.section.align_locked:
                notify(
                    "Make sure to unlock section before "
                    "preforming alignment by correlation."
                )
            return

        window = self.series.window
        dim = self.pixmap_dim

        arr_prev = self.b_section_layer.generateImageArray(dim, window)
        arr_curr = self.section_layer.generateImageArray(dim, window)

        arr_prev = cv2.cvtColor(arr_prev, cv2.COLOR_RGB2BGR)
        arr_curr = cv2.cvtColor(arr_curr, cv2.COLOR_RGB2BGR)

        x, y = correlate(arr_curr, arr_prev)  # get cross correlation

        shift_x = x / self.scaling * self.section.mag
        shift_y = (y / self.scaling * self.section.mag) * -1
        
        shift_tform = Transform([1, 0, shift_x, 0, 1, shift_y])

        tform = self.section.tform
        # the shift is measured in field space (post-transform), so compose it
        # after the existing tform: A * B maps p -> B(A(p)) in this codebase.
        # Route through changeTform (rather than assigning section.tform
        # directly) so that when propagation recording is active the shift is
        # captured in stored_tform and can be replayed across a section range,
        # exactly like a manual transform. The composed new_tform has the same
        # shape as a manual translate (existing tform post-multiplied by a
        # field-space translation), so it propagates with identical semantics.
        # changeTform also handles generateView + saveState.
        self.changeTform(tform * shift_tform)

    def calibrateMag(self, trace_lengths : dict, log_event=True):
        """Calibrate the pixel mag based on the lengths of given traces.

            Params:
                trace_lengths (dict): the lengths of the selected traces (name: length)
        """
        # get an average scaling factor across the selected traces
        sum_scaling = 0
        total = 0
        for cname in trace_lengths:
            for trace in self.section.contours[cname]:
                # get the length of the trace with the given transform
                tform = self.section.tform
                d = lineDistance(tform.map(trace.points), closed=False)
                # scaling = expected / actual
                sum_scaling += trace_lengths[trace.name] / d
                total += 1
        
        # calculate new mag
        avg_scaling = sum_scaling / total
        new_mag = self.section.mag * avg_scaling

        self.setMag(new_mag, log_event)
    
    def setMag(self, new_mag : float, log_event=True):
        """Set a new magnification for the series.
        
            Params:
                new_mag (float): the new magnification for the series
        """
        # a zero, negative or non-finite mag cannot be undone by another
        # calibration, so refuse it before any section is rewritten
        if not math.isfinite(new_mag) or new_mag <= 0:
            raise ValueError(f"magnification must be greater than zero, got {new_mag}")

        # apply new mag to every section, as one undo that cannot be split
        # into section undos: a section undone alone would sit at the old mag
        # while the rest of the series stays at the new one
        self.series_states.addState(breakable=False)
        mag_states = []
        for snum, section in self.series.enumerateSections(
            message="Changing series magnification..."
        ):
            # the state before the change, read from the section's file
            section_states = self.series_states[section]
            self.series_states.recordMag(snum, section.mag)
            section.setMag(new_mag)
            section.save()
            # A state on every section that holds every trace at the new mag,
            # so an undo returns to the old traces exactly and a later edit on
            # the section undoes back to the new ones. The traces stay on disk
            # as a copy of the saved file, as the section's first state does,
            # so a large series is not held in memory.
            section_states.addState(section, self.series)
            if self.series.isWelcomeSeries():
                contours_fp = None
            else:
                contours_fp = os.path.join(
                    self.series.hidden_dir,
                    f"{self.series.sections[snum]}.m{nextStamp()}"
                )
            section_states.current_state = FieldState(
                section.contours,
                {},
                section.tforms,
                section.flags,
                contours_fp,
                src_fp=section.filepath if contours_fp else None,
            )
            section_states.current_state.oids = captureObjectIds(
                self.series, section, section.contours
            )
            mag_states.append(section_states.current_state)
            self.series_states.addSectionUndo(snum)

        # every z-trace moved too: one copy at the new mag, shared by the
        # sections' states, which read it and never change it
        ztraces = {name: z.copy() for name, z in self.series.ztraces.items()}
        for state in mag_states:
            state.ztraces = ztraces
        
        if log_event:
            self.series.addLog(None, None, "Calibrate series")
        
        # reload the field
        self.reload()
        self.table_manager.recreateTables(refresh_data=True)
