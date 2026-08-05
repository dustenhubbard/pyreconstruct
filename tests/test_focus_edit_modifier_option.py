"""The focus-mode edit click is Ctrl by default and configurable.

Reported by a proofreader working in focus mode:

    While in x editing mode, we're repeatedly switching between shift-click and
    control-M. I'm thinking it would be easier if it was control-click. So your
    finger can just remain on control -- and you are just doing control-click or
    control-M. Control-click apparently does nothing at all in x mode right now.

Both halves of that were true of the code. ``focus_edit_p`` was literally
``event.modifiers() & Qt.ShiftModifier`` with no setting behind it, and Ctrl was
bound to nothing on any click anywhere in the field -- its only field binding is
Ctrl+wheel for zoom (``main_window.wheelEvent``). The other half of the pass is
``mergetraces_act``, which defaults to Ctrl+M.

So the default moves to Ctrl and the binding becomes the ``focus_edit_modifier``
setting: ``"ctrl"``, ``"shift"``, or ``"both"``, on the Mouse Tools tab of
``Series > Options``. Shift stays available because this click renames traces
between objects, and anyone mid-series with the old habit should not discover the
change by having a keystroke silently stop working.

One platform note that the option's labels have to carry: Qt swaps Ctrl and Meta
on macOS (nothing here sets ``AA_MacDontSwapCtrlAndMeta``), so
``Qt.ControlModifier`` is Command there. That is the correct reading of the
report anyway -- Command is also what ``Ctrl+M`` renders as on macOS, so "the
same key as merge" holds on both platforms -- and it is the only reading a click
handler can act on, because macOS turns a physical Control+click into a
secondary click that raises the field context menu before ``pointerRelease``
ever runs.

Covered here: the predicate for every setting value including an unrecognized
one, the shipped default, the real ``pointerRelease`` end to end for each
setting, and the options-dialog row in both directions plus under Reset
Defaults.
"""
import os
import shutil
import types

import pytest
from PySide6.QtCore import Qt

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes.default_settings import (
    default_settings, default_series_settings,
)
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.main.field_widget_5_mouse import FieldWidgetMouse
from PyReconstruct.modules.gui.main.focus_mode import focus_edit_p

# The stub field, the fixture's object names and the section number are the ones
# the #99 regression test already established for this exact code path.
from test_focus_split_undo_duplicate import (
    _Field, _one_trace, FOCUS_OBJ, SNUM, VICTIM_OBJ,
)

NONE, CTRL, SHIFT, BOTH_HELD = (
    Qt.NoModifier,
    Qt.ControlModifier,
    Qt.ShiftModifier,
    Qt.ControlModifier | Qt.ShiftModifier,
)


def _event(modifiers):
    """The one accessor ``focus_edit_p`` reads off a mouse event."""
    return types.SimpleNamespace(modifiers=lambda: modifiers)


# ---------------------------------------------------------------------------
# the predicate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "setting,held,expected",
    [
        # the new default
        ("ctrl", CTRL, True),
        ("ctrl", SHIFT, False),
        ("ctrl", NONE, False),
        ("ctrl", BOTH_HELD, True),      # extra modifiers do not disqualify
        # the pre-1.21.0-beta-8 binding, kept for existing habits
        ("shift", SHIFT, True),
        ("shift", CTRL, False),
        ("shift", NONE, False),
        ("shift", BOTH_HELD, True),
        # either
        ("both", CTRL, True),
        ("both", SHIFT, True),
        ("both", BOTH_HELD, True),
        ("both", NONE, False),
    ],
)
def test_focus_edit_p_honors_the_setting(setting, held, expected):
    assert focus_edit_p(_event(held), setting) is expected


@pytest.mark.parametrize("bad", ["meta", "alt", "", "ctrl+shift", None, 0])
def test_an_unrecognized_setting_falls_back_to_the_default(bad):
    """A stored string can be hand-edited or written by another build.

    Falling back to the shipped default is the conservative outcome: editing on
    *any* modifier would make this rename-between-objects click fire on clicks
    the user did not mean as edits, and refusing every modifier would strand
    focus mode with no way to edit at all.
    """
    assert focus_edit_p(_event(CTRL), bad) is True
    assert focus_edit_p(_event(SHIFT), bad) is False
    assert focus_edit_p(_event(NONE), bad) is False


def test_the_predicate_defaults_to_ctrl_with_no_setting_passed():
    """Callers that do not thread the option through still get the default.

    Guards the signature: `focus_edit_p(event)` was the only call shape before
    this option existed, and it must not silently mean "no modifier accepted".
    """
    assert focus_edit_p(_event(CTRL)) is True
    assert focus_edit_p(_event(SHIFT)) is False


# ---------------------------------------------------------------------------
# the shipped default
# ---------------------------------------------------------------------------

def test_the_shipped_default_is_ctrl():
    assert default_settings["focus_edit_modifier"] == "ctrl"


