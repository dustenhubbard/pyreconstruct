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

fast_dumps always returns UTF-8 bytes, so callers open files in binary mode.
fast_loads accepts either bytes or str.
"""

import json

try:
    import orjson
    _HAVE_ORJSON = True
except ImportError:  # pragma: no cover - orjson is a listed dependency
    orjson = None
    _HAVE_ORJSON = False


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
    """Serialize an object to compact UTF-8 JSON bytes."""
    if _HAVE_ORJSON:
        try:
            return orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS)
        except Exception:
            pass
    return json.dumps(obj).encode("utf-8")
