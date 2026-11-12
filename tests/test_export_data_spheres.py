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

    assert float(row["SurfaceArea"]) == pytest.approx(tm.area, rel=1e-12)
    assert float(row["Volume"]) == pytest.approx(tm.volume, rel=1e-12)


@pytest.mark.parametrize("radius,area,volume", [
    (0.01, 0.0012566370614359172, 0.000004188790204786391),
    (0.02, 0.005026548245743669, 0.00003351032163829113),
    (0.00001, 0.0000000012566370614359173, 0.000000000000004188790204786392),
])
@pytest.mark.parametrize("quantity", ["SurfaceArea", "Volume"])
def test_small_sphere_quantities_keep_significant_digits(shapes, tmp_path, radius, area, volume, quantity):
    from PyReconstruct.modules.backend.volume import export_volumes as ev
    from PyReconstruct.modules.datatypes import Trace, Transform

    section = shapes.loadSection(min(shapes.sections))
    section.tform = Transform.identity()
    trace = Trace("small_sphere", (255, 0, 0), True)
    trace.points = [(-radius, 0), (0, radius), (radius, 0), (0, -radius)]
    section.addTrace(trace, log_event=False)
    section.save()
    shapes.setAttr("small_sphere", "3D_mode", "spheres")
    out = tmp_path / "small_sphere.csv"

    ev.export3DData(shapes, ["small_sphere"], str(out), notify_user=False)

    with out.open() as fp:
        row = next(csv.DictReader(fp))
    expected = {"SurfaceArea": area, "Volume": volume}
    assert float(row[quantity]) == pytest.approx(expected[quantity], rel=1e-12, abs=0)
