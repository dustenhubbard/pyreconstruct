"""Each conversion worker writes its own arrays to the Zarr.

``zarree-2.py`` workers read, resize and write one image each, so the main
process only creates the store, counts progress and validates. Three things
come with that: a scale group that only a larger image needs is created by
whichever worker gets there first, a worker that fails must still fail the run,
and an array cut off partway (its own worker failed, or the Pool terminated it)
must never be listed, so the next update writes it again. A scale_1 array cut
off that way has no source to write it from, so the update must stop there.

The converter parses ``sys.argv`` and pins thread pools on import, so it runs
in a subprocess here, as in the other converter tests.
"""
import os
import subprocess
import sys
import textwrap
import time
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


def _run(cores, *args, env=None):
    return subprocess.run(
        [sys.executable, str(CONVERTER), str(cores), *map(str, args)],
        capture_output=True, text=True, timeout=300,
        env=dict(os.environ) if env is None else env,
    )


# Loaded by every process of the converter run (main and spawned workers)
# through PYTHONPATH. It names an array by its place in the zarr, e.g.
# "scale_2/b3.png", or by its shape, e.g. "1024,768", read from a .zarray
# already beside the chunk (an array built somewhere else before it is moved
# into place), and counts that array's chunk writes.
#  - FAIL_ARRAY: the second chunk write raises OSError, like a full disk,
#    once the HOLD_ARRAY array (if any) has started writing.
#  - HOLD_ARRAY: the second chunk write creates FAULT_MARKER and waits until
#    FAULT_RELEASE exists, so that array is part written in the meantime.
#  - WRITE_LOG: the path of every store key written is appended to this file.
FAULTS = textwrap.dedent("""
    import json, os, time
    import zarr.storage

    _orig = zarr.storage.DirectoryStore.__setitem__
    _count = {}

    def _wait_for(path, seconds):
        deadline = time.time() + seconds
        # with no path to wait for, wait the whole time
        while not (path and os.path.exists(path)) and time.time() < deadline:
            time.sleep(0.05)

    def _shape(array):
        try:
            with open(array + "/.zarray") as f:
                return ",".join(map(str, json.load(f)["shape"]))
        except OSError:
            return None

    def _setitem(self, key, value):
        path = os.path.join(self.path, key).replace(os.sep, "/")
        log = os.environ.get("WRITE_LOG")
        if log:
            with open(log, "a") as f:
                f.write(path + "\\n")
        array, name = path.rsplit("/", 1)
        if not name.startswith("."):
            for role in ("FAIL_ARRAY", "HOLD_ARRAY"):
                target = os.environ.get(role)
                shape = os.environ.get(role + "_SHAPE")
                if not (
                    (target and array.endswith("/" + target))
                    or (shape and _shape(array) == shape)
                ):
                    continue
                _count[role] = _count.get(role, 0) + 1
                if _count[role] != 2:
                    continue
                if role == "HOLD_ARRAY":
                    open(os.environ["FAULT_MARKER"], "w").close()
                    _wait_for(os.environ.get("FAULT_RELEASE"), 120)
                else:
                    if os.environ.get("HOLD_ARRAY"):
                        _wait_for(os.environ["FAULT_MARKER"], 15)
                    raise OSError("simulated full disk")
        return _orig(self, key, value)

    zarr.storage.DirectoryStore.__setitem__ = _setitem
""")


def _fault_env(tmp_path, **settings):
    """Environment for a converter run with FAULTS loaded."""
    faults = tmp_path / "faults"
    faults.mkdir(exist_ok=True)
    (faults / "sitecustomize.py").write_text(FAULTS)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(faults), *filter(None, [env.get("PYTHONPATH")])]
    )
    env.update({k: str(v) for k, v in settings.items()})
    return env


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


def _scale_1_only(out, shapes=None):
    """A zarr holding scale_1 alone, ready for an update; returns its arrays."""
    shapes = shapes or {}
    sources = {}
    scale_1 = zarr.group(str(out)).create_group("scale_1")
    for i in range(6):
        name = f"b{i}.png"
        arr = np.random.default_rng(i).integers(
            0, 256, shapes.get(name, (2048, 2048)), np.uint8
        )
        scale_1.create_dataset(name, data=arr)
        sources[name] = arr
    return sources


def _assert_every_level(out, sources):
    """The zarr holds every level of every image and nothing else."""
    _assert_only_whole_arrays(out, sources)
    zg = zarr.open(str(out), "r")
    expected = {}
    for name, arr in sources.items():
        for scale in _expected_levels(arr):
            expected.setdefault(scale, []).append(name)
    assert sorted(zg.group_keys()) == sorted(expected)
    for scale, names in expected.items():
        assert sorted(zg[scale].array_keys()) == sorted(names), scale
    assert sorted(os.listdir(out)) == [".zgroup", *sorted(expected)]


