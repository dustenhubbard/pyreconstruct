"""Mesh files preserve aligned geometry, section gaps, and existing exports."""

import math
import sys

import numpy as np
import pytest
import trimesh

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.volume import export_volumes as ev
from PyReconstruct.modules.backend.volume.generate_volumes import generateVolumes
from PyReconstruct.modules.datatypes import Series, Trace, Transform


@pytest.fixture
def mesh_series(qapp, tmp_path):
    images = [str(tmp_path / f"section{i}.tif") for i in range(3)]
    series = Series.new(images, "mesh", 0.25, 0.5)
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    series.setOption("3D_xy_res", 0)
    series.setOption("3D_smoothing", "none")
    try:
        for snum, dx, dy in ((0, 10, -4), (2, 20, 6)):
            section = series.loadSection(snum)
            section.tforms["default"] = Transform([1, 0, -100, 0, 1, -100])
            section.tforms["mesh"] = Transform([2, 0, dx, 0, 2, dy])
            trace = Trace("mesh", (40, 80, 120), closed=True)
            trace.points = [(0, 0), (2, 0), (2, 2), (0, 2)]
            section.addTrace(trace, log_event=False)
            section.save()
        series.setAttr("mesh", "alignment", "mesh")
        yield series
    finally:
        series.close()


def _triangles(mesh):
    # STL duplicates vertices, and loaders may reorder them. Compare triangles
    # by coordinates so vertex numbering is not part of the file contract.
    triangles = np.round(mesh.triangles, 5)
    return sorted(tuple(sorted(map(tuple, triangle))) for triangle in triangles)


@pytest.mark.parametrize("mode", ["surface", "spheres"])
@pytest.mark.parametrize("file_type", ["obj", "off", "ply", "stl"])
def test_mesh_files_keep_aligned_geometry_and_section_gaps(
    mesh_series, tmp_path, mode, file_type
):
    mesh_series.setAttr("mesh", "3D_mode", mode)
    scene_meshes, _, failures = generateVolumes(
        mesh_series, [{"name": "mesh"}], []
    )
    assert failures == []
    scene_mesh = trimesh.Trimesh(
        vertices=scene_meshes[0]["vertices"], faces=scene_meshes[0]["faces"]
    )

    output = tmp_path / f"mesh.{file_type}"
    output.write_bytes(b"previous export")
    ev.export3DObjects(
        mesh_series, ["mesh"], str(tmp_path), file_type, notify_user=False
    )
    exported = trimesh.load(output, force="mesh")

    assert _triangles(exported) == _triangles(scene_mesh)
    parts = sorted(exported.split(), key=lambda part: part.bounds[0, 0])
    assert len(parts) == 2
    np.testing.assert_allclose(
        [part.bounds.mean(axis=0) for part in parts],
        [[12, -2, 0.5], [22, 8, 1.5]], atol=1e-6,
    )
    assert [part.euler_number for part in parts] == [2, 2]
    assert all(part.is_watertight for part in parts)
    assert [part.is_winding_consistent for part in parts] == [True, True]
    assert exported.volume == pytest.approx(scene_mesh.volume, rel=1e-6)

    if mode == "spheres":
        for part, center in zip(parts, ((12, -2, 0.5), (22, 8, 1.5))):
            np.testing.assert_allclose(
                np.linalg.norm(part.vertices - center, axis=1),
                math.sqrt(8), atol=1e-6,
            )
    else:
        np.testing.assert_allclose(
            exported.bounds, [[10, -4, 0.25], [24, 10, 1.75]], atol=1e-6
        )


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("mode", ["surface", "spheres"])
@pytest.mark.parametrize("file_type", ["obj", "off", "ply", "stl"])
def test_failed_serialization_preserves_the_existing_export(
    mesh_series, tmp_path, monkeypatch, mode, file_type, existing
):
    mesh_series.setAttr("mesh", "3D_mode", mode)
    output = tmp_path / f"mesh.{file_type}"
    original = b"previous export\x00\xff\n"
    if existing:
        output.write_bytes(original)

    def fail_serialization(*args, **kwargs):
        raise ValueError("cannot serialize mesh")

    monkeypatch.setattr(
        getattr(trimesh.exchange, file_type),
        f"export_{file_type}", fail_serialization,
    )
    with pytest.raises(ValueError, match="cannot serialize mesh"):
        ev.export3DObjects(
            mesh_series, ["mesh"], str(tmp_path), file_type, notify_user=False
        )
    if existing:
        assert output.read_bytes() == original
    else:
        assert not output.exists()


@pytest.mark.parametrize("smoothing", ["laplacian", "mut_dif_laplacian", "taubin"])
def test_surface_smoothing_changes_geometry_without_opening_the_mesh(
    mesh_series, smoothing
):
    mesh_series.setAttr("mesh", "3D_mode", "surface")
    surface = ev.get_3D_mesh(mesh_series, "mesh")
    unsmoothed = surface.generateTrimesh()
    mesh_series.setOption("3D_smoothing", smoothing)
    mesh_series.setOption("smoothing_iterations", 2)

    smoothed = surface.generateTrimesh()

    assert np.isfinite(smoothed.vertices).all()
    assert not np.allclose(smoothed.vertices, unsmoothed.vertices)
    assert smoothed.is_watertight
    assert len(smoothed.split()) == 2
    assert smoothed.area < unsmoothed.area


def test_missing_collada_support_reports_the_requirement_without_replacing_files(
    mesh_series, tmp_path, monkeypatch
):
    output = tmp_path / "mesh.dae"
    output.write_bytes(b"previous Collada export")
    notices = []
    monkeypatch.setitem(sys.modules, "collada", None)
    monkeypatch.setattr(ev, "notify", notices.append)

    ev.export3DObjects(mesh_series, ["mesh"], str(tmp_path), "dae")

    assert output.read_bytes() == b"previous Collada export"
    assert len(notices) == 1
    assert "Collada (.dae) export needs the optional 'pycollada'" in notices[0]
