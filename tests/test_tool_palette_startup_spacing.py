"""The tool palette column is spaced correctly the moment the window opens.

Users saw the tool buttons "squished" vertically at startup, then snapping
to the right spacing on the first drag (September 2026). The column's bounds
(getBounds) subtract one button height per button already made, and each
button used to be placed as it was created, so every button had a different
origin. The default position (top of the field) hid it: the offset scales
with the column's saved y fraction, so only a user who had dragged the
column down saw the pile-up. Buttons are now placed once all exist, the
same way resize() places them.
"""
import pytest

from PyReconstruct.modules.gui.palette import mouse_palette as mp

pytestmark = pytest.mark.gui


COLUMN = ["Pointer", "Pan/Zoom", "Knife", "Scissors", "Closed Trace",
          "Open Trace", "Stamp", "Grid", "Flag", "Host"]


def _mode_button_tops(palette):
    """Tops of the ten column buttons, in column order (the z-trace tool
    button lives elsewhere and is placed by its own code)."""
    return [palette.mode_buttons[name][0].y() for name in COLUMN]


@pytest.mark.parametrize("saved_y", [0.01, 0.5, 0.99])
def test_mode_buttons_are_evenly_spaced_right_after_construction(main_window, monkeypatch, saved_y):
    # a persisted column position, as loadPositionState restores it
    monkeypatch.setattr(mp, "load_palette_positions", lambda settings: {"mode_y": saved_y})
    main_window.mouse_palette.reset()          # close + __init__, the startup path
    palette = main_window.mouse_palette

    tops = _mode_button_tops(palette)
    gaps = [b - a for a, b in zip(tops, tops[1:])]
    # the column origin is a float, so setGeometry may round one gap by a pixel
    assert all(abs(g - (palette.mblen + 10)) <= 1 for g in gaps), gaps


def test_construction_matches_a_resize_pass(main_window, monkeypatch):
    monkeypatch.setattr(mp, "load_palette_positions", lambda settings: {"mode_y": 0.5})
    main_window.mouse_palette.reset()
    palette = main_window.mouse_palette
    at_start = _mode_button_tops(palette)
    palette.resize()                            # what a drag or window resize runs
    assert _mode_button_tops(palette) == at_start
