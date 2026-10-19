"""Crash recovery and stranded work for the local store, behind the switch.

In ``store`` mode (store_save.py) Save writes the store alone, and the .jser is
written from it when the series closes. A crash before that leaves the Save in
the store and, as today, the work after it in the working folder beside the
.jser. This is what the next open does with them. With PYRECON_HYBRID_STORE
off, nothing here runs.

At an open, a store that holds a Save the .jser lacks is in one of these
states against the .jser on disk (`standing`):

  * AHEAD: the .jser is the file the Save went over. The open asks "Open it
    with that work?". Yes, or nobody to ask: the series opens from the store's
    Save, and its close writes the .jser. No: the store is set aside and the
    .jser opens as it is.
  * WRITTEN: the .jser is the file a close was writing from the store, put in
    place before the store could record it. The store records it now, and
    holds the .jser.
  * CHANGED: the .jser is neither. Another window or program wrote it. The
    store is set aside, and the .jser opens as it is.
  * UNREADABLE: the store holds working rows, or lacks a section's numbers
    or key, so its Save cannot be opened as it is. The store is set aside.

A set-aside store is the whole store file, renamed to
``<store>.conflict-<UTC>.pyrstore`` in the same folder. It is never deleted.
The open says where it is, and so does every later open of the .jser until
``PyReconstruct --export-local-copy <file>`` writes it out (`exportStore`).

When the window resumes a working folder after a crash (`resumed`), the
series takes its store if the store holds its .jser or a Save the .jser
lacks. The folder is newer than the store, so the next Save takes every
section file in it that differs from the store, an inserted or a deleted
section with them.
"""

import errno
import glob
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

from . import store_open, store_save
from .hybrid_store import HybridStore, _fsyncFolder, storePaths

CLEAN = "clean"
AHEAD = "ahead"
WRITTEN = "written"
CHANGED = "changed"
UNREADABLE = "unreadable"

## the name a set-aside store takes: <store>.conflict-<UTC>.pyrstore
SET_ASIDE = ".conflict-"
STORE_EXT = ".pyrstore"
## meta of a set-aside store: the .jser it was written out to
META_WRITTEN_OUT = "written_out"
## what to run to write a set-aside store out (cli.py)
EXPORT_OPTION = "--export-local-copy"


## ---------------------------------------------------------------------------
## the state of a store at an open
## ---------------------------------------------------------------------------

def standing(held) -> tuple:
    """(state, sha256 of the .jser or None) of a held store against its .jser.

    A store with no Save the .jser lacks is CLEAN and the .jser is not hashed
    here (store_open's own checks do that).

        Raises:
            StoreUnavailable: the store or the .jser cannot be read
    """
    store = held.store
    try:
        pending = store.hasPending()
        if not pending and store.meta(store_save.META_DIRTY) != "1":
            return CLEAN, None
        if pending or not _holdsSave(store):
            return UNREADABLE, None
        digest = store_open.jserDigest(held.jser_fp)
        if digest == store.meta(store_open.META_SHA):
            return AHEAD, digest
        if digest == store.meta(store_save.META_WRITING):
            return WRITTEN, digest
        return CHANGED, digest
    except sqlite3.Error as e:
        store_open._raiseIfBug(e)
        raise store_open.StoreUnavailable(str(e)) from e


def _holdsSave(store) -> bool:
    """True when an open can come from the store's last Save, as from an import."""
    if not store.isImported() or not store_save._statsComplete(store):
        return False
    return set(store_save._keys(store)) == set(store.sectionNumbers())


def finishWrite(held, digest : str):
    """Record the .jser a close wrote from the store, as that close would have."""
    store = held.store
    try:
        with store_open._transaction(store):
            store.recordJser(held.jser_fp)
            store.setMeta(store_open.META_SHA, digest)
            # the layout of that file was never recorded: the next Save writes in full
            store.setMeta(store_open.META_SPLICE, None)
            store.setMeta(store_save.META_WRITING, None)
            store.setMeta(store_save.META_DIRTY, 0)
    except sqlite3.Error as e:
        store_open._raiseIfBug(e)
        raise store_open.StoreUnavailable(str(e)) from e
    store_open.log_note(
        f"Local store recorded {os.path.basename(held.jser_fp)}, which its last close wrote"
    )


