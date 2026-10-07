"""The Object List's 3D column marks the objects that are in the 3D scene.

Pinned here, without opening a VTK window:

1. The column is a default object column, shown, so existing series pick it
   up through DataTable's missing-default merge.
2. ``ObjectTableWidget.getItems("3D")`` reads membership from the live viewer:
   checked when the object is in the scene, unchecked with no viewer, a
   closed viewer, or an object from another series. Clicking the box is
   pinned in ``test_object_list_3d_click.py``.
3. Every scene change reaches the list: ``VPlotter.placeInScene`` (the end of
   every add), ``VPlotter.removeSceneObj`` (every remove, clear, undo, and
   stale refresh), and ``CustomPlotter.closeEvent``.
4. ``TableManager.updateSceneMarks`` refreshes the object lists only and does
   not mark the scene stale (that would regenerate the meshes just added).
5. End to end on the real updateData path: a row's 3D box flips when the scene
   gains or loses the object.
6. A new viewer is already ``mainwindow.viewer`` when its first meshes land,
   so the first batch added from a fresh 3D window is marked.
"""
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from PyReconstruct.modules.backend.table.manager import TableManager
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.gui.popup import custom_plotter as cp
from PyReconstruct.modules.gui.popup.custom_plotter import (
    CustomPlotter,
    SceneObjectList,
    VPlotter,
)
from PyReconstruct.modules.gui.table.object import ObjectTableWidget
from PyReconstruct.modules.gui.table.object_model import ObjectTableModel
from PyReconstruct.modules.gui.utils import sortList


SERIES_FP = "/tmp/current.jser"
OTHER_FP = "/tmp/other.jser"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(["test"])


def _scene(*entries):
    """A SceneObjectList holding (name, type, series_fp) entries."""
    objs = SceneObjectList()
    for name, type_str, fp in entries:
        objs.add(
            SimpleNamespace(metadata={}),
            SimpleNamespace(jser_fp=fp, host_tree=None),
            name, type_str, (255, 0, 0), 1.0,
        )
    return objs


def _viewer(objs, is_closed=False):
    """A CustomPlotter shell with a scene and no window."""
    viewer = CustomPlotter.__new__(CustomPlotter)
    viewer.is_closed = is_closed
    viewer.plt = SimpleNamespace(objs=objs)
    return viewer


# --------------------------------------------------------------------------- #
# 1. Default column                                                            #
# --------------------------------------------------------------------------- #

def test_3d_is_a_shown_default_object_column():
    defaults = dict(Series.getEmptyDict()["options"]["object_columns"])
    assert defaults.get("3D") is True


# --------------------------------------------------------------------------- #
# 2. getItems reads the live scene                                             #
# --------------------------------------------------------------------------- #

def _items_source(viewer, names=("d001", "d002")):
    return SimpleNamespace(
        series=SimpleNamespace(
            jser_fp=SERIES_FP,
            data={"objects": {n: None for n in names}},
            user_columns={},
        ),
        mainwindow=SimpleNamespace(viewer=viewer),
    )


def _mark(source, name):
    (item,) = ObjectTableWidget.getItems(source, name, "3D")
    return item


def test_object_in_scene_is_checked(qapp):
    source = _items_source(_viewer(_scene(("d001", "object", SERIES_FP))))
    assert _mark(source, "d001").checkState() == Qt.CheckState.Checked
    assert _mark(source, "d002").checkState() == Qt.CheckState.Unchecked


def test_no_viewer_is_unchecked(qapp):
    source = _items_source(None)
    assert _mark(source, "d001").checkState() == Qt.CheckState.Unchecked


def test_closed_viewer_is_unchecked(qapp):
    viewer = _viewer(_scene(("d001", "object", SERIES_FP)), is_closed=True)
    source = _items_source(viewer)
    assert _mark(source, "d001").checkState() == Qt.CheckState.Unchecked


def test_same_name_from_another_series_or_a_ztrace_is_unchecked(qapp):
    viewer = _viewer(_scene(
        ("d001", "object", OTHER_FP),
        ("d002", "ztrace", SERIES_FP),
    ))
    source = _items_source(viewer)
    assert _mark(source, "d001").checkState() == Qt.CheckState.Unchecked
    assert _mark(source, "d002").checkState() == Qt.CheckState.Unchecked


# --------------------------------------------------------------------------- #
# 3. Scene changes reach the list                                              #
# --------------------------------------------------------------------------- #

