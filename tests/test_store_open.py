"""Opening a series from its local store (store_open.py), behind the switch.

The oracle is today's open of the same file: an open from the store must give
the same working folder, the same series, and the same object list, number
for number (floats compared by repr, so 0 and 0.0 differ).

What these pin:

* the switch: only PYRECON_HYBRID_STORE=1 turns it on, and off no store is made;
* the first open is today's open, and it keeps the store; the next open comes
  from the store, builds no section and reads nothing from the .jser, and
  equals today's open in every section, in the series, and in the object list
  (which also equals a full refresh);
* an open from the store builds no per-trace object;
* any refusal of the store (a network folder, a store another process holds,
  a file that is not a store, a read that fails) opens as today, quietly,
  with one log line and no dialog, while a fault in the code still raises;
* a store that no longer holds the .jser, holds work the .jser lacks, or
  would need a merge question asked again is not read;
* network folders are told apart on macOS, Windows and Linux.
"""
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import hybrid_store, lazy_sections, network_folder, store_open
from PyReconstruct.modules.datatypes import section as section_module
from PyReconstruct.modules.datatypes.hybrid_store import HybridStore, storePaths
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.series_data import SeriesData

from test_hybrid_store import (
    _EDGE_CASES, PARITY, SERIES_FILES, _edge_series, full_field_series, legacy_series,
    store_root,  # noqa: F401  (fixture)
)


class _NoDialog:
    """A notifier that fails the test if the open asks or tells anything."""

    def confirm(self, *a, **k):
        raise AssertionError(f"the open asked: {a}")

    def notify(self, *a, **k):
        raise AssertionError(f"the open told: {a}")


@pytest.fixture
def switch_on(monkeypatch, store_root):  # noqa: F811
    monkeypatch.setenv(store_open.ENV_SWITCH, "1")
    return store_root


@pytest.fixture
def notes(monkeypatch):
    """The lines the store code writes to the app's log."""
    lines = []
    monkeypatch.setattr(store_open, "log_note", lines.append)
    return lines


def _open(fp, notifier=None):
    series = Series.openJser(str(fp), progress=NullProgressReporter, notifier=notifier)
    series.setProgressReporter(NullProgressReporter)
    return series


