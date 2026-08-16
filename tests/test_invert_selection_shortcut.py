"""Invert selection gets a real, rebindable keyboard shortcut.

The action shipped with a context-menu row and a working handler, but with its
shortcut argument written into the source as the empty string. So it had no key,
no row in the shortcuts dialog, and no default in ``default_settings.py`` -- the
one action of the selection trio (``Select all traces`` / ``Deselect all traces``
/ ``Invert selection``) a user could not reach from the keyboard and could not
give a key to.

The fix is the three places a shortcut has to agree, all of which
``test_configurable_shortcuts_applied.py`` already sweeps generically:

1. ``invertselection_act`` gains a default in ``default_settings.py``;
2. it gains a row in ``help_shortcuts``; and
3. the field menu tuple passes the series instead of ``""``, which is what makes
   ``newAction`` resolve the key by ``act_name``.

What this module adds on top of the generic sweeps is the part that is a
*choice* rather than a mechanism: which key, and the proof that the key really
reaches the handler.

**Why Ctrl+Shift+I.** It is the invert-selection key in Photoshop (``Select >
Inverse``), Krita and Affinity Photo, so the trio reads ``Ctrl+A`` / ``Ctrl+D`` /
``Ctrl+Shift+I`` and the odd one out borrows its muscle memory rather than
inventing it. Qt maps ``Ctrl`` to Command on Apple platforms, so one sequence
gives ``Ctrl+Shift+I`` on Windows and Linux and ``Cmd+Shift+I`` on macOS with no
platform branching. It is claimed by no system-global binding on any of the
three: on macOS ``Cmd+Shift+I`` is a Finder and Mail *menu item*, not a Service
or a symbolic hotkey, so it never leaves those apps; Windows reserves only
``Ctrl+Shift+Esc`` on that tier; and neither GNOME nor KDE takes it (the IBus
grabs that do bite are on ``Ctrl+Shift+U`` and ``Ctrl+Shift+E``).

The alternatives, and why each lost, pinned in
``test_invert_selection_rejected_alternatives`` so that a future "why not just
Ctrl+I?" lands on a test that answers it:

* ``Ctrl+I`` -- free in this app, but it is the italic key almost everywhere
  text is edited, ``Cmd+I`` is Get Info on macOS, and it already means invert
  *colors* in GIMP and Affinity Photo. The meaning is ambiguous across the tools
  this audience uses, which is the opposite of what borrowing a key is for.
* ``Ctrl+Alt+I`` -- free, and the tier ``copytosections_act`` already sits on,
  but ``Ctrl+Alt``+letter is indistinguishable from ``AltGr``+letter on
  international layouts. Microsoft's keyboard guidelines say to avoid the
  combination for exactly that reason, and Qt does not disambiguate the two
  (QTBUG-73247), so a German or Polish user typing an AltGr character would fire
  the shortcut. This was the runner-up and it is the one rejection with a
  concrete failure mode rather than a taste argument.
* ``Shift+I`` -- a bare Shift plus a letter is a typed capital and is swallowed
  by any focused text input. Plain ``I`` is already ``hideimage_act`` here, and
  ``Shift+I`` is Edit > Invert (the image) in ImageJ/Fiji, which this audience
  has open next to this app.
* ``!`` -- Inkscape's invert key, but Microsoft's guidelines list ``!``-class
  punctuation as a poor shortcut character, and Qt's own ``QKeySequence`` notes
  warn that Shift-plus-punctuation moves physical position between layouts.

**And why a duplicate would have been worse than the empty string it replaced.**
``test_menu_verification_headless.test_two_actions_sharing_a_sequence_fire_neither``
pins the platform behavior: Qt resolves an ambiguous shortcut by triggering
neither action. ``test_no_two_actions_share_a_shortcut_anywhere_reachable`` below
is the guard that follows from it, and it is deliberately wider than the existing
``test_no_two_actions_on_the_window_share_a_shortcut``. That one reads
``main_window.actions()``, and ``newAction`` keeps that list clean by design: it
does ``widget.removeAction(getattr(widget, act_name))`` before attaching a
rebuild. But the action it removes from the *window* is still inside whatever
``QMenu`` it was added to, and its shortcut is still live from there. So a second
construction site for an ``act_name`` that already has a key produces two firing
actions and a dead key, while the window-level check stays green. Measured, on a
real ``MainWindow``: giving the menubar its own ``selectall_act`` row alongside
the field menu's left ``Ctrl+A`` bound twice and selecting nothing at all.
"""

