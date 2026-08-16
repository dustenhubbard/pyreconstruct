"""Focus mode's edit-click modifier is remappable to whatever the user holds.

The binding shipped fixed at Ctrl in 1.21.0 after a three-way ctrl/shift/both
radio group was cut at the maintainer's word — *"i just wanted the shortcut
remappable"* — because three presets are not a remapping. This is the remapping.

**Why a bespoke widget rather than the one the dialog already has.** Both halves
of the constraint were measured against the pinned PySide6 6.5.2, and both are
asserted below rather than taken on trust, because the whole design rests on them:

1. ``QKeySequenceEdit`` cannot *capture* a modifier-only key press. It swallows
   the event and waits for a real key, so there is no gesture a user could make
   to put "Ctrl" in one.
2. The strings that look like bare modifiers are not modifiers.
   ``QKeySequence("Shift")`` is ``Qt.Key_Shift``, the physical key code, not
   ``Qt.ShiftModifier``; ``"Ctrl"`` alone does not parse at all. So the round trip
   that appears to work stores the wrong kind of value for a predicate reading
   ``event.modifiers()``.

**Placement is asserted, not just construction.** The cut attempt's second trap
was a widget built in ``createWidgets`` and missing from ``placeWidgets``'
``tab_structure``, reachable by nothing while the suite stayed green.
``ShortcutsDialog`` has no such split — it is one flat ``QGridLayout`` built in
``__init__`` — so the literal trap does not apply here, but the lesson does:
``test_the_picker_is_actually_in_the_dialog_grid`` walks the real layout and finds
the widget in it, rather than trusting that it was constructed.

**macOS.** ``meta`` is *excluded* rather than warned about. Qt swaps Ctrl and Meta
there, so ``Qt.MetaModifier`` is the physical Control key, and Qt's own Cocoa
plugin converts a Control-held left press into a right press before the
application sees it (``qnsview_mouse.mm``, gated on ``QT_MAC_DONT_OVERRIDE_CTRL_LMB``,
which this project does not set). The field context menu opens from
``mousePressEvent`` and the release handler that tests this binding never runs. A
binding that silently does nothing is worse than one the picker declines to make,
so the flag is dropped on capture and on read.
"""
import types

import pytest
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QKeySequenceEdit

from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.gui.main.field_widget_5_mouse import FieldWidgetMouse
from PyReconstruct.modules.gui.main.focus_mode import FOCUS_EDIT_OPTION, focus_edit_p
from PyReconstruct.modules.gui import modifiers as mod

from test_focus_split_undo_duplicate import (
    _Field, _one_trace, FOCUS_OBJ, SNUM, VICTIM_OBJ,
)

CTRL, SHIFT, ALT = Qt.ControlModifier, Qt.ShiftModifier, Qt.AltModifier


def _event(modifiers):
    return types.SimpleNamespace(modifiers=lambda: modifiers)


def _series(binding):
    """A series stub answering with one stored binding."""
    return types.SimpleNamespace(getOption=lambda name: binding)


# ---------------------------------------------------------------------------
# the premise: why QKeySequenceEdit could not be reused
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "key,mods",
    [
        (Qt.Key_Control, Qt.ControlModifier),
        (Qt.Key_Shift, Qt.ShiftModifier),
        (Qt.Key_Shift, Qt.ControlModifier | Qt.ShiftModifier),
    ],
)
def test_qkeysequenceedit_cannot_capture_a_modifier_only_press(qapp, key, mods):
    """The reason this module exists. If this ever starts failing, the bespoke
    widget below can be deleted in favour of the stock one."""
    w = QKeySequenceEdit()
    qapp.sendEvent(w, QKeyEvent(QEvent.KeyPress, key, mods))

    assert w.keySequence().toString() == ""


def test_qkeysequenceedit_does_capture_a_real_key(qapp):
    """The control for the test above: the widget is not simply inert."""
    w = QKeySequenceEdit()
    qapp.sendEvent(w, QKeyEvent(QEvent.KeyPress, Qt.Key_M, Qt.ControlModifier))

    assert w.keySequence().toString() == "Ctrl+M"


