"""Context menus."""


from PyReconstruct.modules.gui.utils import getUserColsMenu, getAlignmentsMenu


def collada_menu_label(available=None):
    """Label for the Collada (.dae) export item, flagged when unavailable.

    Collada export needs the optional 'pycollada' package, which frozen
    (PyInstaller) builds never bundle. When it is unavailable the label gains a
    "(not installed)" suffix so the (disabled) item explains itself. Pass
    ``available`` explicitly to keep the string logic pure/testable; when None
    the live availability is queried (import kept local so this menu module
    doesn't pull in the heavy export backend at import time).

        Params:
            available (bool | None): whether pycollada is importable; None to
                query it live
        Returns:
            (str): the menu label
    """
    if available is None:
        from PyReconstruct.modules.backend.volume.export_volumes import (
            collada_available,
        )
        available = collada_available()
    return "Collada (.dae)" if available else "Collada (.dae) (not installed)"


def disable_unavailable_export_formats(widget):
    """Grey out 3D-export formats whose optional dependency is missing.

    Currently only Collada (.dae), which needs 'pycollada' (absent from frozen
    builds). Disabling the menu item up front means a packaged user is never
    offered an export that can only fail; the runtime guard in
    ``export3DObjects`` remains a backstop. Call once, right after the object
    menu is populated onto ``widget`` (both the field context menu and the
    object-list table build it). No-op when the action isn't on this widget or
    Collada IS available.
    """
    from PyReconstruct.modules.backend.volume.export_volumes import (
        collada_available,
    )
    act = getattr(widget, "export3D_dae_act", None)
    if act is not None and not collada_available():
        act.setEnabled(False)


# Every attribute a "Restore previous visibility" QAction can be stored under.
# Three surfaces offer the command and each gets its own QAction object: the
# field menu's Object submenu and the object list's context menu both use
# restorevisibility_act (on different widgets), and the object list's own menubar
# uses restorevisibility_act1, the same _act1 convention its other duplicated
# visibility entries follow.
RESTORE_VISIBILITY_ACT_NAMES = (
    "restorevisibility_act",
    "restorevisibility_act1",
)


def sync_restore_visibility_action(widget, has_snapshot):
    """Enable "Restore previous visibility" only when there is one to restore.

    The snapshot is taken by "Hide other objects" and consumed by the restore, so
    with no isolate behind it the command has nothing to do. Disabling it is the
    honest state: an enabled row that no-ops teaches nothing, and one that guessed
    at a state it never recorded would be worse.

    Every surface builds its menu ONCE and reuses it, so none can rely on the
    build-time state. Callers, each on the event that precedes the menu appearing:
    ``MainWindow.checkActions`` for the field menu (populated onto the main
    window), ``ObjectTableWidget.contextMenuEvent`` for the object list's context
    menu, and the ``aboutToShow`` of the object list's own ``Selection`` menu.

    Syncs whichever of RESTORE_VISIBILITY_ACT_NAMES the widget actually has, so
    one call covers a widget carrying two copies and is a no-op on one carrying
    none (a window whose menus are not built yet, for instance).

        Params:
            widget (QWidget): the widget the menu was populated onto
            has_snapshot: truthy when a visibility snapshot exists
    """
    for act_name in RESTORE_VISIBILITY_ACT_NAMES:
        act = getattr(widget, act_name, None)
        if act is not None:
            act.setEnabled(bool(has_snapshot))


def edit_selected_label(active):
    """Resolve the Q8 top-level edit action's (label, enabled) for a selection.

    Pure decision function shared by MainWindow.checkActions so the menu's
    "appears/disappears with selection" behavior is testable without a Qt loop.

        Params:
            active (str | None): "trace" when only traces are selected,
                "ztrace" when only z-traces are selected, None when nothing
                applicable is selected (including a mixed trace+z-trace
                selection, which the field menu treats as ambiguous).
        Returns:
            (tuple): (label text, enabled bool)
    """
    if active == "trace":
        return ("Edit trace attributes...", True)
    if active == "ztrace":
        return ("Edit z-trace attributes...", True)
    return ("Edit attributes...", False)


