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
## section 2 has no square, so it keeps its image inside the window of the
## nearest section with one: 1 and 3 are both one away, and the earlier wins
BLANK_SECTION = 2
FILLED_FROM = {BLANK_SECTION: 1}
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


def _window(scale, snum, fill=True):
    """The window a section keeps: its own, or with fill its neighbor's."""
    if fill and snum in FILLED_FROM:
        snum = FILLED_FROM[snum]
    return KEPT.get((scale, snum))


def _expected(src, fill=True):
    """The source images with everything outside each section's window set to zero."""
    source = zarr.open_group(str(src), mode="r")
    expected = {}
    for scale in SCALES:
        for snum in range(5):
            name = f"shapes_{snum}.tif"
            image = source[f"scale_{scale}"][name][:]
            want = np.zeros_like(image)
            window = _window(scale, snum, fill)
            if window:
                t, b, l, r = window
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
    assert lines[-2] == f"Log: {out / 'crop_log.txt'}"

    got = _arrays(out)
    want = _expected(src)
    assert got.keys() == want.keys()
    for key in want:
        np.testing.assert_array_equal(got[key], want[key], err_msg=str(key))
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
        window = _window(scale, snum)
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
            window = _window(scale, snum)
            if window:
                t, b, l, r = window
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


@pytest.mark.parametrize("flag", ["--out", "--zarr"])
@pytest.mark.parametrize("tail", [".", ".."])
def test_dot_parts_after_a_name_are_refused(case, tmp_path, flag, tail):
    """"link/." and "link/.." can name a different folder than zarr writes to."""
    if sys.platform == "win32":
        pytest.skip("symlinks need extra rights on Windows")
    jser, src = case
    (tmp_path / "outside" / "deep").mkdir(parents=True)
    (src / "link").symlink_to(tmp_path / "outside" / "deep", target_is_directory=True)
    source_before = _tree(src)
    entries_before = sorted(p.name for p in src.iterdir())
    outside_before = sorted(p.name for p in (tmp_path / "outside").iterdir())

    path = f"{src}{os.sep}link{os.sep}{tail}"
    if tail == "..":
        path += f"{os.sep}crop" if flag == "--out" else f"{os.sep}imgs.zarr"
    args = {"--out": tmp_path / "out.zarr", flag: path}
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS,
        *[x for pair in args.items() for x in pair],
    ])
    assert result.returncode == 1, result.stderr
    assert "without . or .. parts" in result.stderr
    assert _tree(src) == source_before
    assert sorted(p.name for p in src.iterdir()) == entries_before
    assert sorted(p.name for p in (tmp_path / "outside").iterdir()) == outside_before
    assert not (tmp_path / "out.zarr").exists()


@pytest.mark.parametrize("path, ok", [
    ("out.zarr", True),
    ("./out.zarr", True),
    ("../out.zarr", True),
    ("./../data/out.zarr", True),
    ("/data/out.zarr", True),
    ("data/./out.zarr", False),
    ("data/../out.zarr", False),
    ("link/.", False),
    ("link/..", False),
    ("/data/link/../out.zarr", False),
])
def test_plain_path_rule(path, ok):
    module = _load_script()
    path = path.replace("/", os.sep)
    if ok:
        module.checkPlainPath(path, "output")
    else:
        with pytest.raises(module.CropError, match="without . or .. parts"):
            module.checkPlainPath(path, "output")


def test_leading_dot_parts_are_allowed(case, tmp_path):
    """"./" and "../" start from the current folder and work as before."""
    jser, src = case
    work = tmp_path / "work"
    work.mkdir()
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS,
        "--zarr", f"..{os.sep}imgs.zarr", "--out", f".{os.sep}out.zarr",
    ], cwd=work)
    assert result.returncode == 0, result.stderr
    got = _arrays(work / "out.zarr")
    want = _expected(src)
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
    if what == "link to a folder":
        target = out.parent / "elsewhere"
        target.mkdir()
        (target / "keep.txt").write_text("keep me")
        out.symlink_to(target, target_is_directory=True)
        return target
    raise AssertionError(what)


