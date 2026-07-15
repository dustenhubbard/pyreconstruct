"""Transient-lock retry around the atomic file replace.

Background saves (a save fires on mouse-wheel scroll / section switch) hit
``os.replace``, which on Windows fails intermittently with WinError 5/32/33 when
antivirus/indexer/sync briefly locks the file. ``replace_with_retry`` must retry
those, must NOT retry genuine failures (e.g. a missing directory -> ENOENT), and
must re-raise the real error after exhausting its attempts.
"""
import errno

import pytest

from PyReconstruct.modules.backend.func import atomic_io
from PyReconstruct.modules.backend.func.atomic_io import (
    replace_with_retry,
    _is_retriable,
)

NO_SLEEP = lambda *_: None


def _win_error(code):
    e = OSError()
    e.winerror = code
    return e


def _posix_error(err):
    e = OSError()
    e.errno = err
    return e


def test_is_retriable_classification():
    assert _is_retriable(_win_error(5))     # access denied
    assert _is_retriable(_win_error(32))    # sharing violation
    assert _is_retriable(_win_error(33))    # lock violation
    assert not _is_retriable(_win_error(2))  # file not found -> real failure
    assert _is_retriable(_posix_error(errno.EACCES))
    assert not _is_retriable(_posix_error(errno.ENOENT))


def test_succeeds_first_try(monkeypatch):
    calls = []
    monkeypatch.setattr(atomic_io.os, "replace", lambda s, d: calls.append((s, d)))
    replace_with_retry("a.tmp", "a", _sleep=NO_SLEEP)
    assert calls == [("a.tmp", "a")]


def test_retries_transient_lock_then_succeeds(monkeypatch):
    seq = [_win_error(5), _win_error(32)]   # fail twice, then succeed
    n = {"i": 0}

    def flaky(src, dst):
        if n["i"] < len(seq):
            n["i"] += 1
            raise seq[n["i"] - 1]
        return None

    monkeypatch.setattr(atomic_io.os, "replace", flaky)
    sleeps = []
    replace_with_retry("a.tmp", "a", _sleep=sleeps.append)
    assert n["i"] == 2               # two failures survived
    assert sleeps == [0.1, 0.2]      # exponential backoff between them


def test_gives_up_and_raises_last_error(monkeypatch):
    def always_locked(src, dst):
        raise _win_error(5)

    monkeypatch.setattr(atomic_io.os, "replace", always_locked)
    with pytest.raises(OSError) as ei:
        replace_with_retry("a.tmp", "a", attempts=3, _sleep=NO_SLEEP)
    assert ei.value.winerror == 5    # the real error still surfaces


def test_does_not_retry_non_transient(monkeypatch):
    calls = {"n": 0}

    def missing_dir(src, dst):
        calls["n"] += 1
        raise _posix_error(errno.ENOENT)

    monkeypatch.setattr(atomic_io.os, "replace", missing_dir)
    with pytest.raises(OSError):
        replace_with_retry("a.tmp", "a", _sleep=NO_SLEEP)
    assert calls["n"] == 1           # ENOENT is not masked by retries
