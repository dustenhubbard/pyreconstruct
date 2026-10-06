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
from PyReconstruct.modules.backend.view import SectionLayer, ZarrLayer
from PyReconstruct.modules.backend.func import SeriesStates
from PyReconstruct.modules.backend.func.state_manager import (
    dropEmptiedGroups, forgetHostLinks, hostLinks, recordDroppedHostLinks,
)
from PyReconstruct.modules.backend.table import TableManager


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

        self.mouse_boundary_timer : QTimer  = None
        self.hover_display_timer : QTimer   = None
        self.hover_display : QTextEdit      = None
        self.displayed_item                 = None

        self.single_click : bool            = False
        self.click_time : float             = None
        self.max_click_time : float         = 0.15

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
            focus_on=self.focus_mode
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
                focus_on=self.focus_mode
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
        # save the current state
        section_states = self.series_states[self.series.current_section]
        section_states.addState(self.section, self.series)

        # update the data/tables
        groups_before = set(self.series.object_groups.getGroupList())
        names = section_states.current_state.getModifiedContours()
        objects_before = {n for n in names if n in self.series.data["objects"]}
        links_before = hostLinks(self.series, names)
        self.updateData()
        recordDroppedHostLinks(self.series, links_before)
        forgetHostLinks(self.series, {
            n for n in names
            if n not in objects_before and n in self.series.data["objects"]
        })

        # updateData deletes an object whose last trace the action took, and
        # its groups with it; their visibility entries go too, so the Groups
        # menu loses the row. The state keeps each value for its undo.
        dropped = dropEmptiedGroups(self.series, groups_before)
        section_states.current_state.undo_group_viz = dict(dropped)
        if dropped and hasattr(self.mainwindow, "createMenuBar"):
            self.mainwindow.createMenuBar()

        # check if a series undo/redo has been overwritten
        self.series_states.checkOverwrite(self.section.n)

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

        # get the last undo state
        groups_before = set(self.series.object_groups.getGroupList())
        tform_before = self.section.tform.copy()
        section_states = self.series_states[self.section.n]
        undos_before = len(section_states.undo_states)
        redos_before = len(section_states.redo_states)
        section_states.restored_alignments = {}
        self.series_states.undoSection(self.section, redo)

        # an undo or redo that moves the section leaves no change to pick up
        # when propagation recording starts
        if not self.section.tform.equals(tform_before):
            self.tform_before_change = None

        # update the data/tables
        links_before = hostLinks(self.series, self.section.getAllModifiedNames())
        self.updateData()
        recordDroppedHostLinks(self.series, links_before)

        # updateData gave each object the step recreated the current
        # alignment; put back the pin the object had, and show it in the lists
        pinned = [
            name for name in section_states.restored_alignments
            if name in self.series.data["objects"]
        ]
        for name in pinned:
            self.series.setAttr(
                name, "alignment", section_states.restored_alignments[name]
            )
        if pinned:
            self.table_manager.updateObjects(pinned)
        section_states.restored_alignments = {}

        # updateData deletes an object whose last trace the step took, and
        # its groups with it; their visibility entries go too. The dropped
        # values also go to the state whose opposite step brings the groups
        # back: an undo's to the state it put on the redo stack, a redo's to
        # the state it redid. Replaced every time, even when the step empties
        # nothing: a value left from an earlier step of the same state no
        # longer describes it.
        dropped = dropEmptiedGroups(self.series, groups_before)
        if not redo and len(section_states.redo_states) > redos_before:
            section_states.redo_states[-1].group_viz = dict(dropped)
        elif redo and len(section_states.undo_states) > undos_before:
            section_states.current_state.undo_group_viz = dict(dropped)

        # A redo can bring back a group that no object held a moment ago (the
        # object snapshot in state_manager), and the Groups menu lists groups
        # from createMenuBar. Rebuild it only when the set of groups changed.
        if set(self.series.object_groups.getGroupList()) != groups_before:
            if hasattr(self.mainwindow, "createMenuBar"):
                self.mainwindow.createMenuBar()
        
        self.generateView()
    
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

        self.series_states.undoState(redo)
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
        ## Check if requested section exists
        if new_section_num not in self.series.sections:
            return
        
        ## Check if already on section
        if new_section_num == self.series.current_section:
            return
        
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
    
    def reload(self, clear_states=False) -> None:
        """Reload the section data (used if section files were modified, usually through object list).
        
            Params:
                clear_states (bool): True if ALL undo states should be cleared (rare)
        """
        # the transforms may have been replaced on disk (an import, an undo
        # across the series, sections inserted or reordered), so a change
        # remembered for propagation recording no longer applies
        self.tform_before_change = None

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
    
    def updateData(self, clear_tracking=True) -> None:
        """Update the series data object and the tables.
        
            Params:
                clear_tracking (bool): True if tracking vars in Section and Series should be cleared after they are checked
        """
        # update the series data tracker
        self.series.data.updateSection(
            self.section, 
            update_traces=True,
            all_traces=False
        )

        self.table_manager.updateAll(clear_tracking)
        
    def update(self) -> None: ...