@pytest.mark.parametrize("what", [
    "zarr", "folder named like a zarr", "empty folder", "file", "link to a folder",
])
def test_existing_output_is_refused_and_left_alone(case, what):
    """Nothing that already exists at the output path is changed or deleted."""
    if what.startswith("link") and sys.platform == "win32":
        pytest.skip("symlinks need extra rights on Windows")
    jser, src = case
    out = jser.parent.parent / "out.zarr"
    kept = _make_existing(out, what)
    before = _tree(kept)
    result = _run(["--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", out])
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
def test_dangling_output_link_given_with_a_dot_is_refused(case, tmp_path):
    """"link/." is refused too, so the missing target is never made."""
    jser, src = case
    out = tmp_path / "out.zarr"
    missing = tmp_path / "missing.zarr"
    out.symlink_to(missing, target_is_directory=True)
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", f"{out}{os.sep}.",
    ])
    assert result.returncode == 1, result.stderr
    assert "without . or .. parts" in result.stderr
    assert out.is_symlink()
    assert not os.path.lexists(missing)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need extra rights on Windows")
def test_dangling_link_given_with_a_dot_to_the_crop_step_is_refused(tmp_path):
    """cropSections applies the same rule when it is called directly."""
    module = _load_script()
    out = tmp_path / "out.zarr"
    missing = tmp_path / "missing.zarr"
    out.symlink_to(missing, target_is_directory=True)
    with pytest.raises(module.CropError, match="without . or .. parts"):
        module.cropSections(
            None, OBJECT, 0, None, [1], f"{out}{os.sep}.", show_progress=False,
        )
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


def _zarr_of(folder, names):
    """A two-scale zarr holding nonzero images under the given array names."""
    root = zarr.open_group(str(folder), mode="w")
    for scale, shape in SCALES.items():
        grp = root.create_group(f"scale_{scale}")
        for name in names:
            grp.create_dataset(name, chunks=(64, 64), data=np.full(shape, 9, np.uint8))
    return folder


def _move_square(jser, square):
    """Put the square at (xmin, ymin, xmax, ymax) microns on every section that has it."""
    data = json.loads(jser.read_text())
    xmin, ymin, xmax, ymax = square
    for section in data["sections"]:
        if OBJECT in section["contours"]:
            (trace,) = section["contours"][OBJECT]
            trace[0] = [xmin, xmax, xmax, xmin]
            trace[1] = [ymin, ymin, ymax, ymax]
    jser.write_text(json.dumps(data))


def _assert_refused_before_writing(result, out, jser, fragment):
    assert result.returncode == 1, result.stderr
    assert result.stderr.strip().startswith("error:")
    assert len(result.stderr.strip().splitlines()) == 1, result.stderr
    assert fragment in result.stderr
    assert "@@PROGRESS@@" not in result.stdout
    assert "Crop complete" not in result.stdout
    assert not os.path.lexists(out)
    assert _hidden_dirs(jser.parent) == []


def test_zarr_with_other_image_names_is_refused(case, tmp_path):
    """No section's image name is in the zarr and none starts with a number:
    stop, naming both sides, and write nothing.

    Before this check every section was skipped and the run printed
    "Crop complete" over an output holding only .zgroup.
    """
    jser, src = case
    other = _zarr_of(tmp_path / "other.zarr", [f"grid0{n}_00{n}.tif" for n in range(5)])
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS,
        "--zarr", other, "--out", out,
    ])
    _assert_refused_before_writing(result, out, jser, "No section image in this series is in the zarr")
    assert "'shapes_0.tif'" in result.stderr
    assert "'grid00_000.tif'" in result.stderr
    assert "'grid00_000.tif' does not start with a number" in result.stderr


@pytest.mark.parametrize("where", ["outside every image", "only on sections without an image"])
def test_crop_that_keeps_no_pixels_is_refused(case, tmp_path, where):
    jser, src = case
    args = ["--jser", jser, "--object", OBJECT, "--radius", RADIUS]
    if where == "outside every image":
        _move_square(jser, SQUARES[4])
    else:
        ## the zarr holds only the section without the square
        args += ["--zarr", _zarr_of(tmp_path / "part.zarr", [f"shapes_{BLANK_SECTION}.tif"])]
    out = tmp_path / "out.zarr"
    result = _run([*args, "--out", out])
    _assert_refused_before_writing(result, out, jser, "The crop would be empty")
    assert "'square'" in result.stderr


