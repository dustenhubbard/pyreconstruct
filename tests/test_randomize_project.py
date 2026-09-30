"""File > Utilities > Randomize project and De-randomize project.

Covers the scripts in `assets/scripts/projects/` end to end on real image
files: a coded series with a deleted section, hidden files, upper-case
extensions, a decode.txt written on Windows, and z-traces all decode, and a
project that cannot be decoded is left exactly as it was.
"""

import json
from pathlib import Path, PureWindowsPath

import numpy as np
import pytest
from PIL import Image

from PyReconstruct.assets.scripts.projects import (
    DerandomizeError,
    RandomizeError,
    derandomize_project,
    randomize_project,
)
from PyReconstruct.assets.scripts.projects.derandomize import get_decoding
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.ztrace import Ztrace


def _make_project(root: Path, spec: dict) -> Path:
    """spec maps each series folder to its image names."""
    root.mkdir()
    for series, names in spec.items():
        (root / series).mkdir()
        for i, name in enumerate(names):
            Image.fromarray(np.full((16, 16), 10 * (i + 1), dtype=np.uint8)).save(
                str(root / series / name), format="TIFF"
            )
    return root


def _decode(root: Path) -> dict:
    """Coded image name -> original relative path."""
    lines = (root / "decode.txt").read_text().splitlines()
    return {coded: image for image, coded in (line.split(" -> ") for line in lines)}


def _load(fp: Path) -> dict:
    with open(fp) as f:
        return json.load(f)