def test_bare_modifier_strings_parse_to_key_codes_not_modifiers(qapp):
    """`QKeySequence("Shift")` looks like it works and does not.

    It is the *key* Shift, not the Shift modifier, so storing a binding this way
    would hand `focus_edit_p` a value it cannot compare against
    `event.modifiers()`. And "Ctrl" does not survive at all.
    """
    assert QKeySequence("Shift")[0].toCombined() == Qt.Key_Shift.value
    assert QKeySequence("Shift")[0].toCombined() != Qt.ShiftModifier.value
    assert QKeySequence("Ctrl").toString() == ""


# ---------------------------------------------------------------------------
# the stored form
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "flags,expected",
    [
        (Qt.NoModifier, ""),
        (CTRL, "ctrl"),
        (SHIFT, "shift"),
        (ALT, "alt"),
        (CTRL | SHIFT, "ctrl+shift"),
        (SHIFT | CTRL, "ctrl+shift"),          # canonical order, not input order
        (CTRL | SHIFT | ALT, "ctrl+shift+alt"),
    ],
)
def test_modifier_flags_round_trip_through_the_stored_string(flags, expected):
    assert mod.modifiers_to_string(flags) == expected
    assert mod.string_to_modifiers(expected) == flags


def test_an_unparseable_binding_reads_as_unbound_rather_than_raising():
    """This parses a stored setting inside a mouse handler. A junk value should
    disable the click, not take the handler down."""
    assert mod.string_to_modifiers("nonsense") == Qt.NoModifier
    assert mod.string_to_modifiers(None) == Qt.NoModifier


# ---------------------------------------------------------------------------
# the picker captures what is held
# ---------------------------------------------------------------------------

def _hold(widget, *keys):
    """Press the given modifier keys in order, then release the last one.

    `event.modifiers()` on a real press carries the modifiers already down, which
    is what the second argument reproduces.
    """
    from PyReconstruct.modules.gui.modifiers import MODIFIER_KEYS

    down = Qt.NoModifier
    for key in keys:
        widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, down))
        down |= MODIFIER_KEYS[key]
    widget.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, keys[-1], down))
    return widget.modifierString()


@pytest.mark.parametrize(
    "keys,expected",
    [
        ((Qt.Key_Shift,), "shift"),
        ((Qt.Key_Alt,), "alt"),
        ((Qt.Key_Control, Qt.Key_Shift), "ctrl+shift"),
        ((Qt.Key_Shift, Qt.Key_Control), "ctrl+shift"),
        ((Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt), "ctrl+shift+alt"),
    ],
)
def test_the_picker_captures_whatever_combination_is_held(qapp, keys, expected):
    """The deliverable: an arbitrary combination, not one of a fixed set."""
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    w = ModifierEdit("ctrl")

    assert _hold(w, *keys) == expected


def test_the_picker_shows_what_it_captured(qapp):
    """Captured *and* displayed: a box that stores silently is not a picker."""
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    w = ModifierEdit("ctrl")
    _hold(w, Qt.Key_Control, Qt.Key_Shift)

    assert w.text() == mod.display_label("ctrl+shift")
    assert "Shift" in w.text()


def test_a_non_modifier_key_is_not_a_binding(qapp):
    """Typing `M` at the focused box must not blank or change the binding.

    Both halves of the keystroke, because the release is where a commit happens
    and a press-only check passes even when the release path is wrong.
    """
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    w = ModifierEdit("ctrl")
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_M, Qt.NoModifier))
    w.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_M, Qt.NoModifier))

    assert w.modifierString() == "ctrl"
    assert w.text() == mod.display_label("ctrl")


def test_a_letter_typed_after_a_modifier_does_not_extend_the_binding(qapp):
    """`Ctrl` then `M` is `ctrl`, not `ctrl` plus whatever `M` contributes."""
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    w = ModifierEdit("shift")
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Control, Qt.NoModifier))
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_M, Qt.ControlModifier))
    w.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_Control, Qt.ControlModifier))

    assert w.modifierString() == "ctrl"


