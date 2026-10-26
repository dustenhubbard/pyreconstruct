"""Save, close and export through the local store (store_save.py), behind the switch.

The oracles are today's: with the switch off, the same edit and Save write
the bytes a save through the store must write, and today's open of the file a
save wrote is what the next open from the store must give.

What these pin:

* with the switch off, no store is made, read or written: Save, close and the
  menu are today's;
* "store" mode is the default;
* "jser" mode: Save writes today's bytes, and the next open comes from the
  store and equals today's open of that file, after an edit, an inserted or
  deleted section, or a changed alignment;
* "store" mode: Save leaves the .jser as it was; closing writes it, byte for
  byte what today's Save writes, copying the sections the last .jser holds;
  closing with nothing saved writes nothing; a close that cannot write keeps
  everything;
* the .jser written from the store is today's on every fixture, spliced or not;
* when the store cannot hold a Save exactly, the Save is today's and the next
  open is too;
* backups: as today in "jser" mode; in "store" mode at close and at an Export,
  never at Save.
"""
import hashlib
import os
import sqlite3

import pytest

from PyReconstruct.modules.constants import fast_dumps, fast_loads, getdatetime, jser_format
from PyReconstruct.modules.datatypes import hybrid_store, series as series_module, store_open, store_save

from test_hybrid_store import PARITY, _EDGE_CASES, _edge_series, store_root  # noqa: F401  (fixture)
from test_store_open import (
    SOURCES, _copy, _open, _snapshot, _store_opens, _today, rich_series,
    switch_on, notes,  # noqa: F401  (fixture)
)


@pytest.fixture(autouse=True)
def log_clock(monkeypatch):
    """One minute for every log entry, so two Saves of the same edit log the same time."""
    now = getdatetime.get_now().replace(second=0, microsecond=0)
    monkeypatch.setattr(getdatetime, "get_now", lambda: now)


@pytest.fixture(params=[store_save.MODE_JSER, store_save.MODE_STORE])
def mode(request, monkeypatch):
    monkeypatch.setenv(store_save.ENV_MODE, request.param)
    return request.param


@pytest.fixture
def store_mode(monkeypatch):
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_STORE)


@pytest.fixture(params=sorted(SOURCES))
def src(request, tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    return SOURCES[request.param](folder)


def _edit(series):
    """Delete the first trace of the first section that has one."""
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        traces = section.tracesAsList()
        if traces:
            section.deleteTraces([traces[0]])
            section.save()
            return snum
    raise AssertionError("no traces")


def _save(series):
    """Save as the window does: the store alone when that is how it saves."""
    if not series.saveToStore():
        series.saveJser()


def _today_saved(src, tmp_path, monkeypatch, change=_edit) -> bytes:
    """The bytes today's Save writes after `change`, with the switch off."""
    with monkeypatch.context() as m:
        m.delenv(store_open.ENV_SWITCH, raising=False)
        fp = _copy(src, tmp_path / "today-save")
        series = _open(fp)
        try:
            change(series)
            series.saveJser()
        finally:
            series.close()
        return fp.read_bytes()


def _kept(src, tmp_path, name="s"):
    """A copy of src whose store holds it (the first open imports it)."""
    fp = _copy(src, tmp_path / name)
    _open(fp).close()
    return fp


# ---------------------------------------------------------------------------
# the switch
# ---------------------------------------------------------------------------

def test_with_the_switch_off_no_store_is_made_or_written(tmp_path, store_root, monkeypatch):  # noqa: F811
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_STORE)

    def refuse(*a, **k):
        raise AssertionError("store code ran with the switch off")

    for name in ("saved", "saveToStore", "writeJser", "attach", "JserHasher", "_commit"):
        monkeypatch.setattr(store_save, name, refuse)
    fp = _copy(PARITY, tmp_path / "s")
    series = _open(fp)
    assert store_save.heldStore(series) is None
    assert series.saveToStore() is False
    _edit(series)
    series.saveJser()
    series.close()
    assert not store_root.exists()


def test_with_the_switch_off_save_writes_today_s_bytes(tmp_path, store_root, monkeypatch):  # noqa: F811
    expected = _today_saved(PARITY, tmp_path, monkeypatch)
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_STORE)
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    fp = _copy(PARITY, tmp_path / "s")
    series = _open(fp)
    _edit(series)
    _save(series)
    series.close()
    assert fp.read_bytes() == expected


