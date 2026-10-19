"""Save, close and export a series through its local store, behind the switch.

Works only for a series whose open came from its store or kept one
(store_open.py). With PYRECON_HYBRID_STORE off a series holds no store, so the
checks Save, close and the File menu make here find none and return. That open
hands the store to the series, which holds it (and its lock) until it closes,
so no other window writes the store meanwhile.

Two ways to save, picked by `saveMode` (an internal value, not a setting):

  * ``store`` (the default): Save writes the store alone. The .jser is
    written from the store when the series closes, or by File > Export
    series > To .jser now, and only when the store is ahead of it. The
    automatic backup is made then, not at Save.
  * ``jser``: Save writes the .jser as today. Then the store takes the
    sections whose working files changed, the series and the log, and records
    the new file's sha256 and splice index, so the next open comes from the
    store.

The store holds each section as an open of the .jser just saved writes it
(an open migrates every section it reads: Section.updateJSON). For nearly
every section that is its working file, byte for byte. A store-only Save
keeps only sections for which it is, so the .jser written from the store is
the file today's Save writes from the working folder, and it splices the same
way: a section is keyed by the sha256 of its working file's bytes, as
`JserSplice` keys it.

The object-list numbers of a section that changed are measured again from its
saved file, as a full open of the new .jser measures them, alignments
replayed in section order (store_open._Alignments). So are the numbers of a
section that did not change but whose objects a full open would now measure
in another transform (a fixed alignment changed or was cleared).

When the store cannot hold a Save exactly (a section an open would migrate
again, a working file that changed while it was saved, a store that cannot
be written), it gives up its claim on the .jser, so the next open is today's
and keeps the store again, and the series lets go of it. A store-only Save
then writes the .jser as today instead, so no Save is ever lost to the store.
"""

import hashlib
import os
import sqlite3

import numpy as np

from PyReconstruct.modules.constants import fast_loads, fast_dumps
from PyReconstruct.modules.constants.jser_splice import KeyedSection, section_digest

## Picks how Save writes: "jser" or "store" (tests and benchmarks; no setting)
ENV_MODE = "PYRECON_HYBRID_STORE_SAVE"
MODE_JSER = "jser"
MODE_STORE = "store"
DEFAULT_MODE = MODE_STORE

## One row per saved section: the sha256 of the working file's bytes it was
## stored from; whether the stored section is what an open of a .jser holding
## those bytes writes (`opens_alike`); and whether it is those bytes
## (`as_working`)
KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS section_key(
    snum INTEGER PRIMARY KEY,
    key BLOB NOT NULL,
    opens_alike INTEGER NOT NULL,
    as_working INTEGER NOT NULL
)
"""

## meta: "1" while the store holds a Save the .jser lacks (hybrid_store.py)
META_DIRTY = "dirty"
## meta: when the store last took a Save the .jser lacks (UTC)
META_SAVED = "saved_utc"
## meta: the sha256 of the .jser `writeJser` is writing, kept from just before
## the file is put in place until the store records it (store_recovery.py)
META_WRITING = "writing_sha256"


class NotKept(Exception):
    """The store cannot hold this Save exactly."""


def saveMode() -> str:
    """How Save writes with the store on: MODE_STORE unless ENV_MODE says "jser"."""
    return MODE_JSER if os.environ.get(ENV_MODE) == MODE_JSER else DEFAULT_MODE


## ---------------------------------------------------------------------------
## the store a series holds
## ---------------------------------------------------------------------------

def attach(series, held):
    """Give the series the store its open came from or kept (a StoreForOpen)."""
    series._local_store = held


def heldStore(series):
    """The StoreForOpen the series holds, or None."""
    return getattr(series, "_local_store", None)


def release(series):
    """Let go of the series' store, if it holds one."""
    held = heldStore(series)
    if held is not None:
        series._local_store = None
        held.close()


def savesToStoreOnly(series) -> bool:
    """True when Save writes the series' store and not its .jser."""
    return heldStore(series) is not None and saveMode() == MODE_STORE


