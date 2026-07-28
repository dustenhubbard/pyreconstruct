"""Fast JSON (de)serialization with a stdlib fallback.

Uses orjson when it is installed (much faster dumps, faster loads) and falls
back to the stdlib json whenever orjson *raises* -- e.g. integers that overflow
orjson's signed/unsigned 64-bit range on dump, exotic dict keys, or lone
surrogates. orjson must therefore be a declared dependency (see pyproject.toml /
requirements.txt); without it every call silently uses the slower stdlib path.

Caveat: the fallback only catches cases where orjson RAISES. orjson also has two
SILENT coercions that stdlib json does not, which the fallback cannot intercept:
  * dumps: NaN / Infinity / -Infinity  ->  null     (stdlib writes NaN/Infinity)
  * loads: integers outside [-2**63, 2**64-1]  ->  float  (stdlib keeps the int)
Neither is reachable from PyReconstruct's own saved data -- every serialized
numeric is finite and well within 64-bit, and computed geometry is never
serialized -- so they surface only when re-saving a foreign or hand-edited
.jser. The divergences are pinned in tests/test_perf_equivalence.py.

ASCII output guarantee: fast_dumps emits pure ASCII (every byte < 0x80), with
non-ASCII characters escaped as JSON \\uXXXX sequences -- semantically identical
to stdlib ``json.dumps(..., ensure_ascii=True)``. orjson has no ensure_ascii
option and would otherwise write raw UTF-8. We escape because stock upstream
PyReconstruct on Windows reads series/section files in the platform's locale
text mode (cp1252, not UTF-8): a fork-saved file carrying raw multi-byte object
names or comments would decode to mojibake there (silently re-persisted on the
collaborator's next save) or fail to decode outright. Restricting output to
ASCII keeps fork-written files byte-compatible with those locale-mode readers,
since ASCII is a subset of cp1252/latin-1/UTF-8 alike. The escaping is applied
only when the payload actually contains non-ASCII bytes; the common all-ASCII
save pays a single C-level ``bytes.isascii()`` check and no escape work. (The
stdlib fallback, ``json.dumps(obj)``, already defaults to ensure_ascii=True, so
it emits ASCII with no extra pass.)

fast_dumps always returns ASCII (hence valid UTF-8) bytes, so callers open files
in binary mode. fast_loads accepts either bytes or str.

Separator conventions: ``fast_dumps`` emits orjson's compact ``,`` / ``:`` and is
used for the *working* files inside the hidden series directory, where nothing
but this build ever reads the bytes. The shared ``.jser`` artifact instead goes
through ``std_dumps``, which reproduces stdlib ``json.dumps`` byte-for-byte --
see that function for why the distinction is load-bearing.
"""

import json
import re

try:
    import orjson
    _HAVE_ORJSON = True
except ImportError:  # pragma: no cover - orjson is a listed dependency
    orjson = None
    _HAVE_ORJSON = False


# Matches any character outside the 7-bit ASCII range. In a JSON document such
# characters can only ever occur *inside* string literals (structure -- braces,
# colons, commas, numbers, true/false/null -- is pure ASCII), so blanket-escaping
# them yields valid JSON and never touches orjson's own structural escaping of
# quotes, backslashes, and control chars.
_NON_ASCII = re.compile(r"[^\x00-\x7f]")


def _ascii_escape(match: "re.Match") -> str:
    """Return the JSON \\uXXXX escape(s) for a single non-ASCII character.

    Astral-plane code points (> U+FFFF) are emitted as a UTF-16 surrogate pair,
    exactly as stdlib json's ensure_ascii encoder does.
    """
    cp = ord(match.group(0))
    if cp <= 0xFFFF:
        return "\\u%04x" % cp
    cp -= 0x10000
    hi = 0xD800 + (cp >> 10)
    lo = 0xDC00 + (cp & 0x3FF)
    return "\\u%04x\\u%04x" % (hi, lo)


def _to_ascii(raw: bytes) -> bytes:
    """Escape non-ASCII bytes of an orjson UTF-8 dump to JSON \\uXXXX form.

    Fast path: an all-ASCII payload (the overwhelming majority of saves) is
    returned untouched after one C-level ``isascii()`` scan. Only a payload that
    actually contains non-ASCII bytes pays the decode + single-regex-pass cost.
    """
    if raw.isascii():
        return raw
    return _NON_ASCII.sub(_ascii_escape, raw.decode("utf-8")).encode("ascii")


def fast_loads(data):
    """Parse JSON from bytes or str."""
    if _HAVE_ORJSON:
        try:
            return orjson.loads(data)
        except Exception:
            pass
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    return json.loads(data)


def fast_dumps(obj) -> bytes:
    """Serialize an object to compact ASCII JSON bytes (non-ASCII -> \\uXXXX)."""
    if _HAVE_ORJSON:
        try:
            return _to_ascii(orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS))
        except Exception:
            pass
    # stdlib json.dumps defaults to ensure_ascii=True -> already pure ASCII.
    return json.dumps(obj).encode("utf-8")


