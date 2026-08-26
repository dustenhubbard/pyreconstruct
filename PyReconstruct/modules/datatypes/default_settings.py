import getpass
import math

# MFO = modifiable from options dialog

def get_username() -> str:
    """Return username."""
    try:
        user = getpass.getuser()
    except OSError:
        user = 'default'
    return user

# The 2026-08-23 shortcut sweep (scheme C of the three drafted, plus the two
# macOS collisions): every move defuses a reflex trap, every freed chord stays
# deliberately unbound so an old habit lands on silence, and the one legacy
# chord with deep roots keeps working through this alias registry. An action
# listed here answers to its stored binding AND to the legacy chord, as long
# as no other action's current binding claims that chord; menus display only
# the stored binding, so new users learn one key.
LEGACY_SHORTCUT_ALIASES = {
    "pasteattributes_act": "Ctrl+B",
}

default_settings = {
    # user
    "username": get_username(),  # MFO

    # backup
    # "backup_dir": "",
    # "manual_backup_dir": "",
    # "manual_backup_delimiter": "-",
    # "manual_backup_date_delimiter": "-",
    # "manual_backup_time_delimiter": "-",
    # "manual_backup_name": True,
    # "manual_backup_utc": False,
    # "manual_backup_date": True,
    # "manual_backup_date_str": "%Y-%m-%d",
    # "manual_backup_time": False,
    # "manual_backup_time_str": "%H-%M",
    # "manual_backup_user": True,
    # "manual_backup_comment": True,
    "backup_delimiter": "-",
    "backup_series": True,
    "backup_filename": False,
    "backup_user": True,
    "backup_date": True,
    "backup_date_str": "%Y-%m-%d",
    "backup_time": True,
    "backup_time_str": "%H-%M",
    "backup_prefix" : False,
    "backup_prefix_str": "",
    "backup_suffix": False,
    "backup_suffix_str": "",

    # misc preferences
    "left_handed": False,  # MFO
    "utc": False,  # MFO
    "cpu_max": 50,  # % of cores -> parallel zarr-conversion workers; ~half leaves headroom

    # view
    "3D_xy_res": 0,  # 0-100  # MFO
    "3D_smoothing": "humphrey",  # MFO
    "3D_auto_refresh": True,  # auto-regenerate edited meshes when the 3D window is focused  # MFO
    "smoothing_iterations": 10,  # MFO
    "screenshot_res": 300,
    "show_ztraces": True,  # MFO
    "fill_opacity": 0.2,  # MFO
    "find_zoom": 95.0,  # MFO
    "show_flags": "unresolved",  # MFO
    "display_closest": True,  # MFO
    "flag_size": 14,  # MFO

    # mouse tools
    "pointer": ["lasso", "exc"],  # MFO
    "auto_merge": False,  # MFO
    "roll_average": False,
    "roll_window": 10,
    "roll_knife_average": False,
    "roll_knife_window": 10,
    "trace_mode": "combo",  # combo, poly, scribble  # MFO
    "knife_del_threshold": 1.0,  # MFO
    "knife_ignore_secondary_click": True,  # MFO
    # Focus mode's edit-click modifier, remappable to whatever combination the
    # user holds. Read by `focus_edit_p` in `gui/main/focus_mode.py` and edited in
    # the shortcuts dialog, not here on the Mouse Tools tab: a three-way
    # ctrl/shift/both radio group lived here briefly and was cut before shipping,
    # because three presets are not a remapping. Stored as canonical lowercase
    # names joined by `+`, in the order ctrl, shift, alt, meta (see
    # `gui/modifiers.py`); empty means the edit click is off. `meta` is not
    # offered on macOS, where it is the physical Control key and the click never
    # survives to be tested.
    "focus_edit_modifier": "ctrl",
    "grid": [1, 1, 1, 1, 1, 1],  # MFO
    "sampling_frame_grid": True,  # MFO
    "flag_name": "",  # MFO
    "flag_color": [255, 0, 0],  # MFO
    "palette_inc_all": True,

    # autoseg import trace colors
    # Colors for autoseg-imported traces are chosen from a curated,
    # grayscale-visible palette, mapped deterministically from each label id
    # (see modules/backend/autoseg/palette.py). Leave the palette empty to use
    # the shipped default; bump the seed to reshuffle the id -> color mapping.
    "autoseg_color_palette": [],  # list of [R, G, B]; [] = built-in default
    "autoseg_color_seed": 0,

    # shortcuts 
    "alloptions_act": "Ctrl+,",
    "flicker_act": "/",
    "focus_act": "X",
    "hideall_act": "H",
    "showall_act": "A",
    "hideimage_act": "I",
    "decbr_act": "-",
    "incbr_act": "=",
    "deccon_act": "[",
    "inccon_act": "]",
    "blend_act": "Space",
    "toggleztraces_act": "",  # checkable "Show z-traces"; no default key
    "homeview_act": "Home",
    "selectall_act": "Ctrl+A",
    "deselect_act": "Ctrl+D",
    # Third member of the selection trio, so it wants to sit beside Ctrl+A and
    # Ctrl+D. Ctrl+Shift+I is the invert-selection key in Photoshop (Select >
    # Inverse), Krita and Affinity Photo, so the muscle memory is borrowed rather
    # than invented. It is free here: no other entry in this dict claims it, and
    # neither do the shortcuts written straight into the source (the arrow and
    # function keys in main_window.py, the palette digits it generates, Ctrl+\ in
    # menubar.py). Qt renders it as Cmd+Shift+I on macOS, where it is a Finder
    # and Mail menu item but not a system-global binding, so it never reaches
    # this app's window. Ctrl+Alt+I was the runner-up and was rejected because
    # Ctrl+Alt is indistinguishable from AltGr on international layouts, which
    # Microsoft's own keyboard guidelines warn against and Qt does not
    # disambiguate (QTBUG-73247). Like every key in this dict it is
    # user-configurable in the shortcuts dialog.
    "invertselection_act": "Ctrl+Shift+I",
    "edittrace_act": "Ctrl+E",
    "mergetraces_act": "Shift+M",
    "mergeobjects_act": "Ctrl+Shift+M",
    "smoothtraces_act": "Ctrl+Shift+R",
    "hidetraces_act": "Shift+H",
    "unhideall_act": "Ctrl+U",
    "pastetopalette_act": "Shift+G",
    "pastetopalettewithshape_act": "Ctrl+Shift+G",
    "unlocksection_act": "Ctrl+Shift+U",
    "changetform_act": "Ctrl+T",
    "undo_act": "Ctrl+Z",
    "redo_act": "Ctrl+Y",
    "copy_act": "Ctrl+C",
    # Sibling of copy_act, so it wants to sit next to Ctrl+C. Ctrl+Shift+C is
    # NOT free -- it has been togglecuration_act's default since before this
    # action existed (see "Lists" below, and docs/USER_GUIDE.md) -- so the
    # copy-to-sections key keeps the "C for copy" mnemonic on the otherwise
    # unused Ctrl+Alt tier instead of displacing a documented binding. Like
    # every key in this dict it is user-configurable in the shortcuts dialog.
    "copytosections_act": "Ctrl+Alt+C",
    # "Add to 3D scene" is a frequent action in this lab and had no key at all.
    # Ctrl+Shift+D sits in the tier this dict already uses for feature actions
    # (objectlist, tracelist, flaglist, mergeobjects, togglecuration) rather
    # than the bare-letter tier, which is reserved for tool selection.
    # Unused across all 59 bindings here.
    #
    # Checked on every platform we ship, since one settings string means
    # different physical keys per platform:
    #   macOS   -- Qt maps Ctrl to Command, so this is Cmd+Shift+D. Not an OS
    #              binding (Cmd+Shift+3/4/5 are the screenshot keys).
    #   Windows -- Ctrl stays Ctrl. Not an OS binding; the reserved ones nearby
    #              are Ctrl+Shift+Esc (Task Manager) and Ctrl+Alt+Del.
    #   Linux   -- not a common DE binding; the risky tier there is
    #              Ctrl+Alt+<letter/arrow> (workspace and terminal switching).
    # Verified by reasoning against documented OS-reserved sequences, NOT by
    # pressing it on a Windows or Linux box.
    #
    # Rejected, so this is not relitigated: a digit key (Ctrl+Alt+3) is mnemonic
    # for "3D" but awkward with two modifiers, and Ctrl+Alt+D would reach macOS
    # users as Cmd+Opt+D, which the OS owns for show/hide Dock.
    "addobjto3D_act": "Ctrl+Shift+D",
    "cut_act": "Ctrl+X",
    "paste_act": "Ctrl+V",
    "pasteattributes_act": "Ctrl+Shift+V",
    "findobjectfirst_act": "Ctrl+F",
    "findcontour_act": "Shift+F",
    "goto_act": "Ctrl+G",
    "open_act": "Ctrl+O",
    # Help > Search menus. Ctrl+K (Cmd+K on macOS), the command-palette
    # convention. NOT Ctrl+Shift+/: macOS delivers that chord as Cmd+?, so a
    # Ctrl+Shift+/ binding never fires there (found in click testing).
    "searchmenus_act": "Ctrl+K",
    # View > Show/hide lists. S for Sidebar, on his call (2026-08-25):
    # Ctrl+Alt+S here, delivered as Cmd+Option+S on macOS. Plain Ctrl+S and
    # Ctrl+Shift+S are save and the section list; bare S is the stamp tool.
    "togglelists_act": "Ctrl+Alt+S",
    "save_act": "Ctrl+S",
    "manualbackup_act": "Ctrl+Shift+B",
    "newfromimages_act": "Ctrl+N",
    "restart_act": "Ctrl+Alt+R",
    "quit_act": "Ctrl+Q",
    "objectlist_act": "Ctrl+Shift+O",
    "togglecuration_act": "Ctrl+Shift+C",
    "tracelist_act": "Ctrl+Shift+T",
    "ztracelist_act": "Ctrl+Alt+Z",
    "sectionlist_act": "Ctrl+Shift+S",
    "flaglist_act": "Ctrl+Shift+F",
    "changealignment_act": "Ctrl+Shift+A",
    "modifytracepalette_act": "Ctrl+Shift+P",
    "incpaletteup_act": "Ctrl+]",
    "incpalettedown_act": "Ctrl+[",
    "sethosts_act": "Ctrl+Shift+H",

    # palette-specific shortcuts
    "usepointer_act": "P",
    "usepanzoom_act": "Z",
    "useknife_act": "K",
    "usectrace_act": "C",
    "useotrace_act": "O",
    "usestamp_act": "S",
    "usegrid_act": "G",
    "useflag_act": "F",
    "usehost_act": "Q",

    # series-related
    "series_code_pattern": "[0-9A-Za-z]+",  # MFO

    # theme
    "theme": "default",  # MFO

    # updates
    "update_channel": "release",  # "release" | "prerelease"  # MFO
    "update_branch": "main",      # source/dev installs only     # MFO
    "update_check_on_startup": True,  # frozen builds: once-a-day background check  # MFO

    # 3D
    "translate_step_3D": 0.1,  # MFO
    "rotate_step_3D": 10,  # MFO

    # recently opened series
    "recently_opened_series": [],

    # scale bar settings
    #
    # Two sizing models, chosen by scale_bar_mode:
    #   "screen_fraction"  the historic one, and the default so that a stored
    #                      scale_bar_width keeps meaning what it always meant.
    #                      The bar is a share of the field and the µm figure
    #                      under it moves as you zoom.
    #   "micron_pinned"    the bar is scale_bar_length_um long in real-world
    #                      units and its pixel width moves as you zoom, so the
    #                      figure under it stays put.
    # Each mode reads its own quantity, so switching between them is lossless.
    "scale_bar_mode": "screen_fraction",  # "screen_fraction" | "micron_pinned"  # MFO
    "scale_bar_width": 25,  # displayed as this percentage of the screen (min should be 20)
    "scale_bar_length_um": 5.0,  # microns; used in "micron_pinned" mode  # MFO
    "show_scale_bar_text": True,
    "show_scale_bar_ticks": True,
}

