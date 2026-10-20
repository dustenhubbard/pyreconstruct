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
``<store>.conflict-<UTC>.pyrstore`` in the same folder in one rename. It is
never deleted. The open says where it is, and so does every later open of the
.jser until ``PyReconstruct --export-local-copy <file>`` writes it out
(`exportStore`). A store written out is set aside without a word.

A store that cannot be made one file first (another program has it open) is
not moved: it stays where it is, whole, and the next open tries again. The
open says so, unless the store was written out.

On Windows a store with work no .jser has is not moved at all: SQLite cannot
hold its lock through a rename there (`setAside`). It stays where it is,
whole, until it is written out, and every open names it or offers its Save.

A store keyed by a .jser that is gone (moved, renamed or deleted) is never
opened again by that .jser. Every open names each such store with work no
.jser has (`strandedStores`), until it is written out.

When the window resumes a working folder after a crash (`resumed`), the
series takes its store if the store holds its .jser or a Save the .jser
lacks. The folder is newer than the store, so the next Save takes every
section file in it that differs from the store, an inserted or a deleted
section with them.
"""

import errno
import glob
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import store_open, store_save
from .hybrid_store import SCHEMA_VERSION, HybridStore, _fsyncFolder, storePaths, storeRoot

CLEAN = "clean"
AHEAD = "ahead"
WRITTEN = "written"
CHANGED = "changed"
UNREADABLE = "unreadable"

## the name a set-aside store takes: <store>.conflict-<UTC>.pyrstore
SET_ASIDE = ".conflict-"
STORE_EXT = ".pyrstore"
## meta of a set-aside store, or of one whose .jser is gone: the .jser it was written out to
META_WRITTEN_OUT = store_save.META_WRITTEN_OUT
## the files SQLite keeps beside a store
SIDECARS = ("-wal", "-shm", "-journal")
## what to run to write a set-aside store out (cli.py)
EXPORT_OPTION = "--export-local-copy"

_WINDOWS = sys.platform == "win32"


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

    The WAL is folded into the file first, so the store is one file, and it
    moves in one rename: a crash leaves it whole at one name or the other.
    If it cannot be made one file (another program has it open), nothing
    moves. The path is left free for a new store.

    Off Windows, no other program writes the file from the check that it is
    one file to the rename: the store holds SQLite's exclusive lock through
    the rename, and SQLite refuses a write to a moved file from a connection
    made before the move.

    On Windows SQLite's file cannot be renamed while SQLite has it open, so
    the store is closed first, and another program could write it before
    the rename. So there a store is moved only once it is written out
    (`exportStore`), when its work is in a .jser: until then it stays where
    it is. A journal that a program left at the old name sends the moved
    store back to it (`_sendBack`).

        Returns:
            (str): the set-aside store file
        Raises:
            StoreUnavailable: it was not moved; it is whole where it was
            NotSentBack: it was moved, and a journal left at the old name
                could not have it back
    """
    if _WINDOWS:
        try:
            unwritten = not _writtenOut(held)
        except store_open.StoreUnavailable:
            unwritten = True
        if unwritten:
            held.close()
            raise store_open.StoreUnavailable(
                "the store was not set aside: on Windows it moves only once it is written out"
            )
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
        row = store.con.execute("PRAGMA journal_mode=DELETE").fetchone()
        folded = row is not None and str(row[0]).lower() == "delete"
        if folded:
            # no other connection reads or writes the file until it has moved
            store.con.execute("BEGIN EXCLUSIVE")
    except sqlite3.Error as e:
        store_open._raiseIfBug(e)
        folded = False
    try:
        if not folded or _sidecars(db_fp):
            raise store_open.StoreUnavailable(
                "the store could not be set aside: its WAL could not be folded into it"
            )
        if not _WINDOWS:
            os.rename(db_fp, kept)
        store.con.close()
        store.con = None
        if _WINDOWS:
            os.rename(db_fp, kept)
            if _sidecars(db_fp):
                _sendBack(db_fp, kept)
        _fsyncFolder(os.path.dirname(db_fp))
    except OSError as e:
        raise store_open.StoreUnavailable(f"the store could not be set aside ({e})") from e
    finally:
        # the lock last: no other window takes the store while it moves
        held.close()
    store_open.log_note(f"Local store for {os.path.basename(held.jser_fp)} set aside as {kept}")
    return kept


def _sidecars(db_fp : str) -> list:
    return [db_fp + ext for ext in SIDECARS if os.path.lexists(db_fp + ext)]


class NotSentBack(store_open.StoreUnavailable):
    """The store was set aside as `kept`, and could not go back beside the
    files another program left at its old name (`left`)."""

    def __init__(self, kept : str, left : list, err : OSError):
        super().__init__(f"the store was set aside as {kept} and could not be put back beside {', '.join(left)} ({err})")
        self.kept, self.left, self.err = kept, left, err


