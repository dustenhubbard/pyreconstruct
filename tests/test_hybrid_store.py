"""The local SQLite working store (hybrid_store.py), on its own.

Nothing in PyReconstruct calls the store yet, so these drive it directly. The
oracle is today's open: a store must hold, byte for byte, what
`Series.openJser` writes into the hidden folder for the same file.

What these pin:

* the import holds what today's open writes, for every series in the repo,
  every past file shape the reader takes, and the fields the July evaluation
  left untested; it reads one section at a time and is one transaction;
* a trace row comes back exactly, coordinates and types both;
* the working layer is read before the saved tables, Save folds it in, and a
  rewrite of the same content does not mark the store ahead;
* one process at a time holds a store, a killed process lets go of it, and a
  busy database is reported as busy, never as damage;
* where a store lives, how it is named, and that a network folder is refused.
"""
import copy
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants import fast_dumps
from PyReconstruct.modules.constants.jser_format import KEYED_TRACE_ROW_KEYS
from PyReconstruct.modules.datatypes import hybrid_store
from PyReconstruct.modules.datatypes.flag import Flag
from PyReconstruct.modules.datatypes.hybrid_store import HybridStore, packRow, unpackRow
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.transform import Transform

REPO_ROOT = Path(__file__).resolve().parent.parent
PARITY = REPO_ROOT / "tests" / "fixtures" / "parity_series.jser"
CLASS = REPO_ROOT / "dev" / "assets" / "checker" / "files" / "class_series.jser"
SERIES_FILES = [
    PARITY,
    CLASS,
    REPO_ROOT / "dev" / "assets" / "checker" / "files" / "shapes1.jser",
    REPO_ROOT / "dev" / "assets" / "checker" / "files" / "shapes2.jser",
]


@pytest.fixture
def store_root(tmp_path, monkeypatch):
    root = tmp_path / "stores"
    monkeypatch.setenv(hybrid_store.ENV_DIR, str(root))
    return root


def _copy(src, tmp_path, sub):
    folder = tmp_path / sub
    folder.mkdir(exist_ok=True)
    dest = folder / Path(src).name
    shutil.copyfile(src, dest)
    return dest


