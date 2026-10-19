"""Open a series from its local store (hybrid_store.py), behind a switch.

Turned on by ``PYRECON_HYBRID_STORE=1`` and by nothing else; off, no code here
runs and no store is made. With it on, `Series.openJser` does this when there
is no working folder to resume:

  * The store holds this .jser (same size and modification time as when it
    was imported) and the object-list numbers of its last import: the open
    writes the working folder from the store, the same files today's open
    writes, and fills the object list from the stored numbers. No section is
    loaded, and the .jser is not read.
  * Otherwise: today's open, unchanged, and then the working folder it wrote
    and the numbers it measured go into the store for the next open.

The store is a copy of the .jser and nothing else: Save, close and export are
today's, and a store that no longer matches its .jser is imported again.

When the store cannot be used (its folder is on a network file system,
another process holds it, it is not a store this version reads, or reading it
fails), the open is today's open, with one line in the log and no dialog.
Only `StoreUnavailable` is caught for that, so a fault in this code still
raises.
"""

import gc
import json
import os
import sqlite3
from contextlib import contextmanager

import numpy as np

from PyReconstruct.modules.constants import fast_loads, fast_dumps
from PyReconstruct.modules.constants.fast_json import stdlib_dumps
from PyReconstruct.modules.constants.jser_splice import SpliceIndex, _stat_key

from .hybrid_store import HybridStore, storePaths
from .network_folder import networkFileSystem

ENV_SWITCH = "PYRECON_HYBRID_STORE"

## The object-list numbers of one section, a blob per field. tags and colors:
## the section's distinct values (stdlib JSON, which reads back any value a
## section holds: an integer past 64 bits, NaN, a lone surrogate); the rest
## one entry per trace, in contour then trace order.
STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS section_stats(
    snum INTEGER PRIMARY KEY,
    tags BLOB NOT NULL, colors BLOB NOT NULL,
    cpos BLOB NOT NULL, idx BLOB NOT NULL, flags BLOB NOT NULL,
    tag BLOB NOT NULL, color BLOB NOT NULL,
    length BLOB NOT NULL, area BLOB NOT NULL,
    cx BLOB NOT NULL, cy BLOB NOT NULL, radius BLOB NOT NULL
)
"""
STATS_TYPES = {
    "cpos": "<i4", "idx": "<i4", "flags": "u1", "tag": "<i4", "color": "<i4",
    "length": "<f8", "area": "<f8", "cx": "<f8", "cy": "<f8", "radius": "<f8",
}
STATS_COLS = "tags, colors, " + ", ".join(STATS_TYPES)
CLOSED, HIDDEN, NEGATIVE = 1, 2, 4
## meta: set once every section's numbers are stored for the last import
META_STATS = "open_stats"
## meta: where the .jser's sections sit in it, for the first Save's splice
META_SPLICE = "open_splice"


class StoreUnavailable(Exception):
    """The local store cannot be used for this open; open the .jser as today."""


def enabled() -> bool:
    """True when the store switch is on."""
    return os.environ.get(ENV_SWITCH) == "1"


def log_note(message : str):
    """One line in the app's log (logging_setup.py)."""
    # backend.func's package imports this one's, so not at the top
    from PyReconstruct.modules.backend.func.logging_setup import log_note as note
    note(message)


def _unavailable(jser_fp : str, err : Exception):
    log_note(f"Local store not used for {os.path.basename(jser_fp)}: {err}")


def openJser(fp : str, progress=None, notifier=None):
    """Series.openJser with the switch on, when there is no working folder to resume.

    From the store when it holds this .jser; else today's open, kept in the
    store afterwards. Returns what Series.openJser returns.
    """
    from .series import Series, _default_progress_reporter_factory

    held = StoreForOpen.attempt(fp)
    if held is None:
        return Series._unpackJser(fp, progress, notifier)[0]
    try:
        try:
            if held.holdsJser():
                with _gcPaused():
                    return Series._unpackJser(fp, progress, notifier, store=held)[0]
        except StoreUnavailable as e:
            # a read failed partway: the open put back what it changed
            _unavailable(fp, e)
            held.close()
            held = None
            return Series._unpackJser(fp, progress, notifier)[0]
        series, collisions = Series._unpackJser(fp, progress, notifier)
        if series is not None:
            factory = progress if progress is not None else _default_progress_reporter_factory()
            reporter = factory(text=f"Keeping a local copy of {series.name} for faster opening...")
            try:
                held.importOpened(series, collisions, reporter)
            finally:
                reporter.finish()
        return series
    finally:
        if held is not None:
            held.close()


