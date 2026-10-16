"""Index a .jser by byte range, so an open can unpack it one section at a time.

``orjson.loads`` has no incremental mode: it takes the whole document and builds
the whole tree before it returns. On a 1.4 GB series that tree peaked at 10.3 GB,
and the open kept it alive while it rebuilt the series data. ``scan_jser`` walks
the file's bytes instead and returns where each section starts and ends, plus
the two things the open needs before it writes anything: the series and log
values, decoded, and every section's contour names, for the name collision
check. No section is decoded here. The open then reads one range, decodes it,
writes it and drops it before reading the next.

The scan reads exactly one shape: a top-level object holding ``"sections"`` (an
array of objects or nulls), ``"series"`` (an object) and optionally ``"log"``,
each once, with at least one section that is not null, and nothing after the
closing brace. Every file this app has written since the shape existed is that
shape. Anything else raises ``NotStreamable`` and the caller reads the file whole,
as it always has: a legacy layout, an unknown or repeated key, a section or
``contours`` value of another type, a file orjson would refuse in its series or
log, and a file that is not JSON at all. So an unusual file opens, or fails,
exactly as it did before, and only the common shape takes the new path.

The scan is strict about the structure it walks (commas, colons, string escapes),
and skips the values it does not need without validating them. Those values all
sit inside a section's range, and the caller decodes every range, so the whole
file is still checked before the open completes.

The scan steps between structural bytes with two regexes rather than looking at
every byte in Python, so the coordinate digits that are nearly all of a file are
skipped in C.
"""

import json
import re

from . import fast_json


_CHUNK = 8 << 20  # read buffer; the consumed prefix is dropped on each refill

_WS = b" \t\n\r"  # JSON whitespace, exactly
_QUOTE = 0x22
_BACKSLASH = 0x5C
_COMMA = 0x2C
_COLON = 0x3A
_LBRACE = 0x7B
_RBRACE = 0x7D
_LBRACKET = 0x5B
_RBRACKET = 0x5D

# Outside a string only these bytes change the depth or start a string. A flat
# array of numbers (every coordinate list, every color) matches whole, so it
# costs one step instead of two.
_STRUCT = re.compile(rb'\[[-+0-9.eE, \t\n\r]*\]|[\[\]{}"]')
# Inside a string only a backslash or the closing quote matters.
_IN_STRING = re.compile(rb'[\\"]')
# A bare scalar (number, true, false, null) ends at one of these.
_SCALAR_END = re.compile(rb'[,}\]: \t\n\r]')


class NotStreamable(Exception):
    """The file is not the one shape ``scan_jser`` reads; read it whole."""


class JserIndex:
    """Where everything is in one .jser, and what the open needs before writing.

        Attributes:
            sections (list): one entry per slot of ``"sections"``: None for a
                null slot, else the (start, end) byte range of the section
            names (list): one entry per slot: None for a null slot, else the
                section's contour names as the file spells them, in file order
            series (dict): the decoded ``"series"`` value
            log: the decoded ``"log"`` value; only meaningful when ``has_log``
            has_log (bool): False when the file has no ``"log"`` key
    """

    def __init__(self):
        self.sections = []
        self.names = []
        self.series = None
        self.log = None
        self.has_log = False


def strict_loads(raw):
    """Decode with the parser a whole-file read would use, or raise NotStreamable.

    ``fast_loads`` retries with the stdlib parser when orjson refuses, and it
    does that for the whole file at once. If the scan let the series or a name
    take the stdlib path alone, the rest of the file would still go through
    orjson, which is not what a whole-file read does. So a value orjson refuses
    sends the whole open back to the whole-file read.
    """
    try:
        if fast_json.have_orjson():
            return fast_json.orjson.loads(raw)
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise NotStreamable(f"value the scan will not decode: {e}") from e


