from PyReconstruct.modules.gui.utils import getOpenRecentMenu, getGroupsMenu

from PyReconstruct.modules.constants import (
    kh_web,
    kh_atlas,
    gh_repo,
    gh_wiki,
    gh_issues,
    gh_submit,
    developers_mailto_str,
    repo_string
)


def return_file_menu(self):
    """Return file menu."""

    return {
        "attr_name": "filemenu",
        "text": "File",
        "opts":
        [   
            {
                "attr_name": "newseriesmenu",
                "text": "New series",
                "opts":
                [
                    ("newfromimages_act", "From images...", self.series, self.newSeries),
                    ("newfromzarr_act", "From scaled images...", "", lambda : self.newSeries(from_zarr=True)),
                    ("newfromxml_act", "From legacy .ser...", "", self.newFromXML),
                    ("newfromngzarr_act", "From neuroglancer zarr...", "", self.newFromNgZarr),
                ]
            },
            ("open_act", "Open series...", self.series, self.openSeries),
            getOpenRecentMenu(self.series, self.openSeries, self.clearRecentSeries),
            ("close_act", "Close series", "", self.openWelcomeSeries),
            None,  # None acts as menu divider
            ("save_act", "Save", self.series, self.saveToJser),
            ("saveas_act", "Save as...", "", self.saveAsToJser),
            {
                "attr_name": "projectsmenu",
                "text": "Utilities",
                "opts":
                [
                    ## The optional 5th tuple element is a hover tooltip
                    ## (see newAction). Utilities holds niche, rarely used
                    ## features, so each entry explains itself to someone who
                    ## has never run it. Keep the copy true to the scripts in
                    ## assets/scripts/projects/.
                    (
                        "random_act", "Randomize project...", "",
                        self.randomizeProject,
                        (
                            "Prepare a project for blind analysis: images from each series\n"
                            "subfolder are pooled under randomized code names and a single\n"
                            "coded .jser is created for tracing.\n\n"
                            "The name key is written to decode.txt in the project folder --\n"
                            "keep it, as de-randomizing needs it."
                        ),
                    ),
                    (
                        "derandom_act", "De-randomize project...", "",
                        self.derandomizeProject,
                        (
                            "Reverse a randomized project once tracing is done: original\n"
                            "image names are restored from decode.txt and the coded .jser\n"
                            "is split into one series per original subfolder.\n\n"
                            "The coded files are kept in a dated 'decoded-' folder."
                        ),
                    ),
                ]
            },
            {
                "attr_name": "backupmenu",
                "text": "Backup",
                "opts":
                [
                    ("manualbackup_act", "Backup now...", self.series, self.manualBackup),
                    ("setbackup_act", "Settings...", "", self.setBackup),
                ]
            },
            {
                "attr_name": "exportmenu",
                "text": "Export series",
                "opts":
                [
                    ("exportxml_act", "To legacy Reconstruct (XML)...", "", self.exportToXML),
                    ("exportngzarr_act", "To Neuroglancer (Zarr)...", "", self.exportToZarr)
                ]
            },
            None,
            ("username_act", "Change username...", "", self.changeUsername),
            None,
            ("restart_act", "Restart PyReconstruct", self.series, self.restart),
            ("quit_act", "Quit", self.series, self.close),
            ##("test_act", "Test", "", self.test),
        ]
    }


def return_edit_menu(self):
    """Return edit menu."""

    return {
        "attr_name": "editmenu",
        "text": "Edit",
        "opts":
        [
            ("undo_act", "Undo", self.series, self.undo),
            ("redo_act", "Redo", self.series, lambda : self.undo(True)),
            None,
            ("cut_act", "Cut", self.series, self.field.cut),
            ("copy_act", "Copy", self.series, self.copy),
            ("paste_act", "Paste", self.series, self.field.paste),
            ("pasteattributes_act", "Paste attributes", self.series, self.field.pasteAttributes),
            None,
            ("pastetopalette_act", "Paste attributes to palette", self.series, self.pasteAttributesToPalette),
            ("pastetopalettewithshape_act", "Paste attributes to palette (+shape)", self.series, lambda : self.pasteAttributesToPalette(True)),
            None,
            {
                "attr_name": "bcmenu",
                "text": "Brightness/contrast",
                "opts":
                [
                    ("incbr_act", "Increase brightness", self.series, lambda : self.editImage(option="brightness", direction="up")),
                    ("decbr_act", "Decrease brightness", self.series, lambda : self.editImage(option="brightness", direction="down")),
                    ("inccon_act", "Increase contrast", self.series, lambda : self.editImage(option="contrast", direction="up")),
                    ("deccon_act", "Decrease contrast", self.series, lambda : self.editImage(option="contrast", direction="down"))
                ]
            }
        ]
    }


