"""Discoverability and shortcut for "Add to 3D scene".

Three things were wrong, all reported by the maintainer while using the app:

  1. "Add to 3D scene" existed ONLY at top level, four rows up in the frequent-
     actions strip. Its natural home, the "3D >" submenu, held only "Remove from
     scene", so anyone looking for "add" opened "3D >", did not find it, and hunted.
     Fix: it appears in BOTH places, which is how "Edit object attributes..."
     already behaves.
  2. It had no keyboard shortcut at all, and no way to map one, because the
     shortcuts dialog only lists actions it knows about.
  3. The shortcut must not be duplicated onto the submenu copy: two actions
     sharing one sequence is an AMBIGUOUS shortcut, and Qt answers an ambiguous
     shortcut by firing NEITHER action. That is the trap that made Ctrl+Shift+C
     unusable for copy-to-sections, so it is pinned here rather than rediscovered.
"""

import re
from pathlib import Path

import PyReconstruct
from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.gui.main.context_menu_list import (
    get_context_menu_list_obj,
)

from test_menu_restructure import _ObjMenuStub, _names, _obj_menu, _submenu, _walk

ADD_ACT = "addobjto3D_act"
ADD_SUB_ACT = "addobjto3Dsub_act"
EXPECTED_KEY = "Ctrl+Shift+D"


def _entry(walked, act_name):
    for name, text, kbd in walked:
        if name == act_name:
            return name, text, kbd
    return None


# --------------------------------------------------------------------------- #
# 1. present in both places
# --------------------------------------------------------------------------- #
def test_add_to_3d_is_at_top_level_exactly_once():
    assert _names(_obj_menu()).count(ADD_ACT) == 1


def test_add_to_scene_also_lives_in_the_3d_submenu():
    menu = get_context_menu_list_obj(_ObjMenuStub())
    submenu = _submenu(menu, "3D")
    assert submenu is not None, '"3D >" submenu missing'
    names = _names(list(_walk(submenu)))
    assert ADD_SUB_ACT in names, 'no "Add to scene" inside "3D >"'
    # the pair should be discoverable together
    assert "removeobj3D_act" in names


def test_the_two_copies_use_distinct_attr_names():
    """Reusing one attr_name would make the second action overwrite the first
    on the widget (newAction does setattr(widget, act_name, action))."""
    assert ADD_ACT != ADD_SUB_ACT
    names = _names(_obj_menu())
    assert names.count(ADD_SUB_ACT) == 1


def test_both_copies_invoke_the_same_handler():
    menu = get_context_menu_list_obj(_ObjMenuStub())
    flat = [e for e in _walk_full(menu) if e[0] in (ADD_ACT, ADD_SUB_ACT)]
    assert len(flat) == 2
    # the stub returns a fresh lambda per attribute access, so compare by the
    # source attribute name rather than identity
    src = Path(PyReconstruct.__file__).parent / "modules/gui/main/context_menu_list.py"
    text = src.read_text()
    assert text.count("self.addTo3D") == 2, "both entries should call self.addTo3D"


def _walk_full(menu):
    for entry in menu:
        if isinstance(entry, tuple):
            yield entry
        elif isinstance(entry, dict):
            yield from _walk_full(entry["opts"])


# --------------------------------------------------------------------------- #
# 2. mappable shortcut
# --------------------------------------------------------------------------- #
def test_add_to_3d_has_a_default_shortcut():
    assert default_settings.get(ADD_ACT) == EXPECTED_KEY


def test_shortcut_is_unique_across_every_default_binding():
    """An ambiguous sequence makes Qt fire neither action."""
    seqs = {}
    for name, value in default_settings.items():
        if not name.endswith("_act") or not isinstance(value, str) or not value:
            continue
        seqs.setdefault(value, []).append(name)
    dupes = {k: v for k, v in seqs.items() if len(v) > 1}
    assert not dupes, f"duplicate shortcut sequences: {dupes}"


def test_shortcut_is_listed_in_the_shortcuts_dialog():
    """Without this row the key exists but cannot be re-mapped by the user."""
    src = Path(PyReconstruct.__file__).parent / "modules/gui/dialog/shortcuts.py"
    assert re.search(rf'\("{ADD_ACT}",', src.read_text()), (
        f"{ADD_ACT} missing from the shortcuts dialog list"
    )


# --------------------------------------------------------------------------- #
# 3. the ambiguity trap
# --------------------------------------------------------------------------- #
def test_only_the_top_level_copy_carries_the_shortcut():
    menu = get_context_menu_list_obj(_ObjMenuStub())
    top = _entry(_obj_menu(), ADD_ACT)
    sub_opts = _submenu(menu, "3D")
    sub = _entry(list(_walk(sub_opts)), ADD_SUB_ACT)

    assert top is not None and sub is not None
    # the top-level copy passes a Series, which newAction resolves via
    # series.getOption(act_name); the submenu copy passes an empty string
    assert top[2] != "", "top-level copy should resolve a configurable shortcut"
    assert sub[2] == "", (
        "submenu copy must NOT carry a shortcut; duplicating it makes the "
        "sequence ambiguous and Qt then fires neither action"
    )