def setAside(held) -> str:
    """Rename the held store to a set-aside name and let go of it.

    The WAL is folded into the file first, so the set-aside file is whole on
    its own; if that cannot be done, its WAL and index files move with it.
    The path is left free for a new store.

        Returns:
            (str): the set-aside store file
        Raises:
            StoreUnavailable: it could not be renamed
    """
    store = held.store
    db_fp = store.db_fp
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = db_fp[:-len(STORE_EXT)]
    kept = f"{base}{SET_ASIDE}{stamp}{STORE_EXT}"
    n = 1
    while os.path.exists(kept):
        kept = f"{base}{SET_ASIDE}{stamp}-{n}{STORE_EXT}"
        n += 1
    try:
        store.con.execute("PRAGMA journal_mode=DELETE")
    except sqlite3.Error as e:
        store_open._raiseIfBug(e)
    store.con.close()
    store.con = None
    try:
        os.rename(db_fp, kept)
        for ext in ("-wal", "-shm", "-journal"):
            if os.path.exists(db_fp + ext):
                os.rename(db_fp + ext, kept + ext)
        _fsyncFolder(os.path.dirname(db_fp))
    except OSError as e:
        # whatever did not move stays where it was, whole: the next open tries again
        raise store_open.StoreUnavailable(f"the store could not be set aside ({e})") from e
    finally:
        # the lock last: no other window takes the store while it moves
        held.close()
    store_open.log_note(f"Local store for {os.path.basename(held.jser_fp)} set aside as {kept}")
    return kept


def setAsideStores(jser_fp : str) -> list:
    """The set-aside stores of a .jser not yet written out, oldest first."""
    db_fp, _ = storePaths(jser_fp)
    pattern = glob.escape(db_fp[:-len(STORE_EXT)]) + SET_ASIDE + "*" + STORE_EXT
    return [fp for fp in sorted(glob.glob(pattern)) if not _readMeta(fp).get(META_WRITTEN_OUT)]


def _readMeta(db_fp : str) -> dict:
    """A store file's meta, read without its lock; {} if it cannot be read."""
    try:
        con = sqlite3.connect(db_fp, timeout=1)
        try:
            return {
                k: (v.decode("utf-8", "surrogatepass") if isinstance(v, bytes) else v)
                for k, v in con.execute("SELECT key, value FROM meta")
            }
        finally:
            con.close()
    except sqlite3.Error:
        return {}


## ---------------------------------------------------------------------------
## opening, and resuming a working folder
## ---------------------------------------------------------------------------

def atOpen(held, notifier=None):
    """What an open from the store goes on with, once any Save the .jser lacks is handled.

    Called by store_open.openJser with the store it holds. AHEAD asks; the
    other states need no answer. The user is told of any store set aside,
    this time or before.

        Params:
            held (StoreForOpen): the .jser's store
            notifier: asks and tells; None is the default (Qt) notifier
        Returns:
            (StoreForOpen): the store to open with: the same one, with
                `opens_save` set when the open comes from its Save, or a new
                one after the old was set aside; or None if no store can be had
    """
    jser_fp = held.jser_fp
    state, digest = standing(held)
    kept = None
    if state == WRITTEN:
        finishWrite(held, digest)
    elif state == AHEAD:
        if _asker(notifier).confirm(offerText(held), title="Unsaved Series") is False:
            kept = setAside(held)
        else:
            held.opens_save = True
    elif state in (CHANGED, UNREADABLE):
        kept = setAside(held)
    if kept is not None:
        held = store_open.StoreForOpen.attempt(jser_fp)
    _tellSetAside(notifier, jser_fp, kept, state)
    return held