@pytest.mark.parametrize("value, expected", [
    (None, "store"), ("store", "store"), ("jser", "jser"), ("JSER", "store"), ("", "store"),
])
def test_the_save_mode_is_store_unless_it_says_jser(value, expected, monkeypatch):
    if value is None:
        monkeypatch.delenv(store_save.ENV_MODE, raising=False)
    else:
        monkeypatch.setenv(store_save.ENV_MODE, value)
    assert store_save.saveMode() == expected


# ---------------------------------------------------------------------------
# a Save, then the next open
# ---------------------------------------------------------------------------

def test_a_save_writes_today_s_bytes_and_the_next_open_comes_from_the_store_as_today(
    src, mode, tmp_path, switch_on, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(src, tmp_path, monkeypatch)
    fp = _kept(src, tmp_path)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    assert opens == [series.name]
    before = fp.read_bytes()
    _edit(series)
    _save(series)
    if mode == store_save.MODE_STORE:
        assert fp.read_bytes() == before
        assert store_save.ahead(series)
    else:
        assert fp.read_bytes() == expected_bytes
        assert not store_save.ahead(series)
    series.close()
    assert fp.read_bytes() == expected_bytes
    assert notes == []

    expected = _today(fp, tmp_path, monkeypatch)
    series = _open(fp)
    try:
        assert opens == [series.name] * 2
        assert _snapshot(series) == expected
    finally:
        series.close()


def _insert_and_delete(series):
    _edit(series)
    series.insertSection(1, "inserted.tif", 0.00254, 0.05, log_event=True)
    series.deleteSections([max(series.sections)])


def _refix_alignment(series):
    """Fix an object to another alignment: no section file changes."""
    name = sorted(series.data.objects)[0]
    series.setAttr(name, "alignment", "other")
    series.save()


def _unlock(series):
    """Unlock a section's alignment: every open locks it again."""
    section = series.loadSection(max(series.sections))
    section.align_locked = False
    section.save()


def _nothing(series):
    pass


@pytest.mark.parametrize("change", [_insert_and_delete, _refix_alignment, _unlock, _nothing])
def test_a_save_after_any_change_opens_next_from_the_store_as_today(
    change, mode, tmp_path, switch_on, notes, monkeypatch,  # noqa: F811
):
    src = rich_series(tmp_path)
    expected_bytes = _today_saved(src, tmp_path, monkeypatch, change)
    fp = _kept(src, tmp_path)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    change(series)
    _save(series)
    series.close()
    assert fp.read_bytes() == expected_bytes
    expected = _today(fp, tmp_path, monkeypatch)
    series = _open(fp)
    try:
        assert opens == [series.name] * 2
        assert _snapshot(series) == expected
    finally:
        series.close()
    if change is _insert_and_delete and mode == store_save.MODE_STORE:
        # an inserted section's file is not what an open writes, so this
        # store-only Save wrote the .jser instead
        assert notes == [
            "Saved to rich.jser, not the local store: an open would write "
            "section 1 otherwise than it is saved"
        ]
    else:
        assert notes == []


def _edit_last(series, in_the_first=False):
    """Delete the last trace of the last section that has one (or of the first)."""
    order = sorted(series.sections)
    for snum in (order if in_the_first else reversed(order)):
        section = series.loadSection(snum)
        traces = section.tracesAsList()
        if traces:
            section.deleteTraces([traces[-1]])
            section.save()
            return snum
    raise AssertionError("no traces")


## Not a case, as today has no answer for it: today's Save of an edit to a
## section with a non-finite coordinate raises (Section.getDict rounds it)
_EDGE_EDITS = [
    (place, name, surrogate, in_the_first)
    for place, name, surrogate in _EDGE_CASES for in_the_first in (False, True)
    if not (in_the_first and place == "coordinate" and name in ("nan", "inf", "-inf"))
]


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # today's open, on an infinite coordinate
@pytest.mark.parametrize("place, name, surrogate, in_the_first", _EDGE_EDITS, ids=[
    f"{p}-{n}" + ("-with-a-surrogate" if s else "") + ("-its-section" if f else "-other-section")
    for p, n, s, f in _EDGE_EDITS
])
def test_an_edge_value_saves_and_opens_next_as_today(
    place, name, surrogate, in_the_first, mode, tmp_path, switch_on, monkeypatch,  # noqa: F811
):
    """The edge value is in the first section with traces; the edit is there or elsewhere."""
    folder = tmp_path / "src"
    folder.mkdir()
    src = _edge_series(folder, place, name, surrogate)

    def change(series):
        _edit_last(series, in_the_first)

    expected_bytes = _today_saved(src, tmp_path, monkeypatch, change)
    fp = _kept(src, tmp_path)
    series = _open(fp)
    change(series)
    _save(series)
    series.close()
    assert fp.read_bytes() == expected_bytes
    expected = _today(fp, tmp_path, monkeypatch)
    series = _open(fp)
    try:
        assert _snapshot(series) == expected
    finally:
        series.close()


def test_two_saves_in_one_session_each_keep_the_store(mode, tmp_path, switch_on, notes, monkeypatch):  # noqa: F811
    def twice(series):
        _edit(series)
        _save(series)
        _edit(series)

    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch, twice)
    fp = _kept(PARITY, tmp_path)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    twice(series)
    _save(series)
    series.close()
    assert fp.read_bytes() == expected_bytes
    expected = _today(fp, tmp_path, monkeypatch)
    series = _open(fp)
    try:
        assert opens == [series.name] * 2
        assert _snapshot(series) == expected
    finally:
        series.close()


