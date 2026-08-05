"""Keyboard modifier combinations, as a stored setting.

A modifier combination held during a *mouse* click is not a `QKeySequence`, and
`QKeySequenceEdit` cannot capture one. Both halves were measured on the PySide6
6.5.2 build this project pins, and both are the reason this module exists rather
than a reuse of the shortcuts dialog's existing widget:

1. `QKeySequenceEdit` ignores a modifier-only key press outright. Sending it a
   `QKeyEvent` for `Key_Control`, for `Key_Shift`, or for `Key_Shift` with
   `ControlModifier` already down each leaves `keySequence()` empty; only a press
   carrying a non-modifier key (`Ctrl+M`) is ever captured. There is no mode or
   flag that changes this, so the capture has to be written by hand.

2. The strings that *look* like bare modifiers do not survive as modifiers.
   `QKeySequence("Shift")` parses to `0x01000020`, which is `Qt.Key_Shift`, the
   physical key, not `Qt.ShiftModifier` (`0x02000000`). `"Alt"` and `"Meta"` are
   likewise key codes, `"Ctrl+Shift"` is `ControlModifier | Key_Shift`, and
   `"Ctrl"` alone does not parse at all: it becomes `Qt.Key_unknown` and renders
   back as the empty string. So even where a round trip appears to work it is
   storing the wrong kind of thing for a predicate that reads `event.modifiers()`.

The stored form is therefore a plain canonical string: modifier names, lowercase,
joined by `+`, in the fixed order below, e.g. `"ctrl"` or `"ctrl+shift"`. Empty
means no binding at all, which is a legitimate choice and reads as "off".

**Meta is not offered on macOS**, see `META_IS_UNREACHABLE`.
"""

import sys

from PySide6.QtCore import Qt


#: Canonical order. The stored string always lists modifiers in this order, so
#: that "shift+ctrl" and "ctrl+shift" cannot both be written for one binding.
MODIFIER_ORDER = (
    ("ctrl", Qt.ControlModifier),
    ("shift", Qt.ShiftModifier),
    ("alt", Qt.AltModifier),
    ("meta", Qt.MetaModifier),
)

#: The modifier flag each physical modifier key press carries, for capture. A
#: key press of `Key_Control` does not reliably report `ControlModifier` in its
#: own `modifiers()`, so the pressed key has to be mapped to its flag directly.
MODIFIER_KEYS = {
    Qt.Key_Control: Qt.ControlModifier,
    Qt.Key_Shift: Qt.ShiftModifier,
    Qt.Key_Alt: Qt.AltModifier,
    Qt.Key_Meta: Qt.MetaModifier,
}

ALL_MODIFIERS = Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier

#: True where a `meta` binding could never fire, so the picker must not offer it.
#:
#: Qt swaps Ctrl and Meta on macOS, so `Qt.MetaModifier` there is the *physical
#: Control key*. And Qt's own Cocoa plugin turns a Control-held left press into a
#: right press before the application ever sees it: `qnsview_mouse.mm`'s
#: `mouseDown:` reads
#:
#:     if (!m_dontOverrideCtrlLMB && (theEvent.modifierFlags & NSEventModifierFlagControl)) {
#:         m_buttons |= Qt::RightButton;
#:
#: gated on `QT_MAC_DONT_OVERRIDE_CTRL_LMB`, which this project does not set.
#: (That is a *different* switch from `AA_MacDontSwapCtrlAndMeta`, which governs
#: the Ctrl/Cmd swap and which this project also does not set.) So a macOS user
#: who bound `meta` would be holding physical Control, the click would arrive as
#: a right press, the field context menu would open from `mousePressEvent`, and
#: the release handler that tests this binding would never run. The binding would
#: be silently dead, which is worse than not being offered.
META_IS_UNREACHABLE = sys.platform == "darwin"


def usable_modifiers() -> int:
    """The modifier flags this platform will actually let a user bind."""
    if META_IS_UNREACHABLE:
        return ALL_MODIFIERS & ~Qt.MetaModifier
    return ALL_MODIFIERS


def modifiers_to_string(modifiers) -> str:
    """Canonical stored form of a set of modifier flags."""
    return "+".join(
        name for name, flag in MODIFIER_ORDER if modifiers & flag
    )


def string_to_modifiers(value) -> Qt.KeyboardModifier:
    """Parse the stored form back to modifier flags.

    Unknown or empty names are dropped rather than raising: this reads a stored
    setting, and a binding that cannot be parsed should read as "unbound" rather
    than take down the mouse handler it is called from.
    """
    flags = Qt.NoModifier
    by_name = dict(MODIFIER_ORDER)
    for part in str(value or "").lower().split("+"):
        flag = by_name.get(part.strip())
        if flag is not None:
            flags |= flag
    return flags


def canonical(value) -> str:
    """Round trip a stored string through the flags, dropping what is unusable.

    This is what makes `meta` unavailable on macOS rather than merely
    discouraged: a stored `"meta"` read on a Mac canonicalises to `""`.
    """
    return modifiers_to_string(string_to_modifiers(value) & usable_modifiers())


def resolve(value, fallback):
    """The flags to actually test at click time, given a stored binding.

    A binding that is merely unreachable *on this machine* falls back to the
    default rather than reading as "off". Only a deliberately empty binding means
    off.

    This matters because a stored value outlives the platform it was chosen on. A
    `"meta"` binding set on Linux, or left behind by an older build, is a real
    choice that simply cannot fire on a Mac; honouring it literally would turn the
    feature off with no message and nothing in the dialog to explain it, which is
    the exact silent-dead-binding failure the exclusion above exists to prevent.
    Excluding Meta from the *picker* only stops such a binding being created here.
    """
    stored = string_to_modifiers(value)
    reachable = stored & usable_modifiers()

    if reachable or not stored:
        return reachable

    return string_to_modifiers(fallback) & usable_modifiers()


def display_label(value) -> str:
    """How the combination is written for the user.

    On macOS `Qt.ControlModifier` is the Command key, so a binding stored as
    `"ctrl"` is held as Command there and is labelled that way. `focus_edit_p`'s
    docstring documents the same swap.
    """
    names = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "meta": "Meta"}
    if sys.platform == "darwin":
        names = {**names, "ctrl": "Cmd", "alt": "Option", "meta": "Control"}
    parts = [p for p in canonical(value).split("+") if p]
    return "+".join(names[p] for p in parts)
