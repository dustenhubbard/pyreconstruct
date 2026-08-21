"""Context menus, organized as upstream organizes them.

This is the STABLE line. The right-click menus follow upstream's current
structure row for row -- the same containers, the same order, the same labels --
so a user moving between this build and upstream never has to relearn where a
command lives. The fork's menu reorganization work stays on the test line.

Three kinds of deliberate divergence from upstream's file remain, and only
these:

  1. **Shipped rows.** Features this line has already released to users keep
     their menu entry ("Reapply custom color palette to existing objects...",
     "Restore previous visibility", "Hide all objects", "Hide other traces
     (this section)", the zarr label menu, the trace list's "Find in field").
     Each sits in the container upstream's structure implies for it.
  2. **Shortcut fixes.** Bindings are stored per act_name and bound only
     through the field's copy of a menu, so the rows that carry a configured
     key keep the series form ("Set hosts...", "Copy to sections...", the
     edit/merge/hide trace rows, "Add to scene" in the object 3D menu), and
     no act_name is duplicated on one widget -- upstream's five "export3D_act"
     rows silently shadow each other, so the unique names stay.
  3. **Call-site compatibility.** The list widgets on this line pass
     `list_ops` (and the trace list `find_in_field`), so the builders keep
     those parameters and mount them in upstream's utility slot.
"""


from PyReconstruct.modules.gui.utils import getUserColsMenu, getAlignmentsMenu


def collada_menu_label(available=None):
    """Label for the Collada (.dae) export item, flagged when unavailable.

    Collada export needs the optional 'pycollada' package, which frozen
    (PyInstaller) builds never bundle. When it is unavailable the label gains a
    "(not installed)" suffix so the (disabled) item explains itself.
    """
    if available is None:
        from PyReconstruct.modules.backend.volume.export_volumes import (
            collada_available,
        )
        available = collada_available()
    return "Collada (.dae)" if available else "Collada (.dae) (not installed)"


def disable_unavailable_export_formats(widget):
    """Gray out 3D-export formats whose optional dependency is missing."""
    from PyReconstruct.modules.backend.volume.export_volumes import (
        collada_available,
    )
    act = getattr(widget, "export3D_dae_act", None)
    if act is not None and not collada_available():
        act.setEnabled(False)


# Both attributes a "Restore previous visibility" QAction can be stored under
# (the object list's own menubar uses the _act1 copy).
RESTORE_VISIBILITY_ACT_NAMES = (
    "restorevisibility_act",
    "restorevisibility_act1",
)


def sync_restore_visibility_action(widget, has_snapshot):
    """Enable "Restore previous visibility" only when there is one to restore.

    The snapshot is taken by "Hide unselected objects" and consumed by the
    restore; with no isolate behind it the command has nothing to do.
    """
    for act_name in RESTORE_VISIBILITY_ACT_NAMES:
        act = getattr(widget, act_name, None)
        if act is not None:
            act.setEnabled(bool(has_snapshot))


def get_label_menu_list(self):
    """The zarr-label right-click menu (this line's surface; upstream has none)."""
    return [
        ("importlabels_act", "Import labels", "", self.importLabels),
        ("mergelabels_act", "Merge labels", "", self.mergeLabels)
    ]


def get_field_menu_list(self):

    return [
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
            "text": "Ztrace",
            "opts": self.field.getZtraceMenu()
        },
        None,
        {
            "attr_name": "viewmenu",
            "text": "View",
            "opts":
            [
                ("focus_act", "Toggle focus mode", self.series, self.field.toggleFocusMode),
                None,
                ("unhideall_act", "Unhide all traces", self.series, self.field.unhideAllTraces),
                None,
                ("hideall_act", "Toggle hide all", self.series, self.field.toggleHideAllTraces),
                ("showall_act", "Toggle show all", self.series, self.field.toggleShowAllTraces),
                None,
                ("hideimage_act", "Toggle hide image", self.series, self.field.toggleHideImage),
                ("blend_act", "Toggle section blend", self.series, self.field.toggleBlend),
            ]
        },
        getAlignmentsMenu(self.series, self.changeAlignment),
        None,
        self.cut_act,
        self.copy_act,
        # series form: the user-configurable shortcut is looked up by act_name,
        # and this is the binding's only home
        ("copytosections_act", "Copy to sections...", self.series, self.field.copyTracesToSections),
        self.paste_act,
        self.pasteattributes_act,
        None,
        ("selectall_act", "Select all traces", self.series, self.field.selectAllTraces),
        ("deselect_act", "Deselect all traces", self.series, self.field.deselectAllTraces),
        ("invertselection_act", "Invert selection", self.series, self.field.invertTraceSelection),
        None,
        ("delete_act", "Delete", "Del", self.backspace),
    ]


