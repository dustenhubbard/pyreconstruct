"""PROTOTYPE, OPT-IN: a local SQLite working store for a series.

Turned on by ``PYRECON_HYBRID_STORE=1`` and by nothing else. With it off no
code in this module runs, ``Series.store`` stays ``None``, and every file the
app writes is what it wrote before this module existed.

With it on, the first open of a .jser imports it into a store on local disk,
and later opens read the store instead of the .jser:

  * the object list is rebuilt from per-trace numbers kept in the store
    (``trace_stats``), so an open loads no section but the one on screen;
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

import os
import sys
import shutil
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from PyReconstruct.modules.constants import fast_loads, fast_dumps

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
CREATE TABLE IF NOT EXISTS trace_stats(
    snum INTEGER NOT NULL,
    cpos INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    name TEXT NOT NULL,
    tform_key TEXT NOT NULL,
    closed INTEGER, hidden INTEGER, negative INTEGER,
    color TEXT, tags TEXT,
    length REAL, area REAL, cx REAL, cy REAL, radius REAL,
    PRIMARY KEY (snum, cpos, idx)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS pending_section(snum INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE IF NOT EXISTS pending_series(id INTEGER PRIMARY KEY CHECK (id = 1), data BLOB NOT NULL);
"""

TRACE_COLS = "snum, cpos, ord, name, shape, npts, xy, rest, xmin, ymin, xmax, ymax"


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
        if os.name == "nt":
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


