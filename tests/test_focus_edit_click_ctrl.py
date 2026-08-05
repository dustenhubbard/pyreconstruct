"""Focus mode's edit click is Ctrl, fixed, with no setting behind it.

Reported by a proofreader working in focus mode:

    While in x editing mode, we're repeatedly switching between shift-click and
    control-M. I'm thinking it would be easier if it was control-click. So your
    finger can just remain on control -- and you are just doing control-click or
    control-M. Control-click apparently does nothing at all in x mode right now.

Both halves of that were true. ``focus_edit_p`` was
``event.modifiers() & Qt.ShiftModifier``, and Ctrl was bound to nothing on any
click anywhere in the field: its only field binding is Ctrl+wheel for zoom, in
``MainWindow.wheelEvent``. The other half of the pass is ``mergetraces_act``,
which defaults to ``Ctrl+M``.

**Why there is no option here, which is the part worth reading.** A three-way
ctrl/shift/both radio group on the Mouse Tools tab was built, reviewed and then
cut before shipping, at the maintainer's word: three presets are not a remapping,
and a remapping is what was wanted. The real thing, a picker that accepts whatever
modifier combination the user holds, is scheduled for the next beta. So this
release changes the binding and nothing else, and **Shift-click no longer works**,
which is a deliberate and bounded consequence rather than an oversight.

Two tests below exist to stop the cut option growing back halfway. A setting that
exists in ``default_settings`` but is read by nothing, or a dialog widget that is
constructed but never placed in a tab, are both silent states: the app runs, the
suite passes, and nobody can reach the control. Neither is caught by testing
``focus_edit_p`` alone.

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


# ---------------------------------------------------------------------------
# the predicate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "held,expected",
    [
        (CTRL, True),
        (SHIFT, False),      # the pre-1.21.0 binding, deliberately retired
        (NONE, False),
        (BOTH_HELD, True),   # an extra modifier held does not disqualify
    ],
)
def test_only_ctrl_is_the_edit_click(held, expected):
    assert focus_edit_p(_event(held)) is expected


def test_the_predicate_takes_no_modifier_argument():
    """Guards the signature against the cut option growing back by accident.

    The withdrawn version was `focus_edit_p(event, modifier)`. If a caller starts
    passing a second argument again, that is the option returning, and it should
    return through a decision rather than through a stray call site.
    """
    with pytest.raises(TypeError):
        focus_edit_p(_event(CTRL), "shift")


# ---------------------------------------------------------------------------
# the cut option stays cut, in both directions
# ---------------------------------------------------------------------------

def test_no_focus_edit_modifier_setting_exists():
    """A setting nothing reads is unreachable, and reads as configurable anyway.

    `default_settings` is the per-user store and `default_series_settings` the
    per-series one. Checking both, because landing the key in either one would
    look to a reader like the option shipped.
    """
    assert "focus_edit_modifier" not in default_settings
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
    """The #99 stub field, focused on FOCUS_OBJ."""
    series = real_series
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


def test_shift_click_no_longer_edits(field):
    """The retired binding, pinned so its removal is deliberate and visible.

    If the next beta's remapping makes Shift reachable again by configuration,
    this test should be rewritten to say so rather than deleted quietly.
    """
    assert _incorporate_click(field, SHIFT) is False


def test_an_unmodified_click_does_not_edit(field):
    assert _incorporate_click(field, NONE) is False
