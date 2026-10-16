"""The hybrid store prototype (hybrid_store.py), opt-in by PYRECON_HYBRID_STORE=1.

What these pin:

* with the switch off nothing of the store runs, and no store is created;
* .jser -> store -> .jser writes the same bytes the app writes today from the
  same file, for every series in the repo;
* an open from the store builds the object list without loading a section,
  and that list equals a full refresh;
* Save, discard, crash recovery, a changed .jser, section deletion and a
  stale alignment each do what the design note says.
"""
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import hybrid_store
from PyReconstruct.modules.datatypes.hybrid_store import HybridStore, packRow, unpackRow
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.series import Series

REPO_ROOT = Path(__file__).resolve().parent.parent
SERIES_FILES = [
    REPO_ROOT / "tests" / "fixtures" / "parity_series.jser",
    REPO_ROOT / "dev" / "assets" / "checker" / "files" / "class_series.jser",
    REPO_ROOT / "dev" / "assets" / "checker" / "files" / "shapes1.jser",
    REPO_ROOT / "dev" / "assets" / "checker" / "files" / "shapes2.jser",
]


class Answer:
    """A notifier that answers every confirm the same way."""

    def __init__(self, answer):
        self.answer = answer
        self.asked = []
        self.told = []

    def confirm(self, message):
        self.asked.append(message)
        return self.answer

    def notify(self, message):
        self.told.append(message)
        return False


@pytest.fixture
def store_on(tmp_path, monkeypatch):
    root = tmp_path / "stores"
    monkeypatch.setenv(hybrid_store.ENV_SWITCH, "1")
    monkeypatch.setenv(hybrid_store.ENV_DIR, str(root))
    return root


def _copy(src, tmp_path, sub="data"):
    folder = tmp_path / sub
    folder.mkdir(exist_ok=True)
    dest = folder / Path(src).name
    shutil.copyfile(src, dest)
    return dest


def _open(fp, notifier=None):
    series = Series.openJser(str(fp), progress=NullProgressReporter, notifier=notifier)
    series.setProgressReporter(NullProgressReporter)
    return series


def _today_bytes(src, tmp_path, monkeypatch):
    """What the app writes today when it opens src and saves it."""
    monkeypatch.delenv(hybrid_store.ENV_SWITCH, raising=False)
    fp = _copy(src, tmp_path, "today")
    series = _open(fp)
    try:
        series.saveJser()
    finally:
        series.close()
    monkeypatch.setenv(hybrid_store.ENV_SWITCH, "1")
    return fp.read_bytes()


def _object_list(series) -> dict:
    """Every number the object list holds, comparable across two builds."""
    out = {}
    for name, obj in series.data.objects.items():
        for snum, tds in obj.traces.items():
            out[(name, snum)] = [
                (td.index, td.closed, td.hidden, td.negative, frozenset(td.tags), td.color,
                 td.length, td.area, td.centroid, td.radius, repr(td._tform.getList()))
                for td in tds
            ]
    sections = {
        snum: (d["thickness"], d["calgrid"], d["locked"], d["src"], d["mag"],
               repr(d["bc_profiles"]),
               [f.getList() for f in d["flags"]],
               {k: t.getList() for k, t in d["tforms"].items()})
        for snum, d in series.data["sections"].items()
    }
    return {"objects": out, "sections": sections}


# ---------------------------------------------------------------------------
# switch off
# ---------------------------------------------------------------------------

def test_switch_off_creates_no_store_and_uses_the_hidden_dir(tmp_path, monkeypatch):
    root = tmp_path / "stores"
    monkeypatch.delenv(hybrid_store.ENV_SWITCH, raising=False)
    monkeypatch.setenv(hybrid_store.ENV_DIR, str(root))
    fp = _copy(SERIES_FILES[0], tmp_path)
    series = _open(fp)
    try:
        assert series.store is None
        assert os.path.isdir(fp.parent / f".{fp.stem}")
        series.saveJser()
    finally:
        series.close()
    assert not root.exists()


