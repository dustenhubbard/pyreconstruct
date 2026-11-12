"""A top-level widget a test leaves behind is deleted before the next test.

`tests/conftest.py` explains why: windows only queued for deletion pile up
until a later event loop deletes them all, and under PySide6 6.9 that batch
grows with the square of the pile.
"""
import pytest
from shiboken6 import isValid
from PySide6.QtWidgets import QPushButton, QWidget

from conftest import _top_level_widgets, delete_new_top_level_widgets


@pytest.mark.gui
def test_a_closed_window_queued_for_deletion_is_gone(qapp):
    before = _top_level_widgets()
    window = QWidget()
    QPushButton(window).clicked.connect(lambda: None)
    window.show()
    window.close()
    qapp.processEvents()  # runs no deferred delete
    assert isValid(window)

    delete_new_top_level_widgets(before)

    assert not isValid(window)


@pytest.mark.gui
def test_a_window_made_before_is_kept(qapp):
    window = QWidget()
    before = _top_level_widgets()
    made = QWidget()

    delete_new_top_level_widgets(before)

    assert isValid(window)
    assert not isValid(made)
