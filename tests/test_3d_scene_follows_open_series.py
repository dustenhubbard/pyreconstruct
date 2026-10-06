"""The 3D scene follows the series the window has open.

`3D` > `Add to scene`, `Remove from scene` and the Object List's 3D box hand
the viewer object names only; the viewer fills in the series. It took that
series from the main window once, when it was built, so after `File` >
`Open series` or `Open recent` with the 3D window still open, an add built
meshes from the first series, whose working folder was already deleted, a
remove took out the first series' object of that name and left the open
series' one in place, and an edit in the field marked the first series'
object stale.

The window, the series switch, both series on disk and the scene object list
are real. `QVTKRenderWindowInteractor` cannot be built under the offscreen
platform (the process dies with SIGSEGV in its constructor, measured here),
so `CustomPlotter` and `VPlotter` are instances of the real classes made
without `__init__`, carrying the attributes the methods under test read, with
the VTK calls (`add`, `remove`, `render`, the camera behind `saveState`)
replaced by no-ops. The mesh worker is replaced by a recorder that keeps the
series it was handed.
"""
import os
import shutil
import types

import pytest
import vedo

pytestmark = pytest.mark.gui


def _mesh():
    return vedo.Mesh([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]])


def _instance(cls, window, **attrs):
    """An instance of `cls` without `__init__`, carrying only `attrs`.

    Before the fix, `__init__` stored a copy of the window's series on the
    instance; a class that resolves `series` itself gets no copy. A Qt
    instance reads its own `__dict__` before a class property (measured on
    `CustomPlotter`, unlike a plain Python class), so the copy cannot be
    written unconditionally.
    """
    obj = cls.__new__(cls)
    if "series" not in vars(cls):
        attrs["series"] = window.series
    obj.__dict__.update(attrs)
    return obj


def _viewer(window, monkeypatch):
    """A viewer on the window, built the way `CustomPlotter.__init__` builds
    it, minus the VTK widget. Returns it and the list of worker launches."""
    from PyReconstruct.modules.gui.popup import custom_plotter as cp

    launched = []

    class _Pool:
        def createWorker(self, fn, series, objs, ztraces, **kwargs):
            launched.append((series, [d["name"] for d in objs]))
            result = types.SimpleNamespace(connect=lambda f: None)
            return types.SimpleNamespace(
                signals=types.SimpleNamespace(result=result)
            )

        def startAll(self, *args, **kwargs):
            pass

    monkeypatch.setattr(cp, "ThreadPoolProgBar", _Pool)

    viewer = _instance(
        cp.CustomPlotter,
        window,
        mainwindow=window,
        is_closed=False,
        undo_states=[],
        redo_states=[],
        activateWindow=lambda: None,
        close=lambda: None,  # the window's closeEvent closes its viewer
    )
    plt = _instance(
        cp.VPlotter,
        window,
        qt_parent=viewer,
        mainwindow=window,
        objs=cp.SceneObjectList(),
        selected=[],
        saveState=lambda: None,
        add=lambda msh: None,
        remove=lambda msh: None,
        render=lambda: None,
        updateSelected=lambda: None,
    )
    viewer.plt = plt
    viewer.addToScene = plt.addToScene
    viewer.removeObjects = plt.removeFromScene
    monkeypatch.setattr(window, "viewer", viewer)
    return viewer, launched


def _open_other(window, series_jser, tmp_path):
    """Open a second series in the window, as `Open series` or `Open recent`
    does, and return the first one."""
    other_jser = tmp_path / "other" / "other.jser"
    other_jser.parent.mkdir()
    shutil.copy(series_jser, other_jser)
    first = window.series
    window.openSeries(jser_fp=str(other_jser), query_prev=False)
    assert window.series is not first
    assert window.series.jser_fp == str(other_jser)
    assert not os.path.isdir(first.hidden_dir), "the first series' folder stayed"
    return first


def test_add_after_a_switch_builds_from_the_open_series(
    main_window, main_window_dialogs, series_jser, tmp_path, monkeypatch
):
    window = main_window
    name = sorted(window.series.data["objects"])[0]
    viewer, launched = _viewer(window, monkeypatch)
    window.addTo3D([name])
    assert launched == [(viewer.plt.series, [name])]
    launched.clear()

    first = _open_other(window, series_jser, tmp_path)
    window.addTo3D([name])

    assert main_window_dialogs.notices == []
    assert len(launched) == 1
    series, names = launched[0]
    assert names == [name]
    assert series is window.series, (
        f"meshes built from {series.jser_fp}, not {window.series.jser_fp}"
    )
    assert series is not first


