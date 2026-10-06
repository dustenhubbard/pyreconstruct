"""``dev/assets/misc/crop_zarr.py`` runs from flags, without prompts or dialogs.

With flags it opens a copy of the jser in a temp folder, prints the converter's
``@@PROGRESS@@`` lines, and checks its inputs before it writes anything, so
another program can call it. With no arguments it still asks the same four
questions.

Every run here is a subprocess, the way a wrapper program would call it.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import zarr

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "dev" / "assets" / "misc" / "crop_zarr.py"
SHAPES = REPO_ROOT / "dev" / "assets" / "checker" / "files" / "shapes1.jser"

SCALES = {1: (400, 1000), 2: (200, 500)}
OBJECT = "square"
RADIUS = 0.05
## section 2 has no square, so its images must come out all zero
BLANK_SECTION = 2


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
    del data["sections"][BLANK_SECTION]["contours"][OBJECT]
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


def _expected(jser, src):
    """The crop worked out here from each section's bounds."""
    tmp = jser.parent.parent / "expected"
    tmp.mkdir()
    fp = tmp / jser.name
    shutil.copyfile(jser, fp)
    series = Series.openJser(str(fp), progress=NullProgressReporter)
    source = zarr.open_group(str(src), mode="r")
    expected = {}
    try:
        for snum, section in series.enumerateSections(show_progress=False):
            for scale in SCALES:
                image = source[f"scale_{scale}"][section.src][:]
                want = np.zeros_like(image)
                if OBJECT in section.contours:
                    xmin, ymin, xmax, ymax = section.contours[OBJECT].getBounds()
                    mag = section.mag * scale
                    h, w = image.shape
                    l = max(round((xmin - RADIUS) / mag), 0)
                    r = min(round((xmax + RADIUS) / mag), w)
                    b = min(round(h - (ymin - RADIUS) / mag), h)
                    t = max(round(h - (ymax + RADIUS) / mag), 0)
                    assert 0 < t < b < h and 0 < l < r < w
                    want[t:b, l:r] = image[t:b, l:r]
                expected[(scale, section.src)] = want
    finally:
        series.close()
    return expected


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
    want = _expected(jser, src)
    assert got.keys() == want.keys()
    for key in want:
        np.testing.assert_array_equal(got[key], want[key], err_msg=str(key))
    assert not got[(1, f"shapes_{BLANK_SECTION}.tif")].any()

    ## nothing left beside the jser, and the default output was not made
    assert _hidden_dirs(jser.parent) == []
    assert sorted(p.name for p in jser.parent.iterdir()) == ["shapes.jser"]
    assert not (src.parent / f"imgs_{OBJECT}_crop.zarr").exists()


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
    assert _arrays(out).keys() == _expected(jser, src).keys()


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
])
def test_incomplete_or_bad_flags_are_refused(args):
    result = _run(args)
    assert result.returncode == 2
    assert "Jser filepath" not in result.stdout
