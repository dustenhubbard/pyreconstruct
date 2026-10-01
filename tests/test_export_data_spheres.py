"""Export quantitative data measures spheres-mode objects exactly.

The CSV took area and volume from the display mesh. For one trace that mesh is
a trimesh Sphere primitive, whose area and volume are exact; for two or more it
is a concatenated icosphere mesh with one subdivision, which holds about 87% of
the volume and 93% of the area. So the same spheres measured differently
depending on how many traces the object had.
"""
import csv
import math
import os
import shutil

import pytest
from PySide6.QtWidgets import QApplication

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets", "checker", "files"
)


@pytest.fixture
def shapes(tmp_path, monkeypatch):
    src = os.path.join(FIXTURE_DIR, "shapes1.jser")
    if not os.path.exists(src):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(src, fp)
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.backend.volume import export_volumes as ev
    monkeypatch.setattr(ev, "notify", lambda *a, **k: None)
    from PyReconstruct.modules.datatypes.series import Series
    s = Series.openJser(fp)
    yield s
    s.close()


def _keep_one_trace(series, name):
    kept = False
    for _, section in series.enumerateSections(show_progress=False):
        traces = [t for t in section.tracesAsList() if t.name == name]
        if traces and not kept:
            kept = True
            continue
        if traces:
            section.deleteTraces(traces)
            section.save()


def test_spheres_rows_match_the_sphere_formulas(shapes, tmp_path):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    _keep_one_trace(shapes, "circle2")
    names = ["circle2", "square", "star", "triangle"]
    for name in names:
        shapes.setAttr(name, "3D_mode", "spheres")
    radii = {n: m.radii for n, m in ev.get_3D_meshes(shapes, names).items()}
    assert len(radii["circle2"]) == 1
    assert all(len(radii[n]) == 5 for n in names[1:])

    out = tmp_path / "mesh_data.csv"
    ev.export3DData(shapes, names, str(out))
    with open(out) as fp:
        rows = {r["Name"]: r for r in csv.DictReader(fp)}

    for name in names:
        area = sum(4 * math.pi * r ** 2 for r in radii[name])
        volume = sum(4 / 3 * math.pi * r ** 3 for r in radii[name])
        assert float(rows[name]["SurfaceArea"]) == pytest.approx(area, rel=1e-4), name
        assert float(rows[name]["Volume"]) == pytest.approx(volume, rel=1e-4), name
        assert rows[name]["MeshType"] == "spheres"


def test_surface_rows_still_come_from_the_mesh(shapes, tmp_path):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    shapes.setAttr("square", "3D_mode", "surface")
    tm = ev.get_3D_mesh(shapes, "square").generateTrimesh()

    out = tmp_path / "mesh_data.csv"
    ev.export3DData(shapes, ["square"], str(out))
    with open(out) as fp:
        row = next(csv.DictReader(fp))

    assert float(row["SurfaceArea"]) == round(tm.area, 5)
    assert float(row["Volume"]) == round(tm.volume, 5)