# ---------------------------------------------------------------------------
# the documented "off" state is reachable from the picker
# ---------------------------------------------------------------------------
#
# `default_settings` documents "empty means the edit click is off",
# `focus_edit_p` honours it and `MODIFIER_ROWS` advertises it with a placeholder,
# but no gesture produced it: `keyPressEvent` only ORs flags in, `keyReleaseEvent`
# refuses to commit an empty accumulation, and the box is read-only so it cannot
# be edited to empty. The only route in was the dialog bug fixed above.


def test_the_clear_button_unbinds_the_row(qapp):
    """The affordance the key-sequence rows have, on the row that lacked it."""
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    w = ModifierEdit("ctrl")
    w.clear_action.trigger()

    assert w.modifierString() == ""
    assert w.text() == ""


@pytest.mark.parametrize("key", [Qt.Key_Backspace, Qt.Key_Delete])
def test_backspace_or_delete_unbinds_the_row(qapp, key):
    """The keyboard route to the same state.

    Needed rather than merely convenient: a `QLineEdit` side button is
    `Qt.NoFocus` (pinned below), so the clear button cannot be tabbed to, and
    this widget is otherwise driven entirely from the keyboard.
    """
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    w = ModifierEdit("ctrl+shift")
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))

    assert w.modifierString() == ""
    assert w.text() == ""


def test_unbinding_while_a_modifier_is_held_does_not_rebind_on_release(qapp):
    """Unbinding drops the accumulation too.

    Backspace is reachable with a hand already on Ctrl. If `_held` survived, the
    release that follows would commit `ctrl` straight back and the unbind would
    look like it silently failed.
    """
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    w = ModifierEdit("shift")
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Control, Qt.NoModifier))
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Backspace, Qt.ControlModifier))
    w.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_Control, Qt.ControlModifier))

    assert w.modifierString() == ""


def test_the_row_can_be_bound_again_after_being_unbound(qapp):
    """"Off" must be a state, not a trap: the picker still captures afterwards."""
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    w = ModifierEdit("ctrl")
    w.clear_action.trigger()

    assert _hold(w, Qt.Key_Shift) == "shift"
    assert w.clear_action.isVisible()


def test_the_clear_affordance_is_offered_only_when_there_is_a_binding(qapp):
    """Mirrors the key-sequence rows, whose clear button fades in with text."""
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    bound, unbound = ModifierEdit("ctrl"), ModifierEdit("")

    assert bound.clear_action.isVisible() is True
    assert unbound.clear_action.isVisible() is False


def test_setclearbuttonenabled_would_not_have_worked_on_a_read_only_row(qapp):
    """Why the button is built by hand. Measured on the pinned PySide6 6.5.2.

    The obvious fix is `setClearButtonEnabled(True)`, exactly as the `_act` rows
    use. On a read-only box Qt installs the clear action *disabled*
    (`clearAction->setEnabled(!isReadOnly())`) and disables an existing one when
    `setReadOnly` is called afterwards, so the button renders greyed and dead.
    If this ever starts failing, `ModifierEdit` can drop its hand-built action.
    """
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QLineEdit

    ro = QLineEdit()
    ro.setReadOnly(True)
    ro.setClearButtonEnabled(True)

    assert ro.findChild(QAction, "_q_qlineeditclearaction").isEnabled() is False

    # the control: the same call on an editable box gives a live clear action,
    # so the assertion above is about read-only rather than about the call
    rw = QLineEdit()
    rw.setClearButtonEnabled(True)

    assert rw.findChild(QAction, "_q_qlineeditclearaction").isEnabled() is True

    # and Qt disables it on the transition, so ordering the calls does not help
    rw.setReadOnly(True)

    assert rw.findChild(QAction, "_q_qlineeditclearaction").isEnabled() is False


