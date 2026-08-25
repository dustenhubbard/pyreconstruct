"""Menubar label pass: verbs given their objects (File and Series menus).

Note on MENUBAR_EXPECTED, updated after this module was first written: the
baseline is a losslessness guard, so sanctioned ADDITIONS are folded in beside
it rather than treated as failures. Each one is annotated at the point it is
inserted. The list of additions grew by one when the alignment sources were
gathered under Alignments > Import alignments; see the comment there.


Six menubar labels were reported as "a verb with no object" -- the user cannot
tell what the item acts on. They are renamed here; nothing is moved, nothing is
removed, and one item is added ("Clear recents", which did not exist).

The context-menu work (PR #107) proved its own losslessness with an explicit
112-action inventory in ``tests/test_context_menu_frequency.py``. The menubar had
no equivalent guard at all, so this module adds one: ``MENUBAR_BASELINE`` is the
complete tree of ``main/menubar.py`` as it stood on the commit before the rename
(``51e9a85``), captured as (depth, kind, attr_name) rows. Labels are free to
change; the tree is not. That is what makes a rename provably lossless -- and it
is what will catch the next reorganization that drops a row by accident.

Two facts the labels now rest on, both read out of the code rather than assumed:

* ``restart_act`` ("Reload") reloads every ``PyReconstruct.modules`` module and
  recreates the main window (``MainWindow.restart`` -> ``run.py``'s restart
  loop). It restarts the application; it does not reload the series. The
  shortcuts dialog already called it "Restart".
* ``openrecentmenu`` is ordered most-recently-*opened* first, because
  ``MainWindow.addToRecentSeries`` inserts at index 0 and ``getOpenRecentMenu``
  walks the list in order. It is not ordered by file mtime.
"""

import pytest