def get_label_menu_list(self):
    """The zarr-label right-click menu (unchanged by the frequency redesign).

    Both actions operate on the interactive zarr overlay's currently selected
    label ids (self.field.zarr_layer.selected_ids); their handlers and
    dependencies are all live (see importLabels / mergeLabels). "Import labels"
    imports the selected labels straight away (no dialog -> no ellipsis);
    "Merge labels" merges them in place and is disabled below two labels.
    """
    return [
        ("importlabels_act", "Import labels", "", self.importLabels),
        ("mergelabels_act", "Merge labels", "", self.mergeLabels)
    ]


def get_hoisted_trace_actions(field):
    """The shortcut-bearing trace actions hoisted to the field menu's top strip.

    Frequency-first redesign, Q1: the field top strip is EXACTLY the four
    shortcut-bearing trace actions -- the dynamic "Edit ... attributes..." item
    plus these three. They are built here (rather than inline in the field menu)
    so the field variant of the trace submenu can drop them without either copy
    drifting from the other; the tuples keep their original attr_names, so the
    user-configurable shortcuts (Ctrl+M / Ctrl+Shift+M / Ctrl+H, looked up by
    act_name) follow them to the top strip unchanged.

        Params:
            field (FieldWidget): the field widget that owns the handlers
        Returns:
            (list): action tuples for the field menu's top strip
    """
    return [
        ("mergetraces_act", "Merge traces", field.series, field.mergeTraces),
        ("mergeobjects_act", "Merge attributes only", field.series, lambda : field.mergeTraces(merge_attrs_only=True)),
        # "Hide selected traces": same act_name and same command as the copy in
        # the trace submenu, so the two labels have to move together. See the
        # note beside that copy for why the scope word was added.
        ("hidetraces_act", "Hide selected traces", field.series, field.hideTraces),
    ]