def test_remove_after_a_switch_takes_the_open_series_object(
    main_window, series_jser, tmp_path, monkeypatch
):
    window = main_window
    name = sorted(window.series.data["objects"])[0]
    viewer, _launched = _viewer(window, monkeypatch)
    objs = viewer.plt.objs
    theirs = objs.add(_mesh(), window.series, name, "object", (1, 1, 1), 1)

    first = _open_other(window, series_jser, tmp_path)
    mine = objs.add(_mesh(), window.series, name, "object", (2, 2, 2), 1)
    window.removeFrom3D([name])

    assert objs.search(name, "object", window.series.jser_fp) is None, (
        "the open series' object is still in the scene"
    )
    assert objs.search(name, "object", first.jser_fp) is theirs
    assert mine not in objs.values()


def test_an_edit_after_a_switch_marks_the_open_series_object_stale(
    main_window, series_jser, tmp_path, monkeypatch
):
    window = main_window
    name = sorted(window.series.data["objects"])[0]
    viewer, _launched = _viewer(window, monkeypatch)
    objs = viewer.plt.objs
    theirs = objs.add(_mesh(), window.series, name, "object", (1, 1, 1), 1)

    _open_other(window, series_jser, tmp_path)
    mine = objs.add(_mesh(), window.series, name, "object", (2, 2, 2), 1)
    viewer.markStale([name])

    assert objs.stale_ids == {mine.id}, (
        "the first series' object was marked" if theirs.id in objs.stale_ids
        else "nothing was marked"
    )


def test_a_refresh_after_a_switch_leaves_the_first_series_mark_alone(
    main_window, series_jser, tmp_path, monkeypatch
):
    """A stale object from the first series cannot be checked against the
    open series by name, so it keeps its mark instead of being resolved
    against the open series (rebuilding a same-named object there)."""
    window = main_window
    name = sorted(window.series.data["objects"])[0]
    viewer, launched = _viewer(window, monkeypatch)
    objs = viewer.plt.objs
    theirs = objs.add(_mesh(), window.series, name, "object", (1, 1, 1), 1)
    viewer.markStale([name])
    assert objs.stale_ids == {theirs.id}

    first = _open_other(window, series_jser, tmp_path)
    viewer.refreshStale()

    assert launched == [], "a same-named object was built from the open series"
    assert objs.stale_ids == {theirs.id}
    assert objs.search(name, "object", first.jser_fp) is theirs


def _hover(viewer, msh, z):
    """Move the mouse over a mesh at scene point (0.5, 0.25, z); return the
    text the scene shows."""
    shown = []
    viewer.plt.pos_text = types.SimpleNamespace(text=shown.append)
    event = types.SimpleNamespace(actor=msh, picked3d=(0.5, 0.25, z))
    viewer.plt.mouseMoveEvent(event)
    return shown[-1]


def test_hovering_a_first_series_mesh_reports_its_own_section(
    main_window, series_jser, tmp_path, monkeypatch
):
    """A mesh's z is its section number times its series' thickness, and the
    first series keeps its own section numbers after the switch, even
    though its working folder is closed."""
    window = main_window
    first = window.series
    name = sorted(first.data["objects"])[0]
    viewer, _launched = _viewer(window, monkeypatch)
    last = max(first.sections)
    theirs = viewer.plt.objs.add(_mesh(), first, name, "object", (1, 1, 1), 1)

    _open_other(window, series_jser, tmp_path)
    window.series.sections.pop(last)  # the open series has no such section
    text = _hover(viewer, theirs.msh, last * first.avg_thickness)

    assert f"section {last}" in text, text
    assert os.path.basename(first.jser_fp)[:-5] in text


def test_hovering_an_open_series_mesh_reports_its_own_section(
    main_window, series_jser, tmp_path, monkeypatch
):
    """The mirror: a mesh from the open series is not read against the first
    series' section numbers."""
    window = main_window
    first = window.series
    name = sorted(first.data["objects"])[0]
    viewer, _launched = _viewer(window, monkeypatch)
    lowest = min(first.sections)
    first.sections.pop(lowest)  # the first series has no such section
    viewer.plt.objs.add(_mesh(), first, name, "object", (1, 1, 1), 1)

    _open_other(window, series_jser, tmp_path)
    mine = viewer.plt.objs.add(_mesh(), window.series, name, "object", (2, 2, 2), 1)
    text = _hover(viewer, mine.msh, lowest * window.series.avg_thickness)

    assert f"section {lowest}" in text, text
    assert "(" not in text
