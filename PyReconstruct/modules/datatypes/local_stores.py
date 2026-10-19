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
store's own lock and reads the store again under it first, and removes it
only when it is still clean and still due (an open since the scan makes it
recent). A file is removed only by a name of the store's own shape (no
separator, so no other folder), only when it is a plain file when looked at
(removing a name never touches what a link points at), and the working folder
only when it is empty (os.rmdir). Off Windows the store folder is held open
and every lock and removal goes through it (dir_fd), so a folder moved or
swapped for a link meanwhile is never reached through its path; on Windows a
folder with an open file in it cannot be moved. The lock file is never
removed: an opener that had opened it before the removal would lock the
removed file while the next opener locks a new one, and both would hold the
store.
"""

import os
import re
import sqlite3
import stat
import sys
import threading
from contextlib import contextmanager
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
## the files of a store cleanup removes: the store, SQLite's side files, and
## the file `_create` writes first and its journal; never the lock
_STORE_FILE = re.compile(
    rf"[0-9a-f]{{16}}\.v{SCHEMA_VERSION}\.pyrstore"
    r"(-wal|-shm|-journal|\.new|\.new-journal)?"
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
    return _isOn(store)


def _isOn(store) -> bool:
    if not store.contains(None, SETTING):
        return False
    return store.value(None, SETTING, bool) in (True, "true", 1, "1")


def storedSetting(series) -> bool:
    """The setting as stored for the Options dialog; False when never set.

    Reads only: `Series.getOption` stores the default of an option it does
    not find, and the dialog writes nothing before OK.
    """
    return _isOn(series._settingsStore())


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


## os.open, os.stat (and so os.lstat), os.unlink and os.rmdir take dir_fd
## (not on Windows)
_DIR_FD = {os.open, os.stat, os.unlink, os.rmdir} <= os.supports_dir_fd


class _Folder:
    """The store folder as cleanup found it: held open off Windows.

    `path(name)` is the name to pass with `dir_fd=fd`: the bare name when the
    folder is held open, so the call reaches the held folder whatever is at
    its path now, else the full path.
    """

    def __init__(self, root : str):
        self.root = root
        self.fd = None
        if _DIR_FD:
            self.fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def path(self, name : str) -> str:
        return name if self.fd is not None else os.path.join(self.root, name)

    def same(self) -> bool:
        """True while the folder's path still names the folder held open."""
        if self.fd is None:
            return True
        try:
            at_path = os.lstat(self.root)
        except OSError:
            return False
        held = os.fstat(self.fd)
        return (at_path.st_dev, at_path.st_ino) == (held.st_dev, held.st_ino)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


@contextmanager
def _held(root : str, folder : _Folder | None):
    """folder when the caller holds one, else the folder at root, for this call."""
    if folder is not None:
        yield folder
        return
    folder = _Folder(root)
    try:
        yield folder
    finally:
        folder.close()


def _lockedStore(folder : _Folder, name : str):
    """The store's lock fd, or None when another holder has it.

    The lock HybridStore takes for every open, so a store being opened or
    imported is never read or removed here.
    """
    return hybrid_store._lockFile(folder.path(name + ".lock"), dir_fd=folder.fd)


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
        # mode=rw: a store that is gone is not made again by reading it.
        # A file URI needs a full path (the folder may be set relative).
        con = sqlite3.connect(Path(os.path.abspath(db_fp)).as_uri() + "?mode=rw", uri=True, timeout=1)
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


def readState(root : str, name : str, folder : _Folder | None = None) -> StoreState:
    """One store's record, read under its lock (released after)."""
    with _held(root, folder) as folder:
        try:
            fd = _lockedStore(folder, name)
        except OSError as e:
            log_note(f"Local copy {name} could not be locked: {e}")
            return StoreState(name, why=UNREADABLE)
        if fd is None:
            return StoreState(name, why=IN_USE)
        try:
            return _readState(root, name)
        finally:
            os.close(fd)


## ---------------------------------------------------------------------------
## removing a store
## ---------------------------------------------------------------------------