def ahead(series) -> bool:
    """True when the series' store holds a Save its .jser lacks."""
    held = heldStore(series)
    if held is None:
        return False
    try:
        return held.store.meta(META_DIRTY) == "1"
    except sqlite3.Error as e:
        _raiseIfBug(e)
        # the store cannot say: the .jser is written, as a Save would
        return True


def closing(series):
    """Before the series closes: write its .jser if the store is ahead, let go of it.

    A write that fails raises, and the series keeps its store and its working
    folder, so nothing it saved is lost.
    """
    if heldStore(series) is None:
        return
    if ahead(series):
        writeJser(series)
    release(series)


## ---------------------------------------------------------------------------
## keys
## ---------------------------------------------------------------------------

def openedSection(raw : bytes, snum : int, section_data=None):
    """The section an open of a .jser that holds these working-file bytes writes.

    What Series._unpackJser does to a section it reads from a .jser, but for
    locking its alignment (an open from the store does that too). None when
    that open would rename objects: it renames them in the series too.

        Params:
            section_data (dict): `raw` already parsed, changed here; or None
    """
    from .section import Section

    if section_data is None:
        section_data = fast_loads(raw)
    stored_ids : dict = {}
    if Section.updateJSON(section_data, snum, stored_ids=stored_ids):
        return None
    if stored_ids:
        Section.reattachTraceIDs(section_data, stored_ids)
    return section_data


def opensAlike(raw : bytes, snum : int, section_data=None) -> bool:
    """True when an open of a .jser holding a working file writes it back as it is."""
    opened = openedSection(raw, snum, section_data)
    return opened is not None and fast_dumps(opened) == raw


def recordKeys(store, keys : dict):
    """Keep each section's key, as `keys` gives it (snum -> (key, opens alike)).

    The import stores each working file as it is. Called inside its last
    transaction (store_open.importOpened).
    """
    store.con.execute(KEYS_SCHEMA)
    store.con.execute("DELETE FROM section_key")
    store.con.executemany(
        "INSERT INTO section_key(snum, key, opens_alike, as_working) VALUES (?, ?, ?, 1)",
        [(snum, key, int(alike)) for snum, (key, alike) in sorted(keys.items())],
    )


def _keys(store) -> dict:
    """snum -> (key, opens alike, as working), for every saved section."""
    store.con.execute(KEYS_SCHEMA)
    return {
        snum: (bytes(key), bool(alike), bool(working))
        for snum, key, alike, working in store.con.execute(
            "SELECT snum, key, opens_alike, as_working FROM section_key"
        )
    }


## ---------------------------------------------------------------------------
## Save
## ---------------------------------------------------------------------------

def saved(series, keys : dict, tail : dict, digest, index):
    """After Save wrote the series' own .jser: the store takes what it wrote.

        Params:
            series (Series): the series just saved
            keys (dict): section number -> the sha256 of the working file the
                save wrote for it
            tail (dict): the series and log the save wrote
            digest (str): the sha256 of the file written, or None when the
                write could not hash it (then the file is hashed here)
            index (SpliceIndex): the new file's splice index, or None
    """
    from . import store_open

    held = heldStore(series)
    if held is None:
        return
    try:
        if digest is None:
            digest = store_open.jserDigest(series.jser_fp)
        _commit(series, held, keys, tail, (digest, index))
    except (NotKept, store_open.StoreUnavailable, OSError, sqlite3.Error) as e:
        _raiseIfBug(e)
        _giveUp(series, held, e)


def saveToStore(series, keys : dict, tail : dict) -> bool:
    """A store-only Save. False when the store could not take it, and is as it was.

    On False nothing the user saved is lost: the working folder holds it, and
    the caller writes the .jser as today (`saved` then lets go of a store that
    still cannot keep it).
    """
    from . import store_open

    held = heldStore(series)
    if held is None:
        return False
    try:
        _commit(series, held, keys, tail, None)
        return True
    except (NotKept, store_open.StoreUnavailable, OSError, sqlite3.Error) as e:
        _raiseIfBug(e)
        store_open.log_note(f"Saved to {os.path.basename(series.jser_fp)}, not the local store: {e}")
        return False