def _open(fp):
    series = Series.openJser(str(fp), progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    return series


def _today(src, tmp_path):
    """What today's open writes into the hidden folder for src.

    Returns ({section number: file bytes}, .ser bytes, log text).
    """
    series = _open(_copy(src, tmp_path, "today"))
    try:
        wdir = series.getwdir()
        sections = {
            snum: Path(wdir, fname).read_bytes() for snum, fname in series.sections.items()
        }
        ser = Path(series.filepath).read_bytes()
        log = Path(wdir, "existing_log.csv").read_text(encoding="utf-8")
    finally:
        series.close()
    return sections, ser, log


def _import(fp, store=None):
    """Import the .jser at fp into its store, through today's reader."""
    if store is None:
        store = HybridStore.forJser(str(fp))
    source, collisions = Series._readJserForOpen(str(fp), None)
    try:
        store.importJser(str(fp), source, collisions)
    finally:
        source.close()
    return store


def _held(store):
    """(section bytes by number, .ser bytes, log text), as the store gives them back."""
    sections = {snum: bytes(fast_dumps(store.readSection(snum))) for snum in store.sectionNumbers()}
    return sections, bytes(fast_dumps(store.seriesData())), store.logText()


def _assert_holds_what_today_writes(src, tmp_path):
    expected = _today(src, tmp_path)
    fp = _copy(src, tmp_path, "store")
    before = fp.read_bytes()
    store = _import(fp)
    try:
        assert _held(store) == expected
        assert store.isImported()
        assert store.matchesJser(str(fp))
    finally:
        store.close()
    # nothing is written beside the .jser, and the .jser is untouched
    assert sorted(os.listdir(fp.parent)) == [fp.name]
    assert fp.read_bytes() == before
    return store


# ---------------------------------------------------------------------------
# the import holds what today's open writes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src", SERIES_FILES, ids=lambda p: p.name)
def test_the_import_holds_what_today_s_open_writes(src, tmp_path, store_root):
    _assert_holds_what_today_writes(src, tmp_path)


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
    # what the series knows about the renamed object follows the new name
    doc["series"]["obj_attrs"] = {"zzz first": {"comment": "renamed on open"}}
    doc["series"]["object_groups"] = {"group one": ["zzz first"]}
    flat = {"legacy.ser": doc["series"]}                 # the flat top level, no log
    for i, s in enumerate(doc["sections"]):
        if s:
            flat[f"legacy.{i}"] = s
    fp = Path(folder) / "legacy.jser"
    fp.write_text(json.dumps(flat))
    return fp


def full_field_series(folder) -> Path:
    """class_series with every field the July evaluation listed as untested."""
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
                flag.addComment("tester", "a note, with a comma")
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


def test_every_past_shape_imports_as_it_opens_today(tmp_path, store_root):
    folder = tmp_path / "src"
    folder.mkdir()
    src = legacy_series(folder)
    _assert_holds_what_today_writes(src, tmp_path)
    store = HybridStore.forJser(str(tmp_path / "store" / src.name))
    try:
        series_data = store.seriesData()
        assert series_data["obj_attrs"]["zzz_first"]["comment"] == "renamed on open"
        assert "zzz first" not in series_data["obj_attrs"]
    finally:
        store.close()


def test_the_fields_july_left_untested_import_as_they_open_today(tmp_path, store_root):
    folder = tmp_path / "src"
    folder.mkdir()
    src = full_field_series(folder)
    _assert_holds_what_today_writes(src, tmp_path)
    store = HybridStore.forJser(str(tmp_path / "store" / src.name))
    try:
        assert "Status" in store.seriesData()["user_columns"]
        assert "a logged event" in store.logText()
    finally:
        store.close()


def _keyed(row, trace_id, fill_mode_key):
    keyed = dict(zip(("x", "y", "color", "closed", "negative", "hidden"), row[:6]))
    keyed[fill_mode_key] = row[6]
    keyed["tags"] = row[7]
    keyed["id"] = trace_id
    return keyed


def test_a_trace_s_saved_id_survives_the_import_in_both_fill_mode_spellings(tmp_path, store_root):
    # ids no derivation would give, 11 base62 characters as the reader wants
    planted = {("dendrite01", 0): ("zzSTORE0001", "fill_mode"),
               ("dendrite01", 1): ("zzSTORE0002", "mode")}
    doc = json.loads(PARITY.read_bytes())
    snum = next(i for i, s in enumerate(doc["sections"]) if s and "dendrite01" in s["contours"])
    rows = doc["sections"][snum]["contours"]["dendrite01"]
    for (name, i), (trace_id, key) in planted.items():
        rows[i] = _keyed(rows[i], trace_id, key)
    folder = tmp_path / "src"
    folder.mkdir()
    src = folder / "ids.jser"
    src.write_text(json.dumps(doc))

    _assert_holds_what_today_writes(src, tmp_path)
    store = HybridStore.forJser(str(tmp_path / "store" / src.name))
    try:
        stored = store.readSection(snum)["contours"]["dendrite01"]
    finally:
        store.close()
    for (name, i), (trace_id, key) in planted.items():
        assert isinstance(stored[i], dict), f"row {i} lost its id: {stored[i]!r}"
        assert stored[i]["id"] == trace_id
        assert key in stored[i]  # the spelling the file used


def test_the_import_reads_the_jser_one_section_at_a_time(tmp_path, store_root, monkeypatch):
    import gc
    import weakref
    from PyReconstruct.modules.datatypes import series as series_module

    # as today's Save writes it: the streamed read takes that layout
    resaved = _copy(CLASS, tmp_path, "resaved")
    series = _open(resaved)
    try:
        series.saveJser()
    finally:
        series.close()

    def whole(fp):
        raise AssertionError("the import read the whole file")
    monkeypatch.setattr(Series, "_readWholeJser", staticmethod(whole))

    class Held(dict):
        pass

    real = series_module._StreamedJser.sections
    last = []

    def one_at_a_time(self):
        for snum, section_data, found in real(self):
            if last:
                gc.collect()
                assert last[-1]() is None, f"section {snum} decoded while the last is held"
            held = Held(section_data)
            del section_data
            last.append(weakref.ref(held))
            yield snum, held, found
            del held
    monkeypatch.setattr(series_module._StreamedJser, "sections", one_at_a_time)

    store = _import(_copy(resaved, tmp_path, "store"))
    try:
        assert len(last) == len(store.sectionNumbers()) > 1
        assert store.isImported()
    finally:
        store.close()


class _FailsPartway:
    """A reader source whose second section cannot be read."""

    def __init__(self, source):
        self.source = source

    def __getattr__(self, name):
        return getattr(self.source, name)

    def sections(self):
        for i, item in enumerate(self.source.sections()):
            if i == 1:
                raise RuntimeError("the file changed on disk")
            yield item


@pytest.mark.parametrize("first", [True, False], ids=["first-import", "re-import"])
def test_an_import_that_fails_partway_leaves_the_store_as_it_was(first, tmp_path, store_root):
    fp = _copy(CLASS, tmp_path, "store")
    store = HybridStore.forJser(str(fp))
    try:
        if not first:
            _import(fp, store)
        before = _held(store) if not first else None
        source, collisions = Series._readJserForOpen(str(fp), None)
        try:
            with pytest.raises(RuntimeError, match="changed on disk"):
                store.importJser(str(fp), _FailsPartway(source), collisions)
        finally:
            source.close()
        if first:
            assert not store.isImported()
            assert store.sectionNumbers() == []
            assert store.con.execute("SELECT COUNT(*) FROM trace").fetchone() == (0,)
        else:
            assert store.isImported()
            assert _held(store) == before
    finally:
        store.close()


def test_a_second_import_replaces_everything_and_drops_unsaved_work(tmp_path, store_root):
    fp = _copy(CLASS, tmp_path, "store")
    store = _import(fp)
    try:
        first = _held(store)
        snum = store.sectionNumbers()[0]
        store.writePendingSection(snum, {"edited": True, "contours": {}})
        store.writePendingSeries({"edited": True})
        store.deletePendingSection(store.sectionNumbers()[-1])
        _import(fp, store)
        assert not store.hasPending()
        assert _held(store) == first
    finally:
        store.close()


# ---------------------------------------------------------------------------
# trace rows
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("row", [
    [[0.1, 2.5, -0.0], [1e-7, 3.0, 1234567.8912345], [255, 0, 0], True, False, False, ["none", "none"], ["a"]],
    [[1, 2.0, 3.0], [4.0, 5.0, 6.0], [0, 0, 0], True, False, False, ["none", "none"], []],
    [[], [], [0, 0, 0], False, False, False, ["none", "none"], []],
    {"x": [1.0, 2.0], "y": [3.0, 4.0], "color": [1, 2, 3]},
], ids=["floats", "an-int-coordinate", "empty", "keyed"])
def test_a_trace_row_comes_back_exactly(row):
    shape, npts, xy, rest, *_ = packRow(row)
    back = unpackRow(shape, npts, xy, rest)
    assert back == row
    assert json.dumps(back) == json.dumps(row)  # -0.0 and int stay as they were
    if isinstance(row, list) and row[0]:
        assert [type(v) for v in back[0]] == [type(v) for v in row[0]]


def test_the_object_index_finds_every_trace_of_an_object(tmp_path, store_root):
    sections, _, _ = _today(CLASS, tmp_path)
    expected : dict = {}
    for snum, raw in sections.items():
        for name, rows in json.loads(raw)["contours"].items():
            for row in rows:
                expected.setdefault(name, []).append((snum, row))
    store = _import(_copy(CLASS, tmp_path, "store"))
    try:
        name = max(expected, key=lambda n: len(expected[n]))
        assert len({snum for snum, _ in expected[name]}) > 1
        found = store.objectTraces(name)
        assert json.dumps(found) == json.dumps(sorted(expected[name], key=lambda t: t[0]))
    finally:
        store.close()


# ---------------------------------------------------------------------------
# the working layer and Save
# ---------------------------------------------------------------------------

@pytest.fixture
def opened(tmp_path, store_root):
    """(store, series) for one copy of class_series: the store imported from
    it, and the series opened from it as today, its hidden folder the working
    folder Save reads."""
    fp = _copy(CLASS, tmp_path, "data")
    store = _import(fp)
    series = _open(fp)
    yield store, series
    series.close()
    store.close()


def _edited(store, snum):
    """The saved section snum with its first trace moved."""
    section_data = store.readSection(snum)
    rows = next(rows for rows in section_data["contours"].values() if rows)
    rows[0][0] = [x + 5.0 for x in rows[0][0]]
    return section_data


def _first_with_traces(store):
    return next(
        snum for snum in store.sectionNumbers()
        if any(store.readSection(snum)["contours"].values())
    )


def test_a_working_copy_is_read_first_and_save_keeps_it(opened):
    store, series = opened
    snum = _first_with_traces(store)
    edited = _edited(store, snum)
    store.writePendingSection(snum, edited)
    assert store.hasPending()
    assert store.readSection(snum) == edited
    assert store.meta("dirty") == "0"

    assert store.commit(series) is True
    assert not store.hasPending()
    assert store.readSection(snum) == edited
    assert store.meta("dirty") == "1"

    # durable: a fresh connection reads the saved rows
    store.close()
    again = HybridStore(store.db_fp, store.work_dir)
    try:
        assert again.readSection(snum) == edited
        assert not again.hasPending()
    finally:
        again.close()


def test_discard_returns_the_store_to_the_last_save(opened):
    store, series = opened
    snum = _first_with_traces(store)
    before = store.readSection(snum)
    store.writePendingSection(snum, _edited(store, snum))
    store.writePendingSeries({"edited": True})
    store.clearPending()
    assert not store.hasPending()
    assert store.readSection(snum) == before
    assert "edited" not in store.seriesData()


def test_a_rewrite_of_the_same_content_does_not_mark_the_store_ahead(opened):
    store, series = opened
    for snum in store.sectionNumbers():
        store.writePendingSection(snum, store.readSection(snum))
    store.writePendingSeries(store.seriesData())
    assert store.hasPending()
    assert store.commit(series) is False
    assert not store.hasPending()
    assert store.meta("dirty") == "0"


def test_save_folds_in_the_series_and_the_log(opened):
    store, series = opened
    data = store.seriesData()
    data["current_section"] = max(store.sectionNumbers())
    store.writePendingSeries(data)
    log_fp = Path(series.getwdir(), "existing_log.csv")
    with open(log_fp, "a", encoding="utf-8") as f:
        f.write("a,new,line\n")
    assert store.commit(series) is True
    assert store.seriesData() == data
    assert store.logText() == log_fp.read_text(encoding="utf-8")


@pytest.mark.parametrize("how", ["working-row", "gone-from-the-series"])
def test_a_deleted_section_stays_deleted(how, opened):
    store, series = opened
    snum = max(store.sectionNumbers())
    if how == "working-row":
        store.deletePendingSection(snum)
        assert snum not in store.sectionNumbers()
        del series.sections[snum]
    else:
        series.deleteSections([snum], log_event=False)
    assert store.commit(series) is True
    assert not store.hasSection(snum)
    assert store.con.execute("SELECT COUNT(*) FROM trace WHERE snum=?", (snum,)).fetchone() == (0,)
    with pytest.raises(FileNotFoundError):
        store.readSection(snum)


@pytest.mark.parametrize("how", ["no-data-anywhere", "deleted-but-still-listed"])
def test_save_refuses_a_listed_section_it_has_no_data_for_and_keeps_the_work(how, opened):
    store, series = opened
    snum = _first_with_traces(store)
    edited = _edited(store, snum)
    store.writePendingSection(snum, edited)
    data = store.seriesData()
    data["current_section"] = snum
    store.writePendingSeries(data)
    saved_series = store.con.execute("SELECT data FROM series").fetchone()
    if how == "no-data-anywhere":
        missing = max(series.sections) + 1
        series.sections[missing] = f"{series.name}.{missing}"  # listed, no file
    else:
        missing = max(s for s in store.sectionNumbers() if s != snum)
        store.deletePendingSection(missing)  # the series still lists it

    with pytest.raises(hybrid_store.StoreSaveError, match=f"section\\(s\\) {missing} "):
        store.commit(series)
    # nothing was saved and the unsaved work is all still there
    assert store.meta("dirty") == "0"
    assert store.con.execute("SELECT data FROM series").fetchone() == saved_series
    assert store.readSection(snum) == edited
    assert store.seriesData() == data
    assert store.con.execute("SELECT COUNT(*) FROM pending_section").fetchone()[0] >= 1
    assert store.con.execute(
        "SELECT 1 FROM section WHERE snum=?", (snum,)
    ).fetchone() is not None


def test_a_section_deleted_in_the_working_layer_is_gone_before_save(opened):
    store, series = opened
    snum = _first_with_traces(store)
    hidden_file = os.path.join(series.getwdir(), series.sections[snum])
    assert os.path.isfile(hidden_file)
    store.deletePendingSection(snum)
    assert snum not in store.sectionNumbers()
    assert not store.hasSection(snum)
    with pytest.raises(FileNotFoundError, match="deleted"):
        store.readSection(snum)
    with pytest.raises(FileNotFoundError, match="deleted"):
        store.readSection(snum, hidden_file)  # nor from a file left behind


def test_a_section_only_in_the_working_folder_is_read_and_saved(opened):
    store, series = opened
    new = max(series.sections) + 1
    series.insertSection(new, "inserted.tif", 0.00254, 0.05, log_event=False)
    fp = os.path.join(series.getwdir(), series.sections[new])
    on_disk = json.loads(Path(fp).read_bytes())
    assert not store.hasSection(new)
    assert store.readSection(new, fp) == on_disk
    assert store.commit(series) is True
    assert store.hasSection(new)
    assert store.readSection(new) == on_disk


# ---------------------------------------------------------------------------
# one process at a time, a crash, a busy database
# ---------------------------------------------------------------------------

def test_a_second_store_on_the_same_series_is_refused_until_the_first_closes(tmp_path, store_root):
    fp = _copy(PARITY, tmp_path, "data")
    first = HybridStore.forJser(str(fp))
    try:
        with pytest.raises(hybrid_store.StoreBusyError, match="open in another PyReconstruct window"):
            HybridStore.forJser(str(fp))
    finally:
        first.close()
    HybridStore.forJser(str(fp)).close()  # free again once the first closes


_HOLD = """
import sys, time
from PyReconstruct.modules.datatypes.hybrid_store import HybridStore
store = HybridStore(sys.argv[1], sys.argv[2])
store.writePendingSeries({"held": True})
print("ready", flush=True)
time.sleep(600)
"""


def test_a_store_held_by_a_killed_process_opens_again(tmp_path, store_root):
    db_fp, work = hybrid_store.storePaths(str(tmp_path / "s.jser"))
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLD, db_fp, work],
        stdout=subprocess.PIPE, env=env, text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "ready"
        with pytest.raises(hybrid_store.StoreBusyError):
            HybridStore(db_fp, work)
    finally:
        proc.kill()  # no close, no cleanup: what a crash leaves
        proc.wait(timeout=30)
        proc.stdout.close()
    store = HybridStore(db_fp, work)
    try:
        # the killed process's committed working row is still there
        assert store.con.execute("SELECT data FROM pending_series").fetchone() is not None
    finally:
        store.close()


