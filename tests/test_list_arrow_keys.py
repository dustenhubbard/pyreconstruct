"""Arrow keys in a focused data list move through the list, not the field.

The field's nudge shortcuts (arrow keys, alone or with Ctrl, Shift or both)
are added to the main window in `MainWindow.createShortcuts`. Every data list
is a dock inside that window, so the window-scoped shortcut fired while a list
had focus: Down over the Object list moved the selected trace 0.1 um, or with
nothing selected on an unlocked section shifted the section transform, and the
list row never moved.

Each list view now accepts the ShortcutOverride for an arrow key
(`claimsArrowKey` in `gui/table/copy_table_widget.py`), which is Qt's way for a
focused widget to take a key ahead of a shortcut. Pinned here: over every list
type the key moves the list's current row and leaves the field alone, and over
the field it still nudges.
"""
import pytest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

pytestmark = pytest.mark.gui

# Every list type. The trace list is built per section, the rest series-wide.
LIST_TYPES = ["object", "trace", "ztrace", "section", "flag"]


def _open_list(main_window, table_type):
    """Open a data list, show it, and give its view keyboard focus."""
    manager = main_window.field.table_manager
    if table_type == "trace":
        manager.newTable(table_type, main_window.field.section)
    else:
        manager.newTable(table_type)

    table = manager.tables[table_type][-1]
    table.show()
    table.table.setFocus()
    return table


def _tform(main_window):
    return list(main_window.field.section.tform.getList())


@pytest.fixture
def unlocked_window(main_window, qapp):
    """The window, shown, on a section whose alignment can move.

    The fixture series ships with its sections' alignment locked, which hides
    the transform half of the bug. A user's series is usually unlocked.
    """
    main_window.show()
    main_window.activateWindow()
    main_window.field.section.align_locked = False
    main_window.field.deselectAllTraces()
    qapp.processEvents()
    return main_window


@pytest.mark.parametrize("table_type", ["object", "trace"])
@pytest.mark.parametrize("key", [Qt.Key_Down, Qt.Key_Up])
def test_arrow_in_a_focused_list_moves_the_row(
    unlocked_window, qapp, table_type, key
):
    """The list row moves and the section transform does not."""
    window = unlocked_window
    view = _open_list(window, table_type).table
    model = view.model()
    assert model.rowCount() >= 3
    view.setCurrentIndex(model.index(1, 0))
    qapp.processEvents()
    window.series.modified = False
    before = _tform(window)

    QTest.keyClick(view, key)
    qapp.processEvents()

    expected = 2 if key == Qt.Key_Down else 0
    assert view.currentIndex().row() == expected
    assert _tform(window) == before
    assert window.series.modified is False


@pytest.mark.parametrize("table_type", ["object", "trace"])
def test_arrow_in_a_focused_list_leaves_the_selected_trace(
    unlocked_window, qapp, table_type
):
    """With a trace selected, Down over the list does not move the trace."""
    window = unlocked_window
    field = window.field
    trace = next(iter(field.section.contours.values()))[0]
    field.section.selected_traces = [trace]
    before = list(trace.points)
    view = _open_list(window, table_type).table
    view.setCurrentIndex(view.model().index(0, 0))
    qapp.processEvents()
    window.series.modified = False

    QTest.keyClick(view, Qt.Key_Down)
    qapp.processEvents()

    assert list(trace.points) == before
    assert window.series.modified is False


@pytest.mark.parametrize("table_type", LIST_TYPES)
@pytest.mark.parametrize(
    "modifier",
    [Qt.NoModifier, Qt.ControlModifier, Qt.ShiftModifier,
     Qt.ControlModifier | Qt.ShiftModifier],
)
def test_no_arrow_combination_reaches_the_field_from_a_list(
    unlocked_window, qapp, table_type, modifier
):
    """Every nudge and rotate combination stays in the list, on every list."""
    window = unlocked_window
    view = _open_list(window, table_type).table
    qapp.processEvents()
    before = _tform(window)

    # checked after each key: Left then Right would cancel out and hide a nudge
    for key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
        QTest.keyClick(view, key, modifier)
        qapp.processEvents()
        assert _tform(window) == before, key


def test_arrow_over_the_field_still_nudges(unlocked_window, qapp):
    """The shortcut itself is untouched: with the field focused, Down moves."""
    window = unlocked_window
    window.field.setFocus()
    qapp.processEvents()
    before = _tform(window)

    QTest.keyClick(window.field, Qt.Key_Down)
    qapp.processEvents()

    assert _tform(window) != before