class StoreForOpen():

    def __init__(self, store : HybridStore, jser_fp : str):
        """A series' store, held for one open (its lock is the store's own).

        Made by `attempt`; `close` lets go of it.
        """
        self.store = store
        self.jser_fp = jser_fp
        self.stat = os.stat(jser_fp)

    @staticmethod
    def attempt(jser_fp : str):
        """The .jser's store, or None (and one log line) when it cannot be used."""
        try:
            return StoreForOpen._open(jser_fp)
        except StoreUnavailable as e:
            _unavailable(jser_fp, e)
            return None

    @staticmethod
    def _open(jser_fp : str) -> "StoreForOpen":
        try:
            db_fp, work_dir = storePaths(jser_fp)
            folder = os.path.dirname(db_fp)
            remote = networkFileSystem(folder)
            if remote:
                raise StoreUnavailable(
                    f"the store folder {folder} is on a network file system ({remote})"
                )
            store = HybridStore(db_fp, work_dir)
        except (OSError, sqlite3.Error) as e:
            # busy (StoreBusyError), another schema (StoreSchemaError), a
            # network folder (Linux), or the folder cannot be made
            raise StoreUnavailable(str(e)) from e
        try:
            store.con.execute(STATS_SCHEMA)
            return StoreForOpen(store, jser_fp)
        except (OSError, sqlite3.Error) as e:
            store.close()
            raise StoreUnavailable(str(e)) from e
        except BaseException:
            store.close()
            raise

    def close(self):
        self.store.close()

    ## reading -----------------------------------------------------------------

    def holdsJser(self) -> bool:
        """True when an open can come from the store: it holds this .jser as
        imported, every section's numbers, and nothing else.

        A store with work in its working layer or saved past its .jser (later
        steps write those) is not read here.
        """
        store = self.store
        try:
            if not store.isImported() or not store.matchesJser(self.jser_fp):
                return False
            if store.hasPending() or store.meta("dirty") != "0":
                return False
            if store.meta(META_STATS) != store.meta("imported_utc"):
                return False
            stored = {r[0] for r in store.con.execute("SELECT snum FROM section_stats")}
            return stored == set(store.sectionNumbers())
        except (OSError, sqlite3.Error) as e:
            raise StoreUnavailable(str(e)) from e

    def source(self) -> "_StoreSource":
        """The store as `Series._unpackJser` reads a .jser."""
        return _StoreSource(self.store)

    def spliceIndex(self):
        """The splice index the last import recorded, if the .jser is still that file."""
        try:
            raw = self.store.meta(META_SPLICE)
        except sqlite3.Error as e:
            raise StoreUnavailable(str(e)) from e
        if not raw:
            return None
        doc = fast_loads(raw)
        stat_key = tuple(doc["stat_key"])
        try:
            if _stat_key(os.stat(self.jser_fp)) != stat_key:
                return None
        except OSError:
            return None
        ranges = {}
        for key, offset, length, digest in doc["ranges"]:
            ranges[bytes.fromhex(key)] = (offset, length, bytes.fromhex(digest))
        return SpliceIndex(self.jser_fp, stat_key, ranges)

    def fillSeriesData(self, series):
        """Fill series.data from the stored numbers, as a full open fills it.

        Every object holds its rows of one shared `TraceColumns`, so no
        TraceData is built until something reads an object's traces
        (series_data.ObjectData). An object whose fixed alignment a section
        lacks has it cleared, as `ObjectData.addTrace` clears it on a full
        open.
        """
        try:
            _fillSeriesData(self.store, series)
        except (OSError, sqlite3.Error) as e:
            raise StoreUnavailable(str(e)) from e

    ## writing -----------------------------------------------------------------

    def importOpened(self, series, collisions, reporter=None):
        """Keep what today's open just wrote and measured, for the next open.

        The working folder's files go into the store through its own import
        (`HybridStore.importJser`), then every section's object-list numbers
        from series.data. A failure leaves no numbers recorded, so the store
        is not read, and is reported in the log; the opened series is not
        touched either way.

            Params:
                series (Series): the series today's open returned
                collisions (dict): the contour-name collisions that open merged
                reporter: an optional ProgressReporter
        """
        name = os.path.basename(self.jser_fp)
        if collisions:
            # the merge was asked about; a later open must ask again
            log_note(f"Local store not kept for {name}: its objects were merged on open")
            return
        store = self.store
        try:
            if store.hasPending() or store.meta("dirty") == "1":
                # work a later version left in the store is never replaced
                log_note(f"Local store not kept for {name}: it holds work the .jser lacks")
                return
            with _transaction(store):
                store.con.execute("DELETE FROM section_stats")
                store.setMeta(META_STATS, None)
                store.setMeta(META_SPLICE, None)
            source = _WorkingFolderSource(series)
            # the alignments as the open found them, before it measured
            alignments = _Alignments(source.series["alignment"], source.series["obj_attrs"])
            store.importJser(self.jser_fp, source, {}, reporter, migrated=True)
            stats = [
                (snum, *_statsRow(series.data.objects, alignments, snum, header))
                for snum, header in _headers(store)
            ]
            with _transaction(store):
                store.con.executemany(
                    f"INSERT INTO section_stats(snum, {STATS_COLS})"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    stats,
                )
                # the .jser as this open read it: if it changed since, the
                # next open imports it again
                store.setMeta("jser_size", self.stat.st_size)
                store.setMeta("jser_mtime_ns", self.stat.st_mtime_ns)
                store.setMeta(META_SPLICE, _spliceMeta(getattr(series, "_jser_splice_index", None)))
                store.setMeta(META_STATS, store.meta("imported_utc"))
        except _NotMeasuredAlike as e:
            log_note(f"Local store not kept for {os.path.basename(self.jser_fp)}: {e}")
        except (OSError, sqlite3.Error) as e:
            _unavailable(self.jser_fp, e)