# --------------------------------------------------------------------------- #
# stubs -- build the real menu definitions without a Qt event loop
# --------------------------------------------------------------------------- #
class _Anything:
    """Any attribute access yields a callable returning an empty list, so
    submenu builders return something iterable and callbacks are harmless."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


class _SeriesStub(_Anything):
    """Enough Series surface for the menubar builders, with a real option dict
    so the recently-opened list can be seeded and observed."""

    def __init__(self, recents=None, jser_fp="/nonexistent/current.jser"):
        super().__init__(
            jser_fp=jser_fp,
            object_groups=_Anything(groups={}),
            groups_visibility={},
            user_columns={},
            alignments=set(),
        )
        self.opts = {"recently_opened_series": list(recents or [])}

    def getOption(self, name, get_default=False):
        return self.opts.get(name, "")

    def setOption(self, name, value):
        self.opts[name] = value


class _MainWindowStub(_Anything):
    def __init__(self, series=None):
        super().__init__(
            series=series if series is not None else _SeriesStub(),
            field=_Anything(),
            mouse_palette=_Anything(),
        )


def _menubar(series=None):
    from PyReconstruct.modules.gui.main.menubar import return_menubar

    return return_menubar(_MainWindowStub(series))


def _walk(items, depth=0):
    """Flatten a menu tree to (depth, kind, attr_name, label) rows."""
    for item in items:
        if item is None:
            yield (depth, "sep", None, None)
        elif isinstance(item, tuple):
            yield (depth, "act", item[0], item[1])
        elif isinstance(item, dict):
            yield (depth, "menu", item["attr_name"], item["text"])
            yield from _walk(item["opts"], depth + 1)
        else:  # pragma: no cover -- would be a new item kind
            raise AssertionError(f"unexpected menu item: {item!r}")


def _rows(series=None):
    return list(_walk(_menubar(series)))


def _labels(series=None):
    return {attr: text for _d, kind, attr, text in _rows(series) if kind != "sep"}


def _submenu(items, attr_name):
    """Return the opts list of the submenu with this attr_name."""
    for item in items:
        if isinstance(item, dict):
            if item["attr_name"] == attr_name:
                return item["opts"]
            found = _submenu(item["opts"], attr_name)
            if found is not None:
                return found
    return None


# --------------------------------------------------------------------------- #
# 1. the inventory guard: structure frozen, labels free
# --------------------------------------------------------------------------- #
# The complete menubar of fork/main @ 51e9a85 -- (depth, kind, attr_name) for
# every row, separators included, in order. Built with no object groups (the
# View menu appends a dynamic "Groups" submenu when the series has any) and no
# recently opened series.
#
# One deliberate attr_name change since capture, commented in place below:
# the Alignments import submenu is "importalignmentsmenu" (was "importmenu",
# a duplicate of the Series one).
MENUBAR_BASELINE = [
    (0, "menu", "filemenu"),
    (1, "menu", "newseriesmenu"),
    (2, "act", "newfromimages_act"),
    (2, "act", "newfromzarr_act"),
    (2, "act", "newfromxml_act"),
    (2, "act", "newfromngzarr_act"),
    (1, "act", "open_act"),
    (1, "menu", "openrecentmenu"),
    (1, "act", "close_act"),
    (1, "sep", None),
    (1, "act", "save_act"),
    (1, "act", "saveas_act"),
    (1, "menu", "projectsmenu"),
    (2, "act", "random_act"),
    (2, "act", "derandom_act"),
    (1, "menu", "backupmenu"),
    (2, "act", "manualbackup_act"),
    (2, "act", "setbackup_act"),
    (1, "menu", "exportmenu"),
    (2, "act", "exportxml_act"),
    (2, "act", "exportngzarr_act"),
    (1, "sep", None),
    (1, "act", "username_act"),
    (1, "sep", None),
    (1, "act", "restart_act"),
    (1, "act", "quit_act"),
    (0, "menu", "editmenu"),
    (1, "act", "undo_act"),
    (1, "act", "redo_act"),
    (1, "sep", None),
    (1, "act", "cut_act"),
    (1, "act", "copy_act"),
    (1, "act", "paste_act"),
    (1, "act", "pasteattributes_act"),
    (1, "sep", None),
    (1, "act", "pastetopalette_act"),
    (1, "act", "pastetopalettewithshape_act"),
    (1, "sep", None),
    (1, "menu", "bcmenu"),
    (2, "act", "incbr_act"),
    (2, "act", "decbr_act"),
    (2, "act", "inccon_act"),
    (2, "act", "deccon_act"),
    (0, "menu", "seriesmenu"),
    (1, "act", "alloptions_act"),
    (1, "menu", "importmenu"),
    (2, "act", "importfromseries_act"),
    (2, "act", "importfromzarrlabels_act"),
    (1, "menu", "imagesmenu"),
    (2, "act", "change_src_act"),
    (2, "act", "zarrimage_act"),
    (2, "act", "scalezarr_act"),
    (1, "menu", "serieshidemenu"),
    (2, "act", "hidealltraces_act"),
    (2, "act", "unhidealltraces_act"),
    (1, "menu", "serieslogmenu"),
    (2, "act", "offloadlog_act"),
    (1, "menu", "threedeemenu"),
    (2, "act", "load3Dscene_act"),
    (1, "menu", "tracepalette_menu"),
    (2, "act", "modifytracepalette_act"),
    (2, "act", "resettracepalette_act"),
    (2, "sep", None),
    (2, "act", "exporttracepalette_act"),
    (2, "act", "importtracepalettecsv_act"),
    (1, "menu", "calibrationmenu"),
    (2, "act", "calibrate_act"),
    (2, "act", "setmag_act"),
    (1, "menu", "seriescodemenu"),
    (2, "act", "setseriescode_act"),
    (2, "act", "seriescodepattern_act"),
    (1, "sep", None),
    (1, "act", "findobjectfirst_act"),
    (1, "menu", "cleanupmenu"),
    (2, "act", "removeduplicates_act"),
    (2, "act", "finddiffnamedduplicates_act"),
    (2, "act", "removepixeldust_act"),
    (2, "act", "removeempty_act"),
    (1, "sep", None),
    (1, "act", "updatecuration_act"),
    (1, "sep", None),
    (1, "act", "bcprofiles_act"),
    (1, "sep", None),
    (1, "act", "about_act"),
    (0, "menu", "sectionmenu"),
    (1, "act", "nextsection_act"),
    (1, "act", "prevsection_act"),
    (1, "sep", None),
    (1, "act", "goto_act"),
    (1, "sep", None),
    (1, "act", "flicker_act"),
    (1, "sep", None),
    (1, "act", "findcontour_act"),
    (1, "act", "addscalebar"),
    (1, "menu", "importsecmenu"),
    (2, "act", "importroi_act"),
    (1, "menu", "exportsecmenu"),
    (2, "act", "exportsvg_act"),
    (2, "act", "exportpng_act"),
    (2, "act", "exportroi_act"),
    (0, "menu", "listsmenu"),
    (1, "act", "objectlist_act"),
    (1, "act", "tracelist_act"),
    (1, "act", "sectionlist_act"),
    (1, "act", "ztracelist_act"),
    (1, "act", "flaglist_act"),
    (1, "act", "history_act"),
    (0, "menu", "alignmentsmenu"),
    (1, "act", "changealignment_act"),
    (1, "sep", None),
    # renamed from "importmenu", which Series > Import also used: newMenu does
    # setattr(mw, attr_name, menu), so the second build overwrote the first and
    # MainWindow.importmenu could only ever mean the Alignments submenu
    (1, "menu", "importalignmentsmenu"),
    (2, "act", "importtransforms_act"),
    (2, "act", "import_swift_transforms_act"),
    (1, "sep", None),
    (1, "menu", "propagatemenu"),
    (2, "act", "startpt_act"),
    (2, "act", "endpt_act"),
    (2, "sep", None),
    (2, "act", "proptostart_act"),
    (2, "act", "proptoend_act"),
    (1, "sep", None),
    (1, "act", "unlocksection_act"),
    (1, "act", "changetform_act"),
    (1, "act", "linearalign_act"),
    (1, "act", "aligncorrelation_act"),
    (0, "menu", "viewmenu"),
    (1, "act", "copyscreen_act"),
    (1, "act", "savescreen_act"),
    (1, "sep", None),
    (1, "act", "changetheme_act"),
    (1, "sep", None),
    (1, "act", "fillopacity_act"),
    (1, "sep", None),
    (1, "act", "homeview_act"),
    (1, "act", "viewmag_act"),
    (1, "act", "findview_act"),
    (1, "sep", None),
    (1, "act", "toggleztraces_act"),
    (1, "sep", None),
    (1, "menu", "palettemenu"),
    (2, "menu", "togglepalettemenu"),
    (3, "act", "togglepalette_act"),
    (3, "act", "toggleinc_act"),
    (3, "act", "togglebc_act"),
    (3, "act", "togglesb_act"),
    (2, "menu", "incpalettemenu"),
    (3, "act", "incpaletteup_act"),
    (3, "act", "incpalettedown_act"),
    (2, "act", "resetpalette_act"),
    (1, "act", "lefthanded_act"),
    (1, "sep", None),
    (1, "act", "togglecuration_act"),
    (0, "menu", "helpmenu"),
    (1, "act", "repobranch_act"),
    (1, "act", "checkupdates_act"),
    (1, "act", "whatsnew_act"),
    (1, "sep", None),
    (1, "act", "shortcutshelp_act"),
    (1, "sep", None),
    (1, "menu", "onlinemenu"),
    (2, "act", "openwiki_act"),
    (2, "act", "openrepo_act"),
    (2, "act", "openkhlab_act"),
    (2, "act", "openkhatlast_act"),
    (2, "act", "download2015"),
    (1, "menu", "issuemenu"),
    (2, "act", "copydiag_act"),
    (2, "act", "viewlog_act"),
    (2, "act", "openlogdir_act"),
    (2, "act", "submitissue_act"),
    (2, "act", "seeissues_act"),
    (1, "act", "emailteam_act"),
]

# Sanctioned additions on top of the baseline. The baseline is a losslessness
# guard, not a freeze: rows may be ADDED, and each addition is recorded here
# with the reason, so the diff stays reviewable and a row still cannot vanish.
#
# 1. "Clear recents" inside "Open recent series". With no recent paths there is
#    no separator above it (a rule above a lone row reads like a mistake), so
#    the row lands directly under its submenu.
# 2. "From another series (.jser)..." at the top of the Alignments import
#    submenu. Added because the decision changed, not because the test was
#    wrong: importing a colleague's alignment was reachable only through
#    Series > Import series data > From another series, which is the
#    whole-series merge dialog, while Alignments > Import alignments offered
#    only .txt and SWiFT. All three sources now sit together.
# 3. "Reset window" in View, directly under the Palette submenu. Added because
#    there was no way at all to recover a main window left off-screen or too
#    small to grab, short of quitting and clearing `window/geometry` by hand.
#    It lands after the submenu, next to "Reset palette position", not inside
#    it: the palette submenu is palette-scoped and this is window-scoped.
# 4. "Show what's new after updates" in Help, directly under "What's new".
#    Added with the What's-new dialog's "Don't show again" button: the button
#    switches the startup popup off, and a preference that could only be
#    switched off from inside the dialog it hides needs a visible way back on.
#    Checkable, resynced from the stored preference every time Help opens.
# 5. "Recolor all objects from palette..." in View, directly under "Edit fill
#    opacity..." (2026-08-12, his placement call). The series-wide sibling of
#    the object menus' selection-scoped "Reapply custom color palette to existing objects...": recolors
#    every unlocked object with the current palette and seed as one undoable
#    pass, SKIPPING locked objects rather than aborting on them (an abort
#    would make a series-wide pass useless the moment one object is locked).
#    It sits beside the fill-opacity row because that is the View section
#    about how every object is painted. Semantics are covered in
#    tests/test_autoseg_reapply_colors.py.
_CLEAR_RECENTS_ROW = (2, "act", "clearrecents_act")
_IMPORT_JSER_ALIGNMENTS_ROW = (2, "act", "import_jser_alignments_act")
_RESET_WINDOW_ROW = (1, "act", "resetwindow_act")
_TOGGLE_WHATSNEW_ROW = (1, "act", "togglewhatsnew_act")
# Help > "Check for updates on startup": the checkable that replaced the
# Series Options Updates tab (removed with the channel radio, 2026-08-21).
# It sits directly under "Check for updates...", the action it governs.
_TOGGLE_UPDATECHECK_ROW = (1, "act", "toggleupdatecheck_act")
# Help > the cross-flavor download row (2026-08-25): each build links to the
# OTHER build's latest download, right under "Check for updates...". Stable
# offers the Dev beta, Dev offers stable; legacy Beta-channel users hold a
# lone beta install and this is their road back to stable.
_GET_OTHER_FLAVOR_ROW = (1, "act", "getotherflavor_act")
# Help > "Search menus...": the in-window menubar never gets macOS's native
# Help search, so the app carries its own palette (stable ship, 2026-08-21).
_SEARCH_MENUS_ROW = (1, "act", "searchmenus_act")
_RECOLOR_ALL_ROW = (1, "act", "recolorallfrompalette_act")
MENUBAR_EXPECTED = list(MENUBAR_BASELINE)
MENUBAR_EXPECTED.insert(
    MENUBAR_BASELINE.index((1, "menu", "openrecentmenu")) + 1, _CLEAR_RECENTS_ROW
)
MENUBAR_EXPECTED.insert(
    MENUBAR_EXPECTED.index((1, "menu", "importalignmentsmenu")) + 1,
    _IMPORT_JSER_ALIGNMENTS_ROW,
)
MENUBAR_EXPECTED.insert(
    MENUBAR_EXPECTED.index((1, "act", "lefthanded_act")), _RESET_WINDOW_ROW
)
MENUBAR_EXPECTED.insert(
    MENUBAR_EXPECTED.index((1, "act", "whatsnew_act")) + 1, _TOGGLE_WHATSNEW_ROW
)
MENUBAR_EXPECTED.insert(
    MENUBAR_EXPECTED.index((1, "act", "checkupdates_act")) + 1,
    _TOGGLE_UPDATECHECK_ROW,
)
MENUBAR_EXPECTED.insert(
    MENUBAR_EXPECTED.index((1, "act", "checkupdates_act")) + 1,
    _GET_OTHER_FLAVOR_ROW,
)
MENUBAR_EXPECTED.insert(
    MENUBAR_EXPECTED.index((1, "act", "shortcutshelp_act")), _SEARCH_MENUS_ROW
)
MENUBAR_EXPECTED.insert(
    MENUBAR_EXPECTED.index((1, "act", "fillopacity_act")) + 1, _RECOLOR_ALL_ROW
)

# The one sanctioned MOVE, as opposed to the additions above, decided
# 2026-08-06: the four palette visibility toggles come out of
# View > Palette > Visibility and sit directly in View, next to "Show z-traces".
# #205 had already stopped the menu closing on each toggle, but the three-level
# descent per toggle remained, and that is the half of the report it did not
# reach. Expressed as remove-then-insert rather than by rewriting the baseline,
# so the baseline stays the frozen `51e9a85` capture and this deviation stays
# visible: `test_no_baseline_action_was_lost` still sees all four actions, which
# is the property that makes this a move and not a loss. The now-empty
# "Visibility" submenu row goes with them -- it is the only row that genuinely
# disappears, and a submenu with nothing in it is not a row worth keeping.
_NESTED_VISIBILITY_ROWS = [
    (2, "menu", "togglepalettemenu"),
    (3, "act", "togglepalette_act"),
    (3, "act", "toggleinc_act"),
    (3, "act", "togglebc_act"),
    (3, "act", "togglesb_act"),
]
_HOISTED_VISIBILITY_ROWS = [
    (1, "act", "togglepalette_act"),
    (1, "act", "toggleinc_act"),
    (1, "act", "togglebc_act"),
    (1, "act", "togglesb_act"),
]
for _row in _NESTED_VISIBILITY_ROWS:
    MENUBAR_EXPECTED.remove(_row)
_hoist_at = MENUBAR_EXPECTED.index((1, "act", "toggleztraces_act")) + 1
MENUBAR_EXPECTED[_hoist_at:_hoist_at] = _HOISTED_VISIBILITY_ROWS


def test_menubar_structure_matches_the_baseline_plus_additions():
    """Nothing moved, nothing dropped: the whole tree, row for row.

    Labels are deliberately not part of this comparison -- the point of the
    label pass is that they change while the structure does not.
    """
    built = [(d, kind, attr) for d, kind, attr, _text in _rows()]
    assert built == MENUBAR_EXPECTED


def test_no_baseline_action_was_lost():
    """Stated the other way round, as a set, so a failure names the casualty."""
    built = {attr for _d, kind, attr, _t in _rows() if kind == "act"}
    baseline = {attr for _d, kind, attr in MENUBAR_BASELINE if kind == "act"}
    assert baseline - built == set()


def test_menubar_action_and_submenu_counts():
    """113 actions at capture, 119 now (the additions).

    Submenus were 32 and are 31: the 2026-08-06 hoist emptied
    View > Palette > Visibility and it was removed. The action count is
    deliberately unchanged by that hoist -- moving four rows up two levels adds
    and removes nothing, and an action count that moved here would mean the move
    had dropped or duplicated one. Additions 4 and 5 (the what's-new toggle
    and the series-wide recolor, both 2026-08-12, built on separate branches)
    each took the count up one, 117 to 119 together.
    """
    rows = _rows()
    assert sum(1 for _d, kind, _a, _t in rows if kind == "act") == 122
    assert sum(1 for _d, kind, _a, _t in rows if kind == "menu") == 31


def test_recolor_all_objects_sits_in_view_beside_fill_opacity():
    """Addition 4: the series-wide recolor lives in View, directly under "Edit
    fill opacity..." (his placement call; the View section about how every
    object is painted). The label names the scope ("all objects") and the
    source ("from palette"), keeps the ASCII ellipsis because it opens a
    confirm dialog, and deliberately does not say "autoseg": the palette
    colors any object name, which is the same reason the context row is
    "Reapply custom color palette to existing objects...". Locked-skip and undo semantics are pinned in
    tests/test_autoseg_reapply_colors.py.
    """
    labels = _labels()
    assert labels["recolorallfrompalette_act"] == \
        "Recolor all objects from palette..."
    rows = _rows()
    flat = [(kind, attr) for _d, kind, attr, _t in rows]
    at = flat.index(("act", "fillopacity_act"))
    assert flat[at + 1] == ("act", "recolorallfrompalette_act")
    # in the View menu: the nearest enclosing top-level menu above it
    menus = [(d, kind, attr) for d, kind, attr, _t in rows[:at + 2]
             if kind == "menu" and d == 0]
    assert menus[-1] == (0, "menu", "viewmenu")


# --------------------------------------------------------------------------- #
# 2. the renames
# --------------------------------------------------------------------------- #
# Every label here was verified against its handler before being written; see
# the module docstring and the PR body. A label that confidently lies is worse
# than a vague one, so items whose behavior could not be pinned down were left
# alone (File > Projects, in particular).
RENAMED = {
    # attr_name: (old label, new label)
    "newseriesmenu": ("New", "New series"),
    "open_act": ("Open", "Open series..."),
    "openrecentmenu": ("Open recent", "Open recent series"),
    "close_act": ("Close", "Close series"),
    "restart_act": ("Reload", "Restart PyReconstruct"),
    "updatecuration_act": (
        "Update curation from history",
        "Restore object curation status from log",
    ),
}


@pytest.mark.parametrize("attr", sorted(RENAMED))
def test_renamed_label(attr):
    old, new = RENAMED[attr]
    labels = _labels()
    assert labels[attr] == new, f"{attr} should read {new!r}, not {labels[attr]!r}"
    assert labels[attr] != old


# The second label pass: the deferred "verb with no object" items from the pass
# above, plus the maintainer's catch-all name for the former Projects submenu.
# Same rules: every label verified against its handler, nothing moved, no
# shortcut changed.
RENAMED_SECOND_PASS = {
    # attr_name: (old label, new label)
    #
    # exportToXML converts the open series to a legacy XML .ser;
    # exportToZarr's handler docstring is "Export series as a
    # neuroglancer-compatible zarr" (images over a section range/window plus
    # any chosen group labels). Both act on the open series.
    "exportmenu": ("Export", "Export series"),
    # both children bring data into the open series: traces / z-traces /
    # flags / attributes / alignments / palettes / b-c profiles from another
    # series, or zarr labels converted to objects
    "importmenu": ("Import", "Import series data"),
    # importFromSeries's own docstring: "Import from another series."
    "importfromseries_act": ("From series...", "From another series..."),
    # the maintainer's catch-all for rarely used, user-requested functions;
    # signals where future niche items go
    "projectsmenu": ("Projects", "Utilities"),
    # randomize_project acts on a project directory (codes its images and
    # emits one coded jser); derandomize_project reverses it. The pair now
    # shares its noun -- "De-randomize project..." is unchanged.
    "random_act": ("Randomize images...", "Randomize project..."),
}


@pytest.mark.parametrize("attr", sorted(RENAMED_SECOND_PASS))
def test_second_pass_renamed_label(attr):
    old, new = RENAMED_SECOND_PASS[attr]
    labels = _labels()
    assert labels[attr] == new, f"{attr} should read {new!r}, not {labels[attr]!r}"
    assert labels[attr] != old


def test_menubar_attr_names_are_unique():
    """No two menubar rows may share an attr_name.

    newMenu/newAction do ``setattr(mainwindow, attr_name, ...)``, so a
    duplicate silently overwrites the earlier attribute -- Series > Import and
    Alignments > Import alignments shared "importmenu" until the latter was
    renamed, leaving ``MainWindow.importmenu`` pointing only at the Alignments
    submenu. Nothing read it, so nothing broke; this pins the invariant so the
    next duplicate cannot sit unnoticed."""
    names = [attr for _d, kind, attr, _t in _rows() if kind != "sep"]
    dupes = {n for n in names if names.count(n) > 1}
    assert dupes == set(), f"duplicate menubar attr_names: {sorted(dupes)}"


# The two menus in scope, as the user reads them. Frozen so a future pass has to
# name every label it changes -- the same guarantee test_context_menu_frequency
# gives the seven right-click surfaces. Indentation = submenu depth, "-----" is a
# separator, "Name >" is a submenu title.
FILE_MENU_LABELS = [
    "New series >",
    "    From images...",
    "    From scaled images...",
    "    From legacy .ser...",
    "    From neuroglancer zarr...",
    "Open series...",
    "Open recent series >",
    "    Clear recents",
    "Close series",
    "-----",
    "Save",
    "Save as...",
    "Utilities >",
    "    Randomize project...",
    "    De-randomize project...",
    "Backup >",
    "    Backup now...",
    "    Settings...",
    "Export series >",
    "    To legacy Reconstruct (XML)...",
    "    To Neuroglancer (Zarr)...",
    "-----",
    "Change username...",
    "-----",
    "Restart PyReconstruct",
    "Quit",
]

SERIES_MENU_LABELS = [
    "Options...",
    "Import series data >",
    "    From another series...",
    "    From neuroglancer zarr labels...",
    "Images >",
    "    Find/change image directory",
    "    Convert to scaled images",
    "    Update image scales",
    "Hide >",
    "    Hide all traces (entire series)",
    "    Unhide all traces (entire series)",
    "Log >",
    "    Offload log history...",
    "3D >",
    "    Load 3D scene...",
    "Trace palette >",
    "    Edit all palettes...",
    "    Reset current palette",
    "    -----",
    "    Export as CSV...",
    "    Import from CSV...",
    "Calibration >",
    "    Calibrate pixel size...",
    "    Manually set pixel mag...",
    "Series code >",
    "    Set series code...",
    "    Edit regex pattern...",
    "-----",
    "Find first object contour...",
    "Clean up >",
    "    Remove duplicate traces...",
    "    Find duplicates named differently...",
    "    Remove pixel-dust traces...",
    "    Remove empty traces...",
    "-----",
    "Restore object curation status from log",
    "-----",
    "Brightness/contrast profiles...",
    "-----",
    "About this series...",
]


def _rendered(menu_attr):
    """Render one top-level menu the way the frozen lists above are written."""
    top = next(m for m in _menubar() if m["attr_name"] == menu_attr)
    out = []
    for depth, kind, _attr, text in _walk(top["opts"], depth=1):
        pad = "    " * (depth - 1)
        if kind == "sep":
            out.append(f"{pad}-----")
        else:
            out.append(f"{pad}{text}" + (" >" if kind == "menu" else ""))
    return out


@pytest.mark.parametrize(
    "menu_attr,expected",
    [("filemenu", FILE_MENU_LABELS), ("seriesmenu", SERIES_MENU_LABELS)],
    ids=["File", "Series"],
)
def test_menu_reads_exactly_as_frozen(menu_attr, expected):
    assert _rendered(menu_attr) == expected


def test_close_and_quit_are_distinguishable():
    """"Close" returns to the welcome series; "Quit" exits the app. The old
    labels ("Close" / "Quit") gave no clue which one left the program."""
    labels = _labels()
    assert labels["close_act"] == "Close series"
    assert labels["quit_act"] == "Quit"


def test_open_is_disambiguated_from_the_other_open_items():
    """"Open" now names the thing it opens, so it no longer collides with the
    menubar's other open-something items."""
    labels = _labels()
    assert labels["open_act"] == "Open series..."
    assert labels["openlogdir_act"] == "Open log folder"


