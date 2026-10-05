"""`Revert selected...` in the 3D scene reads each object's own series.

An object added with `File` > `Add to scene` > `From other series...` keeps that
series' path. Its original color is in that series, so the revert has to read
it there instead of looking the name up in the series that is open.

The real `VPlotter.revertSelectedColor` is called on a stand-in that carries the
attributes it reads; building the VTK plotter offscreen is impractical. The
scene objects, their meshes and both series are real.
"""
import os
import shutil
import types

import pytest
import vedo


def _plotter(series, selected):
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    fake = types.SimpleNamespace(
        series=series, selected=selected,
        saveState=lambda: None, render=lambda: None,
    )
    helper = getattr(cp.VPlotter, "_seriesForRevert", None)
    if helper is not None:
        fake._seriesForRevert = types.MethodType(helper, fake)
    return fake


def _mesh():
    return vedo.Mesh([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]]])


@pytest.fixture
def other_series(series_jser, tmp_path):
    """A second copy of the fixture with its first object recolored (1, 2, 3)."""
    from PyReconstruct.modules.datatypes import Series
    fp = tmp_path / "other" / "other.jser"
    fp.parent.mkdir()
    shutil.copy(series_jser, fp)
    other = Series.openJser(str(fp))
    name = None
    for _snum, section in other.enumerateSections(show_progress=False):
        if name is None and section.contours:
            name = sorted(section.contours.keys())[0]
        if name in section.contours:
            section.editTraceAttributes(
                list(section.contours[name]), name=None, color=(1, 2, 3),
                tags=None, mode=None, log_event=False,
            )
            section.save()
    other.saveJser()
    yield other, name
    other.close()


def test_revert_reads_the_objects_own_series(real_series, other_series):
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    other, name = other_series
    obj = cp.SceneObject(_mesh(), other, name, "object", (200, 200, 200), 1)
    obj.setColor((9, 9, 9))

    cp.VPlotter.revertSelectedColor(_plotter(real_series, [obj]))

    assert tuple(obj.color) == (1, 2, 3)


def test_revert_reads_the_ztrace_from_its_own_series(real_series,
                                                     other_series):
    from PyReconstruct.modules.datatypes import Ztrace
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    other, _name = other_series
    other.ztraces["zt"] = Ztrace("zt", (4, 5, 6), [(0.1, 0.2, 1)])
    other.saveJser()
    real_series.ztraces["zt"] = Ztrace("zt", (255, 0, 0), [(0.1, 0.2, 1)])
    obj = cp.SceneObject(_mesh(), other, "zt", "ztrace", (9, 9, 9), 1)

    cp.VPlotter.revertSelectedColor(_plotter(real_series, [obj]))

    assert tuple(obj.color) == (4, 5, 6)


def test_revert_still_reads_the_open_series(real_series):
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    name = sorted(real_series.data["objects"].keys())[0]
    expected = None
    for snum in sorted(real_series.sections):
        section = real_series.loadSection(snum)
        if name in section.contours:
            expected = tuple(section.contours[name][0].color)
            break
    obj = cp.SceneObject(_mesh(), real_series, name, "object", expected, 1)
    obj.setColor((9, 9, 9))

    cp.VPlotter.revertSelectedColor(_plotter(real_series, [obj]))

    assert tuple(obj.color) == expected


def test_a_missing_series_leaves_the_color(real_series, tmp_path):
    from PyReconstruct.modules.gui.popup import custom_plotter as cp
    obj = cp.SceneObject(_mesh(), real_series, "x", "object", (9, 9, 9), 1)
    obj.series_fp = os.path.join(str(tmp_path), "gone.jser")

    cp.VPlotter.revertSelectedColor(_plotter(real_series, [obj]))

    assert tuple(obj.color) == (9, 9, 9)