def _lock_is_free(db_fp) -> bool:
    fd = hybrid_store._lockFile(str(db_fp) + ".lock")
    if fd is None:
        return False
    os.close(fd)
    return True


def test_a_failed_open_lets_go_of_the_lock_when_the_working_folder_fails(tmp_path, monkeypatch):
    db_fp, work = tmp_path / "s.pyrstore", tmp_path / "s.work"
    real = os.makedirs

    def makedirs(path, *a, **k):
        if os.fspath(path) == str(work):
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, *a, **k)
    monkeypatch.setattr(hybrid_store.os, "makedirs", makedirs)
    with pytest.raises(PermissionError):
        HybridStore(str(db_fp), str(work))
    monkeypatch.undo()
    assert _lock_is_free(db_fp)


def test_a_failed_open_lets_go_of_the_lock_when_the_database_fails(tmp_path, monkeypatch):
    db_fp, work = tmp_path / "s.pyrstore", tmp_path / "s.work"
    HybridStore(str(db_fp), str(work)).close()  # a real store, so every check passes

    def connect(*a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")
    monkeypatch.setattr(hybrid_store.sqlite3, "connect", connect)
    with pytest.raises(sqlite3.DatabaseError, match="malformed"):
        HybridStore(str(db_fp), str(work))
    monkeypatch.undo()
    assert _lock_is_free(db_fp)


def _side_files(db_fp) -> list:
    name = Path(db_fp).name
    return sorted(p.name for p in Path(db_fp).parent.iterdir()
                  if p.name.startswith(name) and p.name not in (name, name + ".lock"))


def _foreign(db_fp, version, app_id, tables):
    con = sqlite3.connect(db_fp)
    for table in tables:
        con.execute(f"CREATE TABLE {table}")
    con.execute(f"PRAGMA user_version={version}")
    con.execute(f"PRAGMA application_id={app_id}")
    con.commit()
    con.close()


STORE_TABLES = [
    "meta(key TEXT PRIMARY KEY, value TEXT)", "series(id, data)", "log(id, text)",
    "section(snum, header)", "trace(id)", "pending_section(snum, data)", "pending_series(id, data)",
]


def _whole(db_fp, version, app_id):
    """A file with every store table and the schema record: only its header can be wrong."""
    _foreign(db_fp, version, app_id, STORE_TABLES)
    con = sqlite3.connect(db_fp)
    con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(hybrid_store.SCHEMA_VERSION),))
    con.commit()
    con.close()


