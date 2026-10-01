"""The 3D scene follows the open series through `File` > `Save as...`.

Each scene object keeps the path of the series it came from in `series_fp`,
and the scene tells the open series' objects apart by comparing that path with
`series.jser_fp`. Save As changes `jser_fp`, so without an update every object
from the open series looks like it came from another one: `Revert selected...`
reads the colors last saved in the old file (or nothing, if it is gone), and a
double-click no longer jumps to the object in the field.

The real `CustomPlotter.seriesMoved`, `VPlotter.revertSelectedColor` and
`VPlotter.leftButtonClickEvent` run on stand-ins that carry the attributes they
read; building the VTK plotter offscreen is impractical. The window, the Save
As, the series and the scene object list are real.
"""
import types

import pytest
import vedo

pytestmark = pytest.mark.gui


def _mesh():
    return vedo.Mesh([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]])


def _viewer(series):
    """A stand-in CustomPlotter holding a real scene object list."""
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    viewer = types.SimpleNamespace(
        is_closed=False,
        series=series,
        undo_states=[],
        redo_states=[],
        plt=types.SimpleNamespace(objs=cp.SceneObjectList()),
    )
    helper = getattr(cp.CustomPlotter, "seriesMoved", None)
    if helper is not None:
        viewer.seriesMoved = types.MethodType(helper, viewer)
    else:  # before the fix, Save As never told the scene anything
        viewer.seriesMoved = lambda *_args: None
    return viewer


def _plotter(series, objs, selected=(), mainwindow=None):
    """A stand-in VPlotter for the methods under test."""
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    fake = types.SimpleNamespace(
        series=series, objs=objs, selected=list(selected),
        mainwindow=mainwindow, click_time=None,
        saveState=lambda: None, render=lambda: None,
        updateSelected=lambda: None,
        getFieldCoords=lambda _msh, _pt: (1.0, 2.0, 3),
    )
    fake._seriesForRevert = types.MethodType(cp.VPlotter._seriesForRevert, fake)
    return fake


def _save_as(window, dialogs, tmp_path):
    dest = tmp_path / "saved_as" / "renamed.jser"
    dest.parent.mkdir()
    dialogs.file_responses.append(str(dest))
    window.saveAsToJser()
    assert window.series.jser_fp == str(dest)
    return str(dest)


def test_revert_after_save_as_reads_the_open_series(
    main_window, main_window_dialogs, tmp_path, monkeypatch
):
    window = main_window
    series = window.series
    name = sorted(series.data["objects"].keys())[0]
    viewer = _viewer(series)
    monkeypatch.setattr(window, "viewer", viewer)
    obj = viewer.plt.objs.add(_mesh(), series, name, "object", (9, 9, 9), 1)
    old_fp = series.jser_fp

    _save_as(window, main_window_dialogs, tmp_path)

    # recolor the object in the open series only; the old file keeps its colors
    for snum in series.sections:
        section = series.loadSection(snum)
        if name in section.contours:
            for trace in section.contours[name]:
                trace.color = (1, 2, 3)
            section.save()

    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    cp.VPlotter.revertSelectedColor(_plotter(series, viewer.plt.objs, [obj]))

    assert tuple(obj.color) == (1, 2, 3)
    assert obj.series_fp == series.jser_fp != old_fp


def test_double_click_after_save_as_jumps_to_the_object(
    main_window, main_window_dialogs, tmp_path, monkeypatch
):
    window = main_window
    series = window.series
    name = sorted(series.data["objects"].keys())[0]
    viewer = _viewer(series)
    monkeypatch.setattr(window, "viewer", viewer)
    obj = viewer.plt.objs.add(_mesh(), series, name, "object", (9, 9, 9), 1)

    _save_as(window, main_window_dialogs, tmp_path)

    moves = []
    mainwindow = types.SimpleNamespace(
        field=types.SimpleNamespace(moveTo=lambda *a: moves.append(a)),
        activateWindow=lambda: None,
    )
    fake = _plotter(series, viewer.plt.objs, mainwindow=mainwindow)
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    for t in (1.0, 1.1):
        event = types.SimpleNamespace(time=t, actor=obj.msh, picked3d=(0, 0, 0))
        cp.VPlotter.leftButtonClickEvent(fake, event)

    assert moves == [(3, 1.0, 2.0)]


def test_series_moved_leaves_other_series_alone():
    old_fp, new_fp, other_fp = "/a/old.jser", "/b/new.jser", "/c/other.jser"
    open_series = types.SimpleNamespace(jser_fp=old_fp, host_tree="open tree")
    other_series = types.SimpleNamespace(jser_fp=other_fp, host_tree="other tree")
    viewer = _viewer(open_series)
    objs = viewer.plt.objs
    mine = objs.add(types.SimpleNamespace(metadata={}), open_series, "d01",
                    "object", (1, 1, 1), 1)
    theirs = objs.add(types.SimpleNamespace(metadata={}), other_series, "d01",
                      "object", (1, 1, 1), 1)
    viewer.undo_states.append(
        {"scene_objects": {"series_fps": {
            old_fp: {"objects": [{"id": "x"}], "ztraces": []},
            other_fp: {"objects": [{"id": "y"}], "ztraces": []},
        }}}
    )

    viewer.seriesMoved(old_fp, new_fp)

    assert mine.series_fp == new_fp
    assert theirs.series_fp == other_fp
    assert objs.host_trees == {new_fp: "open tree", other_fp: "other tree"}
    assert objs.search("d01", "object", new_fp) is mine
    state = viewer.undo_states[0]["scene_objects"]["series_fps"]
    assert state == {
        new_fp: {"objects": [{"id": "x"}], "ztraces": []},
        other_fp: {"objects": [{"id": "y"}], "ztraces": []},
    }
