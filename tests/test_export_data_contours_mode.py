"""Export quantitative data with a contours-mode object in the selection.

A contours-mode object has no closed mesh, so it has no surface area or volume.
It used to count as an error, and any error kept the whole CSV from being
written, so one contours-mode object in the selection lost the rows for every
other object too. It is now left out of the CSV and named in the notice.
"""
import csv
import os
import shutil

import pytest
from PySide6.QtWidgets import QApplication

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets", "checker", "files"
)


@pytest.fixture
def shapes(tmp_path):
    src = os.path.join(FIXTURE_DIR, "shapes1.jser")
    if not os.path.exists(src):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "shapes1.jser")
    shutil.copyfile(src, fp)
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    s = Series.openJser(fp)
    yield s
    s.close()


@pytest.fixture
def notices(monkeypatch):
    from PyReconstruct.modules.backend.volume import export_volumes as ev
    seen = []
    monkeypatch.setattr(ev, "notify", lambda msg, *a, **k: seen.append(msg))
    return seen


def test_contours_object_is_left_out_and_the_rest_are_written(shapes, notices, tmp_path):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    shapes.setAttr("circle2", "3D_mode", "surface")
    shapes.setAttr("square", "3D_mode", "contours")
    shapes.setAttr("star", "3D_mode", "spheres")
    out = tmp_path / "mesh_data.csv"

    ev.export3DData(shapes, ["circle2", "square", "star"], str(out))

    assert out.exists()
    with open(out) as fp:
        rows = {r["Name"]: r for r in csv.DictReader(fp)}
    assert set(rows) == {"circle2", "star"}
    assert rows["circle2"]["MeshType"] == "surface"
    assert float(rows["circle2"]["Volume"]) > 0
    assert rows["star"]["MeshType"] == "spheres"
    assert float(rows["star"]["Volume"]) > 0

    assert len(notices) == 1
    assert "Data exported to" in notices[0]
    assert "Not measured" in notices[0] and "square" in notices[0]


def test_only_contours_objects_writes_nothing_and_says_why(shapes, notices, tmp_path):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    shapes.setAttr("square", "3D_mode", "contours")
    out = tmp_path / "mesh_data.csv"

    ev.export3DData(shapes, ["square"], str(out))

    assert not out.exists()
    assert len(notices) == 1
    assert "No data exported" in notices[0] and "square" in notices[0]
    assert "errors" not in notices[0]
