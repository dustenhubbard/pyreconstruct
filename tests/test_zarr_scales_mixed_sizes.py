"""Scaled images from a folder of mixed image sizes (fork #608).

``zarree-2.py`` made the scale groups up front from the first image alone.
When a later image was big enough to need more scales, writing its
``scale_2`` raised ``KeyError`` and the Zarr was left with only ``scale_1``.

The converter imports only cv2 and zarr, so running it in a subprocess never
touches PyReconstruct settings.
"""
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import zarr

import PyReconstruct

CONVERTER = (
    Path(PyReconstruct.__file__).parent
    / "assets" / "scripts" / "convert_zarr" / "zarree-2.py"
)


def _images(folder):
    folder.mkdir()
    ## sorted by name, so the small one comes first
    cv2.imwrite(str(folder / "a.png"), np.full((512, 512), 100, np.uint8))
    cv2.imwrite(str(folder / "b.png"), np.full((2048, 2048), 150, np.uint8))


def _run(*args):
    return subprocess.run(
        [sys.executable, str(CONVERTER), "2", *map(str, args)],
        capture_output=True, text=True, timeout=300, env=dict(os.environ),
    )


def _layout(zarr_fp):
    zg = zarr.open(str(zarr_fp), "r")
    return {
        name: sorted(zg[name].array_keys())
        for name in sorted(zg.group_keys())
    }


EXPECTED = {
    "scale_1": ["a.png", "b.png"],
    "scale_2": ["b.png"],
    "scale_4": ["b.png"],
}


def test_new_zarr_from_mixed_sizes(tmp_path):
    _images(tmp_path / "imgs")
    out = tmp_path / "out.zarr"

    result = _run(tmp_path / "imgs", out)

    assert result.returncode == 0, result.stderr[-2000:]
    assert _layout(out) == EXPECTED
    assert zarr.open(str(out), "r")["scale_4"]["b.png"].shape == (512, 512)


def test_update_scales_with_mixed_sizes(tmp_path):
    out = tmp_path / "out.zarr"
    zg = zarr.group(str(out))
    zg.create_group("scale_1")
    zg["scale_1"].create_dataset("a.png", data=np.full((512, 512), 1, np.uint8))
    zg["scale_1"].create_dataset("b.png", data=np.full((2048, 2048), 2, np.uint8))

    result = _run(out)

    assert result.returncode == 0, result.stderr[-2000:]
    assert _layout(out) == EXPECTED
