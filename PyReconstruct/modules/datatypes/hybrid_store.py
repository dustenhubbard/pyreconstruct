"""A local SQLite working store for a series.

Nothing in PyReconstruct calls this module yet. It is the storage layer alone:
the schema, the import of a .jser, reading sections back, the working layer and
the Save that folds it in, the lock, where a store lives, and the refusal of a
network folder. Opening, saving and exporting through it come later, each on
its own.

What a store holds, for one .jser:

  * ``series``, ``log``: the .ser JSON and the existing_log.csv text, as an
    open writes them into the hidden folder today;
  * ``section``: each section's header (the section JSON with its ordered
    contour names in place of the contours);
  * ``trace``: one row per trace, with x then y as one float64 blob when every
    coordinate is a float, else the whole row as JSON, so nothing is coerced;
  * ``pending_section``, ``pending_series``: unsaved work, the job the hidden
    folder's files do today. ``commit`` folds them into the saved tables.

The import runs the reader's own migration (``Series._readJserForOpen``,
``Section.updateJSON``, ``Series.updateJSON``), so a store holds what today's
open writes into the hidden folder, never what a second parser reads.

A store lives in a per-user folder on local disk, never beside the .jser:
SQLite is not safe on a network share, where lab series often live.
"""

import os
import sys
import hashlib
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from PyReconstruct.modules.constants import fast_loads, fast_dumps

## Moves the folder that holds every store (tests and benchmarks)
ENV_DIR = "PYRECON_HYBRID_STORE_DIR"
BUSY_TIMEOUT_MS = 5000
## A store's schema is never changed in place: a new schema is a new store
## file, built from the .jser. So a store's version is in its file header
## from the day it is made, and the header alone says whose and which it is.
SCHEMA_VERSION = 1
## Marks a SQLite file as a store (PRAGMA application_id; "PyRS")
APPLICATION_ID = 0x50795253
SQLITE_MAGIC = b"SQLite format 3\x00"
REQUIRED_TABLES = {"meta", "series", "log", "section", "trace", "pending_section", "pending_series"}

