"""Each conversion worker writes its own arrays to the Zarr.

``zarree-2.py`` workers read, resize and write one image each, so the main
process only creates the store, counts progress and validates. Two things come
with that: a scale group that only a larger image needs is created by whichever
worker gets there first, and a worker that fails must still fail the run.

The converter parses ``sys.argv`` and pins thread pools on import, so it runs
in a subprocess here, as in the other converter tests.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import cv2
import numpy as np
import zarr

import PyReconstruct

CONVERTER = (
    Path(PyReconstruct.__file__).parent
    / "assets" / "scripts" / "convert_zarr" / "zarree-2.py"
)


def _run(cores, *args):
    return subprocess.run(
        [sys.executable, str(CONVERTER), str(cores), *map(str, args)],
        capture_output=True, text=True, timeout=300, env=dict(os.environ),
    )


def test_workers_create_a_missing_scale_group_together(tmp_path):
    """The first image is small, so only scale_1 exists when the Pool starts.
    Five workers then race to create scale_2 and scale_4 for the larger ones."""
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    cv2.imwrite(str(imgs / "a.png"), np.full((512, 512), 7, np.uint8))
    big = {}
    for i in range(10):
        arr = np.random.default_rng(i).integers(0, 256, (2048, 2048), np.uint8)
        name = f"b{i}.png"
        cv2.imwrite(str(imgs / name), arr)
        big[name] = arr
    out = tmp_path / "out.zarr"

    result = _run(5, imgs, out)

    assert result.returncode == 0, result.stderr[-2000:]
    zg = zarr.open(str(out), "r")
    assert sorted(zg.group_keys()) == ["scale_1", "scale_2", "scale_4"]
    assert sorted(zg["scale_2"].array_keys()) == sorted(big)
    for name, arr in big.items():
        assert np.array_equal(zg["scale_1"][name][:], arr), name
        assert np.array_equal(zg["scale_2"][name][:], cv2.resize(arr, (1024, 1024))), name
    assert result.stdout.count("@@PROGRESS@@ STEP") == 11


def test_losing_the_group_race_opens_the_existing_group(tmp_path):
    """require_group checks for the group and then creates it. If another
    worker creates it in between, zarr raises ContainsGroupError, and the
    converter must use the group that is now there."""
    out = tmp_path / "x.zarr"
    code = textwrap.dedent(f"""
        import sys, importlib.util
        import zarr, zarr.hierarchy
        sys.argv = ["zarree-2.py", "1", {str(out)!r}]
        spec = importlib.util.spec_from_file_location("zarree_under_test", {str(CONVERTER)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        zg = zarr.group({str(out)!r})
        zg.create_group("scale_2")
        # the first check runs before the other worker creates the group
        real = zarr.hierarchy.contains_group
        calls = []
        def stale_once(*a, **k):
            calls.append(1)
            return False if len(calls) == 1 else real(*a, **k)
        zarr.hierarchy.contains_group = stale_once
        group = mod.require_scale_group(zg, "scale_2")
        assert group.path == "scale_2", group.path
        print("OK")
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert r.stdout.strip().endswith("OK"), r.stdout


def test_a_failing_worker_fails_the_run(tmp_path):
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    cv2.imwrite(str(imgs / "a.png"), np.full((512, 512), 7, np.uint8))
    (imgs / "b.png").write_bytes(b"not an image")
    out = tmp_path / "out.zarr"

    result = _run(2, imgs, out)

    assert result.returncode != 0
    assert "b.png is not an image file." in result.stderr
    assert "Zarr validation complete." not in result.stdout
