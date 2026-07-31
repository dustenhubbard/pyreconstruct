"""The review list for duplicates named differently (board card #109).

`DifferentlyNamedDuplicatesDialog` is a real widget, driven here on the offscreen
platform.

**The decision this file exists to pin, settled 2026-07-31.** The dialog started
report-only, and the tests here said so. The maintainer was given four options
and chose per-row selection: each row offers a choice between its two names, the
kept one is ticked, and one action deletes the unselected side of every row that
was answered. He rejected keeping the most-established name automatically,
rejected reassigning instead of deleting, and rejected leaving it report-only.
The reason is the code's own: which name is correct is a judgment about the data
that geometry cannot settle, so the tool must never guess.

So what is pinned now:

  * **No row starts chosen, and an unanswered row is never handed over.** Silence
    is not a selection. `test_no_row_starts_chosen` and
    `test_only_the_answered_rows_reach_the_callback` are that decision; a change
    that makes either fail is reversing it, not fixing it.
  * **The two names of a row are mutually exclusive**, so a row can say "keep
    this one", "keep that one", or nothing at all -- never "keep both".
  * **The choice survives a column sort.** It is item check state, not a cell
    widget, exactly so that re-sorting the table cannot shuffle answers onto the
    wrong pairs.
  * **The base class's "Delete selected" / "Delete all" never appear.** Both
    would be wrong for a list of pairs: row selection is how a pair is inspected,
    and "all" would mean deleting both sides. The dialog passes no `delete`
    callback up for that reason.
  * **Report-only is still reachable**, for a caller that hands over no delete
    callback: no delete button, and the heading still says nothing was changed.
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

from PySide6.QtCore import Qt
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


def _dialog(qtbot, records=None, navigate=None, delete_unselected=None):
    dialog = DifferentlyNamedDuplicatesDialog(
        None, records if records is not None else [_record()],
        navigate=navigate, delete_unselected=delete_unselected,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)
    return dialog


@pytest.fixture
def confirmed(monkeypatch):
    """Accept the delete confirmation, and record what it asked.

    Offscreen, `notifyConfirm` falls through to a console prompt that reads
    stdin, which pytest's capture makes an error, so any test that reaches the
    confirmation has to replace it.
    """
    from PyReconstruct.modules.gui.dialog import malformed_contours
    asked = []
    monkeypatch.setattr(
        malformed_contours, "notifyConfirm",
        lambda message, *a, **k: asked.append(message) or True,
    )
    return asked


def _tick(dialog, row, col):
    """Tick one of a row's two name cells, as a user click on it would."""
    dialog.table.item(row, col).setCheckState(Qt.Checked)


def _check_states(dialog, row):
    return tuple(
        dialog.table.item(row, col).checkState() for col in (0, 1)
    )


def test_no_delete_buttons_are_offered_without_a_callback(qtbot):
    """Report-only is still reachable: no callback, nothing to delete with."""
    dialog = _dialog(qtbot)
    texts = _button_texts(dialog)
    assert not any("Delete" in t for t in texts), texts
    assert dialog.delete_unselected is None
    assert dialog.delete_unselected_button is None
    # and the base class's own two are off regardless
    assert dialog.delete is None
    assert dialog.delete_selected_button is None
    assert dialog.delete_all_button is None
    assert "Nothing in the series has been changed." in dialog.heading.text()


def test_the_base_class_delete_buttons_never_appear(qtbot):
    """"Delete selected" and "Delete all" are the wrong two buttons here.

    Row selection is how a pair is inspected, not how it is answered, and "all"
    of a pairs list would mean deleting both sides. So the subclass passes no
    `delete` callback up to the base class even when it can delete, and the one
    button it does add is its own.
    """
    dialog = _dialog(qtbot, delete_unselected=lambda choices: [])
    texts = _button_texts(dialog)
    assert "Delete unselected" in texts
    assert "Delete selected" not in texts
    assert "Delete all" not in texts
    assert dialog.delete is None
    assert dialog.delete_selected_button is None
    assert dialog.delete_all_button is None


