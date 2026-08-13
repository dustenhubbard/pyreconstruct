"""Frequency-first context-menu redesign: the layout of all seven right-click menus.

Every right-click surface in the app is pinned here by its EXACT list of labels,
so a future reorganization cannot silently drop, rename, or reorder an action
without a test saying so. The seven surfaces are the 2D field, the zarr-label
overlay, and the object / trace / z-trace / section / flag lists (the object,
trace and z-trace menus are shared between the field and their list, and are
checked in both variants).

Layout law, applied to every menu top to bottom:

  1. the action(s) you almost always came here to do (shortcuts on display)
  2. everyday groups, direct items, separated by task
  3. named submenus for genuine sets only (3D, curation, formats)
  4. table utilities (lists): "Invert selection" + "Copy <entity> values"
  5. destructive last, after a separator, with the scope in the label

Also guarded here:
  * SHORTCUTS -- hoisting an action must not unbind its key. Bindings are keyed
    to internal act_names via series.getOption(act_name), so the guard is that
    the act_name still appears in a menu AND still carries the series form.
  * SCOPE HONESTY -- tags are trace-level, comments are object-level, so the
    object menu's bulk tag action must not live under "Object attributes >".
    Widened 2026-07-31: no label may appear on both the object menu and the
    trace menu unless the two do the same amount of work. Four did ("Smooth
    traces", "Edit radius...", "Edit shape...", "Unhide"), one object-wide and
    one selection-scoped, and nothing in either label said which. The fourth was
    found by the standing rule rather than by reading the menu, and was fixed
    a few hours after the other three once the maintainer chose to narrow his
    "leave the visibility section alone" instruction for it. See
    test_no_label_is_shared_between_the_object_and_trace_menus.

The definitions are built against light stubs (no Qt loop), matching the idiom
of test_menu_restructure / test_menu_parity_hoist.
"""
import pytest

from PyReconstruct.modules.gui.main.context_menu_list import (
    get_context_menu_list_obj,
    get_context_menu_list_trace,
    get_field_menu_list,
    get_hoisted_trace_actions,
    get_label_menu_list,
)


# --------------------------------------------------------------------------- #
# stubs / helpers
# --------------------------------------------------------------------------- #
class _Anything:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


def _series():
    return _Anything(user_columns={}, alignments=set(), groups_visibility={})


OBJ_LIST_OPS = [
    ("invertobjselection_act1", "Invert selection", "", None),
    ("copyobjrow_act", "Copy object values", "", None),
]
TRACE_LIST_OPS = [
    ("inverttraceselection_act", "Invert selection", "", None),
    ("copytracerow_act", "Copy trace values", "", None),
]
ZTRACE_LIST_OPS = [
    ("invertztraceselection_act", "Invert selection", "", None),
    ("copyztracerow_act", "Copy z-trace values", "", None),
]


class _FieldStub(_Anything):
    """A field stub whose three entity submenus really are the shared builders,
    so the field menu is checked end-to-end (top strip AND submenu contents)."""

    def __init__(self, series=None):
        super().__init__(series=series or _series())

    def getTraceMenu(self, is_in_field=True, list_ops=None, find_in_field=None):
        return get_context_menu_list_trace(
            self, is_in_field, list_ops=list_ops, find_in_field=find_in_field
        )

    def getObjMenu(self, list_ops=None, is_in_field=True):
        return get_context_menu_list_obj(
            self, list_ops=list_ops, is_in_field=is_in_field
        )

    def getZtraceMenu(self, list_ops=None):
        from PyReconstruct.modules.gui.main.field_widget_2_trace import FieldWidgetTrace
        return FieldWidgetTrace.getZtraceMenu(self, list_ops=list_ops)


def _main_window_stub(series=None):
    series = series or _series()
    return _Anything(series=series, field=_FieldStub(series))


def _field_menu(series=None):
    return get_field_menu_list(_main_window_stub(series))


def _obj_menu(list_ops=None):
    return get_context_menu_list_obj(_Anything(series=_series()), list_ops=list_ops)


def _trace_menu(is_in_field=True, list_ops=None, find_in_field=None):
    return get_context_menu_list_trace(
        _Anything(series=_series()),
        is_in_field=is_in_field,
        list_ops=list_ops,
        find_in_field=find_in_field,
    )


def _ztrace_menu(list_ops=None):
    from PyReconstruct.modules.gui.main.field_widget_2_trace import FieldWidgetTrace
    return FieldWidgetTrace.getZtraceMenu(_Anything(), list_ops=list_ops)


def _section_menu():
    from PyReconstruct.modules.gui.table.section import SectionTableWidget
    return SectionTableWidget.getContextMenuList(_Anything(table=_Anything()))


def _flag_menu():
    from PyReconstruct.modules.gui.table.flag import FlagTableWidget
    return FlagTableWidget.getContextMenuList(_Anything(table=_Anything()))


def _rows(menu):
    """Flatten a menu definition to a readable row list.

    Separators become "-----", submenus become "<title> >" followed by their
    indented rows, actions become their label. Pre-built QActions (the four
    clipboard actions the field menu borrows from the menubar) become
    "<QAction>" -- their labels live in menubar.py, not here.
    """
    out = []
    for entry in menu:
        if entry is None:
            out.append("-----")
        elif isinstance(entry, tuple):
            out.append(entry[1])
        elif isinstance(entry, dict):
            out.append(f"{entry['text']} >")
            out += [f"    {r}" for r in _rows(entry["opts"])]
        else:
            out.append("<QAction>")
    return out


def _act_names(menu):
    out = []
    for entry in menu:
        if isinstance(entry, tuple):
            out.append(entry[0])
        elif isinstance(entry, dict):
            out += _act_names(entry["opts"])
    return out


def _kbds(menu):
    out = {}
    for entry in menu:
        if isinstance(entry, tuple):
            out[entry[0]] = entry[2]
        elif isinstance(entry, dict):
            out.update(_kbds(entry["opts"]))
    return out


def _top_level(menu):
    """Top-level rows only (submenus as titles, no recursion)."""
    out = []
    for entry in menu:
        if entry is None:
            out.append("-----")
        elif isinstance(entry, tuple):
            out.append(entry[1])
        elif isinstance(entry, dict):
            out.append(f"{entry['text']} >")
        else:
            out.append("<QAction>")
    return out


# --------------------------------------------------------------------------- #
# 1. field menu (2D field right-click)
# --------------------------------------------------------------------------- #
FIELD_TOP_LEVEL = [
    # top strip: the dynamic edit item, the object-attributes row added beside
    # it 2026-08-01 (see test_edit_object_attributes_is_row_two_of_the_top_strip
    # for the request it answers), then the three shortcut-bearing trace actions
    "Edit attributes...",
    "Edit object attributes...",
    "Merge traces",
    "Merge attributes only",
    "Hide selected traces",
    "-----",
    # clipboard, uninterrupted muscle-memory order; "Copy to sections..."
    # directly under "Copy"
    "<QAction>",            # Cut            (menubar action)
    "<QAction>",            # Copy           (menubar action)
    "Copy to sections...",
    "<QAction>",            # Paste          (menubar action)
    "<QAction>",            # Paste attributes (menubar action)
    "-----",
    "Select all traces",
    "Deselect all traces",
    "Invert selection",
    "-----",
    # the familiar entity triad survives
    "Trace >",
    "Object >",
    "Z-trace >",
    "-----",
    "View >",
    "Series alignment >",
    "-----",
    "Delete selected",
]