def return_series_menu(self):
    """Return series menu."""

    return {
        "attr_name": "seriesmenu",
        "text": "Series",
        "opts":
        [
            ("alloptions_act", "Options...", self.series, self.allOptions),
            {
                "attr_name": "importmenu",
                "text": "Import series data",
                "opts":
                [
                    ("importfromseries_act", "From another series...", "", self.importFromSeries),
                    ("importfromzarrlabels_act", "From neuroglancer zarr labels...", "", self.importFromZarrLabels),
                ]
            },
            {
                "attr_name": "imagesmenu",
                "text": "Images",
                "opts":
                [
                    ("change_src_act", "Find/change image directory", "", self.changeSrcDir),
                    ("zarrimage_act", "Convert to scaled images", "", self.srcToZarr),
                    ("scalezarr_act", "Update image scales", "", lambda : self.srcToZarr(create_new=False)),
                ]
            },
            {
                "attr_name": "serieshidemenu",
                "text": "Hide",
                "opts":
                [
                    ("hidealltraces_act", "Hide all traces (entire series)", "", self.hideSeriesTraces),
                    ("unhidealltraces_act", "Unhide all traces (entire series)", "", lambda : self.hideSeriesTraces(hidden=False))
                ]
            },
            {
                "attr_name": "serieslogmenu",
                "text": "Log",
                "opts":
                [
                    ("offloadlog_act", "Offload log history...", "", self.offloadLog),
                ]
            },
            {
                "attr_name": "threedeemenu",
                "text": "3D",
                "opts":
                [
                    ("load3Dscene_act", "Load 3D scene...", "", self.load3DScene),
                ]
            },
            {
                "attr_name": "tracepalette_menu",
                "text": "Trace palette",
                "opts":
                [
                    ("modifytracepalette_act", "Edit all palettes...", self.series, self.mouse_palette.modifyAllPaletteButtons),
                    ("resettracepalette_act", "Reset current palette", "", self.resetTracePalette),
                    None,
                    ("exporttracepalette_act", "Export as CSV...", "", self.exportTracePaletteCSV),
                    ("importtracepalettecsv_act", "Import from CSV...", "", self.importTracePaletteCSV),
                ]
            },
            {
                "attr_name": "calibrationmenu",
                "text": "Calibration",
                "opts":
                [
                    ("calibrate_act", "Calibrate pixel size...", "", self.calibrateMag),
                    ("setmag_act", "Manually set pixel mag...", "", self.setSeriesMag),
                ]
            },
            {
                "attr_name": "seriescodemenu",
                "text": "Series code",
                "opts":
                [
                    ("setseriescode_act", "Set series code...", "", self.setSeriesCode),
                    ("seriescodepattern_act", "Edit regex pattern...", "", self.editSeriesCodePattern),
                ]
            },
            None,
            ("findobjectfirst_act", "Find first object contour...", self.series, self.findObjectFirst),
            {
                "attr_name": "cleanupmenu",
                "text": "Clean up",
                "opts":
                [
                    ("removeduplicates_act", "Remove duplicate traces...", "", self.deleteDuplicateTraces),
                    ("finddiffnamedduplicates_act", "Find duplicates named differently...", "", self.findDifferentlyNamedDuplicates),
                    ("removepixeldust_act", "Remove pixel-dust traces...", "", self.removePixelDustTraces),
                    ("removeempty_act", "Remove empty traces...", "", self.removeEmptyTraces),
                    ("repairselfcrossings_act", "Repair self-crossing traces...", "", self.repairSelfCrossingTraces),
                ]
            },
            None,
            ("updatecuration_act", "Restore object curation status from log", "", self.updateCurationFromHistory),
            None,
            ("bcprofiles_act", "Brightness/contrast profiles...", "", self.changeBCProfiles),
            None,
            ("about_act", "About this series...", "", self.displayAbout),
        ]
    }


