"""Section files written on first need after an open from the local store.

An open from the store (store_open.py) writes the series file and the log
into the working folder, and for each section the store holds as its working
file, a stub in place of the section file. The stub is small: a first line
`MAGIC`, then one JSON object naming the sha256 of the bytes the section file
will hold (`key`), the store that holds them, and where they sit in the .jser
the store was imported from (`range`, or null).

`Series.presentSection` is the one way a section file is read: it fills a
stub first. The fill reads the section from the store through a read-only
connection of its own (so it works on any thread), and checks its sha256
against the stub's key. On a mismatch it reads the key's range from the .jser
(the series' splice index in a session, the stub's range after a crash) and
checks that. Only bytes with that sha256 are ever written, then put over the
stub in one replace. When no source matches, `SectionUnavailable` (an
OSError) is raised, the stub stays, and nothing is written: a load fails as
for an unreadable file, and a Save refuses as it does for one.

A Save never fills: `workingSection` gives a stub's key, and its bytes from
the store when the writer must encode the section. Save As, a renumbering, and
letting go of the store fill first (`presentAll`), since nothing else backs a
stub once the store is let go.

The folder holds `MARKER` while it may hold stubs, so a resumed folder is
filled before a series is built from it (`presentFolder`). A real section
file is never turned back into a stub. The first line is not JSON, so an
older build or another tool reading the folder fails loudly on a stub rather
than reading a series short a section.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from PyReconstruct.modules.constants import fast_dumps, fast_loads
from PyReconstruct.modules.constants.jser_splice import section_digest

from .hybrid_store import HybridStore, storeRoot

MAGIC = b"PYRECON-LAZY-SECTION 1\n"
## In a working folder that may hold stubs; no numeric extension, so no scan
## takes it for a section
MARKER = "lazy-sections.json"
FILL_SUFFIX = ".fill.tmp"


class SectionUnavailable(OSError):
    """No source holds the bytes a stub names."""


## ---------------------------------------------------------------------------
## the open: which sections get a stub
## ---------------------------------------------------------------------------

def stubs(held) -> dict:
    """snum -> stub (dict) for each section an open from `held` need not write.

    Only a section whose stored bytes are its working file (`as_working`),
    which an open writes back as it is (`opens_alike`), and whose alignment is
    stored locked, as the open writes it: its file is then the stored bytes,
    whose sha256 is the stored key.
    """
    from . import store_open, store_save

    store = held.store
    try:
        keys = store_save._keys(store)
        index = held.spliceIndex()
        base = {
            "store": os.path.basename(store.db_fp),
            "imported_utc": store.meta("imported_utc"),
            "jser_sha256": store.meta(store_open.META_SHA),
        }
        headers = list(store_open._headers(store))
    except (OSError, sqlite3.Error) as e:
        store_open._raiseIfBug(e)
        raise store_open.StoreUnavailable(str(e)) from e
    ranges = index.ranges if index is not None else {}
    out = {}
    for snum, header in headers:
        key = keys.get(snum)
        if key is None or not (key[1] and key[2]) or header.get("align_locked") is not True:
            continue
        hit = ranges.get(key[0])
        out[snum] = dict(base, snum=snum, key=key[0].hex(), range=None if hit is None else list(hit[:2]))
    return out


def writeStub(fp : str, stub : dict):
    with open(fp, "wb") as f:
        f.write(MAGIC + json.dumps(stub, sort_keys=True).encode("ascii"))


def writeMarker(folder : str, store_name : str):
    with open(os.path.join(folder, MARKER), "w", encoding="ascii") as f:
        f.write(json.dumps({"version": 1, "store": store_name}))


def attach(series, snums):
    """The series' working folder holds stubs for `snums`."""
    series._lazy = set(snums)
    series._lazy_lock = threading.Lock()


## ---------------------------------------------------------------------------
## reading a stub, and filling it
## ---------------------------------------------------------------------------

def readStub(fp : str):
    """The stub at fp, or None when fp is a section file."""
    with open(fp, "rb") as f:
        head = f.read(len(MAGIC))
        if head != MAGIC:
            return None
        return json.loads(f.read())


class _Reader(HybridStore):
    """A store opened read-only, without its lock, usable on any thread."""

    def __init__(self, db_fp : str):
        self.db_fp = db_fp
        self.work_dir = ""
        self._lock_fd = None
        self.con = None  # type: ignore[assignment]
        if not os.path.isfile(db_fp):
            raise FileNotFoundError(db_fp)
        # with no WAL beside it, no connection has it open and its file holds
        # every commit: read that file alone, making no side file
        query = "?mode=ro" if os.path.exists(db_fp + "-wal") else "?mode=ro&immutable=1"
        self.con = sqlite3.connect(
            Path(os.path.abspath(db_fp)).as_uri() + query, uri=True, check_same_thread=False,
        )


def _fromStore(stub : dict):
    """The section's file bytes from the store, or None if they cannot be read."""
    from .store_open import _raiseIfBug

    reader = None
    try:
        reader = _Reader(os.path.join(storeRoot(), stub["store"]))
        section_data = reader.readSectionEncoded(stub["snum"])
        section_data["align_locked"] = True
        return fast_dumps(section_data)
    except (OSError, sqlite3.Error) as e:
        _raiseIfBug(e)
        return None
    except (TypeError, ValueError):
        return None  # a row that does not read back: the .jser is tried next
    finally:
        if reader is not None:
            reader.close()


