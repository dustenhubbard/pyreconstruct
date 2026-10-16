"""The hybrid store prototype against file shapes: every past shape the reader
takes, the fields the July evaluation left untested, and old Stable builds
reading what the store exports.

The rule each test applies: open a file with the switch on and export it, open
the same file with the switch off and save it, and the two .jser files must be
the same bytes. The store's import runs the reader's own migration
(`_readJserForOpen`, `Section.updateJSON`, `Series.updateJSON`), so an old
shape imports exactly as it opens today.
"""
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import hybrid_store
from PyReconstruct.modules.datatypes.flag import Flag
from PyReconstruct.modules.constants.jser_format import KEYED_TRACE_ROW_KEYS
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.transform import Transform

from tests.test_hybrid_store import store_on  # noqa: F401  (fixture)
from tests.test_jser_schema_version import _OLD_READER_DRIVER

REPO_ROOT = Path(__file__).resolve().parent.parent
PARITY = REPO_ROOT / "tests" / "fixtures" / "parity_series.jser"
CLASS = REPO_ROOT / "dev" / "assets" / "checker" / "files" / "class_series.jser"


def _open(fp):
    series = Series.openJser(str(fp), progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    return series


def _both_ways(src, tmp_path, monkeypatch):
    """(bytes today's app writes, bytes the store exports) for one file."""
    out = {}
    for mode in ("today", "store"):
        folder = tmp_path / mode
        folder.mkdir()
        fp = folder / Path(src).name
        shutil.copyfile(src, fp)
        if mode == "store":
            monkeypatch.setenv(hybrid_store.ENV_SWITCH, "1")
        else:
            monkeypatch.delenv(hybrid_store.ENV_SWITCH, raising=False)
        series = _open(fp)
        try:
            assert (series.store is not None) == (mode == "store")
            series.saveJser()
        finally:
            series.close()
        out[mode] = fp.read_bytes()
    return out["today"], out["store"]


def legacy_series(folder) -> Path:
    """A .jser in the oldest shapes the reader still takes, from the parity fixture."""
    doc = json.loads(PARITY.read_bytes())
    sec = next(s for s in doc["sections"] if s and s["contours"])
    base = next(iter(sec["contours"].values()))[0]

    def row(**changes):
        r = copy.deepcopy(base)
        for i, v in changes.items():
            r[int(i[1:])] = v
        return r

    sec["brightness"], sec["contrast"] = 150, 1.7      # the legacy pair
    sec.pop("brightness_contrast_profiles", None)
    sec["tforms"]["no-alignment"] = [1, 0, 0, 0, 1, 0]
    contours = {"zzz first": [row()]}                    # unsorted, and a name to normalize
    contours.update(sec["contours"])
    contours["nine_field"] = [row() + ["extra"]]
    contours["old_mode"] = [row(f6="none", f7=["b", "a"])]
    contours["one_point"] = [row(f0=[1.0], f1=[2.0])]
    contours["two_point"] = [row(f0=[1.0, 2.0], f1=[3.0, 4.0], f3=True)]
    contours["int_coords"] = [row(f0=[1, 2, 3], f1=[4, 5, 6])]
    contours["keyed_row"] = [dict(zip(KEYED_TRACE_ROW_KEYS[1:], row()))]
    sec["contours"] = contours
    sec["flags"] = [
        ["five", 1.0, 2.0, [255, 0, 0], []],
        ["six", 3.0, 4.0, [0, 255, 0], [], True],
    ]
    flat = {"legacy.ser": doc["series"]}                 # the flat top level, no log
    for i, s in enumerate(doc["sections"]):
        if s:
            flat[f"legacy.{i}"] = s
    fp = Path(folder) / "legacy.jser"
    fp.write_text(json.dumps(flat))
    return fp


def full_field_series(folder, monkeypatch) -> Path:
    """class_series with every field the July evaluation listed as untested."""
    monkeypatch.delenv(hybrid_store.ENV_SWITCH, raising=False)
    fp = Path(folder) / "fields.jser"
    shutil.copyfile(CLASS, fp)
    series = _open(fp)
    try:
        names = sorted(series.data.objects)[:3]
        series.addUserCol("Status", ["done", "to do"], log_event=False)
        series.setUserColAttr(names[0], "Status", "done")
        series.setObjHosts([names[0]], [names[1]])
        series.setAttr(names[0], "3D_mode", "surface")
        series.setAttr(names[1], "comment", "a comment, with a comma")
        series.object_groups.add("group one", names[2])
        for snum, section in series.enumerateSections(show_progress=False):
            section.tforms["align2"] = Transform([1, 0, 1.5, 0, 1, -2.0])
            if snum == min(series.sections):
                flag = Flag("look here", 1.0, 2.0, snum, (255, 0, 0))
                flag.addComment("dusten", "a note, with a comma")
                section.addFlag(flag, log_event=False)
            section.save()
        series.addLog(names[0], None, "a logged event")
        series.save()
        series.saveJser()
    finally:
        series.close()
    doc = json.loads(fp.read_bytes())
    s = doc["series"]
    assert s["user_columns"] and s["host_tree"] and s["object_groups"]
    assert any(sec and sec["flags"] for sec in doc["sections"])
    return fp


def test_every_past_shape_imports_as_it_opens_today(tmp_path, monkeypatch, store_on):  # noqa: F811
    src = legacy_series(tmp_path)
    today, store = _both_ways(src, tmp_path, monkeypatch)
    assert store == today


def test_the_fields_july_left_untested_round_trip(tmp_path, monkeypatch, store_on):  # noqa: F811
    src = full_field_series(tmp_path, monkeypatch)
    today, store = _both_ways(src, tmp_path, monkeypatch)
    assert store == today
    doc = json.loads(store)
    assert "Status" in doc["series"]["user_columns"]
    assert "a logged event" in doc["log"]


# ---------------------------------------------------------------------------
# old Stable builds open what the store exports
# ---------------------------------------------------------------------------

def _extract(tag, tmp_path):
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", tag], capture_output=True)
    if proc.returncode != 0:
        pytest.skip(f"cannot git archive {tag}: {proc.stderr.decode()[:200]}")
    dest = tmp_path / f"reader-{tag}"
    dest.mkdir()
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
        try:
            archive.extractall(dest, filter="data")
        except TypeError:  # pragma: no cover - Python < 3.12
            archive.extractall(dest)
    return dest


def _contours(doc):
    return [None if s is None else s["contours"] for s in doc["sections"]]


@pytest.mark.parametrize("tag", ["v1.22.3", "v1.24.0"])
def test_an_old_stable_build_opens_the_export_and_keeps_every_trace(
    tag, tmp_path, monkeypatch, store_on,  # noqa: F811
):
    src = full_field_series(tmp_path, monkeypatch)
    monkeypatch.setenv(hybrid_store.ENV_SWITCH, "1")
    series = _open(src)
    exported = tmp_path / "exported.jser"
    try:
        series.saveJser(str(exported))
    finally:
        series.close()
    sent = json.loads(exported.read_bytes())

    reader = _extract(tag, tmp_path)
    (reader / "_driver.py").write_text(_OLD_READER_DRIVER, encoding="utf-8")
    handed = tmp_path / "handed.jser"
    shutil.copyfile(exported, handed)
    result = tmp_path / "result.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    env.pop(hybrid_store.ENV_SWITCH, None)
    proc = subprocess.run(
        [sys.executable, "_driver.py", str(handed), str(result)],
        cwd=str(reader), env=env, capture_output=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr.decode()[-2000:]
    got = json.loads(result.read_bytes())
    assert str(reader) in got["package"]
    assert got["shapes"] == ["list:8"]
    assert [None if s is None else s["contours"] for s in got["sections"]] == _contours(sent)