# ---------------------------------------------------------------------------
# stdlib-compatible byte layout for the shared .jser artifact
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. `.jser` is not a private format: a second, independent
# implementation reads and re-writes it, lab analysis scripts parse it, and people
# hand-edit it. Those readers were written against the bytes stdlib `json.dumps`
# produces, because that is what this program emitted for its whole history
# before orjson arrived on the write path. orjson writes `,` and `:` where stdlib
# writes `", "` and `": "`, so adopting it silently changed the artifact's byte
# convention as a side effect of a *performance* change. A byte-for-byte
# re-export by the other implementation stopped matching, and its parallel
# importer -- which recognises a document by its first fourteen bytes -- began
# rejecting every file we wrote and falling back to a sequential parse ~27x
# slower on a 427 MB series.
#
# So the writer now states its convention instead of inheriting one:
#
#     a .jser is byte-for-byte what stdlib json.dumps(document) produces.
#
# HOW. Deferring to `json.dumps` for every leaf would be correct by construction
# but costs ~12x on the bytes that dominate a save (measured on a real series'
# trace rows). Instead orjson still does the encoding, and its output is widened
# to stdlib's layout with C-level `bytes.replace`, which is ~3x cheaper than
# re-encoding. Widening is only sound where the two encoders agree on every
# *number* they print, which they do not always do, so `_diverging_number`
# detects the bands where they disagree and those leaves fall back to
# `json.dumps` itself (0.38% of trace rows on a real hand-traced series). The
# assumption that this list of divergences is complete is not left to reasoning:
# tests/test_jser_stdlib_separators.py asserts equality with `json.dumps` over
# millions of float64 draws and hostile strings, so an orjson upgrade that
# changes number formatting fails the suite instead of silently corrupting the
# byte contract the way the original orjson adoption did.
#
# Non-finite floats keep orjson's behaviour (NaN/Infinity -> `null`) rather than
# stdlib's, which is the divergence already accepted and pinned in
# tests/test_perf_equivalence.py. It is unreachable from this program's own data,
# and `null` is valid JSON where stdlib's bare `NaN` is not -- so for the
# round-trip this convention exists to protect, `null` is the better answer.

#: A JSON string literal, as a capturing group so `re.split` yields
#: [outside, string, outside, string, ..., outside] with strings at odd indices.
#: Structure (braces, commas, colons, numbers, keywords) is only ever in the
#: even slots, so separators can be widened there without touching string data.
_STR_LITERAL = re.compile(rb'("(?:[^"\\]|\\.)*")')

def _diverging_number(outside : bytes) -> bool:
    """Whether `outside` may hold a number stdlib json would print differently.

    `outside` must be JSON with all string literals removed, so the only tokens
    in it are structure, ``true``/``false``/``null``, and numbers. Two known
    divergences between orjson's float formatter and stdlib's ``repr``:

      * stdlib switches to exponent notation once the decimal exponent drops
        below -4 (``1e-05``) while orjson keeps expanding the decimal
        (``0.00001``). Four zeros after the point is exactly that boundary.
      * in exponent notation orjson prints a bare exponent (``1e-7``) where
        stdlib pads it to two digits (``1e-07``).

    Detecting the second case needs "is there an exponent here", and outside of
    string literals the only non-number tokens containing ``e`` are ``true`` and
    ``false``, one each -- so any surplus ``e`` is an exponent. Counting is done
    with ``bytes.count`` rather than a regex because a regex here costs more than
    the whole encode it is guarding (measured 121 ms against 13 ms on a real
    series' trace rows, which is the difference between this being worth doing
    and not). ``E`` never appears outside a string except in an exponent, and
    orjson does not emit it, so its mere presence is treated as diverging.

    A True answer means "re-encode with json.dumps", never "emit these bytes",
    so erring towards True costs a little speed and can never cost correctness.

        Params:
            outside (bytes): JSON with every string literal removed
        Returns:
            (bool) True if the bytes must be re-encoded by stdlib json
    """
    return (
        b"0.0000" in outside
        or b"E" in outside
        or outside.count(b"e") != outside.count(b"true") + outside.count(b"false")
    )


def _widen_separators(raw : bytes):
    """Rewrite compact orjson bytes into stdlib json.dumps separator layout.

        Params:
            raw (bytes): an ASCII JSON document/leaf as orjson wrote it
        Returns:
            (bytes) the same JSON with ``", "`` / ``": "`` separators, or
            (None) if `raw` holds a number stdlib would print differently, in
            which case the caller must re-encode with json.dumps
    """
    if b'"' not in raw:
        # no string data at all: the whole buffer is structure and numbers
        if _diverging_number(raw):
            return None
        return raw.replace(b",", b", ").replace(b":", b": ")
    parts = _STR_LITERAL.split(raw)
    if _diverging_number(b"".join(parts[0::2])):
        return None
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace(b",", b", ").replace(b":", b": ")
    return b"".join(parts)


def std_dumps(obj) -> bytes:
    """Serialize to ASCII JSON bytes in stdlib ``json.dumps`` byte layout.

    Byte-for-byte equal to ``json.dumps(obj).encode()`` for every value this
    program serializes -- separators, number formatting and ASCII escaping alike
    -- but encoded by orjson where that is provably equivalent. Use this for the
    shared ``.jser`` artifact; use `fast_dumps` for private working files.
    """
    if _HAVE_ORJSON:
        try:
            raw = _to_ascii(orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS))
        except Exception:
            raw = None
        if raw is not None:
            widened = _widen_separators(raw)
            if widened is not None:
                return widened
    # stdlib json.dumps defaults to ensure_ascii=True -> already pure ASCII.
    return json.dumps(obj).encode("utf-8")
