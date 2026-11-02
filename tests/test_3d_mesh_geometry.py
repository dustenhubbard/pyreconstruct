"""Physical section positions, mesh failures, and z-trace tube geometry."""

from types import MethodType, SimpleNamespace

import numpy as np
import pytest

from PyReconstruct.modules.backend.volume.generate_volumes import generateVolumes
from PyReconstruct.modules.backend.volume.objects_3D import (
    Contours, Spheres, Surface, Ztrace3D, createTube,
)
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series, Trace, Ztrace
from PyReconstruct.modules.gui.popup import custom_plotter as cp


@pytest.fixture
def mesh_series(shapes1_jser, qapp):
    series = Series.openJser(str(shapes1_jser), progress=NullProgressReporter)
    yield series
    series.close()


@pytest.fixture
def uneven_series(mesh_series):
    series = mesh_series
    series.sections = {n: series.sections[n] for n in (1, 2, 3)}
    sections = series.data["sections"]
    for n in list(sections):
        if n not in series.sections:
            del sections[n]
    for n, thickness in ((1, 1), (2, 9), (3, 1)):
        series.data["sections"][n]["thickness"] = thickness
        series.data["sections"][n]["mag"] = 1
    series.setOption("3D_smoothing", "none")
    series.setOption("3D_xy_res", 100)
    series.ztraces["path"] = Ztrace("path", (255, 0, 0),
                                     [(0, 0, 1), (0, 0, 2), (0, 0, 3)])
    return series


def square(name="mesh", negative=False):
    trace = Trace(name, (255, 0, 0), True)
    trace.points = [(0, 0), (2, 0), (2, 2), (0, 2)]
    trace.negative = negative
    return trace


def test_ztrace_uses_cumulative_section_positions(uneven_series):
    vertices = Ztrace3D("path", uneven_series).generate3D()["vertices"]
    centers = vertices.reshape(3, -1, 3).mean(axis=1)
    np.testing.assert_allclose(centers[:, 2], [1, 10, 11])


def test_spheres_use_cumulative_section_positions(uneven_series):
    spheres = Spheres("mesh", uneven_series)
    for n in (1, 2, 3):
        spheres.addTrace(square(), n)
    parts = spheres.generateTrimesh().split(only_watertight=False)
    assert sorted(part.bounds[:, 2].mean() for part in parts) == pytest.approx([1, 10, 11])


def test_contour_slabs_use_each_sections_position_and_thickness(uneven_series):
    contours = Contours("mesh", uneven_series)
    contours.addTrace(square(), 2)
    vertices = contours.generate3D()["vertices"]
    assert sorted(set(vertices[:, 2])) == [10, 14.5]


@pytest.mark.parametrize("n, expected", [(1, [0.5, 5.5]), (2, [5.5, 10.5]), (3, [10.5, 11.5])])
def test_surface_maps_voxel_boundaries_to_physical_z(uneven_series, n, expected):
    surface = Surface("mesh", uneven_series)
    # Empty slices on either side still define the physical voxel grid.
    for snum in (1, 2, 3):
        surface.addTrace(square(negative=snum != n), snum)
    mesh = surface.generateTrimesh()
    assert mesh.bounds[:, 2] == pytest.approx(expected)
    area, volume = surface.measure()
    assert area == pytest.approx(mesh.area)
    assert volume == pytest.approx(mesh.volume)
    assert volume > 0

    cropped = Surface("mesh", uneven_series)
    cropped.addTrace(square(), n)
    assert cropped.generateTrimesh().bounds[:, 2] == pytest.approx(expected)


@pytest.mark.parametrize("z, expected", [(1, 1), (10, 2), (11, 3), (7, 2)])
def test_scene_navigation_uses_physical_section_positions(uneven_series, z, expected):
    plotter = SimpleNamespace(series=uneven_series, objs=cp.SceneObjectList())
    assert cp.VPlotter.getSectionFromZ(plotter, z) == expected


def test_navigation_retains_closed_series_section_positions(uneven_series):
    objects = cp.SceneObjectList()
    objects.add(cp.vedo.Cube(), uneven_series, "mesh", "object", (1, 2, 3), 1)
    other = SimpleNamespace(jser_fp="other.jser")
    plotter = SimpleNamespace(series=other, objs=objects)
    assert cp.VPlotter.getSectionFromZ(plotter, 10, uneven_series.jser_fp) == 2


def test_surface_uses_section_order_across_numbering_gaps(uneven_series):
    del uneven_series.sections[2]
    surface = Surface("mesh", uneven_series)
    surface.addTrace(square(), 1)
    surface.addTrace(square(), 3)
    mesh = surface.generateTrimesh()
    assert mesh.bounds[:, 2] == pytest.approx([0.5, 2.5])
    assert len(mesh.split()) == 1


