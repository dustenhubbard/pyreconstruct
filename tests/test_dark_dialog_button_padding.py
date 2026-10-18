"""Dark-theme push buttons in dialogs are not drawn as tight boxes.

qdarkstyle pads every push button by 2 px, so a text button at its own size
(Help > View log file's Close) drew 40 px wide against the light theme's 64.
``qdark_addon`` pads dialog buttons 12 px left and right; a button box keeps
the 2 px, because it already widens its buttons to the style's minimum.
"""

import pytest

from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QPushButton, QWidget,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(["test"])


@pytest.fixture
def dark(qapp):
    import qdarkstyle
    from PyReconstruct.modules.gui.main.main_window import qdark_addon
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyside6() + qdark_addon)
    yield app
    app.setStyleSheet(previous)
    app.setPalette(app.style().standardPalette())


def _padding(button):
    """Width the button takes beyond its text."""
    return button.sizeHint().width() - button.fontMetrics().horizontalAdvance(button.text())


def test_a_loose_dialog_button_gets_room_beside_its_word(dark):
    dialog = QDialog()
    row = QHBoxLayout(dialog)
    close = QPushButton("Close", dialog)
    row.addStretch()
    row.addWidget(close)
    dialog.ensurePolished()
    close.ensurePolished()
    try:
        assert _padding(close) >= 24
    finally:
        dialog.deleteLater()


def _ok_hint(sheet):
    app = QApplication.instance()
    app.setStyleSheet(sheet)
    dialog = QDialog()
    box = QDialogButtonBox(QDialogButtonBox.Ok, dialog)
    ok = box.button(QDialogButtonBox.Ok)
    for w in (dialog, box, ok):
        w.ensurePolished()
    hint = ok.sizeHint()
    dialog.deleteLater()
    return hint


def test_a_button_box_and_a_window_button_keep_the_two_pixels(dark):
    import qdarkstyle
    from PyReconstruct.modules.gui.main.main_window import qdark_addon
    base = qdarkstyle.load_stylesheet_pyside6()
    plain = "".join(line + "\n" for line in qdark_addon.splitlines()
                    if not line.startswith("QDialog "))
    assert plain != qdark_addon
    assert _ok_hint(base + qdark_addon) == _ok_hint(base + plain)

    dark.setStyleSheet(base + qdark_addon)
    window = QWidget()
    loose = QPushButton("Zarr", window)
    window.ensurePolished()
    loose.ensurePolished()
    try:
        assert _padding(loose) < 12
    finally:
        window.deleteLater()
