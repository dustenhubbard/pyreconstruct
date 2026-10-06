"""Each conversion worker writes its own arrays to the Zarr.

``zarree-2.py`` workers read, resize and write one image each, so the main
process only creates the store, counts progress and validates. Three things
come with that: a scale group that only a larger image needs is created by
whichever worker gets there first, a worker that fails must still fail the run,
and an array cut off partway (its own worker failed, or the Pool terminated it)
must never be listed, so the next update writes it again.

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


def _run(cores, *args, env=None):
    return subprocess.run(
        [sys.executable, str(CONVERTER), str(cores), *map(str, args)],
        capture_output=True, text=True, timeout=300,
        env=dict(os.environ) if env is None else env,
    )


# Loaded by every process of the converter run (main and spawned workers)
# through PYTHONPATH. It finds an array by the shape in its .zarray, so it
# works wherever the converter puts the array while writing it.
#  - FAIL_SHAPE: the second chunk write raises OSError, like a full disk,
#    once the HOLD_SHAPE array has started writing.
#  - HOLD_SHAPE: the second chunk write waits, so that array is still being
#    written when the Pool is torn down.
FAULTS = textwrap.dedent("""
    import json, os, time
    import zarr.storage

    _orig = zarr.storage.DirectoryStore.__setitem__
    _count = {}

    def _shape(store, key):
        meta = os.path.join(store.path, os.path.dirname(key), ".zarray")
        try:
            with open(meta) as f:
                return ",".join(map(str, json.load(f)["shape"]))
        except OSError:
            return None

    def _setitem(self, key, value):
        if not os.path.basename(key).startswith("."):
            shape = _shape(self, key)
            marker = os.environ["FAULT_MARKER"]
            if shape in (os.environ["FAIL_SHAPE"], os.environ["HOLD_SHAPE"]):
                _count[shape] = _count.get(shape, 0) + 1
            if shape == os.environ["HOLD_SHAPE"] and _count[shape] == 2:
                open(marker, "w").close()
                time.sleep(60)
            if shape == os.environ["FAIL_SHAPE"] and _count[shape] == 2:
                deadline = time.time() + 15
                while not os.path.exists(marker) and time.time() < deadline:
                    time.sleep(0.05)
                raise OSError("simulated full disk")
        return _orig(self, key, value)

    zarr.storage.DirectoryStore.__setitem__ = _setitem
""")


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
    assert sorted(zg["scale_4"].array_keys()) == sorted(big)
    assert sorted(zg["scale_1"].array_keys()) == ["a.png", *sorted(big)]
    for name, arr in big.items():
        assert np.array_equal(zg["scale_1"][name][:], arr), name
        assert np.array_equal(zg["scale_2"][name][:], cv2.resize(arr, (1024, 1024))), name
        assert np.array_equal(zg["scale_4"][name][:], cv2.resize(arr, (512, 512))), name
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


def _expected_levels(arr):
    """The levels the converter makes from a scale_1 array, by scale name."""
    levels = {"scale_1": arr}
    h, w = arr.shape
    exp = 0
    while h * w >= 1024**2:
        h, w, exp = round(h / 2), round(w / 2), exp + 1
        levels[f"scale_{2**exp}"] = cv2.resize(arr, (w, h))
    return levels


def _assert_only_whole_arrays(out, sources):
    """Every array the zarr lists holds exactly the pixels it should."""
    zg = zarr.open(str(out), "r")
    for scale in zg.group_keys():
        for name in zg[scale].array_keys():
            stored = zg[scale][name]
            expected = _expected_levels(sources[name])[scale]
            assert stored.nchunks_initialized == stored.nchunks, f"{scale}/{name}"
            assert stored.dtype == np.uint8, f"{scale}/{name}"
            assert np.array_equal(stored[:], expected), f"{scale}/{name}"


def test_a_write_cut_short_is_redone_by_the_next_update(tmp_path):
    """Updating scales, b3's worker fails partway through writing scale_2
    (as on a full disk) while b4's worker is also partway through scale_2,
    so leaving the Pool terminates it mid-write. Neither half-written array
    may be listed, and running the update again must produce every level."""
    out = tmp_path / "out.zarr"
    sources = {}
    zg = zarr.group(str(out))
    scale_1 = zg.create_group("scale_1")
    shapes = {"b3.png": (2048, 1536), "b4.png": (1536, 2048)}
    for i in range(6):
        name = f"b{i}.png"
        arr = np.random.default_rng(i).integers(
            0, 256, shapes.get(name, (2048, 2048)), np.uint8
        )
        scale_1.create_dataset(name, data=arr)
        sources[name] = arr

    faults = tmp_path / "faults"
    faults.mkdir()
    (faults / "sitecustomize.py").write_text(FAULTS)
    marker = tmp_path / "b4-is-writing"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(faults), *filter(None, [env.get("PYTHONPATH")])]
    )
    env.update(
        FAIL_SHAPE="1024,768", HOLD_SHAPE="768,1024", FAULT_MARKER=str(marker)
    )

    failed = _run(5, out, env=env)

    assert failed.returncode != 0
    assert "simulated full disk" in failed.stderr
    assert "Zarr validation complete." not in failed.stdout
    assert marker.exists(), "b4 was not being written when b3 failed"
    _assert_only_whole_arrays(out, sources)
    zg = zarr.open(str(out), "r")
    assert "b3.png" not in zg["scale_2"]
    assert "b4.png" not in zg["scale_2"]
    assert sorted(os.listdir(out)) == [".zgroup", "scale_1", "scale_2", "scale_4"]

    retried = _run(5, out)

    assert retried.returncode == 0, retried.stderr[-2000:]
    assert "Zarr validation complete." in retried.stdout
    _assert_only_whole_arrays(out, sources)
    zg = zarr.open(str(out), "r")
    assert sorted(zg.group_keys()) == ["scale_1", "scale_2", "scale_4"]
    assert sorted(zg["scale_1"].array_keys()) == sorted(sources)
    assert sorted(zg["scale_2"].array_keys()) == sorted(sources)
    assert sorted(zg["scale_4"].array_keys()) == [
        name for name in sorted(sources) if name not in shapes
    ]
    for name, arr in sources.items():
        for scale, expected in _expected_levels(arr).items():
            assert zg[scale][name].shape == expected.shape, f"{scale}/{name}"
    assert sorted(os.listdir(out)) == [".zgroup", "scale_1", "scale_2", "scale_4"]