def test_field_menu_top_level_layout():
    assert _top_level(_field_menu()) == FIELD_TOP_LEVEL


def test_field_top_strip_is_exactly_five_actions():
    """Four until 2026-08-01, when "Edit object attributes..." joined them.

    The other four are unchanged and in their original order: the dynamic edit
    item plus merge / merge-attrs / hide. Smooth and Make negative/positive were
    deliberately NOT hoisted and still are not.
    """
    rows = _top_level(_field_menu())
    strip = rows[: rows.index("-----")]
    assert strip == [
        "Edit attributes...", "Edit object attributes...", "Merge traces",
        "Merge attributes only", "Hide selected traces",
    ]
    # "Smooth traces" until 2026-07-31, when the label gained its scope; the
    # old string would have satisfied this assertion forever without biting.
    assert "Smooth selected traces" not in strip
    assert "Make negative" not in strip
    assert "Make positive" not in strip


def test_edit_object_attributes_is_row_two_of_the_top_strip():
    """A beta-5 tester asked for "Edit object attributes..." at the top level
    "beside Edit trace attributes...". Row 1 carries exactly that label whenever
    traces are selected (checkActions relabels editselected_act), so beside it
    means directly under it.
    """
    menu = _field_menu()
    assert [e[0] for e in menu[:2] if isinstance(e, tuple)] == [
        "editselected_act", "editobjattrs_act",
    ]
    assert menu[1][1] == "Edit object attributes..."


def test_edit_object_attributes_calls_the_field_object_handler():
    """It must fire the object-attributes handler on the FIELD, whose
    object_function wrapper resolves the target objects from the selected traces
    (or the focused object list). No new resolution rule is introduced here.
    """
    calls = []
    field = _FieldStub()
    field.editAttributes = lambda *a, **k: calls.append("editAttributes")
    main_window = _Anything(series=field.series, field=field)

    row = next(e for e in get_field_menu_list(main_window)
               if isinstance(e, tuple) and e[0] == "editobjattrs_act")
    row[3]()
    assert calls == ["editAttributes"]

    # the same handler the object menu's own copy is wired to
    obj_row = next(e for e in field.getObjMenu()
                   if isinstance(e, tuple) and e[0] == "editobjattribtues_act")
    assert obj_row[3] is field.editAttributes


def test_edit_object_attributes_carries_no_shortcut():
    """Two actions sharing one key is an ambiguous binding, which Qt answers by
    firing neither. Neither copy of this action has ever had one; keep it that
    way."""
    kbds = _kbds(_field_menu())
    assert kbds["editobjattrs_act"] == ""
    assert kbds["editobjattribtues_act"] == ""


def test_edit_object_attributes_is_gated_by_the_trace_selection():
    """The objects it edits are the ones owning the selected traces, so it needs
    its own entry in MainWindow.trace_actions -- at top level nothing else
    disables it (the "Object >" copy rides on objectmenu)."""
    import inspect
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    src = inspect.getsource(MainWindow.createContextMenus)
    gating = src.split("self.trace_actions = [")[1].split("]")[0]
    assert "self.editobjattrs_act" in gating


def test_field_view_submenu_is_untouched():
    view = next(e for e in _field_menu()
                if isinstance(e, dict) and e["text"] == "View")
    assert _rows(view["opts"]) == [
        "Focus mode",
        "-----",
        "Unhide all traces (this section)",
        "-----",
        "Hide trace layer",
        "Show all traces (ignore hidden)",
        "-----",
        "Hide image",
        "Section blend",
    ]


def test_field_menu_ends_with_the_destructive_action():
    assert _top_level(_field_menu())[-2:] == ["-----", "Delete selected"]


# --------------------------------------------------------------------------- #
# 2. zarr-label menu (unchanged)
# --------------------------------------------------------------------------- #
def test_label_menu_layout():
    assert _rows(get_label_menu_list(_Anything())) == [
        "Import labels",
        "Merge labels",
    ]


# --------------------------------------------------------------------------- #
# 3. object menu (field "Object >" + object list)
# --------------------------------------------------------------------------- #
# Row order approved by the maintainer on 2026-07-29, superseding the original
# frequency-first arrangement. See test_object_menu_row_order_is_the_approved_one
# below for what changed and why.
OBJECT_ROWS = [
    # top strip: the two actions that "deserve the frequently used top spots",
    # with "3D >" directly under the top-level 3D row it belongs to
    "Edit object attributes...",
    "Add to 3D scene",
    "3D >",
    "    Add to scene",
    "    Remove from scene",
    "    -----",
    "    Export mesh as >",
    "        Wavefront (.obj)",
    "        Object File Format (.off)",
    "        Stanford PLY (.ply)",
    "        STL (.stl)",
    "        __COLLADA__",
    "    Export quantitative data...",
    "    -----",
    "    Edit 3D settings...",
    "-----",
    # the whole visibility family, flat, three hide/unhide pairs by scope
    "Hide object",
    "Unhide object",
    "Hide other objects",
    "Restore previous visibility",
    "Hide all objects",
    "Unhide all objects",
    "-----",
    # object-level settings, one section, most used first (2026-07-31)
    "Object attributes >",
    "    Set hosts...",
    "    Clear hosts",
    "    Show host tree",
    "    Show inhabitant tree",
    "    -----",
    "    Edit alignment...",
    "    -----",
    "    Lock",
    "    Unlock",
    # promoted out of "Object attributes >" on 2026-08-12: a routine bulk pass
    # for autoseg users, not an attribute edit, and it keeps the adjacency to
    # its old home (see test_reapply_autoseg_colors_sits_beside_its_old_home)
    "Reapply autoseg colors...",
    "Smooth object",
    "Duplicate object",
    "Split into separate objects",
    "Edit object radius...",
    "Edit object shape...",
    "Group >",
    "    Add to group...",
    "    Remove from group...",
    "    Remove from all groups",
    "Set curation >",
    "    Needs curation",
    "    Curated",
    "    Clear status",
    "Custom categories >",
    "    New...",
    "Leave object comment...",
    "-----",
    "Create Z-trace >",
    "    On contour midpoints",
    "    From trace sequence",
    "-----",
    "View history",
    "Copy attributes to palette",
    # table utilities go here on the LIST surface only
    "-----",
    # bulk trace operation, its own group (see the scope tests below)
    "Remove all tags",
    "-----",
    "Delete objects",
]

LIST_UTILITY_ROWS = ["-----", "Invert selection", "Copy object values"]


def _normalize_collada(rows):
    """The Collada label carries a "(not installed)" suffix when pycollada is
    absent (always, in frozen builds); its presence is what matters here."""
    return [
        "        __COLLADA__" if r.strip().startswith("Collada (.dae)") else r
        for r in rows
    ]


def test_object_menu_field_variant_layout():
    assert _normalize_collada(_rows(_obj_menu())) == OBJECT_ROWS


