import os
import time

from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QTextEdit,
)
from PySide6.QtGui import (
    QPainter,
    QCursor,
    QAction,
    QKeySequence,
)
from PySide6.QtCore import (
    QTimer,
    Qt
)

from PyReconstruct.modules.datatypes import Series, Section, Trace, Transform
from PyReconstruct.modules.datatypes.transform import alignment_tform
from PyReconstruct.modules.backend.view import SectionLayer, ZarrLayer
from PyReconstruct.modules.backend.view.image_layer import dropReadAhead
from PyReconstruct.modules.datatypes.section_read_ahead import READ_AHEAD
from PyReconstruct.modules.backend.view.trace_layer import roiBoxBounds, traceInRoiBox
from PyReconstruct.modules.backend.view.roi_follow import (
    SeriesSquares,
    followCenter,
    objectCenters,
    sectionSquares,
)
from PyReconstruct.modules.backend.func import SeriesStates
from PyReconstruct.modules.backend.table import TableManager
from PyReconstruct.modules.gui.utils import notify


class FieldWidgetBase:
    """
    Initialize the defaults and their types.
    Define the generateView function.
    Handle the series states.
    Handle section changes.
    Handle the table manager.
    Handling reloading the view (when section data is changed).
    """
    
    def initAttrs(self, series : Series, mainwindow : QMainWindow):

        self.mainwindow                     = mainwindow
        self.series                         = series

        self.section : Section              = None
        self.b_section : Section            = None

        self.pixmap_dim : tuple             = None
        self.section_layer : SectionLayer   = None

        self.table_manager : TableManager   = None

        # True while an action's undo steps fold into the step before it
        # (autoMerge)
        self.merge_undo_step : bool         = False

        self.propagate_tform : bool         = False
        self.tform_before_change : tuple    = None

        # Session-only visibility snapshot taken by "Hide other objects", so
        # "Restore previous visibility" can put back the state the isolate
        # overwrote. Single level (a second isolate replaces it), never written
        # to the .jser, and reset whenever a new field is built for a series.
        self.visibility_snapshot : dict     = None

        self.focus_mode : bool              = False
        # label over the field naming the focused object; built by FieldWidget
        self.focus_hint : QLabel            = None
        self.hide_trace_layer : bool        = False
        self.show_all_traces : bool         = False

        # The ROI box: only traces whose field bounds touch it are drawn and
        # can be picked. View-only, like hide_trace_layer: nothing is written
        # to the traces, the sections or the series. The center is in field
        # coordinates, so the box keeps its place across section changes; it
        # is None until the first click after the box is turned on. The size
        # (width, height in field units) lasts for the session, never saved.
        self.roi_box_on : bool              = False
        self.roi_box_center : tuple         = None
        self.roi_box_size : tuple           = (5.0, 5.0)
        # The ROI mode tool's options, set by a right-click on its button and
        # kept for the session: whether a drag draws the box (else every press
        # is a click that places a box of the set size), and which point of
        # the box a click places, "center" or "corner" (the upper-left).
        self.roi_box_drag_draws : bool      = True
        self.roi_box_anchor : str           = "center"
        # The object the box follows, or None: on each section the box is
        # centered on it, or placed as on the nearest section with it, which
        # roi_follow_from names (the shown section when it has the object).
        self.roi_follow_name : str          = None
        self.roi_follow_from : int          = None
        # The traces the selection rule last dropped (dropSelectedOutsideRoiBox),
        # the traces made by the operation under way, and how deep the field
        # interactions are nested (field_widget_2_trace.field_interaction)
        self.roi_dropped : list             = []
        self.new_traces : list              = []
        self.interaction_depth : int        = 0
        self.inner_modified : bool          = False
        # Keep whole every object with a trace touching the box on any
        # section: all its traces are shown on every section (roiKeep). The
        # series' traces are read once (SeriesSquares) and an edited object
        # again after an edit: roi_dirty maps a section to the object names to
        # read again there (None: the whole section), or is None to read the
        # series again (a reload, an undo, a refresh).
        self.roi_keep_whole : bool          = False
        self._roi_squares                   = None
        self.roi_dirty                      = None
        self._roi_keep_cache : tuple        = None
        self._roi_keep_now : frozenset      = None
        # A drag in the ROI box mode, in field coordinates: where the press
        # was, and where the pointer is once the press has become a drag
        # (None until then, and no preview is drawn).
        self.roi_box_drag_start : tuple     = None
        self.roi_box_drag_end : tuple       = None
        self.hide_image : bool              = False
        self.blend_sections : bool          = False

        self.hover_columns : list           = None

        self.current_trace : list           = []
        self.current_ztrace: list           = []
        self.moving_traces : list           = None
        self.moving_points : list           = None
        self.moving_flags : list            = None

        # the section a pointer drag began on. A drag hides what it carries in
        # THAT section's temp_hide and can only be committed against it, so the
        # release has to be able to tell whether it is still looking at it.
        self.moving_section                 = None

        self.mouse_mode : int               = 0

        self.is_selecting_traces : bool     = False
        self.is_drawing_rad : bool          = False
        self.is_line_tracing : bool         = False
        self.is_moving_trace : bool         = False
        self.is_panzooming : bool           = False
        self.is_gesturing : bool            = False
        self.is_scissoring : bool           = False
        self.scissors_index : int           = None  # the picked-up trace's place in its contour
        self.is_z_tracing : bool            = False

        self.closed_trace_shape             = "trace"

        self.tracing_trace : Trace          = None
        self.hosted_trace : Trace           = None

        self.mouse_x : int                  = 0
        self.mouse_y : int                  = 0
        self.clicked_x : int                = 0
        self.clicked_y : int                = 0
        self.clicked_trace                  = None
        self.selected_trace                 = None
        self.selected_type                  = None
        self.pointer_press_recorded : bool  = False

        self.lclick : bool                  = False
        self.rclick : bool                  = False
        self.mclick : bool                  = False
        self.press_dropped : bool           = False  # see dropPress

        self.mouse_boundary_timer : QTimer  = None
        self.hover_display_timer : QTimer   = None
        self.hover_display : QTextEdit      = None
        self.displayed_item                 = None

        self.single_click : bool            = False
        self.click_time : float             = None
        self.max_click_time : float         = 0.15
        # widget pixels a trace press may drift and still count as a click
        self.click_tolerance : int          = 4
        self.trace_press_travel : int       = 0
        # a trace tool started a new trace with the press under way, and
        # nothing has ended it since (see traceRelease)
        self.trace_click_pending : bool     = False

        self.timer : QTimer                 = None
        self.time : str                     = None

        self.selected_trace_names : set     = {}
        self.selected_ztrace_names : set    = {}

        self.pencil_r : QCursor             = None
        self.pencil_l : QCursor             = None

        self.edit_flag_event : QAction      = None
    
    def createField(self, series : Series):
        """Re-creates the field widget when a new series is opened.

            Params:
                series (Series): the new series to load
        """
        self.series = series
        self.profile_adjustments = {}
        series.setPassWriteHook(self.refreshPassWrite)

        ## An image read ahead for the series before this one is of no use
        ## to it, and must not outlive it
        dropReadAhead()
        READ_AHEAD.stop()
        if hasattr(self, "section_read_timer"):
            self.section_read_timer.stop()
        else:
            self.section_read_timer = QTimer(self)
            self.section_read_timer.setSingleShot(True)
            self.section_read_timer.timeout.connect(self._readAheadSection)
        self.section_read_target = None

        ## Initialize hover columns from series option
        from PyReconstruct.modules.gui.dialog.hover_columns import HoverColumnsDialog
        default_columns = [(col, True) for col in HoverColumnsDialog.AVAILABLE_COLUMNS]
        self.hover_columns = self.series.getOption("hover_columns") or default_columns

        ## Close manager if exists
        if self.table_manager:
            self.table_manager.closeAll()

        ## Load section
        self.section = self.series.loadSection(self.series.current_section)
        
        ## Load/clear series states
        self.clearStates()
        self.series_states[self.section]  # initialize the current section

        ## Create section view
        self.section_layer = SectionLayer(self.section, self.series)

        ## Create zarr view if applicable
        self.createZarrLayer()
        
        ## Reset b section and layer
        self.b_section = None
        self.b_section_layer = None

        ## Hide/show defaults
        self.focus_mode = False
        self.hide_trace_layer = False
        self.show_all_traces = False
        self.hide_image = False
        self.roi_box_on = False
        self.roi_box_center = None
        self.roi_follow_name = None
        self.roi_follow_from = None
        self._roi_squares = None
        self.roi_dirty = None
        self._roi_keep_cache = None
        self._roi_keep_now = None
        self.roi_box_drag_start = None
        self.roi_box_drag_end = None

        ## Propagate tform defaults
        self.propagate_tform = False
        self.stored_tform = Transform.identity()
        self.propagated_sections = set()
        # (section number, transform before the latest change to it)
        self.tform_before_change = None

        ## Clear copy/paste clipboard
        self.clipboard = []

        ## Create new manager
        self.table_manager = TableManager(
            self.series,
            self.section,
            self.series_states,
            self.mainwindow,
        )

        ## Reset cursor
        self.mouse_mode = 0
        self.setCursor(QCursor(Qt.ArrowCursor))
        
        ## Ensure first section is found
        if self.series.current_section not in self.series.sections:
            self.series.current_section = self.series.sections.keys()[0]

        # GUI defaults
        self.tracing_trace = Trace("TRACE", (255, 0, 255))
        self.status_list = ["Section: " + str(self.series.current_section)]
        
        ## Blend default
        self.blend_sections       = False
        
        ## Click defaults
        self.selected_trace       = None
        self.selected_type        = None
        self.pointer_press_recorded = False
        self.lclick               = False
        self.rclick               = False
        self.mclick               = False
        self.press_dropped        = False

        ## Mouse tool defaults
        self.is_panzooming        = False
        self.is_gesturing         = False
        self.is_line_tracing      = False
        self.is_moving_trace      = False
        self.is_selecting_traces  = False
        self.is_scissoring        = False
        self.scissors_index       = None
        self.closed_trace_shape   = "trace"

        ## Clear selected
        self.selected_trace_names = {}
        self.selected_ztrace_names = {}

        ## Set up timer (stop any timer from a previously opened series first)
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None
        if not self.series.isWelcomeSeries():
            self.time = str(round(time.time()))
            open(os.path.join(self.series.getwdir(), self.time), "w").close()
            # identity beside the heartbeat, so the "series in use" guard can
            # say WHICH app holds the series (stable and Dev install side by
            # side); see modules/datatypes/series_owner.py
            from PyReconstruct.modules.datatypes.series_owner import write_owner
            write_owner(self.series.getwdir())
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.markTime)
            self.timer.start(5000)

        self.generateView()
    
    def createZarrLayer(self):
        """Create a zarr layer."""
        if self.series.zarr_overlay_fp and self.series.zarr_overlay_group:
            self.zarr_layer = ZarrLayer(self.series)
        else:
            self.zarr_layer = None
    
    def resizeWindow(self, pixmap_dim : tuple) -> None:
        """Convert the window to match the proportions of the pixmap.

        Nothing is returned; self.series.window is modified.
        
            Params:
                pixmap_dim (tuple): the w and h of the pixmap view
        """
        # get dimensions of field window and pixmap
        window_x, window_y, window_w, window_h = tuple(self.series.window)
        if window_w == 0: window_w = 1e-3
        if window_h == 0: window_h = 1e-3  # prevent dividing by zero
        pixmap_w, pixmap_h = tuple(pixmap_dim)
        window_ratio = window_w/window_h
        pixmap_ratio = pixmap_w / pixmap_h

        # resize window to match proportions of current geometry
        if abs(window_ratio - pixmap_ratio) > 1e-6:
            # increase the width
            if window_ratio < pixmap_ratio: 
                new_w = window_h * pixmap_ratio
                new_x = window_x - (new_w - window_w) / 2
                window_w = new_w
                window_x = new_x
            # increase the height
            else:
                new_h = window_w / pixmap_ratio
                new_y = window_y - (new_h - window_h) / 2
                window_h = new_h
                window_y = new_y
            self.series.window = [window_x, window_y, window_w, window_h]
    
    def generateView(self, generate_image=True, generate_traces=True, update=True) -> None:
        """Generate the output view.

        Nothing is returned: self.field_pixmap is set with the view.
        
            Params:
                generate_image (bool): True if image should be regenerated
                generate_traces (bool): True if traces should be regenerated
                update (bool): True if view widget should be updated
        """
        ## Resize series window to match view proportions
        self.resizeWindow(self.pixmap_dim)

        ## A redraw follows every selection change, so the ROI box's one
        ## selection rule is kept here; a box that follows an object is
        ## placed first, section by section
        self.dropSelectedOutsideRoiBox()

        ## Calculate scaling
        _, _, window_w, window_h = tuple(self.series.window)
        pixmap_w, pixmap_h = tuple(self.pixmap_dim)
        
        ## Scaling: Screen pixels to image pixels ratio (should be equal)
        x_scaling = pixmap_w / (window_w / self.section.mag)
        y_scaling = pixmap_h / (window_h / self.section.mag)
        
        assert(abs(x_scaling - y_scaling) < 1e-6)
        
        self.scaling = x_scaling

        ## Generate section view
        view = self.section_layer.generateView(
            self.pixmap_dim,
            self.series.window,
            generate_image=generate_image,
            generate_traces=generate_traces,
            hide_traces=self.hide_trace_layer,
            show_all_traces=self.show_all_traces,
            hide_image=self.hide_image,
            focus_on=self.focus_mode,
            roi_box=self.roiBox(),
            roi_keep=self.roiKeep(),
        )

        # blend b section if requested
        if self.blend_sections and self.b_section is not None:
            # generate b section view
            b_view = self.b_section_layer.generateView(
                self.pixmap_dim,
                self.series.window,
                generate_image=generate_image,
                generate_traces=generate_traces,
                hide_traces=self.hide_trace_layer,
                show_all_traces=self.show_all_traces,
                hide_image=self.hide_image,
                focus_on=self.focus_mode,
                roi_box=self.roiBox(),
                roi_keep=self.roiKeep(),
            )
            # overlay a and b sections
            painter = QPainter(view)
            painter.setOpacity(0.5)
            painter.drawPixmap(0, 0, b_view)
            painter.end()
        
        # overlay zarr if requested
        if self.zarr_layer:
            zarr_layer = self.zarr_layer.generateZarrLayer(
                self.section,
                self.pixmap_dim,
                self.series.window
            )
            if zarr_layer:
                painter = QPainter(view)
                if not self.hide_image:
                    painter.setOpacity(0.3)
                painter.drawPixmap(0, 0, zarr_layer)
                painter.end()
        
        self.field_pixmap = view

        # update the scale bar
        if self.mainwindow.mouse_palette:
            self.mainwindow.mouse_palette.setScale()

        self.mainwindow.checkActions()

        # a redraw follows every selection change
        if hasattr(self, "table_manager"):
            self.table_manager.syncSelection(self.section)

        # every focus mode change and every resize ends in a redraw
        self.updateFocusHint()

        if update:
            self.update()

    def roiBox(self) -> tuple:
        """The ROI box as (center x, center y, width, height) in field units,
        or None while it is off or not yet placed."""
        if not self.roi_box_on or self.roi_box_center is None:
            return None
        return (*self.roi_box_center, *self.roi_box_size)

    def placeFollowedRoiBox(self):
        """Center a box that follows an object on it on this section, or as
        on the nearest section with it (backend/view/roi_follow.py). When no
        section has the object (deleted or renamed), the box stays where it
        was, stops following, and a message says so.

        Nothing is decided while the series data is being built again (a
        refresh lets events run, a redraw among them): the box stays where it
        is until the data has every section."""
        name = self.roi_follow_name
        if not self.roi_box_on or name is None:
            return
        if not self.seriesDataComplete():
            return
        placed = followCenter(
            objectCenters(
                self.series, name, self.displayTform, self.section,
                self.heldTraces(),
            ),
            self.section.n,
        )
        if placed is None:
            self.roi_follow_name = None
            self.roi_follow_from = None
            # after the redraw, never in the middle of it
            QTimer.singleShot(0, lambda: notify(
                f"No section has {name} now, so the ROI mode box stopped following it."
            ))
            return
        self.roi_box_center, self.roi_follow_from = placed

    def seriesDataComplete(self) -> bool:
        """Whether the series data has every section of the series. A
        refresh (SeriesData.refresh) empties it, then adds the sections back
        one by one."""
        return len(self.series.data["sections"]) >= len(self.series.sections)

    def heldTraces(self) -> list:
        """The traces a tool holds out of the shown section while it edits
        them: the one Scissors took out of its contour (selected_trace, set
        before the pickup's first redraw), until the cut ends or is canceled.
        Still the section's for the ROI box. tracing_trace is not one: it is
        the palette's template until the pickup has drawn once."""
        if self.is_scissoring and self.selected_type == "trace" and isinstance(self.selected_trace, Trace):
            return [self.selected_trace]
        return []

    def displayTform(self, snum : int):
        """The transform the field draws a section with: the shown section's
        own, else the series alignment's from the series data (None for a
        section the series data does not have)."""
        if snum == self.section.n:
            return self.section.tform
        if snum not in self.series.data["sections"]:
            return None
        return alignment_tform(self.series, snum)

    def roiKeep(self) -> frozenset:
        """The objects the ROI box keeps whole, or None while that option or
        the box is off; found by updateRoiKeep, which every redraw runs."""
        if self.roiBox() is None or not self.roi_keep_whole:
            return None
        if self._roi_keep_now is None:
            self.updateRoiKeep()
        return self._roi_keep_now

    def updateRoiKeep(self) -> None:
        """Find the objects the ROI box keeps whole: each has a trace that
        touches the box where the field draws it, on some section, with a
        followed box placed there as it is drawn there.

        Other sections come from the series' traces (roiKeepSections, kept
        until a box there or the traces change, so paging reuses it). The
        shown section is tested now, with its box and transform as they are:
        its saved traces from the series' traces, and an object with an edit
        not saved yet (a drawn, moved, deleted or held trace) by its traces
        as they are now.
        """
        box = self.roiBox()
        if box is None or not self.roi_keep_whole:
            self._roi_keep_now = None
            return
        squares = self.roiSquares()
        if squares is None:
            # the series data is being built again: keep what was found
            return
        n = self.section.n
        touched = self.roiKeepSections(squares)
        names = {name for name, snums in touched.items() if snums - {n}}
        held = self.heldTraces()
        edited = self.section.getAllModifiedNames() | {t.name for t in held}
        bounds = roiBoxBounds(box)
        names |= squares.touchingOn(n, bounds, self.section.tform, exclude=edited)
        for name in edited - names:
            xmin, ymin, xmax, ymax = sectionSquares(self.section, name, held)
            if (
                (xmin <= bounds[2]) & (xmax >= bounds[0])
                & (ymin <= bounds[3]) & (ymax >= bounds[1])
            ).any():
                names.add(name)
        self._roi_keep_now = frozenset(names)

    def roiDataChanged(self, snum=None, names=None) -> None:
        """Note that the series' traces changed: some objects on one section,
        a whole section (names None), or (snum None) anywhere. Keeping
        objects whole reads them again when next needed."""
        if snum is None or self._roi_squares is None:
            self.roi_dirty = None
            self._roi_squares = None
            self._roi_keep_cache = None
        elif self.roi_dirty is not None:
            if names is None or self.roi_dirty.get(snum, set()) is None:
                self.roi_dirty[snum] = None
            else:
                self.roi_dirty.setdefault(snum, set()).update(names)

    def roiSquares(self):
        """The series' traces for keeping objects whole (SeriesSquares), read
        again where they changed; None while the series data is being built
        again."""
        if self._roi_squares is None:
            if not self.seriesDataComplete():
                return None
            self._roi_squares = SeriesSquares.fromSeries(self.series)
            self._roi_keep_cache = None
            self.roi_dirty = {}
        elif self.roi_dirty:
            if set(self.roi_dirty) - {self.section.n}:
                # an edit on a section not shown: read the series again
                self.roiDataChanged()
                return self.roiSquares()
            names = self.roi_dirty[self.section.n]
            if names is None:
                self._roi_squares.setSection(self.section)
            else:
                self._roi_squares.setObjects(self.section, names)
            self.roi_dirty = {}
        return self._roi_squares

    def roiKeepSections(self, squares) -> dict:
        """For each object that touches the ROI box on a section, the
        sections where it does (SeriesSquares.touching). Found again when the
        series' traces are read again, a box moves (a followed box with its
        object) or the series alignment changes; after an edit of some
        objects, only those objects are tested again."""
        w, h = self.roi_box_size
        if self.roi_follow_name is not None:
            centers = objectCenters(
                self.series, self.roi_follow_name, self.displayTform,
                self.section, self.heldTraces(),
            )
            boxes = {}
            for snum in self.series.sections:
                placed = followCenter(centers, snum)
                if placed is not None:
                    boxes[snum] = roiBoxBounds((*placed[0], w, h))
        else:
            bounds = roiBoxBounds(self.roiBox())
            boxes = {snum: bounds for snum in self.series.sections}
        key = (squares.generation, self.series.alignment, tuple(sorted(boxes.items())))
        cache = self._roi_keep_cache
        if cache is not None and cache[0] == key:
            version, touched = cache[1], cache[2]
            if version == squares.version:
                return touched
            later = [c for c in squares.changes if c[0] > version]
            if all(names is not None for _, _, names in later):
                # only some objects changed, each on one section
                touched = dict(touched)
                for _, snum, names in later:
                    for name in names:
                        hit = squares.touches(snum, name, boxes.get(snum), self.displayTform(snum))
                        snums = set(touched.get(name, ())) - {snum}
                        if hit:
                            snums.add(snum)
                        if snums:
                            touched[name] = frozenset(snums)
                        else:
                            touched.pop(name, None)
                self._roi_keep_cache = (key, squares.version, touched)
                squares.changes = []  # brought up to date; this field reads them alone
                return touched
        touched = squares.touching(boxes, self.displayTform)
        self._roi_keep_cache = (key, squares.version, touched)
        squares.changes = []
        return touched

    def inRoiBox(self, trace : Trace) -> bool:
        """Whether a trace on the current section is inside the ROI box
        (always True while the box is off)."""
        return traceInRoiBox(trace, self.section.tform, self.roiBox(), self.roiKeep())

    def dropSelectedOutsideRoiBox(self) -> list:
        """Deselect the traces outside the ROI box, which are not drawn.

        The box's one selection rule: while it is on, the section's selected
        traces are all inside it. Every way of building the selection (click,
        lasso, Select all, Invert, focus mode, Find, a new trace) ends in a
        redraw, and generateView calls this first.

        A box that follows an object is placed first, from the shown
        section's traces as they are now, and the objects it keeps whole are
        found again (updateRoiKeep), so a trace just drawn, pasted or moved
        inside the box's new place, or into an object it keeps whole, stays
        selected. While a field interaction is under way (a paste, a grid, a
        cut), nothing is placed or dropped: the interaction applies the rule
        once, when it is done.

            Returns:
                (list): the traces that were deselected
        """
        self.roi_dropped = []
        if self.interaction_depth:
            # a field interaction is under way; it applies the rule once it
            # is done (field_widget_2_trace.field_interaction)
            return []
        self.placeFollowedRoiBox()
        self.updateRoiKeep()
        if self.roiBox() is None:
            return []
        selected = self.section.selected_traces
        inside = [t for t in selected if self.inRoiBox(t)]
        if len(inside) == len(selected):
            return []
        dropped = [t for t in selected if t not in inside]
        self.section.selected_traces = inside
        self.roi_dropped = dropped
        return dropped

    def focusHintText(self) -> str:
        """The focus mode label's text, naming the live `focus_act` shortcut."""
        act = getattr(self.mainwindow, "focus_act", None)
        key = act.shortcut().toString(QKeySequence.NativeText) if act is not None else ""
        if key:
            how = f"Press {key} to exit."
        else:
            how = "Use View > Toggle focus mode in the right-click menu to exit."
        return f"Focus: {self.focus_mode}. {how}"

    def updateFocusHint(self) -> None:
        """Show the focus mode label while focus mode is on, centered at the top."""
        hint = getattr(self, "focus_hint", None)
        if hint is None:
            return
        if not self.focus_mode:
            hint.hide()
            return
        text = self.focusHintText()
        if hint.text() != text:
            hint.setText(text)
        # one line when it fits, wrapped to the field's width when it does not
        hint.setWordWrap(False)
        w = hint.sizeHint().width()
        max_w = max(self.width() - 20, 1)
        if w > max_w:
            hint.setWordWrap(True)
            w = max_w
            hint.resize(w, hint.heightForWidth(w))
        else:
            hint.resize(w, hint.sizeHint().height())
        hint.move((self.width() - w) // 2, 10)
        hint.show()
        hint.raise_()
    
    def clearStates(self) -> None:
        """Create/clear the states for each section."""
        self.series_states = SeriesStates(self.series)

    def saveState(self) -> None:
        """Save the current traces and transform.
        
        ALSO updates the lists.
        """
        # An edit made while a scissors cut is open (an arrow key moving the
        # alignment, a paste) is recorded here, and the picked-up trace is
        # outside the section until the cut ends. The state would hold the
        # section without it, so undoing and redoing the edit took the trace
        # out again after a save had put it back. The cut is backed out first,
        # as a save does. A finished cut records its own state here too, and
        # lineRelease clears is_line_tracing before that, so it is left alone.
        self.cancelOpenScissorsCut()

        step = self.series_states.commitSection(
            self.section, merge=getattr(self, "merge_undo_step", False)
        )
        self.showSectionStep(step)

        # notify that the series has been edited
        self.mainwindow.seriesModified(True)
        self.mainwindow.checkActions()

    def undoState(self, redo=False) -> None:
        """Undo last action (switch to last state)."""
        # disable if trace layer is hidden
        if self.hide_trace_layer:
            return

        # end any pending events
        self.endPendingEvents()  # function extended in inherited class
        
        # clear selected straces
        self.section.selected_traces = []
        self.section.selected_ztraces = []
        self.section.selected_flags = []

        step = self.series_states.undoSection(self.section, redo)

        # an undo or redo that moves the section leaves no change to pick up
        # when propagation recording starts
        if step.tform_moved:
            self.tform_before_change = None

        self.showSectionStep(step)
        self.generateView()

    def showSectionStep(self, step) -> None:
        """Show a section edit, undo or redo in the lists and menus, once
        its data work is done (SeriesStates.commitSection, undoSection).

            Params:
                step (SectionStep): what the step changed
        """
        self.table_manager.updateAll(step.objects, step.ztraces)
        # a moved transform moves every trace on the section
        self.roiDataChanged(self.section.n, None if step.tform_moved else step.objects)
        # the Groups menu lists groups from createMenuBar
        if step.groups_changed and hasattr(self.mainwindow, "createMenuBar"):
            self.mainwindow.createMenuBar()
    
    def seriesUndo(self, redo=False) -> None:
        """Undo an action across the series.

            Params:
                redo (bool): True if should redo instead of undo
        """
        # the "Series alignment" submenu and its <name>_alignment_act actions are
        # built from series.alignments at createContextMenus() time, so an undo
        # that adds or removes an alignment leaves the submenu listing a name the
        # sections no longer carry
        alignments_before = set(self.series.alignments)
        groups_before = set(self.series.object_groups.getGroupList())

        series = self.series
        self.series_states.undoState(redo)
        # another series can open at the undo's last progress update. The
        # undo still finished on the series it began on, and the field now
        # holds the new one, which a reload would mark modified
        if self.series is not series:
            return
        self.reload()
        self.table_manager.recreateTables()
        # a series undo can change palette buttons' object defaults (a custom
        # column edit); the field draws from its own copy of the button
        if hasattr(self, "syncTracingDefaults"):
            self.syncTracingDefaults()

        # rebuild only when the set of names actually changed: the submenu is one
        # of ~200 actions createContextMenus() recreates, and most series undos
        # (traces, groups, attributes) leave the alignments alone
        if set(self.series.alignments) != alignments_before:
            self.mainwindow.createContextMenus()

        # the Groups menu, as undoState does: a series undo can bring back a
        # group removed with its last object, and the menu has no row for it
        # until createMenuBar runs again
        if set(self.series.object_groups.getGroupList()) != groups_before:
            if hasattr(self.mainwindow, "createMenuBar"):
                self.mainwindow.createMenuBar()
    
    def swapABsections(self) -> None:
        """Switch the A and B sections.
        
        Called when the user switches between the two currently loaded sections.
        """
        self.section, self.b_section = self.b_section, self.section
        self.section_layer, self.b_section_layer = self.b_section_layer, self.section_layer
        if self.section is not None:
            self.series.current_section = self.section.n
    
    def changeSection(self, new_section_num : int) -> None:
        """Change the displayed section.
        
            Params:
                new_section_num (int): the new section number to display
        """
        ## Dropped while a series transition runs. A section change delivered
        ## from the event loop of an open (its progress window) read the
        ## section from the outgoing series after that series was closed, and
        ## raised FileNotFoundError. No transition changes the section itself.
        if self.mainwindow.seriesTransitionRunning():
            return

        ## Check if requested section exists
        if new_section_num not in self.series.sections:
            return
        
        ## Check if already on section
        if new_section_num == self.series.current_section:
            return
        
        snums = sorted(self.series.sections)
        # Deleting the displayed section leaves no previous position in the
        # new ordering. Treat the replacement section as a jump.
        step = (snums.index(new_section_num) - snums.index(self.section.n)
                if self.section.n in self.series.sections else 0)
        self.section_read_timer.stop()
        self.section_read_target = None
        if abs(step) != 1:
            READ_AHEAD.drop()

        ## The requested section may already be loaded as the B section -- the
        ## A/B flicker asks for exactly that. Swapping is then the whole change
        ## and nothing is read from disk.
        if self.b_section is not None and self.b_section.n == new_section_num:
            self.swapABsections()

        else:
            ## Read the section and build its view BEFORE any field state
            ## moves, because these two lines are the only ones here that can
            ## fail. Both touch the filesystem: the section file, which the OS
            ## may not have finished releasing after the save that precedes
            ## every jump from a list, and whatever image the layer opens.
            ##
            ## This used to run the other way round, swapping first and then
            ## loading. The swap trades `section_layer` for `b_section_layer`,
            ## which is None until the first section change of a session, so
            ## the field spent the whole load with no section layer at all --
            ## and if the load raised, it kept none. `paintText` reads
            ## `section_layer` on every paint event, so from that moment on
            ## every repaint raised `AttributeError: 'NoneType' object has no
            ## attribute 'getTrace'`, each one opening an error window, and
            ## painting is not something a user can stop asking for. Loading
            ## first means a failure leaves the field displaying the section it
            ## was already displaying.
            new_section = self.series.loadSection(new_section_num)
            new_section_layer = SectionLayer(new_section, self.series)

            ## Nothing below this line can fail: the field moves from one whole
            ## state to another.
            self.b_section = self.section
            self.b_section_layer = self.section_layer
            self.section = new_section
            self.section_layer = new_section_layer
            self.series.current_section = new_section_num

            # clear selected traces
            if self.focus_mode:
                obj_traces = [t for t in self.section.tracesAsList() if t.name == self.focus_mode]
                self.section.selected_traces = obj_traces
            else:
                self.section.selected_traces = []

            # the next change is most often one more step the same way:
            # read that section's image while this one is on the screen
            self.readAheadImage(new_section_num - self.b_section.n)

        # create section undo/redo state object if needed
        states = self.series_states[new_section_num]
        if not states.initialized:
            states.initialize(self.section, self.series)
        
        # reload trace list
        self.table_manager.changeSection(self.section)
        
        # propagate transform if requested
        if (self.propagate_tform and
            not self.section.align_locked and
            new_section_num not in self.propagated_sections):
            # A profile copy can process paint events in its progress dialog.
            # Finish the newly loaded layer before opening that dialog.
            self.generateView()
            if not self.prepareProfileAdjustment("alignment"):
                self.setPropagationMode(False)
                self.generateView()
                return
            current_tform = self.section.tform
            new_tform = self.stored_tform * current_tform
            # Replay the recorded delta without recording it again through
            # changeTform, which would compound it on subsequent sections.
            self.section.tform = new_tform
            self.series.addLog(None, self.section.n, "Modify transform")
            self.saveState()
            self.propagated_sections.add(new_section_num)

        # generate view and update status bar
        self.generateView()

        # A jump gives no paging direction. Wait briefly after an adjacent
        # step so held-down keys do not compete with speculative Python work.
        READ_AHEAD.drop()
        if abs(step) == 1:
            index = snums.index(new_section_num) + step
            if 0 <= index < len(snums):
                target = snums[index]
                if self.b_section is None or target != self.b_section.n:
                    self.section_read_target = target
                    self.section_read_timer.start(75)

    def _readAheadSection(self):
        number = self.section_read_target
        if (self.series.closed or self.mainwindow.seriesTransitionRunning()
                or number not in self.series.sections
                or number in self.series._lazy):
            return
        # Lazy stubs require series-owned hydration. Leave those synchronous.
        path = os.path.join(self.series.hidden_dir, self.series.sections[number])
        READ_AHEAD.start(self.series, number, path)

    def readAheadImage(self, direction : int) -> None:
        """Start reading the image of the section one step from this one.

        The read runs on its own thread (ImageLayer.readAhead); the change
        to that section then finds its image decoded.

            Params:
                direction (int): forward (positive) or back (negative) in
                    section order
        """
        if not direction:
            return
        snums = sorted(self.series.sections)
        i = snums.index(self.section.n) + (1 if direction > 0 else -1)
        if 0 <= i < len(snums):
            self.section_layer.readAhead(snums[i])

    def reload(self, clear_states=False) -> None:
        """Reload the section data (used if section files were modified, usually through object list).
        
            Params:
                clear_states (bool): True if ALL undo states should be cleared (rare)
        """
        self.section_read_timer.stop()
        self.section_read_target = None
        READ_AHEAD.drop()

        # the transforms may have been replaced on disk (an import, an undo
        # across the series, sections inserted or reordered), so a change
        # remembered for propagation recording no longer applies
        self.tform_before_change = None

        # an open scissors cut ends here with its trace back: left open across
        # the reload, finishing it would add a second copy beside the one
        # read back from the file
        self.cancelOpenScissorsCut()

        # the series' traces may have changed under the ROI box's kept objects
        self.roiDataChanged()

        # reload the actual sections
        self.section = self.series.loadSection(self.series.current_section)
        self.section_layer.section = self.section
        self.table_manager.changeSection(self.section)
        if self.b_section:
            self.b_section = self.series.loadSection(self.b_section.n)
            self.b_section_layer.section = self.b_section
        # clear all the section states
        if clear_states:
            self.clearStates()
        # clear the selected traces
        self.section.selected_traces = []
        if self.b_section:
            self.b_section.selected_traces = []
        # update the palette
        self.mainwindow.mouse_palette.updateBC()
        
        self.generateView()

        # notify that the series has been modified
        self.mainwindow.seriesModified(True)
    
    def refreshPassWrite(self, written) -> None:
        """Reload the held copies of a section a pass over the files wrote.

        Series.setPassWriteHook calls this right after each write, before
        the next progress update, so the copies match the file even when the
        pass stops part-way. The action saved the field before its pass and
        reloads it after, so nothing unsaved is dropped here.

            Params:
                written (Section): the pass's own copy, just saved
        """
        # a series opened during the pass is the field's now
        if written.series is not self.series:
            return
        # the field's own copy, saved during the pass (the save prompt)
        if written is self.section or written is self.b_section:
            return
        self.roiDataChanged()
        if self.section is not None and self.section.n == written.n:
            self.section = self.series.loadSection(written.n)
            self.section_layer.section = self.section
            self.table_manager.changeSection(self.section)
        if self.b_section is not None and self.b_section.n == written.n:
            self.b_section = self.series.loadSection(written.n)
            self.b_section_layer.section = self.b_section

    def reloadImage(self) -> None:
        """Reload the section images (used if transform or image source is modified)."""
        self.section_layer.loadImage()
        if self.b_section is not None:
            self.b_section_layer.loadImage()
        self.generateView()
    
    def openList(self, list_type : str, selected_only=False):
        """Open a list.
        
            Params:
                list_type (str): object, trace, section, ztrace, or flag
                selected_only (bool): True to open an object list that shows
                    only the objects with a selected trace
        """
        self.table_manager.newTable(list_type, self.section, selected_only=selected_only)
    
    def updateData(self) -> None:
        """Update the series data object and the tables, and clear the
        Section and Series tracking they read."""
        # update the series data tracker
        self.series.data.updateSection(
            self.section,
            update_traces=True,
            all_traces=False,
        )

        self.table_manager.updateAll()
        self.roiDataChanged(self.section.n)
        self.section.clearTracking()
        self.series.clearTracking()
        
    def update(self) -> None: ...
