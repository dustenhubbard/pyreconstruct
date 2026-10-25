"""Section files written on first need after an open from the local store (lazy_sections.py).

An open from the store writes a stub for each section the store holds as its
working file, and the first load of a section writes its file. Everything a
series does after that open must give the bytes it gives when every section
file is written at open, so most of these run the same steps both ways and
compare the files and the .jser.
"""
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import numpy as np
import pytest

from PyReconstruct.modules.constants import fast_dumps, fast_loads
from PyReconstruct.modules.datatypes import lazy_sections, local_stores, store_open, store_save
from PyReconstruct.modules.datatypes.hybrid_store import HybridStore, storePaths
from PyReconstruct.modules.datatypes.series import SeriesSaveError
from PyReconstruct.modules.datatypes.series_data import SeriesData

from test_hybrid_store import PARITY, SERIES_FILES, _edge_series, _keyed, full_field_series, legacy_series
from test_hybrid_store import store_root  # noqa: F401  (fixture)
from test_store_open import (
    SOURCES, _NoDialog, _built_sections, _copy, _getters, _open, _today, rich_series,
)
from test_store_open import notes, switch_on  # noqa: F401  (fixture)


def _kept(src):
    """src after a first open that keeps it in its store."""
    _open(src).close()
    return src


def _eager(m):
    """The eager arm: an open from the store that writes every section file."""
    m.setattr(lazy_sections, "stubs", lambda held: {})


def _stubbed(series) -> set:
    wdir = series.getwdir()
    return {
        snum for snum, name in series.sections.items()
        if Path(wdir, name).read_bytes().startswith(lazy_sections.MAGIC)
    }


def _fills(m) -> list:
    """A list that gets the path of every stub filled from now on."""
    filled = []
    real = lazy_sections.fill

    def counting(fp, *a, **k):
        done = real(fp, *a, **k)
        if done:
            filled.append(fp)
        return done

    m.setattr(lazy_sections, "fill", counting)
    return filled


def _keyed_series(folder) -> Path:
    """The parity series with two rows carrying saved ids, in both fill-mode spellings."""
    doc = json.loads(PARITY.read_bytes())
    snum = next(i for i, s in enumerate(doc["sections"]) if s and "dendrite01" in s["contours"])
    rows = doc["sections"][snum]["contours"]["dendrite01"]
    rows[0] = _keyed(rows[0], "zzSTORE0001", "fill_mode")
    rows[1] = _keyed(rows[1], "zzSTORE0002", "mode")
    fp = Path(folder) / "ids.jser"
    fp.write_text(json.dumps(doc))
    return fp


LOAD_SOURCES = {
    **SOURCES,
    "keyed-rows": _keyed_series,
    "int-coordinate": lambda folder: _edge_series(folder, "coordinate", "int-2^63-1", False),
}


