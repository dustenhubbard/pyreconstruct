"""Scene OBJ materials retain opacity when loaded again."""

import pytest
import vedo
from vtkmodules.vtkIOImport import vtkOBJImporter

from tests.test_3d_export_scene_files import (
    cp,  # noqa: F401 (fixture)
    open_series,  # noqa: F401 (fixture)
    run_export,
)


@pytest.mark.parametrize("alpha", [0, 0.25, 1])
@pytest.mark.parametrize("kind", ["object", "ztrace", "scale_cube"])
def test_scene_obj_round_trip_retains_opacity(
    cp, open_series, tmp_path, monkeypatch, kind, alpha,  # noqa: F811 (fixtures)
):
    series = open_series("opacity")
    objs = cp.SceneObjectList()
    name = "Scale Cube" if kind == "scale_cube" else "d01"
    mesh = vedo.Cube() if kind == "scale_cube" else vedo.Sphere()
    objs.add(mesh, series, name, kind, (255, 0, 0), alpha)
    output = tmp_path / "scene.obj"

    notes, _ = run_export(cp, objs, output, monkeypatch)

    assert notes and "Scene exported" in notes[0]
    restored = vtkOBJImporter()
    restored.SetFileName(str(output))
    restored.SetFileNameMTL(str(output.with_suffix(".mtl")))
    restored.Update()
    actors = [
        actor for actor in restored.GetRenderer().GetActors()
        if actor.GetMapper().GetInput().GetNumberOfCells()
    ]
    assert len(actors) == 1
    assert actors[0].GetMapper().GetInput().GetNumberOfCells() > 0
    assert actors[0].GetProperty().GetDiffuseColor() == (1, 0, 0)
    assert actors[0].GetProperty().GetOpacity() == pytest.approx(alpha)