def test_missing_images_are_gray_in_the_nearest_window(case, tmp_path):
    """A section whose image is not in the zarr gets one the size of the nearest
    section with the square, 128 inside that section's window and 0 outside."""
    jser, src = case
    part = _zarr_of(tmp_path / "part.zarr", ["shapes_0.tif"])
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", part, "--out", out,
    ])
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == f"Crop complete: {out}"
    assert ("No image in the zarr for 4 sections (1-4): 128 gray inside the window of "
            f"the nearest section with {OBJECT}") in result.stdout
    got = _arrays(out)
    assert sorted(got) == [(scale, f"shapes_{n}.tif") for scale in SCALES for n in range(5)]
    group = zarr.open_group(str(out), mode="r")
    for scale, shape in SCALES.items():
        t, b, l, r = KEPT[(scale, 0)]
        kept = np.zeros(shape, np.uint8)
        kept[t:b, l:r] = 9
        np.testing.assert_array_equal(got[(scale, "shapes_0.tif")], kept)
        gray = np.zeros(shape, np.uint8)
        gray[t:b, l:r] = 128
        for n in range(1, 5):
            np.testing.assert_array_equal(got[(scale, f"shapes_{n}.tif")], gray, err_msg=str(n))
            assert group[f"scale_{scale}"][f"shapes_{n}.tif"].fill_value == 0
            assert _stored_chunks(out, scale, f"shapes_{n}.tif") == _touched_chunks((t, b, l, r))

    log = (out / "crop_log.txt").read_text()
    for n in range(1, 5):
        assert f"\n  {n} shapes_{n}.tif: 0\n" in log


def test_skip_missing_leaves_missing_images_out(case, tmp_path):
    """--skip-missing keeps the old behavior: no image for a missing section."""
    jser, src = case
    part = _zarr_of(tmp_path / "part.zarr", ["shapes_0.tif"])
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", part, "--out", out,
        "--skip-missing",
    ])
    assert result.returncode == 0, result.stderr
    got = _arrays(out)
    assert sorted(got) == [(1, "shapes_0.tif"), (2, "shapes_0.tif")]
    for scale in SCALES:
        t, b, l, r = KEPT[(scale, 0)]
        assert got[(scale, "shapes_0.tif")][t:b, l:r].all()
        assert got[(scale, "shapes_0.tif")].sum() == 9 * (b - t) * (r - l)
    line = "No image in the zarr for 4 sections (1-4): left out of the crop (--skip-missing)."
    assert line in result.stdout
    assert line in (out / "crop_log.txt").read_text()


def test_untraced_section_keeps_the_nearest_window(case):
    """Section 2 has no square; it keeps its own image inside section 1's window
    (1 and 3 are equally near, and the earlier wins), at every scale level."""
    jser, src = case
    out = jser.parent.parent / "out.zarr"
    result = _run(["--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", out])
    assert result.returncode == 0, result.stderr
    source = zarr.open_group(str(src), mode="r")
    got = _arrays(out)
    name = f"shapes_{BLANK_SECTION}.tif"
    for scale in SCALES:
        image = source[f"scale_{scale}"][name][:]
        t, b, l, r = KEPT[(scale, 1)]
        assert got[(scale, name)][t:b, l:r].all()
        np.testing.assert_array_equal(got[(scale, name)][t:b, l:r], image[t:b, l:r])
        assert got[(scale, name)].sum() == image[t:b, l:r].sum()
    summary = (f"No {OBJECT} on 1 section (2): each keeps its image inside the window of "
               f"the nearest section with {OBJECT}.")
    assert summary in result.stdout
    log = (out / "crop_log.txt").read_text()
    assert summary in log
    assert f"Sections without {OBJECT} (section: the section whose window it kept)\n  2: 1\n" in log


def test_blank_untraced_leaves_untraced_sections_black(case):
    jser, src = case
    out = jser.parent.parent / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", out, "--blank-untraced",
    ])
    assert result.returncode == 0, result.stderr
    got = _arrays(out)
    want = _expected(src, fill=False)
    assert got.keys() == want.keys()
    for key in want:
        np.testing.assert_array_equal(got[key], want[key], err_msg=str(key))
    assert not got[(1, f"shapes_{BLANK_SECTION}.tif")].any()
    assert f"No {OBJECT} on 1 section (2): left black (--blank-untraced)." in result.stdout