def test_the_option_is_a_user_preference_not_a_series_setting():
    """A modifier preference belongs to the hand on the keyboard.

    `default_settings` is the per-user store and `default_series_settings` the
    per-series one; landing in the wrong dict would make the binding change when
    the proofreader opened a different series.
    """
    assert "focus_edit_modifier" not in default_series_settings
    assert "focus_edit_modifier" in Series.qsettings_defaults
    assert "focus_edit_modifier" not in Series.qsettings_series_defaults


# ---------------------------------------------------------------------------
# end to end through the real pointerRelease
# ---------------------------------------------------------------------------

@pytest.fixture
def field(real_series):
    """The #99 stub field, focused on FOCUS_OBJ, over an isolated settings store."""
    series = real_series
    series.setSettingsStore(DictSettingsStore())
    series.current_section = SNUM
    section = series.loadSection(SNUM)

    states = SeriesStates(series)
    states[section]  # baseline state for this section

    f = _Field(series, section, states, FOCUS_OBJ)
    section.selected_traces = [
        t for t in section.tracesAsList() if t.name == FOCUS_OBJ
    ]
    return f


def _incorporate_click(field, modifiers):
    """Click a VICTIM_OBJ trace while focused on FOCUS_OBJ.

    If the modifier is accepted, `pointerRelease` takes the "incorporate into
    obj" branch and renames the trace into the focused object. Returns True if
    the edit happened.
    """
    field.selected_trace = _one_trace(field.section, VICTIM_OBJ)
    field.selected_type = "trace"
    FieldWidgetMouse.pointerRelease(field, _event(modifiers))
    return VICTIM_OBJ not in {
        name for name, contour in field.section.contours.items()
        if len(contour.getTraces())
    }


@pytest.mark.parametrize(
    "setting,held,expected",
    [
        ("ctrl", CTRL, True),
        ("ctrl", SHIFT, False),
        ("shift", SHIFT, True),
        ("shift", CTRL, False),
        ("both", CTRL, True),
        ("both", SHIFT, True),
        ("both", NONE, False),
    ],
)
def test_pointer_release_edits_only_under_the_configured_modifier(
    field, setting, held, expected
):
    field.series.setOption("focus_edit_modifier", setting)

    assert _incorporate_click(field, held) is expected


def test_the_default_series_edits_on_ctrl_without_any_option_written(field):
    """No stored value: the field must still read Ctrl as the edit click.

    This is the reporter's case -- a fresh install, nothing configured.
    """
    assert field.series.getOption("focus_edit_modifier") == "ctrl"
    assert _incorporate_click(field, CTRL) is True


# ---------------------------------------------------------------------------
# the options-dialog row
# ---------------------------------------------------------------------------

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct",
    "assets", "checker", "files", "shapes1.jser",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


@pytest.fixture
def dialog_series(tmp_path):
    """A real series over an in-memory settings store, for the dialog."""
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    series.setSettingsStore(DictSettingsStore())
    yield series
    series.close()


def _selected_modifier(dlg):
    """Which of the three radio buttons the focus-mode widget is showing."""
    w = dlg.all_widgets["focus_mode"]
    assert w.accept(close=False)
    # The three text rows and the spacer produce no response, so the radio group
    # is response 0 -- the same indexing the widget's own setOption relies on.
    radios = w.responses[0]
    labels = [label for label, _checked in radios]
    assert labels == ["Ctrl-click", "Shift-click", "Either one"], labels
    return next(label for label, checked in radios if checked)


def test_the_dialog_row_shows_the_stored_value(qapp, dialog_series):
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

    dialog_series.setOption("focus_edit_modifier", "shift")
    dlg = AllOptionsDialog(None, dialog_series)

    assert _selected_modifier(dlg) == "Shift-click"


@pytest.mark.parametrize(
    "picked,expected", [(0, "ctrl"), (1, "shift"), (2, "both")]
)
def test_accepting_the_dialog_writes_the_picked_value(
    qapp, dialog_series, picked, expected
):
    """Drive the widget's own setOption with a response naming one button.

    Exercises the branch order in `all_options`, which is the half of this that
    a wrong `elif` would silently invert.
    """
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

    dialog_series.setOption("focus_edit_modifier", "shift")
    dlg = AllOptionsDialog(None, dialog_series)
    w = dlg.all_widgets["focus_mode"]

    radios = [
        ["Ctrl-click", False], ["Shift-click", False], ["Either one", False],
    ]
    radios[picked][1] = True
    w.setOption([[tuple(r) for r in radios]])

    assert dialog_series.getOption("focus_edit_modifier") == expected


def test_reset_defaults_returns_the_row_to_ctrl(qapp, dialog_series):
    """`createWidgets(use_defaults=True)` has to reach this getOption call.

    Six options were found not threading `use_defaults` (see
    `test_options_reset_defaults_non_sliders.py`); a seventh is not wanted.
    """
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

    dialog_series.setOption("focus_edit_modifier", "shift")
    dlg = AllOptionsDialog(None, dialog_series)
    assert _selected_modifier(dlg) == "Shift-click"

    dlg.resetDefaults()

    assert _selected_modifier(dlg) == "Ctrl-click"
