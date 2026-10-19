"""The local stores on this computer as a whole: the setting, cleanup, and the check at open.

A store (hybrid_store.py) is a copy of a .jser kept so the series opens in
seconds (store_open.py). This module holds what is about every store, not
about one open:

  * the setting. Series > Options shows "Fast local copy for large series"
    in a Dev build only. PYRECON_HYBRID_STORE, when it is set, wins over the
    setting ("1" on, any other value off), for tests and benchmarks. A stable
    build reads the switch alone: the Dev and stable apps share one settings
    store, so the setting a Dev build wrote must not turn the store on there.
  * cleanup, at app start in the background and from the Options button. It
    removes clean stores and never any other file.
  * the check at open with the store off: a store that holds work its .jser
    lacks is named, so the work is not silently passed over.

A store is clean when what it records says it holds nothing its .jser lacks:

  * it is a store of this schema at the name `storePaths` gives it
    (<16 hex>.v1.pyrstore), a plain file, and no process holds its lock;
  * it holds no work: no working rows (pending_section, pending_series), it
    was not saved past its .jser (meta dirty is not 1), and its working
    folder (.work) holds no file;
  * once imported, its .jser is still at the path it records. A .jser that
    cannot be found now (a share not mounted, a disk not plugged in, a file
    moved or deleted) keeps its store.

The .jser is not hashed for this. A store with no work holds what its .jser
held when it was read, so a .jser saved since is ahead of the store, never
behind it. A store that cannot be read is not clean, so it is kept.

Cleanup removes a clean store not opened for MAX_AGE_DAYS, then, while the
folder is over SIZE_CAP, clean stores oldest first. Every removal takes the
store's own lock and reads the store again under it first. A file is removed
only by a name built from the store folder and a name of the store's own
shape (no separator, so no other folder), only when it is a plain file (a
link is never followed or removed), and the working folder only when it is
empty (os.rmdir).
"""

import os
import re
import sqlite3
import stat
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import hybrid_store
from .hybrid_store import (
    APPLICATION_ID, REQUIRED_TABLES, SCHEMA_VERSION, SQLITE_MAGIC, storePaths, storeRoot,
)

## Turns the store on ("1") or off (any other value), whatever the setting says
ENV_SWITCH = "PYRECON_HYBRID_STORE"
## The per-user setting (default_settings.py)
SETTING = "hybrid_store"
## meta: when the store was last opened (store_open.py writes it)
META_OPENED = "opened_utc"

MAX_AGE_DAYS = 30
SIZE_CAP = 20 * 1024 ** 3

_STORE = re.compile(rf"[0-9a-f]{{16}}\.v{SCHEMA_VERSION}\.pyrstore")
## a store's own files: the store, SQLite's side files, the file `_create`
## writes first and its journal, and the lock
_STORE_FILE = re.compile(
    rf"[0-9a-f]{{16}}\.v{SCHEMA_VERSION}\.pyrstore"
    r"(-wal|-shm|-journal|\.new|\.new-journal|\.lock)?"
)
_WORK_DIR = re.compile(rf"[0-9a-f]{{16}}\.v{SCHEMA_VERSION}\.work")
## removed in this order: SQLite's side files before the store, so a removal
## cut short leaves a whole store or none (a WAL with no store beside it
## would make `HybridStore._create` refuse that series for good)
_SIDE_FILES = ("-wal", "-shm", "-journal", ".new-journal", ".new")

## why a store is kept, as the Options button reports it
WORK = "holds work its .jser lacks"
IN_USE = "is open in PyReconstruct"
NO_JSER = "its .jser was not found"
UNREADABLE = "could not be read"


def log_note(message : str):
    """One line in the app's log (logging_setup.py)."""
    # backend.func's package imports this one's, so not at the top
    from PyReconstruct.modules.backend.func.logging_setup import log_note as note
    note(message)


## ---------------------------------------------------------------------------
## the setting
## ---------------------------------------------------------------------------

def enabled() -> bool:
    """True when the store is on: the switch when it is set, else the setting."""
    value = os.environ.get(ENV_SWITCH)
    if value is not None:
        return value == "1"
    return settingOn()


