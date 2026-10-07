"""Clicking the Object List's 3D box adds the object to the 3D scene or
removes it (issue #780).

Driven on the real ObjectTableWidget over the checked-in series, with a real
mouse click on the box. The click runs the same main window calls as the
`3D` menu's `Add to scene` and `Remove from scene` (``mainwindow.addTo3D`` and
``mainwindow.removeFrom3D``, which the field's ``addTo3D`` and ``remove3D``
call for the selected names). The box itself never stores the click: it is
read from the scene, so it changes only when the scene does.
"""

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from tests.test_data_lists_real_widget import MenuStubField, StubListManager

pytestmark = pytest.mark.gui


class FakeViewer:
    """The one CustomPlotter method the 3D column reads."""

    def __init__(self, series_fp):
        self.series_fp = series_fp
        self.scene = set()

    def inScene(self, name, series_fp):
        return series_fp == self.series_fp and name in self.scene


@pytest.fixture
def object_list(qapp, stub_mainwindow, gui_dialogs):
    from PyReconstruct.modules.gui.table.object import ObjectTableWidget

    mainwindow = stub_mainwindow
    series = mainwindow.series
    mainwindow.field = MenuStubField(series, series.loadSection(sorted(series.sections)[0]))
    mainwindow.viewer = FakeViewer(series.jser_fp)
    mainwindow.calls = []
    mainwindow.addTo3D = lambda names, ztraces=False: mainwindow.calls.append(("add", list(names)))
    mainwindow.removeFrom3D = lambda obj_names, ztraces=None: mainwindow.calls.append(("remove", list(obj_names)))

    widget = ObjectTableWidget(series, mainwindow, StubListManager())
    widget.resize(900, 400)
    widget.show()
    QApplication.processEvents()
    yield widget
    widget.deleteLater()


def _box(widget, row):
    col = widget.horizontal_headers.index("3D")
    return widget.model.index(row, col)


def _state(widget, row):
    return Qt.CheckState(widget.model.data(_box(widget, row), Qt.CheckStateRole))


def _click(widget, row):
    view = widget.table
    view.scrollTo(_box(widget, row))
    rect = view.visualRect(_box(widget, row))
    assert rect.isValid(), "the 3D column is not on screen"
    pos = QPointF(rect.left() + 8, rect.center().y())
    vp = view.viewport()
    global_pos = QPointF(vp.mapToGlobal(pos.toPoint()))
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        QApplication.sendEvent(
            vp,
            QMouseEvent(kind, pos, global_pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier),
        )
    QApplication.processEvents()


def test_3d_box_is_user_checkable(object_list):
    flags = object_list.model.flags(_box(object_list, 0))
    assert flags & Qt.ItemFlag.ItemIsUserCheckable
    assert flags & Qt.ItemFlag.ItemIsEnabled


def test_clicking_an_empty_box_adds_the_object(object_list):
    name = object_list.model.nameAt(0)
    assert _state(object_list, 0) == Qt.CheckState.Unchecked

    _click(object_list, 0)

    assert object_list.mainwindow.calls == [("add", [name])]


def test_clicking_a_checked_box_removes_the_object(object_list):
    name = object_list.model.nameAt(1)
    object_list.mainwindow.viewer.scene.add(name)
    object_list.updateData([name])
    assert _state(object_list, 1) == Qt.CheckState.Checked

    _click(object_list, 1)

    assert object_list.mainwindow.calls == [("remove", [name])]


def test_box_follows_the_scene_not_the_click(object_list):
    """Meshes are built on a thread, so the box stays empty until the object
    is in the scene, and checks once the scene refresh arrives."""
    name = object_list.model.nameAt(0)

    _click(object_list, 0)
    assert _state(object_list, 0) == Qt.CheckState.Unchecked

    object_list.mainwindow.viewer.scene.add(name)
    object_list.updateData([name])
    assert _state(object_list, 0) == Qt.CheckState.Checked


def test_click_acts_on_the_clicked_object_only(object_list):
    """With other rows selected, the click still adds just its own row."""
    from PySide6.QtCore import QItemSelection, QItemSelectionModel

    model = object_list.model
    selection = QItemSelection()
    for row in (1, 2):
        selection.select(model.index(row, 0), model.index(row, model.columnCount() - 1))
    object_list.table.selectionModel().select(
        selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
    )

    _click(object_list, 0)

    assert object_list.mainwindow.calls == [("add", [model.nameAt(0)])]


def test_no_viewer_still_adds(object_list):
    """With no 3D window open the box is empty, and a click opens one through
    the same addTo3D call."""
    object_list.mainwindow.viewer = None
    object_list.updateData([object_list.model.nameAt(0)])

    _click(object_list, 0)

    assert object_list.mainwindow.calls == [("add", [object_list.model.nameAt(0)])]
