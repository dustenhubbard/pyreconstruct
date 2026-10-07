"""``dev/assets/misc/crop_zarr.py`` runs from flags, without prompts or dialogs.

With flags it opens a copy of the jser in a temp folder, prints the converter's
``@@PROGRESS@@`` lines, and checks its inputs before it writes anything, so
another program can call it. With no arguments it still asks the same four
questions.

Every run here is a subprocess, the way a wrapper program would call it.
"""

import importlib.util
import json
import ntpath
import os
import posixpath
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import zarr


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "dev" / "assets" / "misc" / "crop_zarr.py"
SHAPES = REPO_ROOT / "dev" / "assets" / "checker" / "files" / "shapes1.jser"

SCALES = {1: (400, 1000), 2: (200, 500)}
OBJECT = "square"
RADIUS = 0.2
## microns per pixel at scale_1, so each image is 10 x 4 microns, y up from the bottom
MAG = 0.01
## the square on each section as (xmin, ymin, xmax, ymax) in microns
SQUARES = {
    0: (1.0, 1.0, 2.0, 1.5),  # inside the image
    1: (-0.5, 3.5, 0.5, 4.5),  # over the top left corner
    3: (9.5, -0.5, 10.5, 0.5),  # over the bottom right corner
    4: (-3.0, 5.0, -1.0, 6.0),  # wholly outside, left of and above the image
}
## section 2 has no square, so its images must come out all zero
BLANK_SECTION = 2
## (top, bottom, left, right) rows and columns kept, worked out by hand from
## SQUARES, RADIUS and MAG; sections not listed keep nothing
KEPT = {
    (1, 0): (230, 320, 80, 220),
    (2, 0): (115, 160, 40, 110),
    (1, 1): (0, 70, 0, 70),
    (2, 1): (0, 35, 0, 35),
    (1, 3): (330, 400, 930, 1000),
    (2, 3): (165, 200, 465, 500),
}


def _run(args, stdin=None, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        input=stdin, capture_output=True, text=True, timeout=300,
        cwd=str(cwd or REPO_ROOT), env=dict(os.environ),
    )


@pytest.fixture
def case(tmp_path):
    """A five-section series and a two-scale zarr of nonzero images."""
    data = json.loads(SHAPES.read_text())
    for snum, section in enumerate(data["sections"]):
        section["mag"] = MAG
        if snum == BLANK_SECTION:
            del section["contours"][OBJECT]
            continue
        xmin, ymin, xmax, ymax = SQUARES[snum]
        (trace,) = section["contours"][OBJECT]
        trace[0] = [xmin, xmax, xmax, xmin]
        trace[1] = [ymin, ymin, ymax, ymax]
    src = tmp_path / "imgs.zarr"
    data["series"]["src_dir"] = str(src)

    series_dir = tmp_path / "series"
    series_dir.mkdir()
    jser = series_dir / "shapes.jser"
    jser.write_text(json.dumps(data))

    rng = np.random.default_rng(0)
    root = zarr.open_group(str(src), mode="w")
    for scale, shape in SCALES.items():
        grp = root.create_group(f"scale_{scale}")
        for section in data["sections"]:
            grp.create_dataset(
                section["src"], chunks=(64, 64),
                data=rng.integers(1, 256, shape, dtype=np.uint8),
            )
    return jser, src


def _expected(src):
    """The source images with everything outside KEPT set to zero."""
    source = zarr.open_group(str(src), mode="r")
    expected = {}
    for scale in SCALES:
        for snum in range(5):
            name = f"shapes_{snum}.tif"
            image = source[f"scale_{scale}"][name][:]
            want = np.zeros_like(image)
            if (scale, snum) in KEPT:
                t, b, l, r = KEPT[(scale, snum)]
                want[t:b, l:r] = image[t:b, l:r]
            expected[(scale, name)] = want
    return expected


def _tree(folder):
    """Every file under folder, by relative path, with its bytes."""
    folder = Path(folder)
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in sorted(folder.rglob("*")) if p.is_file()
    }


def _arrays(out):
    group = zarr.open_group(str(out), mode="r")
    return {
        (int(g.split("_")[1]), name): group[g][name][:]
        for g in group.group_keys()
        for name in group[g].array_keys()
    }


def _hidden_dirs(folder):
    return [p.name for p in Path(folder).iterdir() if p.name.startswith(".")]