@pytest.fixture(params=sorted(LOAD_SOURCES))
def load_src(request, tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    return LOAD_SOURCES[request.param](folder)


def _edit(series):
    """One edit: a trace deleted from the first section with traces, saved to its file."""
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        traces = [t for c in section.contours.values() for t in c]
        if traces:
            section.deleteTraces([traces[0]])
            section.save()
            return snum
    raise AssertionError("no section has a trace")


def _crash(series):
    """What a crash leaves: the working folder, and a store no process holds."""
    store_save.release(series)
    series.leave_open = True
    series.close()


class _Quiet:
    """A notifier that answers yes and keeps what it was told."""

    def __init__(self):
        self.told = []

    def confirm(self, *a, **k):
        return True

    def notify(self, message, *a, **k):
        self.told.append(message)
        return True


# ---------------------------------------------------------------------------
# the reopen writes stubs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("make", [
    *(lambda folder, p=p: _copy(p, folder) for p in SERIES_FILES),
    legacy_series, full_field_series, lambda folder: rich_series(folder, partial=False),
], ids=[p.stem for p in SERIES_FILES] + ["legacy", "fields", "rich"])
def test_a_reopen_writes_a_stub_for_every_section_and_no_section_json(make, tmp_path, switch_on, notes, monkeypatch):  # noqa: F811
    src = _kept(make(tmp_path))
    built = _built_sections(monkeypatch)
    series = _open(src, notifier=_NoDialog())
    try:
        assert built == []
        wdir = series.getwdir()
        assert _stubbed(series) == set(series.sections)
        assert sorted(os.listdir(wdir)) == sorted(
            [*series.sections.values(), f"{series.name}.ser", "existing_log.csv", lazy_sections.MARKER]
        )
        db_fp = storePaths(str(src))[0]
        for snum, name in series.sections.items():
            fp = Path(wdir, name)
            assert fp.stat().st_size < 1024
            stub = lazy_sections.readStub(str(fp))
            assert stub["snum"] == snum and stub["store"] == os.path.basename(db_fp)
            assert len(bytes.fromhex(stub["key"])) == 32
        # the object list, from the stored numbers, equals a full refresh
        from_store = _getters(series.data)
        refreshed = SeriesData(series)
        refreshed.refresh(show_progress=False)
        assert from_store == _getters(refreshed)
    finally:
        series.close()
    assert notes == []


def test_a_section_the_store_holds_otherwise_than_its_file_is_written_at_reopen(tmp_path, switch_on, monkeypatch):  # noqa: F811
    src = _kept(_copy(PARITY, tmp_path / "s"))
    snum = 1
    store = HybridStore.forJser(str(src))
    try:
        store.con.execute("UPDATE section_key SET as_working=0 WHERE snum=?", (snum,))
    finally:
        store.close()
    expected = _today(src, tmp_path, monkeypatch)["files"]
    series = _open(src)
    try:
        assert _stubbed(series) == set(series.sections) - {snum}
        name = series.sections[snum]
        assert Path(series.getwdir(), name).read_bytes() == expected[name]
    finally:
        series.close()


# ---------------------------------------------------------------------------
# a load fills its own section, as the eager open wrote it
# ---------------------------------------------------------------------------

def _ids(section) -> list:
    return [
        (name, section.traceID(t)) for name, contour in section.contours.items() for t in contour
    ] + [section.trace_ids_trusted]


def test_a_load_fills_only_its_section_with_the_eager_bytes_and_ids(load_src, tmp_path, switch_on, monkeypatch):  # noqa: F811
    expected = _today(load_src, tmp_path, monkeypatch)["files"]
    with monkeypatch.context() as m:
        m.delenv(store_open.ENV_SWITCH)
        today = _open(_copy(load_src, tmp_path / "today-ids"))
    _kept(load_src)
    series = _open(load_src)
    try:
        wdir = series.getwdir()
        for snum in sorted(series.sections):
            name = series.sections[snum]
            key = lazy_sections.readStub(os.path.join(wdir, name))["key"]
            before = _stubbed(series)
            section = series.loadSection(snum)
            assert before - _stubbed(series) == {snum}
            data = Path(wdir, name).read_bytes()
            assert data == expected[name]
            assert hashlib.sha256(data).hexdigest() == key
            assert _ids(section) == _ids(today.loadSection(snum))
        assert lazy_sections.MARKER not in os.listdir(wdir)
    finally:
        series.close()
        today.close()


# ---------------------------------------------------------------------------
# Save, close and backup write the eager bytes, and fill nothing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [store_save.MODE_STORE, store_save.MODE_JSER])
def test_one_edit_saved_and_closed_writes_the_eager_bytes_and_fills_nothing(mode, tmp_path, switch_on, monkeypatch):  # noqa: F811
    monkeypatch.setenv(store_save.ENV_MODE, mode)

    def run(sub, lazy):
        fp = _kept(_copy(PARITY, tmp_path / sub))
        with monkeypatch.context() as m:
            if not lazy:
                _eager(m)
            series = _open(fp)
            if lazy:
                assert _stubbed(series) == set(series.sections)
            _edit(series)
            filled = _fills(m)
            if not series.saveToStore():
                series.saveJser()
            saved = fp.read_bytes()
            backup = tmp_path / sub / "backup.jser"
            series.saveJser(str(backup))
            fills = list(filled)
            series.close()
        return saved, fp.read_bytes(), backup.read_bytes(), fills

    lazy = run("lazy", True)
    eager = run("eager", False)
    assert lazy[3] == []
    assert lazy[:3] == eager[:3]


