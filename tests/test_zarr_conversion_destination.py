"""Creating scaled images must preserve an existing destination."""

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
import zarr

import PyReconstruct


CONVERTER = (
    Path(PyReconstruct.__file__).parent
    / "assets" / "scripts" / "convert_zarr" / "zarree-2.py"
)


def _snapshot(output):
    return {
        path.relative_to(output): path.read_bytes()
        for path in output.rglob("*") if path.is_file()
    }


def _run(images, output, setup=None):
    args = [str(CONVERTER), "1", str(images), str(output)]
    if setup is not None:
        args = ["-c", setup + (
            "\nimport runpy, sys\n"
            "sys.argv = sys.argv[1:]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n"
        ), *args]
    return subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("source", ["empty", "unreadable", "valid"])
def test_conversion_preserves_existing_zarr(tmp_path, source):
    images = tmp_path / "images"
    images.mkdir()
    if source == "unreadable":
        (images / "image.png").write_bytes(b"not an image")
    elif source == "valid":
        cv2.imwrite(str(images / "image.png"), np.full((32, 32), 7, np.uint8))
    output = tmp_path / "output.zarr"
    existing = zarr.group(str(output))
    existing.create_dataset("original", data=np.array([17, 29], dtype=np.uint8))
    before = _snapshot(output)

    result = _run(images, output)

    assert result.returncode != 0
    assert _snapshot(output) == before
    assert "already exists" in result.stderr


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling"])
def test_conversion_refuses_any_existing_path(tmp_path, kind):
    images = tmp_path / "images"
    images.mkdir()
    cv2.imwrite(str(images / "image.png"), np.full((32, 32), 7, np.uint8))
    output = tmp_path / "output.zarr"
    if kind == "file":
        output.write_bytes(b"original file")
    elif kind == "directory":
        output.mkdir()
    else:
        if sys.platform == "win32":
            pytest.skip("creating symlinks requires Windows privileges")
        target = tmp_path / "target"
        if kind == "symlink":
            target.mkdir()
        output.symlink_to(target, target_is_directory=True)
    before = _snapshot(tmp_path)

    result = _run(images, output)

    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert _snapshot(tmp_path) == before
    if kind in ("symlink", "dangling"):
        assert output.is_symlink()
        assert target.exists() is (kind == "symlink")
    else:
        assert output.exists()


@pytest.mark.parametrize("source", ["empty", "unreadable", "later_unreadable"])
def test_invalid_images_do_not_create_a_destination(tmp_path, source):
    images = tmp_path / "images"
    images.mkdir()
    if source == "later_unreadable":
        cv2.imwrite(str(images / "a.png"), np.full((32, 32), 7, np.uint8))
    if source != "empty":
        (images / "b.png").write_bytes(b"not an image")
    output = tmp_path / "output.zarr"

    result = _run(images, output)

    assert result.returncode != 0
    assert "No image files" in result.stderr or "not an image file" in result.stderr
    assert not output.exists()


def test_insufficient_space_does_not_create_a_destination(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    cv2.imwrite(str(images / "image.png"), np.full((32, 32), 7, np.uint8))
    output = tmp_path / "output.zarr"

    result = _run(images, output, setup=(
        "import shutil, types\n"
        "shutil.disk_usage = lambda path: types.SimpleNamespace(free=0)\n"
    ))

    assert result.returncode != 0
    assert "Not enough free disk space" in result.stderr
    assert not output.exists()


def test_destination_created_during_validation_is_preserved(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    cv2.imwrite(str(images / "image.png"), np.full((32, 32), 7, np.uint8))
    output = tmp_path / "output.zarr"
    result = _run(images, output, setup=(
        "import shutil, sys\n"
        "from pathlib import Path\n"
        "original_disk_usage = shutil.disk_usage\n"
        "def create_destination(path):\n"
        "    output = Path(sys.argv[-1])\n"
        "    output.mkdir(exist_ok=True)\n"
        "    (output / 'original').write_bytes(b'keep this')\n"
        "    return original_disk_usage(path)\n"
        "shutil.disk_usage = create_destination\n"
    ))

    assert result.returncode != 0
    assert _snapshot(output) == {Path("original"): b"keep this"}


@pytest.mark.gui
@pytest.mark.parametrize("selection", ["output", "output.zarr", "fresh"])
def test_menu_checks_the_final_suffixed_destination(
    main_window, main_window_dialogs, monkeypatch, tmp_path, selection,
):
    from PyReconstruct.modules.gui.main import main_window as mw

    images = tmp_path / "images"
    images.mkdir()
    cv2.imwrite(str(images / "image.png"), np.full((32, 32), 7, np.uint8))
    main_window.series.src_dir = str(images)
    main_window.field.section.src = "image.png"
    main_window.field.reloadImage()
    assert main_window.field.section_layer.image_found
    output = tmp_path / "output.zarr"
    zarr.group(str(output)).create_dataset("original", data=[17, 29])
    before = _snapshot(output)
    main_window_dialogs.file_responses.append(str(tmp_path / selection))
    main_window_dialogs.notices.clear()
    started = []
    monkeypatch.setattr(mw.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))

    main_window.zarrimage_act.trigger()

    assert _snapshot(output) == before
    if selection == "fresh":
        assert len(started) == 1
        assert started[0][-1] == str(tmp_path / "fresh.zarr")
        assert main_window_dialogs.notices == []
    else:
        assert started == []
        assert len(main_window_dialogs.notices) == 1
        assert str(output) in main_window_dialogs.notices[0]
        assert "already exists" in main_window_dialogs.notices[0]