## File systems a SQLite file must not sit on (Linux names, /proc/self/mountinfo)
NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "9p", "afs"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS series(id INTEGER PRIMARY KEY CHECK (id = 1), data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY CHECK (id = 1), text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS section(
    snum INTEGER PRIMARY KEY,
    header BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS trace(
    id INTEGER PRIMARY KEY,
    snum INTEGER NOT NULL,
    cpos INTEGER NOT NULL,
    ord INTEGER NOT NULL,
    name TEXT NOT NULL,
    shape INTEGER NOT NULL,
    npts INTEGER NOT NULL,
    xy BLOB,
    rest BLOB NOT NULL,
    xmin REAL, ymin REAL, xmax REAL, ymax REAL
);
CREATE INDEX IF NOT EXISTS trace_by_section ON trace(snum, cpos, ord);
CREATE INDEX IF NOT EXISTS trace_by_object ON trace(name, snum);
CREATE TABLE IF NOT EXISTS pending_section(snum INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE IF NOT EXISTS pending_series(id INTEGER PRIMARY KEY CHECK (id = 1), data BLOB NOT NULL);
"""

TRACE_COLS = "snum, cpos, ord, name, shape, npts, xy, rest, xmin, ymin, xmax, ymax"


class StoreBusyError(OSError):
    """Another process holds the store. Never a sign of damage."""


class StoreSchemaError(OSError):
    """The file is not a store this build can read: another schema, or not a store."""


class StoreSaveError(OSError):
    """Save would leave the store naming a section it does not hold."""


IN_USE = (
    "This series is open in another PyReconstruct window (or another program "
    "is saving it). Close it there first."
)


def _isBusy(err : Exception) -> bool:
    text = str(err).lower()
    return "locked" in text or "busy" in text


def _lockFile(path : str):
    """Hold an exclusive lock on path for the life of the process, or None.

    The operating system drops the lock when the process ends, so a crash
    never leaves a series locked.
    """
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def storeRoot() -> Path:
    """The per-user local folder that holds every store.

    A data folder, not a cache folder, so a system cache sweep leaves it alone.
    """
    override = os.environ.get(ENV_DIR)
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "PyReconstruct" / "stores"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PyReconstruct" / "stores"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "PyReconstruct" / "stores"


## pathconf name for case sensitivity on macOS (<sys/unistd.h>); Python's
## table does not list it
_PC_CASE_SENSITIVE = 11


def _diskSpelling(folder : str):
    """An existing folder's path as each disk on it stores the names (macOS), or None."""
    import fcntl
    getpath = getattr(fcntl, "F_GETPATH", None)
    if getpath is None:
        return None
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return None
    try:
        return os.fsdecode(fcntl.fcntl(fd, getpath, bytes(1024)).split(b"\0", 1)[0])
    except OSError:
        return None
    finally:
        os.close(fd)


def _ignoresCase(folder : str) -> bool:
    """True only when the disk holding folder is known to ignore case (macOS)."""
    try:
        return os.pathconf(folder, _PC_CASE_SENSITIVE) == 0
    except (OSError, ValueError):
        return False


def canonicalPath(fp : str) -> str:
    """One spelling of fp for every name of the same file, existing or not.

    `os.path.realpath` resolves links but keeps the case it was given. On
    macOS the nearest folder that exists is spelled as its disks store the
    names, volume by volume, and the rest (always the file's own name, so the
    key does not change when the file is written) is folded to one case only
    when that folder's disk ignores case. When the disk's spelling or its case
    rule cannot be read, nothing is folded: two spellings then get two stores,
    which the lock cannot see, but two files never share one. Windows folds
    the real path with `normcase`; elsewhere it is the real path.
    """
    real = os.path.realpath(fp)
    if sys.platform == "win32":
        return os.path.normcase(real)
    if sys.platform != "darwin":
        return real
    folder, tail = os.path.dirname(real), [os.path.basename(real)]
    while not os.path.isdir(folder) and os.path.dirname(folder) != folder:
        tail.insert(0, os.path.basename(folder))
        folder = os.path.dirname(folder)
    spelled = _diskSpelling(folder)
    if spelled is None:
        return real
    tail = [unicodedata.normalize("NFC", name) for name in tail]
    if _ignoresCase(folder):
        tail = [name.casefold() for name in tail]
    return os.path.join(unicodedata.normalize("NFC", spelled), *tail)


def storePaths(jser_fp : str) -> tuple:
    """(store file, working folder) for a .jser, keyed by its canonical path.

    Two copies at two paths never share a store; a symlink and its target do,
    and so do two spellings of one name on a disk that ignores case.
    """
    real = canonicalPath(jser_fp)
    sname = os.path.splitext(os.path.basename(real))[0]
    key = hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]
    root = storeRoot()
    return str(root / f"{sname}-{key}.pyrstore"), str(root / f"{sname}-{key}.work")


def fsType(path : str):
    """The file system type of path on Linux, or None where it is not read."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        dev = os.stat(path).st_dev
        with open("/proc/self/mountinfo") as f:
            for line in f:
                left, _, right = line.partition(" - ")
                major, minor = left.split()[2].split(":")
                if os.makedev(int(major), int(minor)) == dev:
                    return right.split()[0]
    except (OSError, ValueError, IndexError):
        return None
    return None


def refuseNetworkFolder(folder : str):
    """Raise when the store folder is on a network file system."""
    fstype = fsType(folder)
    if fstype in NETWORK_FS:
        raise OSError(
            f"The local store folder {folder} is on a network file system "
            f"({fstype}). SQLite is not safe there. Set {ENV_DIR} to a local folder."
        )


## ---------------------------------------------------------------------------
## Packing a section into rows and back
## ---------------------------------------------------------------------------

def packRow(row) -> tuple:
    """(shape, npts, xy, rest, xmin, ymin, xmax, ymax) for one stored trace row.

    A positional row whose x and y are all Python floats keeps its coordinates
    as float64 bytes, which is exact for any value a JSON reader produced. Any
    other row (keyed rows, an int coordinate, an empty trace) is kept whole as
    JSON, so nothing is coerced.
    """
    if (
        type(row) is list and len(row) == 8
        and type(row[0]) is list and type(row[1]) is list
        and len(row[0]) == len(row[1]) and row[0]
        and set(map(type, row[0])) == {float}
        and set(map(type, row[1])) == {float}
    ):
        n = len(row[0])
        x = np.array(row[0], dtype="<f8")
        y = np.array(row[1], dtype="<f8")
        return (
            0, n, x.tobytes() + y.tobytes(), fast_dumps(row[2:]),
            float(x.min()), float(y.min()), float(x.max()), float(y.max()),
        )
    return (1, 0, None, fast_dumps(row), None, None, None, None)


def unpackRow(shape, npts, xy, rest) -> list:
    """The stored trace row, as the section file held it."""
    if shape == 0:
        a = np.frombuffer(xy, dtype="<f8")
        return [a[:npts].tolist(), a[npts:].tolist(), *fast_loads(rest)]
    return fast_loads(rest)


def packSection(snum : int, section_data : dict) -> tuple:
    """(header bytes, trace rows) for one section dict."""
    header = {}
    for key, value in section_data.items():
        header[key] = list(value) if key == "contours" else value
    rows = []
    for cpos, (name, traces) in enumerate(section_data["contours"].items()):
        for ord_, row in enumerate(traces):
            rows.append((snum, cpos, ord_, name, *packRow(row)))
    return fast_dumps(header), rows


class HybridStore():

    def __init__(self, db_fp : str, work_dir : str):
        """Open (or create) the store file and its working folder.

            Raises:
                OSError: if the store folder is on a network file system
                StoreBusyError: if another process holds the store
                StoreSchemaError: if the file is not a store of this schema
                    version. A file whose header is not a store's of this
                    version (another program's, or another version's) is
                    never opened and is left as it was
        """
        self.db_fp = db_fp
        self.work_dir = work_dir
        folder = os.path.dirname(db_fp)
        os.makedirs(folder, exist_ok=True)
        refuseNetworkFolder(folder)
        self.con : sqlite3.Connection = None  # type: ignore[assignment]
        self._lock_fd = _lockFile(db_fp + ".lock")
        if self._lock_fd is None:
            raise StoreBusyError(IN_USE)
        # from here on the lock is held: any failure lets go of it
        try:
            os.makedirs(work_dir, exist_ok=True)
            if not os.path.exists(db_fp):
                self._create()
            self._checkHeader()
            self.con = sqlite3.connect(db_fp, isolation_level=None)
            self.con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            self._checkTables()
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA synchronous=FULL")
        except BaseException as e:
            self.close()
            if isinstance(e, sqlite3.OperationalError) and _isBusy(e):
                raise StoreBusyError(IN_USE) from e
            raise

    def _refuse(self, why : str, untouched : bool = True):
        raise StoreSchemaError(
            f"{self.db_fp} is not a local store this version of PyReconstruct "
            f"can read ({why})." + (" It was left as it was." if untouched else "")
        )

    def _create(self):
        """Write a new, empty store beside db_fp, then move it into place.

        So the store file is either absent or whole: a crash while the schema
        is written leaves only the temporary file, which the next create
        replaces. A journal or WAL file already beside the missing store is
        another file's, and is never joined to a new one.
        """
        for ext in ("-wal", "-journal"):
            if os.path.exists(self.db_fp + ext):
                self._refuse(f"a {ext[1:]} file is beside it with no store")
        tmp = self.db_fp + ".new"
        for leftover in (tmp, tmp + "-journal"):
            if os.path.exists(leftover):
                os.remove(leftover)
        con = sqlite3.connect(tmp, isolation_level=None)
        try:
            con.executescript(
                "PRAGMA synchronous=FULL;\nBEGIN IMMEDIATE;\n" + SCHEMA
                + f"PRAGMA user_version={SCHEMA_VERSION};\n"
                + f"PRAGMA application_id={APPLICATION_ID};\n"
                + "INSERT INTO meta(key, value) VALUES "
                + f"('schema_version', '{SCHEMA_VERSION}'), ('created_utc', '{_now()}');\n"
                + "COMMIT;"
            )
        finally:
            con.close()
        with open(tmp, "r+b") as f:
            os.fsync(f.fileno())
        os.replace(tmp, self.db_fp)
        _fsyncFolder(os.path.dirname(self.db_fp))

    def _checkHeader(self):
        """Refuse a file that is not a store of this schema, from its header.

        Read from the file itself, before SQLite opens it: opening a database
        can replay its journal or WAL and make side files, and a file that is
        not ours must be left exactly as it was.
        """
        with open(self.db_fp, "rb") as f:
            header = f.read(100)
        if len(header) < 100 or not header.startswith(SQLITE_MAGIC):
            self._refuse("not a SQLite file")
        version = int.from_bytes(header[60:64], "big")
        app_id = int.from_bytes(header[68:72], "big")
        if app_id != APPLICATION_ID:
            self._refuse("another program's database")
        if version != SCHEMA_VERSION:
            self._refuse(f"schema version {version}")

    def _checkTables(self):
        """Refuse a file with a store's header but not a store's contents.

        Only a file that passed the header check gets here, so it is opened
        as a store is, and that open may finish writing its WAL into it, as
        any open of a store does. Nothing committed is lost by that, but the
        file is not promised to be left byte for byte as it was. Its version
        is the header's alone (a schema is never changed in place).
        """
        tables = {r[0] for r in self.con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        missing = REQUIRED_TABLES - tables
        if missing or self.meta("schema_version") != str(SCHEMA_VERSION):
            self._refuse(
                f"missing {', '.join(sorted(missing)) or 'its schema record'}",
                untouched=False,
            )

    @staticmethod
    def forJser(jser_fp : str) -> "HybridStore":
        return HybridStore(*storePaths(jser_fp))

    def close(self):
        if self.con is not None:
            self.con.close()
            self.con = None
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    ## meta -----------------------------------------------------------------

    def meta(self, key : str):
        row = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else row[0]

    def setMeta(self, key : str, value):
        self.con.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (key, None if value is None else str(value)),
        )

    def isImported(self) -> bool:
        return self.meta("imported_utc") is not None

    def matchesJser(self, jser_fp : str) -> bool:
        """True when the .jser on disk is the one the store last imported."""
        st = os.stat(jser_fp)
        return (
            self.meta("jser_size") == str(st.st_size)
            and self.meta("jser_mtime_ns") == str(st.st_mtime_ns)
        )

    def recordJser(self, jser_fp : str):
        st = os.stat(jser_fp)
        self.setMeta("jser_path", os.path.realpath(jser_fp))
        self.setMeta("jser_size", st.st_size)
        self.setMeta("jser_mtime_ns", st.st_mtime_ns)

    ## the working layer ------------------------------------------------------

    def hasPending(self) -> bool:
        return bool(
            self.con.execute("SELECT 1 FROM pending_section LIMIT 1").fetchone()
            or self.con.execute("SELECT 1 FROM pending_series").fetchone()
        )

    def clearPending(self):
        """Drop unsaved work: the store goes back to the last Save."""
        with self._tx():
            self.con.execute("DELETE FROM pending_section")
            self.con.execute("DELETE FROM pending_series")

    def writePendingSection(self, snum : int, section_data):
        """A section's working copy, as its hidden file holds it today.

        `section_data` is the section dict, or the bytes its file would hold.
        """
        if not isinstance(section_data, bytes):
            section_data = fast_dumps(section_data)
        with self._tx(sync="NORMAL"):
            self.con.execute(
                "INSERT OR REPLACE INTO pending_section(snum, data) VALUES (?, ?)",
                (snum, section_data),
            )

    def deletePendingSection(self, snum : int):
        """Mark a section deleted in the working layer (NULL data)."""
        with self._tx(sync="NORMAL"):
            self.con.execute(
                "INSERT OR REPLACE INTO pending_section(snum, data) VALUES (?, NULL)",
                (snum,),
            )

    def writePendingSeries(self, series_data : dict):
        with self._tx(sync="NORMAL"):
            self.con.execute(
                "INSERT OR REPLACE INTO pending_series(id, data) VALUES (1, ?)",
                (fast_dumps(series_data),),
            )

    ## reading ----------------------------------------------------------------

    def sectionNumbers(self) -> list:
        """Every section the working state has: saved, plus pending, less deleted."""
        saved = {r[0] for r in self.con.execute("SELECT snum FROM section")}
        for snum, data in self.con.execute("SELECT snum, data FROM pending_section"):
            if data is None:
                saved.discard(snum)
            else:
                saved.add(snum)
        return sorted(saved)

    def hasSection(self, snum : int) -> bool:
        return snum in set(self.sectionNumbers())

    def readSection(self, snum : int, fallback_fp : str | None = None) -> dict:
        """A section dict, as the hidden section file holds it today.

        The working copy wins over the saved one, and a section deleted in the
        working layer is gone. A section the store has never seen (one
        inserted this session, which exists only as a file in the working
        folder) is read from `fallback_fp`.
        """
        row = self.con.execute(
            "SELECT data FROM pending_section WHERE snum=?", (snum,)
        ).fetchone()
        if row is not None:
            if row[0] is None:
                raise FileNotFoundError(f"section {snum} is deleted in the store {self.db_fp}")
            return fast_loads(row[0])
        row = self.con.execute(
            "SELECT header FROM section WHERE snum=?", (snum,)
        ).fetchone()
        if row is None:
            if fallback_fp and os.path.isfile(fallback_fp):
                with open(fallback_fp, "rb") as f:
                    return fast_loads(f.read())
            raise FileNotFoundError(f"section {snum} is not in the store {self.db_fp}")
        return self._assemble(snum, fast_loads(row[0]))

    def _assemble(self, snum : int, header : dict) -> dict:
        names = header["contours"]
        contours : dict = {name: [] for name in names}
        for cpos, shape, npts, xy, rest in self.con.execute(
            "SELECT cpos, shape, npts, xy, rest FROM trace WHERE snum=? ORDER BY cpos, ord",
            (snum,),
        ):
            contours[names[cpos]].append(unpackRow(shape, npts, xy, rest))
        header["contours"] = contours
        return header

    def seriesData(self) -> dict:
        row = self.con.execute("SELECT data FROM pending_series").fetchone()
        if row is None:
            row = self.con.execute("SELECT data FROM series").fetchone()
        return fast_loads(row[0])

    def logText(self) -> str:
        row = self.con.execute("SELECT text FROM log").fetchone()
        return "" if row is None else row[0]

    def objectTraces(self, name : str) -> list:
        """(section, row) for every saved trace of one object, by the per-object index."""
        return [
            (snum, unpackRow(shape, npts, xy, rest))
            for snum, shape, npts, xy, rest in self.con.execute(
                "SELECT snum, shape, npts, xy, rest FROM trace WHERE name=? ORDER BY snum, cpos, ord",
                (name,),
            )
        ]

    ## writing the saved tables ----------------------------------------------

    def _replaceSection(self, snum : int, section_data : dict):
        header, rows = packSection(snum, section_data)
        self.con.execute("DELETE FROM trace WHERE snum=?", (snum,))
        self.con.execute(
            "INSERT OR REPLACE INTO section(snum, header) VALUES (?, ?)",
            (snum, header),
        )
        self.con.executemany(
            f"INSERT INTO trace({TRACE_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )

    def _savedSection(self, snum : int) -> dict:
        row = self.con.execute("SELECT header FROM section WHERE snum=?", (snum,)).fetchone()
        return self._assemble(snum, fast_loads(row[0]))

    def _dropSection(self, snum : int):
        for table in ("trace", "section"):
            self.con.execute(f"DELETE FROM {table} WHERE snum=?", (snum,))

    def commit(self, series) -> bool:
        """Save: fold the working layer into the saved tables, one transaction.

        Cost follows the sections changed since the last Save, not the series.

        A working row whose content equals the saved section is dropped, not
        saved: the app writes a section "when in doubt" (MainWindow.saveAllData
        on close, after a Save), and a rewrite of the same content must not
        mark the store ahead of the .jser. So `dirty` means the content changed.

            Params:
                series (Series): the open series; its `sections` say which
                    sections exist, and its working folder holds the log and
                    any section inserted this session that the store has not
                    seen
            Returns:
                (bool): True if any saved content changed
        """
        work_files = {
            snum: os.path.join(series.getwdir(), fname)
            for snum, fname in series.sections.items()
        }
        with self._tx():
            pending = dict(self.con.execute("SELECT snum, data FROM pending_section"))
            saved = {r[0] for r in self.con.execute("SELECT snum FROM section")}
            # a section inserted this session and never written to the store
            for snum in set(series.sections) - saved - set(pending):
                if os.path.isfile(work_files[snum]):
                    with open(work_files[snum], "rb") as f:
                        pending[snum] = f.read()
            # a section the series no longer has
            for snum in saved - set(series.sections):
                pending[snum] = None
            # every section the series lists must have content to save, or the
            # saved series would name a section the store does not hold
            missing = sorted(
                snum for snum in series.sections
                if pending.get(snum) is None and (snum in pending or snum not in saved)
            )
            if missing:
                raise StoreSaveError(
                    f"Not saved: section(s) {', '.join(map(str, missing))} of the "
                    f"series have no data in the store or the working folder."
                )
            changed = False
            for snum, data in sorted(pending.items()):
                if data is None or snum not in series.sections:
                    if snum in saved:
                        self._dropSection(snum)
                        changed = True
                    continue
                section_data = fast_loads(data)
                if snum in saved and self._savedSection(snum) == section_data:
                    continue  # the same content written again
                self._replaceSection(snum, section_data)
                changed = True
            row = self.con.execute("SELECT data FROM pending_series").fetchone()
            if row is not None:
                old = self.con.execute("SELECT data FROM series").fetchone()
                if old is None or fast_loads(old[0]) != fast_loads(row[0]):
                    self.con.execute("INSERT OR REPLACE INTO series(id, data) VALUES (1, ?)", row)
                    changed = True
            log_fp = os.path.join(series.getwdir(), "existing_log.csv")
            if os.path.isfile(log_fp):
                with open(log_fp, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                if text != self.logText():
                    self.con.execute("INSERT OR REPLACE INTO log(id, text) VALUES (1, ?)", (text,))
                    changed = True
            self.con.execute("DELETE FROM pending_section")
            self.con.execute("DELETE FROM pending_series")
            if changed:
                self.setMeta("dirty", 1)
        return changed

    ## import -----------------------------------------------------------------

    def importJser(self, jser_fp : str, source, collisions : dict, reporter=None):
        """Write a .jser into the store, migrated exactly as openJser migrates it.

        One transaction: a failure partway leaves the store as it was.

            Params:
                jser_fp (str): the .jser the source was read from
                source: what Series._readJserForOpen returns. It hands over the
                    sections one at a time (a streamed read where the file
                    allows it), so the import holds one section, the series and
                    the log, as openJser does
                collisions (dict): the contour-name collisions it returns
                reporter: an optional ProgressReporter
        """
        from .section import Section
        from .series import Series, applyContourRenames

        total = source.sectionCount()
        done = 0
        self.con.execute("PRAGMA journal_mode=TRUNCATE")
        try:
            with self._tx():
                for table in ("series", "log", "section", "trace",
                              "pending_section", "pending_series"):
                    self.con.execute(f"DELETE FROM {table}")
                renames = {}
                for snum, section_data, _ in source.sections():
                    stored_ids : dict = {}
                    renames.update(Section.updateJSON(section_data, snum, stored_ids=stored_ids))
                    if stored_ids:
                        Section.reattachTraceIDs(section_data, stored_ids)
                    # every section locks on open (see Series.openJser)
                    section_data["align_locked"] = True
                    self._replaceSection(snum, section_data)
                    section_data = None  # free it before the next is decoded
                    done += 1
                    if reporter is not None and total:
                        reporter.set_progress(done / total * 100)
                self.con.execute(
                    "INSERT INTO log(id, text) VALUES (1, ?)", (source.log,)
                )
                series_data = source.series
                series_data["log_set"] = []
                Series.updateJSON(series_data)
                applyContourRenames(series_data, renames, collisions)
                self.con.execute(
                    "INSERT INTO series(id, data) VALUES (1, ?)", (fast_dumps(series_data),)
                )
                self.recordJser(jser_fp)
                self.setMeta("dirty", 0)
                self.setMeta("imported_utc", _now())
        finally:
            self.con.execute("PRAGMA journal_mode=WAL")

    ## transactions --------------------------------------------------------------

    def _tx(self, sync : str = "FULL"):
        return _Transaction(self.con, sync)


class _Transaction():

    def __init__(self, con, sync):
        self.con, self.sync = con, sync

    def __enter__(self):
        try:
            self.con.execute(f"PRAGMA synchronous={self.sync}")
            self.con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            if _isBusy(e):
                raise StoreBusyError(IN_USE) from e
            raise

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            try:
                self.con.execute("COMMIT")
            except sqlite3.OperationalError as e:
                self.con.execute("ROLLBACK")
                if _isBusy(e):
                    raise StoreBusyError(IN_USE) from e
                raise
        else:
            self.con.execute("ROLLBACK")
        return False


def _fsyncFolder(folder : str):
    """Make a rename in folder durable (POSIX; a no-op where folders cannot be opened)."""
    if sys.platform == "win32":
        return
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
