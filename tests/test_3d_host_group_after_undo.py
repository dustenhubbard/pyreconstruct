"""The 3D scene's host groups follow a series undo and redo.

The scene kept the host tree it first saw for each series and read that one
for `Select object's host group` and `Organize scene...`. `Clear host(s)...`
edits the tree in place, so the kept tree followed it, but a series undo or
redo puts a stored copy in `series.host_tree`, and the scene went on reading
the old tree. An object whose hosts were cleared and then brought back by the undo
still came out with no host group in the scene.

The window, the object list action, the undo and the scene object list are
real. `QVTKRenderWindowInteractor` cannot be built under the offscreen
platform, so `VPlotter` is an instance of the real class made without
`__init__`, carrying the attributes `selectHostGroup` reads, with its
`series` property resolving the window's series as it does in the app.
"""
import types

import pytest
import vedo

from PyReconstruct.modules.datatypes.host_tree import HostTree

pytestmark = pytest.mark.gui


def _mesh():
    return vedo.Mesh([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]])


def _plotter(window):
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    plt = cp.VPlotter.__new__(cp.VPlotter)
    plt.__dict__.update(
        mainwindow=window,
        objs=cp.SceneObjectList(),
        selected=[],
        updateSelected=lambda: None,
    )
    assert plt.series is window.series
    return plt


def _select_in_list(window, monkeypatch, names):
    field = window.field
    field.openList("object")
    table = field.table_manager.tables["object"][0]
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: table)
    monkeypatch.setattr(table, "getSelected", lambda: list(names))
    return field


def _host_group(plt, scene_obj):
    plt.selected = [scene_obj]
    plt.selectHostGroup()
    return sorted(so.name for so in plt.selected)


def test_host_group_after_undo_and_redo_of_clear_hosts(main_window, monkeypatch):
    window = main_window
    series = window.series
    names = sorted(series.data["objects"])
    assert len(names) > 1, "fixture series has too few objects"
    host, traveler = names[0], names[1]
    series.setObjHosts([traveler], [host])

    plt = _plotter(window)
    plt.objs.add(_mesh(), series, host, "object", (255, 0, 0), 1)
    t_obj = plt.objs.add(_mesh(), series, traveler, "object", (0, 255, 0), 1)
    assert _host_group(plt, t_obj) == sorted([host, traveler])

    field = _select_in_list(window, monkeypatch, [traveler])
    field.clearHosts()
    assert series.getObjHosts(traveler) == []
    assert _host_group(plt, t_obj) == [traveler]

    window.undo()
    assert series.getObjHosts(traveler) == [host]
    assert _host_group(plt, t_obj) == sorted([host, traveler])

    window.undo(redo=True)
    assert series.getObjHosts(traveler) == []
    assert _host_group(plt, t_obj) == [traveler]


def test_object_from_another_series_reads_the_tree_kept_at_add(main_window):
    """The scene can hold objects from a series that is no longer open (one
    loaded with a saved scene, or the series open before `File` > `Open
    series`). Those still read the tree kept when they were added."""
    window = main_window
    plt = _plotter(window)
    other = types.SimpleNamespace(
        jser_fp=window.series.jser_fp + ".other.jser",
        host_tree=HostTree({"other_t": ["other_h"]}, None),
    )
    plt.objs.add(_mesh(), other, "other_h", "object", (255, 0, 0), 1)
    t_obj = plt.objs.add(_mesh(), other, "other_t", "object", (0, 255, 0), 1)
    other.host_tree = HostTree({}, None)  # not what the scene kept

    assert _host_group(plt, t_obj) == ["other_h", "other_t"]