def test_a_line_edit_side_button_cannot_be_reached_from_the_keyboard(qapp):
    """The measurement behind offering Backspace/Delete as well as the button."""
    from PySide6.QtWidgets import QToolButton
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    row = ModifierEdit("ctrl")   # kept alive: its children die with it
    button = row.findChildren(QToolButton)[0]

    assert button.focusPolicy() == Qt.NoFocus


def test_unbinding_in_the_dialog_turns_the_edit_click_off_end_to_end(
    main_window, local_series_settings, monkeypatch
):
    """The whole point, through the real dialog, `exec`, and `resetShortcuts`.

    The widget clears its own `_value`, so `exec`'s existing harvest carries the
    empty string out with no special case, `resolve` reads it as the deliberate
    unbinding it now genuinely is, and the click stops editing.
    """
    from PySide6.QtWidgets import QDialog
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog

    series = local_series_settings(main_window)
    series.setOption(FOCUS_EDIT_OPTION, "ctrl")

    assert focus_edit_p(_event(CTRL), series) is True   # on before the user acts

    monkeypatch.setattr(QDialog, "exec", lambda self: 1)
    dialog = ShortcutsDialog(main_window, series)
    try:
        dialog.modifier_widgets[FOCUS_EDIT_OPTION].clear_action.trigger()
        response, confirmed = dialog.exec()
    finally:
        dialog.deleteLater()

    assert confirmed
    assert response[FOCUS_EDIT_OPTION] == ""

    main_window.resetShortcuts(response)

    assert series.getOption(FOCUS_EDIT_OPTION) == ""
    assert focus_edit_p(_event(CTRL), series) is False
    assert focus_edit_p(_event(CTRL | SHIFT), series) is False
    assert focus_edit_p(_event(Qt.NoModifier), series) is False


def test_a_picker_unbind_stops_a_real_edit_click(field, qapp):
    """And the same through the real `pointerRelease`, not just the predicate.

    `_incorporate_click` consumes the victim trace, so it is called once: the
    bound control for it is the `("ctrl", CTRL, True)` row of
    `test_the_predicate_follows_the_stored_binding`. Leaving `unbind` writing
    anything but `""` leaves `"ctrl"` stored and the click still edits.
    """
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    field.series.setOption(FOCUS_EDIT_OPTION, "ctrl")

    row = ModifierEdit(field.series.getOption(FOCUS_EDIT_OPTION))
    row.clear_action.trigger()
    field.series.setOption(FOCUS_EDIT_OPTION, row.modifierString())

    assert field.series.getOption(FOCUS_EDIT_OPTION) == ""
    assert _incorporate_click(field, CTRL) is False


# ---------------------------------------------------------------------------
# macOS: meta is excluded, not merely discouraged
# ---------------------------------------------------------------------------

def test_meta_is_excluded_where_it_could_never_fire(qapp, monkeypatch):
    """On macOS, `meta` is the physical Control key and the click is converted to
    a right press before `pointerRelease` runs. Forced on here rather than
    skipped off-Darwin, so the exclusion is covered on every platform's CI."""
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    monkeypatch.setattr(mod, "META_IS_UNREACHABLE", True)

    assert mod.usable_modifiers() & Qt.MetaModifier == Qt.NoModifier
    assert mod.canonical("meta") == ""
    assert mod.canonical("ctrl+meta") == "ctrl"

    # holding physical Control on a Mac leaves the existing binding untouched
    w = ModifierEdit("ctrl")
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Meta, Qt.NoModifier))
    w.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_Meta, Qt.NoModifier))

    assert w.modifierString() == "ctrl"