# The range of real-world lengths a micron-pinned scale bar can be pinned to:
# a picometre to a metre, against specimen sections measured in tens of microns.
# These are not an opinion about what a sensible bar is -- the pinned mode
# already handles an unhelpful length by stepping it a decade at a time -- they
# are the window outside which that decade arithmetic stops being arithmetic.
MIN_PINNED_UM = 1e-6
MAX_PINNED_UM = 1e6


def validPinnedLength(value) -> bool:
    """True if `value` is a length a scale bar can actually be pinned to.

    `value > 0` is not a sufficient test, and the gap is not academic.
    `float("inf") > 0` is True; `float("1e400")` parses to inf without raising;
    `1e-320` is a positive, finite denormal. All three pass a bare positivity
    check, and all three then raise out of `scale_bar.pinnedLength` --
    `math.log10(0.0)` for the infinities, `math.ceil(inf)` for the denormal --
    from inside `ScaleBar.__init__`, which runs inside `MousePalette.__init__`.
    `scale_bar_length_um` is a *global*-scope option, so a stored value that
    crashes the palette crashes every launch after it, before there is any UI
    left to change it back.

    Applied in three places: the options dialog will not store a length that
    fails it, `MousePalette.getPinnedLength` will not pin a bar to one it reads
    back, and `pinnedLength` treats one as nothing to draw. The first keeps such
    a value out of the store; the other two mean a store already holding one --
    hand-edited, or written by a build without this check -- degrades to the
    screen-fraction bar rather than taking the application down with it.

    It lives here, beside the key it governs, because the dialog and the palette
    both need it and `PyReconstruct.modules.gui.palette` cannot be imported from
    `PyReconstruct.modules.gui.dialog` at module scope without a cycle.

        Params:
            value: the candidate length, from the dialog or the settings store
        Returns:
            bool: True if the pinned-mode arithmetic can use it
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and MIN_PINNED_UM <= value <= MAX_PINNED_UM


default_series_settings = {
    # "autoversion": False,
    # "autoversion_dir": "",
    # "manual_backup_dir": ""
    "autobackup": False,
    "backup_dir": "",
}