## ---------------------------------------------------------------------------
## the store and the working folder, as Series._unpackJser reads a .jser
## ---------------------------------------------------------------------------

class _StoreSource():

    ## The sections are stored as today's open writes them, after
    ## Section.updateJSON: the open writes them as they are
    migrated = True

    def __init__(self, store : HybridStore):
        self.store = store
        try:
            self.snums = store.sectionNumbers()
            self.series = store.seriesData()
            self.log = store.logText()
        except (OSError, sqlite3.Error) as e:
            raise StoreUnavailable(str(e)) from e

    def sectionCount(self) -> int:
        return len(self.snums)

    def sections(self):
        for snum in self.snums:
            try:
                section_data = self.store.readSection(snum)
            except (OSError, sqlite3.Error) as e:
                raise StoreUnavailable(str(e)) from e
            yield snum, section_data, None

    def unchangedStat(self):
        return None

    def close(self):
        pass


class _WorkingFolderSource():
    """An opened series' working folder, as `HybridStore.importJser` reads a .jser.

    Its files are what today's open wrote, already migrated, so the import
    stores them as they are (`migrated=True`). They are read as
    Section.__init__ reads them.
    """

    def __init__(self, series):
        wdir = series.getwdir()
        self.files = {
            snum: os.path.join(wdir, fname) for snum, fname in sorted(series.sections.items())
        }
        with open(series.filepath, "rb") as f:
            self.series = fast_loads(f.read())
        with open(os.path.join(wdir, "existing_log.csv"), "r", encoding="utf-8") as f:
            self.log = f.read()

    def sectionCount(self) -> int:
        return len(self.files)

    def sections(self):
        for snum, fp in self.files.items():
            with open(fp, "rb") as f:
                yield snum, fast_loads(f.read()), None


class _transaction():

    def __init__(self, store : HybridStore):
        self.con = store.con

    def __enter__(self):
        self.con.execute("PRAGMA synchronous=FULL")
        self.con.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type, exc, tb):
        self.con.execute("COMMIT" if exc_type is None else "ROLLBACK")
        return False


## ---------------------------------------------------------------------------
## the numbers
## ---------------------------------------------------------------------------

class _NotMeasuredAlike(Exception):
    """The open measured an object in an alignment the stored numbers would not name."""


@contextmanager
def _gcPaused():
    """Keep the cyclic collector out of a bulk read that makes no cycles.

    An open from the store makes a few objects per trace; left on, the
    collector walked the growing heap many times over (most of 3 s of a
    10 s open on a 550,000-trace series, measured on the prototype).
    Reference counting still frees everything as usual.
    """
    was_on = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_on:
            gc.enable()


def _headers(store : HybridStore):
    """(section number, header) for every saved section, in order.

    Read with the JSON reader the store wrote it with (hybrid_store.py,
    `section.exact`): fast_loads would read an integer past 64 bits as a float.
    """
    for snum, header, exact in store.con.execute(
        "SELECT snum, header, exact FROM section ORDER BY snum"
    ):
        yield snum, (json.loads if exact else fast_loads)(header)


class _Alignments():

    def __init__(self, series_alignment : str, obj_attrs : dict):
        """Which alignment each object's numbers are in, section by section.

        `ObjectData.addTrace` measures an object in its fixed alignment, or
        the series' when it has none; when a section lacks the fixed one it
        clears it, and every later section uses the series'. A full open adds
        the sections in order, so the alignments are replayed in that order.
        """
        self.default = series_alignment
        self.fixed = {
            name: attrs["alignment"] for name, attrs in obj_attrs.items()
            if attrs.get("alignment") is not None
        }
        self.cleared : list = []

    def of(self, name : str, tforms) -> str:
        alignment = self.fixed.get(name)
        if alignment is None:
            return self.default
        if alignment not in tforms:
            del self.fixed[name]
            self.cleared.append(name)
            return self.default
        return alignment