def _sendBack(db_fp : str, kept : str):
    """A program wrote the store between its close and its rename (Windows):
    put it back beside the journal, which SQLite finds by name.

        Raises:
            StoreUnavailable: it is whole where it was
            NotSentBack: it could not be put back; it is whole at `kept`
    """
    try:
        os.rename(kept, db_fp)  # refuses a file made there meanwhile
    except FileExistsError as e:
        # a third program made a file there: the journal may be that file's
        store_open.log_note(f"Local store set aside as {kept} with a journal left at {db_fp} ({e})")
        return
    except OSError as e:
        raise NotSentBack(kept, _sidecars(db_fp), e) from e
    _fsyncFolder(os.path.dirname(db_fp))
    raise store_open.StoreUnavailable(
        "the store could not be set aside: another program wrote it as it moved"
    )


def _keepAside(held, notifier) -> tuple:
    """(set-aside file, None), or (None, store file) if the store stayed where it was."""
    db_fp = held.store.db_fp
    try:
        return setAside(held), None
    except NotSentBack as e:
        # never hidden, even for a store written out
        tell(notifier, notSentBackText(held.jser_fp, e))
        return e.kept, None
    except store_open.StoreUnavailable as e:
        store_open._unavailable(held.jser_fp, e)
        return None, db_fp


def setAsideStores(jser_fp : str) -> list:
    """The set-aside stores of a .jser not yet written out, oldest first."""
    db_fp, _ = storePaths(jser_fp)
    pattern = glob.escape(db_fp[:-len(STORE_EXT)]) + SET_ASIDE + "*" + STORE_EXT
    out = []
    for fp in sorted(glob.glob(pattern)):
        # one that cannot be read is named all the same
        read = _scanRead(fp)
        if read is None or not read[0].get(META_WRITTEN_OUT):
            out.append(fp)
    return out


def strandedStores(skip=()) -> list:
    """Stores with work no .jser has whose .jser is gone: [(store file, its .jser)].

    Read at every open, without a lock, and nothing is changed. The .jser was
    moved, renamed or deleted, or is on a drive not connected: the store is
    keyed by its path, so no open of a .jser ever takes it. A store written
    out (`exportStore`) is not listed again until it takes another Save.
    """
    skip = {os.path.normcase(os.path.abspath(fp)) for fp in skip if fp}
    # PYRECON_HYBRID_STORE_DIR may be relative: to the folder the app started in
    root = os.path.abspath(storeRoot())
    tag = f".v{SCHEMA_VERSION}."
    out = []
    for fp in sorted(glob.glob(os.path.join(glob.escape(root), "*" + STORE_EXT))):
        if tag not in os.path.basename(fp) or os.path.normcase(os.path.abspath(fp)) in skip:
            continue
        read = _scanRead(fp)
        if read is None:
            continue
        meta, pending = read
        if meta.get(META_WRITTEN_OUT):
            continue
        if meta.get(store_save.META_DIRTY) != "1" and not pending:
            continue
        jser = meta.get("jser_path")
        if jser and not os.path.isfile(jser):
            out.append((fp, jser))
    return out


def _scanRead(db_fp : str) -> "tuple[dict, bool] | None":
    """_readStore for a scan: a fault in one store (text in its meta that is
    not UTF-8, say) is noted in the log and read as None, so the scan goes on
    to the others."""
    try:
        return _readStore(db_fp)
    except Exception as e:
        store_open.log_note(f"Local store {db_fp} could not be read for the list of kept work: {e!r}")
        return None


def _readStore(db_fp : str) -> "tuple[dict, bool] | None":
    """(meta, holds working rows) of a store file, read without its lock;
    None if it cannot be read. A missing file is not made."""
    try:
        con = sqlite3.connect(Path(os.path.abspath(db_fp)).as_uri() + "?mode=rw", uri=True, timeout=1)
        try:
            meta = {
                k: (v.decode("utf-8", "surrogatepass") if isinstance(v, bytes) else v)
                for k, v in con.execute("SELECT key, value FROM meta")
            }
            pending = bool(
                con.execute("SELECT 1 FROM pending_section LIMIT 1").fetchone()
                or con.execute("SELECT 1 FROM pending_series LIMIT 1").fetchone()
            )
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return meta, pending


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
    kept = in_place = state = None
    done = False
    try:
        state, digest = standing(held)
        # written out (exportStore): kept aside without a word
        done = state in (AHEAD, CHANGED, UNREADABLE) and _writtenOut(held)
        if state == WRITTEN:
            finishWrite(held, digest)
        elif state == AHEAD:
            if _asker(notifier).confirm(offerText(held), title="Unsaved Series") is False:
                kept, in_place = _keepAside(held, notifier)
            else:
                held.opens_save = True
        elif state in (CHANGED, UNREADABLE):
            kept, in_place = _keepAside(held, notifier)
        if in_place is not None:
            # the store stays as it is, unused: the .jser opens as it is
            held = None
        elif kept is not None:
            held = store_open.StoreForOpen.attempt(jser_fp)
    finally:
        # told even when the store cannot be read just now
        if done:
            kept = in_place = None
        tellKept(notifier, jser_fp, kept, state, in_place)
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
        tellKept(notifier, jser_fp)
        return
    kept = in_place = None
    state = None
    try:
        state, digest = standing(held)
        if state == WRITTEN:
            finishWrite(held, digest)
        if state in (CHANGED, UNREADABLE):
            done = _writtenOut(held)
            kept, in_place = _keepAside(held, notifier)
            held = None
            if done:
                kept = in_place = None
        elif state == AHEAD or held.holdsJser(digest):
            store_save.attach(series, held)
            held = None
    except store_open.StoreUnavailable as e:
        store_open._unavailable(jser_fp, e)
    finally:
        if held is not None:
            held.close()
    tellKept(notifier, jser_fp, kept, state, in_place)