def get_context_menu_list_obj(self, list_ops=None, is_in_field=True):

    # Only the field's copy carries the configurable keys: this menu is built
    # onto the MainWindow and onto the object list's dock, and two QActions
    # with one sequence in one window make Qt fire neither.
    sc = self.series if is_in_field else ""

    return [
        ("editobjattribtues_act", "Edit attributes of traces...", "", self.editAttributes),
        None,
        {
            "attr_name" : "objattrsmenu",
            "text": "Object attributes",
            "opts":
            [
                ("editobjcomment_act", "Comment...", "", self.editComment),
                None,
                # series form: keeps the configured key (default Ctrl+Shift+H)
                # actually bound -- the fix shipped on this line
                ("sethosts_act", "Set host(s)...", sc, self.setHosts),
                ("clearhosts_act", "Clear host(s)...", "", self.clearHosts),
                ("displayinhabitants_act", "Display tree of inhabitants", "", lambda : self.displayHostTree(False)),
                ("displayhosts_act", "Display tree of hosts", "", self.displayHostTree),
                None,
                ("addobjgroup_act", "Add to group...", "", self.addToGroup),
                ("removeobjgroup_act", "Remove from group...", "", self.removeFromGroup),
                ("removeobjallgroups_act", "Remove from all groups", "", self.removeFromAllGroups),
                None,
                ("setobjalignment_act", "Change object alignment...", "", self.editAlignment),
                None,
                ("lockobj_act", "Lock", "", self.lockObjects),
                ("unlockobj_act", "Unlock", "", lambda : self.lockObjects(False)),
                None,
                # Shipped on this line (v1.21.2): reapplies the current palette
                # to objects whose colors were baked in at import time.
                ("reapplyautosegcolors_act", "Reapply custom color palette to existing objects...", "", self.reapplyAutosegColors),
            ]
        },
        {
            "attr_name": "objoperationsmenu",
            "text": "Operations",
            "opts":
            [
                ("copyobj_act", "Create copy of object(s)", "", self.copyObjects),
                ("editobjradius_act", "Edit radius...", "", self.editRadius),
                ("editobjshape_act", "Edit shape...", "", self.editShape),
                None,
                # smoothobj_act, not upstream's smoothtraces_act: the trace menu
                # already stores a QAction under that name on the same widget,
                # and a duplicate silently shadows it.
                ("smoothobj_act", "Smooth object traces", "", self.smoothObject),
                ("splitobj_act", "Split traces into individual objects", "", self.splitObject),
                None,
                ("hideobj_act", "Hide", "", self.hideObj),
                ("unhideobj_act", "Unhide", "", lambda : self.hideObj(False)),
                # Upstream's label; this line's handler and act_name (the
                # snapshot it takes feeds the restore row below).
                ("hideotherobj_act", "Hide unselected objects", "", self.hideOtherObjects),
                # Shipped on this line: the isolate's inverse.
                ("restorevisibility_act", "Restore previous visibility", "", self.restorePreviousVisibility),
                # Shipped on this line, kept beside its opposite.
                ("hideallobj_act", "Hide all objects", "", self.hideAllObjects),
                ("showallobj_act", "Show all objects", "", self.unhideAllObjects),
                None,
                ("removealltags_act", "Remove all tags", "", self.removeAllTags),
                None,
                ("lockobj_act1", "Lock", "", self.lockObjects),
                ("unlockobj_act1", "Unlock", "", lambda : self.lockObjects(False))
            ]
        },
        getUserColsMenu(self.series, self.addUserCol, self.setUserCol, self.editUserCol),
        {
            "attr_name": "curatemenu",
            "text": "Set curation",
            "opts":
            [
                ("blankcurate_act", "Blank", "", lambda : self.bulkCurate("")),
                # instant, assigned to the current user; the dialog moved to
                # the row below so the default costs zero clicks
                ("needscuration_act", "Needs curation", "", lambda : self.bulkCurate("Needs curation")),
                ("needscurationassign_act", "Needs curation (assign to)...", "", self.bulkCurateAssign),
                ("curated_act", "Curated", "", lambda : self.bulkCurate("Curated"))
            ]
        },
        {
            "attr_name": "menu_3D",
            "text": "3D",
            "opts":
            [
                # series form: this row's key (default Ctrl+Shift+D) is bound
                # through the field copy, exactly one claimant per window
                ("addobjto3D_act", "Add to scene", sc, self.addTo3D),
                ("removeobj3D_act", "Remove from scene", "", self.remove3D),
                {
                    "attr_name": "exportobj3D",
                    "text": "Export meshes",
                    "opts":
                    [
                        # unique attr_names per format: upstream's shared
                        # "export3D_act" makes four of five shadow the last
                        ("export3D_obj_act", "Wavefront (.obj)", "", lambda : self.exportAs3D("obj")),
                        ("export3D_off_act", "Object File Format (.off)", "", lambda : self.exportAs3D("off")),
                        ("export3D_ply_act", "Stanford PLY (.ply)", "", lambda : self.exportAs3D("ply")),
                        ("export3D_stl_act", "Stl (.stl)", "", lambda : self.exportAs3D("stl")),
                        ("export3D_dae_act", collada_menu_label(), "", lambda : self.exportAs3D("dae")),
                    ]

                    },
                ("exportmeshdata", "Export quantitative data", "", self.export3DData),
                None,
                ("editobj3D_act", "Edit 3D settings...", "", self.edit3D)
            ]
        },
        {
            "attr_name": "objztracemenu",
            "text": "Create ztrace",
            "opts":
            [
                ("csztrace_act", "On contour midpoints", "", self.createZtrace),
                ("atztrace_act", "From trace sequence", "", lambda : self.createZtrace(cross_sectioned=False)),
            ]
        },
        None,
        ("objhistory_act", "View history", "", self.viewHistory),
        None,
        ("setpaletteobj_act", "Copy attributes to palette", "", self.setPaletteButtonFromObj),
        # table utilities (the object list passes them; the field passes none)
        *([None] + list(list_ops) if list_ops else []),
        None,
        ("deleteobj_act", "Delete", "", self.deleteObjects)
    ]