def _statsRow(objects : dict, alignments : _Alignments, snum : int, header : dict) -> tuple:
    """One section's stored numbers, from the series data a full open built.

    Called for every section in order, so `alignments` replays the open.
    """
    tforms = _transforms(header)
    tag_ids : dict = {}
    color_ids : dict = {}
    cols : dict = {field: [] for field in STATS_TYPES}
    for cpos, name in enumerate(header["contours"]):
        obj = objects.get(name)
        tds = obj.traces.get(snum) if obj is not None else None
        if not tds:
            continue
        key = alignments.of(name, tforms)
        if tforms[key].getList() != tds[0]._tform.getList():
            raise _NotMeasuredAlike(
                f"section {snum}, {name}: measured in another alignment than {key}"
            )
        for td in tds:
            tags = stdlib_dumps(sorted(td.tags, key=repr))
            color = None if td.color is None else stdlib_dumps(list(td.color))
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
    return (
        b"[" + b",".join(tag_ids) + b"]",
        b"[" + b",".join(color_ids) + b"]",
        *(np.array(cols[f], dtype=dtype).tobytes() for f, dtype in STATS_TYPES.items()),
    )


def _transforms(header : dict):
    """A section header's transforms, as Section.__init__ holds them."""
    from .section import TransformsDict
    from .transform import Transform

    tforms = TransformsDict()
    for a, t in header["tforms"].items():
        tforms[a] = Transform(t)
    return tforms


def _spliceMeta(index):
    if index is None:
        return None
    return bytes(fast_dumps({
        "stat_key": list(index.stat_key),
        "ranges": [
            [key.hex(), offset, length, digest.hex()]
            for key, (offset, length, digest) in index.ranges.items()
        ],
    })).decode("ascii")


def _fillSeriesData(store : HybridStore, series):
    from .section import Section
    from .flag import Flag
    from .series_data import ObjectData, TraceColumns

    data = series.data
    data.data = {"sections": {}, "objects": {}}
    objects = data.data["objects"]
    alignments = _Alignments(series.alignment, series.obj_attrs)

    name_ids : dict = {}       # name -> object number, in order of first trace
    tform_list : list = []
    tag_ids : dict = {}        # stored tags -> index in tag_values
    tag_values : list = []
    color_ids : dict = {None: 0}
    color_values : list = [None]
    parts : dict = {f: [] for f in TraceColumns.FIELDS}
    parts["object"] = []

    stats_of = {
        row[0]: row[1:] for row in store.con.execute(
            f"SELECT snum, {STATS_COLS} FROM section_stats"
        )
    }
    for snum, h in _headers(store):
        stats = stats_of[snum]
        tforms = _transforms(h)
        names = h["contours"]
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
        arrays = {
            f: np.frombuffer(blob, dtype=dtype)
            for (f, dtype), blob in zip(STATS_TYPES.items(), stats[2:])
        }
        cpos = arrays["cpos"]
        if not len(cpos):
            continue
        # contour position -> object number and transform number
        object_of = np.zeros(len(names), dtype=np.int32)
        tform_of = np.zeros(len(names), dtype=np.int32)
        section_tforms : dict = {}
        for p in np.unique(cpos).tolist():
            object_of[p] = name_ids.setdefault(names[p], len(name_ids))
            key = alignments.of(names[p], tforms)
            if key not in section_tforms:
                section_tforms[key] = len(tform_list)
                tform_list.append(tforms[key])
            tform_of[p] = section_tforms[key]
        # the section's distinct tags and colors -> the series-wide ones
        tag_of = []
        for value in json.loads(stats[0]):
            stored = tuple(value)
            if stored not in tag_ids:
                tag_ids[stored] = len(tag_values)
                tag_values.append(frozenset(value))
            tag_of.append(tag_ids[stored])
        color_of = []
        for value in json.loads(stats[1]):
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

    # as ObjectData.addTrace does on a full open
    for name in alignments.cleared:
        series.setAttr(name, "alignment", None)

    if not parts["object"]:
        return
    obj_num = np.concatenate(parts["object"])
    # each object's rows together, keeping section then trace order
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
        obj_num[starts].tolist(), starts.tolist(), stops.tolist(), first_pair, last_pair,
    ):
        name = names_in_order[num]
        objects[name] = ObjectData(columns, start, stop)
        by_name.append((name, pair_snums[a:b]))
    data.object_ids.placeAll(by_name)

