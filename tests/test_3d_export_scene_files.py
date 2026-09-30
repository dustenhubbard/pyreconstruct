"""3D `Export scene` only touches the two scene files it writes (fork #546).

The export used to write one .obj/.mtl per object into the chosen folder and
then delete them. A user's same-named files there were replaced and deleted,
two same-named objects crashed it, and an object named like the scene file
deleted the scene itself. The per-object files now live in a scratch folder.
"""
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "dev", "assets", "checker", "files",
    "class_series.jser",
)


@pytest.fixture
def cp():
    QApplication.instance() or QApplication(["test"])
    import PyReconstruct.modules.gui.popup.custom_plotter as cp
    return cp


@pytest.fixture
def open_series(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture class_series.jser not found")
    from PyReconstruct.modules.datatypes import Series
    opened = []

    def _open(name):
        dst = tmp_path / f"{name}.jser"
        shutil.copyfile(FIXTURE, dst)
        s = Series.openJser(str(dst))
        opened.append(s)
        return s

    yield _open
    for s in opened:
        s.close()


def run_export(cp, objs, combo_fp, monkeypatch, confirm=True):
    notes, asked = [], []
    monkeypatch.setattr(
        cp.FileDialog, "get", staticmethod(lambda *a, **k: str(combo_fp))
    )
    monkeypatch.setattr(cp, "notify", lambda msg, *a, **k: notes.append(msg))

    def fake_confirm(msg, *a, **k):
        asked.append(msg)
        return confirm

    monkeypatch.setattr(cp, "notifyConfirm", fake_confirm)
    cp.CustomPlotter.exportScene(SimpleNamespace(plt=SimpleNamespace(objs=objs)))
    return notes, asked


def listing(d):
    return sorted(p.name for p in Path(d).iterdir())


def test_existing_same_named_files_are_left_alone(cp, open_series, tmp_path, monkeypatch):
    import vedo
    s = open_series("a")
    out = tmp_path / "out"
    out.mkdir()
    (out / "d01.obj").write_text("# my own d01\nv 0 0 0\n")
    (out / "d01.mtl").write_text("newmtl mine\n")
    objs = cp.SceneObjectList()
    objs.add(vedo.Sphere(), s, "d01", "object", (255, 0, 0), 1)

    notes, asked = run_export(cp, objs, out / "scene.obj", monkeypatch)

    assert listing(out) == ["d01.mtl", "d01.obj", "scene.mtl", "scene.obj"]
    assert (out / "d01.obj").read_text() == "# my own d01\nv 0 0 0\n"
    assert (out / "d01.mtl").read_text() == "newmtl mine\n"
    assert asked == []
    assert notes and "scene.obj" in notes[0]


def test_same_named_objects_get_their_own_names(cp, open_series, tmp_path, monkeypatch):
    import vedo
    s1, s2 = open_series("a"), open_series("b")
    out = tmp_path / "out"
    out.mkdir()
    objs = cp.SceneObjectList()
    objs.add(vedo.Sphere(), s1, "d01", "object", (255, 0, 0), 1)
    objs.add(vedo.Sphere(pos=(3, 0, 0)), s2, "d01", "object", (0, 255, 0), 1)

    notes, _ = run_export(cp, objs, out / "scene.obj", monkeypatch)

    assert listing(out) == ["scene.mtl", "scene.obj"]
    obj_text = (out / "scene.obj").read_text()
    mtl_text = (out / "scene.mtl").read_text()
    assert "o d01\n" in obj_text and "o d01_2\n" in obj_text
    assert "usemtl d01\n" in obj_text and "usemtl d01_2\n" in obj_text
    assert "newmtl d01\n" in mtl_text and "newmtl d01_2\n" in mtl_text
    assert notes


def test_object_named_like_the_scene_keeps_the_scene(cp, open_series, tmp_path, monkeypatch):
    import vedo
    s = open_series("a")
    out = tmp_path / "out"
    out.mkdir()
    objs = cp.SceneObjectList()
    objs.add(vedo.Sphere(), s, "scene", "object", (255, 0, 0), 1)

    notes, _ = run_export(cp, objs, out / "scene.obj", monkeypatch)

    assert listing(out) == ["scene.mtl", "scene.obj"]
    assert "o scene\n" in (out / "scene.obj").read_text()
    assert "newmtl scene\n" in (out / "scene.mtl").read_text()
    assert notes


def test_existing_scene_mtl_is_replaced_only_after_asking(cp, open_series, tmp_path, monkeypatch):
    import vedo
    s = open_series("a")
    out = tmp_path / "out"
    out.mkdir()
    (out / "scene.mtl").write_text("newmtl mine\n")
    objs = cp.SceneObjectList()
    objs.add(vedo.Sphere(), s, "d01", "object", (255, 0, 0), 1)

    notes, asked = run_export(cp, objs, out / "scene.obj", monkeypatch, confirm=False)
    assert len(asked) == 1 and "scene.mtl" in asked[0]
    assert listing(out) == ["scene.mtl"]
    assert (out / "scene.mtl").read_text() == "newmtl mine\n"
    assert notes == []

    notes, asked = run_export(cp, objs, out / "scene.obj", monkeypatch, confirm=True)
    assert len(asked) == 1
    assert listing(out) == ["scene.mtl", "scene.obj"]
    assert "newmtl d01\n" in (out / "scene.mtl").read_text()
    assert notes
