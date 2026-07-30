"""Real-widget geometry tests for the ``+`` and ``-`` buttons on a multi-value field.

``MultiInput`` (``PyReconstruct/modules/gui/dialog/helper.py``) is the widget
behind the ``multitext`` and ``multicombo`` dialog field types: tag filters,
regex filters, group filters, host names, user-column options, and the trace
attributes dialog's tag list. ``+`` appends a row, ``-`` drops one.

Why these tests exist. ``remove()`` calls ``self.container.adjustSize()`` and
``add()`` does not, which reads like an oversight and was reported as one ("the
dialog does not grow, so the new row can be clipped"). It is not an oversight,
and measuring it is the only way to know that:

- The dialogs that host a ``MultiInput`` set no size constraint, so their layout
  runs under ``QLayout.SetDefaultConstraint``. On a window, that makes
  ``QLayout.activate()`` push the layout's total minimum size onto the window
  via ``QWidget.setMinimumSize()``, and ``setMinimumSize()`` resizes a window
  that is currently smaller than its new minimum. Appending a fixed-height row
  therefore grows the dialog by exactly one row with no explicit call.
- Nothing in Qt shrinks a window when its minimum drops. That is what
  ``remove()``'s ``adjustSize()`` is for, and it is load-bearing: measured
  without it, four ``-`` presses leave the dialog at its five-row height.

So the asymmetry is correct, and the property worth protecting is not "which
method calls ``adjustSize()``" but the user-visible one: after pressing ``+``,
every row of the field, and the OK/Cancel box below it, is still fully inside
the dialog. These tests assert that directly, in dialog coordinates, so they
keep holding if the mechanism ever changes. ``test_remove_shrinks_the_dialog``
is the one that fails if ``remove()``'s ``adjustSize()`` is dropped.

That test allows one row of residual height, deliberately, because the shipped
``-`` runs one press behind. ``adjustSize()`` resizes to the size hint but
``resize()`` is clamped by the window's current ``minimumSize()``, and that
minimum is only lowered by the next ``QLayout.activate()``, which happens on a
posted layout request after ``remove()`` has already returned. So the first
``-`` leaves the dialog at its old height and every later one lands one row
high: measured 262 to [262, 233, 204, 175] over four presses, where one row is
29px and one row of content is 146px. Closing that needs the container's layout
re-activated before the resize (or the resize deferred behind the layout
request), which is a change to ``remove()`` and not to ``add()``.

Two mechanics that a size assertion gets wrong if it skips them, both measured
on PySide6 6.5.2:

1. Geometry is meaningless until the widget has been shown and the event loop
   has spun. ``qtbot.wait()`` is doing real work here, not padding.
2. ``remove()`` retires the row with ``deleteLater()``, and a bare
   ``processEvents()`` does not flush a deferred delete. Until it is flushed the
   row still occupies the layout and the dialog does not shrink, which reads as
   a failure of ``adjustSize()``. Hence ``_settle()``.
"""

import pytest

# No `importorskip("pytestqt")` here on purpose. It would drop this whole module
# in a .venv synced without the `test` extra, and the suite would still say
# green. The `gui` mark plus the guard in tests/conftest.py
# (`pytest_collection_modifyitems`) turns that same environment into a hard
# error, while leaving `-m "not gui"` working.
pytestmark = pytest.mark.gui

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton

from PyReconstruct.modules.gui.dialog.helper import MultiInput
from PyReconstruct.modules.gui.dialog.quick_dialog import QuickDialog


# The real "Tag Filters" structure, from ObjectTableWidget.setTagFilter: a
# label row and a multitext row. Every dialog that hosts a MultiInput has this
# shape (labels, line edits, check rows, the field itself), all fixed-height.
TAG_FILTER_STRUCTURE = [
    ["Enter the tag filter(s) below"],
    [("multitext", ["a"])],
]