def test_log_records_the_inputs_and_a_clean_run(case):
    """Every run writes the log inside the output; a run with no gaps says so."""
    jser, src = case
    data = json.loads(jser.read_text())
    (trace,) = data["sections"][0]["contours"][OBJECT]
    data["sections"][BLANK_SECTION]["contours"][OBJECT] = [trace]
    jser.write_text(json.dumps(data))
    out = jser.parent.parent / "out.zarr"
    result = _run(["--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--out", out])
    assert result.returncode == 0, result.stderr
    log = (out / "crop_log.txt").read_text().splitlines()
    assert log[0].startswith("crop_zarr.py log, written ")
    assert f"Series: {jser}" in log
    assert f"Source zarr: {src}" in log
    assert f"Output zarr: {out}" in log
    assert f"Object: {OBJECT}" in log
    assert f"Radius: {RADIUS:g} microns" in log
    assert "Scale levels: 1, 2" in log
    summary = log[log.index("Summary") + 1:]
    assert summary == [
        f"Cropped around {OBJECT}: 5 of 5 sections.",
        f"Every section has {OBJECT} and its image in the zarr.",
    ]
    assert result.stdout.splitlines()[-4:-2] == summary
    ## the log is a plain file: the crop still opens as a zarr with the same arrays
    assert len(_arrays(out)) == 10


## the zarr names of some real series: the section number, then the grid
GRID_NAMES = ["000_shapes_grid000.tif", "001_shapes_grid01_sec01.tif", "002_shapes_grid01_sec02.tif",
              "003_shapes_grid02_sec01.tif", "004_shapes_grid02_sec02.tif"]


def _renamed_copy(src, folder, names):
    """A copy of the case's zarr with shapes_<n>.tif renamed to names[n]."""
    shutil.copytree(src, folder)
    for scale in SCALES:
        for n, name in enumerate(names):
            (folder / f"scale_{scale}" / f"shapes_{n}.tif").rename(folder / f"scale_{scale}" / name)
    return folder


def test_names_are_matched_by_section_number(case, tmp_path):
    """No series name is in the zarr, but every zarr name starts with a section
    number, one each: crop as if the names matched, under the series' names."""
    jser, src = case
    grid = _renamed_copy(src, tmp_path / "grid.zarr", GRID_NAMES)
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", grid, "--out", out,
    ])
    assert result.returncode == 0, result.stderr
    got = _arrays(out)
    want = _expected(src)
    assert got.keys() == want.keys()
    for key in want:
        np.testing.assert_array_equal(got[key], want[key], err_msg=str(key))
    assert ("Image names: no series name is in the zarr, so each section uses the zarr image "
            "whose name starts with its section number ('000_shapes_grid000.tif' is section 0). "
            "The crop uses the series' names ('shapes_0.tif', ...).") in result.stdout
    log = (out / "crop_log.txt").read_text()
    assert "Image names (section: zarr image -> crop image)\n" in log
    for n, name in enumerate(GRID_NAMES):
        assert f"\n  {n}: {name} -> shapes_{n}.tif\n" in log


@pytest.mark.parametrize("names, reason", [
    (GRID_NAMES[:4], "the zarr's 4 images start with 0-3, and the series' 5 sections are 0-4"),
    ([f"00{n + 1}_grid.tif" for n in range(5)],
     "the zarr's 5 images start with 1-5, and the series' 5 sections are 0-4"),
    (GRID_NAMES[:4] + ["0003_extra.tif"],
     "'0003_extra.tif' and '003_shapes_grid02_sec01.tif' start with the same number"),
    (GRID_NAMES[:4] + ["grid_4.tif"], "'grid_4.tif' does not start with a number"),
])
def test_unclear_number_matches_are_refused(case, tmp_path, names, reason):
    """A match by number is made only when it is one image per section, exactly."""
    jser, src = case
    other = _zarr_of(tmp_path / "other.zarr", names)
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", other, "--out", out,
    ])
    _assert_refused_before_writing(result, out, jser, "No section image in this series is in the zarr")
    assert f"They cannot be matched by section number: {reason}." in result.stderr


def test_number_match_needs_the_same_names_at_every_scale(case, tmp_path):
    jser, src = case
    grid = _renamed_copy(src, tmp_path / "grid.zarr", GRID_NAMES)
    (grid / "scale_2" / GRID_NAMES[4]).rename(grid / "scale_2" / "004_other.tif")
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", grid, "--out", out,
    ])
    _assert_refused_before_writing(result, out, jser, "scale_2 holds other image names than scale_1")


