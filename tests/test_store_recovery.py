"""Crash recovery and stranded work for the local store (store_recovery.py).

In "store" mode Save writes the store alone, and close writes the .jser. A
crash before the close is played here by letting go of the store with the
series still open (the operating system does that for a killed process), and
then either keeping the working folder (the window resumes it) or deleting it
(the user declines it). tests/test_store_kill_reopen.py does the same with a
real process killed by SIGKILL.

The oracle is today's: the same edits saved with the switch off.

What these pin:

* with the switch off, none of this runs and no store is read or changed;
* a store that holds a Save the .jser lacks is offered at the next open, and
  never passed over silently: yes, or nobody to ask, opens that Save, and the
  close writes it to the .jser as today's Save would; no keeps it aside;
* a .jser the store's close wrote, but did not record, is recorded; a close
  that fails, or a later Save, drops its note of that .jser;
* a store whose .jser was changed by someone else, or that cannot be opened
  as it is, is set aside whole, as one file, never deleted, and the user is
  told where, at that open and every later one until it is written out; a
  store that cannot be made one file stays where it is, and the user is told;
* on Windows a store with work no .jser has is never moved: it stays where it
  is, named at each open or its Save offered, until it is written out; then a
  later open moves it, and a store that cannot go back beside a journal left
  at its old name is named to the user;
* a store whose .jser moved holds work no open takes: every open names it
  until it is written out;
* a resumed working folder takes its store, and its next Save folds every
  changed section file into the store;
* `PyReconstruct --export-local-copy` writes a set-aside store, or a .jser's
  store, to a new .jser with the bytes a close writes, and never replaces a
  file, even one made after its check, with hard links or without.
"""
import errno
import hashlib
import io
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from PyReconstruct import cli
from PyReconstruct.modules.datatypes import hybrid_store, store_open, store_recovery, store_save
from PyReconstruct.modules.datatypes import series as series_module
from PyReconstruct.modules.datatypes.hybrid_store import HybridStore

from test_hybrid_store import PARITY, SERIES_FILES, store_root  # noqa: F401  (fixture)
from test_store_open import _Asked, _copy, _open, _snapshot, _store_opens, _today, store_root_glob
from test_store_open import notes, switch_on  # noqa: F401  (fixture)
from test_store_save import _edit, _edit_last, _kept, _today_saved, log_clock, store_mode  # noqa: F401  (fixture)
from test_store_save_gui import _saved_in_the_store, _window, kept  # noqa: F401  (fixture)


def _both_edits(series):
    _edit(series)
    _edit_last(series)


def _crash(series):
    """What a crash leaves: the working folder, and a store no process holds."""
    store_save.release(series)
    series.leave_open = True
    series.close()


def _decline(fp):
    """Delete the working folder, as the window does when its work is declined."""
    hidden = Path(fp).parent / f".{Path(fp).stem}"
    shutil.rmtree(hidden)


def _saved_then_crashed(tmp_path, change=_edit):
    """A kept series, `change` saved to the store alone, then a crash."""
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    change(series)
    assert series.saveToStore() is True
    _crash(series)
    return fp


def _meta(fp, key):
    store = HybridStore.forJser(str(fp))
    try:
        return store.meta(key)
    finally:
        store.close()