def return_section_menu(self):

    return {
        "attr_name": "sectionmenu",
        "text": "Section",
        "opts":
        [
            ("nextsection_act", "Next section", "PgUp", self.incrementSection),
            ("prevsection_act", "Previous section", "PgDown", lambda : self.incrementSection(down=True)),
            None,
            ("goto_act", "Go to section...", self.series, self.changeSection),
            None,
            ("flicker_act", "Flicker section", self.series, self.flickerSections),
            None,
            ("findcontour_act", "Find contour...", self.series, self.field.findContourDialog),
            ("addscalebar", "Add scalebar...", "", self.addScaleBar),
            {
                "attr_name": "importsecmenu",
                "text": "Import",
                "opts":
                [
                    ("importroi_act", "From ImageJ .roi files...", "", self.importROIFiles)
                ]
            },
            {
                "attr_name": "exportsecmenu",
                "text": "Export",
                "opts":
                [
                    ("exportsvg_act", "As .svg...", "", self.exportSectionSVG),
                    ("exportpng_act", "As .png...", "", self.exportSectionPNG),
                    ("exportroi_act", "As .roi...", "", self.exportROIFiles)
                ]
            }
        ]
    }


def return_list_menu(self):
    """Return list menu."""

    return {
        "attr_name": "listsmenu",
        "text": "Lists",
        "opts":
        [
            ("objectlist_act", "Object list", self.series, lambda : self.field.openList(list_type="object")),
            ("tracelist_act", "Trace list", self.series, lambda : self.field.openList(list_type="trace")),
            ("sectionlist_act", "Section list", self.series, lambda : self.field.openList(list_type="section")),
            ("ztracelist_act", "Z-trace list", self.series, lambda : self.field.openList(list_type="ztrace")),
            ("flaglist_act", "Flag list", self.series, lambda : self.field.openList(list_type="flag")),
            ("history_act", "Series history", "", self.viewSeriesHistory)
        ]
    }


def return_alignments_menu(self):
    """Return alignments menu."""

    return {
        "attr_name": "alignmentsmenu",
        "text": "Alignments",
        "opts":
        [
            ("changealignment_act", "Edit alignments...", self.series, self.modifyAlignments),
            None,
            {
                "attr_name": "importalignmentsmenu",
                "text": "Import alignments",
                "opts":
                [
                    ## "From another series" is first because it is the common
                    ## case (taking a colleague's alignment) and because it was
                    ## previously only reachable through Series > Import series
                    ## data, where a user looking for an alignment import does
                    ## not think to look.
                    ("import_jser_alignments_act", "From another series (.jser)...", "", self.importAlignmentsFromSeries),
                    ("importtransforms_act", "From .txt file...", "", self.importTransforms),
                    ("import_swift_transforms_act", "From SWiFT project...", "", self.importSwiftTransforms),
                ]
            },
            None,
            {
                "attr_name": "propagatemenu",
                "text": "Propagate transform",
                "opts":
                [
                    ("startpt_act", "Start propagation recording", "", lambda : self.field.setPropagationMode(True)),
                    ("endpt_act", "End propagation recording", "", lambda : self.field.setPropagationMode(False)),
                    None,
                    ("proptostart_act", "Propagate to start", "", lambda : self.field.propagateTo(False)),
                    ("proptoend_act", "Propagate to end", "", lambda : self.field.propagateTo(True))
                ]
            },
            None,
            ("unlocksection_act", "Unlock current section", self.series, self.field.unlockSection),
            ("changetform_act", "Edit transformation...", self.series, self.changeTform),
            ("linearalign_act", "Estimate affine transform", "", self.field.affineAlign),
            ("aligncorrelation_act", "Align by correlation", "Ctrl+\\", self.field.corrAlign),
            # ("quickalign_act", "Auto-align", "Ctrl+\\", self.field.quickAlign)
        ]
    }


def return_autoseg_menu(self):
    """Return autoseg menu."""

    return {
        "attr_name": "autosegmenu",
        "text": "Autosegment",
        "opts":
        [
            ("export_zarr_act", "Export to zarr...", "", self.exportToZarr),
            ("trainzarr_act", "Train...", "", self.train),
            ("retrainzarr_act", "Retrain...", "", lambda : self.train(retrain=True)),
            ("predictzarr_act", "Predict (infer)...", "", self.predict),
            ("sementzarr_act", "Segment...", "", self.segment),
            {
                "attr_name": "zarrlayermenu",
                "text": "Zarr layer",
                "opts":
                [
                    ("setzarrlayer_act", "Set zarr layer...", "", self.setZarrLayer),
                    ("removezarrlayer_act", "Remove zarr layer", "", self.removeZarrLayer)
                ]
            }
        ]
    }


