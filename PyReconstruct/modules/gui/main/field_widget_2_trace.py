from typing import List, Union

from .context_menu_list import get_context_menu_list_trace

from PySide6.QtWidgets import QInputDialog

from PyReconstruct.modules.datatypes import Trace, Flag, Points
from PyReconstruct.modules.gui.dialog import (
    QuickDialog,
    FlagDialog,
    TraceDialog,
    ShapesDialog,
    ObjectGroupDialog,
    CopyToSectionsDialog,
    format_copy_result,
)
from PyReconstruct.modules.gui.utils import notify
from PyReconstruct.modules.calc import (
    pixmapPointToField,
    getExterior, 
    mergeTraces, 
    reducePoints,
    cutTraces,
    uncuttable_closed_traces,
)
from PyReconstruct.modules.gui.table import (
    TraceTableWidget,
    ZtraceTableWidget
)

from .field_widget_1_base import FieldWidgetBase

class FieldWidgetTrace(FieldWidgetBase):
    """
    TRACE FUNCTIONS
    ---------------
    All of the field widget functions related to editing traces, ztraces, and flags in the field.
    """

    # FIND FUNCTIONS

    def findTrace(self, trace_name : str, index : int = 0) -> None:
        """Focus the window view on a given trace.
        
            Params:
                trace_name (str): the name of the trace to focus on
                index (int): find the nth trace on the section
        """
        # check if the trace exists
        if trace_name not in self.section.contours or self.section.contours[trace_name].isEmpty():
            return
        try:
            trace = self.section.contours[trace_name][index]
        except IndexError:
            return
        
        # set the window to frame the object
        tform = self.section.tform
        min_x, min_y, max_x, max_y = trace.getBounds(tform)
        range_x = max_x - min_x
        range_y = max_y - min_y
        self.series.window = [min_x - range_x/2, min_y - range_y/2, range_x * 2, range_y * 2]

        # Set the trace as the only selected trace. A trace nobody can see is
        # not selected; a locked object's trace is, the same as anywhere else
        # (lock guards edits, not selection).
        if trace.hidden or self.hide_trace_layer:
            self.section.selected_traces = []
        else:
            self.section.selected_traces = [trace]

        self.generateView()
    
    def findContour(self, contour_name : str) -> None:
        """Focus the window view on a given trace.
        
            Params:
                contour_name (str): the name of the contour to focus on
        """
        # check if contour exists
        if contour_name not in self.section.contours or self.section.contours[contour_name].isEmpty():
            return
        
        # # get the minimum window requirements (1:1 screen to image pixels)
        # min_window_w = self.section.mag * self.section_layer.pixmap_dim[0]
        # min_window_h = self.section.mag * self.section_layer.pixmap_dim[1]
        
        # get the bounds of the contour and set the window
        contour = self.section.contours[contour_name]
        tform = self.section.tform
        vals = [trace.getBounds(tform) for trace in contour]
        
        min_x = min([v[0] for v in vals])
        min_y = min([v[1] for v in vals])
        max_x = max([v[2] for v in vals])
        max_y = max([v[3] for v in vals])
        
        range_x = max_x - min_x
        range_y = max_y - min_y

        # Get values of image (if exists) in order to figure out what 100% zoom means

        if self.section_layer.image_found:

            # This should probably be a stand alone function
            # It is used vertbatim in home method below
        
            tform = self.section.tform
            xvals = []
            yvals = []
        
            # get the field location of the image
            for p in self.section_layer.base_corners:
            
                x, y = [n * self.section.mag for n in p]
                x, y = tform.map(x, y)
                xvals.append(x)
                yvals.append(y)

            max_img_dist = max(xvals + yvals)

        else: # default to some arbitrary large size

            max_img_dist = 50

        zoom = self.series.getOption("find_zoom")

        new_range_x = range_x + ((100 - zoom)/100 * (max_img_dist - range_x))
        new_range_y = range_y + ((100 - zoom)/100 * (max_img_dist - range_y))

        new_x = min_x - ( (new_range_x - range_x) / 2 )
        new_y = min_y - ( (new_range_y - range_y) / 2 )

        # # check if minimum requirements are met
        # if new_range_x < min_window_w:
        #     new_x -= (min_window_w - new_range_x) / 2
        #     new_range_x = min_window_w
        # elif new_range_y < min_window_h:
        #     new_y -= (min_window_h - new_range_y) / 2
        #     new_range_y = min_window_h
        
        self.series.window = [
            
            new_x,
            new_y,
            new_range_x,
            new_range_y
            
        ]

        # set the selected traces
        self.section.selected_traces = []
        for trace in contour.getTraces():
            if not trace.hidden and not self.hide_trace_layer:
                self.section.addSelectedTrace(trace)

        self.generateView()
    
    def findFlag(self, flag : Flag):
        """Find a flag on the current section"""
        # check if flag exists
        found = False
        for f in self.section.flags:
            if flag.equals(f):
                flag = f
                found = True
        if not found:
            return
        
        # # get the minimum window requirements (1:1 screen to image pixels)
        # min_window_w = self.section.mag * self.section_layer.pixmap_dim[0]
        # min_window_h = self.section.mag * self.section_layer.pixmap_dim[1]
        
        # get the bounds of the contour and set the window
        tform = self.section.tform
        x, y = tform.map(flag.x, flag.y)
        
        min_x = max_x = x
        min_y = max_y = y
        
        range_x = max_x - min_x
        range_y = max_y - min_y

        # Get values of image (if exists) in order to figure out what 100% zoom means

        if self.section_layer.image_found:

            # This should probably be a stand alone function
            # It is used vertbatim in home method below
        
            tform = self.section.tform
            xvals = []
            yvals = []
        
            # get the field location of the image
            for p in self.section_layer.base_corners:
            
                x, y = [n * self.section.mag for n in p]
                x, y = tform.map(x, y)
                xvals.append(x)
                yvals.append(y)

            max_img_dist = max(xvals + yvals)

        else: # default to some arbitrary large size

            max_img_dist = 50

        zoom = self.series.getOption("find_zoom")

        # modifier for flags: cap at 99% zoom
        if zoom > 99:
            zoom = 99

        new_range_x = range_x + ((100 - zoom)/100 * (max_img_dist - range_x))
        new_range_y = range_y + ((100 - zoom)/100 * (max_img_dist - range_y))

        new_x = min_x - ( (new_range_x - range_x) / 2 )
        new_y = min_y - ( (new_range_y - range_y) / 2 )

        # # check if minimum requirements are met
        # if new_range_x < min_window_w:
        #     new_x -= (min_window_w - new_range_x) / 2
        #     new_range_x = min_window_w
        # elif new_range_y < min_window_h:
        #     new_y -= (min_window_h - new_range_y) / 2
        #     new_range_y = min_window_h
        
        self.series.window = [
            
            new_x,
            new_y,
            new_range_x,
            new_range_y
            
        ]

        # if the flag is an import conflict, hide everything except the conflict traces
        if flag.name.startswith("import-conflict_"):
            flag_cname = flag.name[flag.name.find("_")+1:]
            for cname, contour in self.section.contours.items():
                if cname == flag_cname:
                    for trace in contour:
                        trace.hidden = False
                else:
                    for trace in contour:
                        trace.hidden = True
            # `hidden` is written on the trace in place, from outside
            # `Section`, so no dual-write hook saw it and the columnar store
            # still holds the old flags. Rebuild from the result. Not optional
            # -- every `Section` carries a store and `hidden` is one of the
            # eight columns it mirrors. Without this, clicking an
            # import-conflict flag drifts the store on an ordinary user path
            # (import traces -> conflict flags -> click one), and the next edit
            # to one of these traces raises `ColumnarDualWriteMismatch` at the
            # user. The next SAVE no longer does -- it rebuilds the store and
            # logs the drift instead (D11) -- but the edit usually comes first.
            # See `series.py`'s `hideObjects` for the same shape.
            self.section.resyncColumnarStore()

        # set the selected flags
        show_flags = self.series.getOption("show_flags")
        if (show_flags == "all" or
            (show_flags == "unresolved" and not flag.resolved)):
            self.section.selected_flags = [flag]

        self.generateView()

    # SELECT FUNCTIONS
    
    def selectTrace(self, trace : Trace):
        """Select/deselect a single trace.
        
            Params:
                trace (Trace): the trace to select
        """
        ## Disable if trace layer hidden
        if self.hide_trace_layer:
            return
        
        if not trace:
            return

        ## Remove trace is already selected
        if trace in self.section.selected_traces:
            self.section.selected_traces.remove(trace)
                
        else:  # otherwise select it
            self.section.addSelectedTrace(trace)

        self.generateView(generate_image=False)
    
    def selectTraces(self, traces : list[Trace], ztraces_i : list):
        """Select/deselect a set of traces.
        
            Params:
                traces (list[Trace]): the traces to select
        """
        # disable if trace layer is hidden
        if self.hide_trace_layer:
            return

        for trace in traces:
            if trace not in self.section.selected_traces:
                self.section.addSelectedTrace(trace)
                
        for ztrace_i in ztraces_i:
            if ztrace_i not in self.section.selected_ztraces:
                self.section.selected_ztraces.append(ztrace_i)
            
        self.generateView(generate_image=False)
    
    def selectZtrace(self, ztrace_i : tuple):
        """Select/deselect a single ztrace point.
        
            Params:
                ztrace_i (tuple): the ztrace, index of point selected
        """
        # disbale if trace layer is hidden
        if self.hide_trace_layer:
            return
        
        # check if ztrace point has been selected
        if ztrace_i in self.section.selected_ztraces:
            self.section.selected_ztraces.remove(ztrace_i)
        else:
            self.section.selected_ztraces.append(ztrace_i)
        
        self.generateView(generate_image=False)

    def selectFlag(self, flag : Flag):
        """Select/deselect a single flag.
        
            Params:
                flag (Flag): the flag to select
        """
        # disable if trace layer is hidden
        if self.hide_trace_layer:
            return
        
        # check if flag has been selected
        if flag in self.section.selected_flags:
            self.section.selected_flags.remove(flag)
        else:
            self.section.selected_flags.append(flag)
        
        self.generateView(generate_image=False)
    
    # FIELD FUNCTIONS
    
    def toggleHideAllTraces(self):
        """Hide the trace layer."""
        self.hide_trace_layer = not self.hide_trace_layer
        if self.hide_trace_layer:
            self.show_all_traces = False
            # remove hidden traces that were selected (iterate a snapshot so
            # removing one doesn't skip the next selected trace)
            for trace in self.section.selected_traces.copy():
                if trace.hidden:
                    self.section.selected_traces.remove(trace)
        self.generateView()

    def toggleFocusMode(self):
        """Toggle focus mode."""

        if not self.focus_mode:

            if self.section.selected_traces:

                ## Force switch to pointer mode
                self.mainwindow.mouse_palette.activateModeButton("Pointer")

                last_selected = self.section.selected_traces[-1] # last selected trace
                self.focus_mode = last_selected.name
                
                obj_traces = [t for t in self.section.tracesAsList() if t.name == self.focus_mode]
                self.section.selected_traces = obj_traces

                self.generateView()
                self.copy()  # copy traces to paste attributes

            else:

                notify("Please select at least one trace in the field.")
                self.focus_mode = False

        else:

            self.focus_mode = False
            self.generateView()
    
    # no field_interaction decorator: this function is able to override the disabled trace layer
    def unhideAllTraces(self):
        """Unhide every trace on the section."""
        if self.hide_trace_layer:
            self.hide_trace_layer = False
        modified = self.section.unhideAllTraces()
        if modified:
            self.saveState()
            self.generateView()
    
    def toggleShowAllTraces(self):
        """Toggle show all traces regardless of hiding status."""
        self.show_all_traces = not self.show_all_traces
        if self.show_all_traces:
            self.hide_trace_layer = False
        # remove hidden traces that were selected (iterate a snapshot so
        # removing one doesn't skip the next selected trace)
        else:
            for trace in self.section.selected_traces.copy():
                if trace.hidden:
                    self.section.selected_traces.remove(trace)
        self.generateView()
    
    def toggleHideImage(self):
        """Toggle hide the image from view."""
        self.hide_image = not self.hide_image
        self.generateView(generate_traces=False)

    def deselectAllTraces(self):
        # disable if trace layer is hidden
        if self.zarr_layer:
            self.zarr_layer.deselectAll()
            self.generateView(generate_image=False)
        if not self.hide_trace_layer:
            self.section.deselectAllTraces()
            self.generateView(generate_image=False)
    
    def selectAllTraces(self):
        # disable if trace layer is hidden
        if self.hide_trace_layer:
            return
        self.section.selectAllTraces()
        self.generateView(generate_image=False)

    def invertTraceSelection(self):
        """Invert which traces are selected on the current section."""
        # disable if trace layer is hidden
        if self.hide_trace_layer:
            return
        self.section.invertTraceSelection(include_hidden=self.show_all_traces)
        self.generateView(generate_image=False)

    ############################################################################
    ## The lock check ##########################################################
    ############################################################################

    def refuseLockedTraces(self, traces : list) -> bool:
        """Refuse an operation that would change a locked object's trace data.

        The one lock check behind every field operation that adds, deletes or
        modifies traces. Returns True if the operation must not proceed, and
        tells the user why before it does: a silent refusal reads as a broken
        shortcut.

        All-or-nothing on a mixed selection, which is what `trace_function`,
        `object_function` and `deleteContours` already do: one locked object
        refuses the whole operation rather than quietly performing it on the
        rest, so the user cannot end up with half an edit applied.

        Not to be confused with `notifyLocked`, which asks whether to unlock and
        is used at the *start* of a mouse gesture (`scissorsPress`, and the
        tracing-mode gate in `mousePressEvent`). This one is the commit-time
        refusal used by everything that acts on a selection.

            Params:
                traces (list): the traces the operation would change
            Returns:
                (bool): True if the operation was refused
        """
        for name in set(t.name for t in traces):
            if self.series.getAttr(name, "locked"):
                notify(
                    "Cannot modify locked objects.\n"
                    "Please unlock before modifying."
                )
                return True

        return False

    def refuseLockedDestination(self, name : str) -> bool:
        """Refuse a rename that would move traces INTO a locked object.

        The other half of `refuseLockedTraces`, which only ever looks at the
        objects the selected traces are in right now. A rename has a second
        object: the one the traces land in. Renaming an unlocked object's trace
        to a locked object's name passes every source-side check and still adds
        a trace to the locked object, which is exactly the mutation lock exists
        to prevent.

        Scoped to the destination NAME and nothing else, because the lock rule
        is narrow: locking guards quantitative data (traces added, deleted or
        modified) and never selection, color or visibility. A rename that leaves
        the name alone is a color/tag edit and is not this function's business,
        so callers pass `None` through untouched.

        Same message and same all-or-nothing shape as `refuseLockedTraces`: one
        locked destination refuses the whole operation rather than renaming part
        of the selection, and the user is told why. A silent refusal reads as a
        broken command.

            Params:
                name (str): the name the traces would be renamed to (None or ""
                    when the operation is not renaming anything)
            Returns:
                (bool): True if the operation was refused
        """
        if not name:
            return False

        if self.series.getAttr(name, "locked"):
            notify(
                "Cannot modify locked objects.\n"
                "Please unlock before modifying."
            )
            return True

        return False

    ############################################################################
    ## Interactions only accessible through the field ##########################
    ############################################################################

    def field_interaction(fn):
        """Decorator for most basic field interactions.
        
        Check if the trace layer is hidden. If action performed, save the state
        and generate the view.
        
        The function this is decorating MUST return a modified bool: True if
        section modified, False if not.

        """
        def wrapper(self, *args, **kwargs):
            
            if self.hide_trace_layer:
                return False
            
            modified = fn(self, *args, **kwargs)

            if modified:
                
                self.saveState()
                self.generateView()
            
            return modified

        return wrapper
    
    @field_interaction
    def newTrace(
            self,
            trace_points : list,
            base_trace : Trace,
            points_as_pix=True,
            closed=True,
            reduce_points=True,
            log_event=True,
            simplify=False
    ):
        """Create a new trace from pixel coordinates.
        
            Params:
                trace_points (list): coordinates for the new trace
                base_trace (Trace): the trace containing the desired attributes
                points_as_pix (bool): True if points provided are in screen pixel coords (False if field coords)
                closed (bool): whether or not the new trace is closed
                reduce_points (bool): True if points should be simplified
                simplify (bool): True if points should be further simplifed
                log_event (bool): True if action should be logged
        """
        
        if len(trace_points) < 2:  # do not create if one point
            return False

        if reduce_points:

            if closed:
                
                trace_points = getExterior(trace_points)  # get exterior if closed (will reduce points)
                
            else:

                trace_points = reducePoints(trace_points, closed=False)  # only reduce points if trace is open

        # create the new trace
        new_trace = base_trace.copy()
        new_trace.points = []

        # remove trace if less than 2 points after simplification
        if len(trace_points) < 2:
            return False
        # force trace to be open if only two points
        if len(trace_points) == 2:
            new_trace.closed = False
        else:
            new_trace.closed = closed

        # get the points
        tform = self.section.tform
        for point in trace_points:
            
            if points_as_pix:
                point = pixmapPointToField(
                    point[0],
                    point[1],
                    self.pixmap_dim,
                    self.series.window,
                    self.section.mag
                )
                
            rtform_point = tform.map(*point, inverted=True) # apply the inverse tform to fix trace to base image
            new_trace.add(rtform_point)

        if simplify:

            window = self.series.getOption("roll_window")
            interpol_spacing = self.series.avg_mag / 2
            new_trace.smooth(window=window, spacing=interpol_spacing)  # spacing a function of pixel mag
        
        # add the trace to the section and select
        self.section.addTrace(new_trace, log_event=log_event)
        self.section.addSelectedTrace(new_trace)
        
        # if action is logged, increment the mouse_palette button
        if log_event:
            self.mainwindow.mouse_palette.incrementButton()

        # if not logging the event, the action is not complete
        return log_event 
    
    @field_interaction
    def cutTrace(self, scalpel_trace : list):
        """Execute a scalpel cut on the selected trace(s)

            Params:
                scalpel_trace (list): the list of pixel points defining the scalpel cut
                log_event (bool): True if the action should be logged
        """

        if len(self.section.selected_traces) == 0:
            notify("Select trace you would like to cut.")
            return False

        # The knife deletes the selected traces and replaces them with the
        # pieces. `mousePressEvent` dispatches KNIFE *before* it reaches its
        # `usingLocked()` branch, and that branch reads `tracing_trace` (the
        # palette's name for a new trace) rather than the object being cut, so
        # neither one guards this. The check belongs here, against the selection.
        if self.refuseLockedTraces(self.section.selected_traces):
            return False

        if len(set(t.name for t in self.section.selected_traces)) > 1:
            notify("Select a single object to cut at a time.")
            return False

        ## Make sure selected traces are all closed or all open
        
        closed = self.section.selected_traces[0].closed
        
        for t in self.section.selected_traces[1:]:
            
            if t.closed != closed:
                
                notify("Select traces that are all exclusively open or closed.")
                return False
        
        traces = self.section.selected_traces.copy()

        ## Assume same, otherwise suffer consequences
        example_trace = traces[0]
        ## Combine tags
        #
        # `example_trace` is `traces[0]`, and `traces` is
        # `self.section.selected_traces.copy()` -- a copy of the LIST, not of the
        # traces. So this writes `tags` in place on one of the section's own
        # traces, from outside `Section`, and nothing mirrors it into the store.
        #
        # `deleteTraces` further down would have covered the drift by dropping
        # these traces' rows, but three refusal paths return between here and
        # there (uncuttable self-crossing trace, and two failures of the cut
        # itself). On any of them the section keeps a trace whose tags no longer
        # match its row, and the next edit to that trace raises
        # `ColumnarDualWriteMismatch` at the user for an action they already saw
        # refused. (The next `Section.save()` rebuilds the store and logs the
        # drift rather than raising, since D11, which is why this is now a
        # crash-on-next-edit rather than an unsaveable section.) Repair as soon
        # as the drift exists rather than relying on every exit path below
        # staying the way it is.
        merged_any = False
        for trace in traces[1:]:
            for tag in trace.tags:
                if tag not in example_trace.tags:
                    merged_any = True
                    example_trace.tags.add(tag)

        if merged_any:
            self.section.resyncColumnarStore()

        ## Pixelize the selected traces
        traces_to_cut = [self.section_layer.traceToPix(t) for t in traces]

        ## Refuse a trace that cannot be cut, rather than deleting it
        #
        # A closed cut is a polygon difference and needs a polygon shapely will
        # accept. A freehand outline that crosses itself is not one, and
        # `cut_closed_traces` used to drop it from the result -- which this
        # method only inspects *after* `deleteTraces` has already run, so the
        # object was deleted, nothing replaced it, no message was shown and the
        # method returned True. Decide before anything is committed, and refuse
        # the whole selection the way `refuseLockedTraces` does rather than
        # cutting part of it.
        if example_trace.closed and uncuttable_closed_traces(traces_to_cut):

            notify(
                "A selected trace crosses itself and cannot be cut.\n"
                "The object was left unchanged."
            )

            return False

        ## Smooth cut if requested
        if self.series.getOption("roll_knife_average"):
            
            window = self.series.getOption("roll_knife_window")
            scalpel_points = Points(scalpel_trace, closed=False)
            
            scalpel_trace = scalpel_points.interp_rolling_average(
                spacing=4,  # pixels
                window=window
            )        
        
        ## Crunch the numbers
        cut_traces = cutTraces(
            traces_to_cut, 
            scalpel_trace, 
            self.series.getOption("knife_del_threshold"), 
            closed=example_trace.closed
        )

        ## A cut line of fewer than two points is no cut at all
        #
        # `cutTraces` returns the list it was given, unchanged and by identity,
        # for a degenerate cut line. A knife click with no drag produces one.
        # Leave the section alone instead of deleting every selected trace and
        # recreating it, which logged a modification and consumed a palette
        # increment for a gesture that did nothing.
        if cut_traces is traces_to_cut:
            return False

        ## Nothing to put back
        #
        # The last line of defense, for any path that returns no pieces at all
        # (every piece under the delete threshold, an open trace shapely could
        # not split). Deleting here is what loses an object, so refuse the whole
        # operation rather than half-completing it.
        if not cut_traces:

            notify(
                "The cut could not be completed.\n"
                "The object was left unchanged."
            )

            return False

        ## Remove old traces
        self.section.deleteTraces(traces, log_event=False)

        ## Create new traces
        for piece in cut_traces:
            self.newTrace(
                piece,
                example_trace,
                closed=example_trace.closed,
                reduce_points=False,
                log_event=False
            )
        
        self.series.addLog(example_trace.name, self.section.n, "Modify trace(s)")

        return True
    
    @field_interaction
    def placeStamp(self, pix_x : int, pix_y : int, stamp : Trace):
        """Called when mouse is pressed in stamp mode.
        
        Creates a stamp centered on the mouse location.
        
            Params:
                pix_x (int): pixel x-coord to place stamp
                pix_y (int): pixel y-coord to place stamp
                trace (Trace): the trace to place down
        """
        # convert the center point into field coords
        field_x, field_y = pixmapPointToField(
            pix_x,
            pix_y,
            self.pixmap_dim,
            self.series.window,
            self.section.mag
        )

        # create the stamp trace points
        new_stamp = [
            (field_x + x, field_y + y) for x, y in stamp.points
        ]

        self.newTrace(
            new_stamp,
            stamp,
            points_as_pix=False,
            closed=True,
            reduce_points=False
        )

        # saveState and generateView handled by self.newTrace
        return False 
    
    @field_interaction
    def placeGrid(
        self,
        pix_x : float, pix_y : float,
        ref_trace : Trace,
        w : float, h : float,
        dx : float, dy : float,
        nx : int, ny : int,
        scale_bar: bool=False):
        """Place a grid on the field.
        
            Params:
                pix_x (float): the x-coord of the mouse location
                pix_y (float): the y-coord of the mouse location
                trace (Trace): the trace to use in the grid
                w (float): the desired width of the trace
                h (float): the desired height of the trace
                dx (float): the x distance between traces in the grid
                dy (float): the y distance between traces in the grid
                nx (int): the number of columns
                ny (int): the number of rows
        """
        ## Get mouse coords and convert to field coords
        field_x, field_y = pixmapPointToField(
            pix_x, pix_y, self.pixmap_dim, self.series.window, self.section.mag
        )
            
        origin = field_x + w/2, field_y - h/2

        ## Create custom trace if creating sampling grid
        if self.series.getOption("sampling_frame_grid") and not scale_bar:
            n = 0.5
            nw, nh = n * w, n * h
            exc_points = [
                (-nw, 2*nh),
                (-nw, nh),
                (-nw, -nh),
                (nw, -nh),
                (nw, -2*nh)
            ]
            inc_points = [
                (-nw, nh),
                (nw, nh),
                (nw, -nh)
            ]
            
            exc_trace = ref_trace.copy()
            exc_trace.color = (255, 0, 0)
            exc_trace.closed = False
            exc_trace.points = exc_points

            inc_trace = ref_trace.copy()
            inc_trace.color = (0, 255, 0)
            inc_trace.closed = False
            inc_trace.points = inc_points

            traces = [exc_trace, inc_trace]

        else:
            # stretch the reference trace to desired size
            traces = [ref_trace.getStretched(w, h)]

        for c in range(nx):
            for r in range(ny):
                for trace in traces:
                    # create new trace
                    new_points = [
                        (
                            x + origin[0] + dx * c,
                            y + origin[1] - dy * r
                        )
                        for x, y in trace.points
                    ]
                    self.newTrace(
                        new_points,
                        trace,
                        points_as_pix=False,
                        closed=trace.closed,
                        reduce_points=False,
                        log_event=False
                    )
        
        self.series.addLog(
            ref_trace.name,
            self.section.n,
            "Create trace(s)"
        )

        self.mainwindow.mouse_palette.incrementButton()

        return True
    
    @field_interaction
    def placeFlag(self, title : str, pix_x : int, pix_y : int, color : tuple, comment : str):
        """Create a flag on the section.
        
            Params:
                title (str): the title of the flag
                pix_x (float): the x-coord of the mouse location
                pix_y (float): the y-coord of the mouse location
                color (tuple): the color of the flag
                comment (str): the flag comment
        """
        # get field coords then fix to image
        field_x, field_y = pixmapPointToField(pix_x, pix_y, self.pixmap_dim, self.series.window, self.section.mag)
        x, y = self.section.tform.map(field_x, field_y, inverted=True)
        
        # create flag
        f = Flag(title, x, y, self.section.n, color)
        if comment: f.addComment(self.series.user, comment)
        self.section.addFlag(f)

        return True
    
    # no decorator: called by action
    def editFlag(self, event=None):
        """Edit a flag. (Triggered by action when a flag is right-clicked)"""
        flag : Flag = self.clicked_trace  # clicked_trace is defined later in the GUI functions
        response, confirmed = FlagDialog(self, flag).exec()
        if confirmed:
            flag.name, flag.color, flag.comments, new_comment, resolved = response
            if new_comment: flag.addComment(self.series.user, new_comment)
            flag.resolve(self.series.user, resolved)
            self.generateView(generate_image=False)
            self.saveState()
    
    # no decorator: not an event that can be undone
    def copy(self):
        if self.hide_trace_layer:
            return
        copied_traces = self.section_layer.getCopiedTraces()
        if copied_traces:
            self.clipboard = copied_traces
    
    @field_interaction
    def cut(self):
        # `getCopiedTraces(cut=True)` deletes the selected traces, so this is a
        # delete and lock has to refuse it. `copy` above is left alone: it reads
        # the selection and changes nothing.
        if self.refuseLockedTraces(self.section.selected_traces):
            return False

        copied_traces = self.section_layer.getCopiedTraces(cut=True)
        if copied_traces:
            self.clipboard = copied_traces
            return True
        else:
            return False
    
    @field_interaction
    def paste(self):
        
        if not self.clipboard:
            return False
        
        # paste traces
        for trace in self.clipboard:
            
            self.newTrace(
                trace.points,
                trace,
                points_as_pix=False,
                closed=trace.closed,
                reduce_points=False,
            )
        
        return True
    
    @field_interaction
    def pasteAttributes(self):
        if not self.clipboard:
            return False

        # this rewrites the name of every selected trace, which moves the trace
        # out of one object and into another
        if self.refuseLockedTraces(self.section.selected_traces):
            return False

        trace = self.clipboard[0]
        name, color, tags, mode = trace.name, trace.color, trace.tags, trace.fill_mode

        # ...and the object it would move them INTO. Copy is deliberately
        # allowed on a locked object (it changes nothing), so the clipboard can
        # hold a locked object's trace with no refusal anywhere upstream.
        if self.refuseLockedDestination(name):
            return False

        self.section.editTraceAttributes(
            traces=self.section.selected_traces.copy(),
            name=name,
            color=color,
            tags=tags,
            mode=mode
        )

        return True

    ############################################################################
    ## Interactions accessible through field and trace list ####################
    ############################################################################

    def getTraceMenu(self, is_in_field=True, list_ops=None, find_in_field=None):
        """Return the trace context menu list structure.

            Params:
                is_in_field (bool): True for the field submenu variant
                list_ops (list): list-only table utilities for the trace list's
                    bottom utility slot
                find_in_field (callable): the trace list's "jump to this trace"
                    handler
        """
        return get_context_menu_list_trace(
            self, is_in_field, list_ops=list_ops, find_in_field=find_in_field
        )

    def _trace_function(check_locked: bool):
        """Build the trace-action decorator, with or without the lock check.

        Two decorators come out of this, and the difference between them is the
        whole reason it is a factory. See `trace_function` and
        `visibility_trace_function` below.

            Params:
                check_locked (bool): True if the action changes trace data and
                    must therefore refuse locked objects
        """
        def decorator(fn):
            def wrapper(self, *args, **kwargs):

                ## Get the selected names
                vscroll = None  # scroll bar if object list
                data_table = self.table_manager.hasFocus()

                if isinstance(data_table, TraceTableWidget):
                    selected_traces = data_table.getTraces(data_table.getSelected())

                    vscroll = data_table.table.verticalScrollBar()  # track scroll bar pos
                    scroll_pos = vscroll.value()

                else:
                    selected_traces = self.section.selected_traces.copy()

                ## If no objs selected
                if not selected_traces:
                    return

                ## Check for locked objects
                if check_locked and self.refuseLockedTraces(selected_traces):
                    return

                # save the data in the field
                self.mainwindow.saveAllData()

                # call function with selected names inserted
                completed = fn(self, selected_traces, *args, **kwargs)

                if not completed:
                    return

                # reset the scroll bar position if applicable
                if vscroll: vscroll.setValue(scroll_pos)

                # call to update is handled by field_interaction decorator

            return wrapper

        return decorator

    # Property given to all trace actions that are accessible through a context
    # menu. Handles passing the correct traces into the functions, and refuses
    # the action outright if any selected trace belongs to a locked object.
    trace_function = _trace_function(check_locked=True)

    # `trace_function` without the lock check, for actions that change what is
    # drawn rather than what is measured. Locking an object protects its
    # quantitative data (traces added, deleted or modified) and nothing else, so
    # an action that leaves every point, name and tag identical must not be
    # refused. Same reasoning as `hideOtherTraces` below, which sidesteps
    # `trace_function` entirely for want of this.
    visibility_trace_function = _trace_function(check_locked=False)

    @trace_function
    def copyTracesToSections(self, traces : list):
        """Copy the selected trace(s) onto multiple chosen sections at the same
        field (x, y) location (issue #91)."""
        if self.hide_trace_layer:
            return False

        # convert the selection to field coordinates, exactly as the copy path
        # does, so the traces can be re-projected onto each target section
        tform = self.section.tform
        field_traces = []
        for trace in traces:
            field_trace = trace.copy()
            field_trace.points = [tform.map(*p) for p in trace.points]
            field_traces.append(field_trace)

        # choose the target sections
        chosen, confirmed = CopyToSectionsDialog(self, self.series).get()
        if not confirmed:
            return False

        # never copy onto the source (current) section
        current = self.series.current_section
        excluded_current = current in chosen
        chosen.discard(current)

        if not chosen:
            notify("No other sections were selected to copy to.")
            return False

        names = list(set(t.name for t in field_traces))

        copied_to, skipped = self.series.copyTracesToSections(
            field_traces, chosen, self.series_states
        )

        # refresh the object/trace lists and the field view (only if anything
        # actually changed)
        if copied_to:
            self.table_manager.updateObjects(names)
            self.reload()

        # report the outcome to the user, listing the sections that ACTUALLY
        # received the trace(s) so the message reflects what was done
        message = format_copy_result(
            copied_to, skipped, current if excluded_current else None
        )
        if message:
            notify(message)

        return bool(copied_to)

    @trace_function
    @field_interaction
    def traceDialog(self, traces : list):
        """Opens dialog to edit selected traces."""
        # # do not run if both types of traces are selected or none are selected
        # if not(bool(self.section.selected_traces) ^ bool(self.section.selected_ztraces)):
        #     return
        # # run the ztrace dialog if only ztraces selected
        # elif self.section.selected_ztraces:
        #     self.ztraceDialog()
        #     return
        
        t, confirmed = TraceDialog(
            self,
            traces,
        ).exec()
        if not confirmed:
            return
        
        name, color, tags, mode = (
            t.name, t.color, t.tags, t.fill_mode
        )

        # `trace_function` cleared the objects these traces are in; the name the
        # user typed is a second object and nothing has checked it yet.
        if self.refuseLockedDestination(name):
            return

        self.section.editTraceAttributes(
            traces=traces.copy(),
            name=name,
            color=color,
            tags=tags,
            mode=mode
        )

        return True

    @trace_function
    @field_interaction
    def deleteTraces(
            self,
            traces: Union[List, None]=None,
            flags: Union[List, None]=None
    ) -> bool:
        """Delete the requested traces (selected traces by default)
        
            Params:
                traces (list): list of traces to delete
        """
        return self.section.deleteTraces(traces, flags)
    
    # visibility_trace_function, NOT trace_function: hiding a trace changes what
    # is drawn, not what is measured. Every point, name and tag survives it, so
    # lock has no business refusing it. This matches "Hide Other" below, which
    # was already written this way.
    @visibility_trace_function
    @field_interaction
    def hideTraces(self, traces : list, hide=True):
        """Hide/Unhide the requested traces (selected traces by default)

            Params:
                traces (list): the traces to hide/unhide
                hide (bool): True if hiding traces, False if unhiding
        """
        return self.section.hideTraces(traces, hide)

    # field_interaction only (NOT trace_function): "Hide Other" KEEPS the
    # selected traces and hides the rest on this section, so a locked selected
    # trace must not block it, and locked traces in the complement are hidden on
    # purpose. Undo is the ordinary single-section state from field_interaction.
    @field_interaction
    def hideOtherTraces(self):
        """Hide every trace on the current section except the selected one(s)."""
        return self.section.hideOtherTraces()

    @trace_function
    @field_interaction
    def makeNegative(self, traces : list, negative=True):
        """Make the selected traces negative.
        
            Params:
                negative (bool): True if traces should be made negative
        """
        return self.section.makeNegative(traces, negative)
    
    @trace_function
    @field_interaction
    def mergeTraces(self, traces: list, merge_attrs_only=False, restrict: list=[]):
        """Merge traces.
        
            Params:
                traces (list): selected traces
                merge_attrs_only (bool): True if only trace attributes should be merged
                restrict (list): restrict merging to a list of traces
        """
        if len(traces) < 2:
            notify("Please select two or more traces to merge.")
            return False

        to_merge = restrict if restrict else traces
        first_trace = to_merge[0]

        # set attributes to be the first object selected
        if merge_attrs_only is True:
            self.section.editTraceAttributes(
                to_merge,
                name=first_trace.name,
                color=first_trace.color,
                tags=first_trace.tags,
                mode=first_trace.fill_mode,
            )
            return True

        # merge traces
        else:
            pix_traces = []
            name = first_trace.name
            for trace in to_merge:
                if trace.name != name:
                    notify("Please merge traces with the same name.")
                    return False
                if trace.closed == False:
                    notify("Please merge only closed traces.")
                    return False
                # collect pixel values for trace points
                pix_points = self.section_layer.traceToPix(trace)
                pix_traces.append(pix_points)
            
            merged_traces = mergeTraces(pix_traces)  # merge the pixel traces
            
            # delete the old traces
            self.section.deleteTraces(to_merge, log_event=False)

            # create new merged trace
            for trace in merged_traces:
                self.newTrace(
                    trace,
                    first_trace,
                    log_event=False
                )
            
            self.series.addLog(name, self.section.n, "Modify trace(s)")
            
            return True

    @trace_function
    @field_interaction
    def smoothTraces(self, traces: list):
        """Smooth traces."""

        window = self.series.getOption("roll_window")

        for trace in traces:

            self.section.modified_contours.add(trace.name)
            trace.smooth(window, spacing=0.004)
            self.series.addLog(trace.name, self.section.n, "Smoothed trace(s)")

        if traces:

            # `traces` is the section's own selection, not copies, so
            # `Trace.smooth` has just rewritten `points` in place on traces the
            # section holds -- from outside `Section`, where no dual-write hook
            # sees it. `field_interaction` calls `saveState()` and
            # `generateView()` and neither repairs the store, so without this
            # the drift survives to whichever later edit touches one of these
            # traces and raises `ColumnarDualWriteMismatch` on an unrelated
            # action. A save in between now rebuilds and logs it (D11) rather
            # than raising, which narrows the failure without closing it.
            self.section.resyncColumnarStore()

        return True
        
    @trace_function
    @field_interaction
    def createTraceFlag(self, traces : list):
        """Create a flag associated with the selected traces."""
        name = traces[0].name
        color = traces[0].color
        for trace in traces[1:]:
            if name != trace.name:
                name = ""
            if color != trace.color:
                color = None
        
        structure = [
            ["Name:", (True, "text", name)],
            ["Color:", ("color", color), ""],
            ["Comment:"],
            [("textbox", "")]
        ]
        response, confirmed = QuickDialog.get(self, structure, "Flag")
        if not confirmed:
            return False
        
        # get the average centroid of all the selected traces
        cens = [t.getCentroid() for t in traces]
        cen_x = sum(x for x, y in cens) / len(cens)
        cen_y = sum(y for x, y in cens) / len(cens)
        
        # create the flag
        name, color, comment = response
        f = Flag(name, cen_x, cen_y, self.section.n, color)
        if comment:
            f.addComment(self.series.user, comment)
        self.section.addFlag(f)

        return True
    
    @trace_function
    @field_interaction
    def closeTraces(self, traces : list, closed=True):
        """Close a set of traces.
        
            Params:
                closed (bool): True if the traces should be closed
        """
        return self.section.closeTraces(traces, closed)

    @trace_function
    @field_interaction
    def editTraceRadius(self, traces : list):
        """Edit the radius for a set of traces."""
        existing_radius = round(traces[0].getRadius(), 7)

        for trace in traces[1:]:
            if abs(existing_radius - trace.getRadius()) > 1e-6:
                existing_radius = ""
                break
        
        new_rad, confirmed = QInputDialog.getText(
            self,
            "New Trace Radius",
            "Enter the new trace radius:",
            text=str(existing_radius)
        )
        if not confirmed:
            return False
        try:
            new_rad = float(new_rad)
        except ValueError:
            return False
        
        self.section.editTraceRadius(traces, new_rad)

        return bool(traces)
    
    @trace_function
    @field_interaction
    def editTraceShape(self, traces : list):
        """Modify the shape of the traces on an entire object."""
        new_shape, confirmed = ShapesDialog(self).exec()
        if not confirmed:
            return
        
        self.section.editTraceShape(traces, new_shape)

        return bool(traces)
    
    # ALL ZTRACE FUNCTIONS

    def getZtraceMenu(self, list_ops=None):
        """Get the context menu list for interacting with ztraces.

            Params:
                list_ops (list): list-only table utilities ("Invert selection",
                    "Copy z-trace values") for the standard bottom utility slot
        """
        context_menu_list = [
            ("editztracce_act", "Edit z-trace attributes...", "", self.editZtraceAttributes),
            ("smoothztrace_act", "Smooth", "", self.smoothZtrace),
            # Hoisted out of "3D >" alongside the object menu's equivalent (this
            # lab is 3D-heavy). The label gains "3D" because at top level it no
            # longer has the submenu for context.
            ("addto3D_act", "Add to 3D scene", "", self.addZtraceTo3D),
            None,
            {
                "attr_name": "ztracemenu_3D",
                "text": "3D",
                "opts":
                [
                    ("remove3D_act", "Remove from scene", "", self.removeZtrace3D)
                ]
            },
            {
                "attr_name" : "ztracegroup_menu",
                "text": "Group",
                "opts":
                [
                    ("addztracegroup_act", "Add to group...", "", self.addZtraceToGroup),
                    ("removeztracegroup_act", "Remove from group...", "", self.removeZtraceFromGroup),
                    ("removeztraceallgroups_act", "Remove from all groups", "", self.removeZtraceFromAllGroups)
                ]
            },
            ("setztracealignment_act", "Edit alignment...", "", self.editZtraceAlignment),
        ]

        # table utilities, in the slot every list shares
        if list_ops:
            context_menu_list += [None] + list(list_ops)

        context_menu_list += [
            None,
            ("deleteztrace_act", "Delete z-traces", "", self.deleteZtrace)
        ]

        return context_menu_list

    def ztrace_function(fn):
        """Property given to all ztrace actions that are accessible through a context menu.
        
        Handles passing the correct ztraces into the functions.

        All functions must handle their own addition to series_states
        """
        def wrapper(self, *args, **kwargs):
            # get the selected names
            vscroll = None  # scroll bar if object list
            data_table = self.table_manager.hasFocus()

            if isinstance(data_table, ZtraceTableWidget):
                selected_ztraces = data_table.getSelected()
                vscroll = data_table.table.verticalScrollBar() # keep track of scroll bar position
                scroll_pos = vscroll.value()
            
            else:
                selected_ztraces = self.section.selected_ztraces.copy()
            
            # check that conditions are met
            if not selected_ztraces:
                return
            
            # save the data in the field
            self.mainwindow.saveAllData()

            # call function with selected names inserted
            completed = fn(self, selected_ztraces, *args, **kwargs)

            if not completed:
                return
            
            # reset the scroll bar position if applicable
            if vscroll: vscroll.setValue(scroll_pos)

            # call to update ztraces
            self.table_manager.updateZtraces()
            self.mainwindow.seriesModified(True)
            self.generateView()

        return wrapper
    
    @ztrace_function
    def editZtraceAttributes(self, names : list):
        """Edit the name and color of a ztrace."""
        if len(names) > 1:
            notify("Please modify one ztrace at a time.")
            return False
        name = names[0]

        if name not in self.series.ztraces:
            return False
        ztrace = self.series.ztraces[name]

        structure = [
            ["Name:", ("text", name)],
            ["Color:", ("color", ztrace.color)]
        ]
        response, confirmed = QuickDialog.get(self, structure, "Set Attributes")
        if not confirmed:
            return False

        new_name, new_color = response

        if new_name != name and new_name in self.series.ztraces:
            notify("This ztrace already exists.")
            return False

        # save the series state
        self.series_states.addState()

        # modify the ztrace data
        self.series.editZtraceAttributes(name, new_name, new_color)

        return True
    
    @ztrace_function
    def smoothZtrace(self, names : list):
        """Smooth a set of ztraces."""
        structure = [
            ["Smoothing factor:", ("int", 10)],
            [("check", ("Create new ztrace", True))]
        ]
        
        response, confirmed = QuickDialog.get(self, structure, "Smooth Ztrace")
        if not confirmed:
            return False
        
        smooth = response[0]
        newztrace = response[1][0][1]
        
        # save the series state
        self.series_states.addState()
        
        self.series.smoothZtraces(names, smooth, newztrace)

        return True
    
    @ztrace_function
    def addZtraceTo3D(self, names : list):
        """Generate a 3D view of an object"""
        if names:
            self.mainwindow.addTo3D(names, ztraces=True)
        # return nothing -- no need to update anything
    
    @ztrace_function
    def removeZtrace3D(self, names : list):
        """Remove object(s) from the scene."""
        
        if names:
            self.mainwindow.removeFrom3D(obj_names=[], ztraces=names)
            
        # return nothing -- no need to update anything
    
    @ztrace_function
    def addZtraceToGroup(self, names : list):
        """Add objects to a group."""
        # ask the user for the group
        group_name, confirmed = ObjectGroupDialog(self, self.series.ztrace_groups).exec()

        if not confirmed:
            return False
        
        # save the series state
        self.series_states.addState()
        
        for name in names:
            self.series.ztrace_groups.add(group=group_name, obj=name)
            self.series.addLog(name, None, f"Add to group '{group_name}'")
            self.series.modified_ztraces.add(name)

        return True
    
    @ztrace_function
    def removeZtraceFromGroup(self, names : list):
        """Remove objects from a group."""
        # ask the user for the group
        group_name, confirmed = ObjectGroupDialog(self, self.series.ztrace_groups, new_group=False).exec()

        if not confirmed:
            return False
        
        # save the series state
        self.series_states.addState()
        
        for name in names:
            self.series.ztrace_groups.remove(group=group_name, obj=name)
            self.series.addLog(name, None, f"Remove from group '{group_name}'")
            self.series.modified_ztraces.add(name)

        return True
    
    @ztrace_function
    def removeZtraceFromAllGroups(self, names : list):
        """Remove a set of traces from all groups."""
        # save the series state
        self.series_states.addState()
        
        for name in names:
            self.series.ztrace_groups.removeObject(name)
            self.series.addLog(name, None, f"Remove from all object groups")
            self.series.modified_ztraces.add(name)
            
        return True
    
    @ztrace_function
    def editZtraceAlignment(self, names : list):
        """Edit alignment for ztrace(s)."""
        structure = [
            ["Alignment:", ("combo", list(self.section.tforms.keys()))]
        ]
        response, confirmed = QuickDialog.get(self, structure, "Object Alignment")
        if not confirmed:
            return False
        
        # save the series state
        self.series_states.addState()
        
        alignment = response[0]
        if not alignment: alignment = None
        for name in names:
            self.series.setAttr(name, "alignment", alignment, ztrace=True)
            self.series.modified_ztraces.add(name)
            self.series.addLog(name, None, "Edit default alignment")
        
        return True
    
    @ztrace_function
    def deleteZtrace(self, names : list):
        """Delete a set of ztraces."""
        # save the series state
        self.series_states.addState()
        
        self.series.deleteZtraces(names)

        return True