class HybridStore():

    def __init__(self, db_fp : str, work_dir : str):
        """Open (or create) the store file and its working folder."""
        self.db_fp = db_fp
        self.work_dir = work_dir
        folder = os.path.dirname(db_fp)
        os.makedirs(folder, exist_ok=True)
        refuseNetworkFolder(folder)
        self.con = None
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

    def writePendingSection(self, snum : int, section_data : dict):
        """A section's working copy (Section.save), as its hidden file was."""
        with self._tx(sync="NORMAL"):
            self.con.execute(
                "INSERT OR REPLACE INTO pending_section(snum, data) VALUES (?, ?)",
                (snum, fast_dumps(section_data)),
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

    def readSection(self, snum : int, fallback_fp : str = None) -> dict:
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

    def _assemble(self, snum : int, header : dict) -> dict:
        names = header["contours"]
        contours = {name: [] for name in names}
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
        self.con.execute("DELETE FROM trace_stats WHERE snum=?", (snum,))
        self.con.execute(
            "INSERT OR REPLACE INTO section(snum, header, stats_valid) VALUES (?, ?, 0)",
            (snum, header),
        )
        self.con.executemany(
            f"INSERT INTO trace({TRACE_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )

    def _dropSection(self, snum : int):
        for table in ("trace", "trace_stats", "section"):
            self.con.execute(f"DELETE FROM {table} WHERE snum=?", (snum,))

    def _writeStats(self, snum : int, contour_names : list, tform_keys, series, objects):
        """The object-list numbers of one section, from a SeriesData's objects."""
        rows = []
        for cpos, name in enumerate(contour_names):
            obj = objects.get(name)
            if obj is None:
                continue
            key = tformKey(series, name, tform_keys)
            for td in obj.traces.get(snum, ()):
                rows.append((
                    snum, cpos, td.index, name, key,
                    int(bool(td.closed)), int(bool(td.hidden)), int(bool(td.negative)),
                    None if td.color is None else fast_dumps(list(td.color)).decode(),
                    fast_dumps(sorted(td.tags, key=str)).decode(),
                    td.length, td.area, td.centroid[0], td.centroid[1], td.radius,
                ))
        self.con.execute("DELETE FROM trace_stats WHERE snum=?", (snum,))
        self.con.executemany(
            "INSERT INTO trace_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        self.con.execute("UPDATE section SET stats_valid=1 WHERE snum=?", (snum,))

    def commit(self, series):
        """Save: fold the working layer into the saved tables, one transaction.

        Cost follows the sections changed since the last Save, not the series.
        The object-list numbers of each changed section are measured again from
        its saved rows, exactly as a full open would measure them: the numbers
        the session holds come from unsaved points and can differ in the last
        bit from the saved ones.
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
            for snum, data in sorted(pending.items()):
                if data is None or snum not in series.sections:
                    self._dropSection(snum)
                    continue
                self._replaceSection(snum, fast_loads(data))
                replaced.append(snum)
            self.con.execute("DELETE FROM pending_section")
            self._measure(series, replaced)
            row = self.con.execute("SELECT data FROM pending_series").fetchone()
            if row is not None:
                self.con.execute("INSERT OR REPLACE INTO series(id, data) VALUES (1, ?)", row)
            log_fp = os.path.join(series.getwdir(), "existing_log.csv")
            if os.path.isfile(log_fp):
                with open(log_fp, "r", encoding="utf-8", errors="replace") as f:
                    self.con.execute(
                        "INSERT OR REPLACE INTO log(id, text) VALUES (1, ?)", (f.read(),)
                    )
            self.con.execute("DELETE FROM pending_section")
            self.con.execute("DELETE FROM pending_series")
            if pending or row is not None:
                self.setMeta("dirty", 1)

    def markExported(self, jser_fp : str):
        with self._tx():
            self.recordJser(jser_fp)
            self.setMeta("dirty", 0)
            self.setMeta("exported_utc", _now())

    ## import -----------------------------------------------------------------

    def importJser(self, jser_fp : str, jser_data : dict, collisions : dict, reporter=None):
        """Write a parsed .jser into the store, migrated exactly as openJser migrates it."""
        from .section import Section
        from .series import Series, applyContourRenames

        sections = jser_data["sections"]
        total = sum(1 for s in sections if s is not None) + 1
        done = 0
        self.con.execute("PRAGMA journal_mode=TRUNCATE")
        try:
            with self._tx():
                for table in ("series", "log", "section", "trace", "trace_stats",
                              "pending_section", "pending_series"):
                    self.con.execute(f"DELETE FROM {table}")
                renames = {}
                for snum, section_data in enumerate(sections):
                    if section_data is None:
                        continue
                    stored_ids = {}
                    renames.update(Section.updateJSON(section_data, snum, stored_ids=stored_ids))
                    if stored_ids:
                        Section.reattachTraceIDs(section_data, stored_ids)
                    # every section locks on open (see Series.openJser)
                    section_data["align_locked"] = True
                    self._replaceSection(snum, section_data)
                    sections[snum] = None  # free it as it goes
                    done += 1
                    if reporter is not None:
                        reporter.set_progress(done / total * 50)
                self.con.execute(
                    "INSERT INTO log(id, text) VALUES (1, ?)", (jser_data["log"],)
                )
                series_data = jser_data["series"]
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
        series.store = self
        self.loadSeriesData(series)
        series._repointBCProfile()
        return series

    def loadSeriesData(self, series):
        """Fill series.data from the stored numbers; measure only what is stale.

        A section is measured for real (loaded and run through
        SeriesData.updateSection, as a full open does) when it has pending work,
        has no stored numbers, or has a number computed in an alignment its
        object would not use now.
        """
        from .section import Section, TransformsDict
        from .transform import Transform
        from .flag import Flag
        from .series_data import TraceData, ObjectData

        data = series.data
        data.data = {"sections": {}, "objects": {}}
        objects = data.data["objects"]
        pending = {r[0] for r in self.con.execute("SELECT snum FROM pending_section")}
        valid = dict(self.con.execute("SELECT snum, stats_valid FROM section"))
        recompute = []
        headers = {}

        for snum in sorted(series.sections):
            if snum in pending or not valid.get(snum):
                recompute.append(snum)
                continue
            h = fast_loads(self.con.execute(
                "SELECT header FROM section WHERE snum=?", (snum,)
            ).fetchone()[0])
            tforms = TransformsDict()
            for a, t in h["tforms"].items():
                tforms[a] = Transform(t)
            headers[snum] = (h, tforms)

        for snum, (h, tforms) in headers.items():
            names = h["contours"]
            rows = self.con.execute(
                "SELECT cpos, idx, tform_key, closed, hidden, negative, color, tags,"
                " length, area, cx, cy, radius FROM trace_stats WHERE snum=?"
                " ORDER BY cpos, idx",
                (snum,),
            ).fetchall()
            keys = {}
            stale = False
            for r in rows:
                name = names[r[0]]
                if name not in keys:
                    keys[name] = tformKey(series, name, tforms)
                if keys[name] != r[2]:
                    stale = True
                    break
            if stale:
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
            for (cpos, idx, key, closed, hidden, negative, color, tags,
                 length, area, cx, cy, radius) in rows:
                name = names[cpos]
                td = TraceData.__new__(TraceData)
                td.index = idx
                td.closed = bool(closed)
                td.hidden = bool(hidden)
                td.negative = bool(negative)
                td.tags = set(fast_loads(tags))
                td.color = None if color is None else tuple(fast_loads(color))
                td.length = length
                td.area = area
                td.centroid = (cx, cy)
                td.radius = radius
                td._tform = tforms[key]
                td._feret = None if td.closed else (0, 0)
                obj = objects.get(name)
                if obj is None:
                    obj = objects[name] = ObjectData()
                obj.traces.setdefault(snum, []).append(td)

        for snum in sorted(recompute):
            section = series.loadSection(snum)
            data.updateSection(section, update_traces=True, log_events=False, read_store=True)

        data.object_ids.reconcile(
            (snum, name)
            for name, obj_data in data.data["objects"].items()
            for snum in obj_data.traces
        )
        self.recomputed = sorted(recompute)

    def _measure(self, series, section_numbers):
        """Measure saved sections as a full open does, and store the numbers."""
        from .section import Section
        from .series_data import SeriesData

        scratch = SeriesData(series)
        for snum in section_numbers:
            section = Section(snum, series)
            scratch.updateSection(section, update_traces=True, log_events=False, read_store=True)
            h = fast_loads(self.con.execute(
                "SELECT header FROM section WHERE snum=?", (snum,)
            ).fetchone()[0])
            self._writeStats(
                snum, h["contours"], set(h["tforms"]) | {"no-alignment"},
                series, scratch.objects,
            )
            scratch.clearSection(snum)

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


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        if not store.isImported():
            jser_data, collisions = Series._readJserForOpen(jser_fp, notifier)
            if jser_data is None:
                store.close()
                return None
            store.importJser(jser_fp, jser_data, collisions, reporter)
            del jser_data
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
    except BaseException:
        store.close()
        raise
    finally:
        reporter.finish()
    return series
