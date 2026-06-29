"""Headless tests for the floating tool palette (right-edge docked card).

Covers the logic that does not need a full main window: card structure, the
right-edge / left-handed docking + flip, the active-tool state, keycap hints,
and the theme tokens. Rendering itself is exercised by a grab() smoke test;
the visual review is the preview artifact.

Run: PYTHONPATH=<worktree> QT_QPA_PLATFORM=offscreen pytest -q tests/test_tool_palette.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from _palette_fixture import make_palette  # noqa: E402

from PyReconstruct.modules.gui.utils import theme  # noqa: E402
from PyReconstruct.modules.gui.palette.mouse_palette import PaletteCard  # noqa: E402

SM = PaletteCard.SHADOW_MARGIN  # transparent shadow padding around the body


MODE_TO_INT = {
    "Pointer": 0, "Pan/Zoom": 1, "Knife": 2, "Scissors": 3,
    "Closed Trace": 4, "Open Trace": 5, "Stamp": 6, "Grid": 7,
    "Flag": 8, "Host": 9, "Ztool": 10,
}
EXPECTED_KEYS = {
    "Pointer": "P", "Pan/Zoom": "Z", "Knife": "K", "Closed Trace": "C",
    "Open Trace": "O", "Stamp": "S", "Grid": "G", "Flag": "F", "Host": "Q",
}
NO_KEY = ("Scissors", "Ztool")


# ---------------------------------------------------------------- structure

def test_card_structure():
    _app, _mw, mp, _r = make_palette()
    assert len(mp.mode_buttons) == 11
    # four tool families -> three dividers
    assert len(mp.tool_card.dividers) == 3
    assert mp.tool_card.header is not None
    assert mp.tool_card.header.text() == "TOOLS"
    # all 11 buttons are tracked on the card for the active-halo paint
    assert len(mp.tool_card.tool_buttons) == 11


def test_card_width_matches_prototype():
    # prototype --pal-w is 52px: 38px tool + 7px padding each side (the widget
    # carries an extra transparent SHADOW_MARGIN on each side for the shadow)
    _app, _mw, mp, _r = make_palette()
    assert mp.tool_card.width() - 2 * SM == 52
    assert mp.tool_card.bodyRect().width() == 52
    for b, _m, _p in mp.mode_buttons.values():
        assert b.width() == 38 and b.height() == 38


def test_buttons_not_draggable():
    # docked mode buttons must not free-drag (the card edge-docks/flips instead)
    _app, _mw, mp, _r = make_palette()
    b = mp.mode_buttons["Pointer"][0]
    # ModeButton overrides mouseMoveEvent to a no-op
    assert b.__class__.mouseMoveEvent is not b.__class__.__mro__[1].mouseMoveEvent


# --------------------------------------------------------------- active tool

def test_pointer_active_by_default():
    _app, _mw, mp, _r = make_palette()
    assert mp.mode_buttons["Pointer"][0].isChecked()
    for name, (b, _m, _p) in mp.mode_buttons.items():
        if name != "Pointer":
            assert not b.isChecked(), name


def test_activate_switches_exclusive_and_sets_mode():
    _app, mw, mp, _r = make_palette()
    for name, expect_int in MODE_TO_INT.items():
        mp.activateModeButton(name)
        assert mp.mode_buttons[name][0].isChecked(), name
        # exactly one checked
        checked = [n for n, (b, _m, _p) in mp.mode_buttons.items() if b.isChecked()]
        assert checked == [name], checked
        assert mw.last_mouse_mode == expect_int, (name, mw.last_mouse_mode)
        assert mp.selected_mode == name


def test_active_styling_is_accent_resting_is_transparent():
    _app, _mw, mp, restore = make_palette(scheme="dark")
    try:
        mp.activateModeButton("Closed Trace")
        active_qss = mp.mode_buttons["Closed Trace"][0].styleSheet()
        resting_qss = mp.mode_buttons["Pointer"][0].styleSheet()
        assert theme.ACCENT in active_qss
        assert theme.ACCENT_TEXT in active_qss
        assert "transparent" in resting_qss
        assert ":hover" in resting_qss  # hover affordance present on resting
        assert theme.ACCENT not in resting_qss
    finally:
        if restore:
            restore()


def test_active_keycap_turns_white():
    _app, _mw, mp, _r = make_palette()
    mp.activateModeButton("Pointer")
    kc = mp.mode_buttons["Pointer"][0].keycap
    assert "255, 255, 255" in kc.styleSheet()


# ------------------------------------------------------------------ keycaps

def test_keycaps_match_live_shortcuts():
    _app, _mw, mp, _r = make_palette()
    for name, key in EXPECTED_KEYS.items():
        b = mp.mode_buttons[name][0]
        assert b.keycap is not None, name
        assert b.keycap.text() == key, name
        assert key in b.toolTip() and name in b.toolTip(), name


def test_modes_without_shortcut_have_no_keycap():
    _app, _mw, mp, _r = make_palette()
    for name in NO_KEY:
        b = mp.mode_buttons[name][0]
        assert b.keycap is None, name
        assert b.toolTip() == name


def test_keycap_follows_series_override():
    # a user-overridden shortcut must show on the keycap, not the default
    _app, _mw, mp, _r = make_palette()
    mp.series.setOption("usepointer_act", "A")
    # rebuild the card so it reflects the override
    mp.tool_card.close()
    mp.mode_buttons = {}
    mp.createPaletteCard()
    assert mp.mode_buttons["Pointer"][0].keycap.text() == "A"


# ------------------------------------------------------- docking / handedness

def test_docks_right_by_default():
    _app, mw, mp, _r = make_palette(left_handed=False)
    assert mp.mode_x == 0.99  # field corner-text painter reads this (>.5 == right)
    g = mp.tool_card.geometry()
    field_right = mw.field.x() + mw.field.width()
    # the visible body (widget minus shadow margin) sits at the right edge
    body_right = g.x() + g.width() - SM
    assert abs(body_right - (field_right - 14)) <= 1
    # vertically centered
    assert abs(g.y() - (mw.field.height() - g.height()) / 2) <= 2


def test_docks_left_when_left_handed():
    _app, mw, mp, _r = make_palette(left_handed=True)
    assert mp.mode_x == 0.01  # (<=.5 == left)
    g = mp.tool_card.geometry()
    body_left = g.x() + SM
    assert abs(body_left - (mw.field.x() + 14)) <= 1


def test_toggle_handedness_flips_persists_and_syncs_menu():
    _app, mw, mp, _r = make_palette(left_handed=False)
    right_x = mp.tool_card.geometry().x()

    mp.toggleHandedness()
    assert mp.series.getOption("left_handed") is True
    assert mp.mode_x == 0.01
    left_x = mp.tool_card.geometry().x()
    assert left_x < right_x
    assert mw.lefthanded_act.isChecked() is True

    mp.toggleHandedness()
    assert mp.series.getOption("left_handed") is False
    assert mp.mode_x == 0.99
    assert abs(mp.tool_card.geometry().x() - right_x) <= 1
    assert mw.lefthanded_act.isChecked() is False


def test_apply_handedness_without_menu_action_is_safe():
    _app, mw, mp, _r = make_palette()
    del mw.lefthanded_act  # guarded by getattr in applyHandedness
    mp.series.setOption("left_handed", True)
    mp.applyHandedness()  # must not raise
    assert mp.mode_x == 0.01


# -------------------------------------------------------------------- render

def test_card_grabs_to_pixmap():
    _app, _mw, mp, _r = make_palette()
    pm = mp.tool_card.grab()
    assert not pm.isNull()
    assert pm.width() == mp.tool_card.width()


# -------------------------------------------------------------------- tokens

def test_theme_tokens_distinct_per_scheme():
    dark = theme.tokens("dark")
    light = theme.tokens("light")
    for key in ("panel", "panel_2", "elev", "hair", "txt", "txt_dim", "txt_faint"):
        assert key in dark and key in light
        assert dark[key] != light[key], key
    # resting icon color stays consistent with icon_color()
    assert dark["txt_dim"] == theme.ICON_DARK
    assert light["txt_dim"] == theme.ICON_LIGHT


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