def test_an_unreachable_binding_falls_back_rather_than_going_silently_dead(
    monkeypatch,
):
    """A `meta` binding stored elsewhere must not turn the feature off on a Mac.

    Not hypothetical: the machine this was written on already had
    ``focus_edit_modifier = "META"`` sitting in its real `QSettings` from an
    earlier build, inert only because the shipped predicate ignored the option
    entirely. Making the option live without this fallback would have silently
    killed the edit click there, which is precisely the silent-dead-binding
    failure that excluding Meta from the picker exists to prevent.
    """
    monkeypatch.setattr(mod, "META_IS_UNREACHABLE", True)

    assert mod.resolve("meta", "ctrl") == CTRL
    assert mod.resolve("META", "ctrl") == CTRL       # stored uppercase, as found
    assert focus_edit_p(_event(CTRL), _series("meta")) is True


def test_the_fallback_does_not_override_a_deliberate_unbinding(monkeypatch):
    """"Off" and "unreachable here" are different, and only one falls back."""
    monkeypatch.setattr(mod, "META_IS_UNREACHABLE", True)

    assert mod.resolve("", "ctrl") == Qt.NoModifier
    assert focus_edit_p(_event(CTRL), _series("")) is False


def test_a_reachable_binding_is_never_second_guessed(monkeypatch):
    """The fallback only fires when nothing of the binding survives."""
    monkeypatch.setattr(mod, "META_IS_UNREACHABLE", True)

    assert mod.resolve("shift", "ctrl") == SHIFT
    assert mod.resolve("ctrl+meta", "ctrl") == CTRL  # partial survival, no fallback


def test_meta_is_bindable_where_it_does_work(qapp, monkeypatch):
    """The other side of the same switch, so the exclusion is shown to be
    platform-conditional rather than a blanket refusal."""
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    monkeypatch.setattr(mod, "META_IS_UNREACHABLE", False)

    w = ModifierEdit("ctrl")

    assert _hold(w, Qt.Key_Meta) == "meta"


# ---------------------------------------------------------------------------
# reachability in the real dialog
# ---------------------------------------------------------------------------

def test_the_picker_is_actually_in_the_dialog_grid(main_window, local_series_settings):
    """Placement, not construction.

    The cut attempt's trap was a widget that existed and was in no tab. This
    dialog has no createWidgets/placeWidgets split to fall into, so the check is
    made directly against the layout: walk every item the real grid holds and
    find the picker among them. Reverting the `help_shortcuts` row while leaving
    the widget class in place fails this and nothing else.
    """
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog
    from PyReconstruct.modules.gui.dialog.shortcuts import ModifierEdit

    from PySide6.QtWidgets import QGridLayout

    series = local_series_settings(main_window)

    dialog = ShortcutsDialog(main_window, series)
    try:
        assert FOCUS_EDIT_OPTION in dialog.modifier_widgets
        picker = dialog.modifier_widgets[FOCUS_EDIT_OPTION]
        assert isinstance(picker, ModifierEdit)

        # the one grid every row was added to, inside the scroll area
        grid = dialog.findChild(QGridLayout)
        placed = [grid.itemAt(i).widget() for i in range(grid.count())]

        assert picker in placed, "picker is constructed but never placed"

        # and its description landed beside it, so the row reads as a row
        row, column, _, _ = grid.getItemPosition(grid.indexOf(picker))
        beside = grid.itemAtPosition(row, column + 1).widget()

        assert "focus mode" in beside.text()
    finally:
        dialog.deleteLater()


def test_the_picker_row_sits_with_the_focus_mode_toggle(main_window):
    """It belongs next to `focus_act`, which is the other half of the feature."""
    from PyReconstruct.modules.gui.dialog.shortcuts import help_shortcuts

    names = [
        tuple(i)[0] for i in help_shortcuts
        if i is not None and not isinstance(i, str)
    ]

    assert names.index(FOCUS_EDIT_OPTION) == names.index("focus_act") + 1