def _raiseIfBug(err : Exception):
    from .store_open import _raiseIfBug as raise_if_bug
    raise_if_bug(err)


def _giveUp(series, held, err : Exception):
    """The store gives up its claim on the .jser and the series lets go of it.

    Called only once the .jser holds the Save, so nothing in the store is
    ahead of it. The next open is today's, and keeps the store again.
    """
    from . import store_open

    store_open.log_note(f"Local store not kept in step with {os.path.basename(series.jser_fp)}: {err}")
    store = held.store
    try:
        with store_open._transaction(store):
            store.setMeta(store_open.META_SHA, None)
            store.setMeta(store_open.META_STATS, None)
            store.setMeta(META_DIRTY, 0)
    except sqlite3.Error as e:
        _raiseIfBug(e)
        # left as it was, and its hash still names the last .jser it held:
        # an open reads it only for that file's bytes
    release(series)


def _commit(series, held, keys : dict, tail : dict, written):
    """Fold a Save from the working folder into the store, in one transaction.

        Params:
            written: (sha256, SpliceIndex) of the .jser the Save wrote, or
                None for a store-only Save
        Raises:
            NotKept: the store cannot hold this Save exactly; nothing changed
    """
    from . import store_open
    from .hybrid_store import packSection

    store = held.store
    wdir = series.getwdir()
    stored_keys = _keys(store)
    if not _statsComplete(store) or set(stored_keys) != set(store.sectionNumbers()):
        raise NotKept("the store does not hold every section's numbers and key")

    # the sections the store must take: a working file that changed, or one
    # the store does not hold as the next open writes it
    changed = {}
    for snum in sorted(series.sections):
        stored = stored_keys.get(snum)
        if stored is not None and stored[0] == keys[snum]:
            _, alike, working = stored
            if alike and (written is not None or working):
                continue
            if written is None:
                # held as an open writes it, so the .jser written from it
                # would not be today's
                raise NotKept(f"section {snum} is not held as it is saved")
        with open(os.path.join(wdir, series.sections[snum]), "rb") as f:
            raw = f.read()
        if section_digest(raw) != keys[snum]:
            raise NotKept(f"the working file of section {snum} changed while it was saved")
        try:
            opened = openedSection(raw, snum)
        except ValueError as e:
            raise NotKept(f"the working file of section {snum} could not be read ({e})") from e
        if opened is None:
            raise NotKept(f"an open would rename objects in section {snum}")
        data = fast_dumps(opened)
        if written is None and data != raw:
            raise NotKept(f"an open would write section {snum} otherwise than it is saved")
        changed[snum] = (opened, data, data == raw)
    dropped = sorted(set(stored_keys) - set(series.sections))

    series_bytes = fast_dumps(tail["series"])
    if fast_dumps(fast_loads(series_bytes)) != series_bytes:
        raise NotKept("the series does not read back as it was written")
    try:
        tail["log"].encode("utf-8")
    except UnicodeEncodeError as e:
        # SQLite text is UTF-8: a lone surrogate cannot be stored
        raise NotKept(f"the log holds text the store cannot keep ({e.reason})") from e

    with store_open._transaction(store):
        old_series = _opened(store.seriesData())
        new_series = _opened(fast_loads(series_bytes))
        content_changed = bool(changed or dropped) or fast_dumps(old_series) != fast_dumps(new_series)
        stats = _remeasure(series, store, changed, old_series, new_series)
        for snum in dropped:
            store._dropSection(snum)
            store.con.execute("DELETE FROM section_stats WHERE snum=?", (snum,))
            store.con.execute("DELETE FROM section_key WHERE snum=?", (snum,))
        for snum, (opened, data, as_working) in changed.items():
            header, exact, rows = packSection(snum, opened)
            store.con.execute("DELETE FROM trace WHERE snum=?", (snum,))
            store.con.execute(
                "INSERT OR REPLACE INTO section(snum, header, exact) VALUES (?, ?, ?)",
                (snum, header, exact),
            )
            store.con.executemany(
                f"INSERT INTO trace({_trace_cols()}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
            )
            # read back as an open from the store reads it
            if fast_dumps(store.readSection(snum)) != data:
                raise NotKept(f"section {snum} does not read back from the store as it was stored")
            store.con.execute(
                "INSERT OR REPLACE INTO section_key(snum, key, opens_alike, as_working)"
                " VALUES (?, ?, 1, ?)",
                (snum, keys[snum], int(as_working)),
            )
        for snum, row in stats.items():
            store.con.execute(
                f"INSERT OR REPLACE INTO section_stats(snum, {store_open.STATS_COLS})"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (snum, *row),
            )
        # the series as the .jser holds it, so the .jser written from the
        # store is today's; an open migrates it as it migrates the .jser's
        store.con.execute("INSERT OR REPLACE INTO series(id, data) VALUES (1, ?)", (series_bytes,))
        if tail["log"] != store.logText():
            content_changed = True
            store.con.execute("INSERT OR REPLACE INTO log(id, text) VALUES (1, ?)", (tail["log"],))
        if written is not None:
            digest, index = written
            store.recordJser(series.jser_fp)
            store.setMeta(store_open.META_SHA, digest)
            store.setMeta(store_open.META_SPLICE, store_open._spliceMeta(_asOpened(index, store)))
            store.setMeta(META_DIRTY, 0)
        elif content_changed:
            store.setMeta(META_DIRTY, 1)
            store.setMeta(META_SAVED, _now())


