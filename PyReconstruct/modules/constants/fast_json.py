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