def test_flags_crop_without_prompts(case):
    jser, src = case
    source_before = _tree(src)
    out = jser.parent.parent / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", out,
    ], stdin="")

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines.count("@@PROGRESS@@ TOTAL 5") == 1
    assert [l for l in lines if l.startswith("@@PROGRESS@@ STEP")] == [
        f"@@PROGRESS@@ STEP {i} 5" for i in range(1, 6)
    ]
    assert [l for l in lines if l.startswith("Cropped section")] == [
        f"Cropped section {n}" for n in range(5)
    ]
    assert lines[-1] == f"Crop complete: {out}"

    got = _arrays(out)
    want = _expected(src)
    assert got.keys() == want.keys()
    for key in want:
        np.testing.assert_array_equal(got[key], want[key], err_msg=str(key))
    assert not got[(1, f"shapes_{BLANK_SECTION}.tif")].any()
    ## a square wholly outside the image keeps nothing, at either scale
    assert not got[(1, "shapes_4.tif")].any()
    assert not got[(2, "shapes_4.tif")].any()
    assert _tree(src) == source_before

    ## nothing left beside the jser, and the default output was not made
    assert _hidden_dirs(jser.parent) == []
    assert sorted(p.name for p in jser.parent.iterdir()) == ["shapes.jser"]
    assert not (src.parent / f"imgs_{OBJECT}_crop.zarr").exists()


def _stored_chunks(out, scale, name):
    """Chunk files on disk for one output array (metadata files excluded)."""
    folder = Path(out) / f"scale_{scale}" / name
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def _touched_chunks(window, size=64):
    """The chunk file names a (top, bottom, left, right) window overlaps."""
    t, b, l, r = window
    return sorted(
        f"{row}.{col}"
        for row in range(t // size, (b - 1) // size + 1)
        for col in range(l // size, (r - 1) // size + 1)
    )


def test_all_zero_chunks_are_not_written(case):
    """Only chunks that hold part of the object are stored; the rest read as 0."""
    jser, src = case
    out = jser.parent.parent / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", out,
    ])
    assert result.returncode == 0, result.stderr

    group = zarr.open_group(str(out), mode="r")
    for (scale, name), expected in _expected(src).items():
        array = group[f"scale_{scale}"][name]
        assert array.fill_value == 0
        assert array.shape == SCALES[scale]
        np.testing.assert_array_equal(array[:], expected, err_msg=str((scale, name)))

        snum = int(name.split("_")[1].split(".")[0])
        window = KEPT.get((scale, snum))
        want = _touched_chunks(window) if window else []
        assert _stored_chunks(out, scale, name) == want, (scale, name)
        assert len(want) < array.nchunks


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_negative_zero_survives_in_float_images(case, tmp_path, dtype):
    """A chunk of -0.0 equals the fill value 0 but is still written, sign and all."""
    jser, src = case
    floats = tmp_path / "floats.zarr"
    root = zarr.open_group(str(floats), mode="w")
    for scale, shape in SCALES.items():
        grp = root.create_group(f"scale_{scale}")
        for snum in range(5):
            grp.create_dataset(
                f"shapes_{snum}.tif", chunks=(64, 64), data=np.full(shape, -0.0, dtype),
            )
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS,
        "--zarr", floats, "--out", out,
    ])
    assert result.returncode == 0, result.stderr

    got = _arrays(out)
    for scale, shape in SCALES.items():
        for snum in range(5):
            image = got[(scale, f"shapes_{snum}.tif")]
            want = np.zeros(shape, dtype)  # +0.0 outside the window
            if (scale, snum) in KEPT:
                t, b, l, r = KEPT[(scale, snum)]
                want[t:b, l:r] = -0.0
            assert image.dtype == dtype
            np.testing.assert_array_equal(
                np.signbit(image), np.signbit(want), err_msg=str((scale, snum)),
            )


def test_default_output_and_zarr_override(case, tmp_path):
    jser, src = case
    moved = tmp_path / "moved" / "imgs-zarr"
    shutil.copytree(src, moved)
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", moved,
    ])
    assert result.returncode == 0, result.stderr
    out = moved.parent / f"imgs_{OBJECT}_crop-zarr"
    assert result.stdout.splitlines()[-1] == f"Crop complete: {out}"
    assert _arrays(out).keys() == _expected(src).keys()