def _asOpened(index, store):
    """The splice index an open of the file just written records.

    That open records a section only where the file holds the working file
    it writes (jser_splice.OpenedJserIndex), so not one it writes otherwise:
    one the store holds otherwise than it was saved, or one whose alignment
    is unlocked, since every open locks it.
    """
    if index is None:
        return None
    from . import store_open
    from PyReconstruct.modules.constants.jser_splice import SpliceIndex

    locked = {snum for snum, h in store_open._headers(store) if h["align_locked"] is True}
    kept = {
        key for snum, (key, alike, working) in _keys(store).items()
        if working and snum in locked
    }
    ranges = {key: r for key, r in index.ranges.items() if key in kept}
    return SpliceIndex(index.path, index.stat_key, ranges) if ranges else None


def _statsComplete(store) -> bool:
    """True when the store holds the numbers of every section, from its last import on."""
    from . import store_open

    if store.meta(store_open.META_STATS) != store.meta("imported_utc"):
        return False
    stored = {r[0] for r in store.con.execute("SELECT snum FROM section_stats")}
    return stored == set(store.sectionNumbers())


def _trace_cols() -> str:
    from .hybrid_store import TRACE_COLS
    return TRACE_COLS


def _now() -> str:
    from .hybrid_store import _now as now
    return now()


def _opened(series_data : dict) -> dict:
    """The series an open writes for these series data (Series._unpackJser)."""
    from .series import Series

    series_data["log_set"] = []
    Series.updateJSON(series_data)
    return series_data


## ---------------------------------------------------------------------------
## the object-list numbers
## ---------------------------------------------------------------------------

