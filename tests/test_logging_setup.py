"""Persistent log file for the packaged app.

The packaged (windowed) build has no console, so stdout/stderr -- tracebacks and
diagnostic prints -- are teed to a per-user log file that Help > View log file
surfaces. These pin the Qt-free core: where the log lives, that teeing actually
captures output, size-bounding, tail reading, and that setup never raises.
"""
import sys
import importlib

import PyReconstruct.modules.backend.func.logging_setup as ls


def _fresh_module(monkeypatch, tmp_path):
    """Reload logging_setup with a temp log dir and the install guard reset."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # Windows/mac branches read HOME-based paths; force the XDG branch for the
    # test regardless of host platform.
    monkeypatch.setattr(sys, "platform", "linux")
    mod = importlib.reload(ls)
    return mod


def test_log_dir_is_under_state_home_and_created(monkeypatch, tmp_path):
    mod = _fresh_module(monkeypatch, tmp_path)
    d = mod.log_dir()
    assert str(d).startswith(str(tmp_path))
    assert d.is_dir()
    assert mod.log_file_path().name == "pyreconstruct.log"


def test_install_tees_stdout_to_file(monkeypatch, tmp_path):
    mod = _fresh_module(monkeypatch, tmp_path)
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        path = mod.install_file_logging()
        print("hello-log-marker")
        sys.stdout.flush()
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
    assert "hello-log-marker" in path.read_text(encoding="utf-8")
    assert "PyReconstruct launch" in path.read_text(encoding="utf-8")  # session header


def test_install_is_idempotent(monkeypatch, tmp_path):
    mod = _fresh_module(monkeypatch, tmp_path)
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        mod.install_file_logging()
        teed = sys.stdout
        mod.install_file_logging()          # second call must not re-wrap
        assert sys.stdout is teed
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err


def test_rotation_when_oversized(monkeypatch, tmp_path):
    mod = _fresh_module(monkeypatch, tmp_path)
    path = mod.log_file_path()
    path.write_text("x" * 10, encoding="utf-8")
    mod._rotate_if_large(path, max_bytes=5)
    assert path.with_suffix(".log.1").is_file()   # rolled to backup
    assert not path.is_file()                      # original moved aside


def test_read_log_tail_truncates_to_recent(monkeypatch, tmp_path):
    mod = _fresh_module(monkeypatch, tmp_path)
    path = mod.log_file_path()
    path.write_text("OLD" + ("y" * 1000) + "RECENT_TAIL", encoding="utf-8")
    tail = mod.read_log_tail(max_bytes=20)
    assert "RECENT_TAIL" in tail and "OLD" not in tail
    assert "truncated" in tail


def test_read_log_tail_handles_missing_log(monkeypatch, tmp_path):
    mod = _fresh_module(monkeypatch, tmp_path)
    assert "no log yet" in mod.read_log_tail()


def test_install_never_raises_when_dir_unwritable(monkeypatch, tmp_path):
    mod = _fresh_module(monkeypatch, tmp_path)
    # force the open to fail; install must swallow it and leave streams intact
    monkeypatch.setattr(mod, "log_file_path", lambda: tmp_path / "nope" / "x.log")
    saved_out = sys.stdout
    try:
        path = mod.install_file_logging()   # parent dir missing -> open fails
        assert sys.stdout is saved_out       # streams untouched on failure
        assert path == tmp_path / "nope" / "x.log"
    finally:
        sys.stdout = saved_out