def get_field_menu_list(self):

    return [
        # Top strip (Q1): the five actions a user almost always came here to do,
        # with their shortcuts on display.
        #
        # Row 1 is a single top-level shortcut to the primary "Edit ...
        # attributes..." dialog for whatever is selected. Its label and enabled
        # state are driven by MainWindow.checkActions (trace selection ->
        # "Edit trace attributes...", z-trace selection -> "Edit z-trace
        # attributes...", nothing/mixed -> disabled). The entity submenus below
        # still carry the full per-entity actions; this only surfaces the
        # most-used one at the top.
        #
        # Ctrl+E stays bound to edittrace_act, which keeps its home at the top
        # of the Trace submenu (a single QAction cannot both relabel per
        # selection and hold the trace-only shortcut) -- see the spec's
        # implementation note.
        ("editselected_act", "Edit attributes...", "", self.editSelectedAttributes),
        # Row 2, requested by a beta-5 tester: "put Edit object attributes... at
        # the top level beside Edit trace attributes...". Row 1 IS that label
        # whenever traces are selected, so this sits directly under it.
        #
        # It is a separate always-present row rather than a third case of
        # editselected_act, because an object is not a third kind of selection.
        # The field has trace and z-trace selections only; the objects here are
        # the ones owning the SELECTED TRACES, so with traces selected both
        # dialogs are meaningful at once and a relabeling action can only offer
        # one of them. Adding "object" as a case would make it unreachable: the
        # trace case would always win the same selection.
        #
        # No new resolution rule: editAttributes is wrapped in
        # FieldWidgetObject.object_function, which derives the object names from
        # the selected traces (or, when an object list has focus, that list's
        # selection). This row therefore acts on exactly what the object list's
        # own row-1 copy acts on.
        #
        # Duplicating the "Object >" row-1 label is deliberate and is the
        # established pattern here: "Edit trace attributes..." likewise appears
        # both as row 1 (relabeled) and at the top of "Trace >". Only the
        # attr_name has to be unique -- every one of these menus is populated
        # onto the same widget, so a repeat would silently shadow the submenu
        # copy. The submenu keeps its historical (misspelled) editobjattribtues_act
        # because the object LIST is built from that same shared builder and is
        # out of scope here. Neither copy carries a shortcut, so there is no
        # ambiguous-binding trap of the addobjto3D kind.
        ("editobjattrs_act", "Edit object attributes...", "", self.field.editAttributes),
        *get_hoisted_trace_actions(self.field),
        None,
        # Clipboard group, muscle-memory order. "Copy to sections..." keeps its
        # place directly under "Copy" (approved: keep the noun and the ellipsis).
        #
        # The series form gives it its user-configurable shortcut, looked up by
        # act_name (default Ctrl+Alt+C -- see default_settings.py for why not
        # Ctrl+Shift+C). This is the action's only shortcut-bearing home: the
        # trace-LIST variant in get_context_menu_list_trace passes "", because
        # keys are only ever connected through the field.
        self.cut_act,
        self.copy_act,
        ("copytosections_act", "Copy to sections...", self.series, self.field.copyTracesToSections),
        self.paste_act,
        self.pasteattributes_act,
        None,
        ("selectall_act", "Select all traces", self.series, self.field.selectAllTraces),
        ("deselect_act", "Deselect all traces", self.series, self.field.deselectAllTraces),
        ("invertselection_act", "Invert selection", self.series, self.field.invertTraceSelection),
        None,
        # The familiar entity triad survives; Trace > now holds only the long
        # tail (the four everyday actions moved to the top strip).
        {
            "attr_name": "tracemenu",
            "text": "Trace",
            "opts": self.field.getTraceMenu()
        },
        {
            "attr_name": "objectmenu",
            "text": "Object",
            "opts": self.field.getObjMenu()
        },
        {
            "attr_name": "ztracemenu",
            "text": "Z-trace",
            "opts": self.field.getZtraceMenu()
        },
        None,
        {
            "attr_name": "viewmenu",
            "text": "View",
            "opts":
            [
                # These five are checkable: they mirror a live on/off field
                # state and keep their user-configurable shortcuts via the
                # (series, "checkbox") kbd form. Checked state is (re)synced
                # from the actual state whenever the menu opens -- see
                # MainWindow.checkActions. "Unhide all traces" stays a plain
                # action (it is a one-shot, not a persistent state).
                ("focus_act", "Focus mode", (self.series, "checkbox"), self.field.toggleFocusMode),
                None,
                ("unhideall_act", "Unhide all traces (this section)", self.series, self.field.unhideAllTraces),
                None,
                ("hideall_act", "Hide trace layer", (self.series, "checkbox"), self.field.toggleHideAllTraces),
                ("showall_act", "Show all traces (ignore hidden)", (self.series, "checkbox"), self.field.toggleShowAllTraces),
                None,
                ("hideimage_act", "Hide image", (self.series, "checkbox"), self.field.toggleHideImage),
                ("blend_act", "Section blend", (self.series, "checkbox"), self.field.toggleBlend),
            ]
        },
        getAlignmentsMenu(self.series, self.changeAlignment),
        None,
        ("delete_act", "Delete selected", "Del", self.backspace),
    ]


