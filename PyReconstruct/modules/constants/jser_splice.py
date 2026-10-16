"""Splice save: copy the sections a save did not change from the last .jser.

A save used to decode every section's working file and encode it again, even
when one section of hundreds had changed. With splicing, a section whose
working file holds exactly the bytes it held at the last save is copied from
the .jser that save wrote, and only the other sections are encoded. The file
is byte for byte what a full save writes. Nothing about the format changes.

Why a copy is exact. In the minified form a section's bytes are
``orjson([[section]])[2:-2]`` of the dict parsed from its working file, a pure
function of that file's bytes. Nothing from another section, the series or the
log goes into them. Two things are decided for the whole document, and both
turn splicing off rather than being spliced around:

- the pretty form (``PYRECON_JSER_PRETTY=1``): a pretty save writes in full
  and records no index;
- the stdlib fallback: when orjson refuses any part, every part is written
  with the stdlib's separators, so the whole document is written again and
  no index is recorded.

So "changed" means the working file's bytes differ, compared by sha256. It
does not depend on which edits the GUI tracked. Whatever a full save would
read is what this save reads, so an edit a full save would keep is never
lost here.

The index is a hint. Before it is used, the previous .jser must still have the
size, mtime, inode and device it had right after it was written; if not, the
save is a full save. Each copied range is hashed as it is copied and must
match the digest recorded when it was written. A short read or any mismatch
stops the splice, and the save starts over as a full save in the same temp
file, so the old .jser is replaced only by a complete file either way.
"""

import hashlib
import os

#: Bytes read per copy step. The copy holds one of these at a time.
COPY_CHUNK = 8 << 20


def section_digest(data) -> bytes:
    """The sha256 of `data`, which is any bytes-like object."""
    return hashlib.sha256(data).digest()


class SpliceMismatch(Exception):
    """A range of the previous .jser is not what the index says it is."""


class KeyedSection:
    """One section's working file, read but not yet parsed.

    The save yields one of these per section so the writer can decide whether
    to copy the section or parse and encode it. `load` is called only for a
    section that is encoded.

        Attributes:
            key (bytes): the sha256 of the working file's bytes
            load (callable): returns the parsed section dict
    """

    __slots__ = ("key", "load")

    def __init__(self, key : bytes, load):
        self.key = key
        self.load = load


def loaded(sections):
    """`sections` with every KeyedSection parsed, for the writers that encode all."""
    for sd in sections:
        yield sd.load() if isinstance(sd, KeyedSection) else sd


def _stat_key(st) -> tuple:
    return (st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev)


class SpliceIndex:
    """Where each section's bytes sit in a .jser this series wrote.

        Attributes:
            path (str): the .jser the ranges describe
            stat_key (tuple): its size, mtime, inode and device after the write
            ranges (dict): working-file sha256 -> (offset, length, sha256 of
                the bytes at that range)
    """

    def __init__(self, path : str, stat_key : tuple, ranges : dict):
        self.path = path
        self.stat_key = stat_key
        self.ranges = ranges

    def matchesDisk(self) -> bool:
        """Whether the file still looks as it did right after the write."""
        try:
            return _stat_key(os.stat(self.path)) == self.stat_key
        except OSError:
            return False


class JserSplice:
    """One save's splice: the index it may copy from, and the layout it writes.

    Passed to ``write_jser`` as ``splice=``. After the write is in place, call
    `indexFor` to get the index the next save may use.

        Params:
            index (SpliceIndex): the previous save's index, or None to copy
                nothing (the layout is still recorded)
    """

    def __init__(self, index : SpliceIndex = None):
        self.index = index
        self.layout = None
        self._end = None

    def forgetIndex(self):
        """Copy nothing from here on: the index failed a check."""
        self.index = None

    def noLayout(self):
        """This write's bytes are not the minified orjson form: record nothing."""
        self.layout = None
        self._end = None

    def startPass(self):
        """Begin a minified orjson pass; returns the section writer."""
        self.layout = []
        self._end = None
        return _SectionWriter(self)

    def endPass(self, f):
        self._end = f.tell()

    def indexFor(self, path : str) -> SpliceIndex:
        """The index of the file just written to `path`, or None.

        None when the write did not record a layout, or the file on disk is
        not the size the write ended at.
        """
        if self.layout is None or self._end is None:
            return None
        try:
            st = os.stat(path)
        except OSError:
            return None
        if st.st_size != self._end:
            return None
        ranges = {}
        for key, offset, length, digest in self.layout:
            ranges.setdefault(key, (offset, length, digest))
        return SpliceIndex(path, _stat_key(st), ranges)


class _SectionWriter:
    """Writes one section into the temp file: copied when it can be, else encoded.

    Opens the previous .jser lazily and must be closed; `write_jser` closes it
    in a finally, so the handle is gone before the temp file replaces the
    destination (Windows refuses to replace a file that is open).
    """

    def __init__(self, splice : JserSplice):
        self.splice = splice
        self.src = None
        self.buf = None

    def close(self):
        if self.src is not None:
            self.src.close()
            self.src = None

    def __call__(self, f, sd, encode):
        if not isinstance(sd, KeyedSection):
            raw = encode([[sd]])
            f.write(memoryview(raw)[2:-2])
            return
        start = f.tell()
        index = self.splice.index
        hit = index.ranges.get(sd.key) if index is not None else None
        if hit is not None:
            self._copy(f, *hit)
            digest = hit[2]
        else:
            raw = encode([[sd.load()]])
            part = memoryview(raw)[2:-2]
            f.write(part)
            digest = section_digest(part)
            del part, raw
        self.splice.layout.append((sd.key, start, f.tell() - start, digest))

    def _copy(self, f, offset : int, length : int, digest : bytes):
        """Copy `length` bytes at `offset` of the previous .jser, checking the digest."""
        if self.src is None:
            self.src = open(self.splice.index.path, "rb")
            self.buf = bytearray(COPY_CHUNK)
        src = self.src
        src.seek(offset)
        h = hashlib.sha256()
        view = memoryview(self.buf)
        left = length
        while left:
            n = src.readinto(view[:min(left, COPY_CHUNK)])
            if not n:
                raise SpliceMismatch(f"short read at {offset}")
            h.update(view[:n])
            f.write(view[:n])
            left -= n
        if h.digest() != digest:
            raise SpliceMismatch(f"digest mismatch at {offset}")