def test_no_arguments_still_prompts(case):
    """The four questions, answered on stdin, give the same crop as the flags."""
    jser, src = case
    flags_out = jser.parent.parent / "flags.zarr"
    assert _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", flags_out,
    ]).returncode == 0

    result = _run([], stdin=f"{jser}\n{OBJECT}\n{RADIUS}\n\n")
    assert result.returncode == 0, result.stderr
    assert "Jser filepath:" in result.stdout
    prompted = _arrays(src.parent / f"imgs_{OBJECT}_crop.zarr")
    flagged = _arrays(flags_out)
    assert prompted.keys() == flagged.keys()
    for key in flagged:
        np.testing.assert_array_equal(prompted[key], flagged[key])


def test_wrong_object_lists_close_matches(case):
    jser, src = case
    out = jser.parent.parent / "out.zarr"
    result = _run([
        "--jser", jser, "--object", "sqare", "--radius", "1", "--out", out,
    ])
    assert result.returncode != 0
    assert "'sqare' is not in this series" in result.stderr
    assert "square" in result.stderr
    assert not out.exists()
    assert _hidden_dirs(jser.parent) == []


@pytest.mark.parametrize("problem", [
    "missing jser", "missing zarr", "not a zarr", "no scales", "out is source",
])
def test_bad_inputs_stop_before_writing(case, tmp_path, problem):
    jser, src = case
    out = tmp_path / "out.zarr"
    args = {"--jser": jser, "--object": OBJECT, "--radius": "1", "--out": out}
    if problem == "missing jser":
        args["--jser"] = tmp_path / "nope.jser"
    elif problem == "missing zarr":
        args["--zarr"] = tmp_path / "nope.zarr"
    elif problem == "not a zarr":
        (tmp_path / "plain.zarr").mkdir()
        args["--zarr"] = tmp_path / "plain.zarr"
    elif problem == "no scales":
        zarr.open_group(str(tmp_path / "flat.zarr"), mode="w").create_group("other")
        args["--zarr"] = tmp_path / "flat.zarr"
    elif problem == "out is source":
        args["--out"] = str(src) + os.sep

    result = _run([x for pair in args.items() for x in pair])
    assert result.returncode != 0
    assert result.stderr.strip().startswith("error:")
    assert len(result.stderr.strip().splitlines()) == 1, result.stderr
    assert "@@PROGRESS@@" not in result.stdout
    assert not out.exists()
    assert _hidden_dirs(jser.parent) == []


def _load_script():
    """Import crop_zarr.py in this process, to call its functions directly."""
    spec = importlib.util.spec_from_file_location("crop_zarr", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _overlap_out(src, kind):
    if kind == "inside source":
        return src / "crop"
    if kind == "inside a scale group":
        return src / "scale_1" / "crop"
    if kind == "holds the source":
        return src.parent
    if kind == "inside source through a link":
        link = src.parent / "link"
        link.symlink_to(src, target_is_directory=True)
        return link / "crop"
    if kind == "source with other letter case":
        return src.parent / src.name.upper()
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", [
    "inside source", "inside a scale group", "holds the source",
    "inside source through a link", "source with other letter case",
])
def test_output_overlapping_the_source_is_refused(case, kind):
    """No output path that is, holds or sits inside the source is written."""
    if kind == "inside source through a link" and sys.platform == "win32":
        pytest.skip("symlinks need extra rights on Windows")
    jser, src = case
    out = _overlap_out(src, kind)
    if kind == "source with other letter case" and not out.exists():
        pytest.skip("case-sensitive file system")
    source_before = _tree(src)
    holder_before = sorted(p.name for p in src.parent.iterdir())

    result = _run(["--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", out])
    assert result.returncode == 1, result.stderr
    assert "source zarr" in result.stderr
    assert "@@PROGRESS@@" not in result.stdout
    assert _tree(src) == source_before
    assert sorted(p.name for p in src.parent.iterdir()) == holder_before


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need extra rights on Windows")
def test_output_path_through_a_link_and_dotdot_is_written_where_it_resolves(case, tmp_path):
    """"link/.." means the link target's parent, for the checks and the write.

    Here the path reads as inside the source but resolves outside it, so the
    crop must land outside and leave the source alone.
    """
    jser, src = case
    (tmp_path / "outside" / "deep").mkdir(parents=True)
    (src / "link").symlink_to(tmp_path / "outside" / "deep", target_is_directory=True)
    source_before = _tree(src)
    entries_before = sorted(p.name for p in src.iterdir())

    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS,
        "--out", src / "link" / ".." / "crop",
    ])
    assert result.returncode == 0, result.stderr
    assert _tree(src) == source_before
    assert sorted(p.name for p in src.iterdir()) == entries_before
    got = _arrays(tmp_path / "outside" / "crop")
    want = _expected(src)
    assert got.keys() == want.keys()
    for key in want:
        np.testing.assert_array_equal(got[key], want[key], err_msg=str(key))


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need extra rights on Windows")
def test_source_path_through_a_link_and_dotdot_reads_where_it_resolves(case, tmp_path):
    """The zarr that is read is the one the path resolves to, the one checked."""
    jser, src = case
    ## a second source whose pixels differ from the first everywhere
    other = tmp_path / "b" / "imgs.zarr"
    shutil.copytree(src, other)
    group = zarr.open_group(str(other), mode="r+")
    for scale in SCALES:
        for name in group[f"scale_{scale}"].array_keys():
            array = group[f"scale_{scale}"][name]
            array[:] = 256 - array[:].astype(np.uint16)
    (tmp_path / "b" / "sub").mkdir()
    (tmp_path / "l").symlink_to(tmp_path / "b" / "sub", target_is_directory=True)

    ## "l/../imgs.zarr" reads as the first source but resolves to the second
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS,
        "--zarr", tmp_path / "l" / ".." / "imgs.zarr", "--out", out,
    ])
    assert result.returncode == 0, result.stderr
    got = _arrays(out)
    want = _expected(other)
    assert got.keys() == want.keys()
    for key in want:
        np.testing.assert_array_equal(got[key], want[key], err_msg=str(key))