def test_object_menu_list_variant_adds_utilities_second_from_bottom():
    """Same menu, plus the table utilities in the standard bottom slot -- so
    row 1 of the list menu is "Edit object attributes...", not plumbing."""
    rows = _normalize_collada(_rows(_obj_menu(list_ops=OBJ_LIST_OPS)))
    expected = list(OBJECT_ROWS)
    at = expected.index("Copy attributes to palette") + 1
    expected[at:at] = LIST_UTILITY_ROWS
    assert rows == expected
    assert rows[0] == "Edit object attributes..."


def test_object_list_utilities_are_below_the_domain_actions():
    rows = _rows(_obj_menu(list_ops=OBJ_LIST_OPS))
    assert rows.index("Invert selection") > rows.index("Edit object attributes...")
    assert rows.index("Invert selection") > rows.index("Hide object")
    assert rows.index("Copy object values") < rows.index("Delete objects")


@pytest.mark.parametrize("label", [
    "Leave object comment...", "Duplicate object", "Add to 3D scene",
    "Hide object", "Hide other objects",
    # 2026-07-31: "smoothing is frequent", so it left "Geometry >" for the top
    # level. The two edit rows followed when that left the submenu at two items.
    "Smooth object", "Edit object radius...", "Edit object shape...",
    "Split into separate objects",
    # 2026-08-12: a common workflow action for autoseg users, promoted out of
    # "Object attributes >" after a beta report showed it buried there.
    "Reapply autoseg colors...",
])
def test_often_used_object_actions_are_zero_hop(label):
    """The actions the maintainer named as frequent are top-level (one click),
    not buried in a submenu."""
    assert label in _top_level(_obj_menu())


def test_add_to_3d_scene_is_at_top_level_AND_in_the_3d_submenu():
    """Revised 2026-07-29 at the maintainer's request, after using the app.

    The earlier decision hoisted "Add to 3D scene" OUT of "3D >" entirely, on the
    theory that the frequent member should leave and the rare ones stay. In
    practice that made it hard to find: the top-level copy sits in the
    frequent-actions strip, far from "3D >", so someone looking for "add" opens
    "3D >" first, sees only "Remove from scene", and hunts. His words: "i had to
    hunt for add to 3D scene menu item in the top level because it was so far
    from the 3D submenu."

    So it now appears in BOTH places, which is how "Edit object attributes..."
    already behaves. This test previously asserted the opposite; the product
    decision changed, the test was not wrong.

    Restoring the submenu copy was only half the fix. The distance itself was
    the complaint, and the row reorder closes it: see
    test_the_two_3d_rows_are_adjacent.
    """
    menu = _obj_menu()
    assert "Add to 3D scene" in _top_level(menu)
    three_d = next(e for e in menu if isinstance(e, dict) and e["text"] == "3D")
    submenu_labels = _rows(three_d["opts"])
    assert "Add to scene" in submenu_labels, (
        'the "3D >" submenu should also offer "Add to scene", beside "Remove from scene"'
    )
    assert "Remove from scene" in submenu_labels
    assert "Export mesh as >" in submenu_labels
    # both copies exist as distinct actions; sharing an attr_name would make the
    # second overwrite the first on the widget
    names = _act_names(menu)
    assert "addobjto3D_act" in names
    assert "addobjto3Dsub_act" in names


def test_object_menu_row_order_is_the_approved_one():
    """The maintainer's approved object-menu order, 2026-07-29.

    He was unhappy with the previous arrangement for weeks and finally named
    the reason: "the 3D scene menu item is too far from the 3D submenu". The
    top-level "Add to 3D scene" sat at row 2 and "3D >" at row 15, with the
    visibility family, "Group >" and "Set curation >" in between, so "the 3D
    sections are disjointed".

    Three principles decided the new order, in his words:

      * "Edit object attributes and Add to 3D scene deserve the frequently used
        top spots but not Comment nor Duplicate object."
      * "The view section with the various Hide options is good" -- left alone,
        same members, same order, its own section.
      * "The Group section should be lower, since these are object-level
        settings they should be in the same section as Object attributes and
        Geometry."

    Revised 2026-07-31. That pass was order only; this one renames and flattens.
    Inside the object-settings section: "Object attributes >" leads, the three
    commands whose labels used to collide with the trace menu now name their
    scope, "Smooth object" and the two edit rows are top-level, "Split into
    separate objects" sits beside "Duplicate object" because it is structural
    rather than a trace operation, "Geometry >" is gone, and the comment action
    closes the section as "Leave object comment...". His words: "Dissolve the
    Geometry name. Split object location you suggested makes sense."

    Amended later the same day with the fourth rename. "Unhide" was the one
    remaining shared label, and it lives in the visibility section that the
    2026-07-29 pass was told to leave alone. Shown the collision, he narrowed
    that instruction rather than keeping it: "Make it 'Unhide object' and 'Unhide
    selected traces', consistent with the three renames [...] Touches the
    visibility section, but leaving one collision unfixed is the inconsistency
    users actually hit."

    Amended again the same day, once the whole visibility section was put in
    front of him as a scope-by-action matrix. "The view section is good" had
    stopped being the operative instruction after the fourth rename entered it,
    and the matrix showed the section was incomplete rather than merely uneven.
    His call: "build the restore, skip the blanket unhide-other." So the section
    grew one row and lost none, and its order now expresses three hide/unhide
    pairs -- object, isolate, series. See
    test_the_visibility_section_completes_the_scope_matrix.

    Amended 2026-08-12, one targeted promotion and nothing else: "Reapply
    autoseg colors..." left "Object attributes >" for the top level of the
    settings section, directly below the submenu it left. A beta report showed
    it buried under "Object attributes >" on the object list even though it is
    a common workflow action for automatic-segmentation users, not an attribute
    edit. The placement reuses the adjacency lesson from the 3D pair: the
    promoted row sits beside its old home, so someone who learned the old
    location finds it without hunting. See
    test_reapply_autoseg_colors_sits_beside_its_old_home.
    """
    assert _top_level(_obj_menu()) == [
        "Edit object attributes...",
        "Add to 3D scene",
        "3D >",
        "-----",
        "Hide object",
        "Unhide object",
        "Hide other objects",
        "Restore previous visibility",
        "Hide all objects",
        "Unhide all objects",
        "-----",
        "Object attributes >",
        "Reapply autoseg colors...",
        "Smooth object",
        "Duplicate object",
        "Split into separate objects",
        "Edit object radius...",
        "Edit object shape...",
        "Group >",
        "Set curation >",
        "Custom categories >",
        "Leave object comment...",
        "-----",
        "Create Z-trace >",
        "-----",
        "View history",
        "Copy attributes to palette",
        "-----",
        "Remove all tags",
        "-----",
        "Delete objects",
    ]


def test_the_two_3d_rows_are_adjacent():
    """His actual objection, as a standing guard rather than a row list: the
    top-level "Add to 3D scene" must sit directly above the "3D >" submenu that
    holds its counterpart "Remove from scene". Any future row inserted between
    the two re-creates the complaint."""
    rows = _top_level(_obj_menu())
    assert rows[rows.index("Add to 3D scene") + 1] == "3D >"