def _tree(root: Path) -> dict:
    """Every file under root with its bytes, to prove nothing changed."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def _archive(root: Path) -> Path:
    (archive,) = root.glob("decoded-*")
    return archive


def _srcs(root: Path, series: str) -> list:
    return [s["src"] for s in _load(root / series / f"{series}.jser")["sections"]]


def _assert_decoded(root: Path, spec: dict):
    for series, names in spec.items():
        assert sorted(p.name for p in (root / series / "images").iterdir()) == sorted(names)
    assert not (root / "images").exists()
    assert sorted(p.name for p in _archive(root).iterdir()) == ["coded.jser", "decode.txt"]


def test_round_trip(tmp_path):
    spec = {"A": ["a1.tif", "a2.tif"], "B": ["b1.tif"]}
    root = _make_project(tmp_path / "proj", spec)

    coded = randomize_project(root)
    assert len(_load(coded)["sections"]) == 3

    derandomize_project(coded)

    _assert_decoded(root, spec)
    assert _srcs(root, "A") == ["a1.tif", "a2.tif"]
    assert _srcs(root, "B") == ["b1.tif"]


def test_deleted_section_decodes_and_keeps_its_image(tmp_path):
    spec = {"A": ["a1.tif", "a2.tif", "a3.tif"], "B": ["b1.tif", "b2.tif"]}
    root = _make_project(tmp_path / "proj", spec)
    coded = randomize_project(root)

    series = Series.openJser(str(coded))
    deleted_image = _decode(root)[series.loadSection(2).src]
    series.deleteSections([2])
    series.saveJser()
    series.close()
    assert _load(coded)["sections"][2] is None

    derandomize_project(coded)

    # the deleted section's image still goes back to its own series folder
    _assert_decoded(root, spec)
    series_name, image_name = deleted_image.split("/")
    remaining = [n for n in spec[series_name] if n != image_name]
    assert _srcs(root, series_name) == remaining


def test_hidden_files_stay_out_of_the_coded_series(tmp_path):
    spec = {"A": ["a1.tif", "a2.tif"], "B": ["b1.tif"]}
    root = _make_project(tmp_path / "proj", spec)
    (root / "A" / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")

    coded = randomize_project(root)

    assert all(".DS_Store" not in image for image in _decode(root).values())
    assert (root / "A" / ".DS_Store").exists()

    # Finder can add one to images/ while the coded series is being traced
    (root / "images" / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")

    derandomize_project(coded)

    for series, names in spec.items():
        assert sorted(p.name for p in (root / series / "images").iterdir()) == names
    assert not (root / "images").exists()
    assert (_archive(root) / "images" / ".DS_Store").exists()
    assert (_archive(root) / "coded.jser").exists()
    assert (_archive(root) / "decode.txt").exists()


def test_upper_case_extensions_are_included(tmp_path):
    spec = {"A": ["001.TIF", "002.TIF"], "B": ["001.tif"]}
    root = _make_project(tmp_path / "proj", spec)

    coded = randomize_project(root)
    assert len([s for s in _load(coded)["sections"] if s]) == 3

    derandomize_project(coded)

    _assert_decoded(root, spec)
    assert _srcs(root, "A") == ["001.TIF", "002.TIF"]


def test_windows_decode_file(tmp_path):
    spec = {"A": ["a1.tif", "a2.tif"], "B": ["b1.tif"]}
    root = _make_project(tmp_path / "proj", spec)
    coded = randomize_project(root)

    # rewrite decode.txt the way an older version wrote it on Windows
    lines = [
        f"{PureWindowsPath(*image.split('/'))} -> {name}"
        for name, image in _decode(root).items()
    ]
    assert all("\\" in line and "/" not in line for line in lines)
    (root / "decode.txt").write_text("\n".join(lines) + "\n")

    decoding = get_decoding(root)
    assert decoding["series"] == ["A", "B"]
    assert sorted(decoding["images"].values()) == [("A", "a1.tif"), ("A", "a2.tif"), ("B", "b1.tif")]

    derandomize_project(coded)

    _assert_decoded(root, spec)


def test_ztrace_points_follow_their_sections(tmp_path):
    spec = {"A": ["a1.tif", "a2.tif", "a3.tif"], "B": ["b1.tif", "b2.tif", "b3.tif"]}
    root = _make_project(tmp_path / "proj", spec)
    coded = randomize_project(root)
    decode = _decode(root)

    series = Series.openJser(str(coded))
    coded_to_orig = {n: decode[series.loadSection(n).src] for n in sorted(series.sections)}
    # one point per coded section, x = the coded section number
    series.ztraces["z"] = Ztrace("z", (255, 0, 0), [(float(n), 0.0, n) for n in sorted(series.sections)])
    # one that only touches series A
    a_only = [n for n, image in coded_to_orig.items() if image.startswith("A/")]
    series.ztraces["a_only"] = Ztrace("a_only", (0, 255, 0), [(float(n), 0.0, n) for n in a_only])
    series.saveJser()
    series.close()

    derandomize_project(coded)

    for name in ("A", "B"):
        data = _load(root / name / f"{name}.jser")
        srcs = [s["src"] for s in data["sections"]]
        points = data["series"]["ztraces"]["z"]["points"]
        assert len(points) == 3
        for x, _, snum in points:
            assert coded_to_orig[int(x)] == f"{name}/{srcs[snum]}"
        assert ("a_only" in data["series"]["ztraces"]) == (name == "A")


def test_unknown_image_changes_nothing(tmp_path):
    root = _make_project(tmp_path / "proj", {"A": ["a1.tif", "a2.tif"], "B": ["b1.tif"]})
    coded = randomize_project(root)

    # drop one line from decode.txt, so its section cannot be decoded
    lines = (root / "decode.txt").read_text().splitlines()
    (root / "decode.txt").write_text("\n".join(lines[1:]) + "\n")
    before = _tree(root)

    with pytest.raises(DerandomizeError, match="not listed in decode.txt"):
        derandomize_project(coded)

    assert _tree(root) == before


def test_missing_image_changes_nothing(tmp_path):
    root = _make_project(tmp_path / "proj", {"A": ["a1.tif", "a2.tif"], "B": ["b1.tif"]})
    coded = randomize_project(root)
    next(iter(sorted((root / "images").iterdir()))).unlink()
    before = _tree(root)

    with pytest.raises(DerandomizeError, match="missing"):
        derandomize_project(coded)

    assert _tree(root) == before


def test_existing_target_changes_nothing(tmp_path):
    root = _make_project(tmp_path / "proj", {"A": ["a1.tif", "a2.tif"], "B": ["b1.tif"]})
    coded = randomize_project(root)
    (root / "B" / "images").mkdir(parents=True)
    (root / "B" / "images" / "b1.tif").write_bytes(b"already here")
    before = _tree(root)

    with pytest.raises(DerandomizeError, match="already exist"):
        derandomize_project(coded)

    assert _tree(root) == before


def test_randomize_refuses_without_images(tmp_path):
    root = tmp_path / "proj"
    (root / "A").mkdir(parents=True)
    (root / "A" / "notes.txt").write_text("not an image")

    with pytest.raises(RandomizeError, match="No images"):
        randomize_project(root)

    assert sorted(p.name for p in root.iterdir()) == ["A"]


def test_randomize_refuses_a_randomized_project(tmp_path):
    root = _make_project(tmp_path / "proj", {"A": ["a1.tif"]})
    randomize_project(root)
    (root / "A").mkdir()
    before = _tree(root)

    with pytest.raises(RandomizeError, match="randomized before"):
        randomize_project(root)

    assert _tree(root) == before


def test_derandomize_menu_item_reports_the_problem(tmp_path, monkeypatch):
    import PyReconstruct.modules.gui.main.main_window as mw

    root = _make_project(tmp_path / "proj", {"A": ["a1.tif"], "B": ["b1.tif"]})
    coded = randomize_project(root)
    next(iter(sorted((root / "images").iterdir()))).unlink()
    before = _tree(root)

    notices = []
    monkeypatch.setattr(mw, "notify", lambda msg, *a, **k: notices.append(msg))
    monkeypatch.setattr(mw, "notifyConfirm", lambda *a, **k: True)
    monkeypatch.setattr(mw.FileDialog, "get", staticmethod(lambda *a, **k: str(coded)))

    class _Window:
        series = type("S", (), {"jser_fp": ""})()

    mw.MainWindow.derandomizeProject(_Window())

    assert len(notices) == 1
    assert notices[0].startswith("The project could not be decoded. Nothing was changed.")
    assert _tree(root) == before


def test_targets_that_differ_only_in_case_change_nothing(tmp_path):
    # a.tif and A.TIF can sit side by side on Linux but are one file on a Mac
    root = _make_project(tmp_path / "proj", {"A": ["a1.tif", "a2.tif"]})
    coded = randomize_project(root)
    text = (root / "decode.txt").read_text(encoding="utf-8")
    (root / "decode.txt").write_text(text.replace("A/a2.tif", "A/A1.TIF"), encoding="utf-8")
    before = _tree(root)

    with pytest.raises(DerandomizeError, match="would be the same file"):
        derandomize_project(coded)

    assert _tree(root) == before


def test_decode_file_is_utf8(tmp_path):
    spec = {"Série": ["côté.tif"]}
    root = _make_project(tmp_path / "proj", spec)
    coded = randomize_project(root)

    assert "Série/côté.tif -> " in (root / "decode.txt").read_bytes().decode("utf-8")

    derandomize_project(coded)

    _assert_decoded(root, spec)


def test_decode_file_in_the_locale_encoding(tmp_path, monkeypatch):
    import PyReconstruct.assets.scripts.projects.derandomize as derandomize

    spec = {"Série": ["côté.tif"]}
    root = _make_project(tmp_path / "proj", spec)
    coded = randomize_project(root)

    # what an older version wrote on a Windows machine set to cp1252
    text = (root / "decode.txt").read_text(encoding="utf-8")
    (root / "decode.txt").write_bytes(text.encode("cp1252"))
    monkeypatch.setattr(derandomize.locale, "getpreferredencoding", lambda *a: "cp1252")

    derandomize_project(coded)

    _assert_decoded(root, spec)


def _fail_renames_after(monkeypatch, count, forever=False):
    """Make Path.rename raise after `count` calls (and keep raising if forever)."""
    real_rename = Path.rename
    calls = {"n": 0}

    def rename(self, target):
        calls["n"] += 1
        if calls["n"] == count + 1 or (forever and calls["n"] > count):
            raise OSError("disk went away")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)


@pytest.mark.parametrize("count", [0, 1, 3, 4, 5])
def test_failed_move_is_rolled_back(tmp_path, monkeypatch, count):
    # 3 images, then images/, coded.jser and decode.txt: 6 renames in all
    root = _make_project(tmp_path / "proj", {"A": ["a1.tif", "a2.tif"], "B": ["b1.tif"]})
    coded = randomize_project(root)
    (root / "images" / ".DS_Store").write_bytes(b"\x00")
    before = _tree(root)
    _fail_renames_after(monkeypatch, count)

    with pytest.raises(DerandomizeError, match="every change was undone"):
        derandomize_project(coded)

    monkeypatch.undo()
    assert _tree(root) == before
    assert sorted(p.name for p in root.iterdir()) == ["coded.jser", "decode.txt", "images"]


def test_failed_rollback_says_what_moved(tmp_path, monkeypatch):
    root = _make_project(tmp_path / "proj", {"A": ["a1.tif", "a2.tif"], "B": ["b1.tif"]})
    coded = randomize_project(root)
    _fail_renames_after(monkeypatch, 2, forever=True)

    with pytest.raises(DerandomizeError, match="could not be put back") as raised:
        derandomize_project(coded)

    moved = [p for p in (root / "A" / "images", root / "B" / "images") if p.exists()]
    names = [f.name for d in moved for f in d.iterdir() if f.suffix == ".tif"]
    assert len(names) == 2
    assert all(name in str(raised.value) for name in names)


def test_randomize_refuses_an_existing_coded_jser(tmp_path):
    root = _make_project(tmp_path / "proj", {"A": ["a1.tif"]})
    (root / "coded.jser").write_text("{}")
    before = _tree(root)

    with pytest.raises(RandomizeError, match="coded.jser"):
        randomize_project(root)

    assert _tree(root) == before