def get_context_menu_list_obj(self, list_ops=None, is_in_field=True):
    """Build the object context menu (field ``Object >`` and the object list).

    Frequency-first layout: the everyday actions are top-level, the long tail
    keeps its familiar submenus, table utilities sit second-from-bottom and the
    destructive actions come last.

    Row order approved by the maintainer on 2026-07-29, replacing the earlier
    frequency-first arrangement. Two things changed, both his:

      * "Add to 3D scene" now sits directly above the "3D >" submenu it belongs
        to. Previously it was row 2 of the top strip and "3D >" was row 15, with
        the whole visibility family, "Group >" and "Set curation >" between them
        -- "the 3D scene menu item is too far from the 3D submenu".
      * "Group >" and "Set curation >" dropped out of the upper half to join
        "Object attributes >" and the old "Geometry >": "since these are
        object-level settings they should be in the same section as Object
        attributes and Geometry". The comment action and "Duplicate object" came
        down with them, because they "deserve" a place but not one of "the
        frequently used top spots".

    The visibility family keeps its existing order and its own section ("the
    view section with the various Hide options is good"), and the destructive
    row stays last.

    Revised again 2026-07-31, this time renaming rather than only reordering.
    Three commands appeared on both this menu and the trace menu under identical
    labels with different scope ("Smooth traces", "Edit radius...", "Edit
    shape..."), so the label told a user nothing about how much of the series the
    command would touch. The object copies now name the object, the trace copies
    name the selection, "Smooth object" is promoted to top level, "Geometry >" is
    dissolved under the maintainer's two-item rule, "Split into separate objects"
    joins "Duplicate object", and "Comment..." becomes "Leave object comment..."
    at the end of its section. See the section comment below for the reasoning
    per item.

        Params:
            list_ops (list): list-only table utilities ("Invert selection",
                "Copy object values") to mount in the standard bottom utility
                slot. The object list passes them; the field passes nothing.
            is_in_field (bool): True for the field submenu variant, False for
                the object list's right-click menu
    """
    # Only the field's copy carries the configurable keys, the rule
    # `get_context_menu_list_trace` already follows for the trace list.
    #
    # This menu is built twice into one top-level window: once onto the
    # MainWindow by `createContextMenus`, and once onto `ObjectTableWidget`,
    # which is a QDockWidget inside that same window. `newAction` calls
    # `widget.addAction` on whichever widget it is given, so a keyed row builds
    # two QActions with the same sequence and the default `WindowShortcut`
    # context. Qt answers that pair with `Ambiguous shortcut overload` and fires
    # NEITHER, so passing the series on both sides makes the key dead exactly
    # while the list is open. Passing `""` on the list side leaves one claimant
    # in the window, and `WindowShortcut` on the field's copy already covers the
    # dock, so the key keeps working with the list open and focused.
    #
    # A per-widget shortcut context is not an alternative here:
    # `WidgetWithChildrenShortcut` on the dock's copy is active whenever focus
    # is inside the dock, which is precisely when the window-scoped copy is
    # active too, so the ambiguous pair survives.
    sc = self.series if is_in_field else ""

    return [
        # Top strip: the two actions the maintainer named as deserving the
        # frequently used top spots, plus the 3D submenu they lead into.
        ("editobjattribtues_act", "Edit object attributes...", "", self.editAttributes),
        # Hoisted out of "3D >" (this lab is 3D-heavy): the frequent member
        # leaves the submenu, the rare ones stay. The label gains "3D" because
        # at top level "Add to scene" no longer has the submenu for context.
        #
        # It ALSO stays inside "3D >" directly below (as "Add to scene").
        # Hoisting it out entirely was the wrong trade: someone looking for it
        # goes to "3D >" first, does not find it, and hunts. Both placements is
        # how "Edit object attributes..." already behaves, so this matches an
        # established pattern rather than inventing one. Keeping the two rows
        # adjacent is what makes the pair read as one thing.
        #
        # Only THIS copy carries the shortcut. Two actions sharing one shortcut
        # is an ambiguous binding, and Qt answers an ambiguous shortcut by firing
        # NEITHER action -- the exact trap that made Ctrl+Shift+C unusable for
        # copy-to-sections.
        ("addobjto3D_act", "Add to 3D scene", sc, self.addTo3D),
        {
            "attr_name": "menu_3D",
            "text": "3D",
            "opts":
            [
                # Mirrors the top-level "Add to 3D scene" so the pair is
                # discoverable together: someone hunting for "add" naturally
                # opens "3D >", where previously only "Remove from scene" lived.
                # No shortcut here on purpose; the top-level copy owns it, and
                # duplicating a shortcut makes it ambiguous, which Qt resolves
                # by firing neither action.
                ("addobjto3Dsub_act", "Add to scene", "", self.addTo3D),
                ("removeobj3D_act", "Remove from scene", "", self.remove3D),
                None,
                {
                    "attr_name": "exportobj3D",
                    "text": "Export mesh as",
                    "opts":
                    [
                        # unique attr_names per format (previously all "export3D_act",
                        # so four of five silently shadowed the last on the widget).
                        # Collada needs the optional 'pycollada' package (never
                        # bundled in frozen builds): its label is flagged when
                        # unavailable and the item is disabled after build (see
                        # disable_unavailable_export_formats); export3DObjects
                        # keeps a runtime guard as a backstop.
                        ("export3D_obj_act", "Wavefront (.obj)", "", lambda : self.exportAs3D("obj")),
                        ("export3D_off_act", "Object File Format (.off)", "", lambda : self.exportAs3D("off")),
                        ("export3D_ply_act", "Stanford PLY (.ply)", "", lambda : self.exportAs3D("ply")),
                        ("export3D_stl_act", "STL (.stl)", "", lambda : self.exportAs3D("stl")),
                        ("export3D_dae_act", collada_menu_label(), "", lambda : self.exportAs3D("dae")),
                    ]

                    },
                ("exportmeshdata", "Export quantitative data...", "", self.export3DData),
                None,
                ("editobj3D_act", "Edit 3D settings...", "", self.edit3D)
            ]
        },
        None,
        # The whole visibility family, flat (was a "Visibility >" submenu), in
        # its own section. Members and section boundaries were left alone in the
        # first pass on purpose ("the view section with the various Hide options
        # is good"); the section was completed on 2026-07-31 after the
        # scope-by-action matrix of every visibility command was put in front of
        # the maintainer. His call: "build the restore, skip the blanket
        # unhide-other."
        #
        # It now reads as three hide/unhide pairs, one per scope of action:
        #
        #   Hide object                    Unhide object                 object
        #   Hide other objects             Restore previous visibility   isolate
        #   Hide all objects               Unhide all objects            series
        #
        # Each rename, and the one addition:
        #
        #   * "Hide" -> "Hide object", his words: "yes make it Hide object". Row
        #     one is symmetric with "Unhide object" now. It never collided with
        #     the trace menu (that copy reads "Hide selected traces"), so this is
        #     symmetry rather than the collision fix.
        #   * "Show all objects" -> "Unhide all objects", so one verb means one
        #     thing. The View submenu's "Show all traces (ignore hidden)" keeps
        #     its verb deliberately: that one is a view mode that overrides the
        #     hidden flag without clearing it, so it genuinely is not an unhide.
        #   * "Restore previous visibility" is new, and is the inverse
        #     "Hide other objects" never had. See
        #     FieldWidgetObject.restorePreviousVisibility. It sits directly under
        #     the isolate it undoes, and it is disabled until an isolate has taken
        #     a snapshot (see sync_restore_visibility_action below).
        #
        # NOT added, and rejected explicitly rather than overlooked: "Unhide other
        # objects". After isolating {A}, unhiding the complement of the selection
        # leaves everything visible, which is what "Unhide all objects" already
        # does; its only distinct behavior needs the selection to have changed
        # since the isolate, and then it surprises. A row that duplicates an
        # existing command is not discoverability.
        ("hideobj_act", "Hide object", "", self.hideObj),
        ("unhideobj_act", "Unhide object", "", lambda : self.hideObj(False)),
        ("hideotherobj_act", "Hide other objects", "", self.hideOtherObjects),
        ("restorevisibility_act", "Restore previous visibility", "",
         self.restorePreviousVisibility),
        ("hideallobj_act", "Hide all objects", "", self.hideAllObjects),
        # act_name kept as showallobj_act on purpose: it is the key a
        # user-configurable shortcut would be stored under, so renaming it to
        # match the new label would silently drop any stored binding. Only the
        # label changed.
        ("showallobj_act", "Unhide all objects", "", self.unhideAllObjects),
        None,
        # Object-level settings, one section, ordered most used first. Approved
        # 2026-07-31, and three things changed at once:
        #
        #   * The labels of the three commands that also exist on the trace menu
        #     now name their SCOPE, because the old shared labels did not.
        #     "Smooth traces" on this menu smoothed every trace of the object on
        #     every section it appears on (Series.smoothObject); "Smooth traces"
        #     on the trace menu smooths the current selection on the current
        #     section (FieldWidgetTrace.smoothTraces). Same for the radius and
        #     shape pairs. The axis that separates them is scope, not shape, so
        #     the object copies say "object" and the trace copies say "selected".
        #   * "Smooth object" is promoted out of the old "Geometry >" submenu to
        #     top level: smoothing is frequent enough that it should not cost a
        #     hop.
        #   * "Geometry >" is dissolved rather than renamed. With "Smooth object"
        #     promoted and "Split into separate objects" moved beside "Duplicate
        #     object" (it is structural, not a trace operation), the submenu was
        #     down to two edit rows, which is the maintainer's own bar for asking
        #     whether a submenu earns its place. It did not, so its two rows are
        #     top-level too and the container is gone. There is nothing left for a
        #     more descriptive title to describe: the scope now lives in the
        #     labels.
        #
        # "Object attributes >" leads the section, and "Leave object comment..."
        # closes it (both his). The comment action keeps its ellipsis and gains
        # the noun, so that it reads as an object-level action rather than as an
        # unscoped "Comment..." next to five trace-shaped rows.
        {
            # Stored OBJECT attributes only. Trace-level actions do not belong
            # here (see the bulk trace group at the bottom of this menu).
            "attr_name" : "objattrsmenu",
            "text": "Object attributes",
            "opts":
            [
                # The series form binds the user-configurable key looked up by
                # act_name (default Ctrl+Shift+H). This passed `""` until now,
                # so the default and the shortcuts-dialog row it has always had
                # bound nothing. Nobody reported it because `resetShortcuts`
                # writes onto the built QAction, repairing the key for anyone
                # who opened that dialog until the next `createContextMenus`
                # re-applied the `""`. Same form as `addobjto3D_act` above,
                # this menu's other keyed action, and `sc` for the same reason:
                # the object list's copy must not claim the key a second time.
                ("sethosts_act", "Set hosts...", sc, self.setHosts),
                ("clearhosts_act", "Clear hosts", "", self.clearHosts),
                ("displayhosts_act", "Show host tree", "", self.displayHostTree),
                ("displayinhabitants_act", "Show inhabitant tree", "", lambda : self.displayHostTree(False)),
                None,
                ("setobjalignment_act", "Edit alignment...", "", self.editAlignment),
                # Reapply the current autoseg palette (colorblind-safe default
                # or a custom one) to objects imported before the palette
                # existed, whose old colors were baked in at import time.
                ("reapplyautosegcolors_act", "Reapply autoseg colors...", "", self.reapplyAutosegColors),
                None,
                # Lock/Unlock lives here as its single home (it is a stored
                # object attribute); do NOT re-add it to another submenu.
                ("lockobj_act", "Lock", "", self.lockObjects),
                ("unlockobj_act", "Unlock", "", lambda : self.lockObjects(False))
            ]
        },
        # Distinct attr_name from the field Trace submenu's "smoothtraces_act":
        # both menus are populated onto the same widget, so a shared name meant
        # one silently shadowed the other (same class of bug as the old
        # export3D_act). The LABELS used to collide the same way, with nothing
        # for the user to tell them apart by; the widget collision was fixed
        # long before the label one was.
        ("smoothobj_act", "Smooth object", "", self.smoothObject),
        # The two structural commands, together, more used first.
        ("copyobj_act", "Duplicate object", "", self.copyObjects),
        ("splitobj_act", "Split into separate objects", "", self.splitObject),
        # Was "Geometry > Edit radius..." / "Edit shape...". Object-wide: both
        # walk every section the object appears on (Series.editObjectRadius /
        # editObjectShape), unlike the trace menu's selection-scoped pair.
        ("editobjradius_act", "Edit object radius...", "", self.editRadius),
        ("editobjshape_act", "Edit object shape...", "", self.editShape),
        {
            # Hoisted to top level (was inside "Object attributes >"); mirrors
            # the z-trace menu's "Group >", so there is one pattern to learn.
            "attr_name": "objgroupmenu",
            "text": "Group",
            "opts":
            [
                ("addobjgroup_act", "Add to group...", "", self.addToGroup),
                ("removeobjgroup_act", "Remove from group...", "", self.removeFromGroup),
                ("removeobjallgroups_act", "Remove from all groups", "", self.removeFromAllGroups),
            ]
        },
        {
            "attr_name": "curatemenu",
            "text": "Set curation",
            "opts":
            [
                ("needscuration_act", "Needs curation", "", lambda : self.bulkCurate("Needs curation")),
                ("curated_act", "Curated", "", lambda : self.bulkCurate("Curated")),
                ("blankcurate_act", "Clear status", "", lambda : self.bulkCurate("")),
            ]
        },
        getUserColsMenu(self.series, self.addUserCol, self.setUserCol, self.editUserCol),
        # Closes the object-settings section. Was "Comment...", which said
        # nothing about what it comments on; the comment is stored on the object
        # (series.obj_attrs[name]["comment"]), and on a menu whose neighbors are
        # trace-shaped that needed saying. Ellipsis kept: it opens a dialog.
        ("editobjcomment_act", "Leave object comment...", "", self.editComment),
        None,
        {
            "attr_name": "objztracemenu",
            "text": "Create Z-trace",
            "opts":
            [
                ("csztrace_act", "On contour midpoints", "", self.createZtrace),
                ("atztrace_act", "From trace sequence", "", lambda : self.createZtrace(cross_sectioned=False)),
            ]
        },
        None,
        ("objhistory_act", "View history", "", self.viewHistory),
        ("setpaletteobj_act", "Copy attributes to palette", "", self.setPaletteButtonFromObj),
        # Table utilities (list surface only), in the slot every list shares.
        *([None] + list(list_ops) if list_ops else []),
        None,
        # Bulk trace operation, in its own group above the delete row.
        #
        # Tags are TRACE-level (Trace.tags), not object attributes: on an object
        # menu this action strips the tags off EVERY trace of the selected
        # objects, series-wide (series.removeAllTraceTags -> "Remove all trace
        # tags" in the log). Filing it under "Object attributes >" -- or under
        # the old "Geometry >", where it used to live -- misrepresents what it
        # does, so it gets its own bulk/destructive group instead.
        ("removealltags_act", "Remove all tags", "", self.removeAllTags),
        None,
        ("deleteobj_act", "Delete objects", "", self.deleteObjects)
    ]


