"""Persistent log file for the packaged app (Qt-free).

The CLI launcher used to show stdout/stderr in a console; the packaged
(windowed) build discards them -- on frozen Windows ``sys.stdout``/``stderr``
can even be ``None`` -- so tracebacks and diagnostic prints vanished. This
module tees both streams to a per-user log file and exposes helpers to locate
and read it. Everything here is best-effort and never raises: logging must not
be able to crash the app.

Kept free of Qt so it can run at the very start of ``run.py``, before the
QApplication exists.
"""
import os
import sys
import datetime
from pathlib import Path

LOG_FILENAME = "pyreconstruct.log"
_MAX_BYTES = 2 * 1024 * 1024   # rotate the log once it exceeds ~2 MB
_installed = False             # idempotency guard (only tee once per process)


def log_dir() -> Path:
    """Per-user directory for the log file, created if missing.

    Windows -> %LOCALAPPDATA%/PyReconstruct/logs, macOS ->
    ~/Library/Logs/PyReconstruct, other -> $XDG_STATE_HOME/PyReconstruct/logs
    (default ~/.local/state).
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") \
            or str(Path.home() / "AppData" / "Local")
        d = Path(base) / "PyReconstruct" / "logs"
    elif sys.platform == "darwin":
        d = Path.home() / "Library" / "Logs" / "PyReconstruct"
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        d = Path(base) / "PyReconstruct" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file_path() -> Path:
    """Absolute path to the current log file (directory is created)."""
    return log_dir() / LOG_FILENAME


def _rotate_if_large(path: Path, max_bytes: int = _MAX_BYTES) -> None:
    """Keep the log bounded: once it exceeds ``max_bytes``, roll it to ``.1``."""
    try:
        if path.is_file() and path.stat().st_size > max_bytes:
            backup = path.with_suffix(path.suffix + ".1")
            os.replace(path, backup)   # single backup; overwrite any prior .1
    except OSError:
        pass


class _Tee:
    """Write-through stream: mirrors writes to a file and an optional console.

    Never raises -- a logging failure must not propagate into normal output.
    ``fileno``/``isatty`` defer to the console so a real terminal (source runs)
    keeps working for anything that inspects the stream.
    """

    def __init__(self, file_stream, console_stream=None):
        self._file = file_stream
        self._console = console_stream

    def write(self, s):
        for stream in (self._console, self._file):
            if stream is None:
                continue
            try:
                stream.write(s)
                stream.flush()
            except Exception:
                pass
        try:
            return len(s)
        except Exception:
            return 0

    def flush(self):
        for stream in (self._console, self._file):
            if stream is None:
                continue
            try:
                stream.flush()
            except Exception:
                pass

    def isatty(self):
        return bool(self._console is not None and getattr(self._console, "isatty", lambda: False)())

    def fileno(self):
        if self._console is not None and hasattr(self._console, "fileno"):
            return self._console.fileno()
        raise OSError("no console fileno")


def install_file_logging() -> Path:
    """Tee stdout/stderr to the per-user log file; return the log path.

    Idempotent (only the first call per process tees). Best-effort: if the log
    file cannot be opened, the streams are left untouched and the intended path
    is still returned so callers (e.g. the Help menu) can report it.
    """
    global _installed
    path = log_file_path()
    if _installed:
        return path
    try:
        _rotate_if_large(path)
        f = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return path   # can't log to file; leave stdout/stderr as-is

    _installed = True
    try:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        stamp = "?"
    try:
        version = _version_str()
        f.write(f"\n===== PyReconstruct launch {stamp} (v{version}) =====\n")
        f.flush()
    except Exception:
        pass

    sys.stdout = _Tee(f, sys.stdout)
    sys.stderr = _Tee(f, sys.stderr)
    return path


def _version_str() -> str:
    try:
        from PyReconstruct.modules.backend.updater.install_info import current_version_str
        return current_version_str()
    except Exception:
        return "?"


def read_log_tail(max_bytes: int = 200_000) -> str:
    """Return the last ``max_bytes`` of the log (whole file if smaller).

    Never raises; returns a friendly placeholder if the log is absent/empty.
    """
    path = log_file_path()
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return f"(no log yet at {path})"
        size = path.stat().st_size
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                data = f.read()
                return "…(truncated; showing the most recent output)…\n" + data
            return f.read()
    except OSError as e:
        return f"(could not read log at {path}: {e})"