class _Reader:
    """A forward-only view of a file with a bounded buffer and absolute offsets."""

    def __init__(self, f):
        self.f = f
        self.buf = bytearray()
        self.pos = 0     # next unread byte in buf
        self.base = 0    # file offset of buf[0]
        self.eof = False

    def _fill(self) -> bool:
        if self.eof:
            return False
        if self.pos:
            del self.buf[: self.pos]
            self.base += self.pos
            self.pos = 0
        block = self.f.read(_CHUNK)
        if not block:
            self.eof = True
            return False
        self.buf += block
        return True

    def tell(self) -> int:
        return self.base + self.pos

    def peek(self):
        """Skip whitespace; return the next byte without consuming it, or None."""
        while True:
            buf = self.buf
            n = len(buf)
            pos = self.pos
            while pos < n and buf[pos] in _WS:
                pos += 1
            self.pos = pos
            if pos < n:
                return buf[pos]
            if not self._fill():
                return None

    def expect(self, byte):
        if self.peek() != byte:
            raise NotStreamable(f"expected {chr(byte)!r} at byte {self.tell()}")
        self.pos += 1

    def literal(self, word : bytes):
        """Consume `word` (a bare literal such as null) and check it ends there."""
        while len(self.buf) - self.pos < len(word) + 1 and self._fill():
            pass
        end = self.pos + len(word)
        if bytes(self.buf[self.pos:end]) != word:
            raise NotStreamable(f"expected {word!r} at byte {self.tell()}")
        if end < len(self.buf) and not _SCALAR_END.match(self.buf, end):
            raise NotStreamable(f"expected {word!r} at byte {self.tell()}")
        self.pos = end

    def string(self, keep : bool):
        """Consume one string; return its raw bytes, quotes included, if `keep`."""
        self.expect(_QUOTE)
        out = bytearray(b'"') if keep else None
        while True:
            buf = self.buf
            n = len(buf)
            i = start = self.pos
            while True:
                m = _IN_STRING.search(buf, i)
                if m is None:
                    i = n
                    break
                j = m.start()
                if buf[j] == _QUOTE:
                    self.pos = j + 1
                    if keep:
                        out += buf[start:j + 1]
                        return bytes(out)
                    return None
                if j + 2 > n:  # the escaped byte is not loaded yet
                    i = j
                    break
                i = j + 2
            if keep:
                out += buf[start:i]
            self.pos = i
            # Refill at the bottom: both breaks mean the string does not end in
            # what is loaded, and an escape split across the boundary must not
            # spin on an unchanged buffer.
            if not self._fill():
                raise NotStreamable("the file ends inside a string")

    def skip_value(self):
        """Consume one value of any type without keeping or validating it."""
        c = self.peek()
        if c is None:
            raise NotStreamable("the file ends where a value should be")
        if c == _QUOTE:
            self.string(keep=False)
        elif c == _LBRACE or c == _LBRACKET:
            self._skip_container()
        else:
            self._skip_scalar()

    def _skip_scalar(self):
        start = self.tell()
        while True:
            m = _SCALAR_END.search(self.buf, self.pos)
            if m is not None:
                self.pos = m.start()
                break
            self.pos = len(self.buf)
            if not self._fill():
                break
        if self.tell() == start:
            raise NotStreamable(f"expected a value at byte {start}")

    def _skip_container(self):
        depth = 0
        in_string = False
        while True:
            buf = self.buf
            n = len(buf)
            i = self.pos
            while True:
                if in_string:
                    m = _IN_STRING.search(buf, i)
                    if m is None:
                        i = n
                        break
                    j = m.start()
                    if buf[j] == _QUOTE:
                        in_string = False
                        i = j + 1
                        continue
                    if j + 2 > n:  # the escaped byte is not loaded yet
                        i = j
                        break
                    i = j + 2
                    continue
                m = _STRUCT.search(buf, i)
                if m is None:
                    i = n
                    break
                i = m.end()
                ch = buf[m.start()]
                if i - m.start() > 1:
                    # a whole flat array: no change in depth, unless it is
                    # the value being skipped, and then it is all of it
                    if depth == 0:
                        self.pos = i
                        return
                    continue
                if ch == _QUOTE:
                    in_string = True
                elif ch == _LBRACE or ch == _LBRACKET:
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        self.pos = i
                        return
            self.pos = i
            if not self._fill():
                raise NotStreamable("the file ends inside an object or array")

    def members(self):
        """Yield each key of the object that starts here, decoded.

        The caller consumes the key's value before asking for the next key.
        A repeated key raises: a parser keeps only the last copy, and the scan
        would have to guess which one the open reads.
        """
        self.expect(_LBRACE)
        seen = set()
        if self.peek() == _RBRACE:
            self.pos += 1
            return
        while True:
            key = strict_loads(self.string(keep=True))
            if key in seen:
                raise NotStreamable(f"repeated key {key!r}")
            seen.add(key)
            self.expect(_COLON)
            yield key
            c = self.peek()
            if c == _COMMA:
                self.pos += 1
                continue
            if c == _RBRACE:
                self.pos += 1
                return
            raise NotStreamable(f"expected ',' or '}}' at byte {self.tell()}")

    def raw_keys(self) -> list:
        """The raw keys of the object that starts here; every value is skipped.

        Unlike ``members`` a repeated key is fine: a parser keeps one copy of it,
        and the names it holds are the same either way.
        """
        self.expect(_LBRACE)
        keys : list = []
        if self.peek() == _RBRACE:
            self.pos += 1
            return keys
        while True:
            keys.append(self.string(keep=True))
            self.expect(_COLON)
            self.skip_value()
            c = self.peek()
            if c == _COMMA:
                self.pos += 1
                continue
            if c == _RBRACE:
                self.pos += 1
                return keys
            raise NotStreamable(f"expected ',' or '}}' at byte {self.tell()}")