def get_context_menu_list_trace(self, is_in_field=True, list_ops=None, find_in_field=None):
    """Build the trace context menu (field ``Trace >`` and the trace list).

    Two variants of one menu. In the FIELD, the four shortcut-bearing everyday
    actions (edit / merge / merge attributes only / hide) live on the field
    menu's top strip, so this submenu holds only the long tail. In the trace
    LIST there is no strip above it, so the same actions appear here, ordered
    by frequency: edit, merge, hide/unhide, then the shape-editing tail.

        Params:
            is_in_field (bool): True for the field submenu variant
            list_ops (list): list-only table utilities ("Invert selection",
                "Copy trace values") for the standard bottom utility slot
            find_in_field (callable): the trace list's "jump to this trace"
                handler (it belongs to the table, not the field)
    """
    # only allow shortcuts to be connected through the field

    sc = self.series if is_in_field else ""

    # Row 1 either way. In the field this action keeps Ctrl+E (the top strip's
    # dynamic "Edit ... attributes..." item cannot hold a trace-only shortcut
    # while it relabels per selection).
    context_menu = [
        ("edittrace_act", "Edit trace attributes...", sc, self.traceDialog),
    ]

    if is_in_field:

        # Long tail only: merge / hide / edit are on the field menu's top strip.
        #
        # "Smooth selected traces", not "Smooth traces": the object menu carries
        # a smooth action too, and until now both read "Smooth traces" while
        # doing different amounts of work. This one smooths the current selection
        # on the current section; the object one walks every section the object
        # appears on. The label is the only place a user can see the difference.
        context_menu += [
            None,
            ("smoothtraces_act", "Smooth selected traces", "", self.smoothTraces),
            ("makenegative_act", "Make negative", "", self.makeNegative),
            ("makepositive_act", "Make positive", "", lambda : self.makeNegative(False)),
            None,
            # field only: current-section "hide the rest" (distinct from the
            # volume-wide object action). Menu-only, so no shortcut is bound.
            ("hideothertraces_act", "Hide other traces (this section)", "", self.hideOtherTraces),
        ]

        return context_menu

    context_menu += [
        None,
        ("mergetraces_act", "Merge traces", sc, self.mergeTraces),
        ("mergeobjects_act", "Merge attributes only", sc, lambda : self.mergeTraces(merge_attrs_only=True)),
        None,
        # "Hide selected traces", not "Hide traces". This one never collided by
        # label (the object copy read "Hide" until 2026-07-31), which is why the
        # first pass left it alone -- the collision rule had nothing to say about
        # it. The scope-by-action matrix did: the object copy walks every section
        # the object appears on (Series.hideObjects) and this one hides the
        # traces selected in this table, on this section (Section.hideTraces),
        # exactly the asymmetry the other four pairs have. Renamed with the
        # unhide row below so the pair reads the same way in both directions.
        # The hoisted copy on the field menu's top strip carries the same
        # act_name and the same label; see get_hoisted_trace_actions.
        ("hidetraces_act", "Hide selected traces", sc, self.hideTraces),
        # "Unhide selected traces", not "Unhide": the object menu's unhide read
        # "Unhide" too, and the two did different amounts of work. This one
        # unhides the traces selected in this table, on this section
        # (Section.hideTraces, reached through visibility_trace_function, which
        # supplies the selection); the object one walks every section the object
        # appears on (Series.hideObjects). Fourth pair of the same collision,
        # renamed on 2026-07-31 with the maintainer's explicit go-ahead to touch
        # the visibility section for this one label.
        ("unhidetraces_act", "Unhide selected traces", "", lambda : self.hideTraces(hide=False)),
        None,
        # the shape-editing tail, one group
        ("opentraces_act", "Set open", "", lambda : self.closeTraces(closed=False)),
        ("closedtraces_act", "Set closed", "", self.closeTraces),
        ("makenegative_act", "Make negative", "", self.makeNegative),
        ("makepositive_act", "Make positive", "", lambda : self.makeNegative(False)),
        # Selection-scoped, and now labeled that way. The object menu's
        # "Edit object radius..." / "Edit object shape..." / "Smooth object" are
        # the object-wide counterparts; all three pairs used to share a label.
        # These three act on the traces selected in this table, on this section
        # (Section.editTraceRadius / editTraceShape, Trace.smooth).
        ("edittraceradius_act", "Edit selected radius...", "", self.editTraceRadius),
        ("edittraceshape_act", "Edit selected shape...", "", self.editTraceShape),
        ("smoothtraces_act", "Smooth selected traces", "", self.smoothTraces),
        None,
        ("copytosections_act", "Copy to sections...", "", self.copyTracesToSections),
        ("createtraceflag_act", "Create flag...", "", self.createTraceFlag),
    ]

    # Discoverability probe for the beta testers: double-click already jumps to
    # the trace, but nothing in the menu says so. Deliberately tucked in a
    # submenu -- it is on trial, and a submenu is one line to drop again.
    if find_in_field is not None:
        context_menu.append(
            {
                "attr_name": "tracefindmenu",
                "text": "Find",
                "opts":
                [
                    ("findinfield_act", "Find in field", "", find_in_field),
                ]
            }
        )

    # table utilities, in the slot every list shares
    if list_ops:
        context_menu += [None] + list(list_ops)

    context_menu += [
        None,
        ("deletetrace_act", "Delete traces", "", self.deleteTraces)  # accessible elswhere in the field context menu
    ]

    return context_menu