def test_no_row_starts_chosen(qtbot):
    """Nothing is inferred: both names of every row open unticked.

    A default here would be the tool answering the one question it cannot
    answer, so there is no default -- not even on a row where a heuristic would
    have an obvious pick.
    """
    records = [_record(), _record(name="BIG", other="small", section=7)]
    dialog = _dialog(qtbot, records, delete_unselected=lambda choices: [])
    for row in range(dialog.table.rowCount()):
        assert _check_states(dialog, row) == (Qt.Unchecked, Qt.Unchecked)
        assert dialog._choiceAtRow(row) is None
    assert dialog.chosenPairs() == []
    assert dialog.delete_unselected_button.isEnabled() is False


def test_the_two_names_of_a_row_are_mutually_exclusive(qtbot):
    """A row keeps one name or the other, never both."""
    dialog = _dialog(qtbot, delete_unselected=lambda choices: [])

    _tick(dialog, 0, 0)
    assert _check_states(dialog, 0) == (Qt.Checked, Qt.Unchecked)
    assert dialog._choiceAtRow(0)[1] == "first"

    _tick(dialog, 0, 1)
    assert _check_states(dialog, 0) == (Qt.Unchecked, Qt.Checked)
    assert dialog._choiceAtRow(0)[1] == "other"

    # unticking returns the row to unanswered rather than to the other name
    dialog.table.item(0, 1).setCheckState(Qt.Unchecked)
    assert _check_states(dialog, 0) == (Qt.Unchecked, Qt.Unchecked)
    assert dialog._choiceAtRow(0) is None


def test_only_the_answered_rows_reach_the_callback(qtbot, confirmed):
    """Unanswered rows are not handed over at all, so nothing can default them."""
    records = [_record(name="A1", other="A2", section=1),
               _record(name="B1", other="B2", section=2),
               _record(name="C1", other="C2", section=3)]
    handed = []
    dialog = _dialog(qtbot, records,
                     delete_unselected=lambda choices: handed.append(choices))

    rows = {
        dialog.table.item(r, 0).text(): r
        for r in range(dialog.table.rowCount())
    }
    _tick(dialog, rows["A1"], 0)   # keep A1, delete A2
    _tick(dialog, rows["C1"], 1)   # keep C2, delete C1
    # B is left alone
    dialog.deleteUnselectedTraces()

    assert len(handed) == 1
    assert [(record["name"], keep) for record, keep in handed[0]] == [
        ("A1", "first"), ("C1", "other")
    ]


def test_the_delete_button_turns_on_only_once_a_row_is_answered(qtbot):
    """Nothing to delete until a name is ticked; row selection is not a choice."""
    dialog = _dialog(qtbot, delete_unselected=lambda choices: [])
    button = dialog.delete_unselected_button
    assert button.isEnabled() is False

    # selecting the row is how you inspect a pair, not how you answer it
    dialog.table.selectRow(0)
    qtbot.wait(30)
    assert button.isEnabled() is False

    _tick(dialog, 0, 0)
    assert button.isEnabled() is True

    dialog.table.item(0, 0).setCheckState(Qt.Unchecked)
    assert button.isEnabled() is False


def test_answering_nothing_and_pressing_delete_does_nothing(qtbot):
    """The callback is not even reached, so there is nothing to default."""
    handed = []
    dialog = _dialog(qtbot,
                     delete_unselected=lambda choices: handed.append(choices))
    dialog.deleteUnselectedTraces()
    assert handed == []
    assert dialog.table.rowCount() == 1


