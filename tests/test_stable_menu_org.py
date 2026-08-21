"""The stable line's context menus follow upstream's organization.

This line ships to users who also encounter upstream builds, so the right-click
menus keep upstream's structure: the same containers, the same order, the same
labels. The fork's menu reorganization lives on the test line only. What this
file pins is the agreement, plus the three kinds of deliberate divergence the
builder documents: shipped fork rows keep their entry, shortcut fixes stay
(series forms, unique act names), and the list widgets' extra parameters keep
working.

Trees are pinned by TOP-LEVEL shape rather than full label dumps: the point is
that a user's mental map of upstream holds here, and the top level is that map.
"""
import pytest

from menu_test_helpers import (
    _Anything,
    _FieldStub,
    _act_names,
    _field_menu,
    _kbds,
    _main_window_stub,
    _series,
)
from PyReconstruct.modules.gui.main.context_menu_list import (
    get_context_menu_list_obj,
    get_context_menu_list_trace,
)


def _top_level(menu):
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
# upstream's shape
# --------------------------------------------------------------------------- #
def test_field_root_is_upstream_shaped():
    assert _top_level(_field_menu()) == [
        "Trace >",
        "Object >",
        "Ztrace >",
        "-----",
        "View >",
        "Series alignment >",
        "-----",
        "<QAction>",            # Cut (menubar action)
        "<QAction>",            # Copy
        "Copy to sections...",
        "<QAction>",            # Paste
        "<QAction>",            # Paste attributes
        "-----",
        "Select all traces",
        "Deselect all traces",
        "Invert selection",
        "-----",
        "Delete",
    ]


def test_object_menu_is_upstream_shaped():
    menu = get_context_menu_list_obj(_FieldStub())
    assert _top_level(menu) == [
        "Edit attributes of traces...",
        "-----",
        "Object attributes >",
        "Operations >",
        "Custom categories >",
        "Set curation >",
        "3D >",
        "Create ztrace >",
        "-----",
        "View history",
        "-----",
        "Copy attributes to palette",
        "-----",
        "Delete",
    ]


def test_trace_menu_is_upstream_shaped_in_the_field():
    names = _act_names(get_context_menu_list_trace(_FieldStub(), is_in_field=True))
    assert names == [
        "edittrace_act", "smoothtraces_act", "mergetraces_act",
        "mergeobjects_act", "makenegative_act", "makepositive_act",
        "hidetraces_act",
        # this line's shipped isolate row, directly after Hide
        "hideothertraces_act",
    ]


# --------------------------------------------------------------------------- #
# the shipped fork rows keep their entry
# --------------------------------------------------------------------------- #
def test_shipped_rows_survive_the_reorganization():
    """Rows this line has already released must not vanish from the menus."""
    obj = _act_names(get_context_menu_list_obj(_FieldStub()))
    for act in ("reapplyautosegcolors_act", "restorevisibility_act",
                "hideallobj_act"):
        assert act in obj, f"{act} lost its menu entry"

    listed = _act_names(get_context_menu_list_trace(
        _FieldStub(), is_in_field=False,
        list_ops=[("x_act", "X", "", None)], find_in_field=lambda: None,
    ))
    assert "findinfield_act" in listed
    assert "x_act" in listed, "the list_ops utility slot stopped mounting"


# --------------------------------------------------------------------------- #
# the shortcut fixes stay
# --------------------------------------------------------------------------- #
def test_keyed_rows_carry_the_series_form_through_the_field_only():
    """Bindings resolve by act_name through the field's copy of a menu; the
    list copies pass "" so one window never holds two claimants for one key."""
    series = _series()
    stub = _FieldStub(series)

    field_obj = _kbds(get_context_menu_list_obj(stub))
    assert field_obj["sethosts_act"] is series
    assert field_obj["addobjto3D_act"] is series

    list_obj = _kbds(get_context_menu_list_obj(stub, is_in_field=False))
    assert list_obj["sethosts_act"] == ""
    assert list_obj["addobjto3D_act"] == ""

    field_trace = _kbds(get_context_menu_list_trace(stub, is_in_field=True))
    for act in ("edittrace_act", "mergetraces_act", "mergeobjects_act",
                "hidetraces_act"):
        assert field_trace[act] is series
    list_trace = _kbds(get_context_menu_list_trace(stub, is_in_field=False))
    for act in ("edittrace_act", "mergetraces_act", "mergeobjects_act",
                "hidetraces_act"):
        assert list_trace[act] == ""

    root = _kbds(_field_menu(series))
    assert root["copytosections_act"] is series
    assert root["delete_act"] == "Del"


@pytest.mark.parametrize("build", [
    lambda: _field_menu(),
    lambda: get_context_menu_list_obj(_FieldStub()),
    lambda: get_context_menu_list_obj(
        _FieldStub(), is_in_field=False, list_ops=[("u_act", "U", "", None)]),
    lambda: get_context_menu_list_trace(
        _FieldStub(), is_in_field=False,
        list_ops=[("u_act", "U", "", None)], find_in_field=lambda: None),
])
def test_no_act_name_is_duplicated_on_one_widget(build):
    """Two rows with one attr_name on one widget silently shadow (the trap
    upstream's five shared "export3D_act" rows fall into; this line keeps the
    unique names)."""
    names = _act_names(build())
    assert len(names) == len(set(names)), sorted(
        n for n in names if names.count(n) > 1
    )