@pytest.fixture
def connects(monkeypatch):
    """Every path SQLite is asked to open, while the store opens."""
    opened = []
    real = sqlite3.connect

    def connect(path, *a, **k):
        opened.append(str(path))
        return real(path, *a, **k)
    monkeypatch.setattr(hybrid_store.sqlite3, "connect", connect)
    return opened


@pytest.mark.parametrize("make, why", [
    (lambda fp: _whole(fp, hybrid_store.SCHEMA_VERSION, 0), "another program's database"),
    (lambda fp: _whole(fp, hybrid_store.SCHEMA_VERSION + 998, hybrid_store.APPLICATION_ID), "schema version 999"),
    (lambda fp: _foreign(fp, hybrid_store.SCHEMA_VERSION, 0, ["unrelated(x)"]), "another program's database"),
    (lambda fp: _foreign(fp, 0, 0, ["something_else(x)"]), "another program's database"),
    (lambda fp: fp.write_bytes(b"this is not a SQLite file " * 200), "not a SQLite file"),
], ids=["a-whole-store-of-another-program", "a-whole-store-of-a-newer-version",
        "another-program-at-this-version", "another-program-at-version-0", "not-sqlite"])
def test_a_file_whose_header_is_not_this_store_s_is_never_opened(make, why, tmp_path, connects):
    db_fp = tmp_path / "s.pyrstore"
    make(db_fp)
    before = db_fp.read_bytes()
    connects.clear()
    with pytest.raises(hybrid_store.StoreSchemaError, match=why) as refused:
        HybridStore(str(db_fp), str(tmp_path / "s.work"))
    assert "left as it was" in str(refused.value)
    assert connects == [], "SQLite was never asked to open it"
    assert _lock_is_free(db_fp)
    assert db_fp.read_bytes() == before
    assert _side_files(db_fp) == []


