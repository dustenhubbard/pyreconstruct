"""Palette-position persistence tests.

The five moveable palette groups (mode, trace, inc, bc, sb) store their position
as a fraction 0..1 of the field bounds. Those positions are a global UI choice
and must survive a restart. These tests cover the load/save/clear helpers
hermetically -- no MousePalette widget is built and no real user settings are
touched. The fake mimics QSettings' INI backend (every value serialises to a
string), so the float coercion the helpers rely on is genuinely exercised.
"""
import pytest

from PyReconstruct.modules.gui.palette.mouse_palette import (
    PALETTE_POS_GROUPS,
    _palette_pos_key,
    load_palette_positions,
    save_palette_positions,
    clear_palette_positions,
)

ALL_KEYS = tuple(f"{g}_{a}" for g in PALETTE_POS_GROUPS for a in ("x", "y"))


class FakeSettings:
    """A QSettings-shaped store that serialises values to strings like the INI backend."""

    def __init__(self, data=None):
        self._d = dict(data or {})

    def setValue(self, key, val):
        self._d[key] = str(val)

    def value(self, key, default=None, type=None):
        return self._d.get(key, default)

    def remove(self, key):
        self._d.pop(key, None)


def test_default_is_empty_so_caller_keeps_code_defaults():
    # nothing stored -> empty dict, so MousePalette keeps its in-code defaults
    assert load_palette_positions(FakeSettings()) == {}


def test_save_then_load_roundtrips_every_group():
    s = FakeSettings()
    original = {k: round(0.05 * i, 3) for i, k in enumerate(ALL_KEYS, start=1)}
    save_palette_positions(s, original)
    # a fresh load on the same store simulates a relaunch
    assert load_palette_positions(s) == original


def test_loaded_values_are_floats_even_from_a_string_store():
    s = FakeSettings()
    save_palette_positions(s, {"bc_x": 0.25, "bc_y": 0.8})
    reloaded = load_palette_positions(s)
    assert reloaded == {"bc_x": 0.25, "bc_y": 0.8}
    assert all(isinstance(v, float) for v in reloaded.values())


def test_partial_positions_only_return_present_keys():
    s = FakeSettings()
    save_palette_positions(s, {"sb_x": 0.5, "sb_y": 0.5})
    # only the scale bar was dragged: other groups stay absent (defaults kept)
    assert load_palette_positions(s) == {"sb_x": 0.5, "sb_y": 0.5}


def test_save_coerces_string_and_int_values_to_float():
    s = FakeSettings()
    save_palette_positions(s, {"mode_x": "0.33", "mode_y": 1})
    loaded = load_palette_positions(s)
    assert loaded["mode_x"] == pytest.approx(0.33)
    assert loaded["mode_y"] == 1.0
    assert all(isinstance(v, float) for v in loaded.values())


def test_unparseable_stored_value_is_skipped_not_fatal():
    s = FakeSettings({"palette/bc_x": "", "palette/bc_y": "0.4"})
    loaded = load_palette_positions(s)
    assert "bc_x" not in loaded          # corrupt value ignored
    assert loaded["bc_y"] == 0.4         # the readable one still loads


def test_clear_forgets_saved_positions_so_reset_is_permanent():
    s = FakeSettings()
    save_palette_positions(s, {k: 0.5 for k in ALL_KEYS})
    assert load_palette_positions(s)     # non-empty before clearing
    clear_palette_positions(s)
    assert load_palette_positions(s) == {}


def test_keys_are_namespaced_under_palette():
    for g in PALETTE_POS_GROUPS:
        for a in ("x", "y"):
            assert _palette_pos_key(g, a) == f"palette/{g}_{a}"


def test_groups_cover_all_five_moveable_palettes():
    assert set(PALETTE_POS_GROUPS) == {"mode", "trace", "inc", "bc", "sb"}


def test_non_finite_stored_values_are_skipped():
    # nan/inf parse fine via float() but would break placement on the next resize,
    # so a corrupt store falls back to the code default like any unreadable value
    s = FakeSettings({
        "palette/mode_x": "nan", "palette/mode_y": "inf",
        "palette/bc_x": "-inf", "palette/bc_y": "0.4",
    })
    loaded = load_palette_positions(s)
    assert "mode_x" not in loaded and "mode_y" not in loaded
    assert "bc_x" not in loaded
    assert loaded["bc_y"] == 0.4          # the finite, readable one still loads


# ---- wiring: the load/save/reset hooks on MousePalette ----------------------
# These lock the call-site wiring (not just the pure helpers) without building a
# full MousePalette, which would need a live mainwindow + dozens of widgets. The
# methods only touch the module helpers + plain attributes, so a duck-typed self
# is sufficient.
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


def test_drag_end_persists_once_but_a_plain_click_does_not(qapp):
    """MoveableButton.mouseReleaseEvent saves exactly once per real drag and not
    on a plain click -- the central guarantee of the feature."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PyReconstruct.modules.gui.palette.buttons import MoveableButton

    class FakeManager:
        def __init__(self):
            self.is_dragging = False
            self.saves = 0

        def savePositionState(self):
            self.saves += 1

    mgr = FakeManager()
    btn = MoveableButton(None, mgr, "bc")

    def release():
        # non-deprecated overload: explicit local + global position
        btn.mouseReleaseEvent(QMouseEvent(
            QEvent.MouseButtonRelease, QPointF(0, 0), QPointF(0, 0),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        ))

    try:
        # a real drag (is_dragging True at release) -> persist once, flag cleared
        mgr.is_dragging = True
        release()
        assert mgr.saves == 1
        assert mgr.is_dragging is False

        # a plain click that never moved the group -> no persist
        release()
        assert mgr.saves == 1
        assert mgr.is_dragging is False
    finally:
        btn.deleteLater()


def test_reset_pos_restores_every_default_and_clears_saved(monkeypatch):
    import types
    from PyReconstruct.modules.gui.palette import mouse_palette as M

    cleared = []
    monkeypatch.setattr(M, "clear_palette_positions", lambda settings: cleared.append(True))

    obj = types.SimpleNamespace(
        mode_x=0.1, mode_y=0.1, trace_x=0.1, trace_y=0.1, inc_x=0.1, inc_y=0.1,
        bc_x=0.1, bc_y=0.1, sb_x=0.1, sb_y=0.1, resize=lambda: None,
    )
    M.MousePalette.resetPos(obj)

    assert (obj.mode_x, obj.mode_y) == (0.99, 0.01)
    assert (obj.trace_x, obj.trace_y) == (0.51, 0.99)
    assert (obj.inc_x, obj.inc_y) == (0.99, 0.99)
    assert (obj.bc_x, obj.bc_y) == (0.99, 0.8)
    assert (obj.sb_x, obj.sb_y) == (0.01, 0.99)   # scale bar reset too (deliberate)
    assert cleared == [True]                       # delegates to clear_palette_positions


def test_load_position_state_overrides_defaults_with_saved(monkeypatch):
    import types
    from PyReconstruct.modules.gui.palette import mouse_palette as M

    monkeypatch.setattr(M, "load_palette_positions",
                        lambda settings: {"bc_x": 0.3, "bc_y": 0.7})
    obj = types.SimpleNamespace(bc_x=0.99, bc_y=0.8, mode_x=0.99)
    M.MousePalette.loadPositionState(obj)
    assert (obj.bc_x, obj.bc_y) == (0.3, 0.7)   # saved values applied
    assert obj.mode_x == 0.99                    # untouched groups keep their default
