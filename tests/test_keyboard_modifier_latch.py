"""The modifier latch, the guard that clears it, and the damage it does.

`QApplication.keyboardModifiers()` is process-wide, and under PySide6 6.5.2 a
synthetic modified key press leaves it set for the rest of the process. See the
comment above `clear_latched_modifiers` in `conftest.py` for the mechanism and
for why the cleanup is central rather than per call site.

Four things are pinned here, and they are separate claims:

  BEHAVIOR   that the latch happens at all, for both `QTest.keyClick` with a
             modifier mask and `QTest.keySequence`. If a later PySide6 fixes
             this, these tests fail, and that is the signal that the guard can
             be deleted. Written as an assertion rather than a comment for
             exactly that reason.

  MECHANISM  that a `QTest` press clears it and a `QApplication.sendEvent` of a
             hand-built `QKeyEvent` does not. The wrong fix looks right, so the
             difference is worth a test.

  GUARD      that `_no_latched_modifiers` actually runs between tests. Proven by
             an ordered pair: one test leaves a latch deliberately, the next
             asserts it is gone. Nothing in this suite randomizes test order
             (no `pytest-randomly`, no `pytest-random-order`), so within a
             module the definition order holds; the second test skips rather
             than passing vacuously if it somehow runs alone.

  DAMAGE     that a latched modifier changes what a mouse click means to a real
             list widget. This is the reason any of it matters: the tests it
             breaks press no keys.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from conftest import clear_latched_modifiers

pytestmark = pytest.mark.gui


# --- BEHAVIOR: the latch is real, and this is the version it is real on -------

@pytest.mark.parametrize(
    "sequence,expected",
    [
        ("Ctrl+Shift+O", Qt.ShiftModifier),
        ("Ctrl+Alt+Shift+G", Qt.ShiftModifier),
        ("Ctrl+G", Qt.ControlModifier),
    ],
)
def test_a_modified_key_sequence_latches_a_modifier_process_wide(
    qapp, sequence, expected
):
    """`QTest.keySequence` leaves a modifier standing after the press is over.

    The spelling the menu verification tests use. `expected` is the *last*
    modifier of the sequence rather than the whole mask, which is itself worth
    pinning: `Ctrl+G` latches `ControlModifier`, so a suite can be green only
    because its final key press happened to be the harmless one.
    """
    target = QWidget()
    target.show()

    QTest.keySequence(target, QKeySequence(sequence))

    assert QApplication.keyboardModifiers() == expected


def test_key_click_with_a_modifier_mask_latches_too(qapp):
    """The other spelling, `QTest.keyClick(w, key, mask)`, does the same."""
    target = QWidget()
    target.show()

    QTest.keyClick(target, Qt.Key_A, Qt.ControlModifier | Qt.ShiftModifier)

    assert QApplication.keyboardModifiers() == Qt.ShiftModifier


def test_an_unmodified_press_is_what_clears_it(qapp):
    """Any unmodified `QTest` press clears the whole mask, not just one bit."""
    target = QWidget()
    target.show()
    QTest.keyClick(target, Qt.Key_A, Qt.ControlModifier | Qt.ShiftModifier)
    assert QApplication.keyboardModifiers() != Qt.NoModifier

    QTest.keyClick(target, Qt.Key_B, Qt.NoModifier)

    assert QApplication.keyboardModifiers() == Qt.NoModifier


# --- MECHANISM: what clears it, and what only looks like it should ------------

def test_clear_latched_modifiers_clears_every_combination(qapp):
    """The helper works from each mask a real shortcut can leave behind."""
    target = QWidget()
    target.show()

    for sequence in ("Ctrl+Shift+O", "Ctrl+Alt+Shift+G", "Ctrl+G", "Alt+F"):
        QTest.keySequence(target, QKeySequence(sequence))
        assert QApplication.keyboardModifiers() != Qt.NoModifier, sequence

        clear_latched_modifiers()

        assert QApplication.keyboardModifiers() == Qt.NoModifier, sequence


def test_clear_latched_modifiers_needs_no_visible_widget(qapp):
    """It does not touch the caller's widgets, and needs none of its own.

    What makes it callable from a teardown that runs after the test's own window
    has been closed.
    """
    target = QWidget()
    target.show()
    QTest.keySequence(target, QKeySequence("Ctrl+Shift+O"))
    target.close()
    target.deleteLater()

    clear_latched_modifiers()

    assert QApplication.keyboardModifiers() == Qt.NoModifier


def test_it_takes_a_key_press_and_a_release_will_not_do(qapp):
    """A `KeyRelease` on its own does not clear the latch. A `KeyPress` does.

    `QApplication::notify` records the modifiers of a `KeyPress` it delivers and
    does not do the same for a `KeyRelease`, so a clear built out of modifier
    releases (the obvious shape, since a stuck modifier is what this looks like)
    leaves the latch exactly where it was. `QTest.keyClick` sends a press before
    the release, which is why `clear_latched_modifiers` uses it.
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    target = QWidget()
    target.show()
    QTest.keySequence(target, QKeySequence("Ctrl+Shift+O"))

    QApplication.sendEvent(
        target, QKeyEvent(QEvent.KeyRelease, Qt.Key_A, Qt.NoModifier)
    )
    assert QApplication.keyboardModifiers() == Qt.ShiftModifier

    QApplication.sendEvent(
        target, QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier)
    )
    assert QApplication.keyboardModifiers() == Qt.NoModifier


