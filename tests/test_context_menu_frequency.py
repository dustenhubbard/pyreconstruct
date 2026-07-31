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

    def getObjMenu(self, list_ops=None):
        return get_context_menu_list_obj(self, list_ops=list_ops)

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
    # top strip: exactly the four shortcut-bearing trace actions
    "Edit attributes...",
    "Merge traces",
    "Merge attributes only",
    "Hide traces",
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


def test_field_top_strip_is_exactly_four_actions():
    """Approved as four: the dynamic edit item plus merge / merge-attrs / hide.
    Smooth and Make negative/positive were deliberately NOT hoisted."""
    rows = _top_level(_field_menu())
    strip = rows[: rows.index("-----")]
    assert strip == [
        "Edit attributes...", "Merge traces",
        "Merge attributes only", "Hide traces",
    ]
    assert "Smooth traces" not in strip
    assert "Make negative" not in strip
    assert "Make positive" not in strip


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
    # the whole visibility family, flat, in its established order
    "Hide",
    "Unhide",
    "Hide other objects",
    "Hide all objects",
    "Show all objects",
    "-----",
    # object-level settings, one section
    "Comment...",
    "Duplicate object",
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
    "Object attributes >",
    "    Set hosts...",
    "    Clear hosts",
    "    Show host tree",
    "    Show inhabitant tree",
    "    -----",
    "    Edit alignment...",
    "    Reapply autoseg colors...",
    "    -----",
    "    Lock",
    "    Unlock",
    "Geometry >",
    "    Edit radius...",
    "    Edit shape...",
    "    Smooth traces",
    "    Split into separate objects",
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
    assert rows.index("Invert selection") > rows.index("Hide")
    assert rows.index("Copy object values") < rows.index("Delete objects")


@pytest.mark.parametrize("label", [
    "Comment...", "Duplicate object", "Add to 3D scene",
    "Hide", "Hide other objects",
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

    Order only. Nothing was renamed, added, removed, or moved between a submenu
    and the top level. This test replaces the ordering the previous
    frequency-first rework pinned; that decision was not wrong, it was
    superseded.
    """
    assert _top_level(_obj_menu()) == [
        "Edit object attributes...",
        "Add to 3D scene",
        "3D >",
        "-----",
        "Hide",
        "Unhide",
        "Hide other objects",
        "Hide all objects",
        "Show all objects",
        "-----",
        "Comment...",
        "Duplicate object",
        "Group >",
        "Set curation >",
        "Custom categories >",
        "Object attributes >",
        "Geometry >",
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
    the same section as "Object attributes >" and "Geometry >" -- his reasoning
    for moving them down. A separator between any two of them would split the
    section again."""
    rows = _top_level(_obj_menu())
    members = ["Group >", "Set curation >", "Object attributes >", "Geometry >"]
    idx = [rows.index(m) for m in members]
    assert idx == sorted(idx)
    assert "-----" not in rows[idx[0]:idx[-1] + 1], (
        "the object-level settings are split across sections"
    )


def test_comment_and_duplicate_are_below_the_top_spots():
    """"Edit object attributes and Add to 3D scene deserve the frequently used
    top spots but not Comment nor Duplicate object." Both stay top-level (one
    click), just not in the strip above the first separator."""
    rows = _top_level(_obj_menu())
    strip = rows[: rows.index("-----")]
    assert strip == ["Edit object attributes...", "Add to 3D scene", "3D >"]
    assert "Comment..." not in strip
    assert "Duplicate object" not in strip


def test_the_visibility_section_was_left_alone():
    """"The view section with the various Hide options is good" -- unchanged
    members, unchanged order, still one uninterrupted section."""
    rows = _top_level(_obj_menu())
    start = rows.index("Hide")
    assert rows[start - 1] == "-----"
    assert rows[start:start + 5] == [
        "Hide", "Unhide", "Hide other objects", "Hide all objects",
        "Show all objects",
    ]
    assert rows[start + 5] == "-----"


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
    so "Comment..." is honest on the object menu -- and frequent, so top-level."""
    assert "Comment..." in _top_level(_obj_menu())


def test_bulk_tag_action_is_not_filed_as_an_object_attribute():
    """Tags live on Trace, not on the object. On an OBJECT menu "Remove all
    tags" strips tags from every trace of the selected objects, series-wide
    (series.removeAllTraceTags) -- a bulk TRACE operation. Filing it under
    "Object attributes >" would misdescribe it, and "Geometry >" (its old home)
    is not geometry either."""
    menu = _obj_menu()
    attrs = next(e for e in menu if isinstance(e, dict)
                 and e["text"] == "Object attributes")
    assert "removealltags_act" not in _act_names(attrs["opts"])
    geometry = next(e for e in menu if isinstance(e, dict)
                    and e["text"] == "Geometry")
    assert "removealltags_act" not in _act_names(geometry["opts"])


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
    alignment, color, lock) -- nothing trace-level."""
    attrs = next(e for e in _obj_menu() if isinstance(e, dict)
                 and e["text"] == "Object attributes")
    assert _rows(attrs["opts"]) == [
        "Set hosts...",
        "Clear hosts",
        "Show host tree",
        "Show inhabitant tree",
        "-----",
        "Edit alignment...",
        "Reapply autoseg colors...",
        "-----",
        "Lock",
        "Unlock",
    ]


# --------------------------------------------------------------------------- #
# 5. trace menu (field "Trace >" + trace list)
# --------------------------------------------------------------------------- #
TRACE_FIELD_ROWS = [
    "Edit trace attributes...",
    "-----",
    # long tail only -- edit/merge/hide are on the field menu's top strip
    "Smooth traces",
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
    "Hide traces",
    "Unhide",
    "-----",
    "Set open",
    "Set closed",
    "Make negative",
    "Make positive",
    "Edit radius...",
    "Edit shape...",
    "Smooth traces",
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
        os.path.dirname(__file__), "..", "PyReconstruct",
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
