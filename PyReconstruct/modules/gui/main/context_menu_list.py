"""Context menus."""


from PyReconstruct.modules.gui.utils import getUserColsMenu, getAlignmentsMenu


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
        ("delete_act", "Delete selected", "Del", self.backspace),
    ]


def get_context_menu_list_obj(self):

    return [
        ("editobjattribtues_act", "Edit object attributes...", "", self.editAttributes),
        None,
        {
            "attr_name" : "objattrsmenu",
            "text": "Attributes",
            "opts":
            [
                ("editobjcomment_act", "Comment...", "", self.editComment),
                None,
                ("sethosts_act", "Set hosts...", "", self.setHosts),
                ("clearhosts_act", "Clear hosts", "", self.clearHosts),
                ("displayinhabitants_act", "Show inhabitant tree", "", lambda : self.displayHostTree(False)),
                ("displayhosts_act", "Show host tree", "", self.displayHostTree),
                None,
                ("addobjgroup_act", "Add to group...", "", self.addToGroup),
                ("removeobjgroup_act", "Remove from group...", "", self.removeFromGroup),
                ("removeobjallgroups_act", "Remove from all groups", "", self.removeFromAllGroups),
                None,
                ("setobjalignment_act", "Edit alignment...", "", self.editAlignment),
                None,
                # Lock/Unlock lives here as its single home (it is a stored
                # object attribute); do NOT re-add it to another submenu.
                ("lockobj_act", "Lock", "", self.lockObjects),
                ("unlockobj_act", "Unlock", "", lambda : self.lockObjects(False))
            ]
        },
        {
            "attr_name": "objvisibilitymenu",
            "text": "Visibility",
            "opts":
            [
                ("hideobj_act", "Hide", "", self.hideObj),
                ("unhideobj_act", "Unhide", "", lambda : self.hideObj(False)),
                ("hideotherobj_act", "Hide other objects", "", self.hideOtherObjects),
                ("hideallobj_act", "Hide all objects", "", self.hideAllObjects),
                ("showallobj_act", "Show all objects", "", self.unhideAllObjects),
            ]
        },
        {
            "attr_name": "objgeometrymenu",
            "text": "Geometry",
            "opts":
            [
                ("copyobj_act", "Duplicate object", "", self.copyObjects),
                ("editobjradius_act", "Edit radius...", "", self.editRadius),
                ("editobjshape_act", "Edit shape...", "", self.editShape),
                None,
                ("smoothtraces_act", "Smooth traces", "", self.smoothObject),
                ("splitobj_act", "Split into separate objects", "", self.splitObject),
                None,
                ("removealltags_act", "Remove all tags", "", self.removeAllTags),
            ]
        },
        getUserColsMenu(self.series, self.addUserCol, self.setUserCol, self.editUserCol),
        {
            "attr_name": "curatemenu",
            "text": "Set curation",
            "opts":
            [
                ("blankcurate_act", "Clear status", "", lambda : self.bulkCurate("")),
                ("needscuration_act", "Needs curation", "", lambda : self.bulkCurate("Needs curation")),
                ("curated_act", "Curated", "", lambda : self.bulkCurate("Curated"))
            ]
        },
        {
            "attr_name": "menu_3D",
            "text": "3D",
            "opts":
            [
                ("addobjto3D_act", "Add to scene", "", self.addTo3D),
                ("removeobj3D_act", "Remove from scene", "", self.remove3D),
                {
                    "attr_name": "exportobj3D",
                    "text": "Export mesh as",
                    "opts":
                    [
                        # unique attr_names per format (previously all "export3D_act",
                        # so four of five silently shadowed the last on the widget).
                        # Collada requires the optional 'pycollada' package; the
                        # export handler surfaces that requirement gracefully
                        # (export_volumes.export3DObjects), so the dependency note
                        # is no longer crammed into the label.
                        ("export3D_obj_act", "Wavefront (.obj)", "", lambda : self.exportAs3D("obj")),
                        ("export3D_off_act", "Object File Format (.off)", "", lambda : self.exportAs3D("off")),
                        ("export3D_ply_act", "Stanford PLY (.ply)", "", lambda : self.exportAs3D("ply")),
                        ("export3D_stl_act", "STL (.stl)", "", lambda : self.exportAs3D("stl")),
                        ("export3D_dae_act", "Collada (.dae)", "", lambda : self.exportAs3D("dae")),
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
        ("objhistory_act", "View history", "", self.viewHistory),
        None,
        ("setpaletteobj_act", "Copy attributes to palette", "", self.setPaletteButtonFromObj),
        None,
        ("deleteobj_act", "Delete objects", "", self.deleteObjects)
    ]


def get_context_menu_list_trace(self, is_in_field=True):

    # only allow shortcuts to be connected through the field
    
    sc = self.series if is_in_field else ""
    
    context_menu = [
        ("edittrace_act", "Edit trace attributes...", sc, self.traceDialog),
    ]

    # "Copy to sections..." lives at the field context-menu top level (next to
    # "Copy") when invoked in the field; in the trace list it stays here.
    if not is_in_field:
        context_menu.append(
            ("copytosections_act", "Copy to sections...", "", self.copyTracesToSections)
        )

    context_menu += [
        None,
        ("smoothtraces_act", "Smooth traces", "", self.smoothTraces),
        ("mergetraces_act", "Merge traces", sc, self.mergeTraces),
        ("mergeobjects_act", "Merge attributes only", sc, lambda : self.mergeTraces(merge_attrs=True)),
        None,
        ("makenegative_act", "Make negative", "", self.makeNegative),
        ("makepositive_act", "Make positive", "", lambda : self.makeNegative(False)),
        None,
        ("hidetraces_act", "Hide traces", sc, self.hideTraces),
    ]

    # field only: current-section "hide the rest" (distinct from the volume-wide
    # object action). Menu-only, so no shortcut is bound.
    if is_in_field:
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
        
        if not is_in_field:
            
            context_menu += [
                None,
                ("deletetrace_act", "Delete traces", "", self.deleteTraces)  # accessible elswhere in the field context menu
            ]
        
    return context_menu
