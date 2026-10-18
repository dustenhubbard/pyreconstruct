"""PROTOTYPE, OPT-IN: a local SQLite working store for a series.

Turned on by ``PYRECON_HYBRID_STORE=1`` and by nothing else. With it off no
code in this module runs, ``Series.store`` stays ``None``, and every file the
app writes is what it wrote before this module existed.

With it on, the first open of a .jser imports it into a store on local disk,
and later opens read the store instead of the .jser:

  * the object list is rebuilt from per-trace numbers kept in the store
    (``section_stats``), so an open loads no section but the one on screen;
  * a section change writes the section to the working layer
    (``pending_section``), the role the hidden folder's section file has today;
  * Save folds the working layer into the saved tables, O(changed sections);
  * ``Series.saveJser`` (export, and close) writes the .jser with the existing
    writer, so the file is what any build reads.

The store lives in a per-user folder on local disk, never beside the .jser:
SQLite is not safe on NFS or SMB, where lab series live. The design note and
its gaps are in the hub, specs/hybrid-store-design-2026-10-16.md.

Not for merging as is.
"""

import gc
import os
import sys
import shutil
import hashlib
import sqlite3
import struct
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from PyReconstruct.modules.constants import fast_loads, fast_dumps
from PyReconstruct.modules.constants.jser_splice import ArraySection

ENV_SWITCH = "PYRECON_HYBRID_STORE"
ENV_DIR = "PYRECON_HYBRID_STORE_DIR"
## What Save does with the switch on. "jser" (the default): Save writes the
## store and then the .jser, as Save writes the .jser today. "store": Save
## writes the store only, and the .jser is written on close or export. Which
## one a user gets is the maintainer's call (hub #247); both are here so both
## can be measured.
ENV_SAVE = "PYRECON_HYBRID_STORE_SAVE"
BUSY_TIMEOUT_MS = 5000
SCHEMA_VERSION = 1