@pytest.mark.parametrize("value", ["0", "", "true", "yes"])
def test_only_the_value_1_turns_it_on(value, monkeypatch):
    monkeypatch.setenv(hybrid_store.ENV_SWITCH, value)
    assert not hybrid_store.enabled()


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src", SERIES_FILES, ids=lambda p: p.name)
def test_jser_store_jser_writes_what_the_app_writes_today(src, tmp_path, monkeypatch, store_on):
    expected = _today_bytes(src, tmp_path, monkeypatch)
    fp = _copy(src, tmp_path)
    series = _open(fp)
    try:
        assert series.store is not None
        assert not os.path.exists(fp.parent / f".{fp.stem}")  # nothing beside the .jser
        out = tmp_path / "export.jser"
        series.saveJser(str(out))
    finally:
        series.close()
    assert out.read_bytes() == expected


@pytest.mark.parametrize("src", SERIES_FILES, ids=lambda p: p.name)
def test_export_after_reopening_from_the_store_is_unchanged(src, tmp_path, monkeypatch, store_on):
    expected = _today_bytes(src, tmp_path, monkeypatch)
    fp = _copy(src, tmp_path)
    _open(fp).close()
    series = _open(fp)
    try:
        out = tmp_path / "export.jser"
        series.saveJser(str(out))
    finally:
        series.close()
    assert out.read_bytes() == expected


@pytest.mark.parametrize("row", [
    [[0.1, 2.5, -0.0], [1e-7, 3.0, 1234567.8912345], [255, 0, 0], True, False, False, ["none", "none"], ["a"]],
    [[1, 2.0, 3.0], [4.0, 5.0, 6.0], [0, 0, 0], True, False, False, ["none", "none"], []],
    [[], [], [0, 0, 0], False, False, False, ["none", "none"], []],
    {"x": [1.0, 2.0], "y": [3.0, 4.0], "color": [1, 2, 3]},
])
def test_a_trace_row_comes_back_exactly(row):
    shape, npts, xy, rest, *_ = packRow(row)
    back = unpackRow(shape, npts, xy, rest)
    assert back == row
    if isinstance(row, list) and row[0]:
        assert [type(v) for v in back[0]] == [type(v) for v in row[0]]


# ---------------------------------------------------------------------------
# open from the store
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src", SERIES_FILES, ids=lambda p: p.name)
def test_open_from_the_store_loads_no_section_and_matches_a_full_refresh(src, tmp_path, store_on, monkeypatch):
    fp = _copy(src, tmp_path)
    _open(fp).close()

    loads = []
    real_init = Section.__init__

    def counting_init(self, n, series):
        loads.append(n)
        real_init(self, n, series)
    monkeypatch.setattr(Section, "__init__", counting_init)

    series = _open(fp)
    try:
        assert loads == []
        assert series.store.recomputed == []
        from_store = _object_list(series)
        series.data.refresh(show_progress=False)
        assert _object_list(series) == from_store
    finally:
        series.close()


def test_a_section_read_from_the_store_equals_the_one_read_from_its_file(tmp_path, monkeypatch, store_on):
    src = SERIES_FILES[1]
    monkeypatch.delenv(hybrid_store.ENV_SWITCH)
    plain = _open(_copy(src, tmp_path, "plain"))
    monkeypatch.setenv(hybrid_store.ENV_SWITCH, "1")
    stored = _open(_copy(src, tmp_path))
    try:
        assert sorted(plain.sections) == sorted(stored.sections)
        for snum in plain.sections:
            assert plain.loadSection(snum).getDict() == stored.loadSection(snum).getDict()
    finally:
        plain.close()
        stored.close()


def test_the_object_index_finds_every_trace_of_an_object(tmp_path, store_on):
    series = _open(_copy(SERIES_FILES[1], tmp_path))
    try:
        name = max(series.data.objects, key=lambda n: series.data.getCount(n))
        found = series.store.objectTraces(name)
        assert len(found) == series.data.getCount(name)
        assert {snum for snum, _ in found} == set(series.data.objects[name].traces)
    finally:
        series.close()


