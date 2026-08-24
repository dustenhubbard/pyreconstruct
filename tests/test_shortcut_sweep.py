"""The 2026-08-23 shortcut sweep: scheme C plus the two macOS collisions.

Every move defuses a reflex trap; every freed chord stays deliberately
unbound so an old habit lands on silence; the one legacy chord with deep
roots (Ctrl+B, paste attributes) keeps working through an alias that yields
the moment any other binding claims it.
"""
import pytest

from PyReconstruct.modules.datatypes.default_settings import (
    LEGACY_SHORTCUT_ALIASES, default_settings,
)

pytestmark = pytest.mark.gui

SWEEP = {
    "incpaletteup_act": "Ctrl+]",     # off the zoom reflex
    "incpalettedown_act": "Ctrl+[",
    "ztracelist_act": "Ctrl+Alt+Z",   # off the Mac redo reflex
    "restart_act": "Ctrl+Alt+R",     # off browser refresh (Ctrl+Shift+R is smooth's)
    "pasteattributes_act": "Ctrl+Shift+V",  # the paste-special convention
    "alloptions_act": "Ctrl+,",       # the preferences convention
    "hidetraces_act": "Shift+H",      # Ctrl+H is Cmd+H on a Mac: Hide app
    "mergetraces_act": "Shift+M",     # Ctrl+M is Cmd+M on a Mac: Minimize
}

FREED = ["Ctrl+=", "Ctrl+-", "Ctrl+Shift+Z", "Ctrl+R", "Shift+O",
         "Ctrl+H", "Ctrl+M"]

MACOS_RESERVED = ["Ctrl+H", "Ctrl+M", "Ctrl+Q"]


def _bound():
    return {n: v for n, v in default_settings.items()
            if n.endswith("_act") and isinstance(v, str) and v}


def test_the_sweep_landed():
    for act, key in SWEEP.items():
        assert default_settings[act] == key, act


def test_freed_chords_stay_silent():
    """An old reflex lands on nothing, never on a new surprise."""
    taken = set(_bound().values())
    for chord in FREED:
        if chord == "Ctrl+B":
            continue  # alive as the paste-attributes alias, below
        assert chord not in taken, chord


def test_no_default_sits_on_a_macos_reserved_chord():
    """Ctrl maps to Cmd on macOS, and these Cmd chords belong to the OS.

    quit_act on Ctrl+Q is the one legitimate resident: Cmd+Q quitting the
    app IS the OS meaning, so the binding and the reflex agree."""
    taken = {v: n for n, v in _bound().items()}
    for chord in MACOS_RESERVED:
        owner = taken.get(chord)
        if chord == "Ctrl+Q" and owner == "quit_act":
            continue
        assert owner is None, f"{chord} is bound to {owner}"


def test_paste_attributes_answers_to_both_chords(main_window):
    seqs = [s.toString() for s in main_window.pasteattributes_act.shortcuts()]
    assert seqs == ["Ctrl+Shift+V", "Ctrl+B"]


def test_the_alias_yields_when_a_user_claims_the_chord(main_window):
    """Remapping anything onto Ctrl+B beats the legacy alias."""
    main_window.resetShortcuts({"togglecuration_act": "Ctrl+B"})
    seqs = [s.toString() for s in main_window.pasteattributes_act.shortcuts()]
    assert seqs == ["Ctrl+Shift+V"]
    curation = [s.toString() for s in main_window.togglecuration_act.shortcuts()]
    assert "Ctrl+B" in curation


def test_the_alias_registry_is_exactly_the_one_entry():
    assert LEGACY_SHORTCUT_ALIASES == {"pasteattributes_act": "Ctrl+B"}