def return_view_menu(self):
    """Return view menu."""
    
    view_menu = {
        "attr_name": "viewmenu",
        "text": "View",
        "opts":
        [
            # remappable; also the Lists pill in the status bar. Collapse
            # hides the docked lists, the next toggle brings the same set back.
            ("togglelists_act", "Show/hide lists", self.series, self.toggleLists),
            None,
            ("copyscreen_act", "Copy view to clipboard", "", lambda : self.saveFieldView(False)),
            ("savescreen_act", "Save view to file", "", lambda : self.saveFieldView(True)),
            None,
            ("changetheme_act", "Change theme...", "", self.setTheme),
            None,
            ("fillopacity_act", "Edit fill opacity...", "", self.setFillOpacity),
            # Series-wide sibling of the object menus' selection-scoped
            # "Reapply custom color palette to existing objects..." (added 2026-08-12, his placement
            # call). It sits beside "Edit fill opacity..." because that is the
            # one View section about how every object is painted; it is also
            # the only row in this menu that edits series data, which its
            # confirm dialog owns up to. Locked objects are SKIPPED rather
            # than a blocker (an abort would make a series-wide pass useless
            # the moment one object is locked), the dialog states the split,
            # and the whole pass is one undo. No shortcut: a rare, confirmed
            # bulk action does not earn a key.
            ("recolorallfrompalette_act", "Recolor all objects from palette...", "", self.recolorAllObjectsFromPalette),
            None,
            ("homeview_act", "Set view to image", self.series, self.field.home),
            ("viewmag_act", "View magnification...", "", self.field.setViewMagnification),
            ("findview_act", "Set zoom when finding contours...", "", self.setFindZoom),
            None,
            # Checkable, mirroring the live show_ztraces option (see
            # MainWindow.checkActions / createMenuBar for the resync). The
            # (series, "checkbox") form keeps it configurable-shortcut-capable
            # like the field View toggles; its option default is "" (no key).
            ("toggleztraces_act", "Show z-traces", (self.series, "checkbox"), self.toggleZtraces),
            # Hoisted out of View > Palette > Visibility (2026-08-06 decision).
            # These four were three levels deep, so setting up a workspace cost
            # a fresh descent per toggle; #205's keep-menu-open filter removed
            # the reopening but not the descent. They sit with "Show z-traces"
            # because that is the same question -- what is currently visible --
            # and the group stays contiguous and in its original relative order.
            # The Palette submenu below keeps its palette-scoped items.
            ("togglepalette_act", "Trace palette", "checkbox", self.mouse_palette.togglePalette),
            ("toggleinc_act",  "Section increment buttons", "checkbox", self.mouse_palette.toggleIncrement),
            ("togglebc_act", "Brightness/contrast sliders", "checkbox", self.mouse_palette.toggleBC),
            ("togglesb_act", "Scale bar", "checkbox", self.mouse_palette.toggleSB),
            None,
            {
                "attr_name": "palettemenu",
                "text": "Palette",
                "opts":
                [
                    {
                        "attr_name": "incpalettemenu",
                        "text": "Increment palette buttons",
                        "opts":
                        [
                            ("incpaletteup_act", "Up", self.series, lambda : self.mouse_palette.incrementPalette(True)),
                            ("incpalettedown_act", "Down", self.series, lambda : self.mouse_palette.incrementPalette(False)),
                        ]
                    },
                    ("resetpalette_act", "Reset palette position", "", self.mouse_palette.resetPos),
                ]
            },
            # Sits directly under Palette because "Reset palette position" is
            # the item it is a sibling of: both put a piece of the window
            # furniture back where it started. Kept out of the Palette submenu,
            # which is palette-scoped, and out of File/Help, which are neither
            # about the view. No shortcut: the window it rescues is one the user
            # can still reach the menubar of.
            ("resetwindow_act", "Reset window", "", self.resetWindowGeometry),
            ("lefthanded_act", "Left handed", "checkbox", self.field.setLeftHanded),
            None,
            ("togglecuration_act", "Toggle curation in object lists", self.series, self.toggleCuration),
        ]
    }

    obj_groups = self.series.object_groups.groups

    if(obj_groups):
        
        view_menu["opts"].append(
            getGroupsMenu(self)

        )

    return view_menu