def resumed(series, notifier=None):
    """After a working folder is resumed: give the series its store, if it can take it.

    The store must hold the series' .jser, or a Save the .jser lacks, with
    every section's numbers and key. A store in another state is set aside
    (CHANGED, UNREADABLE) or left for the next open (CLEAN but not of this
    .jser). Nothing here stops the resume: a store that cannot be used is
    noted in the log. `notifier` tells; None is the series' own.
    """
    if notifier is None:
        notifier = series._notifier()
    jser_fp = series.jser_fp
    held = store_open.StoreForOpen.attempt(jser_fp)
    if held is None:
        return
    kept = None
    state = None
    try:
        state, digest = standing(held)
        if state == WRITTEN:
            finishWrite(held, digest)
        if state in (CHANGED, UNREADABLE):
            kept = setAside(held)
            held = None
        elif state == AHEAD or held.holdsJser(digest):
            store_save.attach(series, held)
            held = None
    except store_open.StoreUnavailable as e:
        store_open._unavailable(jser_fp, e)
    finally:
        if held is not None:
            held.close()
    _tellSetAside(notifier, jser_fp, kept, state)


def _asker(notifier):
    if notifier is not None:
        return notifier
    from .series import _default_notifier
    return _default_notifier()


def tell(notifier, message : str):
    """Tell the user, and note it in the log either way."""
    store_open.log_note(message.replace("\n", " "))
    _asker(notifier).notify(message)


def _tellSetAside(notifier, jser_fp : str, kept, state):
    try:
        others = [fp for fp in setAsideStores(jser_fp) if fp != kept]
    except OSError:
        others = []
    if kept is None and not others:
        return
    tell(notifier, setAsideText(jser_fp, kept, state, others))


## ---------------------------------------------------------------------------
## what the user reads
## ---------------------------------------------------------------------------

def _seriesName(jser_fp : str) -> str:
    return os.path.basename(jser_fp)