def test_new_submenu_names_the_thing_it_creates():
    """All four rows call Series.new/xmlToJSON and then openSeries: every one
    creates a series, so the submenu can name it once for all of them."""
    labels = _labels()
    assert labels["newseriesmenu"] == "New series"
    rows = [labels[a] for a in
            ("newfromimages_act", "newfromzarr_act", "newfromxml_act", "newfromngzarr_act")]
    assert all(r.startswith("From ") for r in rows), rows


def test_dialog_items_keep_the_ascii_ellipsis():
    """The renamed items that open a dialog keep the app-wide "..." marker."""
    labels = _labels()
    assert labels["open_act"].endswith("...")
    for attr in ("close_act", "restart_act", "updatecuration_act", "newseriesmenu"):
        assert not labels[attr].endswith("..."), attr


# --------------------------------------------------------------------------- #
# 3. "Clear recents" -- the one addition
# --------------------------------------------------------------------------- #
RECENTS = ["/nonexistent/a.jser", "/nonexistent/b.jser"]


def test_clear_recents_is_the_last_row_of_the_open_recent_submenu():
    series = _SeriesStub()
    sub = _submenu(_menubar(series), "openrecentmenu")
    assert sub is not None
    assert sub[-1][0] == "clearrecents_act"
    assert sub[-1][1] == "Clear recents"