def _crash_copy(db_fp, dest):
    """Copy a database with its WAL as a crash leaves them: the writer never closed."""
    for ext in ("", "-wal"):
        shutil.copyfile(str(db_fp) + ext, str(dest) + ext)


def test_another_program_s_database_with_a_wal_is_never_opened(tmp_path, connects):
    live = tmp_path / "live.db"
    con = sqlite3.connect(live, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE unrelated(x)")
    con.execute("INSERT INTO unrelated VALUES (1)")
    db_fp = tmp_path / "s.pyrstore"
    _crash_copy(live, db_fp)
    con.close()

    def files():
        return {p.name: p.read_bytes() for p in tmp_path.iterdir()
                if p.name.startswith("s.pyrstore") and not p.name.endswith(".lock")}
    before = files()
    assert "s.pyrstore-wal" in before
    connects.clear()
    with pytest.raises(hybrid_store.StoreSchemaError, match="another program's database"):
        HybridStore(str(db_fp), str(tmp_path / "s.work"))
    assert connects == []
    assert files() == before, "the file and its WAL are as they were, and no -shm was made"


@pytest.mark.parametrize("change, why, kept", [
    ("UPDATE meta SET value='999' WHERE key='schema_version'", "its schema record",
     ("SELECT value FROM meta WHERE key='schema_version'", ("999",))),
    ("PRAGMA user_version=999", "schema version 999", ("PRAGMA user_version", (999,))),
], ids=["schema-record", "user-version"])
def test_a_store_whose_wal_holds_another_schema_is_refused_and_keeps_it(change, why, kept, tmp_path):
    made = tmp_path / "made.pyrstore"
    HybridStore(str(made), str(tmp_path / "made.work")).close()
    con = sqlite3.connect(made, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute(change)
    db_fp = tmp_path / "s.pyrstore"
    _crash_copy(made, db_fp)
    con.close()
    assert db_fp.read_bytes()[60:64] == hybrid_store.SCHEMA_VERSION.to_bytes(4, "big"), "the header is still a store's"
    with pytest.raises(hybrid_store.StoreSchemaError, match=why) as refused:
        HybridStore(str(db_fp), str(tmp_path / "s.work"))
    # its header is a store's, so it was opened as one: it is not promised to
    # be byte for byte the same, but what was committed is still there
    assert "left as it was" not in str(refused.value)
    assert _lock_is_free(db_fp)
    check = sqlite3.connect(db_fp)
    try:
        assert check.execute(kept[0]).fetchone() == kept[1]
    finally:
        check.close()


def test_a_file_with_a_store_s_header_but_not_its_tables_is_refused(tmp_path):
    db_fp = tmp_path / "s.pyrstore"
    _foreign(db_fp, hybrid_store.SCHEMA_VERSION, hybrid_store.APPLICATION_ID, ["unrelated(x)"])
    with pytest.raises(hybrid_store.StoreSchemaError, match="missing"):
        HybridStore(str(db_fp), str(tmp_path / "s.work"))
    assert _lock_is_free(db_fp)


@pytest.mark.parametrize("ext", ["-wal", "-journal"])
def test_a_journal_left_with_no_store_is_never_joined_to_a_new_one(ext, tmp_path):
    db_fp = tmp_path / "s.pyrstore"
    left = Path(str(db_fp) + ext)
    left.write_bytes(b"pages of some other database")
    with pytest.raises(hybrid_store.StoreSchemaError, match=ext[1:]):
        HybridStore(str(db_fp), str(tmp_path / "s.work"))
    assert not db_fp.exists()
    assert left.read_bytes() == b"pages of some other database"
    assert _lock_is_free(db_fp)


def test_a_store_s_existing_wal_is_kept_and_read(tmp_path):
    db_fp, work = tmp_path / "s.pyrstore", tmp_path / "s.work"
    store = HybridStore(str(db_fp), str(work))
    store.con.execute("PRAGMA wal_autocheckpoint=0")
    store.writePendingSeries({"in the wal": True})
    # the process dies with the write only in the WAL
    os.close(store._lock_fd)
    store._lock_fd = None
    assert Path(str(db_fp) + "-wal").stat().st_size > 0
    again = HybridStore(str(db_fp), str(work))
    try:
        assert again.seriesData() == {"in the wal": True}
    finally:
        again.close()
        store.con.close()


def test_a_new_store_s_schema_is_written_whole(tmp_path):
    db_fp = tmp_path / "s.pyrstore"
    Path(str(db_fp) + ".new").write_bytes(b"left by a create that crashed")
    HybridStore(str(db_fp), str(tmp_path / "s.work")).close()
    assert not Path(str(db_fp) + ".new").exists()
    store = HybridStore(str(db_fp), str(tmp_path / "s.work"))  # and it opens again
    try:
        tables = {r[0] for r in store.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert hybrid_store.REQUIRED_TABLES <= tables
        assert store.meta("created_utc")
        assert store.con.execute("PRAGMA application_id").fetchone() == (hybrid_store.APPLICATION_ID,)
    finally:
        store.close()


def test_a_busy_store_is_reported_as_busy_never_as_damage(tmp_path, store_root):
    store = HybridStore.forJser(str(tmp_path / "s.jser"))
    try:
        store.con.execute("PRAGMA busy_timeout=50")
        other = sqlite3.connect(store.db_fp, isolation_level=None)
        other.execute("BEGIN EXCLUSIVE")
        try:
            with pytest.raises(hybrid_store.StoreBusyError, match="another"):
                store.writePendingSeries({"x": 1})
        finally:
            other.execute("ROLLBACK")
            other.close()
        store.writePendingSeries({"x": 1})  # and it works once the other is done
    finally:
        store.close()


# ---------------------------------------------------------------------------
# where a store lives
# ---------------------------------------------------------------------------

def test_a_new_store_is_in_wal_mode_with_its_schema_version(tmp_path, store_root):
    store = HybridStore.forJser(str(tmp_path / "s.jser"))
    try:
        assert store.con.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert store.con.execute("PRAGMA user_version").fetchone() == (hybrid_store.SCHEMA_VERSION,)
        assert store.meta("schema_version") == str(hybrid_store.SCHEMA_VERSION)
    finally:
        store.close()


def test_the_store_refuses_a_network_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(hybrid_store, "fsType", lambda path: "nfs4")
    db_fp = tmp_path / "s.pyrstore"
    with pytest.raises(OSError, match="network file system"):
        HybridStore(str(db_fp), str(tmp_path / "s.work"))
    assert not db_fp.exists()
    assert not (tmp_path / "s.work").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the file system is read on Linux only")
def test_a_local_folder_s_file_system_is_read_and_allowed(tmp_path):
    fstype = hybrid_store.fsType(str(tmp_path))
    assert isinstance(fstype, str) and fstype
    assert fstype not in hybrid_store.NETWORK_FS


@pytest.mark.parametrize("platform", [None, "linux"], ids=["this-platform", "linux"])
def test_the_store_is_keyed_by_the_real_path_and_lives_in_the_store_folder(platform, tmp_path, store_root, monkeypatch):
    if platform is not None and sys.platform == "win32":
        pytest.skip("the Linux branch needs POSIX paths")
    if platform is not None:
        monkeypatch.setattr(hybrid_store.sys, "platform", platform)
    fp = _copy(PARITY, tmp_path, "data")
    other = _copy(PARITY, tmp_path, "elsewhere")
    link = tmp_path / "link.jser"
    os.symlink(fp, link)
    assert hybrid_store.storePaths(str(fp)) == hybrid_store.storePaths(str(link))
    assert hybrid_store.storePaths(str(fp)) != hybrid_store.storePaths(str(other))
    db_fp, work = hybrid_store.storePaths(str(fp))
    assert Path(db_fp).parent == store_root == Path(work).parent
    stem, _, key = Path(db_fp).stem.rpartition("-")
    assert stem == fp.stem and len(key) == 16 and int(key, 16) >= 0
    assert Path(db_fp).suffix == ".pyrstore" and Path(work).name == f"{stem}-{key}.work"


def _ignores_case(folder) -> bool:
    probe = Path(folder) / "case-probe"
    probe.write_text("")
    try:
        return (Path(folder) / "CASE-PROBE").exists()
    finally:
        probe.unlink()


def test_two_spellings_of_one_file_share_a_store(tmp_path, store_root):
    fp = _copy(PARITY, tmp_path, "data")
    if not _ignores_case(fp.parent):
        pytest.skip("this disk tells names apart by case")
    alias = fp.parent.parent / "DATA" / fp.name.upper()
    assert os.path.samefile(fp, alias)
    assert hybrid_store.storePaths(str(alias)) == hybrid_store.storePaths(str(fp))
    first = HybridStore.forJser(str(fp))
    try:
        with pytest.raises(hybrid_store.StoreBusyError):
            HybridStore.forJser(str(alias))
    finally:
        first.close()


def test_two_spellings_of_a_file_not_written_yet_share_a_store(tmp_path, store_root):
    folder = tmp_path / "Data"
    folder.mkdir()
    if not _ignores_case(folder):
        pytest.skip("this disk tells names apart by case")
    a = folder / "New Series.jser"
    b = tmp_path / "DATA" / "new series.JSER"
    assert not a.exists() and not b.exists()
    before = hybrid_store.storePaths(str(a))
    assert hybrid_store.storePaths(str(b)) == before
    # and the store stays the same one once the file exists, in either spelling
    b.write_bytes(PARITY.read_bytes())
    assert hybrid_store.storePaths(str(a)) == before
    assert hybrid_store.storePaths(str(b)) == before


def _mixed_mount() -> bool:
    """macOS with its case-sensitive /dev under a root that ignores case."""
    if sys.platform != "darwin":
        return False
    try:
        return os.pathconf("/", 11) == 0 and os.pathconf("/dev", 11) == 1
    except (OSError, ValueError):
        return False


@pytest.mark.skipif(not _mixed_mount(), reason="needs macOS's /dev: a case-sensitive mount under a root that ignores case")
def test_each_disk_s_own_case_rule_holds_across_a_mount(store_root):
    # /DEV is /dev on the root disk, which ignores case ...
    assert os.path.samefile("/DEV", "/dev")
    assert hybrid_store.storePaths("/DEV/not-written.jser") == hybrid_store.storePaths("/dev/not-written.jser")
    # ... but inside /dev case is told apart, so two names stay two stores
    assert hybrid_store.storePaths("/dev/not-written.jser") != hybrid_store.storePaths("/dev/NOT-WRITTEN.jser")


@pytest.mark.skipif(sys.platform != "darwin", reason="names are folded on macOS only")
@pytest.mark.parametrize("unread", ["case-rule", "disk-spelling"])
def test_nothing_is_folded_when_the_disk_cannot_be_read(unread, tmp_path, store_root, monkeypatch):
    folder = tmp_path / "data"
    folder.mkdir()
    if not _ignores_case(folder):
        pytest.skip("this disk tells names apart by case")
    if unread == "case-rule":
        def pathconf(path, name):
            raise OSError(22, "Invalid argument")
        monkeypatch.setattr(hybrid_store.os, "pathconf", pathconf)
    else:
        monkeypatch.setattr(hybrid_store, "_diskSpelling", lambda folder: None)
    # two spellings get two stores (the lock cannot see they are one file),
    # never one store for two files
    assert hybrid_store.storePaths(str(folder / "x.jser")) != hybrid_store.storePaths(str(folder / "X.jser"))


def test_a_disk_that_tells_case_apart_keeps_two_spellings_apart(tmp_path, store_root, monkeypatch):
    monkeypatch.setattr(hybrid_store, "_ignoresCase", lambda path: False)
    a = tmp_path / "series.jser"
    b = tmp_path / "SERIES.jser"
    assert hybrid_store.storePaths(str(a)) != hybrid_store.storePaths(str(b))


@pytest.mark.parametrize("platform, env, expected", [
    ("darwin", {}, "HOME/Library/Application Support/PyReconstruct/stores"),
    ("linux", {}, "HOME/.local/share/PyReconstruct/stores"),
    ("linux", {"XDG_DATA_HOME": "XDG"}, "XDG/PyReconstruct/stores"),
    ("win32", {"LOCALAPPDATA": "LOCAL"}, "LOCAL/PyReconstruct/stores"),
], ids=["macos", "linux", "linux-xdg", "windows"])
def test_the_store_folder_is_a_per_user_data_folder(platform, env, expected, tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("the other platforms' paths are POSIX paths")
    monkeypatch.delenv(hybrid_store.ENV_DIR, raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "HOME"))
    for key, value in env.items():
        monkeypatch.setenv(key, str(tmp_path / value))
    monkeypatch.setattr(hybrid_store.sys, "platform", platform)
    assert hybrid_store.storeRoot() == tmp_path / expected