def test_a_series_resumed_from_its_working_folder_holds_its_store(tmp_path, switch_on, store_mode, monkeypatch):  # noqa: F811
    fp = _kept(PARITY, tmp_path)
    before = fp.read_bytes()
    first = _open(fp)
    assert store_save.heldStore(first) is not None
    # a crash: the working folder stays, and the next open resumes it
    store_save.release(first)
    second = _open(fp)
    try:
        assert store_save.heldStore(second) is not None
        _edit(second)
        assert second.saveToStore() is True
        assert fp.read_bytes() == before
    finally:
        second.close()
    assert fp.read_bytes() != before


def test_the_store_is_held_until_the_series_closes(tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    with pytest.raises(hybrid_store.StoreBusyError):
        hybrid_store.HybridStore(*hybrid_store.storePaths(str(fp)))
    series.close()
    assert store_save.heldStore(series) is None
    hybrid_store.HybridStore(*hybrid_store.storePaths(str(fp))).close()


# ---------------------------------------------------------------------------
# store mode: close and Export
# ---------------------------------------------------------------------------

def _encoded_sections(monkeypatch):
    """A list that gets one entry per section the .jser write encodes."""
    encoded = []
    real = jser_format._orjson_part

    def counting(obj):
        if type(obj) is list and len(obj) == 1 and type(obj[0]) is list:
            encoded.append(1)
        return real(obj)

    monkeypatch.setattr(jser_format, "_orjson_part", counting)
    return encoded


def test_close_writes_from_the_store_copying_the_sections_the_last_jser_holds(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    fp = _copy(PARITY, tmp_path / "s")
    # a file this app wrote, so a save can copy every section of it
    with monkeypatch.context() as m:
        m.delenv(store_open.ENV_SWITCH)
        plain = _open(fp)
        plain.saveJser()
        plain.close()
    expected_bytes = _today_saved(fp, tmp_path, monkeypatch)
    _open(fp).close()  # kept
    series = _open(fp)
    _edit(series)
    _save(series)
    store = series._local_store.store
    reads = []
    real = store.readSection
    monkeypatch.setattr(store, "readSection", lambda n: reads.append(n) or real(n))
    encoded = _encoded_sections(monkeypatch)
    series.close()
    assert fp.read_bytes() == expected_bytes
    assert len(reads) == 1 and len(encoded) == 1


def test_the_jser_written_from_the_store_is_today_s_on_every_fixture_spliced_or_not(
    src, tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(src, tmp_path, monkeypatch)
    for spliced in (True, False):
        fp = _kept(src, tmp_path, f"s-{spliced}")
        series = _open(fp)
        _edit(series)
        _save(series)
        if not spliced:
            series._local_store.spliceIndex = lambda: None
        series.close()
        assert fp.read_bytes() == expected_bytes, spliced


def test_close_with_nothing_saved_writes_nothing(tmp_path, switch_on, store_mode, monkeypatch):  # noqa: F811
    fp = _kept(PARITY, tmp_path)
    before = (fp.read_bytes(), fp.stat().st_mtime_ns)
    series = _open(fp)
    _save(series)  # nothing changed
    assert not store_save.ahead(series)
    monkeypatch.setattr(store_save, "writeJser", lambda s: pytest.fail("the .jser was written"))
    series.close()
    assert (fp.read_bytes(), fp.stat().st_mtime_ns) == before


def test_an_edit_after_the_last_save_is_not_written_at_close(tmp_path, switch_on, store_mode, monkeypatch):  # noqa: F811
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    _edit(series)
    _save(series)
    _edit(series)  # discarded: the window's "No" at close
    series.close()
    assert fp.read_bytes() == expected_bytes


def test_a_close_that_cannot_write_keeps_the_store_and_the_working_folder(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _kept(PARITY, tmp_path)
    before = fp.read_bytes()
    series = _open(fp)
    _edit(series)
    _save(series)
    notices = []
    series._surfaceSaveError = lambda fp, err, message=None: notices.append(err)

    def full(fp, data):
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as m:
        m.setattr(series_module, "_atomicWrite", full)
        with pytest.raises(OSError):
            series.close()
    assert fp.read_bytes() == before
    assert notices and not series.closed
    assert os.path.isdir(series.hidden_dir)
    assert store_save.ahead(series)
    series.close()
    assert fp.read_bytes() == expected_bytes


def test_save_as_writes_the_old_file_first_and_lets_the_store_go(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    _edit(series)
    _save(series)
    new_fp = tmp_path / "moved" / "renamed.jser"
    new_fp.parent.mkdir()
    series.move(str(new_fp))
    assert store_save.heldStore(series) is None
    assert fp.read_bytes() == expected_bytes
    series.saveJser()
    series.close()
    assert new_fp.exists()


def _written_by_this_app(tmp_path):
    """A kept series whose .jser this app wrote, so its store can splice from it."""
    fp = _copy(PARITY, tmp_path / "s")
    series = _open(fp)
    series.saveJser()
    series.close()
    return fp


def _change_in_the_store(fp, snum, thickness=0.123):
    """Change section snum's row in the store of fp, leaving its key as it was.

    Returns the row's header as it was. Another program or a damaged disk
    does this: the key is unchanged, so a Save skips the row.
    """
    con = sqlite3.connect(hybrid_store.storePaths(str(fp))[0], isolation_level=None)
    try:
        con.execute("PRAGMA busy_timeout=5000")
        (header,) = con.execute("SELECT header FROM section WHERE snum=?", (snum,)).fetchone()
        doc = fast_loads(header)
        doc["thickness"] = thickness
        con.execute("UPDATE section SET header=? WHERE snum=?", (fast_dumps(doc), snum))
    finally:
        con.close()
    return header


def _change_in_the_jser(series, snum):
    """Change one byte of section snum where the .jser holds it, so no write copies it."""
    held = store_save.heldStore(series)
    key = store_save._keys(held.store)[snum][0]
    offset, length = held.spliceIndex().ranges[key][:2]
    with open(series.jser_fp, "r+b") as f:
        f.seek(offset + length // 2)
        byte = f.read(1)
        f.seek(offset + length // 2)
        f.write(b"0" if byte != b"0" else b"1")


def _saved_over_a_changed_section(tmp_path, visited):
    """A series saved to its store after section 1 changed there under its key.

    The .jser's copy of section 1 changed too. With `visited`, section 1 was
    loaded first, so its working file holds it as it was saved.
    """
    fp = _written_by_this_app(tmp_path)
    series = _open(fp)
    if visited:
        assert series.loadSection(1).thickness == 0.05
    _change_in_the_store(fp, 1)
    _change_in_the_jser(series, 1)
    series.setAttr("axon", "comment", "a separately saved edit")
    series.save()
    assert series.saveToStore()
    return fp, series


def _notices(series):
    notices = []
    series._surfaceSaveError = lambda fp, err, message=None: notices.append(str(err))
    return notices


@pytest.mark.parametrize("visited", [False, True], ids=["stub", "working-file"])
def test_close_refuses_a_store_section_changed_under_its_key(
    visited, tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    fp, series = _saved_over_a_changed_section(tmp_path, visited)
    before = fp.read_bytes()
    notices = _notices(series)
    with pytest.raises(series_module.SeriesSaveError):
        series.close()
    assert fp.read_bytes() == before
    assert len(notices) == 1 and "section 1 in the local store" in notices[0]
    assert not series.closed and os.path.isdir(series.hidden_dir)
    assert store_save.heldStore(series) is not None and store_save.ahead(series)
    if visited:
        assert series.loadSection(1).thickness == 0.05
    store_save.release(series)


def test_save_as_refuses_a_store_section_changed_under_its_key(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    # visited: Save As writes out every other section from the store first
    fp, series = _saved_over_a_changed_section(tmp_path, visited=True)
    before = fp.read_bytes()
    hidden_dir = series.hidden_dir
    notices = _notices(series)
    new_fp = tmp_path / "moved" / "renamed.jser"
    new_fp.parent.mkdir()
    with pytest.raises(series_module.SeriesSaveError):
        series.move(str(new_fp))
    assert fp.read_bytes() == before
    assert len(notices) == 1 and "section 1 in the local store" in notices[0]
    assert series.jser_fp == str(fp) and os.path.isdir(hidden_dir)
    assert os.listdir(new_fp.parent) == []
    assert store_save.heldStore(series) is not None and store_save.ahead(series)
    assert series.loadSection(1).thickness == 0.05
    store_save.release(series)


def test_a_pretty_write_checks_each_section_against_its_key(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    fp, series = _saved_over_a_changed_section(tmp_path, visited=True)
    monkeypatch.setenv(jser_format.PRETTY_ENV_VAR, "1")
    before = fp.read_bytes()
    notices = _notices(series)
    with pytest.raises(series_module.SeriesSaveError):
        series.close()
    assert fp.read_bytes() == before
    assert len(notices) == 1 and "section 1 in the local store" in notices[0]
    store_save.release(series)


# ---------------------------------------------------------------------------
# when the store cannot hold a Save
# ---------------------------------------------------------------------------

def test_a_save_the_store_cannot_hold_is_today_s_and_so_is_the_next_open(
    mode, tmp_path, switch_on, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _kept(PARITY, tmp_path)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    name = series.name
    _edit(series)
    with monkeypatch.context() as m:
        m.setattr(store_save, "openedSection", lambda *a: None)
        _save(series)
    # the .jser holds the Save at once, and the store is let go
    assert fp.read_bytes() == expected_bytes
    assert store_save.heldStore(series) is None
    assert any("not kept in step" in n for n in notes)
    series.close()
    expected = _today(fp, tmp_path, monkeypatch)
    series = _open(fp)  # today's, and kept again
    try:
        assert opens == [name]
        assert _snapshot(series) == expected
    finally:
        series.close()
    series = _open(fp)
    try:
        assert opens == [name] * 2
    finally:
        series.close()


def test_a_log_naming_a_lone_surrogate_is_kept_by_the_store(mode, tmp_path, switch_on, notes, monkeypatch):  # noqa: F811
    fp = _kept(PARITY, tmp_path)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    _edit(series)
    series.addLog("\ud800", None, "Create object")  # a name SQLite text cannot hold
    _save(series)
    assert store_save.heldStore(series) is not None
    assert not any("not kept" in n or "not the local store" in n for n in notes)
    series.close()
    with open(fp, "rb") as f:
        assert b"\\ud800" in f.read()  # the .jser has it, as today's Save writes it
    series = _open(fp)
    try:
        assert opens == [series.name] * 2
        assert "\ud800" in {log.obj_name for log in series.getFullHistory().all_logs}
    finally:
        series.close()


def test_a_working_file_changed_while_it_is_saved_is_not_kept(tmp_path, switch_on, notes, monkeypatch):  # noqa: F811
    fp = _kept(PARITY, tmp_path)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    name = series.name
    snum = _edit(series)
    real = store_save._commit

    def changed_meanwhile(series, *a):
        path = os.path.join(series.getwdir(), series.sections[snum])
        with open(path, "ab") as f:
            f.write(b" ")
        return real(series, *a)

    monkeypatch.setattr(store_save, "_commit", changed_meanwhile)
    series.saveJser()
    assert store_save.heldStore(series) is None
    assert any("changed while it was saved" in n for n in notes)
    series.close()
    series = _open(fp)
    try:
        assert opens == [name]  # the import's open, not one from the store
    finally:
        series.close()


def test_a_section_an_open_would_write_otherwise_is_stored_anew_at_the_next_save(
    mode, tmp_path, switch_on, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _copy(PARITY, tmp_path / "s")
    with monkeypatch.context() as m:
        # as if an open of the next .jser would write every section otherwise
        m.setattr(store_save, "opensAlike", lambda *a: False)
        _open(fp).close()
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    _edit(series)
    _save(series)  # a store-only Save cannot: it writes the .jser instead
    assert fp.read_bytes() == expected_bytes
    assert store_save.heldStore(series) is not None
    series.close()
    expected = _today(fp, tmp_path, monkeypatch)
    series = _open(fp)
    try:
        assert opens == [series.name] * 2
        assert _snapshot(series) == expected
    finally:
        series.close()
    assert notes == [] if mode == store_save.MODE_JSER else len(notes) == 1


def test_an_inserted_section_is_held_as_the_next_open_writes_it(tmp_path, switch_on, monkeypatch):  # noqa: F811
    src = rich_series(tmp_path)
    fp = _kept(src, tmp_path)
    series = _open(fp)
    series.insertSection(1, "inserted.tif", 0.00254, 0.05, log_event=True)
    raw = (series.getwdir() and open(os.path.join(series.getwdir(), series.sections[1]), "rb").read())
    series.saveJser()
    held = series._local_store.store.readSection(1)
    series.close()
    # the working file's keys are in another order than an open writes them
    assert fast_dumps(held) != raw
    assert fast_dumps(held) == fast_dumps(store_save.openedSection(raw, 1))


def test_opens_alike_is_judged_on_the_bytes_an_open_writes(tmp_path, monkeypatch):
    monkeypatch.delenv(store_open.ENV_SWITCH, raising=False)
    series = _open(_copy(PARITY, tmp_path))
    try:
        with open(os.path.join(series.getwdir(), series.sections[0]), "rb") as f:
            good = f.read()
    finally:
        series.close()
    assert store_save.opensAlike(good, 0)
    # a section an open fills in (a key missing) is not the bytes it writes
    lacking = fast_loads(good)
    del lacking["mag"]
    lacking_raw = fast_dumps(lacking)
    assert not store_save.opensAlike(lacking_raw, 0)


def test_a_store_only_save_the_store_cannot_take_is_left_to_the_jser(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    _edit(series)
    with monkeypatch.context() as m:
        m.setattr(store_save, "openedSection", lambda *a: None)
        assert series.saveToStore() is False
    assert store_save.heldStore(series) is not None  # as it was
    assert not store_save.ahead(series)
    series.close()


# ---------------------------------------------------------------------------
# the hash of the file written
# ---------------------------------------------------------------------------

def test_the_hash_starts_over_when_the_write_does(tmp_path):
    hasher = store_save.JserHasher()
    with open(tmp_path / "f", "w+b") as raw:
        f = hasher.wrap(raw)
        f.write(b"first try")
        f.seek(0)
        f.truncate()
        f.write(b"second")
    assert hasher.digest() == hashlib.sha256(b"second").hexdigest()


@pytest.mark.parametrize("move", ["seek-elsewhere", "truncate-elsewhere", "other-call"])
def test_a_write_the_hash_cannot_follow_gives_no_hash(move, tmp_path):
    hasher = store_save.JserHasher()
    with open(tmp_path / "f", "w+b") as raw:
        f = hasher.wrap(raw)
        f.write(b"abc")
        if move == "seek-elsewhere":
            f.seek(1)
        elif move == "truncate-elsewhere":
            f.truncate(1)
        else:
            f.flush()
    assert hasher.digest() is None


def test_a_save_whose_write_cannot_be_hashed_hashes_the_file(tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _kept(PARITY, tmp_path)
    opens = _store_opens(monkeypatch)
    series = _open(fp)
    _edit(series)
    monkeypatch.setattr(store_save.JserHasher, "digest", lambda self: None)
    series.saveJser()
    series.close()
    series = _open(fp)
    try:
        assert opens == [series.name] * 2
    finally:
        series.close()
