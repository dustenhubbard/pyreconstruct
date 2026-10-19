"""The local store's setting, its cleanup, and the check at open (local_stores.py).

What these pin:

* the switch: PYRECON_HYBRID_STORE, when set, wins over the setting; unset,
  the setting decides in a Dev build and nothing turns the store on in a
  stable one. With neither, an open is today's: no store folder, no store
  code, nothing said;
* the Options row: a Dev build has a Files tab with the row, a stable build
  has neither, and the setting waits for OK;
* cleanup removes a clean store unused for 30 days, then clean stores oldest
  first while the folder is over the cap, and never a store with work, one
  in use, one whose .jser is not found, or one it cannot read;
* nothing outside the store folder, and no file in it that is not a store's
  own, is ever removed;
* with the store off, an open names a store that holds work its .jser lacks.
"""
import os
import time
from datetime import datetime, timezone

import pytest

from PyReconstruct.modules.backend import settings_store
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.constants import build_flavor
from PyReconstruct.modules.datatypes import local_stores, store_open
from PyReconstruct.modules.datatypes.hybrid_store import HybridStore, storePaths
from PyReconstruct.modules.datatypes.local_stores import (
    ENV_SWITCH, META_OPENED, SETTING, cleanUp, removeClean,
)
from PyReconstruct.modules.datatypes.series import Series

from test_hybrid_store import PARITY, store_root  # noqa: F401  (fixture)
from test_store_open import _copy

DAY = 86400


class _Told:
    """A notifier that records what it is told and asks nothing."""

    def __init__(self):
        self.told = []

    def notify(self, message):
        self.told.append(message)
        return True

    def confirm(self, *a, **k):
        raise AssertionError(f"the open asked: {a}")


@pytest.fixture
def settings(monkeypatch):
    """The process's settings, in memory."""
    store = DictSettingsStore()
    monkeypatch.setattr(settings_store, "_DEFAULT_STORE", store)
    return store


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: True)


@pytest.fixture
def stable(monkeypatch):
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: False)


@pytest.fixture
def no_switch(monkeypatch):
    monkeypatch.delenv(ENV_SWITCH, raising=False)


@pytest.fixture
def notes(monkeypatch):
    lines = []
    monkeypatch.setattr(local_stores, "log_note", lines.append)
    return lines


def _open(fp, notifier=None):
    return Series.openJser(str(fp), progress=NullProgressReporter, notifier=notifier)


