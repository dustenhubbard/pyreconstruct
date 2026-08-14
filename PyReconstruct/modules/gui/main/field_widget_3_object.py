from .context_menu_list import get_context_menu_list_obj

from PySide6.QtWidgets import (
    QInputDialog,
    QMessageBox,
)

from PyReconstruct.modules.datatypes import Transform
from PyReconstruct.modules.gui.dialog import (
    QuickDialog,
    TraceDialog,
    ShapesDialog,
    ObjectGroupDialog,
    MalformedContoursDialog,
)
from PyReconstruct.modules.gui.popup import (
    TextWidget,
)
from PyReconstruct.modules.gui.utils import (
    notify,
    notifyConfirm,
)
from PyReconstruct.modules.gui.table import (
    HistoryTableWidget,
    ObjectTableWidget,
)


from .field_widget_2_trace import FieldWidgetTrace


def object_color_seed(series_data, obj_names : list):
    """What the color swatch should show for ``obj_names``, series-wide.

    Returns ``(color, mixed)``. ``color`` is the selection's one agreed
    trace color, or the PREDOMINANT color (most traces; ties broken by the
    color triple, so the answer is stable across opens) when the traces
    disagree, or None when the selection has no traces at all. ``mixed`` is
    True exactly when more than one distinct color is present, which the
    swatch renders as a diagonal split (predominant color against blank) so
    the user is keyed into the discrepancy before deciding to repaint.

    Seed for the object attributes dialog. The swatch went unseeded for
    years and every color-bearing object opened on a gray swatch and a
    white-seeded picker; reported twice as "the swatch is blank even though
    the object has a color".

    Series-wide, deliberately: a first cut answered from the open section
    only, and click testing caught the gap the same day it was built (a
    trace recolored on one section, the dialog opened from an adjacent
    section, no split shown). ``SeriesData`` carries each trace's color for
    exactly this reason, so the answer costs no section load. Display only:
    the dialog returns color None unless the picker was actually used (see
    ``TraceDialog.exec``), so a seeded-then-untouched OK cannot repaint an
    object whose minority traces hold different colors.
    """
    counts = {}
    for obj_name in obj_names:
        for color, n in series_data.getColorCounts(obj_name).items():
            counts[color] = counts.get(color, 0) + n
    if not counts:
        return None, False
    predominant = max(counts, key=lambda c: (counts[c], c or ()))
    return predominant, len(counts) > 1


