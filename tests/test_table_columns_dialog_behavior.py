"""Column moves preserve enabled states and leave the caller's list alone."""

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox

from PyReconstruct.modules.gui.dialog.table_columns import TableColumnsDialog

pytestmark = pytest.mark.gui


def test_reorder_then_toggle_returns_the_visible_column_order(qtbot):
    original = [("Tags", True), ("Hidden", False), ("Length", True)]
    dialog = TableColumnsDialog(None, original)
    qtbot.addWidget(dialog)
    dialog.moveRow(0, up=True)
    dialog.moveRow(2, up=False)
    assert dialog.columns == [("Tags", True), ("Hidden", False), ("Length", True)]

    dialog.moveRow(1, up=True)
    boxes = dialog.columns_widget.findChildren(QCheckBox)
    assert [(box.text(), box.isChecked()) for box in boxes] == [
        ("Hidden", False), ("Tags", True), ("Length", True)
    ]
    boxes[0].click()
    dialog.moveRow(1, up=False)
    QTimer.singleShot(0, dialog.accept)
    assert dialog.exec() == ([("Hidden", True), ("Length", True), ("Tags", True)], True)
    assert original == [("Tags", True), ("Hidden", False), ("Length", True)]


def test_cancel_discards_reorder_and_checkbox_edits(qtbot):
    original = [("Tags", True), ("Hidden", False)]
    dialog = TableColumnsDialog(None, original)
    qtbot.addWidget(dialog)
    dialog.columns_widget.findChildren(QCheckBox)[0].click()
    dialog.moveRow(0, up=False)
    QTimer.singleShot(0, dialog.reject)
    assert dialog.exec() == (None, False)
    assert original == [("Tags", True), ("Hidden", False)]
