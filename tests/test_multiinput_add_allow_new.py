"""Regression tests for ``MultiInput.add()`` dropping ``allow_new``.

``MultiInput.__init__`` builds each of its initial combo rows as
``CompleterBox(self, self.combo_items, allow_new=(not restrict_to_opts))``, so a
field declared with ``restrict_to_opts=False`` accepts free text: that is what
makes the regex filter fields work at all. ``add()``, the ``+`` button's slot,
built ``CompleterBox(self, self.combo_items)`` and left ``allow_new`` at its
default of ``False``. Every row added after the dialog opened was therefore
restricted to the drop-down while the first row was not.

The user-visible consequence is worse than a rejected keystroke.
``CompleterBox.focusOutEvent`` does not clear an out-of-list entry, it
*substitutes* one: the current completion if there is one, otherwise
``itemText(0)``. So typing a regex into an added row and tabbing away silently
replaced it with the alphabetically-first name in the drop-down, and
``getEntries()`` then reported that name as if the user had chosen it.
``QuickDialog``'s validation cannot catch it either, since it only checks
membership when ``restrict_to_opts`` is set.

These tests build the real widget, because the defect lives entirely in which
constructor argument reaches a real ``QComboBox``: a stubbed row cannot have the
wrong ``check_text``. The focus-out assertion is what pins the behavior; the
``check_text`` assertion is kept alongside it so a failure says which of the two
layers broke.
"""

import pytest

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QLineEdit, QWidget

from PyReconstruct.modules.gui.dialog.helper import MultiInput

# No `importorskip("pytestqt")` here on purpose. It would drop this whole module
# in a .venv synced without the `test` extra, and the suite would still say
# green. The `gui` mark plus the guard in tests/conftest.py
# (`pytest_collection_modifyitems`) turns that same environment into a hard
# error, while leaving `-m "not gui"` working.
pytestmark = pytest.mark.gui

# Deliberately not in sorted order: itemText(0) after CompleterBox's own
# sortList() is "alpha", which is what an unfixed added row substitutes in.
COMBO_ITEMS = ["beta", "alpha"]

# Matches nothing in COMBO_ITEMS, and is the shape of the values these fields
# exist to accept (the affected dialogs all label themselves "regex accepted").
TYPED = "d[0-9]+_regex"


def _blur(widget):
    """Send the focus-out that CompleterBox does its enforcement in."""
    widget.focusOutEvent(QFocusEvent(QEvent.FocusOut, Qt.OtherFocusReason))


@pytest.fixture
def parent(qapp):
    widget = QWidget()
    yield widget
    widget.deleteLater()


def _permissive_field(parent):
    return MultiInput(
        parent,
        entries=[""],
        combo=True,
        combo_items=COMBO_ITEMS,
        restrict_to_opts=False,
    )


def test_added_row_is_configured_like_the_initial_row(parent):
    """The `+` row must be as permissive as the row the dialog opened with.

    Split from the behavioral test below so a failure distinguishes "the wrong
    argument reached CompleterBox" from "CompleterBox's enforcement changed".
    """
    field = _permissive_field(parent)
    field.add()
    first, added = field.inputs[0], field.inputs[1]

    assert added.check_text is first.check_text is False


def test_added_row_keeps_a_typed_value_through_focus_out(parent):
    """What the user actually sees: the typed regex survives tabbing away."""
    field = _permissive_field(parent)
    field.add()

    for row in field.inputs:
        row.setCurrentText(TYPED)
        _blur(row)

    assert field.inputs[1].currentText() == TYPED, (
        "added row silently substituted a drop-down value"
    )
    assert field.getEntries() == [TYPED, TYPED]


def test_added_row_still_restricts_when_the_field_restricts(parent):
    """The fix must read `restrict_to_opts`, not hardcode `allow_new=True`.

    Groups and hosts multicombos rely on the restriction, and they are the
    majority of `multicombo` call sites.
    """
    field = MultiInput(
        parent,
        entries=[""],
        combo=True,
        combo_items=COMBO_ITEMS,
        restrict_to_opts=True,
    )
    field.add()
    added = field.inputs[1]

    assert added.check_text is True

    added.setCurrentText(TYPED)
    _blur(added)

    assert added.currentText() != TYPED
    assert added.currentText() in COMBO_ITEMS


def test_added_row_is_a_line_edit_when_the_field_is_not_a_combo(parent):
    """The non-combo path is what the trace tags field uses, and is untouched."""
    field = MultiInput(parent, entries=["a_tag"])
    field.add()

    assert [type(row) for row in field.inputs] == [QLineEdit, QLineEdit]

    field.inputs[1].setText("another_tag")
    assert field.getEntries() == ["a_tag", "another_tag"]
