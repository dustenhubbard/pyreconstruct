"""Context-menu UX overhaul, phase 2a (PR3 + PR4).

PR3 -- object-menu restructure:
  * the old "Operations" grab-bag is dissolved into "Visibility" and
    "Geometry" submenus; the attributes submenu is titled "Object attributes";
  * Lock/Unlock has a SINGLE home (the Attributes submenu) -- the duplicate
    pair (lockobj_act1 / unlockobj_act1) is gone;
  * the five 3D-export formats carry UNIQUE attr_names (they previously all
    shared "export3D_act", so four silently shadowed the fifth on the widget);
  * the Collada dependency note left the label (surfaced in the handler);
  * the object list's duplicate "Set columns..." (List menu) is gone.

PR4 -- the six View "Toggle X" items become checkable items named for the
state, keeping their user-configurable keyboard shortcuts, and their checked
state is (re)synced from the live field state whenever the menu opens WITHOUT
re-firing the toggle handler.

The list-shape checks build the real menu definitions against light stubs (no
Qt loop). The checkbox-mechanism checks build real QActions via the actual
newAction helper and drive the exact resync the app runs in checkActions.
"""
import os
import shutil
import types

import pytest

from PyReconstruct.modules.gui.main.context_menu_list import (
    get_context_menu_list_obj,
    get_field_menu_list,
)