from collections import defaultdict

import pytest

from PyReconstruct.modules.datatypes.default_settings import (
    default_settings as qsettings_defaults,
)
from PyReconstruct.modules.gui.dialog.shortcuts import help_shortcuts


CHOSEN = "Ctrl+Shift+I"


# --------------------------------------------------------------------------- #
# 1. the three places, stated for this action specifically
# --------------------------------------------------------------------------- #
def test_invert_selection_has_a_configurable_default():
    """Without an entry here the shortcuts dialog has nothing to read or write:
    ``Series.getOption`` returns ``None`` for a name it does not know."""
    assert qsettings_defaults.get("invertselection_act") == CHOSEN


def test_invert_selection_has_a_shortcuts_dialog_row():
    """A default with no dialog row is a key the user cannot rebind."""
    rows = [
        item[0] for item in help_shortcuts
        if isinstance(item, tuple) and item[0].endswith("_act")
    ]
    assert "invertselection_act" in rows


def test_invert_selection_is_listed_beside_the_rest_of_the_trio():
    """It reads as the third member of the group in the help dialog, not as a
    stray row somewhere below it."""
    rows = [
        item[0] for item in help_shortcuts
        if isinstance(item, tuple) and item[0].endswith("_act")
    ]
    assert rows.index("invertselection_act") == rows.index("deselect_act") + 1


def test_field_menu_binds_the_key_rather_than_the_empty_string():
    """The regression this PR exists for.

    ``newAction`` only resolves a key by ``act_name`` when the third element of
    the tuple is the series. The literal ``""`` that shipped here meant the
    action was built with no shortcut at all, so a default and a dialog row
    would both have been decorative.
    """
    from PyReconstruct.modules.gui.main.context_menu_list import get_field_menu_list
    from test_context_menu_frequency import _kbds, _main_window_stub

    stub = _main_window_stub()
    kbds = _kbds(get_field_menu_list(stub))
    assert kbds["invertselection_act"] is stub.series, (
        "the field menu must pass the series so newAction looks the key up by "
        f"act_name; it passed {kbds['invertselection_act']!r}"
    )


# --------------------------------------------------------------------------- #
# 2. the choice
# --------------------------------------------------------------------------- #
def test_invert_selection_keeps_the_selection_trio_together():
    """Ctrl+A / Ctrl+D / Ctrl+Shift+I. If one of the three is ever retuned, the
    set should be retuned as a set."""
    assert qsettings_defaults["selectall_act"] == "Ctrl+A"
    assert qsettings_defaults["deselect_act"] == "Ctrl+D"
    assert qsettings_defaults["invertselection_act"] == CHOSEN


@pytest.mark.parametrize(
    "rejected, reason",
    [
        ("Ctrl+I", "italic where text is edited; Get Info on macOS; invert colors in GIMP"),
        ("Ctrl+Alt+I", "Ctrl+Alt+letter is AltGr+letter on international layouts"),
        ("Shift+I", "a typed capital; plain I is hideimage_act; Fiji's invert image"),
        ("!", "poor shortcut character, and Shift+punctuation moves between layouts"),
    ],
)
def test_invert_selection_rejected_alternatives(rejected, reason):
    """The alternatives are recorded, not just the winner.

    Each was free in this app, so "it was available" is not why the chosen key
    won and a future change cannot claim it was.
    """
    assert qsettings_defaults["invertselection_act"] != rejected, reason


def test_the_chosen_key_was_free_among_the_configurable_defaults():
    """Stated for this key specifically, so a failure names it.

    ``test_copy_to_sections_review.test_no_two_actions_share_a_default_shortcut``
    covers the whole dict generically and picks this entry up automatically.
    """
    owners = [
        name for name, value in qsettings_defaults.items()
        if name.endswith("_act") and isinstance(value, str)
        and value.strip().lower() == CHOSEN.lower()
    ]
    assert owners == ["invertselection_act"], (
        f"{CHOSEN} is claimed by more than one action: {owners}"
    )