def test_clear_recents_has_no_separator_when_there_is_nothing_to_clear():
    """An empty list means the row is alone; a rule above a lone row reads as a
    rendering bug."""
    sub = _submenu(_menubar(_SeriesStub()), "openrecentmenu")
    assert len(sub) == 1
    assert sub[0][0] == "clearrecents_act"


def test_clear_recents_is_separated_from_the_remembered_paths(tmp_path):
    """With paths listed, the row sits after a separator so it cannot be hit by
    a mis-click aimed at the last remembered series."""
    paths = []
    for name in ("a.jser", "b.jser"):
        p = tmp_path / name
        p.write_text("{}", encoding="utf-8")
        paths.append(str(p))

    series = _SeriesStub(recents=paths)
    sub = _submenu(_menubar(series), "openrecentmenu")

    assert [row[0] for row in sub if isinstance(row, tuple)] == [
        "openrecent0_act", "openrecent1_act", "clearrecents_act",
    ]
    assert sub[-2] is None  # the separator
    assert sub[-1][1] == "Clear recents"


def test_clear_recents_binds_no_keyboard_shortcut():
    """A new action must not claim a key -- that would collide with a user's
    existing binding."""
    sub = _submenu(_menubar(_SeriesStub()), "openrecentmenu")
    assert sub[-1][2] == ""