# --------------------------------------------------------------------------- #
# stubs + flattening helper (mirrors test_invert_hide_others)
# --------------------------------------------------------------------------- #
class _Anything:
    """Any attribute access yields a callable returning an empty list, so
    submenu builders return something iterable and callbacks are harmless."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


class _ObjMenuStub(_Anything):
    def __init__(self):
        super().__init__(
            series=_Anything(user_columns={}, alignments=set(), groups_visibility={})
        )


class _FieldMenuStub(_Anything):
    def __init__(self):
        super().__init__(
            series=_Anything(user_columns={}, alignments=set(), groups_visibility={}),
            field=_Anything(),
        )


def _walk(menu):
    """Yield (act_name, text, kbd) for every leaf action, recursing submenus."""
    for entry in menu:
        if isinstance(entry, tuple):
            yield entry[0], entry[1], entry[2]
        elif isinstance(entry, dict):
            yield from _walk(entry["opts"])


def _obj_menu():
    return list(_walk(get_context_menu_list_obj(_ObjMenuStub())))


def _field_menu():
    return list(_walk(get_field_menu_list(_FieldMenuStub())))


def _names(walked):
    return [n for n, _t, _k in walked]


def _submenu(menu, title):
    """Return the opts list of the first submenu whose text == title."""
    for entry in menu:
        if isinstance(entry, dict):
            if entry["text"] == title:
                return entry["opts"]
            found = _submenu(entry["opts"], title)
            if found is not None:
                return found
    return None


# --------------------------------------------------------------------------- #
# PR3: single Lock/Unlock home
# --------------------------------------------------------------------------- #
def test_lock_unlock_appear_exactly_once():
    names = _names(_obj_menu())
    assert names.count("lockobj_act") == 1
    assert names.count("unlockobj_act") == 1


def test_duplicate_lock_pair_is_gone():
    names = _names(_obj_menu())
    assert "lockobj_act1" not in names
    assert "unlockobj_act1" not in names


def test_lock_unlock_live_in_attributes_submenu():
    menu = get_context_menu_list_obj(_ObjMenuStub())
    attrs = _submenu(menu, "Object attributes")
    assert attrs is not None, "Object attributes submenu missing"
    attr_names = _names(list(_walk(attrs)))
    assert "lockobj_act" in attr_names and "unlockobj_act" in attr_names


# --------------------------------------------------------------------------- #
# PR3: Operations dissolved into Visibility + Geometry
# --------------------------------------------------------------------------- #
def test_operations_grabbag_is_dissolved():
    menu = get_context_menu_list_obj(_ObjMenuStub())
    assert _submenu(menu, "Operations") is None
    assert _submenu(menu, "Attributes") is None  # reverted from phase-2a retitle
    assert _submenu(menu, "Object attributes") is not None
    assert _submenu(menu, "Visibility") is not None
    assert _submenu(menu, "Geometry") is not None


def test_visibility_submenu_holds_the_five_visibility_actions():
    menu = get_context_menu_list_obj(_ObjMenuStub())
    vis = _names(list(_walk(_submenu(menu, "Visibility"))))
    assert vis == [
        "hideobj_act", "unhideobj_act", "hideotherobj_act",
        "hideallobj_act", "showallobj_act",
    ]


def test_geometry_submenu_holds_the_geometry_actions():
    menu = get_context_menu_list_obj(_ObjMenuStub())
    geo = _names(list(_walk(_submenu(menu, "Geometry"))))
    assert geo == [
        "copyobj_act", "editobjradius_act", "editobjshape_act",
        "smoothobj_act", "splitobj_act", "removealltags_act",
    ]


def test_no_object_capability_was_lost_in_restructure():
    """Every function reachable before the restructure is still reachable.

    Guards against a submenu-move silently dropping an action. The list is the
    full pre-restructure object-menu capability set (by act_name), minus the
    two duplicate lock entries whose capability survives via lockobj_act /
    unlockobj_act.
    """
    expected = {
        "editobjattribtues_act", "editobjcomment_act", "sethosts_act",
        "clearhosts_act", "displayinhabitants_act", "displayhosts_act",
        "addobjgroup_act", "removeobjgroup_act", "removeobjallgroups_act",
        "setobjalignment_act", "lockobj_act", "unlockobj_act",
        "copyobj_act", "editobjradius_act", "editobjshape_act",
        "smoothobj_act", "splitobj_act", "hideobj_act", "unhideobj_act",
        "hideotherobj_act", "hideallobj_act", "showallobj_act",
        "removealltags_act", "blankcurate_act", "needscuration_act",
        "curated_act", "addobjto3D_act", "removeobj3D_act", "exportmeshdata",
        "editobj3D_act", "csztrace_act", "atztrace_act", "objhistory_act",
        "setpaletteobj_act", "deleteobj_act",
    }
    names = set(_names(_obj_menu()))
    missing = expected - names
    assert not missing, f"capabilities lost in restructure: {sorted(missing)}"


# --------------------------------------------------------------------------- #
# PR3: unique 3D-export attr_names + Collada label
# --------------------------------------------------------------------------- #
def test_export_formats_have_unique_attr_names():
    walked = _obj_menu()
    export_names = [n for n, _t, _k in walked if n.startswith("export3D_")]
    assert set(export_names) == {
        "export3D_obj_act", "export3D_off_act", "export3D_ply_act",
        "export3D_stl_act", "export3D_dae_act",
    }
    assert len(export_names) == len(set(export_names)) == 5
    assert "export3D_act" not in _names(walked)  # the old shared name is gone


def test_collada_label_helper_is_pure():
    """The label flags a missing dependency but never crams the old note in."""
    from PyReconstruct.modules.gui.main.context_menu_list import collada_menu_label
    assert collada_menu_label(True) == "Collada (.dae)"
    assert collada_menu_label(False) == "Collada (.dae) (not installed)"
    # the pre-fix dependency note is gone from both branches
    assert "requires" not in collada_menu_label(True).lower()
    assert "requires" not in collada_menu_label(False).lower()


def test_collada_label_reflects_availability(monkeypatch):
    """The built menu label tracks live pycollada availability."""
    import PyReconstruct.modules.backend.volume.export_volumes as ev

    monkeypatch.setattr(ev, "collada_available", lambda: True)
    dae = [t for n, t, _k in _obj_menu() if n == "export3D_dae_act"]
    assert dae == ["Collada (.dae)"]

    monkeypatch.setattr(ev, "collada_available", lambda: False)
    dae = [t for n, t, _k in _obj_menu() if n == "export3D_dae_act"]
    assert dae == ["Collada (.dae) (not installed)"]


def test_collada_menu_item_disabled_only_when_absent(qapp, monkeypatch):
    """disable_unavailable_export_formats greys out .dae iff pycollada is
    missing, and never touches the item when it IS present."""
    from PySide6.QtGui import QAction
    import PyReconstruct.modules.backend.volume.export_volumes as ev
    from PyReconstruct.modules.gui.main.context_menu_list import (
        disable_unavailable_export_formats,
    )

    # absent -> disabled
    monkeypatch.setattr(ev, "collada_available", lambda: False)
    w = types.SimpleNamespace(export3D_dae_act=QAction("Collada (.dae) (not installed)"))
    disable_unavailable_export_formats(w)
    assert w.export3D_dae_act.isEnabled() is False

    # present -> left enabled (must not break when Collada IS available)
    monkeypatch.setattr(ev, "collada_available", lambda: True)
    w = types.SimpleNamespace(export3D_dae_act=QAction("Collada (.dae)"))
    disable_unavailable_export_formats(w)
    assert w.export3D_dae_act.isEnabled() is True

    # no export action on the widget -> harmless no-op
    disable_unavailable_export_formats(types.SimpleNamespace())


def test_smooth_action_names_do_not_shadow_across_menus():
    """The object 'Smooth traces' and the field-trace 'Smooth traces' are
    populated onto the same widget, so they must carry DISTINCT attr_names
    (else one silently shadows the other, as export3D_act once did)."""
    from PyReconstruct.modules.gui.main.context_menu_list import (
        get_context_menu_list_trace,
    )
    obj_names = _names(_obj_menu())
    trace_names = _names(list(_walk(get_context_menu_list_trace(_Anything()))))
    assert "smoothobj_act" in obj_names
    assert "smoothtraces_act" in trace_names
    assert "smoothobj_act" not in trace_names
    assert "smoothtraces_act" not in obj_names


def test_export_submenu_retitled():
    menu = get_context_menu_list_obj(_ObjMenuStub())
    assert _submenu(menu, "Export mesh as") is not None
    assert _submenu(menu, "Export meshes") is None


# --------------------------------------------------------------------------- #
# PR3: attr_name uniqueness guard (the class of bug this phase fixes)
# --------------------------------------------------------------------------- #
def test_object_menu_attr_names_are_unique():
    names = _names(_obj_menu())
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate attr_names in object menu: {sorted(dupes)}"


def test_object_list_set_columns_defined_once():
    """The object-list menubar previously carried "Set columns..." in both the
    List and Columns menus (same columns_act); only the Columns one remains."""
    import PyReconstruct.modules.gui.table.object as objmod
    src = objmod.__file__
    with open(src, encoding="utf-8") as fp:
        text = fp.read()
    assert text.count('("columns_act", "Set columns..."') == 1


# --------------------------------------------------------------------------- #
# PR4: View toggles are checkable and keep their shortcuts (list shape)
# --------------------------------------------------------------------------- #
CHECKBOX_TOGGLES = ["focus_act", "hideall_act", "showall_act",
                    "hideimage_act", "blend_act"]


def test_view_toggles_are_checkbox_tuples_with_series_shortcut():
    walked = {n: k for n, _t, k in _field_menu()}
    for act in CHECKBOX_TOGGLES:
        kbd = walked[act]
        assert isinstance(kbd, tuple), f"{act} is not a (series, 'checkbox') tuple"
        _series, flag = kbd
        assert flag == "checkbox"


def test_view_toggle_labels_name_the_state_not_toggle():
    labels = {n: t for n, t, _k in _field_menu()}
    assert labels["focus_act"] == "Focus mode"
    assert labels["hideall_act"] == "Hide trace layer"
    assert labels["showall_act"] == "Show all traces (ignore hidden)"
    assert labels["hideimage_act"] == "Hide image"
    assert labels["blend_act"] == "Section blend"
    for act in CHECKBOX_TOGGLES:
        assert not labels[act].startswith("Toggle")


def test_unhide_all_stays_a_plain_action():
    """The one-shot 'Unhide all traces (this section)' must NOT become a
    checkbox -- it is not a persistent state."""
    walked = {n: k for n, _t, k in _field_menu()}
    kbd = walked["unhideall_act"]
    assert not isinstance(kbd, tuple)  # still the plain series-shortcut form


# --------------------------------------------------------------------------- #
# PR4: the checkbox mechanism -- real QActions via newAction, resync both ways
# --------------------------------------------------------------------------- #
FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def _series(tmp_path):
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(DictSettingsStore())
    return series


def test_checkbox_tuple_makes_checkable_action_with_shortcut(qapp, tmp_path):
    """(series, 'checkbox') -> checkable action whose shortcut still comes from
    the user-configurable series option (focus_act defaults to 'X')."""
    from PySide6.QtWidgets import QWidget, QMenu
    from PyReconstruct.modules.gui.utils.utils import newAction

    series = _series(tmp_path)
    widget, menu = QWidget(), QMenu()
    fired = []
    newAction(widget, menu,
              ("focus_act", "Focus mode", (series, "checkbox"), lambda: fired.append(1)))

    act = widget.focus_act
    assert act.isCheckable()
    assert act.shortcut().toString() == series.getOption("focus_act") == "X"
    assert fired == []  # building the action does not fire the handler


def test_checkbox_resync_follows_state_both_directions_without_firing(qapp, tmp_path):
    """The exact resync checkActions runs: setChecked(live state) must move the
    checkbox ON->and->OFF and never re-fire the toggle handler (setChecked emits
    `toggled`, the handler is on `triggered`)."""
    from PySide6.QtWidgets import QWidget, QMenu
    from PyReconstruct.modules.gui.utils.utils import newAction

    series = _series(tmp_path)
    widget, menu = QWidget(), QMenu()

    # a stand-in field whose flag the handler flips, wired exactly like the app
    field = types.SimpleNamespace(hide_trace_layer=False)
    fired = []

    def toggle_handler():
        fired.append(1)
        field.hide_trace_layer = not field.hide_trace_layer

    newAction(widget, menu,
              ("hideall_act", "Hide trace layer", (series, "checkbox"), toggle_handler))
    act = widget.hideall_act

    def resync():  # the line checkActions runs for this toggle
        act.setChecked(field.hide_trace_layer)

    # OFF at build
    resync()
    assert act.isChecked() is False

    # state goes ON elsewhere (e.g. via shortcut) -> resync reflects it
    field.hide_trace_layer = True
    resync()
    assert act.isChecked() is True

    # state goes OFF -> resync reflects it (the other direction)
    field.hide_trace_layer = False
    resync()
    assert act.isChecked() is False

    # none of the resyncs fired the toggle handler
    assert fired == [], "programmatic setChecked must not fire the toggle handler"


def test_triggered_fires_handler_but_resync_does_not(qapp, tmp_path):
    """Sanity: the handler IS reachable via trigger() (user action), proving the
    'no fire' above is about setChecked specifically, not a dead connection."""
    from PySide6.QtWidgets import QWidget, QMenu
    from PyReconstruct.modules.gui.utils.utils import newAction

    series = _series(tmp_path)
    widget, menu = QWidget(), QMenu()
    fired = []
    newAction(widget, menu,
              ("blend_act", "Section blend", (series, "checkbox"), lambda: fired.append(1)))
    act = widget.blend_act

    act.setChecked(True)          # resync path
    assert fired == []
    act.trigger()                 # user path
    assert fired == [1]


# --------------------------------------------------------------------------- #
# PR3: Collada dependency surfaced gracefully in the export handler
# --------------------------------------------------------------------------- #
def test_dae_export_without_pycollada_notifies_and_does_not_raise(monkeypatch):
    """With the Collada note gone from the label, the requirement is surfaced
    in export3DObjects: a missing 'pycollada' yields a clear notify() and an
    early return -- NOT an unhandled ModuleNotFoundError, and no mesh work."""
    import sys
    import PyReconstruct.modules.backend.volume.export_volumes as ev

    # make `import collada` fail deterministically, even where it is installed
    monkeypatch.setitem(sys.modules, "collada", None)

    messages = []
    monkeypatch.setattr(ev, "notify", lambda msg, *a, **k: messages.append(msg))
    # if the guard failed to return early, this would run and blow up
    monkeypatch.setattr(ev, "get_3D_meshes",
                        lambda *a, **k: pytest.fail("reached mesh build for missing collada"))

    # must not raise
    ev.export3DObjects(object(), [], "/tmp/whatever", "dae")

    assert len(messages) == 1
    assert "pycollada" in messages[0]


def test_non_dae_export_is_unaffected_by_collada_guard(monkeypatch):
    """The guard is scoped to 'dae': other formats proceed to mesh building."""
    import sys
    import PyReconstruct.modules.backend.volume.export_volumes as ev

    monkeypatch.setitem(sys.modules, "collada", None)  # collada 'missing'
    reached = []
    monkeypatch.setattr(ev, "notify", lambda *a, **k: None)
    monkeypatch.setattr(ev, "get_3D_meshes", lambda *a, **k: reached.append(1) or {})

    ev.export3DObjects(object(), [], "/tmp/whatever", "stl", notify_user=False)
    assert reached == [1]
