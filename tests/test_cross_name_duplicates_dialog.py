"""The review list for duplicates named differently (board card #109).

`DifferentlyNamedDuplicatesDialog` is a real widget, driven here on the offscreen
platform. Three things about it are decisions rather than details, so they are
pinned:

  * **It offers no delete.** Which of two names survives is a question about the
    data, so the dialog is constructed without a delete callback and the base
    class must therefore show no Delete buttons at all. If deletion is ever added
    it will be a deliberate change to this test, not a silent one.
  * **Both traces of a pair are reachable.** "Go to trace" frames the first and
    "Go to other trace" frames the second, which is how a person decides which
    name is right. Both are disabled until a row is selected.
  * **The row shows both names, the overlap and both areas**, which is what makes
    the pair judgeable without opening anything else.

The extra-button hook the subclass uses is shared, so the base class and the
pixel-dust list are checked here too: neither grows a button, and the pixel-dust
list still shows its Delete buttons.
"""
import pytest

pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QDialogButtonBox

from conftest import menu_action, same_action

from PyReconstruct.modules.gui.dialog import (
    DifferentlyNamedDuplicatesDialog,
    MalformedContoursDialog,
    PixelDustDialog,
)

MENU_PATH = "Series > Clean up > Find duplicates named differently..."


def test_the_menu_row_is_the_action_the_window_names(main_window):
    """The row is in the real widget tree, as the action the window holds.

    The frozen menu lists in test_menubar_labels.py read the nested dicts
    `return_menubar` returns, against a stub whose `__getattr__` answers for any
    handler name at all. So they cannot tell a wired row from one naming a method
    that does not exist. This walks a real MainWindow's menubar instead.
    """
    expected = main_window.finddiffnamedduplicates_act  # read before the walk
    row = menu_action(main_window.menubar, MENU_PATH)
    assert row is not None, f"no row at {MENU_PATH!r}"
    assert same_action(row, expected)


def test_the_menu_row_reaches_this_operations_slot(main_window,
                                                   main_window_dialogs):
    """Triggering the row opens this operation's dialog, not a neighbor's.

    A stronger claim than the one above: `newAction` names the action from the
    same tuple that carries the handler, so a row can be the action the window
    names and still be connected to the wrong slot. The threshold prompt's title
    is what tells them apart, and cancelling it leaves the series alone.
    """
    row = menu_action(main_window.menubar, MENU_PATH)
    row.trigger()
    assert main_window_dialogs.dialogs[-1] == (
        "Find duplicates named differently"
    )


def _record(name="OBJ_A", other="OBJ_B", section=3, ratio=0.97):
    return {
        "name": name,
        "other_name": other,
        "section": section,
        "index": 0,
        "other_index": 1,
        "points": 12,
        "other_points": 14,
        "location": (1.25, 2.5),
        "other_location": (1.3, 2.55),
        "area": 0.5,
        "other_area": 0.52,
        "ratio": ratio,
        "reason": f"Overlap {ratio} with '{other}' (above 0.95)",
        "match": {"color": [1, 2, 3], "points": [(0.0, 0.0)]},
        "other_match": {"color": [1, 2, 3], "points": [(0.1, 0.0)]},
    }


def _button_texts(dialog):
    box = dialog.findChild(QDialogButtonBox)
    return [b.text() for b in box.buttons()]


def _dialog(qtbot, records=None, navigate=None):
    dialog = DifferentlyNamedDuplicatesDialog(
        None, records if records is not None else [_record()], navigate=navigate
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)
    return dialog


def test_no_delete_buttons_are_offered(qtbot):
    """Report only: the pairs list cannot delete anything from the series."""
    dialog = _dialog(qtbot)
    texts = _button_texts(dialog)
    assert not any("Delete" in t for t in texts), texts
    assert dialog.delete is None
    assert dialog.delete_selected_button is None
    assert dialog.delete_all_button is None


def test_report_only_is_a_property_of_the_class(qtbot):
    """No caller can pass a delete callback in, so adding one is deliberate.

    The base class shows Delete buttons whenever it is handed a delete callback,
    so "report only" would otherwise rest on one keyword argument at one call
    site in main_window. This dialog takes no such argument.
    """
    import inspect
    params = inspect.signature(DifferentlyNamedDuplicatesDialog).parameters
    assert "delete" not in params
    assert list(params) == ["mainwindow", "records", "navigate"]

    with pytest.raises(TypeError):
        DifferentlyNamedDuplicatesDialog(
            None, [_record()], delete=lambda recs: []
        )