def test_open_recent_submenu_is_unchanged_when_no_clear_handler_is_passed():
    """``clearRecents`` is optional, so any other caller of getOpenRecentMenu
    keeps the old menu exactly."""
    from PyReconstruct.modules.gui.utils.utils import getOpenRecentMenu

    series = _SeriesStub()
    menu = getOpenRecentMenu(series, lambda **kw: None)
    assert menu["opts"] == []


def test_clear_recent_series_empties_the_option_and_rebuilds_the_menubar():
    """The handler itself, on a stub: the option is emptied and the menubar is
    rebuilt so the submenu is visibly empty at once (it is otherwise only
    rebuilt on the next series open)."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    rebuilt = []
    series = _SeriesStub(recents=list(RECENTS))
    mw = _Anything(series=series, createMenuBar=lambda: rebuilt.append(True))

    MainWindow.clearRecentSeries(mw)

    assert series.opts["recently_opened_series"] == []
    assert rebuilt == [True]


def test_clear_recents_round_trips_through_the_real_menu_definition(tmp_path):
    """End to end on the real definitions: a path is listed, the row's own
    callback is fired, and rebuilding the File menu shows the path gone.

    This is the regression test the feature is proven by -- reverting either the
    menubar wiring or MainWindow.clearRecentSeries fails it.
    """
    from PyReconstruct.modules.gui.main.main_window import MainWindow
    from PyReconstruct.modules.gui.main.menubar import return_file_menu

    p = tmp_path / "a.jser"
    p.write_text("{}", encoding="utf-8")
    series = _SeriesStub(recents=[str(p)])

    class _MW(_MainWindowStub):
        clearRecentSeries = MainWindow.clearRecentSeries

        def createMenuBar(self):
            """The real handler rebuilds the menubar; the rebuild is done
            explicitly below so this needs no Qt widgets."""

    mw = _MW(series)
    sub = _submenu([return_file_menu(mw)], "openrecentmenu")
    assert [row[0] for row in sub if isinstance(row, tuple)] == [
        "openrecent0_act", "clearrecents_act",
    ]

    sub[-1][3]()  # fire "Clear recents"

    sub = _submenu([return_file_menu(mw)], "openrecentmenu")
    assert [row[0] for row in sub if isinstance(row, tuple)] == ["clearrecents_act"]


# --------------------------------------------------------------------------- #
# 4. keyboard shortcuts: none moved
# --------------------------------------------------------------------------- #
# Keys resolve through series.getOption(act_name), so a relabelled action keeps
# its key as long as it keeps its attr_name AND is still built with the series
# form. Both halves are asserted -- the second through the real newAction path.
MENUBAR_DEFAULT_KEYS = {
    "open_act": "Ctrl+O",
    "save_act": "Ctrl+S",
    "newfromimages_act": "Ctrl+N",
    "restart_act": "Ctrl+Alt+R",  # moved off browser refresh in the 2026-08-23 sweep
    "quit_act": "Ctrl+Q",
}


def _flat_tuples(item):
    """Yield every action tuple in a menu dict, recursing submenus."""
    for entry in item["opts"]:
        if isinstance(entry, tuple):
            yield entry
        elif isinstance(entry, dict):
            yield from _flat_tuples(entry)


def test_relabelled_actions_still_carry_the_series_shortcut_form():
    series = _SeriesStub()
    kbds = {row[0]: row[2] for menu in _menubar(series) for row in _flat_tuples(menu)}
    for attr in MENUBAR_DEFAULT_KEYS:
        assert kbds[attr] is series, f"{attr} no longer resolves its user key"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(["test"])


@pytest.fixture(scope="module")
def real_series(tmp_path_factory):
    """The real Series, so getOption resolves the real default shortcuts."""
    import os
    import shutil

    from PyReconstruct.modules.backend.settings_store import DictSettingsStore
    from PyReconstruct.modules.datatypes.series import Series

    fixture = os.path.join(
        os.path.dirname(__file__), "..", "dev",
        "assets", "checker", "files", "shapes1.jser",
    )
    if not os.path.exists(fixture):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path_factory.mktemp("series") / "s.jser")
    shutil.copyfile(fixture, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(DictSettingsStore())
    return series


def test_real_file_menu_resolves_every_default_shortcut(qapp, real_series):
    """Build the File menu through the real Qt helpers and assert the resolved
    QAction shortcut. This is the guard that actually proves the relabel did not
    unbind a key -- the label is the only thing newAction takes verbatim."""
    from PySide6.QtWidgets import QMenu, QWidget

    from PyReconstruct.modules.gui.main.menubar import return_file_menu
    from PyReconstruct.modules.gui.utils.utils import populateMenu

    mw = _MainWindowStub(real_series)
    widget = QWidget()
    populateMenu(widget, QMenu(widget), return_file_menu(mw)["opts"])

    for act_name, key in MENUBAR_DEFAULT_KEYS.items():
        action = getattr(widget, act_name, None)
        assert action is not None, f"{act_name} was not built onto the widget"
        assert action.shortcut().toString() == key, (
            f"{act_name} lost its shortcut: {action.shortcut().toString()!r} "
            f"(expected {key!r})"
        )


def test_clear_recents_action_builds_with_no_shortcut(qapp, real_series):
    from PySide6.QtWidgets import QMenu, QWidget

    from PyReconstruct.modules.gui.main.menubar import return_file_menu
    from PyReconstruct.modules.gui.utils.utils import populateMenu

    mw = _MainWindowStub(real_series)
    widget = QWidget()
    populateMenu(widget, QMenu(widget), return_file_menu(mw)["opts"])

    action = getattr(widget, "clearrecents_act", None)
    assert action is not None
    assert action.text() == "Clear recents"
    assert action.shortcut().toString() == ""


# --------------------------------------------------------------------------- #
# 5. "Open recent" order -- the reported question, pinned as behavior
# --------------------------------------------------------------------------- #
def test_recent_series_order_is_most_recently_opened_first(tmp_path):
    """The user expected reverse chronological. It already is -- by *open* time,
    not by file mtime: addToRecentSeries inserts at index 0, de-duplicates, and
    caps the list at ten. Pinned here so the answer stays true."""
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    series = _SeriesStub(recents=[])
    mw = _Anything(series=series)

    for name in ("first", "second", "third"):
        MainWindow.addToRecentSeries(mw, str(tmp_path / f"{name}.jser"))

    assert series.opts["recently_opened_series"] == [
        str(tmp_path / "third.jser"),
        str(tmp_path / "second.jser"),
        str(tmp_path / "first.jser"),
    ]

    # reopening an entry moves it back to the front rather than duplicating it
    MainWindow.addToRecentSeries(mw, str(tmp_path / "first.jser"))
    assert series.opts["recently_opened_series"][0] == str(tmp_path / "first.jser")
    assert len(series.opts["recently_opened_series"]) == 3


def test_recent_menu_preserves_that_order_and_prunes_missing_files(tmp_path):
    """The menu walks the list in order (so the display order is the stored
    order), drops paths that no longer exist, and skips the series already
    open."""
    kept = tmp_path / "kept.jser"
    kept.write_text("{}", encoding="utf-8")
    also = tmp_path / "also.jser"
    also.write_text("{}", encoding="utf-8")
    open_now = tmp_path / "open.jser"
    open_now.write_text("{}", encoding="utf-8")

    series = _SeriesStub(
        recents=[str(kept), str(tmp_path / "gone.jser"), str(open_now), str(also)],
        jser_fp=str(open_now),
    )
    sub = _submenu(_menubar(series), "openrecentmenu")

    shown = [row[1] for row in sub if isinstance(row, tuple)
             and row[0].startswith("openrecent")]
    assert shown == [str(kept), str(also)]
    # the missing path is pruned from the stored option; the open series is not
    assert series.opts["recently_opened_series"] == [
        str(kept), str(open_now), str(also),
    ]
