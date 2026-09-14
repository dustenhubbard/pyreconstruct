"""Scissors gets a keyboard shortcut, the last tool without one.

Every other tool on the palette had a key (P, Z, K, C, O, S, G, F, Q) and a
row in the shortcuts dialog. Scissors had no action behind it at all, so it
could only be clicked and could not be given a key. His call (2026-09-14):
Shift+K for now, one step from Knife, the tool it sits beside; it can be
remapped by the user or given a better default later. S was Stamp, X was
Focus.

The generic sweeps in test_configurable_shortcuts_applied.py cover the
three-places-agree mechanism. This module pins the choice and proves the key
reaches the palette.
"""
import pytest

from PyReconstruct.modules.datatypes.default_settings import default_settings
from PyReconstruct.modules.gui.dialog.shortcuts import help_shortcuts
from PyReconstruct.modules.gui.main.field_widget_5_mouse import SCISSORS

pytestmark = pytest.mark.gui

CHOSEN = "Shift+K"


def test_scissors_has_a_configurable_default():
    assert default_settings["usescissors_act"] == CHOSEN


def test_scissors_has_a_shortcuts_dialog_row_beside_knife():
    names = [row[0] for row in help_shortcuts if isinstance(row, tuple)]
    assert names.index("usescissors_act") == names.index("useknife_act") + 1


def test_the_chosen_key_was_free_among_the_defaults():
    holders = [n for n, v in default_settings.items()
               if n.endswith("_act") and v == CHOSEN]
    assert holders == ["usescissors_act"]


def test_pressing_the_key_selects_the_scissors_tool(main_window, qapp):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    main_window.mouse_palette.activateModeButton("Pointer")
    qapp.processEvents()
    assert main_window.field.mouse_mode != SCISSORS

    QTest.keySequence(main_window, QKeySequence(CHOSEN))
    qapp.processEvents()

    assert main_window.field.mouse_mode == SCISSORS
    button = main_window.mouse_palette.mode_buttons["Scissors"][0]
    assert button.isChecked()
