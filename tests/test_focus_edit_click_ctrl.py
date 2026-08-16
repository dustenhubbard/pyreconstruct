"""Focus mode's edit click defaults to Ctrl, and is remappable.

Reported by a proofreader working in focus mode:

    While in x editing mode, we're repeatedly switching between shift-click and
    control-M. I'm thinking it would be easier if it was control-click. So your
    finger can just remain on control -- and you are just doing control-click or
    control-M. Control-click apparently does nothing at all in x mode right now.

Both halves of that were true. ``focus_edit_p`` was
``event.modifiers() & Qt.ShiftModifier``, and Ctrl was bound to nothing on any
click anywhere in the field: the only Ctrl-plus-mouse binding there is Ctrl+wheel
for zoom, in ``MainWindow.wheelEvent``. The other half of the pass is
``mergetraces_act``, which defaults to ``Ctrl+M``, so Ctrl was busy on the
keyboard and idle on the mouse.

**Where the option is, which is the part worth reading.** A three-way
ctrl/shift/both radio group on the Mouse Tools tab was built, reviewed and then
cut before shipping, at the maintainer's word: three presets are not a remapping,
and a remapping is what was wanted. 1.21.0 therefore changed the binding and
nothing else, and Shift-click stopped working. The real thing landed afterwards:
a picker in the *shortcuts* dialog that accepts whatever combination the user
holds, covered by ``test_focus_edit_modifier_remappable.py``. Ctrl is still the
default, so everything below is the out-of-the-box behavior.

The tests below stop the *cut* shape growing back while that lives elsewhere. A
setting that exists in ``default_settings`` but is read by nothing, or a dialog
widget that is constructed but never placed in a tab, are both silent states: the
app runs, the suite passes, and nobody can reach the control. Neither is caught by
testing ``focus_edit_p`` alone. The Mouse Tools assertion in particular is kept
verbatim: the remapping deliberately did not go back there.

On macOS: Qt swaps Ctrl and Meta, so ``Qt.ControlModifier`` is Command there and
Ctrl everywhere else. That is what makes the pairing hold on both platforms, since
``Ctrl+M`` also renders as ``Cmd+M``. A physical Control+click on macOS is an
operating-system secondary click that arrives as a right-button press and raises
the field context menu in ``FieldWidget.mousePressEvent``, well before
``pointerRelease`` runs, so it can never reach this predicate.
"""
import types

import pytest
from PySide6.QtCore import Qt

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.datatypes.default_settings import (
    default_settings, default_series_settings,
)
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


def _default_series():
    """A series stub answering with the shipped default and nothing else."""
    return types.SimpleNamespace(
        getOption=lambda name: default_settings[name],
    )


# ---------------------------------------------------------------------------
# the predicate, on a fresh install
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "held,expected",
    [
        (CTRL, True),
        (SHIFT, False),      # the pre-1.21.0 binding, no longer the default
        (NONE, False),
        (BOTH_HELD, True),   # an extra modifier held does not disqualify
    ],
)
def test_only_ctrl_is_the_edit_click(held, expected):
    assert focus_edit_p(_event(held), _default_series()) is expected


def test_the_predicate_reads_the_option_rather_than_a_passed_preset():
    """Guards the signature against the *cut* shape growing back.

    The withdrawn version was `focus_edit_p(event, modifier)`, taking one of
    three preset strings. The shipped version takes the series and reads the
    binding out of it, so a caller that hands over a bare preset string gets an
    error rather than a working second way to set this.

    The distinction is the whole point of the correction: a preset passed by the
    caller is not a remapping, and a stored binding the user chose is.
    """
    with pytest.raises((AttributeError, TypeError)):
        focus_edit_p(_event(CTRL), "shift")


# ---------------------------------------------------------------------------
# the setting is read, and stayed out of the Mouse Tools tab
# ---------------------------------------------------------------------------

def test_the_setting_is_per_user_and_not_per_series():
    """`default_settings` is the per-user store, `default_series_settings` the
    per-series one. This binding is a preference about a hand, not about a
    dataset, so it lives in exactly one of them.
    """
    assert default_settings["focus_edit_modifier"] == "ctrl"
    assert "focus_edit_modifier" not in default_series_settings


def test_the_options_dialog_has_no_focus_mode_widget(qapp, real_series):
    """The other silent half: a widget built by `createWidgets` and never placed.

    `placeWidgets` reads a separate `tab_structure`, so a widget can exist in
    `all_widgets` while appearing in no tab. Nothing in this dialog's ~30 rows
    asserts placement, so a leftover here would have been invisible.
    """
    from PyReconstruct.modules.gui.dialog.all_options import AllOptionsDialog

    dlg = AllOptionsDialog(None, real_series)

    assert "focus_mode" not in dlg.all_widgets


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(["test"])


# ---------------------------------------------------------------------------
# end to end through the real pointerRelease
# ---------------------------------------------------------------------------

@pytest.fixture
def field(real_series):
    """The #99 stub field, focused on FOCUS_OBJ.

    The settings store is redirected because `focus_edit_p` now reads an option,
    and `Series.getOption` writes the default back into the developer's real
    `QSettings` whenever a key is absent. Reading the binding would otherwise
    leave a key behind on the machine running the suite.
    """
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore

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


def test_ctrl_click_incorporates_the_clicked_trace(field):
    """The reporter's case, on a fresh install with nothing configured."""
    assert _incorporate_click(field, CTRL) is True


def test_shift_click_does_not_edit_out_of_the_box(field):
    """The pre-1.21.0 binding, still not what a fresh install does.

    This is the rewrite the previous version of this test asked for: Shift is
    reachable again, but only by configuration, and
    `test_remapping_to_shift_restores_the_old_habit` in
    `test_focus_edit_modifier_remappable.py` is where that is shown. Out of the
    box it is still Ctrl, so a user who never opens the dialog sees no change.
    """
    assert _incorporate_click(field, SHIFT) is False


def test_an_unmodified_click_does_not_edit(field):
    assert _incorporate_click(field, NONE) is False