def test_number_match_needs_unique_series_names(case, tmp_path):
    """The crop is written under the series' names, so two sections cannot share one."""
    jser, src = case
    data = json.loads(jser.read_text())
    data["sections"][4]["src"] = "shapes_3.tif"
    jser.write_text(json.dumps(data))
    grid = _renamed_copy(src, tmp_path / "grid.zarr", GRID_NAMES)
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", grid, "--out", out,
    ])
    _assert_refused_before_writing(
        result, out, jser, "two sections in the series use the image name 'shapes_3.tif'")


def test_exact_names_turns_number_matching_off(case, tmp_path):
    jser, src = case
    grid = _renamed_copy(src, tmp_path / "grid.zarr", GRID_NAMES)
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", grid, "--out", out,
        "--exact-names",
    ])
    _assert_refused_before_writing(
        result, out, jser, "They cannot be matched by section number: --exact-names is set.")


def test_prompts_refuse_an_empty_crop(case, tmp_path):
    """The no-argument path stops with the same error and makes no default output."""
    jser, src = case
    other = _zarr_of(tmp_path / "other.zarr", ["000_grid00.tif"])
    result = _run([], stdin=f"{jser}\n{OBJECT}\n{RADIUS}\n{other}\n")
    assert result.returncode == 1, result.stderr
    assert "No section image in this series is in the zarr" in result.stderr
    assert not (tmp_path / f"other_{OBJECT}_crop.zarr").exists()
    assert not (src.parent / f"imgs_{OBJECT}_crop.zarr").exists()


def test_image_missing_at_one_scale_is_gray_there_only(case, tmp_path):
    """shapes_1.tif is only in scale_1: it is cropped there and gray in scale_2.

    A neighbor must have its image at every scale level, so section 2 (no
    square) takes section 3's window, not section 1's.
    """
    jser, src = case
    part = tmp_path / "part.zarr"
    shutil.copytree(src, part)
    shutil.rmtree(part / "scale_2" / "shapes_1.tif")
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", part, "--out", out,
    ])
    assert result.returncode == 0, result.stderr
    source = zarr.open_group(str(src), mode="r")
    got = _arrays(out)
    assert len(got) == 10

    want = _expected(src)
    np.testing.assert_array_equal(got[(1, "shapes_1.tif")], want[(1, "shapes_1.tif")])
    t, b, l, r = KEPT[(2, 0)]
    gray = np.zeros(SCALES[2], np.uint8)
    gray[t:b, l:r] = 128
    np.testing.assert_array_equal(got[(2, "shapes_1.tif")], gray)

    for scale in SCALES:
        image = source[f"scale_{scale}"]["shapes_2.tif"][:]
        t, b, l, r = KEPT[(scale, 3)]
        kept = np.zeros_like(image)
        kept[t:b, l:r] = image[t:b, l:r]
        np.testing.assert_array_equal(got[(scale, "shapes_2.tif")], kept, err_msg=str(scale))

    log = (out / "crop_log.txt").read_text()
    assert "\n  1 shapes_1.tif: 0 (scale_2 only)\n" in log
    assert "\n  2: 3\n" in log


def test_no_complete_neighbor_falls_back_to_black(case, tmp_path):
    """No section with the square has its image at every scale level, so there
    is nothing to borrow: untraced sections stay black, missing images are left
    out, and the log says why."""
    jser, src = case
    part = tmp_path / "part.zarr"
    shutil.copytree(src, part)
    for n in (0, 1, 3, 4):
        shutil.rmtree(part / "scale_2" / f"shapes_{n}.tif")
    out = tmp_path / "out.zarr"
    result = _run([
        "--jser", jser, "--object", OBJECT, "--radius", RADIUS, "--zarr", part, "--out", out,
    ])
    assert result.returncode == 0, result.stderr
    got = _arrays(out)
    assert sorted(got) == sorted(
        [(1, f"shapes_{n}.tif") for n in range(5)] + [(2, "shapes_2.tif")]
    )
    assert not got[(1, "shapes_2.tif")].any()
    assert not got[(2, "shapes_2.tif")].any()
    reason = f"because no section with {OBJECT} has its image at every scale level."
    assert f"No {OBJECT} on 1 section (2): left black, {reason}" in result.stdout
    assert f"No image in the zarr for 4 sections (0-1, 3-4): left out of the crop, {reason}" in result.stdout
