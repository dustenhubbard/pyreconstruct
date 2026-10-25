"""Section files written on first need after an open from the local store (lazy_sections.py).

An open from the store writes a stub for each section the store holds as its
working file, and the first load of a section writes its file. Everything a
series does after that open must give the bytes it gives when every section
file is written at open, so most of these run the same steps both ways and
compare the files and the .jser.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import threading
from pathlib import Path

import numpy as np
import pytest

from PyReconstruct.modules.constants import fast_dumps, fast_loads
from PyReconstruct.modules.datatypes import lazy_sections, local_stores, store_open, store_save
from PyReconstruct.modules.datatypes.hybrid_store import HybridStore, storePaths
from PyReconstruct.modules.datatypes.series import Series, SeriesSaveError
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
# 1. the reopen writes stubs
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
# 2. a load fills its own section, as the eager open wrote it
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
# 3, 4. Save, close and backup write the eager bytes, and fill nothing
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
# 5. Save As
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
# 6. renumbering
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
# 7. worker threads
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
# 8. a store copy that no longer matches its stub
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
# 9. a resumed folder
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
# 10. a reader with no seam
# ---------------------------------------------------------------------------

def test_a_reader_that_takes_a_stub_for_json_writes_no_jser(tmp_path, switch_on, monkeypatch):  # noqa: F811
    """A reader with no seam: a series built from the folder listing, each file read as JSON.

    Its open fails at the first stub, and its Save refuses and leaves the .jser as it was.
    """
    fp = _kept(_copy(PARITY, tmp_path / "s"))
    series = _open(fp)
    wdir = series.getwdir()
    _crash(series)
    jser = fp.read_bytes()
    monkeypatch.delenv(store_open.ENV_SWITCH)
    monkeypatch.setattr(lazy_sections, "presentFolder", lambda *a, **k: True)
    monkeypatch.setattr(
        Series, "presentSection", lambda self, snum: os.path.join(self.getwdir(), self.sections[snum])
    )
    # its open loads every section, and the first stub stops it
    with pytest.raises(ValueError):
        Series.openJser(str(fp), notifier=_NoDialog())
    # its Save, from the folder as listed, refuses
    sections = {int(n.rsplit(".", 1)[1]): n for n in os.listdir(wdir) if n.rsplit(".", 1)[1].isdigit()}
    old = Series(os.path.join(wdir, f"{Path(fp).stem}.ser"), sections, get_series_data=False)
    old.jser_fp = str(fp)
    old.setNotifier(_Quiet())
    with pytest.raises(SeriesSaveError):
        old.saveJser()
    assert fp.read_bytes() == jser
    assert any(Path(wdir, n).read_bytes().startswith(lazy_sections.MAGIC) for n in sections.values())


# ---------------------------------------------------------------------------
# 11. cleanup, and letting go of the store
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