class FieldWidgetObject(FieldWidgetTrace):
    """
    OBJECT FUNCTIONS
    ----------------
    All field functions associated with modifying objects.
    """

    def getObjMenu(self, list_ops=None):
        """Get the context menu list for modifying objects.

            Params:
                list_ops (list): list-only table utilities for the object
                    list's bottom utility slot (the field passes none)
        """
        return get_context_menu_list_obj(self, list_ops=list_ops)

    # repeated code that individual functions might need to handle:
    #  - any series_states handling
    #  - updating the host tree of an object
    #  - updating any other related objects that are not selected
    #  - refreshing the entire table
    def object_function(update_objects: bool, reload_field: bool):
        """Wrapper for functions on objects that are accessible through both the field and the object list.
        
        Handles determining the object names to pass to its functions and saving the mainwindow data.
        
        Handles reloading and updating the objects in the tables.
        """
        def decorator(fn):
            def wrapper(self, *args, **kwargs):

                ## Get selected names
                vscroll = None  # scroll bar if object list
                data_table = self.table_manager.hasFocus()

                if isinstance(data_table, ObjectTableWidget):
                    selected_names = data_table.getSelected()
                    vscroll = data_table.table.verticalScrollBar()  # track scroll bar position
                    scroll_pos = vscroll.value()
                
                else:
                    selected_names = list(
                        set(t.name for t in self.section.selected_traces)
                    )
                    
                ## If no selected objects
                if not selected_names:
                    return
                
                ## Check for locked objects
                if update_objects:
                    for n in selected_names:
                        if self.series.getAttr(n, "locked"):
                            notify(
                                "Cannot modify locked objects.\n"
                                "Please unlock before modifying."
                            )
                            return
                
                # save the data in the field
                self.mainwindow.saveAllData()

                # call function with selected names inserted
                completed = fn(self, selected_names, *args, **kwargs)

                if not completed:
                    return

                # call to update objects
                if update_objects:
                    self.table_manager.updateObjects(selected_names)
                    self.mainwindow.seriesModified(True)
                
                # reset the scroll bar position if applicable
                if vscroll: vscroll.setValue(scroll_pos)

                if reload_field:
                    self.reload()
                    self.mainwindow.seriesModified(True)
            
            return wrapper
        
        return decorator
    
    def getSingleName(self, obj_names : list):
        """Check that the list of objects has only one object and return it."""
        if len(obj_names) == 0:
            return
        elif len(obj_names) == 1:
            return obj_names[0]
        else:
            notify("Please select only one object for this action.")
            return

    @object_function(update_objects=True, reload_field=True)
    def editAttributes(self, obj_names : list):
        """Edit the name of object(s) in the entire series."""
        
        ## Query user for new object name
        ##
        ## tags_displayed records whether the dialog is showing this selection's
        ## real tags. It decides, further down, whether the set coming back is a
        ## replacement or an addition: a set that was displayed and edited is the
        ## user's intended final list (and is the only way a tag can be removed),
        ## while a field that started blank for lack of a single value to show
        ## cannot express a replacement without discarding tags the user never
        ## saw.
        if len(obj_names) == 1:
            displayed_name = obj_names[0]
            tags = self.series.data.getTags(obj_names[0])
            tags_displayed = True
        else:
            displayed_name = None
            tags=None
            tags_displayed = False

        displayed_color, color_mixed = object_color_seed(self.series.data, obj_names)

        response, confirmed = TraceDialog(
            self,
            name=displayed_name,
            color=displayed_color,
            color_mixed=color_mixed,
            tags=tags,
            is_obj_list=True
        ).exec()

        if not confirmed:
            return False
        
        attr_trace, sections = response

        ## Modify object on every section
        t = attr_trace

        name, color, tags, mode = (
            t.name, t.color, t.tags, t.fill_mode
        )

        # `object_function` cleared the selected objects; the name the user
        # typed is a different object and nothing has checked it. Renaming onto
        # it merges the whole selection into it on every section it appears on,
        # which is the widest way to add traces to a locked object.
        if self.refuseLockedDestination(name):
            return False

        self.series.editObjectAttributes(
            obj_names,
            name,
            color,
            tags,
            mode,
            sections,
            series_states=self.series_states,
            add_tags=not tags_displayed,
        )

        ## Decorator will not know to update new name and host trees if name is changed
        if name:
            self.table_manager.updateObjects(
                self.series.host_tree.getObjToUpdate([name] + obj_names)
            )
                
        return True

    @object_function(update_objects=True, reload_field=True)
    def reapplyAutosegColors(self, obj_names : list):
        """Recolor selected objects with the current palette + seed.

        The menu row reads "Reapply custom color palette to existing objects..." (renamed 2026-08-12: the
        action colors any name, not only autoseg ones); the method keeps its
        historical name because nothing user-facing hangs on it. Confirms first
        because it discards the objects' existing colors. Locked objects are
        blocked by the object_function wrapper (update_objects=True), exactly
        as any other bulk attribute edit; a single series undo restores every
        prior color. The series-wide sibling, which SKIPS locked objects
        instead, is MainWindow.recolorAllObjectsFromPalette.
        """
        n = len(obj_names)
        s = "s" if n != 1 else ""
        confirmed = notifyConfirm(
            f"Recolor {n} selected object{s} using the current palette "
            "and seed?\n\n"
            "This replaces the objects' existing colors. You can undo it.",
            yn=True,
        )
        if not confirmed:
            return False

        self.series.reapplyAutosegColors(
            obj_names,
            series_states=self.series_states,
        )
        return True

    @object_function(update_objects=True, reload_field=True)
    def smoothObject(self, obj_names: list):
        """Smooth object traces."""

        self.series_states.addState()

        malformed = self.series.smoothObject(
            obj_names,
            series_states=self.series_states
        )

        if malformed:

            # surface the skipped contours in a dialog with enough detail to
            # track them down; double-clicking a row focuses the field on it
            self.malformed_contours_dialog = MalformedContoursDialog(
                self.mainwindow,
                malformed,
                navigate=self.focusMalformedContour,
                delete=self.deleteMalformedContours,
            )
            self.malformed_contours_dialog.show()

        return True

    def focusMalformedContour(self, section_num: int, obj_name: str, index: int = 0):
        """Focus the field on a trace reported in the malformed dialog."""

        # switch to the trace's section first (changeSection finalizes any
        # in-progress trace and saves field data before the switch), then frame
        # the individual trace the way the Trace List does, rather than the
        # whole object
        self.mainwindow.changeSection(section_num)
        self.mainwindow.field.findTrace(obj_name, index)
        self.mainwindow.field.setFocus()

    def deleteMalformedContours(self, records: list) -> list:
        """Delete malformed contours chosen in the dialog.

        Mirrors the object-list delete/reload path: refuse locked objects, save
        field data, delete via the series (whose enumerateSections records the
        undo state), then refresh the tables and field. Returns the records
        actually deleted so the dialog can prune exactly those rows.
        """
        if not records:
            return []

        # like the object_function delete path, never modify locked objects
        names = {r["name"] for r in records}
        if any(self.series.getAttr(n, "locked") for n in names):
            notify(
                "Cannot delete contours of locked objects.\n"
                "Please unlock before deleting."
            )
            return []

        # persist field edits to section data before reloading sections
        self.mainwindow.saveAllData()

        deleted = self.series.deleteMalformedTraces(
            records,
            series_states=self.series_states,
        )

        if deleted:
            self.table_manager.updateObjects({r["name"] for r in deleted})
            self.reload()
            self.mainwindow.seriesModified(True)

        missed = len(records) - len(deleted)
        if missed:
            were = "was" if missed == 1 else "were"
            notify(
                f"{missed} of {len(records)} listed contour(s) {were} not "
                "found and could not be deleted — they may have been changed "
                "or removed since smoothing."
            )

        return deleted

    def deleteDifferentlyNamedDuplicates(self, choices: list) -> list:
        """Delete the unkept trace of each cross-name duplicate pair chosen.

        The delete callback behind the pairs list's "Delete unselected". Each
        choice is a ``(record, keep)`` tuple naming which of the pair's two
        traces to keep; the other one goes. Mirrors deleteMalformedContours:
        save field data, delete through the series (whose enumerateSections
        records the undo state), then refresh the tables and field. Returns the
        choices actually applied so the dialog can prune exactly those rows.

        Locked objects keep their traces. Series.deleteDifferentlyNamedDuplicates
        is the guard that makes that true -- it re-checks the lock itself, so a
        pair surfaced by a scan run with "check locked traces" on cannot be
        resolved by deleting from the locked side. This layer only says so.
        """
        if not choices:
            return []

        # name the objects that would lose a trace, so a refusal can explain
        # itself; the series refuses them again regardless of what is said here
        locked_names = set()
        locked_rows = 0
        for record, keep in choices:
            name = record["other_name"] if keep == "first" else record["name"]
            if self.series.getAttr(name, "locked"):
                locked_names.add(name)
                locked_rows += 1
        if locked_names:
            notify(
                "Cannot delete traces of locked objects:\n"
                + ", ".join(sorted(locked_names))
                + "\n\nPlease unlock before deleting. Any other rows you "
                "chose will still be applied."
            )

        # persist field edits to section data before reloading sections
        self.mainwindow.saveAllData()

        applied = self.series.deleteDifferentlyNamedDuplicates(
            choices,
            series_states=self.series_states,
        )

        if applied:
            names = set()
            for record, keep in applied:
                names.add(record["name"])
                names.add(record["other_name"])
            self.table_manager.updateObjects(names)
            self.reload()
            self.mainwindow.seriesModified(True)

        # a row can go unapplied because its object is locked (reported above)
        # or because the trace is no longer where the scan saw it
        missed = len(choices) - len(applied) - locked_rows
        if missed > 0:
            were = "was" if missed == 1 else "were"
            notify(
                f"{missed} of the traces you chose to delete {were} not found "
                "and could not be deleted — they may have been changed or "
                "removed since the scan."
            )

        return applied

    @object_function(update_objects=True, reload_field=False)
    def editComment(self, obj_names : list):
        """Edit the comment of the object."""
        ## Show the selection's comment whenever there is a single one to show,
        ## which for more than one object means they all agree. When they
        ## disagree there is nothing to display, and a blank field then means
        ## "no value chosen", NOT "clear the comment". Writing it back
        ## unconditionally erased the comment of every selected object, and it
        ## did so even when they all agreed, because the field was blanked on
        ## selection size alone rather than on the values.
        existing = {self.series.getAttr(name, "comment") for name in obj_names}
        if len(existing) == 1:
            comment = existing.pop() or ""
            mixed = False
        else:
            comment = ""
            mixed = True

        new_comment, confirmed = QInputDialog.getText(
            self,
            "Object Comment",
            "Comment:",
            text=comment
        )
        if not confirmed:
            return False

        if mixed and not new_comment:
            return False  # nothing chosen, so leave every comment as it was

        self.series_states.addState()

        for obj_name in obj_names:
            self.series.setAttr(obj_name, "comment", new_comment)
            self.series.addLog(obj_name, None, "Edit object comment")

        return True        

    @object_function(update_objects=True, reload_field=False)
    def editAlignment(self, obj_names : list):
        """Edit alignment for object(s)."""
        structure = [
            ["Alignment:", ("combo", list(self.mainwindow.field.section.tforms.keys()))]
        ]
        response, confirmed = QuickDialog.get(self, structure, "Object Alignment")
        if not confirmed:
            return False
        
        self.series_states.addState()
        
        alignment = response[0]
        if not alignment: alignment = None
        for obj_name in obj_names:
            self.series.setAttr(obj_name, "alignment", alignment)
            self.series.addLog(obj_name, None, "Edit default alignment")
        
        self.table_manager.refresh()

        return True
    
    @object_function(update_objects=True, reload_field=True)
    def editRadius(self, obj_names : list):
        """Modify the radius of the trace on an entire object."""
        new_rad, confirmed = QInputDialog.getText(
            self, 
            "Object Trace Radius",
            "Enter the new radius:",
        )
        if not confirmed:
            return False

        try:
            new_rad = float(new_rad)
        except ValueError:
            return False
        
        if new_rad <= 0:
            return False
        
        for name in obj_names:
            a = self.series.getAttr(name, "alignment")
            if a and a != self.series.alignment:
                response = QMessageBox.question(
                    self,
                    "Alignment Conflict",
                    "The field alignment does not match the object alignment.\nWould you like to continue?",
                    buttons=(
                        QMessageBox.Yes |
                        QMessageBox.No 
                    )
                )
                if response != QMessageBox.Yes:
                    return False
                
        # iterate through all sections
        self.series.editObjectRadius(
            obj_names,
            new_rad,
            self.series_states
        )

        return True
    
    @object_function(update_objects=True, reload_field=True)
    def editShape(self, obj_names : list):
        """Modify the shape of the traces on an entire object."""
        new_shape, confirmed = ShapesDialog(self).exec()
        if not confirmed:
            return False

        # iterate through all sections
        self.series.editObjectShape(
            obj_names,
            new_shape,
            self.series_states
        )

        return True
    
    @object_function(update_objects=True, reload_field=True)
    def hideObj(self, obj_names : list, hide=True):
        """Edit whether or not an object is hidden in the entire series.
        
            Params:
                hide (bool): True if the object should be hidden
        """
        # iterate through sections and hide the traces
        self.series.hideObjects(obj_names, hide, self.series_states)

        return True

    # update_objects=False so the decorator does NOT run its locked-check on the
    # selection (the SELECTED objects are the ones being kept, not modified) and
    # does not refresh the wrong rows -- both are handled against the complement
    # below.
    @object_function(update_objects=False, reload_field=True)
    def hideOtherObjects(self, obj_names : list):
        """Isolate the selected object(s): hide every OTHER object throughout the
        whole series, so the isolation persists as sections change.

        Locked objects in the complement are hidden too -- locking guards edits
        and quantification, not visibility. An empty selection is a no-op (the
        decorator returns before we get here), so this can never blank the series.

            Params:
                obj_names (list): the objects to keep visible (object-list
                    selection, or the objects owning the field's selected traces)
            Returns:
                (bool): True if any object was hidden
        """
        keep = set(obj_names)
        others = [name for name in self.series.data["objects"] if name not in keep]
        if not others:  # everything is already selected -> nothing to hide
            return False

        # Record the whole series' visibility BEFORE isolating, so "Restore
        # previous visibility" can put back deliberate hides. Whole series, not
        # just the complement, because the command's name promises the state as
        # it was: a hide made to the KEPT object while isolated has to come out
        # too. Single level -- a second isolate replaces this, there is no stack.
        # Session-only: nothing about it is written to the .jser.
        self.visibility_snapshot = self.series.snapshotObjectVisibility(
            list(self.series.data["objects"].keys())
        )

        self.series.hideObjects(others, True, self.series_states)
        self.table_manager.updateObjects(others)

        return True

    def hideAllObjects(self):
        """Hide all objects: hide every object throughout the whole series.

        The volume-wide complement of "Show all objects"; undoable series-wide,
        like the object hide itself. Locked objects are hidden too -- locking
        guards edits and quantification, not visibility.
        """
        all_names = list(self.series.data["objects"].keys())
        if not all_names:
            return
        self.mainwindow.saveAllData()
        self.series.hideObjects(all_names, True, self.series_states)
        self.table_manager.updateObjects(all_names)
        self.mainwindow.seriesModified(True)
        self.reload()

    def unhideAllObjects(self):
        """Unhide all objects: unhide every object throughout the whole series.

        The volume-wide complement of "Hide all objects"; undoable series-wide,
        like the object hide itself. Locked objects are unhidden too -- locking
        guards edits and quantification, not visibility.

        This is NOT the restore for "Hide other objects", though it used to be
        described that way. It unhides everything, which discards every
        deliberate hide the user made before isolating; "Restore previous
        visibility" is the command that puts those back.
        """
        all_names = list(self.series.data["objects"].keys())
        if not all_names:
            return
        self.mainwindow.saveAllData()
        self.series.hideObjects(all_names, False, self.series_states)
        self.table_manager.updateObjects(all_names)
        self.mainwindow.seriesModified(True)
        self.reload()

    def restorePreviousVisibility(self):
        """Put visibility back to what it was just before the last isolate.

        "Hide other objects" hides every other object series-wide, and had no
        inverse: the only way back was "Unhide all objects", which unhides
        everything and so throws away every hide the user had made on purpose
        before isolating. This replays the per-trace hidden flags recorded at the
        moment of the isolate (Series.snapshotObjectVisibility), so an object the
        user had hidden stays hidden and everything else comes back.

        SINGLE LEVEL, by design. A second isolate overwrites the snapshot rather
        than pushing onto a stack, so this always means "before the most recent
        isolate" and never needs a history to reason about.

        The snapshot is consumed: after a restore there is nothing left to
        restore, and the action disables itself again (MainWindow.checkActions
        for the field menu, ObjectTableWidget.contextMenuEvent for the object
        list). Undoing the restore is Ctrl+Z, which works because the restore
        goes through the same series_states machinery as every other
        volume-wide visibility change.

        With no snapshot the command is unreachable, so the guard here is a
        backstop rather than the mechanism.

        Locked objects are restored like any other -- locking guards edits and
        quantification, not visibility.
        """
        snapshot = self.visibility_snapshot
        if not snapshot:
            return
        self.mainwindow.saveAllData()
        self.series.restoreObjectVisibility(snapshot, self.series_states)
        self.visibility_snapshot = None
        self.table_manager.updateObjects(list(snapshot.keys()))
        self.mainwindow.seriesModified(True)
        self.reload()

    @object_function(update_objects=False, reload_field=False)
    def addTo3D(self, obj_names : list):
        """Generate a 3D view of an object"""
        self.mainwindow.addTo3D(obj_names)
    
    @object_function(update_objects=False, reload_field=False)
    def remove3D(self, obj_names : list):
        """Remove object(s) from the scene."""
        self.mainwindow.removeFrom3D(obj_names)

    @object_function(update_objects=False, reload_field=False)
    def exportAs3D(self, obj_names : list, export_type):
        """Export 3D objects."""
        self.mainwindow.exportAs3D(obj_names, export_type)

    @object_function(update_objects=False, reload_field=False)
    def export3DData(self, obj_names: list):
        """Export quantitative data from 3D meshes."""
        self.mainwindow.export3DData(obj_names)
        
    @object_function(update_objects=True, reload_field=False)
    def addToGroup(self, obj_names : list, log_event=True):
        """Add objects to a group."""

        obj_groups = self.series.object_groups
        starting_groups = obj_groups.getGroupList()
        
        # ask the user for the group
        group_name, confirmed = ObjectGroupDialog(self, obj_groups).exec()

        if not confirmed:
            return False
        
        self.series_states.addState()
        
        for name in obj_names:
            
            obj_groups.add(group=group_name, obj=name)
            
            if log_event:
                self.series.addLog(
                    name, None, f"Add to group '{group_name}'"
                )
        
            ## Update series visibility
            if group_name not in starting_groups:
                self.series.groups_visibility[group_name] = True

                ## Update menubar
                self.mainwindow.createMenuBar()

        return True
    
    @object_function(update_objects=True, reload_field=False)
    def removeFromGroup(self, obj_names : list, log_event=True):
        """Remove objects from a group."""
        # ask the user for the group

        obj_groups = self.series.object_groups
        starting_groups = obj_groups.getGroupList()
        
        group_name, confirmed = ObjectGroupDialog(
            self, obj_groups, new_group=False
        ).exec()

        if not confirmed:
            return False
        
        self.series_states.addState()

        for name in obj_names:
            
            obj_groups.remove(group=group_name, obj=name)
            
            if log_event:
                self.series.addLog(
                    name, None, f"Remove from group '{group_name}'"
                )

            ## Update group visibility
            if group_name not in obj_groups.getGroupList():
                del self.series.groups_visibility[group_name]
            
                ## Create menubar
                self.mainwindow.createMenuBar()

        return True

    @object_function(update_objects=True, reload_field=False)    
    def removeFromAllGroups(self, obj_names : list, log_event=True):
        """Remove a set of traces from all groups."""
        self.series_states.addState()

        obj_groups = self.series.object_groups
        starting_groups = obj_groups.getGroupList()
        
        for name in obj_names:
            
            obj_groups.removeObject(name)
            
            if log_event:
                self.series.addLog(
                    name, None, f"Remove from all object groups"
                )

        ## Update group visibility
        group_diffs = set(starting_groups) - set(obj_groups.getGroupList())
        if group_diffs:

            ## Loop over each group that differs and rm from group viz
            for diff in group_diffs:
                del self.series.groups_visibility[diff]
            
            ## Update menubar
            self.mainwindow.createMenuBar()

        return True

    @object_function(update_objects=True, reload_field=True)    
    def removeAllTags(self, obj_names : list):
        """Remove all tags from all traces on selected objects."""    
        # iterate through all the sections
        self.series.removeAllTraceTags(obj_names, self.series_states)

        return True
    
    @object_function(update_objects=False, reload_field=False)
    def viewHistory(self, obj_names : list):
        """View the history for a set of objects."""
        HistoryTableWidget(self.series.getFullHistory(), self.mainwindow, obj_names)
    
    @object_function(update_objects=False, reload_field=True)
    def createZtrace(self, obj_names : list, cross_sectioned=True):
        """Create a ztrace from selected objects."""
        self.series_states.addState()

        for name in obj_names:
            self.series.createZtrace(name, cross_sectioned)
        
        # manual call to update ztraces
        self.mainwindow.field.table_manager.updateZtraces()

        return True

    @object_function(update_objects=True, reload_field=True)
    def deleteObjects(self, obj_names : list):
        """Delete an object from the entire series."""
        # get the objects that will require updating once deleted (include hosted objects)
        modified_objs = self.series.host_tree.getObjToUpdate(obj_names)

        # delete the object on every section
        self.series.deleteObjects(obj_names, self.series_states)

        # update the dictionary data and tables
        self.table_manager.updateObjects(modified_objs)

        return True
    
    @object_function(update_objects=True, reload_field=True)
    def copyObjects(self, obj_names: list):
        """Make copies of object(s)."""

        self.series_states.addState()

        series_states = self.mainwindow.field.series_states
        copies = self.series.copyObjects(obj_names, series_states)

        ## Update dictionary data and tables
        self.table_manager.updateObjects(copies)

        return True

    @object_function(update_objects=False, reload_field=False)
    def edit3D(self, obj_names : list):
        """Edit the 3D options for an object or set of objects."""
        # check for object names and opacities
        type_3D = self.series.getAttr(obj_names[0], "3D_mode")
        opacity = self.series.getAttr(obj_names[0], "3D_opacity")
        for name in obj_names[1:]:
            new_type = self.series.getAttr(name, "3D_mode")
            new_opacity = self.series.getAttr(name, "3D_opacity")
            if type_3D != new_type:
                type_3D = None
            if opacity != new_opacity:
                opacity = None
        
        structure = [
            ["3D Type:", ("combo", ["surface", "spheres", "contours"], type_3D)],
            ["Opacity (0-1):", ("float", opacity, (0,1))]
        ]
        response, confirmed = QuickDialog.get(self, structure, "3D Object Settings")
        if not confirmed:
            return False
        
        new_type, new_opacity = response

        self.series_states.addState()

        # set the series settings
        for name in obj_names:
            if new_type:
                self.series.setAttr(name, "3D_mode", new_type)
            if new_opacity is not None:
                self.series.setAttr(name, "3D_opacity", new_opacity)
        
        # if this object exists in the 3D scene, update its opacity
        if self.mainwindow.viewer:
            for name in obj_names:
                scene_obj = self.mainwindow.viewer.plt.objs.search(
                    name,
                    "object",
                    self.series.jser_fp
                )
                ## Guard the opacity the same way the setAttr above does. A
                ## blank field is "no value chosen", and passing it through
                ## stored None on SceneObject.alpha, after which the 3D scene's
                ## opacity-increment shortcut raised on None + i and a saved
                ## scene recorded "alpha": None.
                if scene_obj and new_opacity is not None:
                    scene_obj.setAlpha(new_opacity)
                    
        self.mainwindow.seriesModified(True)
        
        return True
    
    @object_function(update_objects=True, reload_field=False)
    def bulkCurate(self, names : list, curation_status : str):
        """Set the curation status for multiple selected objects.
        
            Params:
                curation_status (str): "", "Needs curation" or "Curated"
        """
        # prompt assign to
        if curation_status == "Needs curation":
            assign_to, confirmed = QInputDialog.getText(
                self,
                "Assign to",
                "Assign curation to username:\n(press enter to leave blank)"
            )
            if not confirmed:
                return False
        else:
            assign_to = ""
        
        self.series_states.addState()
        
        self.series.setCuration(names, curation_status, assign_to)

        return True
    
    @object_function(update_objects=False, reload_field=False)  # set update objects as False to avoid the lock check
    def lockObjects(self, names : list, lock=True):
        """Locked the selected objects."""
        self.series_states.addState()

        for name in names:
            self.series.setAttr(name, "locked", lock)

        self.table_manager.updateObjects(names)
        self.mainwindow.field.deselectAllTraces()
        self.mainwindow.seriesModified(True)

        return True
    
    @object_function(update_objects=True, reload_field=True)
    def setPaletteButtonFromObj(self, names : list):
        """Set the selected object name as the name of the selected palette trace."""
        name = self.getSingleName(names)
        if not name:
            return False
        
        self.mainwindow.setPaletteButtonFromObj(name)

        return True
    
    @object_function(update_objects=True, reload_field=True)
    def splitObject(self, names : list):
        """Split an object into one object per trace."""
        name = self.getSingleName(names)
        if not name:
            return False
        
        self.series_states.addState()

        series_states = self.mainwindow.field.series_states
        new_names = self.series.splitObject(name, series_states)

        self.table_manager.updateObjects(new_names)  # manual call to update the objects

        return True

    @object_function(update_objects=True, reload_field=False)
    def setUserCol(self, names : list, col_name : str, opt : str, log_event=True):
        """Set the categorical user column for an object.
        
            Params:
                col_name (str): the name of the user-defined column
                opt (str): the option to set for the object(s)
        """
        self.series_states.addState()

        for name in names:
            self.series.setUserColAttr(name, col_name, opt)
        
        if log_event:
            for name in names:
                self.series.addLog(name, None, f"Set user column {col_name} as {opt}")

        return True
    
    def editUserCol(self, col_name : str):
        """Edit a user-defined column.
        
            Params:
                col_name (str): the name of the user-defined column to edit
        """
        structure = [
            ["Column name:"],
            [(True, "text", col_name)],
            [" "],
            ["Options:"],
            [(True, "multitext", self.series.user_columns[col_name])]
        ]
        response, confirmed = QuickDialog.get(self, structure, "Add Column")
        if not confirmed:
            return
        
        name = response[0]
        opts = response[1]

        if name != col_name and name in self.series.user_columns:
            notify("This group already exists.")
            return
        
        self.series_states.addState()
        self.series.editUserCol(col_name, name, opts)

        self.mainwindow.seriesModified(True)
        self.mainwindow.createContextMenus()

        self.table_manager.updateObjCols()

    def addUserCol(self):
        """Add a user-defined column."""
        structure = [
            ["Column name:"],
            [(True, "text", "")],
            [" "],
            ["Options:"],
            [(True, "multitext", [])]
        ]
        response, confirmed = QuickDialog.get(self, structure, "Add Column")
        if not confirmed:
            return
    
        name = response[0]
        opts = response[1]

        if name in self.series.getOption("object_columns"):
            notify("This column already exists.")
            return
        
        self.series_states.addState()
        self.series.addUserCol(name, opts)

        self.mainwindow.seriesModified(True)
        self.mainwindow.createContextMenus()

        self.table_manager.updateObjCols()

    @object_function(update_objects=False, reload_field=False)    
    def displayHostTree(self, names : list, hosts=True):
        """Display the hosts/travelers of an object in ASCII tree representation.
        
            Params:
                hosts (bool): True if hosts, False if travelers
        """
        name = self.getSingleName(names)
        if not name:
            return False
        
        t = TextWidget(
            self.mainwindow,
            self.series.host_tree.getASCII(name, hosts),
            "Host Tree" if hosts else "Inhabitant Tree",
        )
        t.output.setFont("Courier New")

        return True
    
    @object_function(update_objects=True, reload_field=False)
    def setHosts(self, names : list):
        """Set host(s) for selected object(s)."""
        if len(names) == 1:
            current_hosts = self.series.getObjHosts(names[0])
        else:
            current_hosts = []
        
        structure = [
            ["Host Name:"],
            [(True, "multicombo", list(self.series.data["objects"].keys()), current_hosts)]
        ]
        response, confirmed = QuickDialog.get(self, structure, "Object Host")
        if not confirmed:
            return False
        host_names = list(set(response[0]))
        
        ## Ensure objects do not host each other
        for hn in host_names:
            
            if hn in names:
                notify("An object cannot host itself.")
                return False

            ## If intersection exists
            trav_hosts = set(self.series.getObjHosts(hn, traverse=True))
            if bool(set(names) & trav_hosts):
                notify("Objects cannot host each other.")
                return False
        
        self.series_states.addState()
        self.series.setObjHosts(names, host_names)

        ## Explicitly update entire host tree
        self.table_manager.updateObjects(
            self.series.host_tree.getObjToUpdate(names)
        )

        return True
    
    @object_function(update_objects=True, reload_field=False)
    def clearHosts(self, names : list):
        """Clear the host(s) for the selected object(s)."""
        self.series_states.addState()
        self.series.clearObjHosts(names)
        
        # manual call to update entire host tree
        self.table_manager.updateObjects(
            self.series.host_tree.getObjToUpdate(names)
        )

        return True

    
