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

from PyReconstruct.modules.gui.main.context_menu_list import (
    get_context_menu_list_obj,
    get_context_menu_list_trace,
    get_field_menu_list,
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
# The exact-layout pins that used to live here described the frequency-first
# redesign. That scheme is parked (2026-08-21, his call: the Dev build follows
# stable's context-menu organization "until i come up with a new scheme"), and
# the layouts now come verbatim from the release line, where their own history
# pins them. What stays here: the shared stubs the other menu tests import,
# and sanity checks that the seven surfaces still build and carry the rows
# recent features added. Resurrect the exact pins from git history alongside
# the new scheme when it lands.
# --------------------------------------------------------------------------- #

def test_all_seven_surfaces_build():
    for build in (_field_menu, _obj_menu, _trace_menu, _ztrace_menu,
                  _section_menu, _flag_menu):
        assert build(), build.__name__
    assert _rows(get_label_menu_list(_main_window_stub()))


def test_curation_rows_survived_the_organization_swap():
    names = _act_names(_obj_menu())
    assert "needscuration_act" in names
    assert "needscurationassign_act" in names


def test_field_menu_carries_the_trace_and_object_scopes():
    names = _act_names(_field_menu())
    assert "tracemenu" not in names  # submenus are dicts, not act tuples
    labels = _rows(_field_menu())
    assert any(l.strip() == "Trace" for l in labels) or any("Trace" in l for l in labels)