def _removeFile(folder : _Folder, name : str):
    """Remove a plain file of a store from the folder; nothing else.

    name must be a store file's own name, which holds no separator, so no
    other folder can be reached. A link is never followed: removing a name
    removes that name only. A file that is not there is fine.
    """
    if not _STORE_FILE.fullmatch(name):
        raise ValueError(f"not a local store file: {name!r}")
    fp = folder.path(name)
    try:
        st = os.lstat(fp, dir_fd=folder.fd)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(st.st_mode):
        raise OSError(f"{name} is not a plain file; it was left as it is")
    os.unlink(fp, dir_fd=folder.fd)


def _removeWorkDir(folder : _Folder, name : str):
    """Remove a store's working folder when it is an empty folder; nothing else."""
    if not _WORK_DIR.fullmatch(name):
        raise ValueError(f"not a local store folder: {name!r}")
    fp = folder.path(name)
    try:
        st = os.lstat(fp, dir_fd=folder.fd)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(st.st_mode):
        raise OSError(f"{name} is not a folder; it was left as it is")
    os.rmdir(fp, dir_fd=folder.fd)  # refuses a folder with anything in it


def removeIfClean(root : str, name : str, folder : _Folder | None = None, due=None) -> StoreState:
    """Remove one store if it is clean, read again under its lock.

    due, when given, is asked again of the state read under the lock: a store
    opened since the caller looked is no longer due. Returns its state;
    `clean` is True only when it was removed.
    """
    if not _STORE.fullmatch(name):
        raise ValueError(f"not a local store: {name!r}")
    with _held(root, folder) as folder:
        try:
            fd = _lockedStore(folder, name)
        except OSError as e:
            log_note(f"Local copy {name} could not be locked: {e}")
            return StoreState(name, why=UNREADABLE)
        if fd is None:
            return StoreState(name, why=IN_USE)
        try:
            # what is read is what is removed: the folder at root is still
            # the one held open, before the read and after it
            state = _readState(root, name) if folder.same() else None
            if state is None or (state.clean and not folder.same()):
                log_note(f"Local copy {name} was kept: the store folder moved while it was read")
                return StoreState(name, why=UNREADABLE)
            if not state.clean:
                return state
            if due is not None and not due(state):
                state.clean = False
                return state
            try:
                for suffix in _SIDE_FILES:
                    _removeFile(folder, name + suffix)
                _removeFile(folder, name)
                _removeWorkDir(folder, name[:-len(".pyrstore")] + ".work")
            except OSError as e:
                log_note(f"Local copy {name} was not fully removed: {e}")
                return StoreState(name, why=UNREADABLE, size=state.size, last_used=state.last_used)
            return state
        finally:
            os.close(fd)


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
    with _held(root, None) as folder:
        states = [readState(root, name, folder) for name in storeNames(root)]
        total = folderSize()

        def due(s):
            return now - s.last_used > max_age_days * 86400 or total > cap

        for s in states:
            if not s.clean:
                report.kept.append((s.name, s.why))
        # oldest first: every old one, then more while the folder is over the cap
        for s in sorted((s for s in states if s.clean), key=lambda s: s.last_used):
            if not due(s):
                report.kept.append((s.name, ""))
                continue
            done = removeIfClean(root, s.name, folder, due)
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
    with _held(root, None) as folder:
        for name in storeNames(root):
            done = removeIfClean(root, name, folder)
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
        if not os.path.isfile(db_fp):
            return False
        # the folder's real, full path, as cleanup reads it (storeFolder)
        root, store_name = os.path.split(db_fp)
        root = os.path.realpath(root)
        db_fp = os.path.join(root, store_name)
        state = readState(root, store_name)
    except (OSError, ValueError) as e:
        # a notice only: the open goes on whatever happens here
        log_note(f"Could not look for a local copy of {jser_fp}: {e!r}")
        return False
    if not state.work:
        return False
    name = os.path.splitext(os.path.basename(jser_fp))[0]
    log_note(f"Local copy of {name} holds work its .jser lacks; it was not used ({db_fp})")
    # true whichever way the open goes: the .jser, or the working folder
    # (the hidden folder beside it) a session left
    message = (
        f"The local copy of {name} on this computer holds work that "
        f"{name}.jser does not have.\n\n"
        f"Fast local copy is off, so this open does not use it. "
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