def get_context_menu_list_trace(self, is_in_field=True, list_ops=None, find_in_field=None):

    # only allow shortcuts to be connected through the field
    sc = self.series if is_in_field else ""

    context_menu = [
        ("edittrace_act", "Edit attributes...", sc, self.traceDialog),
    ]

    # "Copy to sections..." lives at the field context-menu top level (next to
    # "Copy") when invoked in the field; in the trace list it appears here.
    if not is_in_field:
        context_menu.append(
            ("copytosections_act", "Copy to sections...", "", self.copyTracesToSections)
        )

    context_menu += [
        None,
        ("smoothtraces_act", "Smooth traces", "", self.smoothTraces),
        ("mergetraces_act", "Merge traces", sc, self.mergeTraces),
        ("mergeobjects_act", "Merge attributes", sc, lambda : self.mergeTraces(merge_attrs_only=True)),
        None,
        ("makenegative_act", "Make negative", "", self.makeNegative),
        ("makepositive_act", "Make positive", "", lambda : self.makeNegative(False)),
        None,
        ("hidetraces_act", "Hide", sc, self.hideTraces),
    ]

    if is_in_field:
        # Shipped on this line: current-section isolate (distinct from the
        # object menu's series-wide "Hide unselected objects").
        context_menu += [
            ("hideothertraces_act", "Hide other traces (this section)", "", self.hideOtherTraces),
        ]

    if not is_in_field:

        context_menu += [
            ("unhidetraces_act", "Unhide", "", lambda : self.hideTraces(hide=False))
        ]

        context_menu += [
            None,
            ("opentraces_act", "Set open", "", lambda : self.closeTraces(closed=False)),
            ("closedtraces_act", "Set closed", "", self.closeTraces),
            None,
            ("edittraceshape_act", "Edit shape...", "", self.editTraceShape),
            ("edittraceradius_act", "Edit radius...", "", self.editTraceRadius),
            None,
            ("createtraceflag_act", "Create flag...", "", self.createTraceFlag),
        ]

        # Shipped on this line: the trace list's jump-to-field row.
        if find_in_field is not None:
            context_menu += [
                ("findinfield_act", "Find in field", "", find_in_field),
            ]

        # table utilities, in the slot every list shares
        if list_ops:
            context_menu += [None] + list(list_ops)

        context_menu += [
            None,
            ("deletetrace_act", "Delete", "", self.deleteTraces)  # accessible elswhere in the field context menu
        ]

    return context_menu