def _fromRange(path : str, rng) -> "bytes | None":
    if not path or rng is None:
        return None
    offset, length = rng[0], rng[1]
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(length)
    except OSError:
        return None
    return data if len(data) == length else None


def sectionBytes(stub : dict, jser_fp : str = "", index=None) -> bytes:
    """The bytes the stub names: from the store, else the .jser; checked by sha256.

        Params:
            jser_fp (str): the .jser the stub's range is read from
            index (SpliceIndex): the series' splice index, tried before the
                stub's own range
        Raises:
            SectionUnavailable: no source holds bytes with the stub's sha256
    """
    key = bytes.fromhex(stub["key"])
    candidates = [lambda: _fromStore(stub)]
    if index is not None and key in index.ranges:
        candidates.append(lambda: _fromRange(index.path, index.ranges[key][:2]))
    candidates.append(lambda: _fromRange(jser_fp, stub.get("range")))
    for read in candidates:
        data = read()
        if data is not None and section_digest(data) == key:
            return data
    raise SectionUnavailable(
        f"section {stub['snum']} is in neither the local store nor the .jser as it was saved"
    )


def fill(fp : str, jser_fp : str = "", index=None) -> bool:
    """Put the section file in place of the stub at fp. False if fp is no stub."""
    from PyReconstruct.modules.backend.func import atomic_io

    stub = readStub(fp)
    if stub is None:
        return False
    data = sectionBytes(stub, jser_fp, index)
    tmp = fp + FILL_SUFFIX
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        atomic_io.replace_with_retry(tmp, fp)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return True


## ---------------------------------------------------------------------------
## the series
## ---------------------------------------------------------------------------

def present(series, snum : int, fp : str):
    """Fill section snum's stub, if it is one (Series.presentSection)."""
    with series._lazy_lock:
        if snum not in series._lazy:
            return
        fill(fp, series.jser_fp, getattr(series, "_jser_splice_index", None))
        series._lazy.discard(snum)
        if not series._lazy:
            # the folder holds no stub now: cleanup need not keep the store for it
            try:
                os.remove(os.path.join(os.path.dirname(fp), MARKER))
            except FileNotFoundError:
                pass


def forget(series, snum : int):
    """Section snum's stub was removed with its section (Series.deleteSections)."""
    with series._lazy_lock:
        series._lazy.discard(snum)


def workingSection(series, snum : int):
    """(key, loader) for a stubbed section, as Save reads a working file; else None.

    The loader returns the section dict from the stub's source, unwritten.
    """
    if snum not in series._lazy:
        return None
    fp = os.path.join(series.getwdir(), series.sections[snum])
    stub = readStub(fp)
    if stub is None:
        return None
    jser_fp, index = series.jser_fp, getattr(series, "_jser_splice_index", None)
    return bytes.fromhex(stub["key"]), lambda: fast_loads(sectionBytes(stub, jser_fp, index))


## ---------------------------------------------------------------------------
## a working folder found at open (resume)
## ---------------------------------------------------------------------------

def presentFolder(folder : str, jser_fp : str, notifier=None) -> bool:
    """Fill every stub in a working folder before a series is built from it.

    True when the folder holds no stub now. False when a stub could not be
    filled: the folder is renamed aside whole and the user told where, so
    the .jser opens instead; nothing is deleted.
    """
    if not os.path.isfile(os.path.join(folder, MARKER)):
        return True
    try:
        for name in sorted(os.listdir(folder)):
            stem, _, ext = name.rpartition(".")
            if stem and ext.isnumeric():
                fill(os.path.join(folder, name), jser_fp)
    except SectionUnavailable as e:
        aside = f"{folder}.lazy-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        os.rename(folder, aside)
        _tell(notifier, (
            f"PyReconstruct could not finish the unsaved work of "
            f"{os.path.basename(jser_fp)} ({e}), so it opens the saved file. "
            f"The unsaved work is unchanged in:\n{aside}"
        ))
        return False
    for name in os.listdir(folder):
        if name.endswith(FILL_SUFFIX) or name == MARKER:
            os.remove(os.path.join(folder, name))
    return True


def _tell(notifier, message : str):
    from .store_open import log_note
    from .series import _default_notifier

    log_note(message.replace("\n", " "))
    (notifier or _default_notifier()).notify(message)


def namesStore(jser_fp : str, store_name : str) -> bool:
    """True when the working folder beside jser_fp may hold stubs filled from the store.

    Cleanup keeps such a store (local_stores.removeIfClean): its stubs need
    it. A folder that cannot be read keeps it too.
    """
    stem = os.path.basename(jser_fp)
    stem = stem[:stem.rfind(".")] if "." in stem else stem
    marker = os.path.join(os.path.dirname(jser_fp), f".{stem}", MARKER)
    try:
        with open(marker, "rb") as f:
            return json.loads(f.read()).get("store") == store_name
    except (FileNotFoundError, NotADirectoryError):
        return False
    except (OSError, ValueError, AttributeError):
        return True
