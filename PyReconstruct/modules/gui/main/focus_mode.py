"""Focus mode utilities."""

from PySide6.QtCore import Qt


#: What each value of the `focus_edit_modifier` setting accepts on the
#: focus-mode edit click. `"both"` is assembled in `focus_edit_p` rather than
#: stored here, so that a mask is never mistaken for a single named key.
#:
#: Qt swaps Ctrl and Meta on macOS, so `Qt.ControlModifier` is **Command**
#: there and **Ctrl** everywhere else. That is the point of the default: it is
#: the same key that carries `Ctrl+M` (merge traces) on whichever platform the
#: user is on, so a proofreading pass alternating edit-click and merge never
#: moves the hand between two modifiers. Reported by a proofreader who was
#: switching between Shift and Ctrl for exactly that pair.
#:
#: macOS's physical Control+click is an OS-level secondary click and reaches Qt
#: as a right-button press, which raises the field context menu well before
#: `pointerRelease` runs. It therefore can never be this binding on macOS, and
#: `Qt.ControlModifier` (Command) is the only reading of "control-click" there
#: that a click handler can act on at all.
FOCUS_EDIT_MODIFIERS = {
    "ctrl": Qt.ControlModifier,
    "shift": Qt.ShiftModifier,
}

#: Fallback for an unrecognized `focus_edit_modifier`, which is reachable: the
#: value is a stored string, and a settings file can be hand-edited or written
#: by an older build. Silently editing on an unknown value would be worse than
#: falling back to the shipped default, because this click renames traces
#: between objects.
FOCUS_EDIT_MODIFIER_DEFAULT = "ctrl"


def focus_edit_p(event, modifier: str = FOCUS_EDIT_MODIFIER_DEFAULT) -> bool:
    """User requests editing in focus mode.

        Params:
            event: the mouse event carrying the modifier state
            modifier (str): the `focus_edit_modifier` setting -- "ctrl",
                "shift", or "both" to accept either
    """
    if modifier == "both":
        accepted = Qt.ControlModifier | Qt.ShiftModifier
    else:
        accepted = FOCUS_EDIT_MODIFIERS.get(
            modifier, FOCUS_EDIT_MODIFIERS[FOCUS_EDIT_MODIFIER_DEFAULT]
        )

    return bool(event.modifiers() & accepted)


def focus_comparison(selected_trace, focused_obj) -> bool:
    """Compare selected trace and obj that is focused_on."""

    return selected_trace.name == focused_obj  # return true if same obj
