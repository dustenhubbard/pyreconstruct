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


@pytest.mark.gui
def test_a_deleted_main_window_is_no_longer_the_main_window(qapp):
    from PyReconstruct.modules.gui.utils import utils

    before = _top_level_widgets()
    window = QWidget()
    utils.setMainWindow(window)

    delete_new_top_level_widgets(before)

    assert utils.mainwindow is None


@pytest.mark.gui
def test_a_new_window_at_a_deleted_window_s_address_is_deleted(qapp):
    from PySide6.QtTest import QTest
    from shiboken6 import getCppPointer

    window = QWidget()
    before = _top_level_widgets()
    address = getCppPointer(window)[0]
    window.deleteLater()
    QTest.qWait(0)
    assert not isValid(window)
    for _ in range(1000):
        made = QWidget()
        if getCppPointer(made)[0] == address:
            break
        made.deleteLater()
        QTest.qWait(0)
    else:
        pytest.fail("Qt never reused the deleted window's address")

    delete_new_top_level_widgets(before)

    assert not isValid(made)