def _copy(src, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / Path(src).name
    shutil.copyfile(src, dest)
    return dest


def rich_series(folder, partial=True) -> Path:
    """The parity series with alignments to replay, thicknesses, and every trace kind.

    axon is fixed to an alignment every section has. With `partial`,
    dendrite01 is fixed to one only section 0 has, so the open clears it on
    section 1 and measures the rest in the series' alignment.
    """
    doc = json.loads(PARITY.read_bytes())
    sections = [s for s in doc["sections"] if s]
    for i, sec in enumerate(sections):
        sec["thickness"] = [0.05, 0.07, 0.1][i]
        sec["tforms"]["other"] = [1, 0, 5.5, 0, 1.25, -3]
        if i == 0:
            sec["tforms"]["partial"] = [2, 0, 0, 0, 2, 0]
        base = copy.deepcopy(next(iter(sec["contours"].values()))[0])
        open_row = copy.deepcopy(base)
        open_row[3] = False
        neg = copy.deepcopy(base)
        neg[3], neg[4] = True, True
        sec["contours"][f"extra{i}"] = [open_row, neg]
    doc["series"]["obj_attrs"] = {
        "axon": {"alignment": "other", "comment": "kept"},
        "dendrite01": {"alignment": "partial" if partial else "other"},
    }
    fp = Path(folder) / "rich.jser"
    fp.write_text(json.dumps(doc))
    return fp


def _built_sections(monkeypatch):
    """A list that gets one entry per Section built from now on."""
    built = []
    real = section_module.Section.__init__

    def counting(self, n, *a, **k):
        built.append(n)
        return real(self, n, *a, **k)

    monkeypatch.setattr(section_module.Section, "__init__", counting)
    return built


def _getters(data : SeriesData) -> dict:
    """Every object-list number, by repr, for every object, in the list's order."""
    out = {}
    for name in data.objects:
        out[name] = repr((
            data.getStart(name), data.getEnd(name), data.getCount(name),
            data.getFlatArea(name), data.getVolume(name), data.getConfiguration(name),
            sorted(data.getTags(name), key=repr), sorted(data.getColorCounts(name).items(), key=repr),
            data.getAvgRadius(name),
        ))
    out[None] = repr(sorted(data.usedTags(), key=repr))
    return out


def _traces(data : SeriesData) -> dict:
    """Every per-trace field, by repr (builds the TraceData)."""
    out = {}
    for name, obj in data.objects.items():
        out[name] = repr([
            (snum, [
                (td.index, td.closed, td.hidden, td.negative, type(td.tags).__name__,
                 sorted(td.tags, key=repr), td.color, td.length, td.area, td.centroid,
                 td.radius, td._tform.getList(), td._feret)
                for td in tds
            ])
            for snum, tds in obj.traces.items()
        ])
    return out


def _sections(data : SeriesData) -> dict:
    out = {}
    for snum, d in data.data["sections"].items():
        out[snum] = repr((
            d["thickness"], d["calgrid"], d["locked"], d["bc_profiles"], d["src"],
            d["mag"], [f.getList() for f in d["flags"]],
            {a: t.getList() for a, t in d["tforms"].items()},
        ))
    return out


def _snapshot(series) -> dict:
    """What an open gives: the working folder, the series, the object list.

    Every section file is filled first (an open from the store writes stubs,
    lazy_sections.py), so the files are what the open's sections hold.
    """
    wdir = series.getwdir()
    data = series.data
    getters = _getters(data)  # before anything builds the TraceData
    series.presentAllSections()
    index = getattr(series, "_jser_splice_index", None)
    ids = data.object_ids
    return {
        "files": {
            f: Path(wdir, f).read_bytes() for f in sorted(os.listdir(wdir))
            if f != lazy_sections.MARKER
        },
        "sections_listed": dict(series.sections),
        "series": repr(series.getDict()),
        "obj_attrs": repr(series.obj_attrs),
        "bc_profile": series.bc_profile,
        "objects": list(data.objects),
        "getters": getters,
        "section_data": _sections(data),
        "traces": _traces(data),
        "placed": sorted(ids.placed.items()),
        "one_id_per_name": all(len(ids.live(n)) == 1 for n in data.objects),
        "splice": None if index is None else sorted(index.ranges.items()),
    }


def _today(src, tmp_path, monkeypatch):
    """The snapshot of today's open of a copy of src, with the switch off."""
    with monkeypatch.context() as m:
        m.delenv(store_open.ENV_SWITCH, raising=False)
        series = _open(_copy(src, tmp_path / "today"))
        try:
            return _snapshot(series)
        finally:
            series.close()


SOURCES = {
    **{p.name: (lambda folder, p=p: _copy(p, folder)) for p in SERIES_FILES},
    "legacy": legacy_series,
    "fields": full_field_series,
    "rich": rich_series,
}


@pytest.fixture(params=sorted(SOURCES))
def src(request, tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    return SOURCES[request.param](folder)


def _reads_no_jser(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the .jser was read")
    monkeypatch.setattr(Series, "_readJserForOpen", staticmethod(refuse))


# ---------------------------------------------------------------------------
# the switch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "0", "true", "yes", " 1"])
def test_only_the_value_1_turns_it_on_and_off_no_store_is_made(value, tmp_path, store_root, monkeypatch):  # noqa: F811
    if value is None:
        monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    else:
        monkeypatch.setenv(store_open.ENV_SWITCH, value)

    def refuse(*a, **k):
        raise AssertionError("store code ran with the switch off")

    monkeypatch.setattr(store_open, "openJser", refuse)
    series = _open(_copy(PARITY, tmp_path / "s"))
    series.close()
    assert not store_root.exists()


def test_a_working_folder_to_resume_is_resumed_not_opened_from_the_store(tmp_path, switch_on, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    series = _open(fp)
    series.leave_open = True  # a crash: the working folder stays
    wdir = series.getwdir()

    def refuse(*a, **k):
        raise AssertionError("the store was opened")

    # the resume may give the series its store (store_recovery.resumed), but
    # the series comes from the folder
    monkeypatch.setattr(store_open, "openJser", refuse)
    again = _open(fp)
    assert again.getwdir() == wdir
    again.close()


# ---------------------------------------------------------------------------
# open from the store equals today's open
# ---------------------------------------------------------------------------

def test_the_first_open_is_today_s_and_the_next_comes_from_the_store_and_equals_it(src, tmp_path, switch_on, notes, monkeypatch):
    expected = _today(src, tmp_path, monkeypatch)

    first = _open(src, notifier=None)
    try:
        assert _snapshot(first) == expected
    finally:
        first.close()

    built = _built_sections(monkeypatch)
    _reads_no_jser(monkeypatch)
    second = _open(src, notifier=_NoDialog())
    try:
        # no section is loaded and no per-trace object is built at open
        assert built == []
        assert all(obj.columnRows() is not None for obj in second.data.objects.values())
        assert _snapshot(second) == expected
    finally:
        second.close()
    assert notes == []


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # today's open, on an infinite coordinate
@pytest.mark.parametrize("place, name, surrogate", _EDGE_CASES,
                         ids=[f"{p}-{n}" + ("-with-a-surrogate" if s else "") for p, n, s in _EDGE_CASES])
def test_an_edge_value_opens_from_the_store_as_today(place, name, surrogate, tmp_path, switch_on, notes, monkeypatch):
    """A section the store keeps with the stdlib writer opens from it as today."""
    folder = tmp_path / "src"
    folder.mkdir()
    src = _edge_series(folder, place, name, surrogate)
    expected = _today(src, tmp_path, monkeypatch)
    _open(src).close()
    built = _built_sections(monkeypatch)
    _reads_no_jser(monkeypatch)
    series = _open(src, notifier=_NoDialog())
    try:
        assert built == []
        assert _snapshot(series) == expected
    finally:
        series.close()
    assert notes == []


@pytest.mark.parametrize("make", [
    *(lambda folder, p=p: _copy(p, folder) for p in SERIES_FILES),
    legacy_series, full_field_series, lambda folder: rich_series(folder, partial=False),
])
def test_the_object_list_from_the_store_equals_a_full_refresh(make, tmp_path, switch_on, monkeypatch):
    """A full refresh of the opened series: the same numbers.

    (Not with an alignment the open clears: the refresh then measures in
    another alignment than the open did, today as with the store.)
    """
    src = make(tmp_path)
    _open(src).close()
    series = _open(src)
    try:
        from_store = _getters(series.data)
        refreshed = SeriesData(series)
        refreshed.refresh(show_progress=False)
        assert from_store == _getters(refreshed)
        assert _traces(series.data) == _traces(refreshed)
        assert _sections(series.data) == _sections(refreshed)
    finally:
        series.close()


def test_a_fixed_alignment_a_section_lacks_is_cleared_as_today(tmp_path, switch_on, monkeypatch):
    src = rich_series(tmp_path)
    _open(src).close()
    series = _open(src)
    try:
        # cleared by the open from the store, as by today's open
        assert series.getAttr("dendrite01", "alignment") is None
        assert series.getAttr("axon", "alignment") == "other"
        dendrite = series.data.objects["dendrite01"]
        tforms = {snum: tds[0]._tform.getList() for snum, tds in dendrite.traces.items()}
        assert tforms[0] == [2, 0, 0, 0, 2, 0]
        assert tforms[1] == series.data.data["sections"][1]["tforms"]["default"].getList()
    finally:
        series.close()


def test_an_edit_and_save_after_an_open_from_the_store_writes_today_s_bytes(tmp_path, switch_on, monkeypatch):
    def edit_and_save(fp):
        series = _open(fp)
        try:
            section = series.loadSection(min(series.sections))
            trace = next(iter(section.contours.values()))[0]
            section.deleteTraces([trace])
            section.save()
            series.saveJser()
        finally:
            series.close()
        return fp.read_bytes()

    with monkeypatch.context() as m:
        m.delenv(store_open.ENV_SWITCH)
        expected = edit_and_save(_copy(PARITY, tmp_path / "today"))

    fp = _copy(PARITY, tmp_path / "store")
    _open(fp).close()
    assert edit_and_save(fp) == expected


def test_the_first_save_after_an_open_from_the_store_splices_as_today(tmp_path, switch_on, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    # a file this app wrote, whose sections a save can copy
    saved = _open(fp)
    saved.saveJser()
    saved.close()
    first = _open(fp)
    expected = sorted(first._jser_splice_index.ranges.items())
    first.close()
    assert expected
    second = _open(fp)
    try:
        index = second._jser_splice_index
        assert index is not None and index.matchesDisk()
        assert sorted(index.ranges.items()) == expected
    finally:
        second.close()


# ---------------------------------------------------------------------------
# when the store is not read
# ---------------------------------------------------------------------------

def _store_opens(monkeypatch):
    """A list that gets one entry per open that comes from the store."""
    opens = []
    real = store_open.StoreForOpen.fillSeriesData

    def counting(self, series):
        opens.append(series.name)
        return real(self, series)

    monkeypatch.setattr(store_open.StoreForOpen, "fillSeriesData", counting)
    return opens


def test_a_changed_jser_is_opened_as_today_and_kept_again(tmp_path, switch_on, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    # another program writes the file: a different series under the same path
    shutil.copyfile(SERIES_FILES[1], fp)
    expected = _today(fp, tmp_path, monkeypatch)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    try:
        assert opens == []
        assert _snapshot(series) == expected
    finally:
        series.close()
    series = _open(fp)
    try:
        assert opens == [series.name]
        assert _snapshot(series) == expected
    finally:
        series.close()


def _same_size_other_content(fp) -> bytes:
    """fp's bytes with one object renamed to a name of the same length."""
    data = fp.read_bytes()
    assert data.count(b"dendrite01") and not data.count(b"dendrite02")
    return data.replace(b"dendrite01", b"dendrite02")


@pytest.mark.parametrize("how", ["rewritten-in-place", "copied-over"])
def test_other_bytes_with_the_same_size_and_time_are_not_read_from_the_store(how, tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    st = os.stat(fp)
    other = _same_size_other_content(fp)
    if how == "rewritten-in-place":
        fp.write_bytes(other)
        os.utime(fp, ns=(st.st_atime_ns, st.st_mtime_ns))
    else:
        # a copy that keeps the times, as cp -p and sync tools do
        elsewhere = tmp_path / "elsewhere" / fp.name
        elsewhere.parent.mkdir()
        elsewhere.write_bytes(other)
        os.utime(elsewhere, ns=(st.st_atime_ns, st.st_mtime_ns))
        shutil.copy2(elsewhere, fp)
    after = os.stat(fp)
    assert (after.st_size, after.st_mtime_ns) == (st.st_size, st.st_mtime_ns)
    expected = _today(fp, tmp_path, monkeypatch)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    try:
        assert opens == []
        assert "dendrite02" in series.data.objects and "dendrite01" not in series.data.objects
        assert _snapshot(series) == expected
    finally:
        series.close()


def test_the_same_bytes_with_a_new_time_open_from_the_store(tmp_path, switch_on, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    os.utime(fp, ns=(os.stat(fp).st_atime_ns, os.stat(fp).st_mtime_ns + 10**9))
    expected = _today(fp, tmp_path, monkeypatch)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    try:
        assert opens == [series.name]
        expected["splice"] = None  # the index names the file's old time, so Save writes in full
        assert _snapshot(series) == expected
    finally:
        series.close()


def test_the_store_records_the_sha256_of_the_file_it_holds(tmp_path, switch_on):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    store = HybridStore.forJser(str(fp))
    try:
        assert store.meta(store_open.META_SHA) == hashlib.sha256(fp.read_bytes()).hexdigest()
    finally:
        store.close()


def _write_in_place(fp, data, keep_time=True):
    """Overwrite fp's bytes in place (same file), keeping its modification time."""
    st = os.stat(fp)
    with open(fp, "r+b") as f:
        f.write(data)
    if keep_time:
        os.utime(fp, ns=(st.st_atime_ns, st.st_mtime_ns))


def _write_during_the_hash(monkeypatch, fp, data, keep_time=True):
    """Make the reopen's hash read the file in small parts, and write `data`
    into it after the first part (bytes the hash has already read)."""
    monkeypatch.setattr(store_open, "HASH_CHUNK", 1024)
    real = store_open._readChunk
    calls = []

    def reads(f, buf):
        n = real(f, buf)
        calls.append(n)
        if len(calls) == 1:
            _write_in_place(fp, data, keep_time)
        return n

    monkeypatch.setattr(store_open, "_readChunk", reads)
    return calls


def test_a_write_into_the_file_while_it_is_hashed_opens_as_today(tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    other = _same_size_other_content(fp)
    calls = _write_during_the_hash(monkeypatch, fp, other)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    try:
        assert len(calls) > 1 and opens == []
        assert "dendrite02" in series.data.objects and "dendrite01" not in series.data.objects
    finally:
        series.close()
    assert notes == ["Local store not used for parity_series.jser: parity_series.jser changed while it was being hashed"]


@pytest.mark.parametrize("rules", ["this-system", "windows"])
def test_a_file_renamed_over_it_while_it_is_hashed_opens_as_today(rules, tmp_path, switch_on, notes, monkeypatch):
    if rules == "windows":
        # no change time: only the path, read again, shows the new file
        monkeypatch.setattr(store_open, "_WINDOWS", True)
        monkeypatch.setitem(sys.modules, "msvcrt", _FakeMsvcrt())
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    other = _same_size_other_content(fp)
    st = os.stat(fp)
    monkeypatch.setattr(store_open, "HASH_CHUNK", 1024)
    real = store_open._readChunk
    calls = []

    def reads(f, buf):
        n = real(f, buf)
        calls.append(n)
        if len(calls) == 1:
            # a save that writes a new file and renames it over this one
            new = fp.with_name("saving.tmp")
            new.write_bytes(other)
            os.utime(new, ns=(st.st_atime_ns, st.st_mtime_ns))
            os.replace(new, fp)
        return n

    monkeypatch.setattr(store_open, "_readChunk", reads)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    try:
        assert opens == []
        assert "dendrite02" in series.data.objects
    finally:
        series.close()
    assert notes == ["Local store not used for parity_series.jser: parity_series.jser changed while it was being hashed"]


class _FakeMsvcrt:
    """msvcrt.locking, recorded; `fail` makes the lock refused."""
    LK_NBRLCK, LK_UNLCK = 3, 0

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def locking(self, fd, mode, n):
        if mode == self.LK_NBRLCK and self.fail:
            raise PermissionError(13, "Permission denied")
        self.calls.append((mode, os.lseek(fd, 0, os.SEEK_CUR), n))


@pytest.fixture
def windows(monkeypatch):
    """Windows' rules for the hash: no change time, and the file locked meanwhile."""
    fake = _FakeMsvcrt()
    monkeypatch.setattr(store_open, "_WINDOWS", True)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    return fake


def test_on_windows_the_whole_file_is_locked_while_it_is_hashed(tmp_path, switch_on, windows, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    monkeypatch.setattr(store_open, "_LOCK_PART", 100_000)
    opens = _store_opens(monkeypatch)
    _open(fp).close()
    assert opens == ["parity_series"]
    size = os.path.getsize(fp)
    parts = [(start, min(100_000, size - start)) for start in range(0, size, 100_000)]
    assert windows.calls == [(windows.LK_NBRLCK, s, n) for s, n in parts] + [(windows.LK_UNLCK, s, n) for s, n in parts]


def test_on_windows_a_file_that_cannot_be_locked_opens_as_today(tmp_path, switch_on, windows, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    windows.fail = True
    opens = _store_opens(monkeypatch)
    _open(fp).close()
    assert opens == []
    assert len(notes) == 1 and "could not be locked while it was hashed" in notes[0]


def test_on_windows_a_write_while_it_is_hashed_that_moves_the_time_opens_as_today(tmp_path, switch_on, windows, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    _write_during_the_hash(monkeypatch, fp, _same_size_other_content(fp), keep_time=False)
    opens = _store_opens(monkeypatch)
    _open(fp).close()
    assert opens == []
    assert notes == ["Local store not used for parity_series.jser: parity_series.jser changed while it was being hashed"]


@pytest.mark.parametrize("when", ["while-it-is-scanned", "after-it-is-scanned"])
def test_a_write_during_the_first_open_never_keeps_one_file_under_another_s_hash(when, tmp_path, switch_on, windows, monkeypatch):
    """Windows' rules, a same-size write that keeps the time, during the first open.

    The open hashes the bytes it decodes, so whatever it keeps carries their
    hash: neither the old file nor the new one opens from it later.
    """
    from PyReconstruct.modules.constants import jser_scan
    from PyReconstruct.modules.datatypes.series import SeriesOpenError

    fp = _copy(PARITY, tmp_path / "s")
    old = fp.read_bytes()
    other = _same_size_other_content(fp)
    monkeypatch.setattr(jser_scan, "_CHUNK", 4096)
    if when == "while-it-is-scanned":
        real = jser_scan._Reader._fill
        fills = []

        def fill(self):
            more = real(self)
            fills.append(more)
            if len(fills) == 1:
                _write_in_place(fp, other)
            return more

        monkeypatch.setattr(jser_scan._Reader, "_fill", fill)
    else:
        import PyReconstruct.modules.datatypes.series as series_module
        real_scan = series_module.scan_jser

        def scan(f, hasher=None):
            index = real_scan(f, hasher)
            _write_in_place(fp, other)
            return index

        monkeypatch.setattr(series_module, "scan_jser", scan)
    try:
        _open(fp).close()
    except SeriesOpenError as e:
        # the open's own check: a section's bytes differ from the scan's
        assert "changed while it was being opened" in str(e)
    monkeypatch.undo()
    monkeypatch.setenv(store_open.ENV_SWITCH, "1")
    monkeypatch.setenv(hybrid_store.ENV_DIR, str(switch_on))
    # whatever was kept, each version of the file opens as today opens it
    for data in (old, other):
        fp.write_bytes(data)
        expected = _today(fp, tmp_path, monkeypatch)
        series = _open(fp)
        try:
            assert _snapshot(series) == expected
        finally:
            series.close()


def test_the_kept_hash_is_of_the_bytes_the_open_decoded_not_of_the_file_after(tmp_path, switch_on, windows, monkeypatch):
    """The open reads the file once: a same-size write that keeps the time,
    made after that read, is not what the store holds, so A stays under A's
    hash and B never opens from it."""
    import PyReconstruct.modules.datatypes.series as series_module

    fp = _copy(PARITY, tmp_path / "s")
    old = fp.read_bytes()
    other = _same_size_other_content(fp)
    real_scan = series_module.scan_jser

    def scan(f, hasher=None):
        index = real_scan(f, hasher)
        _write_in_place(fp, other)
        return index

    monkeypatch.setattr(series_module, "scan_jser", scan)
    try:
        _open(fp).close()
    except series_module.SeriesOpenError:
        pass
    monkeypatch.setattr(series_module, "scan_jser", real_scan)
    store = HybridStore.forJser(str(fp))
    try:
        kept = store.meta(store_open.META_SHA)
        held = store.readSection(min(store.sectionNumbers())) if kept else None
    finally:
        store.close()
    if kept is not None:
        assert kept == hashlib.sha256(old).hexdigest()
        assert "dendrite01" in held["contours"] and "dendrite02" not in held["contours"]
    assert fp.read_bytes() == other
    opens = _store_opens(monkeypatch)
    _open(fp).close()
    assert opens == []


class _Asked:
    """A notifier that answers every question with `answer` and keeps what it was told."""

    def __init__(self, answer=None):
        self.answer = answer
        self.asked = []
        self.told = []

    def confirm(self, message, title="Confirm"):
        self.asked.append(message)
        return self.answer

    def notify(self, message):
        self.told.append(message)
        return True


def test_a_store_with_working_rows_is_set_aside_not_read_or_replaced(tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    store = HybridStore.forJser(str(fp))
    store.writePendingSeries({"marker": 1})
    store.close()
    expected = _today(fp, tmp_path, monkeypatch)
    opens = _store_opens(monkeypatch)
    asker = _Asked()
    series = _open(fp, notifier=asker)
    try:
        assert opens == []
        assert _snapshot(series) == expected
    finally:
        series.close()
    assert asker.asked == []
    kept = sorted(store_root_glob(fp))
    assert len(kept) == 1 and len(asker.told) == 1 and kept[0] in asker.told[0]
    aside = HybridStore(kept[0], str(tmp_path / "w"))
    try:
        assert aside.seriesData() == {"marker": 1}
    finally:
        aside.close()


def test_a_store_with_a_save_the_jser_lacks_is_offered_and_opened(tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    store = HybridStore.forJser(str(fp))
    store.setMeta("dirty", 1)
    store.close()
    expected = _today(fp, tmp_path, monkeypatch)
    opens = _store_opens(monkeypatch)
    asker = _Asked()
    series = _open(fp, notifier=asker)
    try:
        assert opens == [series.name]
        assert _snapshot(series) == expected
    finally:
        series.leave_open = True
        from PyReconstruct.modules.datatypes import store_save
        store_save.release(series)
    assert len(asker.asked) == 1 and "Open it with that work?" in asker.asked[0]
    assert asker.told == [] and store_root_glob(fp) == []


def store_root_glob(fp):
    """The set-aside stores of a .jser."""
    db, _ = storePaths(str(fp))
    return sorted(str(p) for p in Path(db).parent.glob(Path(db).name[:-len(".pyrstore")] + ".conflict-*.pyrstore"))


def test_a_merge_on_open_is_not_kept_so_the_next_open_asks_again(tmp_path, switch_on, notes, monkeypatch):
    doc = json.loads(PARITY.read_bytes())
    sec = next(s for s in doc["sections"] if s)
    # two objects whose names become one
    sec["contours"]["a b"] = copy.deepcopy(sec["contours"]["axon"])
    sec["contours"]["a_b"] = copy.deepcopy(sec["contours"]["axon"])
    fp = tmp_path / "merge.jser"
    fp.write_text(json.dumps(doc))

    class Yes:
        asked = 0

        def confirm(self, *a, **k):
            Yes.asked += 1
            return True

    _open(fp, notifier=Yes()).close()
    _open(fp, notifier=Yes()).close()
    assert Yes.asked == 2
    assert notes == ["Local store not kept for merge.jser: its objects were merged on open"] * 2


# ---------------------------------------------------------------------------
# the quiet fallback
# ---------------------------------------------------------------------------

def _assert_falls_back(fp, tmp_path, monkeypatch, notes, why):
    expected = _today(fp, tmp_path, monkeypatch)
    series = _open(fp, notifier=_NoDialog())
    try:
        assert _snapshot(series) == expected
    finally:
        series.close()
    assert len(notes) == 1, notes
    assert notes[0].startswith(f"Local store not used for {fp.name}: ")
    assert why in notes[0]


def test_a_store_folder_on_a_network_file_system_opens_as_today(tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    seen = []

    def remote(path):
        seen.append(path)
        return "smbfs"

    monkeypatch.setattr(store_open, "networkFileSystem", remote)
    _assert_falls_back(fp, tmp_path, monkeypatch, notes, "network file system (smbfs)")
    assert seen == [os.path.dirname(storePaths(str(fp))[0])]
    assert not any(p.suffix == ".pyrstore" for p in switch_on.rglob("*"))


def test_a_store_another_process_holds_opens_as_today(tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    holder = HybridStore.forJser(str(fp))
    try:
        _assert_falls_back(fp, tmp_path, monkeypatch, notes, "open in another PyReconstruct window")
    finally:
        holder.close()


def test_a_file_that_is_not_a_store_opens_as_today_and_is_left_as_it_was(tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    db_fp, _ = storePaths(str(fp))
    os.makedirs(os.path.dirname(db_fp))
    con = sqlite3.connect(db_fp)
    con.execute("CREATE TABLE other(x)")
    con.commit()
    con.close()
    before = Path(db_fp).read_bytes()
    _assert_falls_back(fp, tmp_path, monkeypatch, notes, "another program's database")
    assert Path(db_fp).read_bytes() == before


@pytest.mark.parametrize("error", [
    sqlite3.OperationalError("disk I/O error"),
    sqlite3.DatabaseError("database disk image is malformed"),
], ids=["operational", "damaged"])
def test_a_store_read_that_fails_partway_opens_as_today(error, tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(SERIES_FILES[1], tmp_path / "s")
    _open(fp).close()
    # every section read at open, as for one the store holds otherwise than its file
    monkeypatch.setattr(lazy_sections, "stubs", lambda held: {})
    real = HybridStore.readSectionEncoded
    calls = []

    def fails_second(self, snum, *a, **k):
        calls.append(snum)
        if len(calls) == 2:
            raise error
        return real(self, snum, *a, **k)

    monkeypatch.setattr(HybridStore, "readSectionEncoded", fails_second)
    _assert_falls_back(fp, tmp_path, monkeypatch, notes, str(error))
    assert len(calls) == 2
    # nothing of the failed open is left beside the file
    assert sorted(os.listdir(fp.parent)) == [fp.name]


def test_a_fault_in_the_store_code_is_raised_not_hidden(tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()

    def fault(store, series):
        raise ValueError("a bug")

    monkeypatch.setattr(store_open, "_fillSeriesData", fault)
    with pytest.raises(ValueError, match="a bug"):
        _open(fp)
    assert notes == []
    assert sorted(os.listdir(fp.parent)) == [fp.name]
    # and the store was let go of
    HybridStore.forJser(str(fp)).close()


@pytest.mark.parametrize("error", [sqlite3.ProgrammingError, sqlite3.IntegrityError, sqlite3.InterfaceError])
def test_an_sqlite_error_only_code_can_cause_is_raised_not_hidden(error, tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    # every section read at open, as for one the store holds otherwise than its file
    monkeypatch.setattr(lazy_sections, "stubs", lambda held: {})

    def bug(self, snum, *a, **k):
        raise error("Incorrect number of bindings supplied")

    monkeypatch.setattr(HybridStore, "readSectionEncoded", bug)
    with pytest.raises(error):
        _open(fp)
    assert notes == []
    assert sorted(os.listdir(fp.parent)) == [fp.name]


def test_a_store_that_cannot_be_written_leaves_the_open_as_today(tmp_path, switch_on, notes, monkeypatch):
    fp = _copy(PARITY, tmp_path / "s")
    expected = _today(fp, tmp_path, monkeypatch)

    def full(*a, **k):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(HybridStore, "importJser", full)
    series = _open(fp, notifier=_NoDialog())
    try:
        assert _snapshot(series) == expected
    finally:
        series.close()
    assert notes == ["Local store not used for parity_series.jser: database or disk is full"]


# ---------------------------------------------------------------------------
# network folders
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, flags, expected", [
    ("smbfs", 0, "smbfs"),
    ("afpfs", 0, "afpfs"),
    ("nfs", 0, "nfs"),
    ("webdav", 0, "webdav"),
    ("smbfs", network_folder.MNT_LOCAL, "smbfs"),
    ("macfuse", 0, "macfuse, not local"),
    ("apfs", network_folder.MNT_LOCAL, None),
    ("hfs", network_folder.MNT_LOCAL, None),
])
def test_macos_network_mounts_are_told_by_their_file_system(name, flags, expected):
    assert network_folder.macosRemote("/x", statfs=lambda p: (name, flags)) == expected


def test_macos_answers_local_when_statfs_cannot_be_read():
    assert network_folder.macosRemote("/x", statfs=lambda p: None) is None


@pytest.mark.parametrize("magic, mount, expected", [
    (0x6969, None, "nfs"),
    (0xFF534D42, None, "cifs"),
    (0x517B, None, "smb"),
    (0xFE534D42, None, "smb2"),
    (0x01021997, None, "9p"),
    (0x65735546, "fuse.sshfs", "fuse.sshfs"),
    (0x65735546, "fuse.portal", None),
    (0xEF53, None, None),        # ext4
    (0x58465342, None, None),    # xfs
])
def test_linux_network_mounts_are_told_by_their_magic(magic, mount, expected):
    assert network_folder.linuxRemote(
        "/x", statfs=lambda p: magic, mount_type=lambda p: mount
    ) == expected


@pytest.mark.parametrize("path, expected", [
    (r"\\server\share\series", "UNC path"),
    (r"\\?\UNC\server\share\series", "UNC path"),
    (r"Z:\lab\series", "network drive"),
    (r"\\?\Z:\lab\series", "network drive"),
    (r"C:\Users\me\AppData\Local\PyReconstruct\stores", None),
    (r"\\?\C:\data", None),
])
def test_windows_unc_paths_and_mapped_drives_are_network(path, expected):
    def drive_type(root):
        return network_folder.DRIVE_REMOTE if root.upper() == "Z:\\" else 3  # DRIVE_FIXED
    assert network_folder.windowsRemote(path, drive_type=drive_type) == expected


def test_a_folder_not_made_yet_is_judged_by_the_one_above_it(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(network_folder, "macosRemote", lambda p: seen.append(p))
    network_folder.networkFileSystem(str(tmp_path / "not" / "yet"), platform="darwin")
    assert seen == [str(tmp_path)]


def test_this_machine_s_temp_folder_is_local(tmp_path):
    assert network_folder.networkFileSystem(str(tmp_path)) is None


@pytest.mark.skipif(sys.platform != "darwin", reason="reads macOS's statfs")
def test_macos_statfs_is_read_for_real():
    name, flags = network_folder._macStatfs("/")
    assert name in {"apfs", "hfs"} and flags & network_folder.MNT_LOCAL
    name, flags = network_folder._macStatfs("/dev")
    assert name == "devfs"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads Linux's statfs")
def test_linux_statfs_is_read_for_real():
    assert network_folder._linuxStatfs("/proc") == 0x9FA0  # proc


@pytest.mark.skipif(sys.platform != "win32", reason="reads Windows' drive type")
def test_windows_drive_type_is_read_for_real():
    root = os.environ.get("SystemDrive", "C:") + "\\"
    assert network_folder._windowsDriveType(root) == 3  # DRIVE_FIXED


def test_the_store_module_still_refuses_a_linux_network_folder_itself(tmp_path, monkeypatch):
    # the step 1 check stays: a store folder that statfs misses is caught by mountinfo
    monkeypatch.setattr(hybrid_store, "fsType", lambda path: "nfs4")
    with pytest.raises(OSError, match="network file system"):
        HybridStore(str(tmp_path / "s.pyrstore"), str(tmp_path / "s.work"))