def test_object_level_settings_share_one_section():
    """"Group >" and "Set curation >" are per-object settings, so they belong in
    the same section as "Object attributes >" -- his reasoning for moving them
    down. A separator between any two of them would split the section again.

    "Geometry >" was a member of this list until it was dissolved on 2026-07-31;
    the two edit rows it held are now members in their own right, so the section
    it belonged to is asserted the same way with more members in it.
    """
    rows = _top_level(_obj_menu())
    members = [
        "Object attributes >", "Reapply autoseg colors...", "Smooth object",
        "Duplicate object",
        "Split into separate objects", "Edit object radius...",
        "Edit object shape...", "Group >", "Set curation >",
        "Leave object comment...",
    ]
    idx = [rows.index(m) for m in members]
    assert idx == sorted(idx)
    assert "-----" not in rows[idx[0]:idx[-1] + 1], (
        "the object-level settings are split across sections"
    )


def test_the_geometry_submenu_is_gone():
    """His two-item rule: "if a submenu has only two items we should double check
    if it's even worth a submenu."

    "Geometry >" held four rows. "Smooth object" was promoted for frequency and
    "Split into separate objects" moved beside "Duplicate object" (structural,
    not a trace operation), which left exactly two edit rows. That is the bar, so
    the submenu was dissolved rather than renamed: with the scope in the labels
    there was nothing left for a container to describe. Renaming it to something
    "less generic and descriptive", his earlier ask, is moot.
    """
    menu = _obj_menu()
    assert not any(isinstance(e, dict) and e["text"] == "Geometry" for e in menu)
    assert "objgeometrymenu" not in [
        e.get("attr_name") for e in menu if isinstance(e, dict)
    ]
    top = _top_level(menu)
    for label in ("Edit object radius...", "Edit object shape...",
                  "Smooth object", "Split into separate objects"):
        assert label in top, f"{label} lost its home when Geometry > was dissolved"


def test_split_object_sits_beside_duplicate_object():
    """Structural pair, more used first. He named "Duplicate object" as the more
    used of the two and said the split action "sits closer to" it than to radius
    and shape, which are trace-shape edits applied object-wide."""
    rows = _top_level(_obj_menu())
    assert rows[rows.index("Duplicate object") + 1] == "Split into separate objects"


def test_leave_object_comment_closes_its_section():
    """It "deserves" a place but not a frequent one, so it is last in the
    object-settings section, directly above the separator that ends it."""
    rows = _top_level(_obj_menu())
    i = rows.index("Leave object comment...")
    assert rows[i + 1] == "-----"


def test_object_attributes_submenu_leads_the_settings_section():
    """His ask: "Object attributes" leads the section it named."""
    rows = _top_level(_obj_menu())
    i = rows.index("Object attributes >")
    assert rows[i - 1] == "-----"


def test_reapply_autoseg_colors_sits_beside_its_old_home():
    """Promoted 2026-08-12, and the placement is the point.

    The report: on the object list, "Reapply autoseg colors..." sat under
    "Object attributes >" even though it is a common workflow action for
    automatic-segmentation users, not an attribute edit. The fix is one hop up,
    to the top level of the settings section, DIRECTLY below the submenu it
    left. That adjacency is the lesson the 3D pair already taught (see
    test_the_two_3d_rows_are_adjacent): someone who learned the old home
    reaches for "Object attributes >" and the row is beside it, so nobody
    hunts. Any future row inserted between the two re-creates the hunt.
    """
    rows = _top_level(_obj_menu())
    assert rows[rows.index("Object attributes >") + 1] == \
        "Reapply autoseg colors..."


def test_reapply_autoseg_colors_left_the_attributes_submenu():
    """The promotion is a move, not a copy: the 3D pair mirrors its frequent
    member inside the submenu because "Add to scene" belongs to the 3D family
    either way, but this action was mis-filed, so a leftover copy would keep
    telling users it is an attribute edit. The act_name stays put because it is
    the key any user-configured shortcut is stored under
    (series.getOption(act_name)); renaming it would silently unbind the key.
    """
    attrs = next(e for e in _obj_menu() if isinstance(e, dict)
                 and e["text"] == "Object attributes")
    assert "reapplyautosegcolors_act" not in _act_names(attrs["opts"])
    assert "Reapply autoseg colors..." not in _rows(attrs["opts"])
    # still reachable, top-level, under its old act_name, on both surfaces
    for list_ops in (None, OBJ_LIST_OPS):
        menu = _obj_menu(list_ops=list_ops)
        assert "Reapply autoseg colors..." in _top_level(menu)
        top_level_acts = [e[0] for e in menu if isinstance(e, tuple)]
        assert "reapplyautosegcolors_act" in top_level_acts


def test_comment_and_duplicate_are_below_the_top_spots():
    """"Edit object attributes and Add to 3D scene deserve the frequently used
    top spots but not Comment nor Duplicate object." Both stay top-level (one
    click), just not in the strip above the first separator."""
    rows = _top_level(_obj_menu())
    strip = rows[: rows.index("-----")]
    assert strip == ["Edit object attributes...", "Add to 3D scene", "3D >"]
    assert "Leave object comment..." not in strip
    assert "Duplicate object" not in strip


def test_the_visibility_section_completes_the_scope_matrix():
    """Three hide/unhide pairs, one per scope of action, and nothing else.

    This test was `test_the_visibility_section_was_left_alone` until 2026-07-31,
    guarding "the view section with the various Hide options is good" as an
    instruction to change nothing. That instruction is spent: the fourth rename
    entered the section earlier the same day with his explicit go-ahead, and once
    the whole section was laid out as a scope-by-action matrix he asked for it to
    be finished -- "build the restore, skip the blanket unhide-other."

    So the rule it pins is now positive rather than negative, which is the
    stronger form: every hide has the unhide at its own scope beside it.

        Hide object                    Unhide object                 object
        Hide other objects             Restore previous visibility   isolate
        Hide all objects               Unhide all objects            series

    The three approved changes, with his words:

      * "Hide" -> "Hide object": "yes make it Hide object". Symmetry with row
        one's unhide; it never collided with the trace menu.
      * "Show all objects" -> "Unhide all objects", so one verb means one thing.
      * "Restore previous visibility" added, the inverse "Hide other objects"
        never had.

    Deliberately NOT here, and rejected rather than forgotten: "Unhide other
    objects". Unhiding the complement of the selection after an isolate leaves
    everything visible, which is "Unhide all objects"; see
    test_no_blanket_unhide_other_objects_row.

    Still asserted twice over, once by label and once by `act_name`, because that
    is what "unchanged members" means and a relabel cannot satisfy the second
    half by accident. Nothing in this section moves without his call, the same
    way both of these did.
    """
    rows = _top_level(_obj_menu())
    start = rows.index("Hide object")
    assert rows[start - 1] == "-----"
    assert rows[start:start + 6] == [
        "Hide object", "Unhide object",
        "Hide other objects", "Restore previous visibility",
        "Hide all objects", "Unhide all objects",
    ]
    assert rows[start + 6] == "-----"

    # membership and order by act_name, which no relabel can satisfy by accident.
    # Top-level entries only: a visibility action that fell into a submenu must
    # fail here rather than be found by a recursive walk.
    #
    # showallobj_act keeps its name against the new "Unhide all objects" label on
    # purpose: act_name is the key a user-configurable shortcut is stored under
    # (series.getOption(act_name)), so renaming it would drop any stored binding.
    acts = [e[0] for e in _obj_menu() if isinstance(e, tuple)]
    first = acts.index("hideobj_act")
    assert acts[first:first + 6] == [
        "hideobj_act", "unhideobj_act",
        "hideotherobj_act", "restorevisibility_act",
        "hideallobj_act", "showallobj_act",
    ]