def test_a_write_cut_short_is_redone_by_the_next_update(tmp_path):
    """Updating scales, b3's worker fails partway through writing scale_2
    (as on a full disk) while b4's worker is also partway through scale_2,
    so leaving the Pool terminates it mid-write. Neither half-written array
    may be listed, and running the update again must produce every level."""
    out = tmp_path / "out.zarr"
    shapes = {"b3.png": (2048, 1536), "b4.png": (1536, 2048)}
    sources = _scale_1_only(out, shapes)
    marker = tmp_path / "b4-is-writing"
    env = _fault_env(
        tmp_path, FAIL_ARRAY="scale_2/b3.png", FAIL_ARRAY_SHAPE="1024,768",
        HOLD_ARRAY="scale_2/b4.png", HOLD_ARRAY_SHAPE="768,1024",
        FAULT_MARKER=marker,
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
    _assert_every_level(out, sources)


def test_an_update_writes_into_a_folder_left_without_metadata(tmp_path):
    """A write that stopped before its .zarray leaves a folder zarr does not
    count as an array: empty, or holding chunks and a temporary file. The
    next update must write the array there and finish."""
    out = tmp_path / "out.zarr"
    sources = _scale_1_only(out)
    zarr.open(str(out), "a").create_group("scale_2")
    (out / "scale_2" / "b1.png").mkdir()
    stale = out / "scale_2" / "b2.png"
    stale.mkdir()
    (stale / "0.0").write_bytes(b"not a chunk")
    (stale / ".zarray.0123abcd.partial").write_bytes(b"{")

    result = _run(5, out)

    assert result.returncode == 0, result.stderr[-2000:]
    assert "Zarr validation complete." in result.stdout
    _assert_every_level(out, sources)


def test_an_update_refuses_a_scale_1_image_left_unfinished(tmp_path):
    """A conversion from images stops partway through scale_1/b.png, after
    a.png is done. b.png's folder has chunks but no .zarray, so zarr lists
    only a.png. The update has no source to rebuild b.png from, so it must
    fail and name it, not finish without it."""
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    cv2.imwrite(str(imgs / "a.png"), np.full((512, 512), 7, np.uint8))
    cv2.imwrite(
        str(imgs / "b.png"),
        np.random.default_rng(0).integers(0, 256, (2048, 2048), np.uint8),
    )
    out = tmp_path / "out.zarr"

    # one worker, so a.png is done before b.png starts
    failed = _run(1, imgs, out, env=_fault_env(tmp_path, FAIL_ARRAY="scale_1/b.png"))

    assert failed.returncode != 0
    assert "simulated full disk" in failed.stderr
    assert (out / "scale_1" / "b.png").is_dir()
    assert list(zarr.open(str(out), "r")["scale_1"]) == ["a.png"]

    update = _run(1, out)

    assert update.returncode != 0
    assert "Zarr validation complete." not in update.stdout
    assert "scale_1/b.png" in update.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="a backslash is a separator")
def test_a_name_with_a_backslash_is_stored_as_zarr_stores_it(tmp_path):
    """zarr reads a backslash in an array name as a separator, so the image
    a\\b.png is stored as scale_1/a/b.png. The converter must put its files
    where zarr looks for them: the same files create_dataset makes."""
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    name = "a\\b.png"
    arr = np.random.default_rng(0).integers(0, 256, (1024, 1024), np.uint8)
    cv2.imwrite(str(imgs / name), arr)
    out = tmp_path / "out.zarr"

    result = _run(1, imgs, out)

    assert result.returncode == 0, result.stderr[-2000:]
    reference = zarr.group(str(tmp_path / "reference.zarr"))
    for scale, level in _expected_levels(arr).items():
        reference.require_group(scale).create_dataset(name, data=level)
    zg = zarr.open(str(out), "r")
    for scale, level in _expected_levels(arr).items():
        assert np.array_equal(zg[scale][name][:], level), scale

    def files(root):
        return sorted(
            os.path.relpath(os.path.join(d, f), root)
            for d, _dirs, fs in os.walk(root) for f in fs
        )
    assert files(out) == files(tmp_path / "reference.zarr")


def test_two_updates_of_one_zarr_at_once_both_finish(tmp_path):
    """Run B is part way through scale_2/b3.png while run A updates the same
    zarr from start to finish. Neither run may undo the other's work."""
    out = tmp_path / "out.zarr"
    sources = _scale_1_only(out, {"b3.png": (2048, 1536)})
    marker = tmp_path / "b-is-writing"
    release = tmp_path / "release-b"
    env = _fault_env(
        tmp_path, HOLD_ARRAY="scale_2/b3.png", HOLD_ARRAY_SHAPE="1024,768",
        FAULT_MARKER=marker, FAULT_RELEASE=release,
    )
    run_b = subprocess.Popen(
        [sys.executable, str(CONVERTER), "5", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        deadline = time.time() + 120
        while not marker.exists() and time.time() < deadline:
            assert run_b.poll() is None, run_b.communicate()
            time.sleep(0.05)
        assert marker.exists(), "run B never reached scale_2/b3.png"

        run_a = _run(5, out)
        release.touch()
        b_out, b_err = run_b.communicate(timeout=300)
    finally:
        release.touch()
        if run_b.poll() is None:
            run_b.kill()
            run_b.communicate()

    assert run_a.returncode == 0, run_a.stderr[-2000:]
    assert "Zarr validation complete." in run_a.stdout
    assert run_b.returncode == 0, b_err[-2000:]
    assert "Zarr validation complete." in b_out
    _assert_every_level(out, sources)


def test_the_store_writes_only_files_of_the_finished_zarr(tmp_path):
    """Every key the converter writes through the store is a file of the
    finished zarr: nothing is built in another folder and moved in. This
    sees store keys, not the temporary file zarr writes beside each one
    before renaming it."""
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    for i, shape in enumerate([(2048, 2048), (1500, 1499)]):
        arr = np.random.default_rng(i).integers(0, 256, shape, np.uint8)
        cv2.imwrite(str(imgs / f"s{i}.png"), arr)
    out = tmp_path / "out.zarr"
    log = tmp_path / "writes.txt"

    result = _run(2, imgs, out, env=_fault_env(tmp_path, WRITE_LOG=log))

    assert result.returncode == 0, result.stderr[-2000:]
    written = set(log.read_text().split())
    on_disk = {
        os.path.join(root, f).replace(os.sep, "/")
        for root, _dirs, files in os.walk(out)
        for f in files
    }
    assert written == on_disk

