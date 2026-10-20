"""The local copy notice when the window resumes a working folder, with the store off.

The window's recovery offer (MainWindow._recoverUnsavedSeries) builds the
series from the working folder, so Series.openJser does not run. Taken with
Fast local copy off, it names this .jser's store as Series.openJser does
(local_stores.noteWorkAtOpen): a store with work, one another window holds,
and a set-aside store. Declined, the .jser opens and names it once. With the
store on, the resumed series takes its store (store_recovery.resumed) and
this notice is not given.
"""
import os
import sys

import pytest

from PyReconstruct.modules.datatypes import local_stores, store_open, store_recovery, store_save
from PyReconstruct.modules.datatypes import series as series_module

from test_hybrid_store import store_root  # noqa: F401  (fixture)
from test_local_stores import (  # noqa: F401  (fixture)
    _Told, _open, _pending, _set_aside, dev, held, make_store, no_switch, settings,
)

pytestmark = pytest.mark.gui


def _crashed(fp):
    """Open fp with the store off and leave its working folder, as a crash does;
    what that open told."""
    told = _Told()
    series = _open(fp, notifier=told)
    assert os.path.isdir(series.hidden_dir)
    return told.told


def _resume(window, fp, answer, monkeypatch):
    """The window's open of fp, with the recovery offer answered; (series, told)."""
    from PyReconstruct.modules.gui.main import main_window as mw

    monkeypatch.setattr(mw, "unsavedNotify", lambda *a, **k: answer)
    told = _Told()
    monkeypatch.setattr(series_module, "_NOTIFIER", told)
    return window._acquireSeries(str(fp)), told.told


@pytest.mark.parametrize("state", [
    "work",
    "in-use",
    pytest.param("set-aside", marks=pytest.mark.skipif(
        sys.platform == "win32",
        reason="on Windows a store with work is not set aside (store_recovery.setAside)",
    )),
])
def test_a_resumed_working_folder_names_the_store_as_an_open_does(
    state, tmp_path, store_root, settings, dev, no_switch, main_window, monkeypatch,  # noqa: F811
):
    fp, db = make_store(tmp_path / "s", monkeypatch)
    holder = None
    if state == "work":
        _pending(db)
    elif state == "in-use":
        holder = held(db)
    else:
        _set_aside(fp, db, monkeypatch)
    try:
        expected = _crashed(fp)
        assert len(expected) == 1
        resumed, told = _resume(main_window, fp, True, monkeypatch)
        assert isinstance(resumed, series_module.Series)
        assert resumed.hidden_dir == os.path.join(str(fp.parent), ".parity_series")
        assert told == expected
        resumed.close()
    finally:
        if holder is not None:
            holder.close()
    assert not os.path.isdir(os.path.join(str(fp.parent), ".parity_series"))


def test_a_declined_working_folder_names_the_store_once(
    tmp_path, store_root, settings, dev, no_switch, main_window, monkeypatch,  # noqa: F811
):
    fp, db = make_store(tmp_path / "s", monkeypatch)
    _pending(db)
    expected = _crashed(fp)
    opened, told = _resume(main_window, fp, False, monkeypatch)
    assert told == expected
    opened.close()


def test_with_the_store_on_a_resumed_working_folder_takes_its_store_not_this_notice(
    tmp_path, store_root, settings, dev, no_switch, main_window, monkeypatch,  # noqa: F811
):
    fp, db = make_store(tmp_path / "s", monkeypatch)
    _crashed(fp)
    monkeypatch.setenv(local_stores.ENV_SWITCH, "1")
    assert store_open.enabled()
    noted, resumes = [], []
    monkeypatch.setattr(local_stores, "noteWorkAtOpen", lambda *a, **k: noted.append(a))
    real = store_recovery.resumed
    monkeypatch.setattr(store_recovery, "resumed", lambda s, *a, **k: (resumes.append(s), real(s, *a, **k)))
    resumed, told = _resume(main_window, fp, True, monkeypatch)
    try:
        assert noted == []
        assert resumes == [resumed]
        assert told == []
    finally:
        store_save.release(resumed)
        resumed.close()