def test_the_restore_sits_directly_under_the_isolate_it_undoes():
    """"Restore previous visibility" is the inverse of "Hide other objects", and
    the only way a user learns that from a menu is adjacency."""
    rows = _top_level(_obj_menu())
    assert rows.index("Restore previous visibility") == \
        rows.index("Hide other objects") + 1


def test_no_blanket_unhide_other_objects_row():
    """Rejected explicitly, and worth a test so it is not re-derived.

    After isolating {A}, unhiding the complement of the selection leaves
    everything visible -- byte for byte what "Unhide all objects" already does.
    Its only distinct behavior needs the selection to have changed since the
    isolate, and then it surprises. A row that duplicates an existing command is
    not discoverability.
    """
    rows = _rows(_obj_menu(list_ops=OBJ_LIST_OPS))
    assert "Unhide other objects" not in rows
    assert "unhideotherobj_act" not in _act_names(_obj_menu())


def test_group_submenu_is_top_level_on_the_object_menu():
    """Mirrors the z-trace menu's "Group >" -- one pattern to learn."""
    assert "Group >" in _top_level(_obj_menu())
    obj_group = next(e for e in _obj_menu()
                     if isinstance(e, dict) and e["text"] == "Group")
    assert _act_names(obj_group["opts"]) == [
        "addobjgroup_act", "removeobjgroup_act", "removeobjallgroups_act",
    ]


def test_curation_stays_a_submenu():
    """Approved: occasional, not a heavy batch pass -- the three related states
    belong together, with "Clear status" last rather than first."""
    assert "Set curation >" in _top_level(_obj_menu())
    curate = next(e for e in _obj_menu()
                  if isinstance(e, dict) and e["text"] == "Set curation")
    assert _rows(curate["opts"]) == ["Needs curation", "Curated", "Clear status"]


def test_object_menu_attr_names_are_unique_on_both_surfaces():
    """Both variants are populated onto one widget, so a shared attr_name means
    one action silently shadows another (the old export3D_act bug)."""
    for list_ops in (None, OBJ_LIST_OPS):
        names = _act_names(_obj_menu(list_ops=list_ops))
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f"duplicate attr_names in object menu: {sorted(dupes)}"


# --------------------------------------------------------------------------- #
# 4. Q6 scope honesty: tags are TRACE-level, comments are OBJECT-level
# --------------------------------------------------------------------------- #
def test_comment_is_an_object_level_action_at_the_top_level():
    """Comments really are an object attribute (series.obj_attrs[name]["comment"]),
    so the action is honest on the object menu -- and frequent enough to be
    top-level. The label says so now: "Comment..." named neither the object nor
    the fact that a comment is stored on it, sitting among rows that read as
    trace operations."""
    assert "Leave object comment..." in _top_level(_obj_menu())
    assert "editobjcomment_act" in _act_names(_obj_menu())


def test_bulk_tag_action_is_not_filed_as_an_object_attribute():
    """Tags live on Trace, not on the object. On an OBJECT menu "Remove all
    tags" strips tags from every trace of the selected objects, series-wide
    (series.removeAllTraceTags) -- a bulk TRACE operation. Filing it under
    "Object attributes >" would misdescribe it, and "Geometry >" (an earlier
    home) was not geometry either. That submenu no longer exists, so the second
    half of the guard is now that it cannot come back and take the action with
    it."""
    menu = _obj_menu()
    attrs = next(e for e in menu if isinstance(e, dict)
                 and e["text"] == "Object attributes")
    assert "removealltags_act" not in _act_names(attrs["opts"])
    submenus = [e["text"] for e in menu if isinstance(e, dict)]
    assert "Geometry" not in submenus


def test_bulk_tag_action_sits_in_its_own_group_above_delete():
    """Its own bulk/destructive group: separated from the utility rows above and
    from "Delete objects" below (so it cannot be hit by a mis-click on delete),
    and still reachable."""
    rows = _rows(_obj_menu())
    i = rows.index("Remove all tags")
    assert rows[i - 1] == "-----"
    assert rows[i + 1] == "-----"
    assert rows[i + 2] == "Delete objects"
    assert rows[-1] == "Delete objects"


def test_object_attributes_submenu_holds_only_object_level_attributes():
    """Every remaining member is a stored per-object attribute (hosts,
    alignment, lock) -- nothing trace-level.

    "Reapply autoseg colors..." was a member until 2026-08-12. It does write
    the color attribute, but what it IS to a user is a bulk workflow pass over
    imported autoseg objects, and a beta report showed autoseg users digging
    for it here. It was promoted to the top level of the settings section, the
    same way "Remove all tags" left this submenu's neighborhood once its filing
    misdescribed it. See test_reapply_autoseg_colors_sits_beside_its_old_home.
    """
    attrs = next(e for e in _obj_menu() if isinstance(e, dict)
                 and e["text"] == "Object attributes")
    assert _rows(attrs["opts"]) == [
        "Set hosts...",
        "Clear hosts",
        "Show host tree",
        "Show inhabitant tree",
        "-----",
        "Edit alignment...",
        "-----",
        "Lock",
        "Unlock",
    ]


# The three commands that existed on both menus under one label, with the
# implementation each label actually reached. Verified 2026-07-31 by reading
# them, not by reading the menu:
#
#   Smooth object            Series.smoothObject      enumerateSections over
#                                                     getObjectSections(names),
#                                                     every trace of the contour
#   Smooth selected traces   FieldWidgetTrace         the traces passed in, on
#                            .smoothTraces            self.section only
#   Edit object radius...    Series.editObjectRadius  enumerateSections, all
#                                                     traces of the contour
#   Edit selected radius...  Section.editTraceRadius  the traces passed in
#   Edit object shape...     Series.editObjectShape   enumerateSections, all
#                                                     traces of the contour
#   Edit selected shape...   Section.editTraceShape   the traces passed in
#
# The traces "passed in" are the current selection: FieldWidgetTrace's
# trace_function decorator supplies section.selected_traces (or the trace
# table's selected rows), so the trace copies are selection-scoped on one
# section and the object copies are object-scoped across every section the
# object appears on.
SCOPE_PAIRS = [
    ("Smooth object", "Smooth selected traces"),
    ("Edit object radius...", "Edit selected radius..."),
    ("Edit object shape...", "Edit selected shape..."),
    # The fourth pair, added 2026-07-31 after the standing rule below found it.
    # Same asymmetry as the three above, verified by reading each implementation:
    #
    #   unhideobj_act    -> FieldWidgetObject.hideObj(hide=False) [object_function]
    #                    -> Series.hideObjects(names, False), which walks
    #                       enumerateSections over getObjectSections(names) and
    #                       clears `hidden` on every trace of the contour.
    #   unhidetraces_act -> FieldWidgetTrace.hideTraces(hide=False)
    #                       [visibility_trace_function, which supplies the trace
    #                       table's selection or section.selected_traces]
    #                    -> Section.hideTraces(traces, False), on self.section only.
    ("Unhide object", "Unhide selected traces"),
    # The fifth pair, added later on 2026-07-31, and the only one the collision
    # rule below could never have found: these two labels never collided. The
    # object copy read "Hide" and the trace copy read "Hide traces", so
    # test_no_label_is_shared_between_the_object_and_trace_menus was satisfied
    # while the pair stayed asymmetric -- one label named no scope and the other
    # named the wrong axis. The scope-by-action matrix is what found it:
    #
    #   hideobj_act    -> FieldWidgetObject.hideObj(hide=True) [object_function]
    #                  -> Series.hideObjects(names, True), enumerateSections over
    #                     getObjectSections(names), sets `hidden` on every trace
    #                     of the contour, section.save() per section.
    #   hidetraces_act -> FieldWidgetTrace.hideTraces(hide=True)
    #                     [visibility_trace_function, which supplies the trace
    #                     table's selection or section.selected_traces]
    #                  -> Section.hideTraces(traces, True), on self.section only.
    #
    # Identical asymmetry to the unhide pair above, which is the point: a pair
    # cannot be scoped in one direction and unscoped in the other.
    ("Hide object", "Hide selected traces"),
]