def test_negative_only_surface_does_not_abort_batch(mesh_series):
    section = mesh_series.loadSection(min(mesh_series.sections))
    for trace in (square("valid"), square("negative", negative=True)):
        section.addTrace(trace, log_event=False)
    section.save()
    mesh_series.setOption("3D_smoothing", "none")
    result = generateVolumes(mesh_series, [{"name": "negative"}, {"name": "valid"}], [])
    assert [mesh["name"] for mesh in result[0]] == ["valid"]
    assert [failure["name"] for failure in result[2]] == ["negative"]


def test_failed_refresh_preserves_mesh_and_reports_name(mesh_series, monkeypatch):
    section = mesh_series.loadSection(min(mesh_series.sections))
    section.addTrace(square("negative", negative=True), log_event=False)
    section.save()
    plotter = SimpleNamespace(
        series=mesh_series, objs=cp.SceneObjectList(), selected=[],
        saveState=lambda: None, render=lambda: None, updateSelected=lambda: None,
        add=lambda mesh: None, remove=lambda mesh: None,
        qt_parent=SimpleNamespace(updateObjectList=lambda objects: None),
        mainwindow=SimpleNamespace(statusbar=None),
    )
    for name in ("removeSceneObj", "removeFromScene", "placeInScene"):
        setattr(plotter, name, MethodType(getattr(cp.VPlotter, name), plotter))
    old = plotter.objs.add(cp.vedo.Cube(), mesh_series, "negative", "object", (12, 34, 56), 0.4)
    old.translate(2, 3, 4)
    before = old.getExportDict()
    plotter.selected.append(old)
    messages = []
    monkeypatch.setattr(cp, "notify", lambda message, *a, **kw: messages.append(message))

    class Pool:
        def createWorker(self, fn, *args, **kwargs):
            self.run = lambda: self.callback(fn(*args))
            return SimpleNamespace(signals=SimpleNamespace(result=SimpleNamespace(
                connect=lambda callback: setattr(self, "callback", callback))))

        def startAll(self, **kwargs):
            self.run()

    monkeypatch.setattr(cp, "ThreadPoolProgBar", Pool)
    cp.VPlotter.addToScene(plotter, ["negative"], [])
    assert plotter.objs.search("negative", "object", mesh_series.jser_fp) is old
    assert old.getExportDict() == before
    assert plotter.selected == [old]
    assert old.id in plotter.objs.stale_ids
    assert len(messages) == 1 and "negative" in messages[0]


@pytest.mark.parametrize("end", [(10, 0, 0), (0, 10, 0), (4, 6, 8), (0, 0, 10)])
def test_tube_rings_are_perpendicular_to_path(end):
    vertices, faces = createTube([(0, 0, 0), end], radius=1, segments=12)
    rings = vertices.reshape(2, 12, 3)
    offsets = rings - np.array([(0, 0, 0), end])[:, None, :]
    np.testing.assert_allclose(offsets @ np.asarray(end), 0, atol=1e-12)
    np.testing.assert_allclose(np.linalg.norm(offsets, axis=2), 1, atol=1e-12)
    if end[2] == 0:
        assert np.ptp(vertices[:, 2]) == pytest.approx(2)
    assert len(faces) == 24


def test_repeated_tube_points_do_not_create_zero_area_faces():
    vertices, faces = createTube([(0, 0, 0), (0, 0, 0), (3, 0, 0), (3, 0, 0)], radius=1)
    triangles = vertices[faces]
    areas = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                    triangles[:, 2] - triangles[:, 0]), axis=1) / 2
    assert np.all(areas > 0)


@pytest.mark.parametrize("points", [[], [(1, 2, 3)], [(1, 2, 3), (1, 2, 3)]])
def test_tube_without_a_segment_has_no_geometry(points):
    vertices, faces = createTube(points)
    assert vertices.shape == faces.shape == (0, 3)


def test_reversing_tube_path_has_finite_vertices_and_valid_faces():
    points = [(0, 0, 0), (3, 0, 0), (0, 0, 0)]
    vertices, faces = createTube(points, radius=0.1)
    assert np.isfinite(vertices).all()
    assert len(vertices) == 18 and len(faces) == 24
    assert faces.max() < len(vertices)


def test_tube_turn_has_finite_perpendicular_rings():
    points = np.array([(0, 0, 0), (3, 0, 0), (3, 3, 0), (3, 3, 3)])
    vertices, faces = createTube(points, radius=0.1, segments=12)
    offsets = vertices.reshape(4, 12, 3) - points[:, None, :]
    tangents = np.array([(1, 0, 0), (1, 1, 0), (0, 1, 1), (0, 0, 1)])
    np.testing.assert_allclose(np.einsum("ijk,ik->ij", offsets, tangents), 0, atol=1e-12)
    assert np.isfinite(vertices).all()
    assert faces.max() < len(vertices)