def test_the_choice_survives_a_column_sort(qtbot):
    """Re-sorting must not shuffle answers onto the wrong pairs.

    This is why the choice is item check state rather than a radio button placed
    in the cell: check state is item data and travels with its row.
    """
    records = [_record(name="S9", other="S9b", section=9),
               _record(name="S2", other="S2b", section=2),
               _record(name="S5", other="S5b", section=5)]
    dialog = _dialog(qtbot, records, delete_unselected=lambda choices: [])

    rows = {
        dialog.table.item(r, 0).text(): r
        for r in range(dialog.table.rowCount())
    }
    _tick(dialog, rows["S9"], 1)    # keep S9b
    _tick(dialog, rows["S2"], 0)    # keep S2

    dialog.table.sortItems(0, Qt.DescendingOrder)
    qtbot.wait(30)

    answers = {
        dialog.table.item(r, 0).text(): dialog._choiceAtRow(r)
        for r in range(dialog.table.rowCount())
    }
    assert answers["S9"][1] == "other"
    assert answers["S2"][1] == "first"
    assert answers["S5"] is None
    # and each answer is still attached to its own record
    assert answers["S9"][0]["name"] == "S9"
    assert answers["S2"][0]["name"] == "S2"


def test_applied_rows_are_pruned_and_the_rest_stay(qtbot, confirmed):
    """Rows whose deletion went through leave the list; the rest are untouched."""
    records = [_record(name="GONE", other="KEPT", section=1),
               _record(name="LEFT", other="ALONE", section=2)]
    dialog = _dialog(
        qtbot, records,
        # the series applies the choice and reports back what it did
        delete_unselected=lambda choices: choices,
    )
    rows = {
        dialog.table.item(r, 0).text(): r
        for r in range(dialog.table.rowCount())
    }
    _tick(dialog, rows["GONE"], 1)
    dialog.deleteUnselectedTraces()

    remaining = [
        dialog.table.item(r, 0).text() for r in range(dialog.table.rowCount())
    ]
    assert remaining == ["LEFT"]
    assert [r["name"] for r in dialog.records] == ["LEFT"]
    assert dialog.delete_unselected_button.isEnabled() is False


def test_a_refused_deletion_leaves_its_row_in_place(qtbot, confirmed):
    """A callback that applied nothing (a locked object, say) prunes nothing."""
    dialog = _dialog(qtbot, delete_unselected=lambda choices: [])
    _tick(dialog, 0, 0)
    dialog.deleteUnselectedTraces()
    assert dialog.table.rowCount() == 1
    assert len(dialog.records) == 1


def test_the_confirmation_says_how_many_rows_were_left_alone(qtbot,
                                                             confirmed):
    """"Say what happened": the skipped count is stated, not silently dropped."""
    asked = confirmed
    records = [_record(name=f"P{i}", other=f"Q{i}", section=i)
               for i in range(4)]
    dialog = _dialog(qtbot, records, delete_unselected=lambda choices: [])
    _tick(dialog, 0, 0)
    dialog.deleteUnselectedTraces()

    assert len(asked) == 1
    assert "Delete 1 trace" in asked[0]
    assert "3 pairs were left alone" in asked[0]
    assert "Nothing is chosen for you." in asked[0]


def test_declining_the_confirmation_deletes_nothing(qtbot, monkeypatch):
    """The confirmation is a real gate, as it is for the other clean-up lists."""
    from PyReconstruct.modules.gui.dialog import malformed_contours
    monkeypatch.setattr(
        malformed_contours, "notifyConfirm", lambda *a, **k: False
    )
    handed = []
    dialog = _dialog(qtbot,
                     delete_unselected=lambda choices: handed.append(choices))
    _tick(dialog, 0, 0)
    dialog.deleteUnselectedTraces()
    assert handed == []
    assert dialog.table.rowCount() == 1


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


def test_the_heading_says_nothing_was_changed_when_it_cannot_delete(qtbot):
    """The one thing a reader must not get wrong about a report-only list."""
    dialog = _dialog(qtbot)
    heading = dialog.heading.text()
    assert "Nothing in the series has been changed." in heading
    assert "1 pair" in heading


def test_the_heading_says_the_choice_is_the_users(qtbot):
    """When it can delete, the heading has to say what a tick means and that
    an unticked row is left completely alone."""
    dialog = _dialog(qtbot, delete_unselected=lambda choices: [])
    heading = dialog.heading.text()
    assert "1 pair" in heading
    assert "the name you want to KEEP" in heading
    assert "left completely alone" in heading
    assert "nothing is chosen for you" in heading
    assert "Nothing in the series has been changed." not in heading