def _make_existing(out, what):
    """Put something at out; return the folder whose files must not change."""
    if what == "zarr":
        group = zarr.open_group(str(out), mode="w")
        group.create_group("scale_1").create_dataset("old.tif", data=np.full((4, 4), 7, np.uint8))
        return out
    if what == "folder named like a zarr":
        out.mkdir()
        (out / ".zgroup").write_text("not really")
        (out / "notes.txt").write_text("keep me")
        return out
    if what == "empty folder":
        out.mkdir()
        return out
    if what == "file":
        out.write_text("keep me")
        return out.parent
    if what in ("link to a folder", "link to a folder, given as link/."):
        target = out.parent / "elsewhere"
        target.mkdir()
        (target / "keep.txt").write_text("keep me")
        out.symlink_to(target, target_is_directory=True)
        return target
    raise AssertionError(what)


@pytest.mark.parametrize("what", [
    "zarr", "folder named like a zarr", "empty folder", "file",
    "link to a folder", "link to a folder, given as link/.",
])
def test_existing_output_is_refused_and_left_alone(case, what):
    """Nothing that already exists at the output path is changed or deleted."""
    if what.startswith("link") and sys.platform == "win32":
        pytest.skip("symlinks need extra rights on Windows")
    jser, src = case
    out = jser.parent.parent / "out.zarr"
    kept = _make_existing(out, what)
    before = _tree(kept)
    arg = f"{out}{os.sep}." if what.endswith("link/.") else out

    result = _run(["--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", arg])
    assert result.returncode == 1, result.stderr
    assert "already exists" in result.stderr and "Remove it" in result.stderr
    assert "@@PROGRESS@@" not in result.stdout
    assert _tree(kept) == before
    assert os.path.lexists(out)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need extra rights on Windows")
def test_dangling_output_link_is_refused(case, tmp_path):
    """A link to a missing folder is an existing entry; its target is not made."""
    jser, src = case
    out = tmp_path / "out.zarr"
    missing = tmp_path / "missing.zarr"
    out.symlink_to(missing, target_is_directory=True)
    result = _run(["--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", out])
    assert result.returncode == 1, result.stderr
    assert "already exists" in result.stderr
    assert out.is_symlink()
    assert not os.path.lexists(missing)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need extra rights on Windows")
def test_dangling_link_made_after_the_checks_is_refused(tmp_path):
    """cropSections refuses a dangling link at the output path by itself."""
    module = _load_script()
    out = tmp_path / "out.zarr"
    missing = tmp_path / "missing.zarr"
    out.symlink_to(missing, target_is_directory=True)
    with pytest.raises(module.CropError, match="already exists"):
        module.cropSections(None, OBJECT, 0, None, [1], str(out), show_progress=False)
    assert out.is_symlink()
    assert not os.path.lexists(missing)