@pytest.mark.parametrize("obj_label,trace_label", SCOPE_PAIRS)
def test_the_scoped_pair_labels_are_distinct_and_on_the_right_menu(
        obj_label, trace_label):
    """Each pair now says which one it is.

    Before 2026-07-31 the object copy and the trace copy shared a label. The
    internal attr_names were already distinct (a shared one made "one silently
    shadow the other" on the widget, and that was fixed); the labels were not,
    and a user has only the label.
    """
    obj_rows = _rows(_obj_menu())
    trace_rows = _rows(_trace_menu(is_in_field=False, list_ops=TRACE_LIST_OPS))
    assert obj_label in obj_rows
    assert obj_label not in trace_rows
    assert trace_label in trace_rows
    assert trace_label not in obj_rows


# Exceptions to the rule below, each one a deliberate decision rather than an
# oversight. Anything not listed here fails the test.
KNOWN_SHARED_LABELS = {
    # The table utility every list shares by design, and it does the same thing
    # on both surfaces. Not a scope collision.
    "Invert selection",
    # "Unhide" was listed here for exactly one day. This test found it as a real
    # fourth instance of the collision, and it was recorded rather than fixed
    # because the object copy sits in the visibility section that was out of
    # scope. Shown the entry, the maintainer chose to fix it: "Make it 'Unhide
    # object' and 'Unhide selected traces' [...] leaving one collision unfixed is
    # the inconsistency users actually hit." It is now the fourth row of
    # SCOPE_PAIRS above, so the exception is gone rather than permanent.
    #
    # The set is the right shape for that outcome and worth keeping at one entry:
    # a recorded exception is a decision someone can overturn, where a collision
    # absorbed by a loose assertion is invisible.
}


def test_no_label_is_shared_between_the_object_and_trace_menus():
    """The standing form of the rule, rather than a list of the three known
    offenders: the object menu and the trace menu are populated onto one widget
    and are read side by side, so a label on both is a label a user cannot use to
    tell two different amounts of work apart.

    Submenu titles are excluded (a container is not a command) and so are
    separators.
    """
    def labels(menu):
        return {
            r.strip() for r in _rows(menu)
            if r.strip() not in ("-----", "<QAction>") and not r.strip().endswith(">")
        }

    shared = labels(_obj_menu()) & labels(
        _trace_menu(is_in_field=False, list_ops=TRACE_LIST_OPS,
                    find_in_field=lambda: None)
    )
    assert not shared - KNOWN_SHARED_LABELS, (
        f"labels on both the object and trace menus: "
        f"{sorted(shared - KNOWN_SHARED_LABELS)}"
    )


# --------------------------------------------------------------------------- #
# 5. trace menu (field "Trace >" + trace list)
# --------------------------------------------------------------------------- #
TRACE_FIELD_ROWS = [
    "Edit trace attributes...",
    "-----",
    # long tail only -- edit/merge/hide are on the field menu's top strip
    "Smooth selected traces",
    "Make negative",
    "Make positive",
    "-----",
    "Hide other traces (this section)",
]

TRACE_LIST_ROWS = [
    "Edit trace attributes...",
    "-----",
    "Merge traces",
    "Merge attributes only",
    "-----",
    "Hide selected traces",
    "Unhide selected traces",
    "-----",
    "Set open",
    "Set closed",
    "Make negative",
    "Make positive",
    "Edit selected radius...",
    "Edit selected shape...",
    "Smooth selected traces",
    "-----",
    "Copy to sections...",
    "Create flag...",
    "Find >",
    "    Find in field",
    "-----",
    "Invert selection",
    "Copy trace values",
    "-----",
    "Delete traces",
]


def test_trace_field_variant_layout():
    assert _rows(_trace_menu(is_in_field=True)) == TRACE_FIELD_ROWS


def test_trace_list_variant_layout():
    rows = _rows(_trace_menu(
        is_in_field=False, list_ops=TRACE_LIST_OPS, find_in_field=lambda: None
    ))
    assert rows == TRACE_LIST_ROWS
    assert rows[0] == "Edit trace attributes..."


def test_find_in_field_is_a_submenu_item_and_is_optional():
    """Added as a discoverability probe for the beta testers, deliberately in a
    submenu so it stays out of the everyday flow and is one line to drop."""
    menu = _trace_menu(is_in_field=False, list_ops=TRACE_LIST_OPS,
                       find_in_field=lambda: None)
    find = next(e for e in menu if isinstance(e, dict) and e["text"] == "Find")
    assert _rows(find["opts"]) == ["Find in field"]
    assert _act_names(find["opts"]) == ["findinfield_act"]
    # not offered when no handler is supplied (the field variant)
    assert "findinfield_act" not in _act_names(_trace_menu(is_in_field=True))


def test_find_in_field_is_wired_to_the_table_handler():
    calls = []
    menu = _trace_menu(is_in_field=False, find_in_field=lambda: calls.append(1))
    find = next(e for e in menu if isinstance(e, dict) and e["text"] == "Find")
    find["opts"][0][3]()
    assert calls == [1]


def test_hide_other_traces_is_still_field_only():
    assert "hideothertraces_act" in _act_names(_trace_menu(is_in_field=True))
    assert "hideothertraces_act" not in _act_names(_trace_menu(is_in_field=False))


def test_copy_to_sections_keeps_the_noun_and_the_ellipsis():
    """Approved wording: the noun disambiguates (copy to WHAT), the ellipsis is
    the orthogonal "opens a dialog" convention -- the item wants both. ASCII
    "..." per the app-wide convention (see test_menu_label_style)."""
    field_rows = _top_level(_field_menu())
    assert "Copy to sections..." in field_rows
    assert "Copy to..." not in field_rows
    assert "Copy to sections" not in field_rows
    # and it sits directly under "Copy" in the clipboard group (Copy is a
    # pre-built menubar QAction, so it shows as <QAction> here)
    assert field_rows[field_rows.index("Copy to sections...") - 1] == "<QAction>"
    assert "Copy to sections..." in _rows(
        _trace_menu(is_in_field=False, list_ops=TRACE_LIST_OPS)
    )


