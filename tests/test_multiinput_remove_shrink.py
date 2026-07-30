"""Real-widget geometry tests for ``-`` on a multi-value dialog field.

``MultiInput`` (``PyReconstruct/modules/gui/dialog/helper.py``) is the widget
behind the ``multitext`` and ``multicombo`` field types: tag filters, group
filters, regex filters, host names, and the trace attributes dialog's tag list.
``+`` appends a row and ``-`` drops one.

``tests/test_multiinput_row_resize.py`` pins the growth direction. This file
pins the shrink direction, which was one press behind: the dialog kept the
height of a row that was no longer there, so a band of unused space sat inside
the dialog and every further ``-`` moved it rather than removing it. Removing
four of five rows measured 262 to [262, 233, 204, 175] where the one-row height
is 146, so the dialog finished 29px (one row) too tall no matter how many rows
were taken out. On the real cocoa platform the same sequence measured 302 to
[302, 271, 240, 209] against a one-row height of 178.

The cause was a stale size hint rather than a stale minimum size. Dropping a row
marks the layouts dirty and posts a layout request, and until that request is
delivered both the field's size hint and the host's still describe the layout
with the row in it. The button's slot returns before the request is delivered, so
``adjustSize()`` was resizing to the previous row count's hint. Measured: setting
the window minimum to zero first does not help, and neither does activating only
the host's layout, because the host asks the field for a hint the field has not
recomputed.

These assertions are written against the user-visible property, not against
heights, so they survive a font or platform-metric change:

- The dialog is the same size for the same content. Whatever height it had with
  N rows on the way up is the height it has with N rows on the way back down.
  That is what "no accumulated dead space" means, stated without a literal.
- The dialog is no taller than the space its contents ask for, after every
  press. A window taller than its own size hint, with nothing stretchable in it,
  is showing dead space by definition.

Two mechanics a size assertion has to respect or it passes for the wrong reason,
both measured on PySide6 6.5.2:

1. Geometry is not settled until the widget is shown and the event loop has
   spun. The ``qtbot.wait()`` in ``_settle`` is load-bearing.
2. ``remove()`` retires its row with ``deleteLater()``, and ``processEvents()``
   does not flush a deferred delete. Until it is flushed the row still occupies
   the layout and the dialog does not shrink, which reads as a failure of the
   resize. ``_settle`` flushes it explicitly.
"""

import pytest

pytest.importorskip("pytestqt", reason="real-widget tests need pytest-qt")

pytestmark = pytest.mark.gui

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QPushButton

from PyReconstruct.modules.gui.dialog.helper import MultiInput
from PyReconstruct.modules.gui.dialog.quick_dialog import QuickDialog


# The real "Tag Filters" structure from ObjectTableWidget.setTagFilter, and the
# real "Group Filters" structure for the combo variant. Both hosts are built
# from fixed-height widgets, which is true of every dialog that hosts a
# MultiInput.
TAG_FILTER_STRUCTURE = [
    ["Enter the tag filter(s) below"],
    [("multitext", ["a"])],
]
GROUP_FILTER_STRUCTURE = [
    ["Enter the group filter(s) below"],
    [("multicombo", ["axon", "dendrite", "glia"], ["axon"])],
]

ALL_STRUCTURES = pytest.mark.parametrize(
    "structure", [TAG_FILTER_STRUCTURE, GROUP_FILTER_STRUCTURE],
    ids=["multitext", "multicombo"],
)


def _settle(qtbot):
    """Spin the event loop, then flush deferred deletes and re-layout."""
    qtbot.wait(30)
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()


def _dialog(qtbot, structure, title="Filters"):
    dialog = QuickDialog(None, structure, title)
    qtbot.addWidget(dialog)
    dialog.show()
    _settle(qtbot)
    return dialog, dialog.findChildren(MultiInput)[0]


def _button(field, text):
    for button in field.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"no {text!r} button on the field")


def _grow(qtbot, dialog, field, presses):
    """Press ``+`` `presses` times, returning the height at each row count."""
    plus = _button(field, "+")
    heights = {len(field.inputs): dialog.height()}
    for _ in range(presses):
        plus.click()
        _settle(qtbot)
        heights[len(field.inputs)] = dialog.height()
    return heights