# ---------------------------------------------------------------------------
# Save As
# ---------------------------------------------------------------------------

def test_save_as_fills_every_stub_before_the_store_is_let_go(tmp_path, switch_on, monkeypatch):  # noqa: F811

    def run(sub, lazy):
        fp = _kept(_copy(PARITY, tmp_path / sub))
        old = fp.read_bytes()
        new = tmp_path / sub / "elsewhere" / "renamed.jser"
        new.parent.mkdir()
        with monkeypatch.context() as m:
            if not lazy:
                _eager(m)
            series = _open(fp)
            stubs_at_release = []
            real_release = store_save.release

            def release(s):
                stubs_at_release.append(_stubbed(s))
                real_release(s)

            m.setattr(store_save, "release", release)
            series.move(str(new))
            series.saveJser()
            assert stubs_at_release == [set()]
            assert not series._lazy and _stubbed(series) == set()
            series.close()
        assert fp.read_bytes() == old
        return new.read_bytes()

    assert run("lazy", True) == run("eager", False)


# ---------------------------------------------------------------------------
# renumbering
# ---------------------------------------------------------------------------

def test_insert_reorder_and_delete_then_save_write_the_eager_bytes(tmp_path, switch_on, monkeypatch):  # noqa: F811

    def run(sub, lazy):
        fp = _kept(_copy(SERIES_FILES[1], tmp_path / sub))
        with monkeypatch.context() as m:
            if not lazy:
                _eager(m)
            series = _open(fp)
            snums = sorted(series.sections)
            src = series.loadSection(snums[0]).src
            series.insertSection(snums[len(snums) // 2], src, 0.00254, 0.05)
            snums = sorted(series.sections)
            # a section below the insert: not renumbered, so still a stub
            if lazy:
                assert snums[1] in series._lazy
            series.deleteSections([snums[1]])
            snums = sorted(series.sections)
            swap = {s: s for s in snums}
            swap[snums[1]], swap[snums[2]] = snums[2], snums[1]
            series.reorderSections(swap)
            if not series.saveToStore():
                series.saveJser()
            series.close()
        return fp.read_bytes()

    assert run("lazy", True) == run("eager", False)


# ---------------------------------------------------------------------------
# worker threads
# ---------------------------------------------------------------------------

def test_stubs_fill_on_worker_threads(tmp_path, switch_on, monkeypatch):  # noqa: F811
    src = SERIES_FILES[1]
    expected = _today(src, tmp_path, monkeypatch)["files"]
    fp = _kept(_copy(src, tmp_path / "s"))
    series = _open(fp)
    errors = []
    try:
        def load(snum):
            try:
                series.loadSection(snum)
            except BaseException as e:  # noqa: BLE001  (reported below)
                errors.append(e)

        # every section, each from two threads at once
        threads = [threading.Thread(target=load, args=(s,)) for s in sorted(series.sections) * 2]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        wdir = series.getwdir()
        assert {n: Path(wdir, n).read_bytes() for n in series.sections.values()} == {
            n: expected[n] for n in series.sections.values()
        }
        assert not list(Path(wdir).glob(f"*{lazy_sections.FILL_SUFFIX}"))
    finally:
        series.close()


def test_a_zarr_export_and_a_labels_import_give_the_eager_output(qapp, tmp_path, switch_on, monkeypatch):  # noqa: F811
    zarr = pytest.importorskip("zarr")
    from PyReconstruct.modules.backend.autoseg import conversions

    def run(sub, lazy):
        fp = _kept(_copy(PARITY, tmp_path / sub))
        with monkeypatch.context() as m:
            if not lazy:
                _eager(m)
            series = _open(fp)
            try:
                snums = sorted(series.sections)
                out = conversions.seriesToZarr(
                    series, snums, 0.01, [0.0, 0.0, 0.5, 0.5], data_fp=str(tmp_path / sub / "out.zarr"),
                )
                assert out is not None
                group = "lazy_test"
                for name in list(series.data.objects):
                    series.object_groups.add(group, name)
                assert conversions.seriesToLabels(series, out, group=group, img_mag=0.01)
                if lazy:
                    # the import on a fresh lazy reopen, every section a stub
                    series.close()
                    series = _open(fp)
                    assert _stubbed(series) == set(series.sections)
                assert conversions.labelsToObjects(series, out, f"labels_{group}")
                series.presentAllSections()
                wdir = series.getwdir()
                files = {n: Path(wdir, n).read_bytes() for n in series.sections.values()}
                data = zarr.open(out, "r")
                arrays = {k: np.asarray(data[k]).tobytes() for k in sorted(data.array_keys())}
            finally:
                series.close()
        return files, arrays

    lazy = run("lazy", True)
    eager = run("eager", False)
    assert lazy[1] == eager[1]
    assert lazy[0] == eager[0]


# ---------------------------------------------------------------------------
# a store copy that no longer matches its stub
# ---------------------------------------------------------------------------

def _tamper_store(fp, snum):
    """Change section snum in the store, behind the series' back."""
    db_fp = storePaths(str(fp))[0]
    con = sqlite3.connect(db_fp, isolation_level=None)
    try:
        con.execute("PRAGMA busy_timeout=5000")
        (header,) = con.execute("SELECT header FROM section WHERE snum=?", (snum,)).fetchone()
        doc = fast_loads(header)
        doc["thickness"] = 0.123
        con.execute("UPDATE section SET header=? WHERE snum=?", (fast_dumps(doc), snum))
    finally:
        con.close()


def _saved_by_this_app(tmp_path):
    """A kept series whose .jser this app wrote, so its stubs carry a range."""
    fp = _copy(PARITY, tmp_path / "s")
    series = _open(fp)
    series.saveJser()
    series.close()
    return fp


def test_a_stub_whose_store_copy_changed_fills_from_the_jser(tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _saved_by_this_app(tmp_path)
    expected = _today(fp, tmp_path, monkeypatch)["files"]
    series = _open(fp)
    try:
        snum = 1
        name = series.sections[snum]
        assert lazy_sections.readStub(os.path.join(series.getwdir(), name))["range"] is not None
        _tamper_store(fp, snum)
        series.loadSection(snum)
        assert Path(series.getwdir(), name).read_bytes() == expected[name]
    finally:
        series.close()


def test_a_stub_no_source_matches_is_kept_and_a_save_of_the_jser_refuses(tmp_path, switch_on, monkeypatch):  # noqa: F811
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_JSER)
    fp = _saved_by_this_app(tmp_path)
    series = _open(fp)
    series.setNotifier(_Quiet())
    try:
        snum = 1
        stub_fp = Path(series.getwdir(), series.sections[snum])
        stub_bytes = stub_fp.read_bytes()
        offset, length = lazy_sections.readStub(str(stub_fp))["range"]
        _tamper_store(fp, snum)
        # the .jser's bytes at that range change too
        with open(fp, "r+b") as f:
            f.seek(offset + length // 2)
            byte = f.read(1)
            f.seek(offset + length // 2)
            f.write(b"0" if byte != b"0" else b"1")
        jser_bytes = fp.read_bytes()
        with pytest.raises(lazy_sections.SectionUnavailable):
            series.loadSection(snum)
        assert stub_fp.read_bytes() == stub_bytes
        assert not list(Path(series.getwdir()).glob(f"*{lazy_sections.FILL_SUFFIX}"))
        with pytest.raises(SeriesSaveError):
            series.saveJser()
        assert fp.read_bytes() == jser_bytes
    finally:
        _crash(series)


# ---------------------------------------------------------------------------
# a resumed folder
# ---------------------------------------------------------------------------

def test_a_crashed_lazy_folder_is_filled_and_resumed_with_the_switch_off(tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    expected = _today(fp, tmp_path, monkeypatch)["files"]
    series = _open(fp)
    edited = _edit(series)
    series.save()
    edited_name = series.sections[edited]
    edited_bytes = Path(series.getwdir(), edited_name).read_bytes()
    wdir = series.getwdir()
    _crash(series)
    monkeypatch.delenv(store_open.ENV_SWITCH)
    resumed = _open(fp, notifier=_NoDialog())
    try:
        assert resumed.getwdir() == wdir
        files = {n: Path(wdir, n).read_bytes() for n in resumed.sections.values()}
        assert files.pop(edited_name) == edited_bytes
        assert files == {n: expected[n] for n in files}
        assert lazy_sections.MARKER not in os.listdir(wdir)
        for snum in resumed.sections:
            resumed.loadSection(snum)
    finally:
        resumed.close()


def test_a_crashed_lazy_folder_no_source_matches_is_set_aside_whole(tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    series = _open(fp)
    wdir = Path(series.getwdir())
    _crash(series)
    before = {p.name: p.read_bytes() for p in wdir.iterdir()}
    # the store gone, and the stubs name no range of the .jser
    for p in Path(switch_on).iterdir():
        if p.is_file():
            p.unlink()
    asker = _Quiet()
    monkeypatch.delenv(store_open.ENV_SWITCH)
    opened = _open(fp, notifier=asker)
    try:
        assert opened.getwdir() == str(wdir)
        assert _stubbed(opened) == set()
    finally:
        opened.close()
    aside = [p for p in wdir.parent.iterdir() if p.name.startswith(f"{wdir.name}.lazy-")]
    assert len(aside) == 1
    assert {p.name: p.read_bytes() for p in aside[0].iterdir()} == before
    assert len(asker.told) == 1 and str(aside[0]) in asker.told[0]


# ---------------------------------------------------------------------------
# an older build given a lazy folder
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]

_OLD_BUILD_DRIVER = '''\
"""Take up a working folder as this build does, then Save its .jser."""
import json, os, sys, traceback

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6 import QtCore


class _NoSettings:
    """Keeps this process away from the real settings."""

    def __init__(self, *a, **k):
        raise RuntimeError("QSettings is blocked here")


QtCore.QSettings = _NoSettings

import PyReconstruct
from PyReconstruct.modules.backend.settings_store import DictSettingsStore, set_default_settings_store
from PyReconstruct.modules.datatypes.series import Series

set_default_settings_store(DictSettingsStore())
jser_fp, result_fp = sys.argv[1], sys.argv[2]
stem = os.path.splitext(os.path.basename(jser_fp))[0]
wdir = os.path.join(os.path.dirname(jser_fp), "." + stem)
got = {"package": PyReconstruct.__file__}


def attempt(key, step):
    """got[key]: None when the step finished, else what stopped it."""
    got[key] = None
    try:
        step()
    except Exception as e:
        got[key] = {
            "error": type(e).__name__, "value_error": isinstance(e, ValueError),
            "text": str(e)[:300], "trace": traceback.format_exc()[-1500:],
        }


# opening the .jser, or answering yes to its unsaved work, builds a Series from the
# folder listing and reads every section
attempt("open", lambda: Series.openJser(jser_fp))

# a Series from the same listing that has read no section, then a Save
def save():
    sections = {}
    for name in os.listdir(wdir):
        ext = name.rsplit(".", 1)[-1]
        if "." in name and ext.isnumeric():
            sections[int(ext)] = name
    series = Series(os.path.join(wdir, stem + ".ser"), sections, get_series_data=False)
    series.jser_fp = jser_fp
    series.saveJser()


attempt("save", save)
with open(result_fp, "w", encoding="utf-8") as f:
    json.dump(got, f)
'''


def _extract(tag, tmp_path) -> Path:
    """`git archive` of a tag, or a skip saying why."""
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", tag], capture_output=True)
    if proc.returncode != 0:
        pytest.skip(f"cannot git archive {tag}: {proc.stderr.decode('utf-8', 'replace')[:200]}")
    dest = tmp_path / f"build-{tag}"
    dest.mkdir()
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
        try:
            archive.extractall(dest, filter="data")
        except TypeError:  # pragma: no cover - Python < 3.12
            archive.extractall(dest)
    return dest


def _files(folder) -> dict:
    return {p.name: p.read_bytes() for p in Path(folder).iterdir()}


@pytest.mark.parametrize("tag", ["v1.24.0"])
def test_an_older_build_given_a_lazy_folder_writes_no_jser(tag, tmp_path, switch_on, monkeypatch):  # noqa: F811
    """v1.24.0 reads each section file as JSON: it cannot open the folder, and its Save refuses."""
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    series = _open(fp)
    _edit(series)
    wdir = series.getwdir()
    assert _stubbed(series)
    _crash(series)
    jser, folder = fp.read_bytes(), _files(wdir)

    build = _extract(tag, tmp_path)
    (build / "_driver.py").write_text(_OLD_BUILD_DRIVER, encoding="utf-8")
    result = tmp_path / "result.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYRECON_")}
    proc = subprocess.run(
        [sys.executable, "_driver.py", str(fp), str(result)],
        cwd=str(build), env=env, capture_output=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    got = json.loads(result.read_bytes())
    assert str(build) in got["package"]
    # the open stops at a stub, read as JSON
    assert got["open"] and got["open"]["value_error"], got["open"]
    # the Save refuses at a stub
    assert got["save"] and got["save"]["error"] == "SeriesSaveError", got["save"]
    assert "could not be read" in got["save"]["text"], got["save"]
    assert fp.read_bytes() == jser
    assert _files(wdir) == folder


# ---------------------------------------------------------------------------
# cleanup, and letting go of the store
# ---------------------------------------------------------------------------

def test_cleanup_keeps_a_clean_store_a_folder_s_stubs_need(tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    series = _open(fp)
    _crash(series)
    root = local_stores.storeFolder()
    name = os.path.basename(storePaths(str(fp))[0])
    state = local_stores.removeIfClean(root, name)
    assert not state.clean and state.why == local_stores.STUBS
    assert os.path.isfile(os.path.join(root, name))
    # once the folder holds no stub, the same store is clean
    shutil.rmtree(Path(fp).parent / f".{Path(fp).stem}")
    assert local_stores.removeIfClean(root, name).clean


@pytest.mark.parametrize("how", ["give-up", "turn-off"])
def test_letting_go_of_the_store_mid_session_fills_every_stub_first(how, tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    series = _open(fp)
    try:
        stubs_at_release = []
        real_release = store_save.release

        def release(s):
            stubs_at_release.append(_stubbed(s))
            real_release(s)

        monkeypatch.setattr(store_save, "release", release)
        if how == "give-up":
            store_save._giveUp(series, store_save.heldStore(series), OSError("a test"))
        else:
            local_stores.turnOff(series)
        assert stubs_at_release == [set()]
        assert store_save.heldStore(series) is None
        assert not series._lazy
    finally:
        series.close()


def _remove_if_clean(fp):
    root = local_stores.storeFolder()
    name = os.path.basename(storePaths(str(fp))[0])
    return local_stores.removeIfClean(root, name), os.path.join(root, name)


def test_cleanup_keeps_the_store_of_a_folder_opened_through_a_link(tmp_path, switch_on, monkeypatch):  # noqa: F811
    real = _copy(PARITY, tmp_path / "real")
    (tmp_path / "alias").mkdir()
    alias = tmp_path / "alias" / "linked.jser"
    alias.symlink_to(real)
    _kept(alias)
    series = _open(alias)
    edited = _edit(series)
    series.save()
    wdir = Path(series.getwdir())
    assert wdir.parent == alias.parent and _stubbed(series)
    edited_bytes = (wdir / series.sections[edited]).read_bytes()
    _crash(series)
    state, db_fp = _remove_if_clean(real)
    assert not state.clean and state.why == local_stores.STUBS
    assert os.path.isfile(db_fp)
    # the resume finds every section, the edit with them
    monkeypatch.delenv(store_open.ENV_SWITCH)
    resumed = _open(alias, notifier=_NoDialog())
    try:
        assert Path(resumed.getwdir()) == wdir and _stubbed(resumed) == set()
        assert (wdir / resumed.sections[edited]).read_bytes() == edited_bytes
    finally:
        resumed.close()


def test_cleanup_keeps_the_store_of_a_folder_beside_another_series_folder(tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    # the usual folder belongs to another series, so the open writes into .<name>-2
    usual = fp.parent / f".{fp.stem}"
    usual.mkdir()
    (usual / "other.ser").write_text("{}")
    series = _open(fp)
    wdir = Path(series.getwdir())
    assert wdir != usual and _stubbed(series)
    _crash(series)
    state, db_fp = _remove_if_clean(fp)
    assert not state.clean and state.why == local_stores.STUBS
    assert os.path.isfile(db_fp)
    # once that folder holds no stub, the store is clean
    shutil.rmtree(wdir)
    assert _remove_if_clean(fp)[0].clean


@pytest.mark.parametrize("how", ["give-up", "turn-off"])
def test_a_fill_that_fails_keeps_the_store_and_says_so(how, tmp_path, switch_on, notes, monkeypatch):  # noqa: F811
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    series = _open(fp)
    try:
        def full(*a, **k):
            raise OSError(28, "No space left on device")

        with monkeypatch.context() as m:
            m.setattr(lazy_sections, "sectionBytes", full)
            if how == "give-up":
                store_save._giveUp(series, store_save.heldStore(series), OSError("a test"))
            else:
                report = local_stores.turnOff(series)
                assert report.kept == [str(fp)]
                assert str(fp) in local_stores.turnOffText(report)
        assert store_save.heldStore(series) is not None
        assert _stubbed(series) == set(series.sections)
        assert any("not every section" in n for n in notes)
    finally:
        series.close()


def _left_by_a_link(src, tmp_path):
    """A folder opened through a link to src, one section edited, left as a crash leaves it."""
    alias = tmp_path / "alias.jser"
    alias.symlink_to(src)
    first = _open(alias)
    section = first.loadSection(0)
    section.thickness = 0.321
    section.save()
    first.save()
    folder = Path(first.getwdir())
    stubbed = _stubbed(first)
    _crash(first)
    return alias, folder, stubbed


@pytest.mark.parametrize("ranges", [False, True], ids=["no-ranges", "ranges"])
def test_a_session_by_another_path_leaves_a_crashed_folder_whole(ranges, tmp_path, switch_on, monkeypatch):  # noqa: F811
    src = _saved_by_this_app(tmp_path) if ranges else _kept(_copy(PARITY, tmp_path / "original"))
    alias, folder, stubbed = _left_by_a_link(src, tmp_path)
    assert stubbed
    # a session on the file itself saves over a section the folder had as a stub
    second = _open(src)
    assert store_save.heldStore(second) is not None
    section = second.loadSection(1)
    section.thickness = 0.456
    section.save()
    assert second.saveToStore()
    second.close()
    asker = _Quiet()
    resumed = _open(alias, notifier=asker)
    try:
        assert Path(resumed.getwdir()) == folder and asker.told == []
        assert resumed.loadSection(0).thickness == 0.321
        assert resumed.loadSection(1).thickness != 0.456
    finally:
        resumed.close()


def test_a_crashed_folder_by_another_path_no_source_matches_keeps_the_store_unused(tmp_path, switch_on, notes, monkeypatch):  # noqa: F811
    src = _kept(_copy(PARITY, tmp_path / "original"))
    alias, folder, stubbed = _left_by_a_link(src, tmp_path)
    snum = min(stubbed)
    _tamper_store(src, snum)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    second = _open(src)
    try:
        # opened as today, from the .jser, and the store is not taken
        assert store_save.heldStore(second) is None and _stubbed(second) == set()
        assert any(str(folder) in n for n in notes)
    finally:
        second.close()
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


def test_deleting_the_last_stub_lets_cleanup_remove_the_store(tmp_path, switch_on):  # noqa: F811
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    series = _open(fp)
    for snum in sorted(series.sections)[:-1]:
        series.loadSection(snum)
    series.deleteSections([max(series.sections)])
    assert not series._lazy
    _crash(series)
    state, db_fp = _remove_if_clean(fp)
    assert state.clean and not os.path.exists(db_fp)


BAD_STUBS = {
    "truncated": lazy_sections.MAGIC + b"{",
    "bad-key": lazy_sections.MAGIC + b'{"snum": 1, "key": "zz", "store": "x.v1.pyrstore", "range": null}',
    "store-path": lazy_sections.MAGIC + b'{"snum": 1, "key": "' + b"00" * 32 + b'", "store": "../x", "range": null}',
}


@pytest.mark.parametrize("bad", sorted(BAD_STUBS))
def test_a_bad_stub_in_a_folder_by_another_path_does_not_stop_the_open(bad, tmp_path, switch_on, notes, monkeypatch):  # noqa: F811
    src = _kept(_copy(PARITY, tmp_path / "original"))
    alias, folder, stubbed = _left_by_a_link(src, tmp_path)
    (folder / f"{alias.stem}.1").write_bytes(BAD_STUBS[bad])
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    second = _open(src)
    try:
        # opened from the .jser, the store not taken, the folder as it was
        assert store_save.heldStore(second) is None
        assert second.loadSection(0).thickness == 0.05
        assert any(str(folder) in n for n in notes)
    finally:
        second.close()
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


@pytest.mark.parametrize("bad", sorted(BAD_STUBS))
def test_a_bad_stub_in_this_session_fails_its_load_and_a_save(bad, tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    series = _open(fp)
    series.setNotifier(_Quiet())
    try:
        stub_fp = Path(series.getwdir(), series.sections[1])
        stub_fp.write_bytes(BAD_STUBS[bad])
        with pytest.raises(lazy_sections.SectionUnavailable):
            series.loadSection(1)
        assert stub_fp.read_bytes() == BAD_STUBS[bad]
        with pytest.raises(SeriesSaveError):
            series.saveToStore()
        with pytest.raises(SeriesSaveError):
            series.saveJser()
    finally:
        _crash(series)


def test_a_bad_stub_in_a_resumed_folder_sets_it_aside_whole(tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    series = _open(fp)
    wdir = Path(series.getwdir())
    _crash(series)
    # the first stub, so none is filled before it
    Path(wdir, f"{fp.stem}.0").write_bytes(BAD_STUBS["truncated"])
    before = {p.name: p.read_bytes() for p in wdir.iterdir()}
    asker = _Quiet()
    opened = _open(fp, notifier=asker)
    try:
        # a fresh open of the .jser, every section of it readable
        for snum in opened.sections:
            opened.loadSection(snum)
    finally:
        opened.close()
    aside = [p for p in wdir.parent.iterdir() if p.name.startswith(f"{wdir.name}.lazy-")]
    assert len(aside) == 1 and {p.name: p.read_bytes() for p in aside[0].iterdir()} == before
    assert len(asker.told) == 1