def _scan_section(r : _Reader) -> list:
    """Walk one section object; return its contour names in file order."""
    names = []
    for key in r.members():
        if key != "contours":
            r.skip_value()
            continue
        c = r.peek()
        if c == _LBRACE:
            raw = r.raw_keys()
            if raw:
                names = strict_loads(b"[" + b",".join(raw) + b"]")
        elif c == ord("n"):
            r.literal(b"null")
        else:
            # A contours value that is neither an object nor null: the
            # collision check would iterate it as it stands. Not worth a
            # second copy of that logic here.
            raise NotStreamable("contours is not an object")
    return names


def _scan_sections(r : _Reader, index : JserIndex):
    r.expect(_LBRACKET)
    if r.peek() == _RBRACKET:
        r.pos += 1
        return
    while True:
        c = r.peek()
        if c == _LBRACE:
            start = r.tell()
            names = _scan_section(r)
            index.sections.append((start, r.tell()))
            index.names.append(names)
        elif c == ord("n"):
            r.literal(b"null")
            index.sections.append(None)
            index.names.append(None)
        else:
            raise NotStreamable("a section is neither an object nor null")
        c = r.peek()
        if c == _COMMA:
            r.pos += 1
            continue
        if c == _RBRACKET:
            r.pos += 1
            return
        raise NotStreamable(f"expected ',' or ']' at byte {r.tell()}")


def read_range(f, byte_range) -> bytes:
    """Read the bytes of one (start, end) range from an open binary file."""
    start, end = byte_range
    f.seek(start)
    data = f.read(end - start)
    if len(data) != end - start:
        raise ValueError("the file got shorter while it was being read")
    return data


def scan_jser(f) -> JserIndex:
    """Index the .jser open in `f` (binary, at its start), or raise NotStreamable.

    See the module docstring for the one shape it reads. Holds a bounded
    buffer, the contour names and the series and log values; never a section.
    The caller reads the section ranges from the same `f`, so a file replaced
    on disk between the scan and the reads cannot mix two files.
    """
    index = JserIndex()
    spans = {}
    r = _Reader(f)
    for key in r.members():
        if key == "sections":
            if r.peek() != _LBRACKET:
                raise NotStreamable("sections is not an array")
            _scan_sections(r, index)
        elif key in ("series", "log"):
            if key == "series" and r.peek() != _LBRACE:
                raise NotStreamable("series is not an object")
            start = r.tell()
            r.skip_value()
            spans[key] = (start, r.tell())
        else:
            raise NotStreamable(f"top-level key {key!r}")
    if r.peek() is not None:
        raise NotStreamable("bytes after the end of the document")
    if "series" not in spans or not any(s is not None for s in index.sections):
        raise NotStreamable("no series, or no section that is not null")
    index.series = strict_loads(read_range(f, spans["series"]))
    if "log" in spans:
        index.log = strict_loads(read_range(f, spans["log"]))
        index.has_log = True
    return index