## File systems a SQLite file must not sit on (Linux names, /proc/self/mountinfo)
NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "9p", "afs"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS series(id INTEGER PRIMARY KEY CHECK (id = 1), data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY CHECK (id = 1), text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS section(
    snum INTEGER PRIMARY KEY,
    header BLOB NOT NULL,
    stats_valid INTEGER NOT NULL DEFAULT 0
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
DROP TABLE IF EXISTS trace_stats;
CREATE TABLE IF NOT EXISTS section_stats(
    snum INTEGER PRIMARY KEY,
    keys BLOB NOT NULL, tags BLOB NOT NULL, colors BLOB NOT NULL,
    cpos BLOB NOT NULL, idx BLOB NOT NULL, flags BLOB NOT NULL,
    tag BLOB NOT NULL, color BLOB NOT NULL,
    length BLOB NOT NULL, area BLOB NOT NULL,
    cx BLOB NOT NULL, cy BLOB NOT NULL, radius BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_section(snum INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE IF NOT EXISTS pending_series(id INTEGER PRIMARY KEY CHECK (id = 1), data BLOB NOT NULL);
"""

TRACE_COLS = "snum, cpos, ord, name, shape, npts, xy, rest, xmin, ymin, xmax, ymax"

## The object-list numbers of one section, one blob per field (section_stats).
## keys: the alignment each contour's numbers are in (JSON, by contour
## position, null for a contour with no traces); tags, colors: the distinct
## values (JSON); then one entry per trace, in contour then index order.
STATS_COLS = "keys, tags, colors, cpos, idx, flags, tag, color, length, area, cx, cy, radius"
STATS_TYPES = {
    "cpos": "<i4", "idx": "<i4", "flags": "u1", "tag": "<i4", "color": "<i4",
    "length": "<f8", "area": "<f8", "cx": "<f8", "cy": "<f8", "radius": "<f8",
}
CLOSED, HIDDEN, NEGATIVE = 1, 2, 4


def enabled() -> bool:
    """True when the prototype switch is on."""
    return os.environ.get(ENV_SWITCH) == "1"


def saveWritesJser() -> bool:
    """True unless PYRECON_HYBRID_STORE_SAVE=store: Save writes the .jser too."""
    return os.environ.get(ENV_SAVE, "jser") != "store"


class StoreBusyError(OSError):
    """Another process holds the store. Never a sign of damage."""


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
    """The per-user local folder that holds every store."""
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


def storePaths(jser_fp : str) -> tuple:
    """(store file, working folder) for a .jser, keyed by its real path."""
    real = os.path.realpath(jser_fp)
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
            f"The hybrid store folder {folder} is on a network file system "
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


def unpackRowArrays(shape, npts, xy, rest) -> list:
    """unpackRow, with x and y as read-only float64 arrays over the blob.

    For the export only (jser_splice.ArraySection): no list of Python floats
    is built, and nothing can edit the arrays.
    """
    if shape == 0:
        a = np.frombuffer(xy, dtype="<f8")
        return [a[:npts], a[npts:], *fast_loads(rest)]
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


def tformKey(series, name : str, tform_keys) -> str:
    """The alignment an object's numbers are computed in, as ObjectData.addTrace picks it."""
    alignment = series.getAttr(name, "alignment")
    if alignment is None or alignment not in tform_keys:
        return series.alignment
    return alignment


@contextmanager
def _gcPaused():
    """Keep the cyclic garbage collector out of a bulk build.

    The lazy open makes about four objects per trace (550,637 traces on DW09)
    and no cyclic garbage. Left on, the collector walked the growing heap a
    dozen times during the open (2.9 s of a 10 s open on DW09, round 3).
    Reference counting still frees everything as usual.
    """
    was_on = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_on:
            gc.enable()


class HybridStore():

    def __init__(self, db_fp : str, work_dir : str):
        """Open (or create) the store file and its working folder."""
        self.db_fp = db_fp
        self.work_dir = work_dir
        folder = os.path.dirname(db_fp)
        os.makedirs(folder, exist_ok=True)
        refuseNetworkFolder(folder)
        self.con : sqlite3.Connection = None  # type: ignore[assignment]
        self._lock_fd = _lockFile(db_fp + ".lock")
        if self._lock_fd is None:
            raise StoreBusyError(IN_USE)
        os.makedirs(work_dir, exist_ok=True)
        try:
            self.con = sqlite3.connect(db_fp, isolation_level=None)
            self.con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA synchronous=FULL")
            self.con.executescript(SCHEMA)
            if self.meta("schema_version") is None:
                self.setMeta("schema_version", SCHEMA_VERSION)
                self.setMeta("created_utc", _now())
                self.con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        except sqlite3.OperationalError as e:
            self.close()
            if _isBusy(e):
                raise StoreBusyError(IN_USE) from e
            raise

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
        """True when the .jser on disk is the one the store last imported or exported."""
        st = os.stat(jser_fp)
        return (
            self.meta("jser_size") == str(st.st_size)
            and self.meta("jser_mtime_ns") == str(st.st_mtime_ns)
        )

    def hasUnexportedWork(self) -> bool:
        return self.meta("dirty") == "1" or self.hasPending()

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
        """A section's working copy (Section.save), as its hidden file was.

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

    def foldStraySections(self):
        """Keep section files the last session left only in the working folder.

        A section inserted by Section.new exists as a file in the working folder
        until it is in the store. After a crash the next open would clear the
        folder; its sections go into the working rows first, so the recovery
        offer includes them, as the hidden folder's files are offered today.
        """
        if not os.path.isdir(self.work_dir):
            return []
        known = set(self.sectionNumbers())
        found = {}
        for name in os.listdir(self.work_dir):
            stem, dot, ext = name.rpartition(".")
            if dot and ext.isdigit() and int(ext) not in known:
                with open(os.path.join(self.work_dir, name), "rb") as f:
                    found[int(ext)] = fast_loads(f.read())
        for snum, data in sorted(found.items()):
            self.writePendingSection(snum, data)
        return sorted(found)

    def reorderSections(self, mapping : dict, work_files : dict):
        """Renumber sections in the working layer (Series.reorderSections)."""
        moved = {old: new for old, new in mapping.items() if old != new}
        if not moved:
            return
        data = {old: self.readSection(old, work_files.get(old)) for old in moved}
        with self._tx(sync="NORMAL"):
            for old, new in moved.items():
                self.con.execute(
                    "INSERT OR REPLACE INTO pending_section(snum, data) VALUES (?, ?)",
                    (new, fast_dumps(data[old])),
                )
            for old in set(moved) - set(mapping.values()):
                self.con.execute(
                    "INSERT OR REPLACE INTO pending_section(snum, data) VALUES (?, NULL)",
                    (old,),
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
        """A section dict, as the hidden section file held it.

        The working copy wins over the saved one. A section the store has never
        seen (one inserted this session, Section.new writes a file) is read
        from its file in the working folder.
        """
        row = self.con.execute(
            "SELECT data FROM pending_section WHERE snum=?", (snum,)
        ).fetchone()
        if row is not None and row[0] is not None:
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

    def readSectionWithBytes(self, snum : int, fallback_fp : str | None = None) -> tuple:
        """(section dict, the bytes its hidden file would hold), as readSection.

        The bytes are what Section.save writes for that dict, so the trace-id
        record (TraceIDIssuer) and the splice save's key see the same bytes a
        hidden file would give them.
        """
        row = self.con.execute(
            "SELECT data FROM pending_section WHERE snum=?", (snum,)
        ).fetchone()
        if row is not None and row[0] is not None:
            return fast_loads(row[0]), row[0]
        if not self.con.execute(
            "SELECT 1 FROM section WHERE snum=?", (snum,)
        ).fetchone() and fallback_fp and os.path.isfile(fallback_fp):
            with open(fallback_fp, "rb") as f:
                raw = f.read()
            return fast_loads(raw), raw
        section_data = self.readSection(snum, fallback_fp)
        return section_data, fast_dumps(section_data)

    def readSectionKeyed(self, snum : int, fallback_fp : str | None = None) -> tuple:
        """(section dict, splice key) for an export from the store.

        The key stands for the section's content, so an export copies a
        section whose key the last export recorded (jser_splice.py). For a
        saved section it is the sha256 of the stored header and rows, read as
        they are fetched: re-encoding the section to hash its file bytes cost
        about 6 s per DW09 export (round 3). Working rows and a section only
        in the working folder are keyed by their bytes, as a hidden file is.
        """
        row = self.con.execute(
            "SELECT data FROM pending_section WHERE snum=?", (snum,)
        ).fetchone()
        if row is not None and row[0] is not None:
            return fast_loads(row[0]), hashlib.sha256(row[0]).digest()
        row = self.con.execute(
            "SELECT header FROM section WHERE snum=?", (snum,)
        ).fetchone()
        if row is None:
            if fallback_fp and os.path.isfile(fallback_fp):
                with open(fallback_fp, "rb") as f:
                    raw = f.read()
                return fast_loads(raw), hashlib.sha256(raw).digest()
            raise FileNotFoundError(f"section {snum} is not in the store {self.db_fp}")
        h = hashlib.sha256(b"hybrid-store-section-v1\0")
        h.update(struct.pack("<q", len(row[0])))
        h.update(row[0])
        section_data = self._assemble(snum, ArraySection(fast_loads(row[0])), h, unpackRowArrays)
        return section_data, h.digest()

    def _assemble(self, snum : int, header : dict, hasher=None, unpack=unpackRow) -> dict:
        names = header["contours"]
        contours : dict = {name: [] for name in names}
        for cpos, shape, npts, xy, rest in self.con.execute(
            "SELECT cpos, shape, npts, xy, rest FROM trace WHERE snum=? ORDER BY cpos, ord",
            (snum,),
        ):
            if hasher is not None:
                hasher.update(struct.pack(
                    "<qqqqq", cpos, shape, npts, -1 if xy is None else len(xy), len(rest)
                ))
                if xy is not None:
                    hasher.update(xy)
                hasher.update(rest)
            contours[names[cpos]].append(unpack(shape, npts, xy, rest))
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
        """(section, row) for every trace of one object, by the per-object index."""
        return [
            (snum, unpackRow(shape, npts, xy, rest))
            for snum, shape, npts, xy, rest in self.con.execute(
                "SELECT snum, shape, npts, xy, rest FROM trace WHERE name=? ORDER BY snum, ord",
                (name,),
            )
        ]

    ## writing the saved tables ----------------------------------------------

    def _replaceSection(self, snum : int, section_data : dict):
        header, rows = packSection(snum, section_data)
        self.con.execute("DELETE FROM trace WHERE snum=?", (snum,))
        self.con.execute("DELETE FROM section_stats WHERE snum=?", (snum,))
        self.con.execute(
            "INSERT OR REPLACE INTO section(snum, header, stats_valid) VALUES (?, ?, 0)",
            (snum, header),
        )
        self.con.executemany(
            f"INSERT INTO trace({TRACE_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )

    def _savedSection(self, snum : int) -> dict:
        row = self.con.execute("SELECT header FROM section WHERE snum=?", (snum,)).fetchone()
        return self._assemble(snum, fast_loads(row[0]))

    def _dropSection(self, snum : int):
        for table in ("trace", "section_stats", "section"):
            self.con.execute(f"DELETE FROM {table} WHERE snum=?", (snum,))

    def _writeStats(self, snum : int, contour_names : list, tform_keys, series, objects):
        """The object-list numbers of one section, from a SeriesData's objects."""
        keys : list = [None] * len(contour_names)
        tag_ids : dict = {}
        color_ids : dict = {}
        cols : dict = {field: [] for field in STATS_TYPES}
        for cpos, name in enumerate(contour_names):
            obj = objects.get(name)
            if obj is None:
                continue
            tds = obj.traces.get(snum)
            if not tds:
                continue
            keys[cpos] = tformKey(series, name, tform_keys)
            for td in tds:
                tags = fast_dumps(sorted(td.tags, key=str))
                color = None if td.color is None else fast_dumps(list(td.color))
                cols["cpos"].append(cpos)
                cols["idx"].append(td.index)
                cols["flags"].append(
                    (CLOSED if td.closed else 0) | (HIDDEN if td.hidden else 0)
                    | (NEGATIVE if td.negative else 0)
                )
                cols["tag"].append(tag_ids.setdefault(tags, len(tag_ids)))
                cols["color"].append(
                    -1 if color is None else color_ids.setdefault(color, len(color_ids))
                )
                cols["length"].append(td.length)
                cols["area"].append(td.area)
                cols["cx"].append(td.centroid[0])
                cols["cy"].append(td.centroid[1])
                cols["radius"].append(td.radius)
        self.con.execute(
            f"INSERT OR REPLACE INTO section_stats(snum, {STATS_COLS})"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snum, fast_dumps(keys),
                b"[" + b",".join(tag_ids) + b"]",
                b"[" + b",".join(color_ids) + b"]",
                *(np.array(cols[f], dtype=dtype).tobytes() for f, dtype in STATS_TYPES.items()),
            ),
        )
        self.con.execute("UPDATE section SET stats_valid=1 WHERE snum=?", (snum,))

    def commit(self, series):
        """Save: fold the working layer into the saved tables, one transaction.

        Cost follows the sections changed since the last Save, not the series.
        The object-list numbers of each changed section are measured again from
        its saved rows, exactly as a full open would measure them: the numbers
        the session holds come from unsaved points and can differ in the last
        bit from the saved ones.

        A working row whose content equals the saved section is dropped, not
        saved: the app writes a section "when in doubt" (MainWindow.saveAllData
        on close, after a Save), and a rewrite of the same content must not
        mark the store ahead of the .jser. So `dirty` means the content changed.
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
            replaced = []
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
                replaced.append(snum)
                changed = True
            self.con.execute("DELETE FROM pending_section")
            self._measure(series, replaced)
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

    def markExported(self, jser_fp : str):
        with self._tx():
            self.recordJser(jser_fp)
            self.setMeta("dirty", 0)
            self.setMeta("exported_utc", _now())

    ## import -----------------------------------------------------------------

    def importJser(self, jser_fp : str, source, collisions : dict, reporter=None):
        """Write a .jser into the store, migrated exactly as openJser migrates it.

        `source` is what Series._readJserForOpen returns: it hands over the
        sections one at a time (a streamed read where the file allows it), so
        the import holds one section, the series and the log, as openJser does.
        """
        from .section import Section
        from .series import Series, applyContourRenames

        total = source.sectionCount() + 1
        done = 0
        self.con.execute("PRAGMA journal_mode=TRUNCATE")
        try:
            with self._tx():
                for table in ("series", "log", "section", "trace", "section_stats",
                              "pending_section", "pending_series"):
                    self.con.execute(f"DELETE FROM {table}")
                renames = {}
                for snum, section_data in source.sections():
                    stored_ids : dict = {}
                    renames.update(Section.updateJSON(section_data, snum, stored_ids=stored_ids))
                    if stored_ids:
                        Section.reattachTraceIDs(section_data, stored_ids)
                    # every section locks on open (see Series.openJser)
                    section_data["align_locked"] = True
                    self._replaceSection(snum, section_data)
                    section_data = None  # free it before the next is decoded
                    done += 1
                    if reporter is not None:
                        reporter.set_progress(done / total * 50)
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

    def setAside(self) -> str:
        """Keep this store under a conflict name and leave the path free."""
        self.close()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = self.db_fp[:-len(".pyrstore")]
        kept = f"{base}.conflict-{stamp}.pyrstore"
        os.replace(self.db_fp, kept)
        for ext in ("-wal", "-shm"):
            if os.path.exists(self.db_fp + ext):
                os.replace(self.db_fp + ext, kept + ext)
        return kept

    ## building the series ------------------------------------------------------

    def buildSeries(self, jser_fp : str):
        """A Series opened from the store, with its object list from the stored numbers."""
        from .series import Series

        sname = os.path.splitext(os.path.basename(jser_fp))[0]
        # the working folder is this store's own: last session's timer and undo
        # files go, the .ser and the log are written fresh from the store
        if os.path.isdir(self.work_dir):
            shutil.rmtree(self.work_dir)
        os.makedirs(self.work_dir)
        ser_fp = os.path.join(self.work_dir, f"{sname}.ser")
        with open(ser_fp, "wb") as f:
            f.write(fast_dumps(self.seriesData()))
        with open(os.path.join(self.work_dir, "existing_log.csv"), "w", encoding="utf-8") as f:
            f.write(self.logText())

        sections = {snum: f"{sname}.{snum}" for snum in self.sectionNumbers()}
        series = Series(ser_fp, sections, get_series_data=False)
        series.jser_fp = jser_fp
        series.store = self  # type: ignore[assignment]
        self.loadSeriesData(series)
        series._repointBCProfile()
        return series

    def loadSeriesData(self, series):
        """Fill series.data from the stored numbers; measure only what is stale.

        A section is measured for real (loaded and run through
        SeriesData.updateSection, as a full open does) when it has pending work,
        has no stored numbers, or has a number computed in an alignment its
        object would not use now.

        The stored numbers go into one TraceColumns, and each object holds its
        rows of it: no TraceData is built until something reads an object's
        traces (series_data.ObjectData).
        """
        from .section import Section, TransformsDict
        from .transform import Transform
        from .flag import Flag
        from .series_data import ObjectData, TraceColumns

        data = series.data
        data.data = {"sections": {}, "objects": {}}
        objects = data.data["objects"]
        pending = {r[0] for r in self.con.execute("SELECT snum FROM pending_section")}
        valid = dict(self.con.execute("SELECT snum, stats_valid FROM section"))
        recompute = []

        # the alignment attribute of each name, read once (tformKey)
        alignments : dict = {}

        def keyFor(name, tforms):
            alignment = alignments.get(name, alignments)
            if alignment is alignments:
                alignment = alignments[name] = series.getAttr(name, "alignment")
            if alignment is None or alignment not in tforms:
                return series.alignment
            return alignment

        name_ids : dict = {}       # name -> object number, in order of first trace
        tform_list : list = []
        tag_ids : dict = {}        # stored tags -> index in tag_values
        tag_values : list = []
        color_ids : dict = {None: 0}
        color_values : list = [None]
        parts : dict = {f: [] for f in TraceColumns.FIELDS}
        parts["object"] = []

        with _gcPaused():
            for snum in sorted(series.sections):
                if snum in pending or not valid.get(snum):
                    recompute.append(snum)
                    continue
                stats = self.con.execute(
                    f"SELECT {STATS_COLS} FROM section_stats WHERE snum=?", (snum,)
                ).fetchone()
                if stats is None:
                    recompute.append(snum)
                    continue
                h = fast_loads(self.con.execute(
                    "SELECT header FROM section WHERE snum=?", (snum,)
                ).fetchone()[0])
                tforms = TransformsDict()
                for a, t in h["tforms"].items():
                    tforms[a] = Transform(t)
                names = h["contours"]
                keys = fast_loads(stats[0])
                arrays = {
                    f: np.frombuffer(blob, dtype=dtype)
                    for (f, dtype), blob in zip(STATS_TYPES.items(), stats[3:])
                }
                cpos = arrays["cpos"]
                present = np.unique(cpos).tolist()
                if any(keys[p] != keyFor(names[p], tforms) for p in present):
                    recompute.append(snum)
                    continue
                data.data["sections"][snum] = {
                    "thickness": h["thickness"],
                    "calgrid": h["calgrid"],
                    "locked": h["align_locked"],
                    "bc_profiles": h["brightness_contrast_profiles"].copy(),
                    "src": Section.imageName(h["src"]),
                    "mag": h["mag"],
                    "flags": [Flag.fromList(f, snum) for f in h["flags"]],
                    "tforms": tforms.copy(),
                }
                # contour position -> object number and transform number
                object_of = np.zeros(len(names), dtype=np.int32)
                tform_of = np.zeros(len(names), dtype=np.int32)
                section_tforms : dict = {}
                for p in present:
                    object_of[p] = name_ids.setdefault(names[p], len(name_ids))
                    key = keys[p]
                    if key not in section_tforms:
                        section_tforms[key] = len(tform_list)
                        tform_list.append(tforms[key])
                    tform_of[p] = section_tforms[key]
                # the section's distinct tags and colors -> the series-wide ones
                tag_of = []
                for value in fast_loads(stats[1]):
                    stored = tuple(value)
                    if stored not in tag_ids:
                        tag_ids[stored] = len(tag_values)
                        tag_values.append(frozenset(value))
                    tag_of.append(tag_ids[stored])
                color_of = []
                for value in fast_loads(stats[2]):
                    stored = tuple(value)
                    if stored not in color_ids:
                        color_ids[stored] = len(color_values)
                        color_values.append(stored)
                    color_of.append(color_ids[stored])
                color_of.append(0)  # stored -1: no color
                flags = arrays["flags"]
                parts["object"].append(object_of[cpos])
                parts["snum"].append(np.full(len(cpos), snum, dtype=np.int32))
                parts["index"].append(arrays["idx"])
                parts["closed"].append((flags & CLOSED) != 0)
                parts["hidden"].append((flags & HIDDEN) != 0)
                parts["negative"].append((flags & NEGATIVE) != 0)
                parts["tag"].append(np.array(tag_of, dtype=np.int32)[arrays["tag"]])
                parts["color"].append(np.array(color_of, dtype=np.int32)[arrays["color"]])
                for f in ("length", "area", "cx", "cy", "radius"):
                    parts[f].append(arrays[f])
                parts["tform"].append(tform_of[cpos])

            if parts["object"]:
                obj_num = np.concatenate(parts["object"])
                # each object's rows together, keeping section then index order
                order = np.argsort(obj_num, kind="stable")
                obj_num = obj_num[order]
                columns = TraceColumns(
                    {f: np.concatenate(parts[f])[order] for f in TraceColumns.FIELDS},
                    tag_values, color_values, tform_list,
                )
                n = len(obj_num)
                cuts = np.flatnonzero(np.diff(obj_num)) + 1
                starts = np.concatenate(([0], cuts))
                stops = np.concatenate((cuts, [n]))
                # where each (object, section) pair starts, for the object ids
                snums = columns.arrays["snum"]
                pair_starts = np.concatenate((
                    [0], np.flatnonzero((np.diff(obj_num) != 0) | (np.diff(snums) != 0)) + 1
                ))
                pair_snums = snums[pair_starts].tolist()
                first_pair = np.searchsorted(pair_starts, starts).tolist()
                last_pair = np.searchsorted(pair_starts, stops).tolist()
                names_in_order = list(name_ids)
                by_name = []
                for num, start, stop, a, b in zip(
                    obj_num[starts].tolist(), starts.tolist(), stops.tolist(),
                    first_pair, last_pair,
                ):
                    name = names_in_order[num]
                    objects[name] = ObjectData(columns, start, stop)
                    by_name.append((name, pair_snums[a:b]))
                data.object_ids.placeAll(by_name)

        # updateSection places the ids of what it measures (ensure), so every
        # (section, name) with traces has its id without a reconcile, which
        # would build every object's TraceData to list its sections
        touched = set()
        for snum in sorted(recompute):
            section = series.loadSection(snum)
            data.updateSection(section, update_traces=True, log_events=False, read_store=True)
            touched.update(section.contours)
        # a section measured here went in after the stored ones; put each
        # object's sections back in order, as a full open adds them, so the
        # list's sums add in the same order
        for name in touched:
            obj = objects.get(name)
            if obj is not None:
                obj.traces = dict(sorted(obj.traces.items()))
        self.recomputed = sorted(recompute)

    def _measure(self, series, section_numbers):
        """Measure saved sections as a full open does, and store the numbers."""
        from .section import Section
        from .series_data import SeriesData

        scratch = SeriesData(series)
        for snum in section_numbers:
            h = fast_loads(self.con.execute(
                "SELECT header FROM section WHERE snum=?", (snum,)
            ).fetchone()[0])
            if not self._measureRows(series, snum, h, scratch):
                section = Section(snum, series)
                scratch.updateSection(section, update_traces=True, log_events=False, read_store=True)
            self._writeStats(
                snum, h["contours"], set(h["tforms"]) | {"no-alignment"},
                series, scratch.objects,
            )
            scratch.clearSection(snum)
            scratch.data["sections"].pop(snum, None)

    def _measureRows(self, series, snum : int, header : dict, scratch) -> bool:
        """Measure one saved section from its stored rows, with no Section.

        The numbers are the ones a load and SeriesData.updateSection give: the
        same TraceData code on the same float64 points, (n, 2) and C-ordered
        as the section's columnar store holds them. A load changes some rows
        before it measures them (Section.updateJSON and Section.__init__: a
        keyed or 9-field row, a row under two points, a closed two-point row,
        a name the name rule would change). For those this measures nothing
        and returns False, and the caller loads the section.
        """
        from .section import TransformsDict
        from .transform import Transform
        from .trace import normalizeObjectName

        names = header["contours"]
        if any(normalizeObjectName(name) != name for name in names):
            return False
        rows = []
        for cpos, shape, npts, xy, rest in self.con.execute(
            "SELECT cpos, shape, npts, xy, rest FROM trace WHERE snum=? ORDER BY cpos, ord",
            (snum,),
        ):
            if shape != 0 or npts < 2:
                return False
            fields = fast_loads(rest)
            if fields[1] and npts == 2:
                return False
            rows.append((names[cpos], npts, xy, fields))
        tforms = TransformsDict()
        for a, t in header["tforms"].items():
            if a != "no-alignment":
                tforms[a] = Transform(t)
        section = _MeasuredSection(snum, tforms)
        scratch.data["sections"][snum] = {}
        for name, npts, xy, (color, closed, negative, hidden, _fill, tags) in rows:
            a = np.frombuffer(xy, dtype="<f8")
            points = np.column_stack((a[:npts], a[npts:]))
            trace = _MeasuredTrace(name, color, closed, negative, hidden, set(tags))
            scratch.addTrace(trace, section, points)
        return True

    def writeStatsFor(self, series, section_numbers):
        """Store the object-list numbers of saved sections just measured."""
        pending = {r[0] for r in self.con.execute("SELECT snum FROM pending_section")}
        snums = [n for n in section_numbers if n not in pending]
        if not snums:
            return
        objects = series.data.objects
        with self._tx():
            for snum in snums:
                h = fast_loads(self.con.execute(
                    "SELECT header FROM section WHERE snum=?", (snum,)
                ).fetchone()[0])
                self._writeStats(
                    snum, h["contours"], set(h["tforms"]) | {"no-alignment"},
                    series, objects,
                )

    ## transactions --------------------------------------------------------------

    def _tx(self, sync : str = "FULL"):
        return _Transaction(self.con, sync)


class _MeasuredSection():
    """What SeriesData.addTrace reads of a section: its number and transforms."""

    def __init__(self, n, tforms):
        self.n = n
        self.tforms = tforms


class _MeasuredTrace():
    """What TraceData reads of a trace, from one stored row."""

    def __init__(self, name, color, closed, negative, hidden, tags):
        self.name = name
        self.color = color
        self.closed = closed
        self.negative = negative
        self.hidden = hidden
        self.tags = tags


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


def _readMeta(db_fp : str):
    """(meta dict, has working rows) of a store, read only; None if unreadable."""
    try:
        con = sqlite3.connect(f"file:{db_fp}?mode=ro", uri=True, timeout=1)
        try:
            meta = dict(con.execute("SELECT key, value FROM meta"))
            pending = bool(
                con.execute("SELECT 1 FROM pending_section LIMIT 1").fetchone()
                or con.execute("SELECT 1 FROM pending_series LIMIT 1").fetchone()
            )
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return meta, pending


def strandedStores(skip=()) -> list:
    """Stores holding work no .jser has: (store file, recorded .jser, why).

    Read at every open. A store is stranded when it has unexported work and its
    .jser is gone (moved, renamed, deleted), changed on disk since the store
    last matched it, or when the store was set aside after such a change.
    Content-keyed identity, which would follow a moved file, is not built.
    """
    root = storeRoot()
    if not root.is_dir():
        return []
    skip = {os.path.realpath(p) for p in skip}
    out = []
    for fp in sorted(root.glob("*.pyrstore")):
        if os.path.realpath(fp) in skip:
            continue
        read = _readMeta(str(fp))
        if read is None:
            continue
        meta, pending = read
        if meta.get("dirty") != "1" and not pending:
            continue
        jser = meta.get("jser_path") or ""
        if ".conflict-" in fp.name:
            why = "set aside after its .jser changed on disk"
        elif not os.path.isfile(jser):
            why = "its .jser is gone (moved, renamed or deleted)"
        else:
            st = os.stat(jser)
            if (str(st.st_size), str(st.st_mtime_ns)) == (meta.get("jser_size"), meta.get("jser_mtime_ns")):
                continue  # the .jser is as the store left it; its own open says so
            why = "its .jser changed on disk after the store's last export"
        out.append((str(fp), jser, why))
    return out


def strandedText(stranded) -> str:
    lines = [
        "Changes saved on this computer were never written to a .jser:", "",
    ]
    for fp, jser, why in stranded:
        lines.append(f"{os.path.basename(jser) or '(unknown series)'}: {why}.")
        lines.append(f"    kept in {fp}")
    lines += ["", "Nothing was deleted. To get a .jser back, use File > Export series > "
              "Set-aside store to .jser..."]
    return "\n".join(lines)


def exportStoreFile(db_fp : str, out_fp : str | None = None, progress=None) -> str:
    """Write a .jser from a store file (a set-aside one, say), next to it.

    The series is built from the store as an open would build it and written
    by Series.saveJser, so the bytes are what the app writes. An existing file
    is never replaced.
    """
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    meta : dict = (_readMeta(db_fp) or ({}, False))[0]
    if out_fp is None:
        stem = os.path.splitext(os.path.basename(meta.get("jser_path") or "series.jser"))[0]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_fp = os.path.join(os.path.dirname(db_fp), f"{stem} recovered {stamp}.jser")
    if os.path.exists(out_fp):
        raise FileExistsError(out_fp)
    store = HybridStore(db_fp, db_fp[:-len(".pyrstore")] + ".work")
    series = None
    try:
        store.foldStraySections()
        series = store.buildSeries(out_fp)
        series.setProgressReporter(progress or NullProgressReporter)
        series.saveJser()
    finally:
        if series is not None:
            series.close()
        store.close()
    return out_fp


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _main(argv):
    """python -m PyReconstruct.modules.datatypes.hybrid_store export <store> [out.jser]"""
    if len(argv) < 2 or argv[0] != "export":
        print(_main.__doc__)
        return 2
    print(exportStoreFile(argv[1], argv[2] if len(argv) > 2 else None))
    return 0


def openSeries(jser_fp : str, progress, notifier):
    """Series.openJser with the switch on. Returns a Series, or None if declined."""
    from .series import (
        Series, SeriesOpenError, _default_progress_reporter_factory, _default_notifier,
        _openingText,
    )

    asker = notifier if notifier is not None else _default_notifier()
    try:
        store = HybridStore.forJser(jser_fp)
    except StoreBusyError as e:
        raise SeriesOpenError(str(e)) from e
    kept = None
    if store.isImported() and not store.matchesJser(jser_fp):
        if store.hasUnexportedWork():
            # both the .jser and the store changed: keep the store, read the file
            kept = store.setAside()
            asker.notify(
                f"{os.path.basename(jser_fp)} changed on disk while the local store "
                f"held changes that were never written to it. Those changes are "
                f"kept, untouched, in\n{kept}\nThe series opens from the file on disk."
            )
            store = HybridStore.forJser(jser_fp)
        else:
            # the .jser is newer and the store holds nothing it lacks: import again
            store.setMeta("imported_utc", None)

    factory = progress if progress is not None else _default_progress_reporter_factory()
    sname = os.path.splitext(os.path.basename(jser_fp))[0]
    reporter = factory(text=_openingText(sname))
    try:
        if store.isImported():
            store.foldStraySections()
        if not store.isImported():
            source, collisions = Series._readJserForOpen(jser_fp, notifier)
            if source is None:
                store.close()
                return None
            try:
                store.importJser(jser_fp, source, collisions, reporter)
            finally:
                source.close()
            del source
        elif store.hasPending():
            if asker.confirm(
                f"{sname} has unsaved work from a session that did not close.\n"
                "Open it with that work?"
            ) is False:
                store.clearPending()
        elif store.meta("dirty") == "1":
            asker.notify(
                f"{sname}.jser does not have the changes saved last time yet. "
                "They are in the local store, and the .jser is written when you "
                "close the series."
            )
        series = store.buildSeries(jser_fp)
        # numbers measured just now are kept, so the next open skips them
        store.writeStatsFor(series, store.recomputed)
        if store.hasPending():
            series.modified = True
        stranded = strandedStores(skip=[store.db_fp] + ([kept] if kept else []))
        if stranded:
            asker.notify(strandedText(stranded))
    except BaseException:
        store.close()
        raise
    finally:
        reporter.finish()
    return series


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