def _remeasure(series, store, changed : dict, old_series : dict, new_series : dict) -> dict:
    """The stored numbers of every section a full open of the Save would measure anew.

    Both opens are replayed in section order: the one the store's numbers
    came from, and the one of this Save. A section that changed is measured;
    so is one that did not but whose objects the new open measures in
    another transform.

        Returns:
            (dict): section number -> its section_stats row, less the number
    """
    from . import store_open

    old_al = store_open._Alignments(old_series["alignment"], old_series["obj_attrs"])
    new_al = store_open._Alignments(new_series["alignment"], new_series["obj_attrs"])
    headers = dict(store_open._headers(store))
    traced = {
        snum: np.unique(np.frombuffer(cpos, dtype="<i4")).tolist()
        for snum, cpos in store.con.execute("SELECT snum, cpos FROM section_stats")
    }
    rows = {}
    for snum in sorted(set(headers) | set(series.sections)):
        old_keys = {}
        tforms = None
        if snum in headers:
            h = headers[snum]
            tforms = store_open._transforms(h)
            for p in traced[snum]:
                old_keys[h["contours"][p]] = old_al.of(h["contours"][p], tforms)
        if snum not in series.sections:
            continue
        if snum in changed:
            opened = changed[snum][0]
            header = {"contours": list(opened["contours"]), "tforms": opened["tforms"]}
        else:
            # a section the store holds: its header was read above
            assert tforms is not None
            lists = {a: t.getList() for a, t in tforms.items()}
            if all(lists[key] == lists[new_al.of(name, tforms)] for name, key in old_keys.items()):
                continue
            header = headers[snum]
        rows[snum] = _measure(series, snum, header, new_al)
    return rows


class _AsOpened():

    def __init__(self, alignments, tforms):
        """What ObjectData.addTrace asks of a series, answered as a full open would.

        A full open of the .jser starts from its series' alignments and clears
        a fixed one that a section lacks; `alignments` replays that (see
        store_open._Alignments), so the live series is never asked or changed.
        """
        self.alignment = alignments.default
        self._alignments = alignments
        self._tforms = tforms

    def getAttr(self, name : str, attr : str):
        return self._alignments.of(name, self._tforms)

    def setAttr(self, name : str, attr : str, value):
        raise AssertionError("the replay chose an alignment the section lacks")


def _measure(series, snum : int, header : dict, alignments) -> tuple:
    """One saved section's numbers, measured from its working file as a full open does.

    The open loads the section and measures every trace from its columnar
    store (SeriesData.updateSection with read_store), each object in its
    alignment; this does the same with the replayed alignments. `header` is
    the section as stored, whose contour order the numbers follow.
    """
    from . import store_open
    from .section import Section
    from .columnar_store import TraceView
    from .series_data import ObjectData

    section = Section(snum, series)
    as_opened = _AsOpened(alignments, section.tforms)
    columns = section._columns
    # a Section built from its file always has its columns (Section.__init__)
    assert columns is not None
    objects : dict = {}
    for name in section.contours:
        for row in columns.rowsForContour(name):
            obj = objects.setdefault(name, ObjectData())
            obj.addTrace(TraceView(columns, row), section, as_opened, columns.getCoordinates(row))
    try:
        return store_open._statsRow(objects, alignments, snum, header)
    except store_open._NotMeasuredAlike as e:
        raise NotKept(str(e)) from e


## ---------------------------------------------------------------------------
## the .jser from the store
## ---------------------------------------------------------------------------

class JserHasher():

    def __init__(self):
        """The sha256 of what a .jser write puts in its file, as it writes it.

        `write_jser` may start over from the top of the file (seek to 0 and
        truncate); that starts the hash over. Any other move leaves no digest.
        """
        self._h = hashlib.sha256()
        self._ok = True

    def wrap(self, f):
        return _HashingFile(f, self)

    def digest(self):
        """The hex digest, or None if the write moved in a way it cannot follow."""
        return self._h.hexdigest() if self._ok else None


class _HashingFile():

    def __init__(self, f, hasher : JserHasher):
        self._f = f
        self._hasher = hasher

    def write(self, data):
        self._hasher._h.update(data)
        return self._f.write(data)

    def tell(self):
        return self._f.tell()

    def seek(self, pos, whence=0):
        if (pos, whence) == (0, 0):
            self._hasher._h = hashlib.sha256()
        else:
            self._hasher._ok = False
        return self._f.seek(pos, whence)

    def truncate(self, size=None):
        if (self._f.tell() if size is None else size) != 0:
            self._hasher._ok = False
        return self._f.truncate(size)

    def __getattr__(self, name):
        # anything else the writer does is not followed
        self._hasher._ok = False
        return getattr(self._f, name)