def test_the_dialog_returns_the_binding_for_storage(
    main_window, local_series_settings, monkeypatch
):
    """`exec` hands the caller a dict; a picker missing from it is a dead box.

    `QDialog.exec` is the modal part and is stubbed to "the user pressed OK", so
    what runs is `ShortcutsDialog.exec`'s own gathering of the widgets.
    """
    from PySide6.QtWidgets import QDialog
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog

    series = local_series_settings(main_window)
    monkeypatch.setattr(QDialog, "exec", lambda self: 1)

    dialog = ShortcutsDialog(main_window, series)
    try:
        _hold(dialog.modifier_widgets[FOCUS_EDIT_OPTION], Qt.Key_Shift)
        response, confirmed = dialog.exec()
    finally:
        dialog.deleteLater()

    assert confirmed
    assert response[FOCUS_EDIT_OPTION] == "shift"
    # the key-sequence rows still come back too, unchanged
    assert response["focus_act"] == series.getOption("focus_act")


def test_opening_the_dialog_and_pressing_ok_does_not_destroy_the_fallback(
    main_window, local_series_settings, monkeypatch
):
    """The fallback and the dialog, *composed*. Each works alone; the round trip
    through both is where the feature was lost.

    `resolve` protects the predicate from a binding that cannot fire here, but
    that protection was one-way and lived only in `focus_edit_p`. The dialog
    seeded its row from the raw stored value, and `canonical` *drops* an
    unreachable flag instead of falling back — so the row displayed empty while
    Ctrl-click still worked, and `exec` harvests every row whether or not the
    user touched it. One OK on an untouched row therefore wrote `""`, which
    `resolve` correctly reads as a deliberate unbinding, and the edit click was
    off permanently with no message.

    Not hypothetical: the machine this was written on holds
    ``focus_edit_modifier = "META"`` in its real `QSettings`, so this exact
    sequence — open the shortcuts dialog, press OK, touch nothing — would have
    killed its own edit click. `META_IS_UNREACHABLE` is forced on rather than
    skipped off-Darwin, so the composition is covered on every platform's CI.
    """
    from PySide6.QtWidgets import QDialog
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog

    monkeypatch.setattr(mod, "META_IS_UNREACHABLE", True)
    series = local_series_settings(main_window)
    series.setOption(FOCUS_EDIT_OPTION, "META")   # stored uppercase, as found

    # the binding is unreachable here, so the predicate falls back to the default
    assert focus_edit_p(_event(CTRL), series) is True

    monkeypatch.setattr(QDialog, "exec", lambda self: 1)
    dialog = ShortcutsDialog(main_window, series)
    try:
        row = dialog.modifier_widgets[FOCUS_EDIT_OPTION]

        # the row shows the binding the user is really getting, not an empty box
        assert row.modifierString() == "ctrl"
        assert row.text() == mod.display_label("ctrl")

        response, confirmed = dialog.exec()   # OK pressed, this row never touched
    finally:
        dialog.deleteLater()

    assert confirmed
    assert response[FOCUS_EDIT_OPTION] == "ctrl"

    main_window.resetShortcuts(response)

    # and the edit click still fires afterwards, which is the whole point
    assert series.getOption(FOCUS_EDIT_OPTION) == "ctrl"
    assert focus_edit_p(_event(CTRL), series) is True


def test_reset_defaults_does_not_destroy_the_fallback_either(
    main_window, local_series_settings, monkeypatch
):
    """The dialog's other route into the row, and it re-seeds from the same
    stored value. Reverting only the constructor leaves this one corrupting."""
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog

    monkeypatch.setattr(mod, "META_IS_UNREACHABLE", True)
    series = local_series_settings(main_window)
    series.setOption(FOCUS_EDIT_OPTION, "META")

    dialog = ShortcutsDialog(main_window, series)
    try:
        dialog.resetDefaults()

        assert dialog.modifier_widgets[FOCUS_EDIT_OPTION].modifierString() == "ctrl"
    finally:
        dialog.deleteLater()