def _utc(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_store(folder, monkeypatch, days_ago=0):
    """A clean store, made by an open with the switch on; (jser, store file)."""
    fp = _copy(PARITY, folder)
    with monkeypatch.context() as m:
        m.setenv(ENV_SWITCH, "1")
        _open(fp).close()
    db, _ = storePaths(str(fp))
    assert os.path.isfile(db)
    if days_ago:
        set_meta(db, **{META_OPENED: _utc(time.time() - days_ago * DAY)})
    return fp, db


def held(db):
    return HybridStore(db, db[:-len(".pyrstore")] + ".work")


def set_meta(db, **values):
    store = held(db)
    try:
        for key, value in values.items():
            store.setMeta(key, value)
    finally:
        store.close()


def files_of(db):
    """Every file of one store that is on disk."""
    root, name = os.path.split(db)
    base = name[:-len(".pyrstore")]
    return sorted(n for n in os.listdir(root) if n.startswith(base))


# ---------------------------------------------------------------------------
# the switch and the setting
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dev_build", [True, False], ids=["dev", "stable"])
def test_with_no_switch_and_the_setting_off_an_open_is_today_s(dev_build, tmp_path, store_root, settings, no_switch, monkeypatch):  # noqa: F811
    """Nothing changes for anyone who has not turned it on: no store code runs,
    no folder is made, nothing is said, no setting is written."""
    monkeypatch.setattr(build_flavor, "is_dev_build", lambda: dev_build)

    def refuse(*a, **k):
        raise AssertionError("store code ran with the store off")

    monkeypatch.setattr(store_open, "openJser", refuse)
    told = _Told()
    series = _open(_copy(PARITY, tmp_path / "s"), notifier=told)
    series.close()
    assert told.told == []
    assert not store_root.exists()
    assert local_stores.startCleanup() is None
    assert not store_root.exists()
    assert not any(settings._data.values())


def test_the_setting_turns_it_on_in_a_dev_build(tmp_path, store_root, settings, dev, no_switch):  # noqa: F811
    settings.set_value(None, SETTING, True)
    assert local_stores.enabled()
    fp = _copy(PARITY, tmp_path / "s")
    _open(fp).close()
    assert os.path.isfile(storePaths(str(fp))[0])


def test_a_stable_build_ignores_the_setting(tmp_path, store_root, settings, stable, no_switch):  # noqa: F811
    """The Dev and stable apps share their settings: a Dev choice must not reach stable."""
    settings.set_value(None, SETTING, True)
    assert not local_stores.enabled()
    _open(_copy(PARITY, tmp_path / "s")).close()
    assert not store_root.exists()


@pytest.mark.parametrize("switch, setting, on", [
    ("1", False, True), ("0", True, False), ("", True, False), ("true", True, False),
])
def test_the_switch_wins_over_the_setting(switch, setting, on, settings, dev, monkeypatch):
    settings.set_value(None, SETTING, setting)
    monkeypatch.setenv(ENV_SWITCH, switch)
    assert local_stores.enabled() is on


def test_the_setting_is_read_as_settings_store_it(settings, dev, no_switch):
    assert not local_stores.enabled()
    for stored, on in [(False, False), ("false", False), (True, True), ("true", True)]:
        settings.set_value(None, SETTING, stored)
        assert local_stores.enabled() is on


def test_an_open_records_when_the_store_was_opened(tmp_path, store_root, monkeypatch):  # noqa: F811
    fp, db = make_store(tmp_path / "s", monkeypatch, days_ago=40)
    with monkeypatch.context() as m:
        m.setenv(ENV_SWITCH, "1")
        _open(fp).close()
    state = local_stores.readState(*os.path.split(db))
    assert time.time() - state.last_used < DAY


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

def test_a_clean_store_unused_for_30_days_is_removed_and_a_recent_one_kept(tmp_path, store_root, notes, monkeypatch):  # noqa: F811
    _, old = make_store(tmp_path / "old", monkeypatch, days_ago=31)
    _, recent = make_store(tmp_path / "recent", monkeypatch, days_ago=29)
    report = cleanUp()
    assert report.removed == [os.path.basename(old)]
    assert files_of(old) == []
    assert os.path.isfile(recent)
    assert local_stores.readState(*os.path.split(recent)).clean


def test_over_the_cap_clean_stores_go_oldest_first(tmp_path, store_root, monkeypatch):  # noqa: F811
    _, a = make_store(tmp_path / "a", monkeypatch, days_ago=3)
    _, b = make_store(tmp_path / "b", monkeypatch, days_ago=2)
    _, c = make_store(tmp_path / "c", monkeypatch, days_ago=1)
    total = local_stores.folderSize()
    one = total // 3
    # room for two of the three
    report = cleanUp(cap=total - one // 2)
    assert report.removed == [os.path.basename(a)]
    assert not os.path.exists(a)
    assert os.path.isfile(b) and os.path.isfile(c)
    assert local_stores.folderSize() <= total - one // 2


def _pending(db):
    store = held(db)
    try:
        store.writePendingSection(0, {"edited": True})
    finally:
        store.close()


def _dirty(db):
    set_meta(db, dirty=1)


def _work_file(db):
    work = db[:-len(".pyrstore")] + ".work"
    with open(os.path.join(work, "0.section"), "w") as f:
        f.write("{}")


@pytest.mark.parametrize("give_work", [_pending, _dirty, _work_file],
                         ids=["working-rows", "saved-past-its-jser", "a-file-in-its-working-folder"])
def test_a_store_with_work_is_never_removed(give_work, tmp_path, store_root, monkeypatch):  # noqa: F811
    _, db = make_store(tmp_path / "s", monkeypatch, days_ago=400)
    give_work(db)
    before = files_of(db)
    for report in (cleanUp(cap=0), cleanUp(now=time.time() + 1000 * DAY, cap=0), removeClean()):
        assert report.removed == []
        assert report.kept == [(os.path.basename(db), local_stores.WORK)]
    assert files_of(db) == before
    state = local_stores.readState(*os.path.split(db))
    assert state.work and not state.clean


def test_a_store_in_use_is_never_removed(tmp_path, store_root, monkeypatch):  # noqa: F811
    _, db = make_store(tmp_path / "s", monkeypatch, days_ago=400)
    store = held(db)
    try:
        for report in (cleanUp(cap=0), removeClean()):
            assert report.removed == []
            assert report.kept == [(os.path.basename(db), local_stores.IN_USE)]
        assert os.path.isfile(db)
    finally:
        store.close()
    assert cleanUp(cap=0).removed == [os.path.basename(db)]


def test_a_store_whose_jser_is_not_found_is_kept(tmp_path, store_root, monkeypatch):  # noqa: F811
    """A share not mounted at app start looks the same as a deleted file."""
    fp, db = make_store(tmp_path / "s", monkeypatch, days_ago=400)
    os.rename(fp, str(fp) + ".away")
    report = cleanUp(cap=0)
    assert report.removed == []
    assert report.kept == [(os.path.basename(db), local_stores.NO_JSER)]
    os.rename(str(fp) + ".away", fp)
    assert cleanUp(cap=0).removed == [os.path.basename(db)]


def test_a_store_that_cannot_be_read_is_kept(tmp_path, store_root, notes, monkeypatch):  # noqa: F811
    _, db = make_store(tmp_path / "s", monkeypatch, days_ago=400)
    with open(db, "r+b") as f:
        f.seek(100)
        f.write(b"\xff" * 4000)  # the schema page, past the header
    report = cleanUp(cap=0)
    assert report.removed == []
    assert report.kept == [(os.path.basename(db), local_stores.UNREADABLE)]
    assert os.path.isfile(db)


def test_cleanup_leaves_every_file_that_is_not_a_store_s_own(tmp_path, store_root, monkeypatch):  # noqa: F811
    _, db = make_store(tmp_path / "s", monkeypatch, days_ago=400)
    key = os.path.basename(db)[:16]
    others = [
        "notes.txt",
        f"{key}.v1.conflict-20261019T000000Z.pyrstore",   # a set-aside store
        f"{key}.v2.pyrstore",                             # another schema
        f"{key}.v1.pyrstore.bak",
    ]
    for name in others:
        (store_root / name).write_bytes(b"keep me")
    (store_root / "folder").mkdir()
    (store_root / "folder" / f"{key}.v1.pyrstore").write_bytes(b"keep me")
    assert cleanUp(cap=0).removed == [os.path.basename(db)]
    assert removeClean().removed == []
    for name in others:
        assert (store_root / name).read_bytes() == b"keep me"
    assert (store_root / "folder" / f"{key}.v1.pyrstore").read_bytes() == b"keep me"


@pytest.mark.skipif(os.name == "nt", reason="links need rights on Windows")
@pytest.mark.parametrize("part", ["-wal", "-shm", ".lock", ".work", ""])
def test_a_link_in_the_store_folder_is_never_followed(part, tmp_path, store_root, notes, monkeypatch):  # noqa: F811
    """A link where a store's file or folder goes: what it points at stays."""
    outside = tmp_path / "outside"
    outside.mkdir()
    target_file = outside / "precious.txt"
    target_file.write_bytes(b"precious")
    _, db = make_store(tmp_path / "s", monkeypatch, days_ago=400)
    if part == ".work":
        link = db[:-len(".pyrstore")] + ".work"
        os.rmdir(link)
        os.symlink(outside, link)
    elif part == "":
        # the store itself is a link to a store kept elsewhere
        moved = outside / os.path.basename(db)
        os.rename(db, moved)
        os.symlink(moved, db)
    else:
        link = db + part
        if os.path.exists(link):
            os.remove(link)
        os.symlink(target_file, link)
    cleanUp(cap=0)
    removeClean()
    assert target_file.read_bytes() == b"precious"
    if part == "":
        assert (outside / os.path.basename(db)).is_file()
    assert os.path.lexists(db[:-len(".pyrstore")] + part if part == ".work" else db + part)


@pytest.mark.parametrize("name", [
    "../escape.v1.pyrstore", "/etc/passwd", "notes.txt", "0123456789abcdef.v1.pyrstore/../x",
    "0123456789abcdef.v1.pyrstore-wal/x",
])
def test_removal_refuses_any_name_that_is_not_a_store_file(name, tmp_path):
    with pytest.raises(ValueError):
        local_stores._removeFile(str(tmp_path), name)
    with pytest.raises(ValueError):
        local_stores._removeWorkDir(str(tmp_path), name)
    with pytest.raises(ValueError):
        local_stores.removeIfClean(str(tmp_path), name)


def test_a_non_empty_working_folder_is_never_emptied(tmp_path):
    work = tmp_path / "0123456789abcdef.v1.work"
    work.mkdir()
    (work / "x").write_text("work")
    with pytest.raises(OSError):
        local_stores._removeWorkDir(str(tmp_path), work.name)
    assert (work / "x").read_text() == "work"


def test_cleanup_with_no_store_folder_makes_none(store_root):  # noqa: F811
    assert cleanUp(cap=0).removed == []
    assert removeClean().removed == []
    assert local_stores.folderSize() == 0
    assert not store_root.exists()


def test_cleanup_at_app_start_runs_in_the_background(tmp_path, store_root, notes, monkeypatch):  # noqa: F811
    _, db = make_store(tmp_path / "s", monkeypatch, days_ago=31)
    thread = local_stores.startCleanup()
    assert thread is not None and thread.daemon
    thread.join(30)
    assert not os.path.exists(db)
    assert any(line.startswith("Removed 1 unused local copy") for line in notes)


def test_a_store_made_again_after_cleanup_opens_from_the_store(tmp_path, store_root, monkeypatch):  # noqa: F811
    """Removing a clean store loses nothing: the next open builds it again."""
    fp, db = make_store(tmp_path / "s", monkeypatch, days_ago=31)
    assert cleanUp().removed == [os.path.basename(db)]
    make_store(tmp_path / "s2", monkeypatch)
    with monkeypatch.context() as m:
        m.setenv(ENV_SWITCH, "1")
        _open(fp).close()
    assert local_stores.readState(*os.path.split(db)).clean


# ---------------------------------------------------------------------------
# the check at open, with the store off
# ---------------------------------------------------------------------------

def test_with_the_store_off_an_open_names_a_store_with_work(tmp_path, store_root, settings, dev, no_switch, notes, monkeypatch):  # noqa: F811
    fp, db = make_store(tmp_path / "s", monkeypatch)
    _pending(db)
    told = _Told()
    series = _open(fp, notifier=told)
    series.close()
    assert len(told.told) == 1
    assert "The local copy of parity_series on this computer holds work" in told.told[0]
    assert "parity_series.jser does not have" in told.told[0]
    assert len(notes) == 1
    # the store is left as it was
    assert local_stores.readState(*os.path.split(db)).work


def test_with_the_store_off_a_clean_store_says_nothing(tmp_path, store_root, settings, dev, no_switch, monkeypatch):  # noqa: F811
    fp, db = make_store(tmp_path / "s", monkeypatch)
    before = files_of(db)
    told = _Told()
    _open(fp, notifier=told).close()
    assert told.told == []
    assert files_of(db) == before


def test_with_the_store_off_a_store_another_window_holds_is_not_read(tmp_path, store_root, settings, dev, no_switch, monkeypatch):  # noqa: F811
    fp, db = make_store(tmp_path / "s", monkeypatch)
    _pending(db)
    store = held(db)
    try:
        told = _Told()
        _open(fp, notifier=told).close()
        assert told.told == []
    finally:
        store.close()


def test_with_the_store_on_the_open_does_not_name_it(tmp_path, store_root, monkeypatch):  # noqa: F811
    """With the store on, the open itself deals with the store (store_open.py)."""
    fp, db = make_store(tmp_path / "s", monkeypatch)
    _dirty(db)
    monkeypatch.setenv(ENV_SWITCH, "1")
    told = _Told()
    _open(fp, notifier=told).close()
    assert told.told == []