def settingOn() -> bool:
    """True when the setting is on and this is a Dev build.

    A process with no Qt loaded (a script opening a series headless) reads
    the switch alone: the stored settings are Qt's, and the core opens a
    series without loading Qt (tests/test_qt_free_core.py). The app loads
    Qt before it opens anything, and a script can pass its own store.
    """
    from PyReconstruct.modules.constants import build_flavor
    if not build_flavor.is_dev_build():
        return False
    from PyReconstruct.modules.backend.settings_store import (
        QSettingsStore, default_settings_store,
    )
    store = default_settings_store()
    if isinstance(store, QSettingsStore) and "PySide6.QtCore" not in sys.modules:
        return False
    if not store.contains(None, SETTING):
        return False
    return store.value(None, SETTING, bool) in (True, "true", 1, "1")


def setSetting(series, on : bool):
    """Store the setting, from the Options dialog.

    Turning it off leaves every store as it is: cleanup removes the clean
    ones in time, and one that holds work is named at each open of its
    series (`noteWorkAtOpen`) and never removed by cleanup.
    """
    series.setOption(SETTING, bool(on))


def switchIsSet() -> bool:
    """True when PYRECON_HYBRID_STORE is set, so the setting decides nothing."""
    return os.environ.get(ENV_SWITCH) is not None


## ---------------------------------------------------------------------------
## reading a store's record
## ---------------------------------------------------------------------------

@dataclass
class StoreState:
    """What one store records, read under its lock."""
    name : str
    clean : bool = False
    work : bool = False
    why : str = ""            # why it is kept, when it is not clean
    last_used : float = 0.0   # POSIX time
    size : int = 0            # bytes, every file of the store


@dataclass
class CleanupReport:
    removed : list = field(default_factory=list)   # store file names
    kept : list = field(default_factory=list)      # (store file name, why)
    freed : int = 0                                # bytes


def _lockedStore(db_fp : str):
    """The store's lock fd, or None when another holder has it.

    The lock HybridStore takes for every open, so a store being opened or
    imported is never read or removed here.
    """
    return hybrid_store._lockFile(db_fp + ".lock")


def _release(fd, lock_fp : str | None = None):
    """Let go of a store's lock, removing its lock file when lock_fp is given.

    Off Windows the file is removed while the lock is held, so no other
    opener can take this lock file between the two. Windows will not remove
    a file that is open, so there it is closed first.
    """
    try:
        if lock_fp is not None and sys.platform != "win32":
            _removeFile(*os.path.split(lock_fp))
    finally:
        os.close(fd)
    if lock_fp is not None and sys.platform == "win32":
        _removeFile(*os.path.split(lock_fp))


