"""A docked list must scroll to its last row.

Reported 2026-08-26: docked, a list sometimes could not scroll all the way
down, hiding the last row or two; undocking showed every row. The cause was
an old resizeEvent override sizing the table by hand to the DOCK's height
minus a guessed 20px, past the space under the list's own menu bar. The
table is the internal window's central widget, so the layout owns its size;
the override is gone and this pins the table inside its window.
"""

import pytest

pytestmark = pytest.mark.gui


def test_docked_table_never_overflows_its_viewport(qapp, section_table):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMainWindow, QWidget

    window = QMainWindow()
    window.setCentralWidget(QWidget())
    window.resize(1200, 800)
    window.addDockWidget(Qt.LeftDockWidgetArea, section_table)
    window.show()
    for _ in range(6):
        qapp.processEvents()
    try:
        body = section_table.main_widget
        inner = section_table.table
        assert inner.geometry().bottom() <= body.rect().bottom()
        assert inner.geometry().top() >= body.menuBar().height() - 1

        window.resize(900, 500)          # and after a dock resize
        for _ in range(6):
            qapp.processEvents()
        assert inner.geometry().bottom() <= body.rect().bottom()
    finally:
        window.close()
        window.deleteLater()
