"""Export quantitative data when one object fails to measure.

Any error used to keep the whole CSV from being written, so one object whose
mesh raised lost the rows for every other object. The rows that measured are
now written and the failed objects are named in the notice, together with any
contours-mode objects that were left out. ``notify_user=False`` shows nothing.
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
    for name in ("circle2", "square", "star", "triangle"):
        s.setAttr(name, "3D_mode", "surface")
    yield s
    s.close()


@pytest.fixture
def notices(monkeypatch):
    from PyReconstruct.modules.backend.volume import export_volumes as ev
    seen = []
    monkeypatch.setattr(ev, "notify", lambda msg, *a, **k: seen.append(msg))
    return seen


def _fail_to_measure(monkeypatch, *bad):
    from PyReconstruct.modules.backend.volume.objects_3D import Surface
    original = Surface.measure

    def measure(self):
        if self.name in bad:
            raise ValueError(f"bad mesh: {self.name}")
        return original(self)

    monkeypatch.setattr(Surface, "measure", measure)


def _rows(fp):
    with open(fp) as f:
        return {r["Name"]: r for r in csv.DictReader(f)}


def test_rows_that_measured_are_written_unchanged(shapes, notices, monkeypatch, tmp_path):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    names = ["circle2", "square", "star"]
    clean = tmp_path / "clean.csv"
    ev.export3DData(shapes, names, str(clean))

    _fail_to_measure(monkeypatch, "square")
    out = tmp_path / "partial.csv"
    notices.clear()
    ev.export3DData(shapes, names, str(out))

    assert out.exists()
    rows = _rows(out)
    assert set(rows) == {"circle2", "star"}
    expected = _rows(clean)
    for name in rows:
        assert rows[name] == expected[name]

    assert len(notices) == 1
    assert "Data exported to" in notices[0]
    assert "Could not be measured" in notices[0] and "square" in notices[0]


def test_error_and_contours_skip_are_both_named(shapes, notices, monkeypatch, tmp_path):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    shapes.setAttr("triangle", "3D_mode", "contours")
    _fail_to_measure(monkeypatch, "square")
    out = tmp_path / "mesh_data.csv"

    ev.export3DData(shapes, ["circle2", "square", "triangle"], str(out))

    assert set(_rows(out)) == {"circle2"}
    assert len(notices) == 1
    assert "Not measured" in notices[0] and "triangle" in notices[0]
    assert "Could not be measured" in notices[0] and "square" in notices[0]


def test_nothing_measured_writes_nothing_and_names_both(shapes, notices, monkeypatch, tmp_path):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    shapes.setAttr("triangle", "3D_mode", "contours")
    _fail_to_measure(monkeypatch, "square", "star")
    out = tmp_path / "mesh_data.csv"

    ev.export3DData(shapes, ["square", "star", "triangle"], str(out))

    assert not out.exists()
    assert len(notices) == 1
    assert "No data exported" in notices[0]
    assert "square, star" in notices[0] and "triangle" in notices[0]


@pytest.mark.parametrize("bad", [(), ("square",), ("square", "star")])
def test_notify_user_false_shows_nothing(shapes, notices, monkeypatch, tmp_path, bad):
    from PyReconstruct.modules.backend.volume import export_volumes as ev

    _fail_to_measure(monkeypatch, *bad)
    out = tmp_path / "mesh_data.csv"

    ev.export3DData(shapes, ["square", "star"], str(out), notify_user=False)

    assert notices == []
    assert out.exists() == (len(bad) < 2)
