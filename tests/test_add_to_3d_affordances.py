"""The "Add to scene" action keeps a working, remappable shortcut.

The dual-placement affordances this file used to pin (a hoisted top-level copy
plus the 3D-submenu copy, distinct attr names, one shortcut carrier) left with
the frequency-first menus (2026-08-21: Dev follows stable's context-menu
organization until a new scheme lands; the pins live in git history beside
it). What must hold under any organization: the action has its default key,
no default binding collides with another, and the key is remappable from the
shortcuts dialog.
"""
import re
from pathlib import Path

import PyReconstruct
from PyReconstruct.modules.datatypes.default_settings import default_settings

ADD_ACT = "addobjto3D_act"
EXPECTED_KEY = default_settings.get(ADD_ACT)  # pinned non-empty just below


def test_add_to_3d_has_a_default_shortcut():
    assert isinstance(EXPECTED_KEY, str) and EXPECTED_KEY


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