def test_pixel_dust_list_still_deletes(qtbot):
    """The shared base class did not lose its Delete buttons."""
    records = [{
        "name": "DUST", "section": 1, "index": 0, "points": 4,
        "location": (0.0, 0.0), "reason": "Area 3 px^2", "area": 1e-4,
        "area_px": 3.0, "match": {"color": [1, 2, 3], "points": [(0.0, 0.0)]},
    }]
    dialog = PixelDustDialog(None, records, delete=lambda recs: [])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)
    texts = _button_texts(dialog)
    assert "Delete selected" in texts
    assert "Delete all" in texts
    # and the shared hook added nothing to it
    assert dialog.extra_buttons == []


def test_base_dialog_grows_no_extra_button(qtbot):
    """The hook is opt-in: the smoothing report is unchanged."""
    records = [{
        "name": "OBJ", "section": 1, "index": 0, "points": 2,
        "location": (0.0, 0.0), "reason": "Too few points",
        "match": {"color": [1, 2, 3], "points": [(0.0, 0.0)]},
    }]
    dialog = MalformedContoursDialog(None, records)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)
    assert dialog.extra_buttons == []
    assert _button_texts(dialog) == ["Close", "Go to trace", "Copy table list",
                                     "Save table as CSV…"]


def test_both_traces_of_a_pair_are_reachable(qtbot):
    """"Go to trace" frames the first trace, "Go to other trace" the second."""
    visited = []
    dialog = _dialog(qtbot, navigate=lambda s, n, i: visited.append((s, n, i)))

    assert "Go to other trace" in _button_texts(dialog)

    # nothing selected: both navigation buttons are off
    assert dialog.goto_button.isEnabled() is False
    assert dialog.goto_other_button.isEnabled() is False
    dialog.goToSelectedOtherContour()
    assert visited == []

    dialog.table.selectRow(0)
    qtbot.wait(30)
    assert dialog.goto_button.isEnabled() is True
    assert dialog.goto_other_button.isEnabled() is True

    dialog.goToSelectedContour()
    dialog.goToSelectedOtherContour()
    assert visited == [(3, "OBJ_A", 0), (3, "OBJ_B", 1)]


def test_the_row_names_both_objects_and_shows_the_overlap(qtbot):
    """A pair is judgeable from the row: both names, the overlap, both areas."""
    dialog = _dialog(qtbot)
    headers = [
        dialog.table.horizontalHeaderItem(c).text()
        for c in range(dialog.table.columnCount())
    ]
    assert headers == ["Object", "Duplicate of", "Section", "Overlap",
                       "Area (um^2)", "Other area (um^2)", "Point count",
                       "Location (x, y)", "Reason"]

    cells = [dialog.table.item(0, c).text() for c in range(len(headers))]
    assert cells[0] == "OBJ_A"
    assert cells[1] == "OBJ_B"
    assert cells[2] == "3"
    assert cells[3].startswith("0.97")
    assert cells[4].startswith("0.5")
    assert cells[5].startswith("0.52")
    assert "(1.25, 2.5)" in cells[7]


def test_the_table_opens_sorted_by_section(qtbot):
    """Column 1 is "Duplicate of" here, so the default sort column moved to 2."""
    records = [_record(section=9), _record(section=2), _record(section=5)]
    dialog = _dialog(qtbot, records)
    sections = [
        int(dialog.table.item(row, 2).text())
        for row in range(dialog.table.rowCount())
    ]
    assert sections == [2, 5, 9]
    assert DifferentlyNamedDuplicatesDialog.DEFAULT_SORT_COLUMN == 2
    assert MalformedContoursDialog.DEFAULT_SORT_COLUMN == 1


def test_the_heading_says_nothing_was_changed(qtbot):
    """The one thing a reader must not get wrong about this list."""
    dialog = _dialog(qtbot)
    heading = dialog.heading.text()
    assert "Nothing in the series has been changed." in heading
    assert "1 pair" in heading