# --------------------------------------------------------------------------- #
# 6. z-trace menu (field "Z-trace >" + z-trace list)
# --------------------------------------------------------------------------- #
ZTRACE_ROWS = [
    "Edit z-trace attributes...",
    "Smooth",
    "Add to 3D scene",
    "-----",
    "3D >",
    "    Remove from scene",
    "Group >",
    "    Add to group...",
    "    Remove from group...",
    "    Remove from all groups",
    "Edit alignment...",
    "-----",
    "Delete z-traces",
]


def test_ztrace_field_variant_layout():
    assert _rows(_ztrace_menu()) == ZTRACE_ROWS


def test_ztrace_list_variant_adds_utilities_second_from_bottom():
    rows = _rows(_ztrace_menu(list_ops=ZTRACE_LIST_OPS))
    expected = list(ZTRACE_ROWS)
    at = expected.index("Edit alignment...") + 1
    expected[at:at] = ["-----", "Invert selection", "Copy z-trace values"]
    assert rows == expected
    assert rows[0] == "Edit z-trace attributes..."


def test_ztrace_add_to_3d_scene_hoisted_like_the_object_menu():
    assert "Add to 3D scene" in _top_level(_ztrace_menu())
    assert "addto3D_act" in _act_names(_ztrace_menu())


# --------------------------------------------------------------------------- #
# 7. section list
# --------------------------------------------------------------------------- #
def test_section_list_layout():
    assert _rows(_section_menu()) == [
        "Lock sections",
        "Unlock sections",
        "-----",
        "Brightness/contrast >",
        "    Set values...",
        "    Increment values...",
        "    Match section in view",
        "    Optimize...",
        "Edit thickness...",
        "Edit image source...",
        "Insert section >",
        "    Above",
        "    Below",
        "-----",
        "Invert selection",
        "Copy section values",
        "-----",
        "Delete sections",
    ]


# --------------------------------------------------------------------------- #
# 8. flag list
# --------------------------------------------------------------------------- #
def test_flag_list_layout():
    assert _rows(_flag_menu()) == [
        "Edit flag...",
        "-----",
        "Mark resolved",
        "Mark unresolved",
        "-----",
        "Use as color filter",
        "-----",
        "Invert selection",
        "Copy flag values",
        "-----",
        "Delete flags",
        "Delete all flags with this name (entire series)",
    ]


def test_flag_destructive_actions_stay_last_with_scope_in_the_label():
    rows = _rows(_flag_menu())
    assert rows[-2:] == [
        "Delete flags",
        "Delete all flags with this name (entire series)",
    ]
    assert rows[-3] == "-----"


# --------------------------------------------------------------------------- #
# 9. the uniform law for lists
# --------------------------------------------------------------------------- #
LIST_MENUS = {
    "object": (lambda: _obj_menu(list_ops=OBJ_LIST_OPS), "Copy object values"),
    "trace": (lambda: _trace_menu(is_in_field=False, list_ops=TRACE_LIST_OPS,
                                  find_in_field=lambda: None), "Copy trace values"),
    "ztrace": (lambda: _ztrace_menu(list_ops=ZTRACE_LIST_OPS), "Copy z-trace values"),
    "section": (_section_menu, "Copy section values"),
    "flag": (_flag_menu, "Copy flag values"),
}


@pytest.mark.parametrize("name", sorted(LIST_MENUS))
def test_every_list_puts_its_utilities_in_the_standard_slot(name):
    """Learn one list, know all five: "Invert selection" + "Copy <entity>
    values" adjacent, below every domain action, above the destructive tail."""
    build, copy_label = LIST_MENUS[name]
    rows = _rows(build())
    i = rows.index("Invert selection")
    assert rows[i + 1] == copy_label, f"{name}: copy row does not follow invert"
    assert rows[i - 1] == "-----", f"{name}: utilities not in their own group"
    assert rows[i] != rows[0], f"{name}: utilities are still at the top"


@pytest.mark.parametrize("name", sorted(LIST_MENUS))
def test_every_list_ends_with_a_destructive_group(name):
    build, _copy = LIST_MENUS[name]
    rows = _rows(build())
    assert rows[-1].startswith("Delete"), f"{name}: last row is not destructive"


@pytest.mark.parametrize("name", sorted(LIST_MENUS))
def test_every_list_leads_with_a_domain_action(name):
    build, _copy = LIST_MENUS[name]
    rows = _rows(build())
    assert rows[0] not in ("Invert selection", "-----"), (
        f"{name}: row 1 is table plumbing, not a domain action"
    )


# --------------------------------------------------------------------------- #
# 10. keyboard shortcuts survive the reorganization
# --------------------------------------------------------------------------- #
# Shortcuts are persisted per internal act_name (series.getOption(act_name)),
# so a hoisted action keeps its key as long as it keeps its name AND is still
# built with the series form. These are every act_name the field menu binds a
# user-configurable shortcut for.
FIELD_SHORTCUT_ACTS = [
    "mergetraces_act",      # Ctrl+M      -- hoisted to the top strip
    "mergeobjects_act",     # Ctrl+Shift+M -- hoisted to the top strip
    "hidetraces_act",       # Ctrl+H      -- hoisted to the top strip
    "edittrace_act",        # Ctrl+E      -- stays in "Trace >" (its single home)
    "selectall_act",        # Ctrl+A
    "deselect_act",         # Ctrl+D
    "unhideall_act",        # Ctrl+U
]


def test_hoisted_actions_keep_their_attr_names():
    """The keys are keyed to these names; renaming one would silently unbind it."""
    hoisted = [a[0] for a in get_hoisted_trace_actions(_Anything(series=_series()))]
    assert hoisted == ["mergetraces_act", "mergeobjects_act", "hidetraces_act"]


def test_every_field_shortcut_act_is_still_bound_to_the_series_option():
    series = _series()
    kbds = _kbds(_field_menu(series))
    for act in FIELD_SHORTCUT_ACTS:
        assert act in kbds, f"{act} left the field menu -- its shortcut is now unbound"
        kbd = kbds[act]
        # the series form (bare, or the (series, "checkbox") tuple) is what makes
        # newAction look the key up by act_name
        bound = kbd is series or (isinstance(kbd, tuple) and kbd[0] is series)
        assert bound, f"{act} no longer carries the series shortcut form: {kbd!r}"


def test_view_toggles_keep_their_checkbox_shortcut_form():
    series = _series()
    kbds = _kbds(_field_menu(series))
    for act in ["focus_act", "hideall_act", "showall_act", "hideimage_act", "blend_act"]:
        assert isinstance(kbds[act], tuple) and kbds[act][1] == "checkbox"


def test_ctrl_e_stays_on_the_trace_action_not_the_dynamic_item():
    """The top strip's dynamic "Edit ... attributes..." item relabels per
    selection, so it cannot also hold the trace-only key; Ctrl+E stays on
    edittrace_act, which keeps its home at the top of "Trace >"."""
    series = _series()
    menu = _field_menu(series)
    kbds = _kbds(menu)
    assert kbds["editselected_act"] == ""
    assert kbds["edittrace_act"] is series
    trace = next(e for e in menu if isinstance(e, dict) and e["text"] == "Trace")
    assert _rows(trace["opts"])[0] == "Edit trace attributes..."


