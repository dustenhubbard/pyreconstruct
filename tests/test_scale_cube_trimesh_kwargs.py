"""The Scale Cube export passes only real keywords to `trimesh.Trimesh`.

`convert_vedo_to_tm` built the cube with `prcess=False`. Trimesh swallows
unknown keywords, so the typo did nothing and the mesh was processed anyway.
"""
import inspect
from types import SimpleNamespace

import numpy as np
import trimesh

from PyReconstruct.modules.backend.volume import export_volumes
from PyReconstruct.modules.backend.volume.export_volumes import convert_vedo_to_tm

CUBE = np.array(
    [[x, y, z] for x in (0.0, 2.0) for y in (0.0, 2.0) for z in (0.0, 2.0)]
)
# Corners plus interior points, so the hull has to drop vertices.
POINTS = np.vstack([CUBE, [[1, 1, 1], [0.5, 1, 1.5], [1, 0.5, 0.5]]])


class _Points:
    def __init__(self, arr):
        self.arr = arr

    def GetNumberOfPoints(self):
        return len(self.arr)

    def GetPoint(self, i):
        return tuple(self.arr[i])


def _scale_cube(points=POINTS):
    polydata = SimpleNamespace(GetPoints=lambda: _Points(points))
    return SimpleNamespace(
        name="Scale Cube", msh=SimpleNamespace(polydata=lambda: polydata)
    )


def test_scale_cube_hull_is_watertight_with_cube_corners():
    hull = convert_vedo_to_tm(_scale_cube())
    assert hull.is_watertight
    assert len(hull.vertices) == 8
    assert len(hull.faces) == 12
    assert np.isclose(hull.volume, 8.0)


def test_scale_cube_passes_only_trimesh_keywords(monkeypatch):
    seen = {}
    real = trimesh.Trimesh

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(export_volumes.trimesh, "Trimesh", spy)
    convert_vedo_to_tm(_scale_cube())

    params = inspect.signature(real.__init__).parameters
    unknown = set(seen) - set(params)
    assert not unknown
    assert seen["process"] is False