def _sha(fp):
    return hashlib.sha256(Path(fp).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# the switch
# ---------------------------------------------------------------------------

def test_with_the_switch_off_no_recovery_runs_and_the_store_is_left_as_it_was(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    stores = {p: p.read_bytes() for p in Path(switch_on).iterdir() if p.is_file()}
    monkeypatch.delenv(store_open.ENV_SWITCH)

    def refuse(*a, **k):
        raise AssertionError("store recovery ran with the switch off")

    for name in ("atOpen", "resumed", "standing", "setAside", "finishWrite", "tell"):
        monkeypatch.setattr(store_recovery, name, refuse)
    monkeypatch.setattr(store_open.StoreForOpen, "attempt", staticmethod(refuse))
    expected_resumed = _snapshot_of_folder(fp)
    # the working folder: resumed as today
    series = _open(fp, notifier=_NoNotifier())
    try:
        assert store_save.heldStore(series) is None
        assert _snapshot_of_folder(fp) == expected_resumed
    finally:
        series.close()
    # no working folder: today's open of the .jser
    _decline(fp)
    expected = _today(fp, tmp_path, monkeypatch)
    series = _open(fp, notifier=_NoNotifier())
    try:
        assert store_save.heldStore(series) is None
        assert _snapshot(series) == expected
    finally:
        series.close()
    assert {p: p.read_bytes() for p in Path(switch_on).iterdir() if p.is_file()} == stores


class _NoNotifier:
    def confirm(self, *a, **k):
        raise AssertionError(f"asked: {a}")

    def notify(self, *a, **k):
        raise AssertionError(f"told: {a}")


def _snapshot_of_folder(fp):
    hidden = Path(fp).parent / f".{Path(fp).stem}"
    return {p.name: p.read_bytes() for p in sorted(hidden.iterdir()) if p.is_file()}


# ---------------------------------------------------------------------------
# a Save the .jser lacks, at the next open
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("answer", [True, None])
def test_a_save_the_jser_lacks_is_offered_and_its_close_writes_today_s_bytes(
    answer, tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    before = fp.read_bytes()
    _decline(fp)
    opens = _store_opens(monkeypatch)
    asker = _Asked(answer)
    series = _open(fp, notifier=asker)
    try:
        assert len(asker.asked) == 1
        assert f"{fp.name} does not have the work last saved on this computer (" in asker.asked[0]
        assert opens == [series.name]
        assert store_save.ahead(series)
        assert fp.read_bytes() == before
    finally:
        series.close()
    assert fp.read_bytes() == expected_bytes
    assert asker.told == [] and store_root_glob(fp) == []
    # the store holds the .jser again, and the next open is a quiet one from it
    again = _open(fp, notifier=_NoNotifier())
    try:
        assert opens == [series.name] * 2
        assert _snapshot(again) == _today(fp, tmp_path, monkeypatch)
    finally:
        again.close()


def test_declining_a_save_keeps_it_aside_and_opens_the_jser_as_it_is(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    before = fp.read_bytes()
    _decline(fp)
    expected = _today(fp, tmp_path, monkeypatch)
    asker = _Asked(False)
    series = _open(fp, notifier=asker)
    try:
        assert len(asker.asked) == 1
        assert _snapshot(series) == expected
    finally:
        series.close()
    assert fp.read_bytes() == before
    aside = store_root_glob(fp)
    assert len(aside) == 1 and ".v1.conflict-" in aside[0]
    assert len(asker.told) == 1
    assert aside[0] in asker.told[0] and "--export-local-copy" in asker.told[0]
    # the store at the .jser's path is a new copy of the .jser as it is
    assert _meta(fp, store_save.META_DIRTY) == "0"
    assert _meta(fp, store_open.META_SHA) == _sha(fp)
    # every later open says where the work is, until it is written out
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert asker.asked == [] and len(asker.told) == 1 and aside[0] in asker.told[0]
    out = tmp_path / "out" / "back.jser"
    out.parent.mkdir()
    assert store_recovery.exportStore(aside[0], str(out)) == str(out)
    assert out.read_bytes() == expected_bytes
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert asker.told == []
    # never deleted
    assert os.path.isfile(aside[0])


def test_a_jser_changed_under_a_save_keeps_the_store_aside_without_asking(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    # another window or program writes the file
    shutil.copyfile(SERIES_FILES[1], fp)
    other = fp.read_bytes()
    expected = _today(fp, tmp_path, monkeypatch)
    asker = _Asked()
    series = _open(fp, notifier=asker)
    try:
        assert asker.asked == []
        assert _snapshot(series) == expected
    finally:
        series.close()
    assert fp.read_bytes() == other
    aside = store_root_glob(fp)
    assert len(aside) == 1 and len(asker.told) == 1
    assert "was changed on disk by another window or program" in asker.told[0]
    out = tmp_path / "back.jser"
    store_recovery.exportStore(aside[0], str(out))
    assert out.read_bytes() == expected_bytes


def test_a_jser_its_close_wrote_but_did_not_record_is_recorded_not_set_aside(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    _edit(series)
    assert series.saveToStore() is True

    class Crash(BaseException):
        pass

    def cut_off(*a, **k):
        raise Crash()

    # the close puts the .jser in place, and dies before the store records it
    with monkeypatch.context() as m:
        m.setattr(hybrid_store.HybridStore, "recordJser", cut_off)
        with pytest.raises(Crash):
            store_save.writeJser(series)
    assert fp.read_bytes() == expected_bytes
    assert _meta_held(series, store_save.META_DIRTY) == "1"
    _crash(series)
    _decline(fp)
    opens = _store_opens(monkeypatch)
    asker = _Asked()
    again = _open(fp, notifier=asker)
    try:
        assert asker.asked == [] and asker.told == []
        assert opens == [again.name]
        assert not store_save.ahead(again)
    finally:
        again.close()
    assert fp.read_bytes() == expected_bytes
    assert store_root_glob(fp) == []
    assert _meta(fp, store_open.META_SHA) == _sha(fp)
    assert _meta(fp, store_save.META_WRITING) is None


def _meta_held(series, key):
    return store_save.heldStore(series).store.meta(key)


def test_the_close_notes_the_jser_it_writes_until_it_is_recorded(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    from PyReconstruct.modules.backend.func import atomic_io

    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    _edit(series)
    series.saveToStore()
    seen = []
    real = atomic_io.replace_with_retry

    def replace(src, dst, *a, **k):
        if os.path.abspath(dst) == os.path.abspath(fp):
            seen.append((_meta_held(series, store_save.META_WRITING), _sha(src)))
        return real(src, dst, *a, **k)

    monkeypatch.setattr(atomic_io, "replace_with_retry", replace)
    store_save.writeJser(series)
    assert len(seen) == 1 and seen[0][0] == seen[0][1]
    assert _meta_held(series, store_save.META_WRITING) is None
    series.close()


@pytest.mark.parametrize("error", [OSError(errno.EIO, "the disk failed"), RuntimeError("a fault")])
def test_a_close_that_fails_drops_its_note_of_the_jser_it_was_writing(
    error, tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    from PyReconstruct.modules.backend.func import atomic_io

    fp = _kept(PARITY, tmp_path)
    before = fp.read_bytes()
    series = _open(fp)
    _edit(series)
    series.saveToStore()
    seen = []

    def fail(src, dst, *a, **k):
        seen.append(_meta_held(series, store_save.META_WRITING))
        raise error

    with monkeypatch.context() as m:
        m.setattr(atomic_io, "replace_with_retry", fail)
        m.setattr(series, "_surfaceSaveError", lambda *a, **k: None)
        with pytest.raises(type(error)):
            store_save.writeJser(series)
    assert fp.read_bytes() == before
    assert len(seen) == 1 and seen[0] is not None
    assert _meta_held(series, store_save.META_WRITING) is None
    assert _meta_held(series, store_save.META_DIRTY) == "1"
    series.close()


def test_a_later_save_drops_the_note_so_an_older_jser_is_never_taken_for_it(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    save_a = _today_saved(PARITY, tmp_path / "a", monkeypatch)
    save_b = _today_saved(PARITY, tmp_path / "b", monkeypatch, _both_edits)
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    _edit(series)
    assert series.saveToStore() is True
    # a close was writing Save A's .jser, and stopped before it was in place
    store_save._noteWriting(store_save.heldStore(series).store, hashlib.sha256(save_a).hexdigest())
    _edit_last(series)
    assert series.saveToStore() is True
    assert _meta_held(series, store_save.META_WRITING) is None
    _crash(series)
    _decline(fp)
    # another program puts Save A's bytes in place: not the store's Save B
    fp.write_bytes(save_a)
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert fp.read_bytes() == save_a
    aside = store_root_glob(fp)
    assert len(aside) == 1 and len(asker.told) == 1
    assert "was changed on disk by another window or program" in asker.told[0]
    out = tmp_path / "back.jser"
    store_recovery.exportStore(aside[0], str(out))
    assert out.read_bytes() == save_b


def test_a_save_that_cannot_be_read_at_the_open_is_said_and_kept_for_the_next(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    expected = _today(fp, tmp_path, monkeypatch)

    def fail(self):
        raise store_open.StoreUnavailable("disk I/O error")

    with monkeypatch.context() as m:
        m.setattr(store_open._StoreSource, "sections", fail)
        asker = _Asked()
        series = _open(fp, notifier=asker)
        try:
            assert _snapshot(series) == expected
        finally:
            series.close()
    assert len(asker.asked) == 1 and len(asker.told) == 1
    assert "could not be read just now" in asker.told[0]
    assert _meta(fp, store_save.META_DIRTY) == "1"
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert len(asker.asked) == 1


def test_a_store_without_its_numbers_is_set_aside_not_deleted(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    store = HybridStore.forJser(str(fp))
    store.con.execute("DELETE FROM section_stats WHERE snum = (SELECT MIN(snum) FROM section_stats)")
    store.close()
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert asker.asked == []
    aside = store_root_glob(fp)
    assert len(aside) == 1 and "could not be opened as it is" in asker.told[0]


def test_a_set_aside_store_is_one_file_whole_on_its_own(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    _open(fp, notifier=_Asked(False)).close()
    aside = store_root_glob(fp)
    assert len(aside) == 1
    # its WAL was folded in before it moved: a rollback-journal file, alone
    assert Path(aside[0]).read_bytes()[18:20] == b"\x01\x01"
    assert [ext for ext in store_recovery.SIDECARS if os.path.lexists(aside[0] + ext)] == []


def test_a_store_another_program_has_open_is_kept_whole_where_it_is(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    shutil.copyfile(SERIES_FILES[1], fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    # another program reads the store, so its WAL cannot be folded into it
    reader = sqlite3.connect(db_fp)
    try:
        reader.execute("SELECT count(*) FROM meta").fetchone()
        asker = _Asked()
        series = _open(fp, notifier=asker)
        try:
            assert store_save.heldStore(series) is None
        finally:
            series.close()
    finally:
        reader.close()
    # nothing moved: no set-aside name holds a part of it
    assert store_root_glob(fp) == []
    assert len(asker.told) == 1
    assert "could not be set aside just now" in asker.told[0] and db_fp in asker.told[0]
    assert _meta(fp, store_save.META_DIRTY) == "1"
    # the next open, with the store let go, sets it aside
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert len(store_root_glob(fp)) == 1 and len(asker.told) == 1
    out = tmp_path / "back.jser"
    store_recovery.exportStore(store_root_glob(fp)[0], str(out))
    assert out.read_bytes() == expected_bytes


def _kept_in_place(tmp_path, monkeypatch, then=None):
    """A store with a Save over a changed .jser, held open by another program
    through one open, so it stays where it is. `then(series)` runs on that open."""
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    shutil.copyfile(SERIES_FILES[1], fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    reader = sqlite3.connect(db_fp)
    try:
        reader.execute("SELECT count(*) FROM meta").fetchone()
        asker = _Asked()
        series = _open(fp, notifier=asker)
        try:
            assert store_save.heldStore(series) is None
            if then is not None:
                then(series)
        finally:
            series.close()
    finally:
        reader.close()
    assert store_root_glob(fp) == [] and "could not be set aside just now" in asker.told[0]
    return fp, db_fp


def test_a_store_kept_in_place_and_written_out_is_named_no_more(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp, db_fp = _kept_in_place(tmp_path, monkeypatch)
    out = tmp_path / "back.jser"
    store_recovery.exportStore(db_fp, str(out))
    assert out.read_bytes() == expected_bytes
    # written out: the next open sets it aside without a word, and keeps it
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert asker.asked == [] and asker.told == []
    aside = store_root_glob(fp)
    assert len(aside) == 1
    assert store_recovery.exportStore(aside[0], str(tmp_path / "again.jser"))
    assert (tmp_path / "again.jser").read_bytes() == expected_bytes
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert asker.told == []


def test_a_save_written_out_and_declined_is_set_aside_without_a_word(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    before = fp.read_bytes()
    out = tmp_path / "back.jser"
    code, _ = _cli(monkeypatch, str(fp), str(out))
    assert code == 0 and out.read_bytes() == expected_bytes
    # written out: still offered; No sets it aside without a word, and keeps it
    asker = _Asked(False)
    _open(fp, notifier=asker).close()
    assert len(asker.asked) == 1 and asker.told == []
    assert fp.read_bytes() == before
    aside = store_root_glob(fp)
    assert len(aside) == 1
    store_recovery.exportStore(aside[0], str(tmp_path / "again.jser"))
    assert (tmp_path / "again.jser").read_bytes() == expected_bytes


def test_a_resumed_folder_over_a_store_written_out_says_nothing(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    shutil.copyfile(SERIES_FILES[1], fp)
    store_recovery.exportStore(str(fp), str(tmp_path / "back.jser"))
    asker = _Asked()
    resumed = _open(fp, notifier=asker)
    try:
        assert store_save.heldStore(resumed) is None
    finally:
        resumed.close()
    assert asker.told == [] and len(store_root_glob(fp)) == 1


def test_a_save_over_a_store_kept_in_place_leaves_that_store_whole(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)

    def save(series):
        _edit_last(series)
        # no store: Save writes the .jser, as today
        assert series.saveToStore() is False
        series.saveJser()

    fp, db_fp = _kept_in_place(tmp_path, monkeypatch, then=save)
    assert fp.read_bytes() != Path(SERIES_FILES[1]).read_bytes()
    assert _meta(fp, store_save.META_DIRTY) == "1"
    asker = _Asked()
    _open(fp, notifier=asker).close()
    aside = store_root_glob(fp)
    assert len(aside) == 1 and len(asker.told) == 1 and aside[0] in asker.told[0]
    out = tmp_path / "back.jser"
    store_recovery.exportStore(aside[0], str(out))
    assert out.read_bytes() == expected_bytes


def _just_before_the_rename(m, db_fp, then):
    """Run then() as the store is about to be renamed to its set-aside name."""
    real = os.rename

    def rename(src, dst, *a, **k):
        if os.path.abspath(src) == os.path.abspath(db_fp) and store_recovery.SET_ASIDE in str(dst):
            then()
        return real(src, dst, *a, **k)

    m.setattr(os, "rename", rename)


def test_no_other_program_writes_a_store_as_it_moves(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    # another program has the store open, idle, and writes it at the rename
    other = sqlite3.connect(db_fp, isolation_level=None, timeout=0)
    refused = []

    def write():
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('theirs', '1')")
        except sqlite3.OperationalError as e:
            refused.append(str(e))

    try:
        with monkeypatch.context() as m:
            _just_before_the_rename(m, db_fp, write)
            try:
                kept = store_recovery.setAside(store_open.StoreForOpen.attempt(str(fp)))
            except store_open.StoreUnavailable:
                kept = None
        # a journal is never apart from the store it is for
        if kept is not None:
            assert not os.path.lexists(db_fp + "-journal")
        if sys.platform != "win32":
            # the store held SQLite's lock through the rename
            assert kept is not None and refused and "locked" in refused[0]
            # and SQLite refuses a write to the moved file from that program
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                other.execute("BEGIN IMMEDIATE")
                other.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('theirs', '1')")
    finally:
        try:
            other.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        other.close()
    out = tmp_path / "back.jser"
    store_recovery.exportStore(kept or db_fp, str(out))
    assert out.read_bytes() == expected_bytes


_DIES_WRITING = """
import os, sqlite3, sys
con = sqlite3.connect(sys.argv[1], isolation_level=None)
con.execute("PRAGMA cache_size=2")
con.execute("BEGIN IMMEDIATE")
con.execute("CREATE TABLE theirs(x)")
con.execute(
    "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 400)"
    " INSERT INTO theirs SELECT randomblob(4000) FROM n"
)
os._exit(0)
"""


def test_a_store_a_program_wrote_as_it_moved_on_windows_goes_back_to_its_journal(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    import subprocess

    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    # on Windows only a store written out is moved
    store_recovery.exportStore(str(fp), str(tmp_path / "first.jser"))
    # Windows: the store is closed before the rename, and another program
    # writes it in that moment and dies, leaving its journal
    def die_writing():
        subprocess.run([sys.executable, "-c", _DIES_WRITING, db_fp], check=True)
        assert os.path.isfile(db_fp + "-journal")

    with monkeypatch.context() as m:
        m.setattr(store_recovery, "_WINDOWS", True)
        _just_before_the_rename(m, db_fp, die_writing)
        with pytest.raises(store_open.StoreUnavailable):
            store_recovery.setAside(store_open.StoreForOpen.attempt(str(fp)))
    assert store_root_glob(fp) == [] and os.path.isfile(db_fp)
    # SQLite puts back what that program wrote
    con = sqlite3.connect(db_fp)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name = 'theirs'").fetchone() is None
    finally:
        con.close()
    out = tmp_path / "back.jser"
    store_recovery.exportStore(db_fp, str(out))
    assert out.read_bytes() == expected_bytes


def _changed_on_windows(tmp_path, monkeypatch):
    """A store with a Save over a changed .jser, under Windows' rules for setting it aside."""
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    shutil.copyfile(SERIES_FILES[1], fp)
    monkeypatch.setattr(store_recovery, "_WINDOWS", True)
    return fp, hybrid_store.storePaths(str(fp))[0]


def test_on_windows_a_store_with_work_no_jser_has_stays_where_it_is_until_written_out(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp, db_fp = _changed_on_windows(tmp_path, monkeypatch)
    for _ in range(2):
        # each open names it where it is, and moves nothing
        asker = _Asked()
        series = _open(fp, notifier=asker)
        try:
            assert store_save.heldStore(series) is None
        finally:
            series.close()
        assert store_root_glob(fp) == [] and _meta(fp, store_save.META_DIRTY) == "1"
        assert len(asker.told) == 1 and db_fp in asker.told[0]
        assert "On Windows that work stays there until it is written out." in asker.told[0]
        assert "tries again" not in asker.told[0]
    out = tmp_path / "back.jser"
    store_recovery.exportStore(db_fp, str(out))
    assert out.read_bytes() == expected_bytes
    # written out: the next open moves it without a word, and the .jser gets a new store
    asker = _Asked()
    series = _open(fp, notifier=asker)
    try:
        assert store_save.heldStore(series) is not None
    finally:
        series.close()
    aside = store_root_glob(fp)
    assert asker.told == [] and len(aside) == 1
    store_recovery.exportStore(aside[0], str(tmp_path / "again.jser"))
    assert (tmp_path / "again.jser").read_bytes() == expected_bytes


def test_on_windows_a_declined_save_stays_where_it_is_and_is_offered_again(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    monkeypatch.setattr(store_recovery, "_WINDOWS", True)
    asker = _Asked(False)
    _open(fp, notifier=asker).close()
    assert len(asker.asked) == 1 and store_root_glob(fp) == []
    assert len(asker.told) == 1 and db_fp in asker.told[0]
    assert "On Windows that work stays there until it is written out." in asker.told[0]
    # still there: offered again, and Yes opens it, and its close writes the .jser
    asker = _Asked(True)
    _open(fp, notifier=asker).close()
    assert len(asker.asked) == 1 and asker.told == []
    assert fp.read_bytes() == expected_bytes


def test_on_windows_a_store_not_known_to_be_written_out_is_not_moved(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp, db_fp = _written_out_on_windows(tmp_path, monkeypatch)

    def unread(held):
        raise store_open.StoreUnavailable("disk I/O error")

    with monkeypatch.context() as m:
        m.setattr(store_recovery, "_writtenOut", unread)
        with pytest.raises(store_open.StoreUnavailable):
            store_recovery.setAside(store_open.StoreForOpen.attempt(str(fp)))
    assert store_root_glob(fp) == [] and os.path.isfile(db_fp)


def test_off_windows_a_store_kept_in_place_is_tried_again_at_the_next_open(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    monkeypatch.setattr(store_recovery, "_WINDOWS", False)
    fp, db_fp = _kept_in_place(tmp_path, monkeypatch)
    text = store_recovery.setAsideText(str(fp), None, None, in_place=db_fp)
    assert "its next open tries again" in text and "On Windows" not in text


def _written_out_on_windows(tmp_path, monkeypatch):
    fp, db_fp = _changed_on_windows(tmp_path, monkeypatch)
    store_recovery.exportStore(str(fp), str(tmp_path / "first.jser"))
    return fp, db_fp


def _moves_as_a_program_writes(m, db_fp, back):
    """As the store moves, another program writes it and dies, leaving its
    journal; putting the store back meets `back`."""
    import subprocess

    real = os.rename

    def rename(src, dst, *a, **k):
        if os.path.abspath(src) == os.path.abspath(db_fp) and store_recovery.SET_ASIDE in str(dst):
            subprocess.run([sys.executable, "-c", _DIES_WRITING, db_fp], check=True)
        elif os.path.abspath(dst) == os.path.abspath(db_fp):
            raise back
        return real(src, dst, *a, **k)

    m.setattr(os, "rename", rename)


def test_on_windows_a_store_that_cannot_go_back_beside_its_journal_is_named_and_kept(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp, db_fp = _written_out_on_windows(tmp_path, monkeypatch)
    asker = _Asked()
    with monkeypatch.context() as m:
        _moves_as_a_program_writes(m, db_fp, PermissionError(13, "Access is denied"))
        series = _open(fp, notifier=asker)
        try:
            # no store is made beside that journal
            assert store_save.heldStore(series) is None
        finally:
            series.close()
    aside = store_root_glob(fp)
    assert len(aside) == 1 and not os.path.lexists(db_fp) and os.path.isfile(db_fp + "-journal")
    # written out, and told all the same
    assert len(asker.told) == 1
    told = asker.told[0]
    assert aside[0] in told and db_fp + "-journal" in told and "Access is denied" in told
    assert any("could not be put back" in n for n in notes)
    out = tmp_path / "back.jser"
    store_recovery.exportStore(aside[0], str(out))
    assert out.read_bytes() == expected_bytes


def test_on_windows_a_file_made_at_the_old_name_keeps_the_store_set_aside(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp, db_fp = _written_out_on_windows(tmp_path, monkeypatch)
    with monkeypatch.context() as m:
        _moves_as_a_program_writes(m, db_fp, FileExistsError(17, "File exists"))
        aside = store_recovery.setAside(store_open.StoreForOpen.attempt(str(fp)))
    assert store_root_glob(fp) == [aside] and os.path.isfile(db_fp + "-journal")
    assert any("with a journal left at" in n for n in notes)
    out = tmp_path / "back.jser"
    store_recovery.exportStore(aside, str(out))
    assert out.read_bytes() == expected_bytes


class _ReportsWal:
    """A store connection whose change out of WAL reports that it failed."""

    def __init__(self, con):
        self._con = con

    def execute(self, sql, *a):
        cur = self._con.execute(sql, *a)
        if sql.startswith("PRAGMA journal_mode="):
            return _Row(("wal",))
        return cur

    def __getattr__(self, name):
        return getattr(self._con, name)


class _Row:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


def test_a_store_whose_journal_mode_stays_wal_is_not_moved(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    held = store_open.StoreForOpen.attempt(str(fp))
    held.store.con = _ReportsWal(held.store.con)
    with pytest.raises(store_open.StoreUnavailable):
        store_recovery.setAside(held)
    assert store_root_glob(fp) == [] and os.path.isfile(db_fp)
    assert _meta(fp, store_save.META_DIRTY) == "1"


class _SidecarAfterLock:
    """A store connection that finds a file beside the store once it holds the lock."""

    def __init__(self, con, sidecar):
        self._con = con
        self._sidecar = sidecar

    def execute(self, sql, *a):
        cur = self._con.execute(sql, *a)
        if sql == "BEGIN EXCLUSIVE":
            Path(self._sidecar).write_bytes(b"")
        return cur

    def __getattr__(self, name):
        return getattr(self._con, name)


def test_a_store_with_a_file_beside_it_after_the_lock_is_not_moved(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    held = store_open.StoreForOpen.attempt(str(fp))
    held.store.con = _SidecarAfterLock(held.store.con, db_fp + "-wal")
    with pytest.raises(store_open.StoreUnavailable):
        store_recovery.setAside(held)
    assert store_root_glob(fp) == [] and os.path.isfile(db_fp)
    os.remove(db_fp + "-wal")
    assert _meta(fp, store_save.META_DIRTY) == "1"


_DIES_AFTER_COMMIT = """
import os, sqlite3, sys
con = sqlite3.connect(sys.argv[1], isolation_level=None)
con.execute("PRAGMA wal_autocheckpoint=0")
con.execute("BEGIN IMMEDIATE")
con.execute("CREATE TABLE theirs(x)")
con.execute("INSERT INTO theirs VALUES (1)")
con.execute("COMMIT")
os._exit(0)
"""


@pytest.mark.parametrize("sidecar", ["-journal", "-wal"])
def test_no_store_is_made_over_a_journal_or_wal_left_without_its_store(
    sidecar, tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    import subprocess

    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    # another program writes the store and dies, then the store is moved apart
    # from its journal or WAL (what a crash in a rename would leave)
    if sidecar == "-journal":
        con = sqlite3.connect(db_fp)
        con.execute("PRAGMA journal_mode=DELETE")
        con.close()
        subprocess.run([sys.executable, "-c", _DIES_WRITING, db_fp], check=True)
    else:
        subprocess.run([sys.executable, "-c", _DIES_AFTER_COMMIT, db_fp], check=True)
    apart = tmp_path / "apart.pyrstore"
    os.rename(db_fp, apart)
    left = Path(db_fp + sidecar).read_bytes()
    assert left
    asker = _Asked()
    _open(fp, notifier=asker).close()
    # no store was made there, and what was left is as it was
    assert not os.path.lexists(db_fp)
    assert Path(db_fp + sidecar).read_bytes() == left
    # put back beside it, SQLite takes back that program's half-written
    # change, or keeps the one it committed
    os.rename(apart, db_fp)
    con = sqlite3.connect(db_fp)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        theirs = con.execute("SELECT 1 FROM sqlite_master WHERE name = 'theirs'").fetchone()
        assert (theirs is not None) == (sidecar == "-wal")
    finally:
        con.close()
    out = tmp_path / "back.jser"
    store_recovery.exportStore(db_fp, str(out))
    assert out.read_bytes() == expected_bytes


def test_two_set_asides_in_one_second_keep_both(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(store_recovery, "datetime", Frozen)
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    first = store_recovery.setAside(store_open.StoreForOpen.attempt(str(fp)))
    series = _open(fp, notifier=_Asked())
    _edit_last(series)
    assert series.saveToStore() is True
    _crash(series)
    _decline(fp)
    second = store_recovery.setAside(store_open.StoreForOpen.attempt(str(fp)))
    assert first != second
    assert store_root_glob(fp) == sorted([first, second])
    for kept_fp, change in ((first, _edit), (second, _edit_last)):
        out = tmp_path / f"{Path(kept_fp).stem}.jser"
        store_recovery.exportStore(kept_fp, str(out))
        assert out.read_bytes() == _today_saved(PARITY, tmp_path / Path(kept_fp).stem, monkeypatch, change)


# ---------------------------------------------------------------------------
# a .jser that moved
# ---------------------------------------------------------------------------

def test_a_save_whose_jser_moved_is_named_at_every_open_until_written_out(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    # with its .jser in place, the store is its own open's to offer, no other's
    other = _copy(SERIES_FILES[1], tmp_path / "other")
    asker = _Asked()
    _open(other, notifier=asker).close()
    assert asker.told == []
    moved = fp.with_name("renamed.jser")
    fp.rename(moved)
    # the moved .jser opens as it is, and the open names the store with the Save
    asker = _Asked()
    _open(moved, notifier=asker).close()
    assert asker.asked == [] and len(asker.told) == 1
    assert fp.name in asker.told[0] and db_fp in asker.told[0]
    assert "--export-local-copy" in asker.told[0]
    # so does the open of another series
    asker = _Asked()
    _open(other, notifier=asker).close()
    assert len(asker.told) == 1 and db_fp in asker.told[0]
    # written out: no longer named, and never deleted
    out = tmp_path / "back.jser"
    code, text = _cli(monkeypatch, db_fp, str(out))
    assert (code, text.strip()) == (0, str(out))
    assert out.read_bytes() == expected_bytes
    asker = _Asked()
    _open(moved, notifier=asker).close()
    assert asker.told == [] and os.path.isfile(db_fp)
    # put back, it takes another Save, and moves again: named again
    moved.rename(fp)
    series = _open(fp, notifier=_Asked(True))
    _edit_last(series)
    assert series.saveToStore() is True
    _crash(series)
    _decline(fp)
    fp.rename(moved)
    asker = _Asked()
    _open(moved, notifier=asker).close()
    assert len(asker.told) == 1 and db_fp in asker.told[0]


def _moved(tmp_path, name="s"):
    """A store with a Save its .jser lacks, whose .jser was then renamed."""
    fp = _saved_then_crashed(tmp_path / name)
    _decline(fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    fp.rename(fp.with_name("renamed.jser"))
    return os.path.abspath(db_fp)


def test_an_open_whose_own_store_is_held_names_a_store_whose_jser_moved(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    db_fp = _moved(tmp_path)
    other = _kept(SERIES_FILES[1], tmp_path, "other")
    # another window holds the store of the series opened
    holder = store_open.StoreForOpen.attempt(str(other))
    try:
        asker = _Asked()
        _open(other, notifier=asker).close()
        assert len(asker.told) == 1 and db_fp in asker.told[0]
        # so does a resumed working folder
        series = _open(other, notifier=_Asked())
        series.leave_open = True
        series.close()
        asker = _Asked()
        resumed = _open(other, notifier=asker)
        resumed.close()
        assert len(asker.told) == 1 and db_fp in asker.told[0]
    finally:
        holder.close()


def test_an_open_whose_own_store_cannot_be_read_names_a_store_whose_jser_moved(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    db_fp = _moved(tmp_path)
    other = _saved_then_crashed(tmp_path / "other")
    _decline(other)

    def fail(held):
        raise store_open.StoreUnavailable("disk I/O error")

    monkeypatch.setattr(store_recovery, "standing", fail)
    asker = _Asked()
    _open(other, notifier=asker).close()
    assert len(asker.told) == 1 and db_fp in asker.told[0]


def test_a_relative_store_folder_names_a_store_whose_jser_moved(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(hybrid_store.ENV_DIR, "stores")
    db_fp = _moved(tmp_path)
    other = _kept(SERIES_FILES[1], tmp_path, "other")
    asker = _Asked()
    _open(other, notifier=asker).close()
    assert len(asker.told) == 1 and db_fp in asker.told[0]


def test_the_scan_for_kept_work_never_stops_an_open(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    _moved(tmp_path)
    other = _kept(SERIES_FILES[1], tmp_path, "other")

    def fail(db_fp):
        raise RuntimeError("a fault")

    monkeypatch.setattr(store_recovery, "_readStore", fail)
    asker = _Asked()
    _open(other, notifier=asker).close()
    assert asker.told == []
    assert any("could not be read" in line and "a fault" in line for line in notes)


def test_a_fault_in_either_list_of_kept_work_never_stops_an_open(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    other = _kept(SERIES_FILES[1], tmp_path, "other")

    def fail(*a, **k):
        raise RuntimeError("a fault")

    monkeypatch.setattr(store_recovery, "setAsideStores", fail)
    monkeypatch.setattr(store_recovery, "strandedStores", fail)
    asker = _Asked()
    _open(other, notifier=asker).close()
    assert asker.told == []
    assert any(line.startswith("Set-aside local stores not listed") for line in notes)
    assert any(line.startswith("Local stores whose .jser is gone not listed") for line in notes)


def test_a_store_whose_meta_is_not_text_stops_no_other_store_being_named(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    bad = _moved(tmp_path, "bad")
    good = _moved(tmp_path, "good")
    con = sqlite3.connect(bad, isolation_level=None)
    try:
        con.execute("UPDATE meta SET value = X'FF' WHERE key = 'created_utc'")
    finally:
        con.close()
    other = _kept(SERIES_FILES[1], tmp_path, "other")
    asker = _Asked()
    _open(other, notifier=asker).close()
    assert len(asker.told) == 1 and good in asker.told[0] and bad not in asker.told[0]
    assert any(bad in line and "could not be read" in line for line in notes)


def test_a_relative_store_folder_reads_its_set_aside_stores(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(hybrid_store.ENV_DIR, "stores")
    fp = _saved_then_crashed(tmp_path)
    _decline(fp)
    aside = store_recovery.setAside(store_open.StoreForOpen.attempt(str(fp)))
    assert not os.path.isabs(aside)
    assert store_recovery._readStore(aside)[0]["jser_path"] == str(fp)
    store_recovery.exportStore(aside, str(tmp_path / "back.jser"))
    # written out, and read as such: named no more
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert asker.told == []


def test_a_store_with_only_working_rows_whose_jser_moved_is_named(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _kept(PARITY, tmp_path)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    store = HybridStore.forJser(str(fp))
    try:
        snum = store.sectionNumbers()[0]
        store.writePendingSection(snum, store.readSection(snum))
    finally:
        store.close()
    assert _meta(fp, store_save.META_DIRTY) == "0"
    fp.rename(fp.with_name("renamed.jser"))
    other = _copy(SERIES_FILES[1], tmp_path / "other")
    asker = _Asked()
    _open(other, notifier=asker).close()
    assert len(asker.told) == 1 and os.path.abspath(db_fp) in asker.told[0]


def test_a_set_aside_store_that_cannot_be_read_is_named(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _kept(PARITY, tmp_path)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    damaged = db_fp[:-len(store_recovery.STORE_EXT)] + ".conflict-20261019T120000Z.pyrstore"
    Path(damaged).write_bytes(b"not a store")
    asker = _Asked()
    _open(fp, notifier=asker).close()
    assert len(asker.told) == 1 and damaged in asker.told[0]


# ---------------------------------------------------------------------------
# a resumed working folder
# ---------------------------------------------------------------------------

def test_a_resumed_folder_takes_its_store_and_its_save_folds_in_every_changed_file(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch, _both_edits)
    fp = _kept(PARITY, tmp_path)
    before = fp.read_bytes()
    series = _open(fp)
    _edit(series)
    assert series.saveToStore() is True
    # unsaved work after that Save, in the working folder only (the window
    # writes the series file as a section is left)
    _edit_last(series)
    series.save()
    _crash(series)
    resumed = _open(fp, notifier=_NoNotifier())
    try:
        assert store_save.heldStore(resumed) is not None
        assert resumed.saveToStore() is True
        assert fp.read_bytes() == before
    finally:
        resumed.close()
    assert fp.read_bytes() == expected_bytes


def test_a_resumed_folder_whose_close_says_no_writes_the_store_s_last_save(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    _edit(series)
    series.saveToStore()
    _edit_last(series)
    _crash(series)
    resumed = _open(fp, notifier=_NoNotifier())
    resumed.close()  # no Save: the close writes the last one
    assert fp.read_bytes() == expected_bytes


def test_a_resumed_folder_over_a_changed_jser_sets_the_store_aside(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    shutil.copyfile(SERIES_FILES[1], fp)
    asker = _Asked()
    resumed = _open(fp, notifier=asker)
    try:
        assert store_save.heldStore(resumed) is None
        assert asker.asked == [] and len(asker.told) == 1
    finally:
        resumed.close()
    assert len(store_root_glob(fp)) == 1


def test_a_resumed_folder_whose_store_cannot_be_set_aside_says_where_it_is(
    tmp_path, switch_on, store_mode, notes, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    shutil.copyfile(SERIES_FILES[1], fp)
    db_fp, _ = hybrid_store.storePaths(str(fp))
    reader = sqlite3.connect(db_fp)
    try:
        reader.execute("SELECT count(*) FROM meta").fetchone()
        asker = _Asked()
        resumed = _open(fp, notifier=asker)
        try:
            assert store_save.heldStore(resumed) is None
        finally:
            resumed.close()
    finally:
        reader.close()
    assert store_root_glob(fp) == [] and len(asker.told) == 1
    assert "could not be set aside just now" in asker.told[0] and db_fp in asker.told[0]


def test_a_resumed_folder_of_an_unchanged_jser_takes_its_store(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    _crash(series)
    resumed = _open(fp, notifier=_NoNotifier())
    try:
        assert store_save.heldStore(resumed) is not None
    finally:
        resumed.close()


# ---------------------------------------------------------------------------
# PyReconstruct --export-local-copy
# ---------------------------------------------------------------------------

def _cli(monkeypatch, *args):
    out = io.StringIO()
    monkeypatch.setattr(sys, "argv", ["PyReconstruct", "--export-local-copy", *args])
    monkeypatch.setattr(sys, "stdout", out)
    with pytest.raises(SystemExit) as e:
        cli.main()
    return e.value.code, out.getvalue()


def test_the_command_line_writes_a_jser_s_store_to_a_new_file_and_replaces_none(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    before = fp.read_bytes()
    out = tmp_path / "new.jser"
    code, text = _cli(monkeypatch, str(fp), str(out))
    assert (code, text.strip()) == (0, str(out))
    assert out.read_bytes() == expected_bytes
    assert fp.read_bytes() == before
    # the store still holds its Save: this was a copy, not the close
    assert _meta(fp, store_save.META_DIRTY) == "1"
    out.write_bytes(b"mine")
    code, text = _cli(monkeypatch, str(fp), str(out))
    assert code == 1 and "was not replaced" in text
    assert out.read_bytes() == b"mine"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".export-")] == []


def _no_hard_links(monkeypatch):
    def link(*a, **k):
        raise OSError(errno.ENOTSUP, "no hard links")

    monkeypatch.setattr(os, "link", link)


@pytest.mark.parametrize("links", [True, False], ids=["hard links", "no hard links"])
def test_the_export_never_replaces_a_file_made_after_its_check(
    links, tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    out = tmp_path / "new.jser"
    real = os.path.lexists

    def lexists(path):
        # each check finds no file, and another program makes one right after
        if os.path.abspath(path) == str(out):
            out.write_bytes(b"theirs")
            return False
        return real(path)

    if not links:
        _no_hard_links(monkeypatch)
    monkeypatch.setattr(os.path, "lexists", lexists)
    with pytest.raises(FileExistsError):
        store_recovery.exportStore(str(fp), str(out))
    monkeypatch.setattr(os.path, "lexists", real)
    assert out.read_bytes() == b"theirs"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".export-")] == []


def test_the_export_without_hard_links_writes_the_same_bytes(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    expected_bytes = _today_saved(PARITY, tmp_path, monkeypatch)
    fp = _saved_then_crashed(tmp_path)
    _no_hard_links(monkeypatch)
    out = tmp_path / "new.jser"
    assert store_recovery.exportStore(str(fp), str(out)) == str(out)
    assert out.read_bytes() == expected_bytes
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".export-")] == []


def test_a_copy_that_fails_without_hard_links_leaves_no_part_of_a_file(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    _no_hard_links(monkeypatch)

    def copy(src, dst, length=0):
        dst.write(src.read(100))
        raise OSError(errno.ENOSPC, "the disk is full")

    out = tmp_path / "new.jser"
    with monkeypatch.context() as m:
        m.setattr(shutil, "copyfileobj", copy)
        with pytest.raises(OSError):
            store_recovery.exportStore(str(fp), str(out))
    assert not os.path.lexists(out)
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".export-")] == []
    assert _meta(fp, store_save.META_WRITTEN_OUT) is None


def test_the_command_line_names_its_file_beside_the_series_by_default(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    fp = _saved_then_crashed(tmp_path)
    code, text = _cli(monkeypatch, str(fp))
    written = Path(text.strip())
    assert code == 0 and written.parent == fp.parent
    assert written.name.startswith(f"{fp.stem} recovered ") and written.suffix == ".jser"


def test_the_command_line_refuses_a_store_a_window_holds(
    tmp_path, switch_on, store_mode, monkeypatch,  # noqa: F811
):
    fp = _kept(PARITY, tmp_path)
    series = _open(fp)
    try:
        code, text = _cli(monkeypatch, str(fp), str(tmp_path / "new.jser"))
        assert code == 1 and "open in another PyReconstruct window" in text
        assert not (tmp_path / "new.jser").exists()
    finally:
        series.close()


def test_the_command_line_says_when_there_is_no_store(tmp_path, switch_on, monkeypatch):  # noqa: F811
    fp = _copy(PARITY, tmp_path / "s")
    code, text = _cli(monkeypatch, str(fp))
    assert code == 1 and "No local copy" in text
    code, text = _cli(monkeypatch)
    assert code == 2 or "usage" in text.lower()


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------

@pytest.mark.gui
def test_the_window_s_recovery_offer_gives_the_resumed_series_its_store(
    kept, store_mode, monkeypatch,  # noqa: F811
):
    from PyReconstruct.modules.gui.main import main_window as mw

    window = _window(kept)
    try:
        _saved_in_the_store(window)
        store_save.release(window.series)  # a crash: the store is let go
        monkeypatch.setattr(mw, "unsavedNotify", lambda: True)
        # the timer file of this very window would say the series is in use
        monkeypatch.setattr(window, "_seriesHolder", lambda folder: None)
        resumed = window._recoverUnsavedSeries(str(kept))
        assert isinstance(resumed, series_module.Series)
        try:
            assert store_save.heldStore(resumed) is not None
            assert store_save.ahead(resumed)
        finally:
            store_save.release(resumed)
            resumed.leave_open = True
            resumed.close()
    finally:
        window.series.modified = False
        window.close()


def test_the_command_line_writes_working_rows_over_the_last_save(tmp_path, switch_on, monkeypatch):  # noqa: F811
    import json

    fp = _kept(PARITY, tmp_path)
    store = HybridStore.forJser(str(fp))
    try:
        snum = store.sectionNumbers()[0]
        section = store.readSection(snum)
        section["thickness"] = 0.125
        store.writePendingSection(snum, section)
    finally:
        store.close()
    out = tmp_path / "new.jser"
    store_recovery.exportStore(str(fp), str(out))
    assert json.loads(out.read_bytes())["sections"][snum]["thickness"] == 0.125