def _plotter(objs):
    plt = VPlotter.__new__(VPlotter)
    plt.objs = objs
    plt.selected = []
    # the plotter reads its series off the main window
    plt.mainwindow = SimpleNamespace(
        series=SimpleNamespace(jser_fp=SERIES_FP, host_tree=None)
    )
    plt.qt_parent = mock.Mock()
    plt.remove = lambda msh: None
    plt.add = lambda msh: None
    plt.render = lambda: None
    return plt


def test_placing_meshes_notifies_the_list():
    plt = _plotter(SceneObjectList())
    triangle = {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        "faces": [[0, 1, 2]],
        "color": (255, 0, 0),
        "alpha": 1.0,
        "tform": None,
    }
    plt.placeInScene((
        [dict(triangle, name="d001", type="object")],
        plt.series,
    ))
    plt.qt_parent.updateObjectList.assert_called_once()
    (placed,), _ = plt.qt_parent.updateObjectList.call_args
    assert [o.name for o in placed] == ["d001"]
    assert placed[0] is plt.objs.search("d001", "object", SERIES_FP)


def test_removing_a_scene_object_notifies_the_list():
    objs = _scene(("d001", "object", SERIES_FP))
    plt = _plotter(objs)
    scene_obj = objs.search("d001", "object", SERIES_FP)
    plt.removeSceneObj(scene_obj)
    plt.qt_parent.updateObjectList.assert_called_once_with([scene_obj])
    assert objs.search("d001", "object", SERIES_FP) is None


def test_clearing_the_scene_notifies_for_each_object():
    objs = _scene(("d001", "object", SERIES_FP), ("d002", "object", SERIES_FP))
    plt = _plotter(objs)
    plt.clear()
    notified = [
        o.name
        for call in plt.qt_parent.updateObjectList.call_args_list
        for o in call.args[0]
    ]
    assert sorted(notified) == ["d001", "d002"]


def test_update_object_list_sends_object_names_only():
    viewer = _viewer(_scene(
        ("d001", "object", SERIES_FP),
        ("zt1", "ztrace", SERIES_FP),
        ("Scale Cube", "scale_cube", SERIES_FP),
    ))
    manager = mock.Mock()
    viewer.mainwindow = SimpleNamespace(field=SimpleNamespace(table_manager=manager))
    viewer.updateObjectList(list(viewer.plt.objs.values()))
    manager.updateSceneMarks.assert_called_once_with(["d001"])


def test_update_object_list_skips_a_scene_with_no_objects():
    viewer = _viewer(_scene(("zt1", "ztrace", SERIES_FP)))
    manager = mock.Mock()
    viewer.mainwindow = SimpleNamespace(field=SimpleNamespace(table_manager=manager))
    viewer.updateObjectList(list(viewer.plt.objs.values()))
    manager.updateSceneMarks.assert_not_called()


def test_update_object_list_without_a_field_is_a_noop():
    viewer = _viewer(_scene(("d001", "object", SERIES_FP)))
    viewer.mainwindow = SimpleNamespace(field=None)
    viewer.updateObjectList(list(viewer.plt.objs.values()))  # must not raise


def test_closing_the_viewer_clears_every_mark():
    objs = _scene(("d001", "object", SERIES_FP), ("d002", "object", SERIES_FP))
    viewer = _viewer(objs)
    viewer.plt = SimpleNamespace(objs=objs, close=lambda: None)
    viewer.container = object()
    seen = {}

    def record(names):
        # the list re-reads the viewer while refreshing, so the viewer must
        # already answer "not in the scene" when the refresh arrives
        seen["names"] = sorted(names)
        seen["in_scene"] = [viewer.inScene(n, SERIES_FP) for n in names]

    manager = SimpleNamespace(updateSceneMarks=record)
    viewer.mainwindow = SimpleNamespace(field=SimpleNamespace(table_manager=manager))
    with mock.patch.object(cp.QVTKRenderWindowInteractor, "closeEvent"):
        viewer.closeEvent(None)
    assert seen == {"names": ["d001", "d002"], "in_scene": [False, False]}


# --------------------------------------------------------------------------- #
# 4. TableManager.updateSceneMarks                                             #
# --------------------------------------------------------------------------- #

