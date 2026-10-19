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
* a .jser the store's close wrote, but did not record, is recorded;
* a store whose .jser was changed by someone else, or that cannot be opened
  as it is, is set aside whole, never deleted, and the user is told where, at
  that open and every later one until it is written out;
* a resumed working folder takes its store, and its next Save folds every
  changed section file into the store;
* `PyReconstruct --export-local-copy` writes a set-aside store, or a .jser's
  store, to a new .jser with the bytes a close writes, and never replaces a
  file.
"""
import hashlib
import io
import os
import shutil
import sys
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