def test_the_chosen_key_was_free_among_the_hardcoded_shortcuts():
    """The collision sweep only sees the settings dict.

    Some shortcuts are written straight into the source and are therefore
    invisible to it: the arrow and function keys in ``main_window.py``, the
    palette digits it generates, and ``Ctrl+\\`` in ``menubar.py``. A new default
    has to clear those too, and nothing else checks that.
    """
    from pathlib import Path
    import re

    gui = Path(__file__).resolve().parents[1] / "PyReconstruct" / "modules" / "gui"
    sources = [
        gui / "main" / "main_window.py",
        gui / "main" / "menubar.py",
        gui / "main" / "context_menu_list.py",
    ]
    pattern = re.compile(re.escape(CHOSEN), re.IGNORECASE)
    hits = [p.name for p in sources if pattern.search(p.read_text(encoding="utf-8"))]
    assert hits == [], f"{CHOSEN} is also hardcoded in {hits}"


# --------------------------------------------------------------------------- #
# 3. the key really reaches the handler, and it is the only one that does
# --------------------------------------------------------------------------- #
gui = pytest.mark.gui


@gui
def test_pressing_the_key_inverts_the_selection(main_window, qapp):
    """End to end, through a real window: the default key flips the selection.

    The generic sweep proves the action carries the configured sequence. This
    proves the sequence is actually delivered to it, which is the part an
    ambiguous binding would break while every static check stayed green.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest

    field = main_window.field
    section = field.section

    field.selectAllTraces()
    qapp.processEvents()
    everything = {id(t) for t in section.selected_traces}
    assert everything, "the fixture series has no traces to select"

    QTest.keySequence(main_window, QKeySequence(CHOSEN))
    qapp.processEvents()
    after = {id(t) for t in section.selected_traces}

    # clear the latched modifier before asserting -- see conftest
    QTest.keyRelease(main_window, Qt.Key_Shift)
    qapp.processEvents()

    assert after != everything, f"{CHOSEN} did not reach invertTraceSelection"
    assert not (after & everything), "inverting a full selection must empty it"


@gui
def test_no_two_actions_share_a_shortcut_anywhere_reachable(main_window):
    """Every bound sequence is bound once, counting actions inside menus.

    Wider than the window-level check in ``test_menu_verification_headless``, and
    for a specific reason: ``newAction`` de-duplicates ``main_window.actions()``
    on rebuild but leaves the superseded action in the ``QMenu`` it was added to,
    still holding a live shortcut. A second construction site for an action that
    already owns a key is therefore invisible to the window-level check and
    fatal to the key -- Qt fires neither of an ambiguous pair.
    """
    from PySide6.QtGui import QKeySequence

    seen = {}

    def walk(container):
        for action in container.actions():
            if id(action) in seen:
                continue
            seen[id(action)] = action
            submenu = action.menu()
            if submenu is not None:
                walk(submenu)

    walk(main_window)
    if main_window.menuBar() is not None:
        walk(main_window.menuBar())

    by_sequence = defaultdict(list)
    for action in seen.values():
        sequence = action.shortcut()
        if not sequence.isEmpty():
            by_sequence[sequence.toString(QKeySequence.PortableText)].append(
                action.text()
            )

    assert len(by_sequence) > 100, "the window was not populated; harness broken"
    duplicates = {s: t for s, t in by_sequence.items() if len(t) > 1}
    assert duplicates == {}, (
        "these sequences are bound to more than one live action, so Qt will "
        f"fire neither: {duplicates}"
    )


@gui
def test_the_new_key_is_bound_exactly_once(main_window):
    """The narrow form of the guard above, named for this key."""
    from PySide6.QtGui import QKeySequence

    target = QKeySequence(CHOSEN)
    owners = [
        action.text() for action in main_window.actions()
        if action.shortcut() == target
    ]
    assert owners == ["Invert selection"], owners