def _writtenOut(held) -> bool:
    """True when the store was written out (exportStore) after its last Save."""
    try:
        return bool(held.store.meta(META_WRITTEN_OUT))
    except sqlite3.Error as e:
        store_open._raiseIfBug(e)
        raise store_open.StoreUnavailable(str(e)) from e


def _asker(notifier):
    if notifier is not None:
        return notifier
    from .series import _default_notifier
    return _default_notifier()


def tell(notifier, message : str):
    """Tell the user, and note it in the log either way."""
    store_open.log_note(message.replace("\n", " "))
    _asker(notifier).notify(message)


def tellKept(notifier, jser_fp : str, kept=None, state=None, in_place=None):
    """Tell of the store set aside or kept in place at this open, if any, and
    of every store with work no .jser has: this .jser's set-aside stores, and
    the stores whose .jser is gone. The scans never stop an open."""
    try:
        others = [fp for fp in setAsideStores(jser_fp) if fp != kept]
    except Exception as e:
        store_open.log_note(f"Set-aside local stores not listed: {e!r}")
        others = []
    try:
        stranded = strandedStores(skip=[storePaths(jser_fp)[0], kept, *others])
    except Exception as e:
        store_open.log_note(f"Local stores whose .jser is gone not listed: {e!r}")
        stranded = []
    if kept is None and in_place is None and not others and not stranded:
        return
    tell(notifier, setAsideText(jser_fp, kept, state, others, in_place, stranded))


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


def setAsideText(jser_fp : str, kept, state, others=(), in_place=None, stranded=()) -> str:
    name = _seriesName(jser_fp)
    parts = []
    if in_place is not None and _WINDOWS:
        # setAside moves no store with work no .jser has on Windows
        parts.append(
            f"Work saved on this computer that {name} does not have is kept where "
            f"it is, untouched, in:\n  {in_place}\n{name} opens as it is on disk. "
            "On Windows that work stays there until it is written out.\n\n"
            + _exportLine(in_place)
        )
    elif in_place is not None:
        parts.append(
            f"Work saved on this computer that {name} does not have could not be "
            f"set aside just now. It is kept where it is, untouched, in:\n  {in_place}\n"
            f"{name} opens as it is on disk, and its next open tries again.\n\n"
            + _exportLine(in_place)
        )
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
    if stranded:
        listed = "\n".join(f"  {_seriesName(jser)}, kept in:\n    {fp}" for fp, jser in stranded)
        parts.append(
            "Work saved on this computer was never written to a .jser, and the "
            ".jser is not where it was (moved, renamed or deleted, or on a drive "
            f"that is not connected):\n{listed}\n\n"
            + _exportLine(stranded[0][0] if len(stranded) == 1 else "<file>")
        )
    return "\n\n".join(parts)


def notSentBackText(jser_fp : str, err : NotSentBack) -> str:
    name = _seriesName(jser_fp)
    left = "\n".join(f"  {fp}" for fp in err.left)
    return (
        f"Work saved on this computer for {name} was set aside in:\n  {err.kept}\n"
        "Another program wrote it as it moved, and it could not be put back "
        f"beside what that program left:\n{left}\n({err.err})\n"
        f"Both are kept as they are. {name} opens as it is on disk."
    )


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
    one with work no .jser has (a Save, or working rows), which records where
    it was written out so later opens stop naming it. A later Save to it drops that
    record.

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
        recorded = store.meta("jser_path")
        if out_fp is None:
            out_fp = _defaultOut(recorded, db_fp)
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

        unsaved = store.meta(store_save.META_DIRTY) == "1" or store.hasPending()
        _writeNew(out_fp, lambda f: write_jser(f, sections, tail))
        if unsaved:
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
    """Write a new file; an existing file is never replaced, even one made a
    moment ago.

    The file is written beside its name, then put in place whole by a step
    that refuses a file already there: a hard link (POSIX) or a rename
    (Windows). A file system with no hard links (FAT) gets it copied into a
    name made only if none is there (`_copyNew`), so a crash during that copy
    can leave part of the file; nothing records it as written out then.
    """
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
                _copyNew(tmp, fp)
        _fsyncFolder(folder)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _copyNew(src : str, fp : str):
    """Copy src to fp, a file made here (O_EXCL), so never over another."""
    fd = os.open(fp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
    try:
        with os.fdopen(fd, "wb") as f, open(src, "rb") as s:
            shutil.copyfileobj(s, f, 1 << 20)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        os.remove(fp)  # made above: only this part of the file is in it
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
