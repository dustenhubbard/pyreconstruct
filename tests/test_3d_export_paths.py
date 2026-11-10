"""Object names cannot put mesh exports outside their destination."""

import errno
import sys

import pytest
import vedo

from PyReconstruct.modules.backend.volume import export_volumes as ev
from tests.test_3d_export_scene_files import (
    cp,  # noqa: F401 (fixture)
    open_series,  # noqa: F401 (fixture)
    run_export,
)

PATH_NAMES = [
    "../victim", "absolute", r"..\victim", "nested/victim",
    r"C:\victim", "C:/victim",
    pytest.param(
        r"\\server\share\victim",
        marks=pytest.mark.skipif(sys.platform == "win32", reason="Avoid accessing a network share"),
    ),
]


def path_name(name, victim):
    if name == "absolute":
        return str(victim)
    if name.startswith("C:"):
        absolute = str(victim) if victim.drive else f"C:{victim}"
        return absolute.replace("/", "\\") if "\\" in name else absolute.replace("\\", "/")
    return name


@pytest.mark.parametrize("name", PATH_NAMES)
@pytest.mark.parametrize("export_type", ["obj", "stl"])
def test_mesh_export_keeps_path_names_inside_destination(
    open_series, tmp_path, name, export_type,  # noqa: F811 (fixture)
):
    series = open_series("meshes")
    victim = tmp_path / f"victim.{export_type}"
    victim.write_bytes(b"keep this file")
    name = path_name(name, victim.with_suffix(""))
    original = sorted(series.data["objects"])[0]
    series.editObjectAttributes([original], name=name)
    series.setAttr(name, "3D_mode", "spheres")
    out = tmp_path / "out"
    out.mkdir()

    ev.export3DObjects(series, [name], str(out), export_type, notify_user=False)

    assert victim.read_bytes() == b"keep this file"
    files = list(out.iterdir())
    assert len(files) == 1
    assert files[0].is_file() and files[0].suffix == f".{export_type}"
    assert not any(c in files[0].name for c in "/\\:")
    mesh = ev.trimesh.load(str(files[0]), force="mesh")
    assert len(mesh.faces) > 0
    assert name in series.data["objects"]


@pytest.mark.parametrize("name", PATH_NAMES)
def test_scene_export_keeps_writes_and_cleanup_inside_scratch(
    cp, open_series, tmp_path, monkeypatch, name,  # noqa: F811 (fixtures)
):
    series = open_series("scene")
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    victim = scratch_root / "victim"
    sentinels = {victim.with_suffix(ext): f"keep {ext}" for ext in (".obj", ".mtl")}
    for path, contents in sentinels.items():
        path.write_text(contents)
    name = path_name(name, victim)
    real_temporary_directory = cp.tempfile.TemporaryDirectory
    monkeypatch.setattr(
        cp.tempfile, "TemporaryDirectory", lambda: real_temporary_directory(dir=scratch_root),
    )
    objs = cp.SceneObjectList()
    objs.add(vedo.Sphere(), series, name, "object", (255, 0, 0), 1)
    out = tmp_path / "out"
    out.mkdir()

    notes, _ = run_export(cp, objs, out / "scene.obj", monkeypatch)

    assert {p: p.read_text() for p in sentinels if p.exists()} == sentinels
    assert sorted(p.name for p in scratch_root.iterdir()) == ["victim.mtl", "victim.obj"]
    assert sorted(p.name for p in out.iterdir()) == ["scene.mtl", "scene.obj"]
    assert notes and "Scene exported" in notes[0]
    assert "Could not be exported" not in notes[0]
    for line in (out / "scene.obj").read_text().splitlines():
        if line.startswith(("o ", "usemtl ")):
            assert not any(c in line for c in "/\\:")
    mesh = ev.trimesh.load(str(out / "scene.obj"), force="mesh")
    assert len(mesh.faces) > 0


def test_mesh_export_keeps_objects_whose_filenames_collide(open_series, tmp_path):  # noqa: F811 (fixture)
    series = open_series("collisions")
    names = ["a/b", r"a\b", "a_b", "A_B", "a_b_2"]
    for original, name in zip(sorted(series.data["objects"]), names):
        series.editObjectAttributes([original], name=name)
        series.setAttr(name, "3D_mode", "spheres")
    out = tmp_path / "out"
    out.mkdir()

    ev.export3DObjects(series, names, str(out), "obj", notify_user=False)

    files = list(out.iterdir())
    assert len(files) == len(names)
    assert len({p.name.casefold() for p in files}) == len(names)
    for path in files:
        assert len(ev.trimesh.load(str(path), force="mesh").faces) > 0


def test_scene_export_keeps_objects_whose_filenames_collide(
    cp, open_series, tmp_path, monkeypatch,  # noqa: F811 (fixtures)
):
    series = open_series("collisions")
    names = ["a/b", r"a\b", "a_b", "A_B", "a_b_2"]
    objs = cp.SceneObjectList()
    for i, name in enumerate(names):
        objs.add(vedo.Sphere(pos=(i * 3, 0, 0)), series, name, "object", (255, 0, 0), 1)

    notes, _ = run_export(cp, objs, tmp_path / "scene.obj", monkeypatch)

    assert notes and "Could not be exported" not in notes[0]
    scene = ev.trimesh.load(str(tmp_path / "scene.obj"), force="scene", group_material=False)
    assert len(scene.geometry) == len(names)
    materials = [
        line for line in (tmp_path / "scene.mtl").read_text().splitlines()
        if line.startswith("newmtl ")
    ]
    assert len({line.casefold() for line in materials}) == len(names)


def test_mesh_export_does_not_follow_an_existing_symlink(open_series, tmp_path):  # noqa: F811 (fixture)
    series = open_series("symlink")
    name = sorted(series.data["objects"])[0]
    series.setAttr(name, "3D_mode", "spheres")
    victim = tmp_path / "victim.obj"
    victim.write_text("keep this file")
    out = tmp_path / "out"
    out.mkdir()
    try:
        (out / f"{name}.obj").symlink_to(victim)
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.ENOSYS):
            pytest.skip("This host cannot create symbolic links")
        raise

    with pytest.raises(ValueError, match="symbolic link"):
        ev.export3DObjects(series, [name], str(out), "obj", notify_user=False)

    assert victim.read_text() == "keep this file"
