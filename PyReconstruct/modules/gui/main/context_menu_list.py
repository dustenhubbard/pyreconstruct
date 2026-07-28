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
        ("mergeobjects_act", "Merge attributes only", field.series, lambda : field.mergeTraces(merge_attrs=True)),
        ("hidetraces_act", "Hide traces", field.series, field.hideTraces),
    ]


def get_field_menu_list(self):

    return [
        # Top strip (Q1): the four shortcut-bearing trace actions -- what a user
        # almost always came here to do, with their shortcuts on display.
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
        *get_hoisted_trace_actions(self.field),
        None,
        # Clipboard group, muscle-memory order. "Copy to sections..." keeps its
        # place directly under "Copy" (approved: keep the noun and the ellipsis).
        self.cut_act,
        self.copy_act,
        ("copytosections_act", "Copy to sections...", "", self.field.copyTracesToSections),
        self.paste_act,
        self.pasteattributes_act,
        None,
        ("selectall_act", "Select all traces", self.series, self.field.selectAllTraces),
        ("deselect_act", "Deselect all traces", self.series, self.field.deselectAllTraces),
        ("invertselection_act", "Invert selection", "", self.field.invertTraceSelection),
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


def get_context_menu_list_obj(self, list_ops=None):
    """Build the object context menu (field ``Object >`` and the object list).

    Frequency-first layout: the everyday actions are top-level, the long tail
    keeps its familiar submenus, table utilities sit second-from-bottom and the
    destructive actions come last.

        Params:
            list_ops (list): list-only table utilities ("Invert selection",
                "Copy object values") to mount in the standard bottom utility
                slot. The object list passes them; the field passes nothing.
    """
    return [
        # Top strip: edit + the three actions the maintainer named as
        # often-used (comment, duplicate, add to 3D scene).
        ("editobjattribtues_act", "Edit object attributes...", "", self.editAttributes),
        ("editobjcomment_act", "Comment...", "", self.editComment),
        ("copyobj_act", "Duplicate object", "", self.copyObjects),
        # Hoisted out of "3D >" (this lab is 3D-heavy): the frequent member
        # leaves the submenu, the rare ones stay. The label gains "3D" because
        # at top level "Add to scene" no longer has the submenu for context.
        ("addobjto3D_act", "Add to 3D scene", "", self.addTo3D),
        None,
        # The whole visibility family, flat (was a "Visibility >" submenu).
        ("hideobj_act", "Hide", "", self.hideObj),
        ("unhideobj_act", "Unhide", "", lambda : self.hideObj(False)),
        ("hideotherobj_act", "Hide other objects", "", self.hideOtherObjects),
        ("hideallobj_act", "Hide all objects", "", self.hideAllObjects),
        ("showallobj_act", "Show all objects", "", self.unhideAllObjects),
        None,
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
        None,
        {
            "attr_name": "menu_3D",
            "text": "3D",
            "opts":
            [
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
        {
            # Stored OBJECT attributes only. Trace-level actions do not belong
            # here (see the bulk trace group at the bottom of this menu).
            "attr_name" : "objattrsmenu",
            "text": "Object attributes",
            "opts":
            [
                ("sethosts_act", "Set hosts...", "", self.setHosts),
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
        {
            "attr_name": "objgeometrymenu",
            "text": "Geometry",
            "opts":
            [
                ("editobjradius_act", "Edit radius...", "", self.editRadius),
                ("editobjshape_act", "Edit shape...", "", self.editShape),
                # Distinct attr_name from the field Trace submenu's
                # "smoothtraces_act": both menus are populated onto the same
                # widget, so a shared name meant one silently shadowed the
                # other (same class of bug as the old export3D_act).
                ("smoothobj_act", "Smooth traces", "", self.smoothObject),
                ("splitobj_act", "Split into separate objects", "", self.splitObject),
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
        # "Geometry >", where it used to live -- misrepresents what it does, so
        # it gets its own bulk/destructive group instead.
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
        context_menu += [
            None,
            ("smoothtraces_act", "Smooth traces", "", self.smoothTraces),
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
        ("mergeobjects_act", "Merge attributes only", sc, lambda : self.mergeTraces(merge_attrs=True)),
        None,
        ("hidetraces_act", "Hide traces", sc, self.hideTraces),
        ("unhidetraces_act", "Unhide", "", lambda : self.hideTraces(hide=False)),
        None,
        # the shape-editing tail, one group
        ("opentraces_act", "Set open", "", lambda : self.closeTraces(closed=False)),
        ("closedtraces_act", "Set closed", "", self.closeTraces),
        ("makenegative_act", "Make negative", "", self.makeNegative),
        ("makepositive_act", "Make positive", "", lambda : self.makeNegative(False)),
        ("edittraceradius_act", "Edit radius...", "", self.editTraceRadius),
        ("edittraceshape_act", "Edit shape...", "", self.editTraceShape),
        ("smoothtraces_act", "Smooth traces", "", self.smoothTraces),
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