def test_a_deliberate_unbinding_survives_the_same_round_trip(
    main_window, local_series_settings, monkeypatch
):
    """The control for the two tests above: seeding through `resolve` must not
    quietly re-bind a user who chose "off". Only *unreachable* falls back."""
    from PySide6.QtWidgets import QDialog
    from PyReconstruct.modules.gui.dialog import ShortcutsDialog

    monkeypatch.setattr(mod, "META_IS_UNREACHABLE", True)
    series = local_series_settings(main_window)
    series.setOption(FOCUS_EDIT_OPTION, "")

    monkeypatch.setattr(QDialog, "exec", lambda self: 1)
    dialog = ShortcutsDialog(main_window, series)
    try:
        assert dialog.modifier_widgets[FOCUS_EDIT_OPTION].modifierString() == ""
        response, _ = dialog.exec()
    finally:
        dialog.deleteLater()

    assert response[FOCUS_EDIT_OPTION] == ""
    assert focus_edit_p(_event(CTRL), series) is False


def test_the_window_stores_the_binding_without_treating_it_as_an_action(
    main_window, local_series_settings
):
    """`resetShortcuts` applies every other row to a QAction. This row has none,
    and must still be persisted rather than skipped or crashed on."""
    series = local_series_settings(main_window)

    main_window.resetShortcuts({FOCUS_EDIT_OPTION: "shift+alt"})

    assert series.getOption(FOCUS_EDIT_OPTION) == "shift+alt"


# ---------------------------------------------------------------------------
# the setting actually changes behavior
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "binding,held,expected",
    [
        ("ctrl", CTRL, True),
        ("ctrl", SHIFT, False),
        ("shift", SHIFT, True),           # the old habit, restored by choice
        ("shift", CTRL, False),
        ("alt", ALT, True),
        ("ctrl+shift", CTRL | SHIFT, True),
        ("ctrl+shift", CTRL, False),      # a combination needs all of it held
        ("ctrl", CTRL | ALT, True),       # a spare modifier does not disqualify
        ("", CTRL, False),                # unbound means off
        ("", Qt.NoModifier, False),       # and not "fires on every click"
    ],
)
def test_the_predicate_follows_the_stored_binding(binding, held, expected):
    assert focus_edit_p(_event(held), _series(binding)) is expected


@pytest.fixture
def field(real_series):
    """The #99 stub field, focused on FOCUS_OBJ, with settings redirected."""
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore

    series = real_series
    series.setSettingsStore(DictSettingsStore())
    series.current_section = SNUM
    section = series.loadSection(SNUM)

    states = SeriesStates(series)
    states[section]

    f = _Field(series, section, states, FOCUS_OBJ)
    section.selected_traces = [
        t for t in section.tracesAsList() if t.name == FOCUS_OBJ
    ]
    return f


def _incorporate_click(field, modifiers):
    """Click a VICTIM_OBJ trace while focused on FOCUS_OBJ; True if it edited."""
    field.selected_trace = _one_trace(field.section, VICTIM_OBJ)
    field.selected_type = "trace"
    FieldWidgetMouse.pointerRelease(field, _event(modifiers))
    return VICTIM_OBJ not in {
        name for name, contour in field.section.contours.items()
        if len(contour.getTraces())
    }


def test_remapping_to_shift_restores_the_old_habit(field):
    """The user-visible point of the whole change.

    1.21.0 stranded anyone with the Shift-click habit, with no way back. This is
    the way back, end to end through the real `pointerRelease`.
    """
    field.series.setOption(FOCUS_EDIT_OPTION, "shift")

    assert _incorporate_click(field, SHIFT) is True


def test_remapping_away_from_ctrl_actually_releases_ctrl(field):
    """The other half: a remap moves the binding rather than adding to it."""
    field.series.setOption(FOCUS_EDIT_OPTION, "shift")

    assert _incorporate_click(field, CTRL) is False


def test_a_combination_binding_works_end_to_end(field):
    """Ctrl+Shift is not one of the three presets that were cut, which is the
    difference between a remapping and a picker over an enum."""
    field.series.setOption(FOCUS_EDIT_OPTION, "ctrl+shift")

    assert _incorporate_click(field, CTRL | SHIFT) is True


def test_an_unbound_binding_turns_the_edit_click_off(field):
    field.series.setOption(FOCUS_EDIT_OPTION, "")

    assert _incorporate_click(field, CTRL) is False