def _when(utc_text) -> str:
    """ ' (month day, year at HH:MM)', local time, or '' if not known."""
    try:
        t = datetime.strptime(utc_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return ""
    t = t.astimezone()
    return f" ({t:%B} {t.day}, {t.year} at {t:%H:%M})"


def offerText(held) -> str:
    when = _when(held.store.meta(store_save.META_SAVED))
    name = _seriesName(held.jser_fp)
    return (
        f"{name} does not have the work last saved on this computer{when}.\n"
        "Open it with that work?\n\n"
        f"No keeps that work aside, untouched, and opens {name} as it is."
    )


def _exportLine(fp : str) -> str:
    return f'To write it to a new .jser, run:\n  PyReconstruct {EXPORT_OPTION} "{fp}"'


def setAsideText(jser_fp : str, kept, state, others=()) -> str:
    name = _seriesName(jser_fp)
    parts = []
    if kept is not None:
        if state == AHEAD:
            why = f"The work saved on this computer that {name} does not have"
        elif state == CHANGED:
            why = (
                f"{name} was changed on disk by another window or program while "
                "this computer held work saved to it that the file does not have. "
                "That work"
            )
        else:
            why = f"Work saved on this computer for {name} could not be opened as it is. It"
        parts.append(
            f"{why} is kept aside, untouched, in:\n  {kept}\n"
            f"{name} opens as it is on disk.\n\n" + _exportLine(kept)
        )
    if others:
        listed = "\n".join(f"  {fp}" for fp in others)
        parts.append(
            f"Earlier work for {name} is still kept aside in:\n{listed}\n\n"
            + _exportLine(others[0] if len(others) == 1 else "<file>")
        )
    return "\n\n".join(parts)


def unreadSaveText(jser_fp : str) -> str:
    name = _seriesName(jser_fp)
    return (
        f"The work saved on this computer that {name} does not have could not "
        f"be read just now. It is kept as it is, and offered again the next "
        f"time {name} opens. {name} opens as it is on disk."
    )


## ---------------------------------------------------------------------------
## writing a store out to a .jser (PyReconstruct --export-local-copy)
## ---------------------------------------------------------------------------

def exportStore(path : str, out_fp=None) -> str:
    """Write a .jser from a store file, or from the store of a .jser.

    The .jser holds the store's working state: its last Save, and any working
    rows over it. The bytes are those a close writes from the same store
    (store_save.writeJser), since both use today's writer on the same rows.
    An existing file is never replaced, and the store is not changed, but for
    a set-aside store, which records where it was written out so later opens
    stop listing it.

        Params:
            path (str): a .pyrstore file, or a .jser whose store is wanted
            out_fp (str): the .jser to write; default beside the .jser the
                store records, named "<series> recovered <UTC>.jser"
        Returns:
            (str): the .jser written
        Raises:
            FileNotFoundError: no such store
            FileExistsError: out_fp exists
            StoreBusyError: a window has the series open
            ValueError: the store holds no section
    """
    from PyReconstruct.modules.constants.jser_format import write_jser

    if path.lower().endswith(STORE_EXT):
        db_fp = os.path.abspath(path)
    else:
        db_fp, _ = storePaths(path)
    if not os.path.isfile(db_fp):
        raise FileNotFoundError(f"No local copy at {db_fp}")
    base = os.path.basename(db_fp)
    # a set-aside store shares its store's working folder rather than make one
    work_dir = os.path.join(
        os.path.dirname(db_fp), base.split(SET_ASIDE, 1)[0].removesuffix(STORE_EXT) + ".work"
    )
    store = HybridStore(db_fp, work_dir)
    try:
        if out_fp is None:
            out_fp = _defaultOut(store.meta("jser_path"), db_fp)
        out_fp = os.path.abspath(out_fp)
        if os.path.lexists(out_fp):
            raise FileExistsError(f"{out_fp} exists; it was not replaced")
        snums = store.sectionNumbers()
        if not snums:
            raise ValueError(f"The local copy {db_fp} holds no section")
        series_data = store.seriesData()
        log = store.logText()
        slots = [None] * (snums[-1] + 1)
        for snum in snums:
            slots[snum] = snum

        def sections():
            for snum in slots:
                yield None if snum is None else store.readSection(snum)

        def tail():
            return {"series": series_data, "log": log}

        _writeNew(out_fp, lambda f: write_jser(f, sections, tail))
        if SET_ASIDE in base:
            with store_open._transaction(store):
                store.setMeta(META_WRITTEN_OUT, out_fp)
    finally:
        store.close()
    return out_fp


def _defaultOut(recorded, db_fp : str) -> str:
    stem = os.path.splitext(os.path.basename(recorded or "series.jser"))[0]
    folder = os.path.dirname(recorded) if recorded else ""
    if not folder or not os.path.isdir(folder):
        folder = os.getcwd()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(folder, f"{stem} recovered {stamp}.jser")


def _writeNew(fp : str, write):
    """Write a new file whole, or not at all; an existing file is never replaced."""
    folder = os.path.dirname(fp)
    fd, tmp = tempfile.mkstemp(prefix=".export-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        if sys.platform == "win32":
            os.rename(tmp, fp)  # refuses an existing file
        else:
            try:
                os.link(tmp, fp)  # refuses an existing file
            except OSError as e:
                if e.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV):
                    raise
                # a file system with no hard links
                if os.path.lexists(fp):
                    raise FileExistsError(errno.EEXIST, "exists; it was not replaced", fp) from e
                os.rename(tmp, fp)
            else:
                os.remove(tmp)
        _fsyncFolder(folder)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def exportMain(args : list, out=None) -> int:
    """`PyReconstruct --export-local-copy <store or .jser> [<out.jser>]` (cli.py)."""
    if out is None:
        out = sys.stdout
    if not 1 <= len(args) <= 2:
        print(f"usage: PyReconstruct {EXPORT_OPTION} <store file or .jser> [<new .jser>]", file=out)
        return 2
    try:
        written = exportStore(args[0], args[1] if len(args) > 1 else None)
    except (OSError, ValueError, sqlite3.Error) as e:
        print(f"Not written: {e}", file=out)
        return 1
    print(written, file=out)
    return 0