def _seconds(utc):
    try:
        return datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _text(value):
    """A meta value as text (setMeta writes UTF-8 bytes)."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "surrogatepass")
    return value


def _storeSize(root : str, name : str) -> int:
    total = 0
    for suffix in ("", *_SIDE_FILES, ".lock"):
        try:
            st = os.lstat(os.path.join(root, name + suffix))
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            total += st.st_size
    return total


def _readState(root : str, name : str) -> StoreState:
    """Read one store's record. The caller holds its lock."""
    state = StoreState(name)
    db_fp = os.path.join(root, name)
    work_dir = os.path.join(root, name[:-len(".pyrstore")] + ".work")
    try:
        st = os.lstat(db_fp)
        if not stat.S_ISREG(st.st_mode):
            state.why = UNREADABLE
            return state
        state.size = _storeSize(root, name)
        state.last_used = st.st_mtime
        with open(db_fp, "rb") as f:
            header = f.read(100)
        if (
            len(header) < 100 or not header.startswith(SQLITE_MAGIC)
            or int.from_bytes(header[68:72], "big") != APPLICATION_ID
            or int.from_bytes(header[60:64], "big") != SCHEMA_VERSION
        ):
            state.why = UNREADABLE
            return state
        # mode=rw: a store that is gone is not made again by reading it
        con = sqlite3.connect(Path(db_fp).as_uri() + "?mode=rw", uri=True, timeout=1)
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES <= tables:
                state.why = UNREADABLE
                return state
            meta = {k: _text(v) for k, v in con.execute("SELECT key, value FROM meta")}
            pending = bool(
                con.execute("SELECT 1 FROM pending_section LIMIT 1").fetchone()
                or con.execute("SELECT 1 FROM pending_series LIMIT 1").fetchone()
            )
        finally:
            con.close()
        # the last open; a store from before opens were recorded: when it was
        # filled, else made; else the file's own time
        for key in (META_OPENED, "imported_utc", "created_utc"):
            when = _seconds(meta.get(key))
            if when is not None:
                state.last_used = when
                break
        work_files = False
        if os.path.lexists(work_dir):
            wst = os.lstat(work_dir)
            if not stat.S_ISDIR(wst.st_mode):
                state.why = UNREADABLE
                return state
            with os.scandir(work_dir) as entries:
                work_files = any(True for _ in entries)
        state.work = pending or meta.get("dirty") == "1" or work_files
        if state.work:
            state.why = WORK
            return state
        jser = meta.get("jser_path")
        if meta.get("imported_utc") is not None and not (jser and os.path.isfile(jser)):
            state.why = NO_JSER
            return state
        state.clean = True
        return state
    except (OSError, sqlite3.Error) as e:
        state.why = UNREADABLE
        log_note(f"Local copy {name} could not be read: {e}")
        return state


def readState(root : str, name : str) -> StoreState:
    """One store's record, read under its lock (released after)."""
    fd = _lockedStore(os.path.join(root, name))
    if fd is None:
        return StoreState(name, why=IN_USE)
    try:
        return _readState(root, name)
    finally:
        os.close(fd)


## ---------------------------------------------------------------------------
## removing a store
## ---------------------------------------------------------------------------

def _removeFile(root : str, name : str):
    """Remove root/name when it is a plain file of a store; nothing else.

    root is the store folder and name must be a store file's own name, which
    holds no separator, so no path outside the folder can be reached. A link
    is never followed or removed. A file that is not there is fine.
    """
    if not _STORE_FILE.fullmatch(name):
        raise ValueError(f"not a local store file: {name!r}")
    fp = os.path.join(root, name)
    try:
        st = os.lstat(fp)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(st.st_mode):
        raise OSError(f"{fp} is not a plain file; it was left as it is")
    os.unlink(fp)


def _removeWorkDir(root : str, name : str):
    """Remove a store's working folder when it is an empty folder; nothing else."""
    if not _WORK_DIR.fullmatch(name):
        raise ValueError(f"not a local store folder: {name!r}")
    fp = os.path.join(root, name)
    try:
        st = os.lstat(fp)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(st.st_mode):
        raise OSError(f"{fp} is not a folder; it was left as it is")
    os.rmdir(fp)  # refuses a folder with anything in it


def removeIfClean(root : str, name : str) -> StoreState:
    """Remove one store if it is clean, read again under its lock.

    Returns its state; `clean` is True only when it was removed.
    """
    if not _STORE.fullmatch(name):
        raise ValueError(f"not a local store: {name!r}")
    db_fp = os.path.join(root, name)
    fd = _lockedStore(db_fp)
    if fd is None:
        return StoreState(name, why=IN_USE)
    lock_fp : str | None = None
    try:
        state = _readState(root, name)
        if not state.clean:
            return state
        try:
            for suffix in _SIDE_FILES:
                _removeFile(root, name + suffix)
            _removeFile(root, name)
            _removeWorkDir(root, name[:-len(".pyrstore")] + ".work")
        except OSError as e:
            log_note(f"Local copy {name} was not fully removed: {e}")
            return StoreState(name, why=UNREADABLE, size=state.size, last_used=state.last_used)
        lock_fp = db_fp + ".lock"
        return state
    finally:
        try:
            _release(fd, lock_fp)
        except OSError:
            pass


## ---------------------------------------------------------------------------
## the folder
## ---------------------------------------------------------------------------