def _assert_no_dead_space(dialog, note=""):
    """The dialog is no taller than the space its contents ask for."""
    needed = dialog.sizeHint().height()
    assert dialog.height() <= needed, (
        f"dialog is {dialog.height() - needed}px taller than its contents "
        f"need ({dialog.height()} against {needed}){note}"
    )


@ALL_STRUCTURES
def test_dialog_is_the_same_size_for_the_same_rows(qtbot, structure):
    """A row count has one height, whether it was reached by ``+`` or by ``-``.

    The failure this catches is the accumulating band of unused space: with the
    shrink a press behind, four rows on the way down were as tall as five rows
    on the way up, and so on all the way to one row.
    """
    dialog, field = _dialog(qtbot, structure)
    growing = _grow(qtbot, dialog, field, 4)
    assert len(field.inputs) == 5

    minus = _button(field, "-")
    shrinking = {}
    for _ in range(4):
        minus.click()
        _settle(qtbot)
        shrinking[len(field.inputs)] = dialog.height()

    assert len(field.inputs) == 1
    assert shrinking == {rows: growing[rows] for rows in shrinking}, (
        f"heights differ by history: going up {growing}, coming down "
        f"{shrinking}"
    )


@ALL_STRUCTURES
def test_no_dead_space_below_the_rows_after_each_removal(qtbot, structure):
    """Every ``-`` leaves the dialog fitting its contents, not a row larger."""
    dialog, field = _dialog(qtbot, structure)
    _grow(qtbot, dialog, field, 5)

    minus = _button(field, "-")
    for press in range(1, 6):
        minus.click()
        _settle(qtbot)
        _assert_no_dead_space(
            dialog, f", after '-' press {press} ({len(field.inputs)} rows left)"
        )


def test_removing_back_to_one_row_lands_on_the_one_row_height(qtbot):
    """The boundary: down to a single row is the height the dialog opened at.

    ``MultiInput.__init__`` coerces an empty entry list to ``[""]``, so one row
    is the floor, and ``remove()`` clears the last row's text rather than
    deleting it. Pressing ``-`` again at the floor must therefore leave the
    height alone rather than shrink it further.
    """
    dialog, field = _dialog(qtbot, TAG_FILTER_STRUCTURE)
    opening = dialog.height()
    assert len(field.inputs) == 1

    _grow(qtbot, dialog, field, 4)
    grown = dialog.height()
    assert grown > opening

    minus = _button(field, "-")
    for _ in range(4):
        minus.click()
        _settle(qtbot)

    assert len(field.inputs) == 1
    assert dialog.height() == opening, (
        f"dialog is {dialog.height()} back at one row, not the {opening} it "
        f"opened at; it was {grown} with five rows"
    )

    minus.click()
    _settle(qtbot)
    assert len(field.inputs) == 1
    assert field.getEntries() == []
    assert dialog.height() == opening


def test_removing_a_middle_row_shrinks_the_dialog(qtbot):
    """``-`` on the row being edited gives back a row's height, not zero.

    ``remove()`` drops the focused row rather than the last one, so the resize
    has to hold for a row taken out of the middle of the field as well. Offscreen
    Qt hands out no focus until the window is active, hence ``activateWindow()``.
    """
    dialog, field = _dialog(qtbot, TAG_FILTER_STRUCTURE)
    one_row_height = dialog.height()
    _grow(qtbot, dialog, field, 2)
    three_rows = dialog.height()
    row = (three_rows - one_row_height) // 2
    assert row > 0

    field.inputs[0].setText("first")
    field.inputs[1].setText("middle")
    field.inputs[2].setText("last")

    dialog.activateWindow()
    field.inputs[1].setFocus()
    _settle(qtbot)
    assert field.currentIndex() == 1

    _button(field, "-").click()
    _settle(qtbot)

    assert field.getEntries() == ["first", "last"]
    assert dialog.height() == three_rows - row, (
        f"dialog is {dialog.height()} after removing the middle of three rows; "
        f"three rows was {three_rows} and a row is {row}px"
    )
    _assert_no_dead_space(dialog)