# ---------------------------------------------------------------------------
# save, discard, recovery
# ---------------------------------------------------------------------------

def _edit_one_trace(series):
    """Move one trace on the first section with traces; return (snum, name)."""
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        traces = section.tracesAsList()
        if traces:
            trace = traces[0]
            section.selected_traces = [trace]
            section.translateTraces(5.0, -3.0)
            series.data.updateSection(section, update_traces=True)
            section.save(update_series_data=False)
            series.save()
            return snum, trace.name, section.getDict()
    raise AssertionError("no traces")


def test_save_keeps_the_edit_and_the_next_open_shows_it(tmp_path, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    series = _open(fp)
    snum, name, edited = _edit_one_trace(series)
    series.store.commit(series)
    assert not series.store.hasPending()
    series.close()

    series = _open(fp)
    try:
        assert series.store.recomputed == []
        assert series.loadSection(snum).getDict() == edited
        from_store = _object_list(series)
        series.data.refresh(show_progress=False)
        assert _object_list(series) == from_store
    finally:
        series.close()


def test_export_carries_the_edit_to_a_jser_any_build_opens(tmp_path, monkeypatch, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    series = _open(fp)
    snum, name, edited = _edit_one_trace(series)
    series.saveJser()
    assert not series.store.hasUnexportedWork()
    assert series.store.matchesJser(str(fp))
    series.close()

    monkeypatch.delenv(hybrid_store.ENV_SWITCH)
    plain = _open(fp)
    try:
        assert plain.store is None
        assert plain.loadSection(snum).getDict() == edited
    finally:
        plain.close()


def test_discard_returns_the_store_to_the_last_save(tmp_path, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    series = _open(fp)
    before = {n: series.loadSection(n).getDict() for n in series.sections}
    snum, name, edited = _edit_one_trace(series)
    assert edited != before[snum]
    series.store.clearPending()
    series.close()

    series = _open(fp)
    try:
        assert series.loadSection(snum).getDict() == before[snum]
        assert not series.modified
    finally:
        series.close()


@pytest.mark.parametrize("answer", [True, False])
def test_unsaved_work_after_a_crash_is_offered_back(answer, tmp_path, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    series = _open(fp)
    before = {n: series.loadSection(n).getDict() for n in series.sections}
    snum, name, edited = _edit_one_trace(series)
    _die(series)

    asked = Answer(answer)
    series = _open(fp, notifier=asked)
    try:
        assert len(asked.asked) == 1
        got = series.loadSection(snum).getDict()
        assert got == (edited if answer else before[snum])
        assert got != before[snum] or not answer
        assert series.modified is answer
    finally:
        series.close()


def _die(series):
    """The process dies: no close, no Save; the OS drops its lock."""
    series.store.con.close()
    series.store.con = None
    os.close(series.store._lock_fd)
    series.store._lock_fd = None


def test_a_changed_jser_is_imported_again(tmp_path, monkeypatch, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    _open(fp).close()
    # someone saves the .jser with another build
    monkeypatch.delenv(hybrid_store.ENV_SWITCH)
    plain = _open(fp)
    snum, name, edited = _edit_one_trace(plain)
    plain.saveJser()
    plain.close()
    monkeypatch.setenv(hybrid_store.ENV_SWITCH, "1")

    series = _open(fp)
    try:
        assert series.loadSection(snum).getDict() == edited
    finally:
        series.close()


def test_a_changed_jser_under_unexported_work_keeps_the_store_aside(tmp_path, monkeypatch, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    series = _open(fp)
    _edit_one_trace(series)
    series.store.commit(series)
    series.close()
    os.utime(fp, ns=(1, 1))  # the .jser changes under it

    told = Answer(True)
    series = _open(fp, notifier=told)
    series.close()
    kept = [p for p in store_on.iterdir() if ".conflict-" in p.name and p.suffix == ".pyrstore"]
    assert len(kept) == 1
    assert len(told.told) == 1 and str(kept[0]) in told.told[0]
    con = sqlite3.connect(kept[0])
    assert con.execute("SELECT value FROM meta WHERE key='dirty'").fetchone() == ("1",)
    con.close()


def test_a_deleted_section_stays_deleted(tmp_path, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    series = _open(fp)
    snum = max(series.sections)
    series.deleteSections([snum], log_event=False)
    series.save()
    series.store.commit(series)
    series.close()

    series = _open(fp)
    try:
        assert snum not in series.sections
    finally:
        series.close()


def test_numbers_from_another_alignment_are_measured_again(tmp_path, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    _open(fp).close()
    db_fp, _ = hybrid_store.storePaths(str(fp))
    con = sqlite3.connect(db_fp)
    snum = con.execute("SELECT MIN(snum) FROM trace_stats").fetchone()[0]
    con.execute("UPDATE trace_stats SET tform_key='elsewhere' WHERE snum=?", (snum,))
    con.commit()
    con.close()

    series = _open(fp)
    try:
        assert series.store.recomputed == [snum]
        from_store = _object_list(series)
        series.data.refresh(show_progress=False)
        assert _object_list(series) == from_store
    finally:
        series.close()


# ---------------------------------------------------------------------------
# where the store lives
# ---------------------------------------------------------------------------

def test_the_store_refuses_a_network_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(hybrid_store, "fsType", lambda path: "nfs4")
    with pytest.raises(OSError, match="network file system"):
        HybridStore(str(tmp_path / "s.pyrstore"), str(tmp_path / "s.work"))


def test_the_store_is_keyed_by_the_real_path_and_lives_in_the_store_folder(tmp_path, store_on):
    fp = _copy(SERIES_FILES[0], tmp_path)
    link = tmp_path / "link.jser"
    os.symlink(fp, link)
    assert hybrid_store.storePaths(str(fp)) == hybrid_store.storePaths(str(link))
    db_fp, work = hybrid_store.storePaths(str(fp))
    assert Path(db_fp).parent == store_on


# ---------------------------------------------------------------------------
# unexported work, two windows, a busy store
# ---------------------------------------------------------------------------

def test_open_says_when_the_jser_lacks_the_last_save(tmp_path, store_on):
    fp = _copy(SERIES_FILES[1], tmp_path)
    series = _open(fp)
    _edit_one_trace(series)
    series.store.commit(series)  # Save to the store only, no export
    series.close()

    told = Answer(True)
    _open(fp, notifier=told).close()
    assert len(told.told) == 1 and "local store" in told.told[0]

    series = _open(fp)
    series.saveJser()  # the export
    series.close()
    told = Answer(True)
    _open(fp, notifier=told).close()
    assert told.told == []


def test_a_second_window_is_told_the_series_is_open_elsewhere(tmp_path, store_on):
    from PyReconstruct.modules.datatypes.series import SeriesOpenError

    fp = _copy(SERIES_FILES[0], tmp_path)
    first = _open(fp)
    try:
        with pytest.raises(SeriesOpenError, match="open in another PyReconstruct window"):
            _open(fp)
    finally:
        first.close()
    _open(fp).close()  # free again once the first closes


def test_a_busy_store_is_reported_as_busy_never_as_damage(tmp_path, store_on):
    fp = _copy(SERIES_FILES[0], tmp_path)
    series = _open(fp)
    try:
        series.store.con.execute("PRAGMA busy_timeout=50")
        other = sqlite3.connect(series.store.db_fp, isolation_level=None)
        other.execute("BEGIN EXCLUSIVE")
        try:
            with pytest.raises(hybrid_store.StoreBusyError, match="another"):
                series.store.writePendingSeries({"x": 1})
        finally:
            other.execute("ROLLBACK")
            other.close()
    finally:
        series.close()