def storeFolder():
    """The real path of the store folder, or None when it does not exist.

    Never makes the folder: with no store, nothing here writes anything.
    """
    root = storeRoot()
    if not os.path.isdir(root):
        return None
    return os.path.realpath(root)


def storeNames(root : str) -> list:
    """The names of the stores in root, sorted; no other file."""
    with os.scandir(root) as entries:
        return sorted(e.name for e in entries if _STORE.fullmatch(e.name))


def folderSize() -> int:
    """Bytes in the store folder, every plain file in it; links are not followed."""
    root = storeFolder()
    if root is None:
        return 0
    total = 0
    pending = [root]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for e in entries:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            pending.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def cleanUp(now : float | None = None, max_age_days : float = MAX_AGE_DAYS, cap : int = SIZE_CAP) -> CleanupReport:
    """The cleanup rule: old clean stores, then clean stores oldest first while over the cap."""
    report = CleanupReport()
    root = storeFolder()
    if root is None:
        return report
    if now is None:
        now = datetime.now(timezone.utc).timestamp()
    states = [readState(root, name) for name in storeNames(root)]
    total = folderSize()
    for s in states:
        if not s.clean:
            report.kept.append((s.name, s.why))
    # oldest first: every old one, then more while the folder is over the cap
    for s in sorted((s for s in states if s.clean), key=lambda s: s.last_used):
        old = now - s.last_used > max_age_days * 86400
        if not old and total <= cap:
            report.kept.append((s.name, ""))
            continue
        done = removeIfClean(root, s.name)
        if done.clean:
            report.removed.append(s.name)
            report.freed += done.size
            total -= done.size
        else:
            report.kept.append((s.name, done.why))
    return report


def removeClean() -> CleanupReport:
    """Remove every clean store (the Options button)."""
    report = CleanupReport()
    root = storeFolder()
    if root is None:
        return report
    for name in storeNames(root):
        done = removeIfClean(root, name)
        if done.clean:
            report.removed.append(name)
            report.freed += done.size
        else:
            report.kept.append((name, done.why))
    return report


def _cleanUpAndLog():
    try:
        report = cleanUp()
    except Exception as e:  # a background thread: nothing above it to report to
        log_note(f"Local copy cleanup stopped: {e!r}")
        return
    if report.removed:
        log_note(
            f"Removed {len(report.removed)} unused local "
            f"cop{'y' if len(report.removed) == 1 else 'ies'} ({report.freed} bytes)"
        )


def startCleanup():
    """Run cleanup once in the background, at app start.

    With no store folder nothing starts: one look for the folder, and no file
    is read or written. Returns the thread, or None.
    """
    if storeFolder() is None:
        return None
    thread = threading.Thread(target=_cleanUpAndLog, name="local-store-cleanup", daemon=True)
    thread.start()
    return thread


## ---------------------------------------------------------------------------
## the check at open, with the store off
## ---------------------------------------------------------------------------

def noteWorkAtOpen(jser_fp : str, notifier=None) -> bool:
    """With the store off, say so when this .jser's store holds work the .jser lacks.

    One look for the series' store file; only a store that is there is read.
    A store another window holds is that window's, and is not read. Returns
    True when the user was told.
    """
    try:
        db_fp, _ = storePaths(jser_fp)
    except OSError:
        return False
    if not os.path.isfile(db_fp):
        return False
    state = readState(*os.path.split(db_fp))
    if not state.work:
        return False
    name = os.path.splitext(os.path.basename(jser_fp))[0]
    log_note(f"Local copy of {name} holds work its .jser lacks; opened the .jser ({db_fp})")
    message = (
        f"The local copy of {name} on this computer holds work that "
        f"{name}.jser does not have.\n\n"
        f"Fast local copy is off, so this opens the .jser. "
        f"The local copy is kept, and cleanup never removes it."
    )
    if notifier is None:
        from .series import _default_notifier
        notifier = _default_notifier()
    try:
        notifier.notify(message)
    except Exception as e:
        log_note(f"Could not show the local copy notice: {e!r}")
    return True
