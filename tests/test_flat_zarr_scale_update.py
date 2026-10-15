"""The scale update is not offered or started for a zarr in the flat layout.

PyReconstruct shows a flat zarr (each image an array at the root, no scale_N
folders) as it is, with one scale, so the section layer reports it unscaled.
The scale update (zarree-2.py) reads scale_1 and stops with KeyError 'scale_1'
on that layout. So the "Zarr Scaling" question is not asked for it, and
`Series > Update image scales` explains why instead of starting the converter.
A scale-layout zarr with only scale_1 still gets both.
"""
import os

import numpy as np
import pytest

pytestmark = pytest.mark.gui

IW, IH = 64, 48


def _flat(tmp_path):
    import zarr

    fp = str(tmp_path / "images.zarr")
    group = zarr.open_group(fp, mode="w")
    for name in ("img.png", "other.png"):
        group.create_dataset(name, data=np.full((IH, IW), 90, "u1"))
    return fp


def _scale_1_only(tmp_path):
    import zarr

    fp = str(tmp_path / "images.zarr")
    scale = zarr.open_group(fp, mode="w").create_group("scale_1")
    for name in ("img.png", "other.png"):
        scale.create_dataset(name, data=np.full((IH, IW), 90, "u1"))
    return fp


def _snapshot(folder):
    found = {}
    for root, dirs, files in os.walk(folder):
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                found[os.path.relpath(os.path.join(root, f), folder)] = fh.read()
    return found


@pytest.fixture
def on_screen(monkeypatch):
    """A user at the screen, so the prompts are allowed to show."""
    from PyReconstruct.modules.gui.utils import utils as gui_utils

    monkeypatch.delenv(gui_utils.UNATTENDED_ENV_VAR, raising=False)
    monkeypatch.setattr(gui_utils, "qt_offscreen", False)


@pytest.fixture
def started(monkeypatch):
    """Every process the main window starts, recorded and never run."""
    from PyReconstruct.modules.gui.main import main_window as mw

    calls = []
    monkeypatch.setattr(
        mw.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd)
    )
    return calls


def _show(main_window, fp):
    """Point the series at the zarr and show img.png on the current section."""
    main_window.series.src_dir = fp
    main_window.field.section.src = "img.png"
    main_window.field.reloadImage()
    assert main_window.field.section_layer.image_found
    assert not main_window.field.section_layer.is_scaled


def _scaling_prompts(dialogs):
    return [box for box in dialogs.message_boxes if box[0] == "Zarr Scaling"]


@pytest.mark.parametrize("make, asked", [(_flat, False), (_scale_1_only, True)])
def test_the_scaling_question_after_the_images_are_found(
    main_window, main_window_dialogs, on_screen, tmp_path, make, asked
):
    fp = make(tmp_path)
    _show(main_window, fp)
    main_window_dialogs.message_boxes.clear()

    main_window._ensureImagesAvailable()

    assert bool(_scaling_prompts(main_window_dialogs)) is asked


@pytest.mark.parametrize("make, asked", [(_flat, False), (_scale_1_only, True)])
def test_the_scaling_question_after_the_image_folder_changes(
    main_window, main_window_dialogs, on_screen, tmp_path, make, asked
):
    fp = make(tmp_path)
    main_window.field.section.src = "img.png"
    main_window_dialogs.message_boxes.clear()

    main_window.changeSrcDir(fp)

    assert main_window.field.section_layer.image_found
    assert bool(_scaling_prompts(main_window_dialogs)) is asked


def test_update_image_scales_on_a_flat_zarr_explains_and_starts_nothing(
    main_window, main_window_dialogs, started, tmp_path
):
    fp = _flat(tmp_path)
    _show(main_window, fp)
    before = _snapshot(fp)
    main_window_dialogs.notices.clear()

    main_window.scalezarr_act.trigger()

    assert started == []
    assert len(main_window_dialogs.notices) == 1
    notice = main_window_dialogs.notices[0]
    assert "older layout" in notice and "scale_N" in notice
    assert _snapshot(fp) == before


def test_update_image_scales_on_a_scale_layout_zarr_starts_the_converter(
    main_window, main_window_dialogs, started, tmp_path
):
    fp = _scale_1_only(tmp_path)
    _show(main_window, fp)
    main_window_dialogs.notices.clear()

    main_window.scalezarr_act.trigger()

    assert main_window_dialogs.notices == []
    assert len(started) == 1
    assert started[0][-3] == "convert_zarr"
    assert started[0][-1] == fp
