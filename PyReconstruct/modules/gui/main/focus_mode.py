"""Focus mode utilities."""

from PySide6.QtCore import Qt


def focus_edit_p(event) -> bool:
    """User requests editing in focus mode.

    Ctrl rather than Shift, changed 2026-08-05 on a proofreader's report: the
    other half of a proofreading pass is `mergetraces_act`, which defaults to
    `Ctrl+M`, so Shift here meant alternating two modifiers for two halves of one
    job. Ctrl-click did nothing at all in focus mode beforehand, and the only
    other Ctrl-plus-mouse binding in the field is Ctrl+wheel for zoom. (Ctrl is of
    course all over the keyboard shortcuts, `Ctrl+M` among them; it is the mouse
    that had nothing on it.)

    Qt swaps Ctrl and Meta on macOS, so `Qt.ControlModifier` is the Command key
    there and the Ctrl key everywhere else. That is what makes this pair hold on
    both platforms: `Ctrl+M` also renders as `Cmd+M` on macOS. A physical
    Control+click on macOS is an operating-system secondary click that arrives as
    a right-button press and raises the field menu in
    `FieldWidget.mousePressEvent`, well before `pointerRelease` runs, so it can
    never reach this check.

    Deliberately a fixed modifier and not a setting. A three-way Ctrl/Shift/both
    option was built and then cut, because three presets are not a remapping; the
    real thing, a picker that accepts any modifier combination the user holds,
    is scheduled for the next beta rather than for this release.
    """

    return bool(event.modifiers() & Qt.ControlModifier)


def focus_comparison(selected_trace, focused_obj) -> bool:
    """Compare selected trace and obj that is focused_on."""

    return selected_trace.name == focused_obj  # return true if same obj
