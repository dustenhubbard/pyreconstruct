"""The duplicates list behind `Series ▸ Clean up ▸ Duplicates...`.

`DuplicateTracesDialog` is a real widget, driven here on the offscreen platform.
Each row is one structure traced more than once. Its Keep cell is a drop-down
of the row's own names, and the name picked there is the one combining keeps.

What is pinned here:

  * the menu has `Duplicates...` and neither of the two items it replaced, and
    the row reaches this operation's prompt
  * a row with one name has it picked; a row with more than one starts with
    none, and an unpicked row never reaches the callback
  * the drop-down lists exactly the row's names, and the pick is stored in
    the cell, so it survives a column sort
  * nothing reaches the callback until a Combine button is pressed and the
    confirmation accepted
  * combined rows go, refused rows stay, and the rows left on that section
    still point at their own traces
  * no Delete buttons, and the copied table includes the picked names
"""
import re

import pytest

pytestmark = pytest.mark.gui

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialogButtonBox

from conftest import menu_action, menu_leaf_paths, same_action

from PyReconstruct.modules.gui.dialog import (
    DuplicateTracesDialog,
    MalformedContoursDialog,
    PixelDustDialog,
)

MENU_PATH = "Series > Clean up > Duplicates..."


# ---------------------------------------------------------------------------
# the menu
# ---------------------------------------------------------------------------

def test_clean_up_has_duplicates_and_neither_old_item(main_window):
    paths = menu_leaf_paths(main_window.menubar)
    assert MENU_PATH in paths
    assert "Series > Clean up > Remove duplicate traces..." not in paths
    assert "Series > Clean up > Find duplicates named differently..." not in paths
    assert same_action(
        menu_action(main_window.menubar, MENU_PATH), main_window.duplicates_act
    )


def test_the_menu_row_reaches_this_operations_prompt(main_window,
                                                     main_window_dialogs):
    menu_action(main_window.menubar, MENU_PATH).trigger()
    assert main_window_dialogs.dialogs[-1] == "Duplicates"


def test_the_list_opens_wired_to_the_field_combine(main_window,
                                                   main_window_dialogs):
    """A planted pair under two names reaches the list, which combines through
    the field (save first, one undo state), not straight through the series."""
    from PyReconstruct.modules.datatypes.trace import Trace
    section = main_window.field.section
    for name in ("DUP_A", "DUP_B"):
        trace = Trace(name, (255, 0, 0), closed=True)
        trace.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        section.addTrace(trace, log_event=False)
    main_window_dialogs.responses = [
        ([0.95, [("check locked traces", False)]], True)
    ]

    main_window.reviewDuplicateTraces()

    dialog = main_window.duplicate_traces_dialog
    assert dialog.combine == main_window.field.combineDuplicateTraces
    assert dialog.navigate == main_window.field.focusMalformedContour
    assert any(
        g["names"] == ["DUP_A", "DUP_B"] and g["section"] == section.n
        for g in dialog.records
    )
    dialog.close()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _member(name, index, section=3, points=4):
    return {
        "name": name, "section": section, "index": index, "points": points,
        "location": (1.25, 2.5), "reason": "", "area": 0.5,
        "match": {"color": [1, 2, 3], "points": [(0.0, 0.0)]},
        "identity": ("i", name, index), "lookalikes": 1,
        "lookalike_ordinal": 0,
    }


def _group(*members, section=3, ratio=0.97):
    members = [
        _member(name, index, section) for name, index in members
    ]
    return {
        "section": section,
        "members": members,
        "names": sorted({m["name"] for m in members}),
        "count": len(members),
        "ratio": ratio,
        "location": members[0]["location"],
    }


def _without_mnemonic(text):
    return re.sub(r"&(.)", r"\1", text)


def _button_texts(dialog):
    box = dialog.findChild(QDialogButtonBox)
    return [_without_mnemonic(b.text()) for b in box.buttons()]