def test_clear_latched_modifiers_is_a_no_op_when_nothing_is_latched(qapp):
    """Callable unconditionally, which is what lets the fixture be autouse."""
    assert QApplication.keyboardModifiers() == Qt.NoModifier

    clear_latched_modifiers()
    clear_latched_modifiers()

    assert QApplication.keyboardModifiers() == Qt.NoModifier


# --- GUARD: the autouse fixture actually runs between tests -------------------

_LEFT_A_LATCH = []


def test_a_latch_left_standing_at_the_end_of_a_test(qapp):
    """Leave a `ShiftModifier` latched on purpose, and do not clean up.

    Half of an ordered pair. This test asserts only that it succeeded in
    creating the mess; the next one asserts the mess was cleaned up. Deleting
    `_no_latched_modifiers` from `conftest.py` makes the next test fail, which is
    the revert-and-fail proof for the guard.
    """
    target = QWidget()
    target.show()

    QTest.keySequence(target, QKeySequence("Ctrl+Shift+O"))

    assert QApplication.keyboardModifiers() == Qt.ShiftModifier
    _LEFT_A_LATCH.append("Ctrl+Shift+O")


def test_the_autouse_guard_cleared_what_the_previous_test_left(qapp):
    """The latch left by the previous test is gone before this one runs."""
    if not _LEFT_A_LATCH:
        pytest.skip(
            "proves the guard only when run after "
            "test_a_latch_left_standing_at_the_end_of_a_test"
        )

    assert QApplication.keyboardModifiers() == Qt.NoModifier


# --- DAMAGE: why a test that presses no keys cares ---------------------------

def test_a_latched_shift_makes_select_row_select_nothing(qapp, section_table):
    """Reproduce the failure mode in the widget that suffered it.

    No mouse event anywhere in this test. `selectRow` resolves its selection
    command through `extendedSelectionCommand`, which is handed the originating
    event when there is one and reads
    `QGuiApplication::keyboardModifiers()` when there is not. A latched
    `ShiftModifier` therefore means "extend from the current index", and after
    `clearSelection()` there is no current index to extend from, so the call
    silently selects nothing.

    That is the whole of the seven `test_section_list_real_widget.py` failures:
    their `assert len(table.selectedIndexes()) > 1` sees 0.

    The precondition is that there is no current index, which is the state a
    freshly built section list is in and the state each of those tests reaches
    through `clearSelection()`. It is set explicitly here so the test does not
    depend on the fixture's construction order: with a current index already at
    row 0, Shift extends from row 0 to row 0 and the bug is invisible.

    Manages the modifier state itself at both ends rather than leaning on the
    autouse guard, so the assertions are about `selectRow` and not about teardown
    order, and so removing the guard produces one clear failure in the test named
    for it rather than a confusing one here.
    """
    clear_latched_modifiers()
    table = section_table.table

    table.setCurrentCell(-1, -1)
    table.clearSelection()
    table.selectRow(0)
    assert len(table.selectedIndexes()) > 1
    assert {index.row() for index in table.selectedIndexes()} == {0}

    table.setCurrentCell(-1, -1)
    table.clearSelection()
    QTest.keySequence(table, QKeySequence("Ctrl+Shift+O"))
    assert QApplication.keyboardModifiers() == Qt.ShiftModifier
    try:
        table.selectRow(0)
        latched = table.selectedIndexes()
    finally:
        clear_latched_modifiers()

    assert latched == []


def test_a_latched_control_leaves_select_row_looking_correct(qapp, section_table):
    """And this is why a green run proves nothing about the next one.

    `ControlModifier` resolves to "toggle", which from a cleared selection gives
    the same answer as a plain select. So the same suite passes or fails on which
    modifier the last key press anywhere in the session left standing, with no
    test able to see the difference. `Ctrl+G` is the last press in the menu
    verification file today; a `Ctrl+Shift+...` sequence appended below it would
    be enough.
    """
    clear_latched_modifiers()
    table = section_table.table
    table.setCurrentCell(-1, -1)
    table.clearSelection()

    QTest.keySequence(table, QKeySequence("Ctrl+G"))
    assert QApplication.keyboardModifiers() == Qt.ControlModifier
    try:
        table.selectRow(0)
        latched_rows = {index.row() for index in table.selectedIndexes()}
        latched_count = len(table.selectedIndexes())
    finally:
        clear_latched_modifiers()

    assert latched_rows == {0}
    assert latched_count > 1
