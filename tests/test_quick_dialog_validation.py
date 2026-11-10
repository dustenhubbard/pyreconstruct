"""Invalid dialog input can be corrected without accepting partial responses."""

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from PyReconstruct.modules.gui.dialog import quick_dialog
from PyReconstruct.modules.gui.dialog.quick_dialog import QuickDialog, QuickTabDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def notices(monkeypatch):
    messages = []
    monkeypatch.setattr(quick_dialog, "notify", messages.append)
    return messages


@pytest.mark.parametrize(
    ("field", "invalid", "corrected", "expected", "message"),
    [
        ((True, "text", ""), "", "cell2", "cell2", "Please enter a response."),
        ((True, "textbox", ""), "", "first\nsecond", "first\nsecond", "Please enter a response."),
        ((True, "int", None), "", "4", 4, "Please enter an integer."),
        ((True, "int", 1), "1.5", "2", 2, "Please enter a valid integer."),
        ((True, "int", 1, [1, 3]), "2", "3", 3, "Please enter a valid integer."),
        ((True, "float", None), "", "2.5", 2.5, "Please enter a number."),
        ((True, "float", 1), "two", "2.5", 2.5, "Please enter a valid number."),
        ((True, "float", 1, [1, 3]), "0.9", "1", 1.0, "Please enter a valid number."),
        ((True, "float", 1, [1, 3]), "3.1", "3", 3.0, "Please enter a valid number."),
    ],
)
def test_invalid_input_then_correction(qtbot, notices, field, invalid, corrected, expected, message):
    dialog = QuickDialog(None, [[field]], "Edit value")
    qtbot.addWidget(dialog)
    widget = dialog.inputs[0].widget
    set_text = widget.setPlainText if field[1] == "textbox" else widget.setText
    set_text(invalid)

    assert dialog.accept(close=False) is False
    assert notices == [message]
    assert dialog.result() == QDialog.Rejected

    set_text(corrected)
    assert dialog.accept(close=False) is True
    assert dialog.responses == (expected,)


def test_optional_blank_numbers_remain_distinct_from_zero(qtbot, notices):
    dialog = QuickDialog(None, [[("int", 7), ("float", 2.5)]], "Optional values")
    qtbot.addWidget(dialog)
    for field in dialog.inputs:
        field.widget.clear()
    assert dialog.accept(close=False) is True
    assert dialog.responses == (None, None)

    for field in dialog.inputs:
        field.widget.setText("0")
    assert dialog.accept(close=False) is True
    assert dialog.responses == (0, 0.0)
    assert notices == []


def test_combo_keeps_a_valid_choice_when_unknown_text_is_refused(qtbot, notices):
    dialog = QuickDialog(None, [[(True, "combo", ["rough", "final"])]], "Choose")
    qtbot.addWidget(dialog)
    combo = dialog.inputs[0].widget
    combo.setCurrentText("final")
    combo.setEditText("missing")
    assert dialog.accept(close=False) is True
    assert dialog.responses == ("final",)
    assert notices == []


def test_required_combo_needs_a_selection(qtbot, notices):
    dialog = QuickDialog(None, [[(True, "combo", ["rough", "final"])]], "Choose")
    qtbot.addWidget(dialog)
    assert dialog.accept(close=False) is False
    assert notices == ["Please select a field from the dropdown menu."]
    dialog.inputs[0].widget.setCurrentText("rough")
    assert dialog.accept(close=False) is True
    assert dialog.responses == ("rough",)


@pytest.mark.parametrize("kind", ["multitext", "multicombo"])
def test_required_multiinput_cannot_be_empty(qtbot, notices, kind):
    params = (True, kind, []) if kind == "multitext" else (True, kind, ["keep", "review"], [])
    dialog = QuickDialog(None, [[params]], "Tags")
    qtbot.addWidget(dialog)
    assert dialog.accept(close=False) is False
    assert notices == ["Please enter a response."]
    row = dialog.inputs[0].widget.inputs[0]
    if kind == "multitext":
        row.setText("keep")
    else:
        row.setCurrentText("keep")
    assert dialog.accept(close=False) is True
    assert dialog.responses == (["keep"],)


@pytest.mark.parametrize("restricted", [True, False])
def test_multicombo_can_restrict_entries_to_its_vocabulary(qtbot, notices, restricted):
    dialog = QuickDialog(
        None, [[("multicombo", ["keep", "review"], ["custom"], restricted)]], "Tags"
    )
    qtbot.addWidget(dialog)
    assert dialog.accept(close=False) is (not restricted)
    if restricted:
        assert notices == ["Please enter a valid response from the drop-down menu."]
        dialog.inputs[0].widget.inputs[0].setCurrentText("review")
        assert dialog.accept(close=False) is True
        assert dialog.responses == (["review"],)
    else:
        assert dialog.responses == (["custom"],)


def test_tab_dialog_validates_other_tabs_before_accepting(qtbot, notices):
    dialog = QuickTabDialog(None, {
        "Name": [[(True, "text", "cell2")]],
        "Count": [[(True, "int", None, [1, 2, 3])]],
    })
    qtbot.addWidget(dialog)
    button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
    button.click()
    assert dialog.result() == QDialog.Rejected
    assert notices == ["Please enter an integer."]

    dialog.inputs["Count"][0].widget.setText("2")
    button.click()
    assert dialog.result() == QDialog.Accepted
    assert dialog.responses == {"Name": ["cell2"], "Count": [2]}


def test_cancel_returns_no_response_even_with_edited_fields(qtbot):
    dialog = QuickDialog(None, [[("text", "before")]], "Edit")
    qtbot.addWidget(dialog)
    dialog.inputs[0].widget.setText("after")
    QTimer.singleShot(0, dialog.reject)
    assert dialog.exec() == (None, False)