# The real "Group Filters" structure from the same widget, for the combo
# variant. The options list is arbitrary; only the row height matters here.
GROUP_FILTER_STRUCTURE = [
    ["Enter the group filter(s) below"],
    [("multicombo", ["axon", "dendrite", "glia"], ["axon"])],
]


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


def _bottom_in_dialog(dialog, widget):
    """Bottom edge of `widget` in `dialog` coordinates."""
    top_left = widget.mapTo(dialog, widget.rect().topLeft())
    return top_left.y() + widget.height()


def _assert_everything_fits(dialog, field):
    """Every row, and the button box, is fully inside the dialog."""
    for index, row in enumerate(field.inputs):
        bottom = _bottom_in_dialog(dialog, row)
        assert bottom <= dialog.height(), (
            f"row {index} of {len(field.inputs)} is clipped: bottom {bottom} "
            f"exceeds dialog height {dialog.height()}"
        )
    box = dialog.findChildren(QDialogButtonBox)[0]
    bottom = _bottom_in_dialog(dialog, box)
    assert bottom <= dialog.height(), (
        f"OK/Cancel is clipped: bottom {bottom} exceeds dialog height "
        f"{dialog.height()}"
    )


@pytest.mark.parametrize(
    "structure", [TAG_FILTER_STRUCTURE, GROUP_FILTER_STRUCTURE],
    ids=["multitext", "multicombo"],
)
def test_add_grows_the_dialog_by_one_row(qtbot, structure):
    """Each ``+`` makes the dialog taller, by the same amount every time."""
    dialog, field = _dialog(qtbot, structure)
    plus = _button(field, "+")

    heights = [dialog.height()]
    for _ in range(4):
        plus.click()
        _settle(qtbot)
        heights.append(dialog.height())

    assert len(field.inputs) == 5
    deltas = [b - a for a, b in zip(heights, heights[1:])]
    assert all(d > 0 for d in deltas), f"dialog did not grow: heights {heights}"
    assert len(set(deltas)) == 1, (
        f"growth per row was not uniform: {deltas} from heights {heights}"
    )


@pytest.mark.parametrize(
    "structure", [TAG_FILTER_STRUCTURE, GROUP_FILTER_STRUCTURE],
    ids=["multitext", "multicombo"],
)
def test_added_rows_are_never_clipped(qtbot, structure):
    """The row ``+`` just added is fully visible, and so is OK/Cancel."""
    dialog, field = _dialog(qtbot, structure)
    plus = _button(field, "+")

    _assert_everything_fits(dialog, field)
    for _ in range(6):
        plus.click()
        _settle(qtbot)
        _assert_everything_fits(dialog, field)


def test_remove_shrinks_the_dialog(qtbot):
    """``-`` gives the height back.

    This is the assertion that ``remove()``'s ``adjustSize()`` exists to
    satisfy. Qt grows a window when its layout minimum grows but never shrinks
    one when the minimum drops, so dropping that call leaves the dialog stuck at
    its tallest-ever height: four rows of dead space, not one.

    Stops at one remaining row, because an empty field is a separate question
    from a resize. Tolerates one row of residual height, because the shipped
    ``-`` lands one press behind (see the module docstring).
    """
    dialog, field = _dialog(qtbot, TAG_FILTER_STRUCTURE)
    plus = _button(field, "+")
    minus = _button(field, "-")

    start = dialog.height()
    for _ in range(4):
        plus.click()
        _settle(qtbot)
    grown = dialog.height()
    assert grown > start
    one_row = (grown - start) // 4

    heights = []
    for _ in range(4):
        minus.click()
        _settle(qtbot)
        heights.append(dialog.height())

    assert len(field.inputs) == 1
    assert heights == sorted(heights, reverse=True), (
        f"dialog height did not fall monotonically as rows were removed: "
        f"{heights}"
    )
    assert dialog.height() <= start + one_row, (
        f"dialog stayed at {dialog.height()} after removing back to one row; "
        f"it was {start} with one row and {grown} with five, and one row is "
        f"{one_row}px. Heights after each '-': {heights}"
    )
