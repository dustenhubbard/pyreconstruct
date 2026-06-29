"""Palette-visibility persistence tests.

The four palette show/hide preferences (trace palette, section-increment
buttons, brightness/contrast sliders, scale bar) are a global UI choice and must
survive a restart. These tests cover the load/save helpers hermetically -- no
MousePalette widget is built and no real user settings are touched. The fake
mimics QSettings' INI behaviour (bools are stored as strings), so the `type=bool`
coercion the helpers rely on is genuinely exercised.
"""
from PyReconstruct.modules.gui.palette.mouse_palette import (
    PALETTE_VIS_KEYS,
    load_palette_visibility,
    save_palette_visibility,
)

ALL_FLAGS = ("palette_hidden", "inc_hidden", "bc_hidden", "sb_hidden")


class FakeSettings:
    """A QSettings-shaped store that serialises like the INI backend."""

    def __init__(self, data=None):
        self._d = dict(data or {})

    def setValue(self, key, val):
        # QSettings' INI backend stores bools as the strings "true"/"false"
        self._d[key] = "true" if (isinstance(val, bool) and val) else \
                       "false" if isinstance(val, bool) else str(val)

    def value(self, key, default=None, type=None):
        if key not in self._d:
            return default
        raw = self._d[key]
        if type is bool:
            return raw == "true" or raw is True
        return raw


def test_default_is_all_shown():
    state = load_palette_visibility(FakeSettings())
    assert set(state) == set(ALL_FLAGS)
    assert all(v is False for v in state.values())


def test_save_then_load_roundtrips_each_flag():
    s = FakeSettings()
    original = {"palette_hidden": False, "inc_hidden": True,
                "bc_hidden": True, "sb_hidden": False}
    save_palette_visibility(s, original)
    # a fresh load on the same store simulates a relaunch
    assert load_palette_visibility(s) == original


def test_stored_bools_coerce_back_to_real_bools():
    # the whole point of type=bool: a bare "false" string is truthy in Python,
    # so a missing coercion would silently read every flag as hidden.
    s = FakeSettings()
    save_palette_visibility(s, {k: True for k in ALL_FLAGS})
    reloaded = load_palette_visibility(s)
    assert reloaded == {k: True for k in ALL_FLAGS}
    assert all(isinstance(v, bool) for v in reloaded.values())


def test_a_disabled_palette_stays_disabled_after_reload():
    s = FakeSettings()
    # user turns off the brightness/contrast sliders + increment buttons
    save_palette_visibility(s, {"palette_hidden": False, "inc_hidden": True,
                                "bc_hidden": True, "sb_hidden": False})
    reloaded = load_palette_visibility(s)
    assert reloaded["bc_hidden"] is True
    assert reloaded["inc_hidden"] is True
    assert reloaded["palette_hidden"] is False
    assert reloaded["sb_hidden"] is False


def test_keys_are_namespaced_and_cover_every_flag():
    assert set(PALETTE_VIS_KEYS) == set(ALL_FLAGS)
    assert all(key.startswith("palette/") for key in PALETTE_VIS_KEYS.values())