def test_update_scene_marks_refreshes_object_lists_without_marking_stale():
    viewer = mock.Mock(is_closed=False)
    mainwindow = SimpleNamespace(viewer=viewer)
    manager = TableManager(SimpleNamespace(), SimpleNamespace(), None, mainwindow)
    object_list = mock.Mock()
    trace_list = mock.Mock()
    manager.tables["object"].append(object_list)
    manager.tables["trace"].append(trace_list)

    manager.updateSceneMarks(["d001"])

    object_list.updateData.assert_called_once_with(["d001"])
    trace_list.updateData.assert_not_called()
    viewer.markStale.assert_not_called()
    viewer.markAllStale.assert_not_called()


# --------------------------------------------------------------------------- #
# 5. End to end on the real updateData path                                    #
# --------------------------------------------------------------------------- #

class _ListSource:
    """The object list's model contract on its real getItems and updateData."""

    getItems = ObjectTableWidget.getItems
    getHeaders = ObjectTableWidget.getHeaders
    updateData = ObjectTableWidget.updateData

    def __init__(self, names, viewer):
        self.static_columns = ["Name"]
        self.columns = [("3D", True)]
        self.series = SimpleNamespace(
            jser_fp=SERIES_FP,
            data={"objects": {n: None for n in names}},
            user_columns={},
        )
        self.mainwindow = mock.Mock(viewer=viewer)
        self.table = mock.Mock()

    def getFiltered(self):
        return sortList(list(self.series.data["objects"]))

    def passesFilters(self, name):
        return name in self.series.data["objects"]


def test_row_mark_follows_the_scene(qapp):
    objs = SceneObjectList()
    viewer = _viewer(objs)
    source = _ListSource(["d001", "d002"], viewer)
    model = ObjectTableModel(source)
    source.model = model

    def mark(name):
        row, _ = model.rowOf(name)
        return Qt.CheckState(model.data(model.index(row, 1), Qt.CheckStateRole))

    assert model.headerData(1, Qt.Horizontal) == "3D"
    assert mark("d001") == Qt.CheckState.Unchecked  # builds and caches the row

    manager = TableManager(SimpleNamespace(), SimpleNamespace(), None, SimpleNamespace())
    manager.tables["object"].append(source)
    viewer.mainwindow = SimpleNamespace(field=SimpleNamespace(table_manager=manager))

    objs.add(
        SimpleNamespace(metadata={}),
        SimpleNamespace(jser_fp=SERIES_FP, host_tree=None),
        "d001", "object", (255, 0, 0), 1.0,
    )
    viewer.updateObjectList(list(objs.values()))
    assert mark("d001") == Qt.CheckState.Checked
    assert mark("d002") == Qt.CheckState.Unchecked

    scene_obj = objs.search("d001", "object", SERIES_FP)
    objs.remove(scene_obj)
    viewer.updateObjectList([scene_obj])
    assert mark("d001") == Qt.CheckState.Unchecked


# --------------------------------------------------------------------------- #
# 6. The first batch in a new 3D window is marked                              #
# --------------------------------------------------------------------------- #

def test_new_viewer_is_the_mainwindow_viewer_when_its_first_meshes_land(qapp):
    """addToScene blocks inside CustomPlotter.__init__ until the meshes are
    placed, so placeInScene refreshes the list before the caller's
    ``viewer = CustomPlotter(...)`` assignment. The list reads the scene via
    mainwindow.viewer, so the plotter has to be registered there already."""
    from PySide6.QtWidgets import QWidget

    seen = []

    class FakeVPlotter:
        def __init__(self, qt_parent, **kwargs):
            self.qt_parent = qt_parent
            self.actors = []
            self.objs = SceneObjectList()

        def addToScene(self, objs, ztraces, **kwargs):
            seen.append(self.qt_parent.mainwindow.viewer)

        def __getattr__(self, name):  # menu callbacks
            return lambda *a, **k: None

    mainwindow = SimpleNamespace(
        viewer=None,
        series=mock.Mock(jser_fp=SERIES_FP, getOption=lambda name: False),
        screen_info=None,
    )

    def widget_init(self, parent=None):
        QWidget.__init__(self, parent)

    with mock.patch.object(cp.QVTKRenderWindowInteractor, "__init__", widget_init), \
         mock.patch.object(cp, "VPlotter", FakeVPlotter), \
         mock.patch.object(CustomPlotter, "show"), \
         mock.patch.object(cp.Container, "show"):
        viewer = CustomPlotter(mainwindow, names=["d001"])

    try:
        assert seen == [viewer]
    finally:
        viewer.container.deleteLater()