# The default keys, from datatypes/default_settings.py. Asserting the resolved
# QAction shortcut (not just the tuple shape) is what actually proves the
# reorganization did not unbind a key.
DEFAULT_KEYS = {
    "copytosections_act": "Ctrl+Alt+C",
    "mergetraces_act": "Ctrl+M",
    "mergeobjects_act": "Ctrl+Shift+M",
    "hidetraces_act": "Ctrl+H",
    "edittrace_act": "Ctrl+E",
    "selectall_act": "Ctrl+A",
    "deselect_act": "Ctrl+D",
    "unhideall_act": "Ctrl+U",
    "focus_act": "X",
    "hideall_act": "H",
    "showall_act": "A",
    "hideimage_act": "I",
    "blend_act": "Space",
}


@pytest.fixture(scope="module")
def real_series(tmp_path_factory):
    """The real Series (so getOption resolves real default shortcuts)."""
    import os
    import shutil
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore

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


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def test_real_field_menu_resolves_every_default_shortcut(qapp, real_series):
    """Build the field menu with the REAL Qt helpers onto one widget (as the app
    does) and assert every shortcut-bearing action resolves to its default key.

    This is the guard that matters for the hoist: a moved action keeps its key
    only if it keeps its attr_name AND the series form, and only the real
    newAction path proves that end to end. Building all four menus onto a single
    widget also surfaces any attr_name collision, which would silently drop one
    of the colliding actions.
    """
    from PySide6.QtWidgets import QWidget, QMenu
    from PySide6.QtGui import QAction
    from PyReconstruct.modules.gui.utils.utils import populateMenu

    field = _FieldStub(real_series)
    main_window = _Anything(
        series=real_series,
        field=field,
        cut_act=QAction("Cut"),
        copy_act=QAction("Copy"),
        paste_act=QAction("Paste"),
        pasteattributes_act=QAction("Paste attributes"),
    )

    widget = QWidget()
    populateMenu(widget, QMenu(widget), get_field_menu_list(main_window))

    for act_name, key in DEFAULT_KEYS.items():
        action = getattr(widget, act_name, None)
        assert action is not None, f"{act_name} was not built onto the widget"
        assert action.shortcut().toString() == key, (
            f"{act_name} lost its shortcut: {action.shortcut().toString()!r} "
            f"(expected {key!r})"
        )


def test_trace_list_variant_binds_no_shortcuts():
    """Shortcuts are only connected through the field (a list menu must not
    steal the key), so the list variant passes the empty form."""
    kbds = _kbds(_trace_menu(is_in_field=False, list_ops=TRACE_LIST_OPS))
    assert all(k == "" for k in kbds.values()), kbds


# --------------------------------------------------------------------------- #
# 11. zero feature loss -- every act_name that existed before is still reachable
# --------------------------------------------------------------------------- #
# The full pre-redesign action set for the three shared menus, by act_name. The
# redesign only moves rows, so nothing here may disappear.
PRE_REDESIGN_OBJECT_ACTS = {
    "editobjattribtues_act", "editobjcomment_act", "sethosts_act",
    "clearhosts_act", "displayinhabitants_act", "displayhosts_act",
    "addobjgroup_act", "removeobjgroup_act", "removeobjallgroups_act",
    "setobjalignment_act", "reapplyautosegcolors_act", "lockobj_act",
    "unlockobj_act", "copyobj_act", "editobjradius_act", "editobjshape_act",
    "smoothobj_act", "splitobj_act", "removealltags_act", "hideobj_act",
    "unhideobj_act", "hideotherobj_act", "hideallobj_act", "showallobj_act",
    "blankcurate_act", "needscuration_act", "curated_act", "newusercol_act",
    "addobjto3D_act", "removeobj3D_act", "export3D_obj_act", "export3D_off_act",
    "export3D_ply_act", "export3D_stl_act", "export3D_dae_act", "exportmeshdata",
    "editobj3D_act", "csztrace_act", "atztrace_act", "objhistory_act",
    "setpaletteobj_act", "deleteobj_act",
}

PRE_REDESIGN_TRACE_LIST_ACTS = {
    "edittrace_act", "copytosections_act", "smoothtraces_act", "mergetraces_act",
    "mergeobjects_act", "makenegative_act", "makepositive_act", "hidetraces_act",
    "unhidetraces_act", "opentraces_act", "closedtraces_act", "edittraceshape_act",
    "edittraceradius_act", "createtraceflag_act", "deletetrace_act",
}

PRE_REDESIGN_ZTRACE_ACTS = {
    "editztracce_act", "smoothztrace_act", "addto3D_act", "remove3D_act",
    "addztracegroup_act", "removeztracegroup_act", "removeztraceallgroups_act",
    "setztracealignment_act", "deleteztrace_act",
}

PRE_REDESIGN_FIELD_ACTS = {
    "editselected_act", "copytosections_act", "focus_act", "unhideall_act",
    "hideall_act", "showall_act", "hideimage_act", "blend_act", "selectall_act",
    "deselect_act", "invertselection_act", "delete_act",
}


def test_no_object_action_was_lost():
    names = set(_act_names(_obj_menu(list_ops=OBJ_LIST_OPS)))
    missing = PRE_REDESIGN_OBJECT_ACTS - names
    assert not missing, f"object actions lost: {sorted(missing)}"


def test_no_trace_list_action_was_lost():
    names = set(_act_names(_trace_menu(
        is_in_field=False, list_ops=TRACE_LIST_OPS, find_in_field=lambda: None
    )))
    missing = PRE_REDESIGN_TRACE_LIST_ACTS - names
    assert not missing, f"trace-list actions lost: {sorted(missing)}"


def test_no_ztrace_action_was_lost():
    names = set(_act_names(_ztrace_menu(list_ops=ZTRACE_LIST_OPS)))
    missing = PRE_REDESIGN_ZTRACE_ACTS - names
    assert not missing, f"z-trace actions lost: {sorted(missing)}"


def test_no_field_action_was_lost():
    """Field-menu-owned actions, plus the trace actions that moved to the top
    strip (they must be reachable from the field menu one way or another)."""
    names = set(_act_names(_field_menu()))
    missing = PRE_REDESIGN_FIELD_ACTS - names
    assert not missing, f"field actions lost: {sorted(missing)}"
    for act in ("mergetraces_act", "mergeobjects_act", "hidetraces_act",
                "edittrace_act", "hideothertraces_act", "smoothtraces_act",
                "makenegative_act", "makepositive_act"):
        assert act in names, f"{act} is no longer reachable from the field menu"


def test_field_menu_attr_names_are_unique():
    """Field, trace, object and z-trace menus are all populated onto the SAME
    widget, so one duplicated name silently shadows another action."""
    names = _act_names(_field_menu())
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate attr_names across the field menus: {sorted(dupes)}"


# --------------------------------------------------------------------------- #
# 12. selection gating covers the hoisted actions
# --------------------------------------------------------------------------- #
def test_hoisted_actions_are_in_the_field_selection_gating_list():
    """They used to be gated by disabling the whole "Trace >" submenu; at top
    level they need their own entries in MainWindow.trace_actions or they stay
    clickable with nothing selected."""
    import inspect
    from PyReconstruct.modules.gui.main.main_window import MainWindow

    src = inspect.getsource(MainWindow.createContextMenus)
    gating = src.split("self.trace_actions = [")[1].split("]")[0]
    for act in ("mergetraces_act", "mergeobjects_act", "hidetraces_act"):
        assert f"self.{act}" in gating, f"{act} is not gated by the selection"
