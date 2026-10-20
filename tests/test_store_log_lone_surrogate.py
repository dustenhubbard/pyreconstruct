"""A series whose log names an object with a lone surrogate, with the store on.

The log keeps such a name as the bytes "surrogatepass" writes (log.py). With
PYRECON_HYBRID_STORE=1 the first open keeps the working folder in the store.
It read existing_log.csv as strict UTF-8, so the open raised. SQLite text
cannot take a lone surrogate either, so the store keeps such a log as its
UTF-8 bytes, as it keeps names.

What these pin: the name is in the log after the first open, after an open
from the store, after a Save in either mode, after the close that writes the
.jser, after a reopen with the switch on or off, and after a crash the store's
Save is recovered from.
"""
import shutil

import pytest

from PyReconstruct.modules.datatypes import store_open, store_save
from PyReconstruct.modules.datatypes.hybrid_store import HybridStore
from PyReconstruct.modules.datatypes.log import LOG_READ_ERRORS, LOG_WRITE_ERRORS
from PyReconstruct.modules.datatypes.series import Series

from test_hybrid_store import PARITY, store_root  # noqa: F401  (fixture)
from test_store_open import _Asked, _copy, _open, _store_opens
from test_store_open import notes, switch_on  # noqa: F401  (fixture)
from test_store_save import log_clock  # noqa: F401  (fixture)

NAME = "axon_\ud800_1"


@pytest.fixture(params=[store_save.MODE_JSER, store_save.MODE_STORE])
def mode(request, monkeypatch):
    monkeypatch.setenv(store_save.ENV_MODE, request.param)
    return request.param


@pytest.fixture
def renamed(tmp_path, store_root, monkeypatch):  # noqa: F811
    """A .jser whose log names NAME: renamed and saved with the switch off."""
    monkeypatch.setattr(Series, "user", property(lambda self: "alice"))
    fp = _copy(PARITY, tmp_path / "s")
    with monkeypatch.context() as m:
        m.delenv(store_open.ENV_SWITCH, raising=False)
        series = _open(fp)
        old = sorted(series.data["objects"])[0]
        series.editObjectAttributes([old], name=NAME)
        series.saveJser(close=True)
    assert not store_root.exists()
    return fp


def _names(series):
    return [log.obj_name for log in series.getFullHistory().all_logs]


def _close(series):
    series.leave_open = False
    series.close()


def _reopened_names(fp, monkeypatch, switch):
    with monkeypatch.context() as m:
        if switch:
            m.setenv(store_open.ENV_SWITCH, "1")
        else:
            m.delenv(store_open.ENV_SWITCH, raising=False)
        series = _open(fp)
        try:
            return _names(series)
        finally:
            _close(series)


def test_the_first_open_keeps_the_store_and_the_next_comes_from_it(renamed, switch_on, notes, monkeypatch):  # noqa: F811
    series = _open(renamed)
    try:
        assert store_save.heldStore(series) is not None
        assert NAME in _names(series)
    finally:
        _close(series)
    assert not [n for n in notes if "not kept" in n]
    opens = _store_opens(monkeypatch)
    series = _open(renamed)
    try:
        assert opens == [series.name]
        assert NAME in _names(series)
    finally:
        _close(series)


def test_the_store_keeps_the_log_as_its_bytes(renamed, switch_on):  # noqa: F811
    _close(_open(renamed))
    store = HybridStore.forJser(str(renamed))
    try:
        raw = store.con.execute("SELECT text FROM log").fetchone()[0]
        assert NAME.encode("utf-8", "surrogatepass") in raw
        assert NAME in store.logText()
    finally:
        store.close()


def test_a_log_without_a_surrogate_is_kept_as_text(tmp_path, switch_on):  # noqa: F811
    fp = _copy(PARITY, tmp_path / "s")
    _close(_open(fp))
    store = HybridStore.forJser(str(fp))
    try:
        assert store.con.execute("SELECT typeof(text) FROM log").fetchone()[0] == "text"
    finally:
        store.close()


def test_the_name_survives_save_close_and_reopen(renamed, mode, switch_on, notes, monkeypatch):  # noqa: F811
    _close(_open(renamed))  # the store holds it
    series = _open(renamed)
    series.editObjectAttributes([NAME], color=(1, 2, 3))
    if not series.saveToStore():
        series.saveJser()
    if mode == store_save.MODE_STORE:
        assert store_save.ahead(series)
    _close(series)  # in "store" mode the close writes the .jser
    assert not [n for n in notes if "not kept" in n or "not the local store" in n]
    opens = _store_opens(monkeypatch)
    for switch in (True, False):
        names = _reopened_names(renamed, monkeypatch, switch)
        assert names.count(NAME) >= 2  # the rename and the color edit
        assert not any("�" in (n or "") for n in names)
    assert len(opens) == 1  # the reopen with the switch on came from the store


def test_a_store_save_is_recovered_after_a_crash(renamed, switch_on, notes, monkeypatch):  # noqa: F811
    monkeypatch.setenv(store_save.ENV_MODE, store_save.MODE_STORE)
    _close(_open(renamed))
    series = _open(renamed)
    series.editObjectAttributes([NAME], color=(1, 2, 3))
    assert series.saveToStore() is True
    # a crash: the store let go of, the working folder declined
    store_save.release(series)
    series.leave_open = True
    series.close()
    shutil.rmtree(renamed.parent / f".{renamed.stem}")

    asker = _Asked(answer=True)
    series = _open(renamed, notifier=asker)
    try:
        assert len(asker.asked) == 1
        assert _names(series).count(NAME) >= 2
    finally:
        _close(series)
    assert _reopened_names(renamed, monkeypatch, switch=False).count(NAME) >= 2


def test_the_store_commit_reads_the_log_back_as_written(renamed, switch_on):  # noqa: F811
    series = _open(renamed)
    try:
        store = store_save.heldStore(series).store
        log_fp = f"{series.getwdir()}/existing_log.csv"
        with open(log_fp, "r", encoding="utf-8", errors=LOG_READ_ERRORS) as f:
            text = f.read()
        with open(log_fp, "w", encoding="utf-8", errors=LOG_WRITE_ERRORS) as f:
            f.write(text + f"26-10-19, 12:00, alice, {NAME}, 1, Modify object\n")
        store.commit(series)
        assert store.logText().count(NAME) == text.count(NAME) + 1
    finally:
        _close(series)