def test_root_output_is_refused(case, tmp_path):
    """A root keeps its meaning: "/" is not trimmed to "" (the current folder)."""
    jser, src = case
    work = tmp_path / "work"
    work.mkdir()
    root = Path(tmp_path.anchor)
    result = _run(
        ["--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", root], cwd=work,
    )
    assert result.returncode == 1, result.stderr
    assert "root" in result.stderr
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("pathmod, given, kept", [
    (posixpath, "/", "/"),
    (posixpath, "//", "//"),
    (posixpath, "/data/out.zarr/", "/data/out.zarr"),
    (posixpath, "out.zarr//", "out.zarr"),
    (ntpath, "C:\\", "C:\\"),
    (ntpath, "C:/", "C:/"),
    (ntpath, "C:\\work\\out.zarr\\", "C:\\work\\out.zarr"),
    (ntpath, "\\\\server\\share\\", "\\\\server\\share\\"),
])
def test_trailing_separators_are_trimmed_but_roots_kept(pathmod, given, kept):
    assert _load_script().trimSeparators(given, pathmod) == kept


def test_output_made_after_the_checks_is_not_written_into(tmp_path):
    """If another program makes the output between the checks and the crop,
    the crop stops and leaves it alone."""
    module = _load_script()
    out = tmp_path / "out.zarr"
    out.mkdir()
    (out / "theirs.txt").write_text("keep me")
    with pytest.raises(module.CropError, match="already exists"):
        module.cropSections(None, OBJECT, 0, None, [1], str(out), show_progress=False)
    assert _tree(out) == {"theirs.txt": b"keep me"}


def test_prompts_refuse_an_existing_output(case):
    jser, src = case
    out = src.parent / f"imgs_{OBJECT}_crop.zarr"
    _make_existing(out, "zarr")
    before = _tree(out)
    result = _run([], stdin=f"{jser}\n{OBJECT}\n{RADIUS}\n\n")
    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert _tree(out) == before


def test_prompts_check_the_object_name(case):
    jser, src = case
    result = _run([], stdin=f"{jser}\nsqare\n{RADIUS}\n\n")
    assert result.returncode == 1
    assert "'sqare' is not in this series" in result.stderr
    assert not (src.parent / "imgs_sqare_crop.zarr").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM cannot be caught on Windows")
def test_sigterm_removes_the_temp_copy(case, tmp_path):
    """A SIGTERM mid-crop still removes the temp folder holding the jser copy.

    The crop step is replaced with one that sends SIGTERM to its own process,
    so the signal always arrives while the copy is open.
    """
    jser, src = case
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    code = "\n".join([
        "import importlib.util, os, signal, sys, time",
        f"spec = importlib.util.spec_from_file_location('crop_zarr', {str(SCRIPT)!r})",
        "mod = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(mod)",
        "def interrupted(*args, **kwargs):",
        f"    print('during:', sorted(os.listdir({str(temp_root)!r})), flush=True)",
        "    os.kill(os.getpid(), signal.SIGTERM)",
        "    time.sleep(30)",
        "mod.cropSections = interrupted",
        f"mod.runCli(mod.parseArgs(['--jser', {str(jser)!r}, '--object', {OBJECT!r},",
        f"    '--radius', '1', '--out', {str(tmp_path / 'out.zarr')!r}]))",
    ])
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
        cwd=str(REPO_ROOT), env={**os.environ, "TMPDIR": str(temp_root)},
    )
    assert result.returncode == 128 + 15, result.stderr
    assert "'crop_zarr_" in result.stdout
    assert [p for p in temp_root.iterdir() if p.name.startswith("crop_zarr_")] == []
    assert _hidden_dirs(jser.parent) == []


@pytest.mark.parametrize("args", [
    ["--jser", "x.jser"],
    ["--out", "x.zarr"],
    ["--jser", "x.jser", "--object", "a", "--radius", "-1"],
    ["--jser", "x.jser", "--object", "a", "--radius", "inf"],
    ["--jser", "x.jser", "--object", "a", "--radius", "1", "--overwrite"],
])
def test_incomplete_or_bad_flags_are_refused(args):
    result = _run(args)
    assert result.returncode == 2
    assert "Jser filepath" not in result.stdout