def _dialog(qtbot, groups, navigate=None, combine=None):
    dialog = DuplicateTracesDialog(
        None, groups, navigate=navigate, combine=combine,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(30)
    return dialog


def _row_of(dialog, group):
    for row in range(dialog.table.rowCount()):
        if dialog._recordAtRow(row) is group:
            return row
    raise AssertionError("group not in the table")


def _combo(dialog, row):
    combo = dialog.table.indexWidget(dialog.table.model().index(row, 0))
    assert isinstance(combo, QComboBox), "no drop-down in the Keep cell"
    return combo


def _pick(dialog, group, name):
    """Pick a name in a row's drop-down, as a user would."""
    combo = _combo(dialog, _row_of(dialog, group))
    combo.setCurrentIndex(combo.findText(name))
    QApplication.processEvents()


def _shown(dialog, group):
    """The name a row's drop-down shows, or "" for none."""
    combo = _combo(dialog, _row_of(dialog, group))
    return combo.currentText() if combo.currentIndex() >= 0 else ""


@pytest.fixture
def confirmed(monkeypatch):
    """Accept the combine confirmation, and record what it asked."""
    from PyReconstruct.modules.gui.dialog import malformed_contours
    asked = []
    monkeypatch.setattr(
        malformed_contours, "notifyConfirm",
        lambda message, *a, **k: asked.append(message) or True,
    )
    return asked


class _Combine:
    """A combine callback that records its calls and applies a chosen few."""

    def __init__(self, refuse=()):
        self.calls = []
        self.refuse = refuse

    def __call__(self, choices):
        self.calls.append(list(choices))
        return [c for c in choices if c[0] not in self.refuse]


# ---------------------------------------------------------------------------
# the Keep drop-down
# ---------------------------------------------------------------------------

def test_a_row_with_one_name_has_it_picked(qtbot):
    same = _group(("A", 0), ("A", 1))
    dialog = _dialog(qtbot, [same], combine=_Combine())
    assert _shown(dialog, same) == "A"


def test_a_row_with_several_names_starts_with_none(qtbot):
    cross = _group(("A", 0), ("B", 0))
    dialog = _dialog(qtbot, [cross], combine=_Combine())
    assert _shown(dialog, cross) == ""
    assert dialog.choices() == []


def test_the_drop_down_lists_exactly_the_rows_names(qtbot):
    cross = _group(("A", 0), ("A", 1), ("C", 0), ("B", 2))
    dialog = _dialog(qtbot, [cross], combine=_Combine())
    combo = _combo(dialog, 0)
    assert [combo.itemText(i) for i in range(combo.count())] == ["A", "B", "C"]


def test_the_pick_survives_a_column_sort(qtbot):
    first = _group(("A", 0), ("B", 0), section=1)
    second = _group(("C", 0), ("D", 0), section=2)
    third = _group(("E", 0), ("F", 0), section=3)
    dialog = _dialog(qtbot, [first, second, third], combine=_Combine())
    _pick(dialog, first, "B")
    _pick(dialog, third, "E")

    dialog.table.sortItems(2, Qt.DescendingOrder)
    QApplication.processEvents()

    assert _shown(dialog, first) == "B"
    assert _shown(dialog, second) == ""
    assert _shown(dialog, third) == "E"
    assert {(id(g), k) for g, k in dialog.choices()} == {
        (id(first), "B"), (id(third), "E"),
    }


def test_the_mouse_wheel_never_changes_a_pick(qtbot):
    """Scrolling the list over a drop-down leaves its pick alone."""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    cross = _group(("A", 0), ("B", 0), ("C", 0))
    dialog = _dialog(qtbot, [cross], combine=_Combine())
    _pick(dialog, cross, "B")
    combo = _combo(dialog, 0)

    # one turn down: a plain combo box on this style moves to "C"
    event = QWheelEvent(
        QPointF(5, 5), QPointF(combo.mapToGlobal(QPoint(5, 5))),
        QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
        Qt.NoScrollPhase, False,
    )
    QApplication.sendEvent(combo, event)
    QApplication.processEvents()

    assert _shown(dialog, cross) == "B"


# ---------------------------------------------------------------------------
# combining
# ---------------------------------------------------------------------------

def test_no_delete_buttons_and_two_combine_buttons(qtbot):
    dialog = _dialog(qtbot, [_group(("A", 0), ("B", 0))], combine=_Combine())
    texts = _button_texts(dialog)
    assert "Combine selected" in texts
    assert "Combine all" in texts
    assert "Delete selected" not in texts
    assert "Delete all" not in texts


def test_without_a_callback_there_is_nothing_to_combine_with(qtbot):
    dialog = _dialog(qtbot, [_group(("A", 0), ("B", 0))])
    texts = _button_texts(dialog)
    assert "Combine selected" not in texts
    assert "Combine all" not in texts


def test_picking_names_changes_nothing(qtbot):
    cross = _group(("A", 0), ("B", 0))
    combine = _Combine()
    dialog = _dialog(qtbot, [cross], combine=combine)
    _pick(dialog, cross, "A")
    _pick(dialog, cross, "B")
    assert combine.calls == []


def test_combine_all_hands_over_only_the_picked_rows(qtbot, confirmed):
    same = _group(("A", 0), ("A", 1), section=1)
    picked = _group(("B", 0), ("C", 0), section=2)
    unpicked = _group(("D", 0), ("E", 0), section=3)
    combine = _Combine()
    dialog = _dialog(qtbot, [same, picked, unpicked], combine=combine)
    _pick(dialog, picked, "C")

    dialog.combine_all_button.click()

    assert len(combine.calls) == 1
    assert {(id(g), k) for g, k in combine.calls[0]} == {
        (id(same), "A"), (id(picked), "C"),
    }
    assert "1 row was left alone because no name is picked" in confirmed[0]


def test_combine_selected_hands_over_only_the_selected_rows(qtbot, confirmed):
    first = _group(("A", 0), ("A", 1), section=1)
    second = _group(("B", 0), ("B", 1), section=2)
    combine = _Combine()
    dialog = _dialog(qtbot, [first, second], combine=combine)
    dialog.table.selectRow(_row_of(dialog, second))

    dialog.combine_selected_button.click()

    assert combine.calls == [[(second, "B")]]


def test_the_combine_buttons_wait_for_a_pick(qtbot):
    cross = _group(("A", 0), ("B", 0))
    dialog = _dialog(qtbot, [cross], combine=_Combine())
    assert not dialog.combine_all_button.isEnabled()
    dialog.table.selectRow(0)
    assert not dialog.combine_selected_button.isEnabled()

    _pick(dialog, cross, "B")

    assert dialog.combine_all_button.isEnabled()
    assert dialog.combine_selected_button.isEnabled()


def test_declining_the_confirmation_combines_nothing(qtbot, monkeypatch):
    from PyReconstruct.modules.gui.dialog import malformed_contours
    monkeypatch.setattr(
        malformed_contours, "notifyConfirm", lambda *a, **k: False
    )
    combine = _Combine()
    dialog = _dialog(qtbot, [_group(("A", 0), ("A", 1))], combine=combine)
    dialog.combine_all_button.click()
    assert combine.calls == []
    assert dialog.table.rowCount() == 1


def test_combined_rows_go_and_refused_rows_stay(qtbot, confirmed):
    done = _group(("A", 0), ("A", 1), section=1)
    refused = _group(("B", 0), ("B", 1), section=2)
    dialog = _dialog(qtbot, [done, refused],
                     combine=_Combine(refuse=(refused,)))

    dialog.combine_all_button.click()

    assert dialog.records == [refused]
    assert dialog.table.rowCount() == 1
    assert dialog._recordAtRow(0) is refused


def test_the_heading_says_when_every_row_is_combined(qtbot, confirmed):
    dialog = _dialog(qtbot, [_group(("A", 0), ("A", 1))], combine=_Combine())
    dialog.combine_all_button.click()
    assert dialog.heading.text().startswith("Every row has been combined.")


def test_rows_left_on_the_section_still_point_at_their_traces(qtbot,
                                                             confirmed):
    """Combining `A`[0] and `A`[1] keeps `A`[0] and deletes `A`[1], so a later
    `A`[3] on that section is now `A`[2]. Another section is untouched."""
    done = _group(("A", 0), ("A", 1), section=1)
    later = _group(("A", 3), ("B", 0), section=1)
    elsewhere = _group(("A", 3), ("B", 0), section=2)
    dialog = _dialog(qtbot, [done, later, elsewhere],
                     combine=_Combine(refuse=(later, elsewhere)))

    dialog.table.selectRow(_row_of(dialog, done))
    dialog.combine_selected_button.click()

    assert [m["index"] for m in later["members"]] == [2, 0]
    assert [m["index"] for m in elsewhere["members"]] == [3, 0]


# ---------------------------------------------------------------------------
# going to a row, and the copied table
# ---------------------------------------------------------------------------

def test_go_to_trace_frames_the_trace_to_keep(qtbot):
    cross = _group(("A", 0), ("B", 4), section=7)
    went = []
    dialog = _dialog(qtbot, [cross], navigate=lambda *a: went.append(a),
                     combine=_Combine())
    dialog.table.selectRow(0)

    dialog.goto_button.click()
    _pick(dialog, cross, "B")
    dialog.goto_button.click()

    assert went == [(7, "A", 0), (7, "B", 4)]


def test_the_copied_table_carries_the_picked_names(qtbot):
    cross = _group(("A", 0), ("B", 0))
    dialog = _dialog(qtbot, [cross], combine=_Combine())
    _pick(dialog, cross, "B")

    dialog.copyToClipboard()

    header, row = QApplication.clipboard().text().splitlines()
    assert header.split("\t") == list(DuplicateTracesDialog.COLUMNS)
    assert row.split("\t")[:4] == ["B", "A, B", "3", "2"]


def test_the_heading_explains_the_pick_and_the_undo(qtbot):
    dialog = _dialog(qtbot, [_group(("A", 0), ("B", 0))], combine=_Combine())
    heading = dialog.heading.text()
    assert "Pick the name to keep in each row." in heading
    assert "adds the tags of the other traces to it" in heading
    assert "Nothing changes until you combine" in heading


# ---------------------------------------------------------------------------
# the shared base class
# ---------------------------------------------------------------------------

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
    assert dialog.extra_buttons == []


def test_base_dialog_grows_no_extra_button(qtbot):
    """The extra-button hook is opt-in: the smoothing report is unchanged."""
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
    box = dialog.findChild(QDialogButtonBox)
    assert box.standardButtons() == QDialogButtonBox.Close
    assert _button_texts(dialog) == ["Close", "Go to trace", "Copy table list",
                                     "Save table as CSV…"]
