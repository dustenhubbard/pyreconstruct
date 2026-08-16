"""Focus mode utilities."""

from ..modifiers import resolve
from ...datatypes.default_settings import default_settings


#: The option holding the modifier combination that turns a focus-mode click
#: into an edit. Named here because this is the only thing that reads it.
FOCUS_EDIT_OPTION = "focus_edit_modifier"


def focus_edit_p(event, series) -> bool:
    """User requests editing in focus mode.

    The combination is remappable: it is stored in the `focus_edit_modifier`
    option and edited in the shortcuts dialog, which is why this takes the series
    rather than a modifier. It defaults to Ctrl, changed from Shift on 2026-08-05
    on a proofreader's report: the other half of a proofreading pass is
    `mergetraces_act`, which defaults to `Ctrl+M`, so Shift here meant
    alternating two modifiers for two halves of one job. Ctrl-click did nothing
    at all in focus mode beforehand, and the only other Ctrl-plus-mouse binding
    in the field is Ctrl+wheel for zoom. (Ctrl is of course all over the keyboard
    shortcuts, `Ctrl+M` among them; it is the mouse that had nothing on it.)

    Qt swaps Ctrl and Meta on macOS, so `Qt.ControlModifier` is the Command key
    there and the Ctrl key everywhere else. That is what makes the default pair
    hold on both platforms: `Ctrl+M` also renders as `Cmd+M` on macOS. A physical
    Control+click on macOS is a secondary click that arrives as a right-button
    press and raises the field menu in `FieldWidget.mousePressEvent`, well before
    `pointerRelease` runs, so it can never reach this check. That is also why
    `meta` cannot be bound at all on macOS; see `gui/modifiers.py`.

    **Held, not matched exactly.** An extra modifier the user happens to be
    holding does not disqualify the click, which is the behavior the fixed Ctrl
    binding had. A binding of `"ctrl+shift"` needs both held; a binding of
    `"ctrl"` fires whether or not Shift is also down.

    An empty binding is a real choice and means the edit click is off, so it
    returns False rather than firing on every unmodified click. A binding that is
    merely unreachable on *this* machine is not the same thing and falls back to
    the default instead of reading as off; `resolve` carries that distinction.
    """

    binding = resolve(
        series.getOption(FOCUS_EDIT_OPTION),
        default_settings[FOCUS_EDIT_OPTION],
    )

    if not binding:
        return False

    return (event.modifiers() & binding) == binding


def focus_comparison(selected_trace, focused_obj) -> bool:
    """Compare selected trace and obj that is focused_on."""

    return selected_trace.name == focused_obj  # return true if same obj