def _other_flavor_label(self=None):
    """Menu text for the cross-flavor download row, decided by this build."""
    from PyReconstruct.modules.datatypes.series_owner import app_display_name
    if "Dev" in app_display_name():
        return "Download PyReconstruct (stable)..."
    return "Download PyReconstruct Dev (beta)..."


def return_help_menu(self):
    """Return help menu.

    Ordered in five groups, separator between each (his layout call,
    2026-08-26): the search field, then what this build IS, then updates,
    then the What's-new pop-up, then everything else unchanged. The search
    field itself is inserted at the very top by MainWindow.createMenuBar,
    which also focuses it when Help opens.
    """

    return {
        "attr_name": "helpmenu",
        "text": "Help",
        "opts":
        [
            # 1. the search field's remappable keyboard carrier. The visible
            # field is a QWidgetAction inserted above this row in
            # createMenuBar; a QWidgetAction cannot take the series-form
            # shortcut lookup, so the key lives here.
            # series form: the key is user-configurable, looked up by act_name
            ("searchmenus_act", "Search menus...", self.series, self.openMenuSearch),
            None,
            # 2. what this build is: version and commit, copied on click
            ("repobranch_act", repo_string, "", self.copyCommit),
            None,
            # 3. updates
            ("checkupdates_act", "Check for updates...", "", self.checkForUpdates),
            # Checkable, mirroring the update_check_on_startup series option.
            # It resyncs on every Help open because the option follows the
            # open series, not this window.
            ("toggleupdatecheck_act", "Automatically check for updates", "checkbox",
             self.toggleUpdateCheckOnStartup),
            # The other build's download page, labeled by what THIS build is:
            # the stable app offers Dev, the Dev app offers stable. Resolved
            # when clicked (updater.other_flavor_url), so it always points at
            # the latest of the other flavor.
            ("getotherflavor_act", _other_flavor_label(), "", self.openOtherFlavorPage),
            None,
            # 4. the What's-new pop-up
            ("whatsnew_act", "What's new?", "", self.showWhatsNew),
            # Checkable, mirroring the stored suppress_whatsnew preference the
            # dialog's "Don't show again" button also writes. Unlike the
            # menubar's other checkables this one resyncs on every Help open
            # (see MainWindow.createMenuBar), because the dialog can flip the
            # preference behind the menu's back.
            ("togglewhatsnew_act", "Show what's new after updates", "checkbox",
             self.toggleWhatsNewPopup),
            None,
            # 5. the rest, unchanged
            ("shortcutshelp_act", "Shortcuts list", "?", self.displayShortcuts),
            None,
            {
                "attr_name": "onlinemenu",
                "text": "Online resources",
                "opts": [
                    ("openwiki_act", "PyReconstruct user guide", "", lambda : self.openWebsite(gh_wiki)),
                    ("openrepo_act", "PyReconstruct source code", "", lambda : self.openWebsite(gh_repo)),
                    ("openkhlab_act", "KH lab website", "", lambda : self.openWebsite(kh_web)),
                    ("openkhatlast_act", "Atlas of Ultrastructural Neurocytology", "", lambda : self.openWebsite(kh_atlas)),
                    ("download2015", "Harris2015 example images", "", self.downloadExample)
                ]
            },
            {
                "attr_name": "issuemenu",
                "text": "Report issues (GitHub)",
                "opts":
                [
                    ("copydiag_act", "Copy diagnostic report...", "", self.copyDiagnosticReport),
                    ("viewlog_act", "View log file...", "", self.viewLogFile),
                    ("openlogdir_act", "Open log folder", "", self.openLogFolder),
                    ("submitissue_act", "Report bug / Request feature", "", lambda : self.openWebsite(gh_submit)),
                    ("seeissues_act", "See unresolved issues", "", lambda : self.openWebsite(gh_issues))
                ]
            },
            ("emailteam_act", "Email developers", "", lambda : self.openWebsite(developers_mailto_str)),
        ]
    }


def return_menubar(self):
    """Return the complete menubar."""

    return [
        return_file_menu(self),
        return_edit_menu(self),
        return_series_menu(self),
        return_section_menu(self),
        return_list_menu(self),
        return_alignments_menu(self),
        ##return_autoseg_menu(self),
        return_view_menu(self),
        return_help_menu(self)
    ]