def writeJser(series):
    """Write the series' .jser from its store's last Save, then record it.

    The bytes are what today's Save writes for the working folder of that
    Save, and the sections the last .jser holds are copied from it (the
    splice index the store keeps). An automatic backup is the caller's.

        Raises:
            SeriesSaveError: if the store cannot be read, or another save
                of this series is running. The .jser is not replaced.
            OSError: if the file cannot be written. The .jser is not replaced.
    """
    from . import store_open
    from .series import _atomicWrite
    from PyReconstruct.modules.constants.jser_format import write_jser
    from PyReconstruct.modules.constants.jser_splice import JserSplice

    held = heldStore(series)
    store = held.store
    jser_fp = series.jser_fp
    if series.jserSaveRunning():
        raise series.refuseNestedSave(jser_fp)
    try:
        snums = store.sectionNumbers()
        keys = _keys(store)
        series_data = store.seriesData()
        log = store.logText()
        index = held.spliceIndex()
    except (sqlite3.Error, store_open.StoreUnavailable) as e:
        _raiseIfBug(e)
        series._refuseSave(jser_fp, f"the local store could not be read ({e}).")
    if not snums or set(keys) != set(snums):
        series._refuseSave(jser_fp, "the local store does not hold every section of the series.")

    slots = [None] * (snums[-1] + 1)
    for snum in snums:
        slots[snum] = snum

    reporter = series._progressReporterFactory()(text="Saving series...", cancel=False)
    series._jser_save_running = True
    try:
        def sections():
            for i, snum in enumerate(slots):
                if snum is None:
                    yield None
                    continue
                reporter.set_progress(i / len(slots) * 100)
                yield KeyedSection(keys[snum][0], lambda snum=snum: readSection(snum))

        def readSection(snum):
            try:
                return store.readSection(snum)
            except sqlite3.Error as e:
                _raiseIfBug(e)
                series._refuseSave(jser_fp, f"section {snum} could not be read from the local store ({e}).")

        def tail():
            return {"series": series_data, "log": log}

        if index is not None and not index.matchesDisk():
            index = None
        splice = JserSplice(index)
        hasher = JserHasher()

        def write(f):
            write_jser(hasher.wrap(f), sections, tail, splice=splice)
            # before the file is put in place: a crash after that, before the
            # record below, leaves a .jser the next open knows as this one
            _noteWriting(store, hasher.digest())

        try:
            _atomicWrite(jser_fp, write)
        except OSError as e:
            series._surfaceSaveError(jser_fp, e)
            raise
        series._jser_splice_index = new_index = splice.indexFor(jser_fp)
        digest = hasher.digest()
        try:
            if digest is None:
                digest = store_open.jserDigest(jser_fp)
            with store_open._transaction(store):
                store.recordJser(jser_fp)
                store.setMeta(store_open.META_SHA, digest)
                store.setMeta(store_open.META_SPLICE, store_open._spliceMeta(_asOpened(new_index, store)))
                store.setMeta(META_WRITING, None)
                store.setMeta(META_DIRTY, 0)
        except (store_open.StoreUnavailable, OSError, sqlite3.Error) as e:
            # the .jser holds the Save: only the store's record of it failed
            _raiseIfBug(e)
            _giveUp(series, held, e)
    finally:
        series._jser_save_running = False
        reporter.finish()


def _noteWriting(store, digest):
    """Keep the sha256 of the .jser about to be put in place (META_WRITING).

    Only crash recovery reads it, so a store that cannot take it is noted in
    the log and the write goes on: without it, a crash in that gap sets the
    store aside rather than finishing its record (store_recovery.py).
    """
    from . import store_open

    if digest is None:
        return
    try:
        with store_open._transaction(store):
            store.setMeta(META_WRITING, digest)
    except sqlite3.Error as e:
        _raiseIfBug(e)
        store_open.log_note(f"Local store did not note the .jser it is writing: {e}")
