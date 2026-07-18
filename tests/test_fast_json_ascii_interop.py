"""ASCII-interop contract for fast_json.fast_dumps (review finding 2).

fast_dumps uses orjson on the hot save path. orjson has no ``ensure_ascii``
option and would write raw UTF-8, but stock upstream PyReconstruct on Windows
reads series/section files in the platform locale text mode (cp1252, not
UTF-8). A fork-saved file carrying raw multi-byte object names/comments would
therefore decode to mojibake (silently re-persisted) or fail to decode on a
collaborator's machine.

The fix escapes every non-ASCII character to a JSON ``\\uXXXX`` sequence
(surrogate pairs for astral code points) so output is pure ASCII -- byte-for-byte
identical semantics to stdlib ``json.dumps(..., ensure_ascii=True)``.

The oracle here is stdlib json (ensure_ascii=True) and hand-written literals --
never fast_json's own output echoed back at it.
"""
import json
import contextlib

import pytest

import PyReconstruct.modules.constants.fast_json as fj
from PyReconstruct.modules.constants.fast_json import fast_dumps, fast_loads


@contextlib.contextmanager
def force_backend(use_orjson):
    """Temporarily pin fast_json's backend; restore the real flag afterward."""
    saved = fj._HAVE_ORJSON
    try:
        fj._HAVE_ORJSON = bool(use_orjson)
        yield
    finally:
        fj._HAVE_ORJSON = saved


def _backends():
    backends = [False]                 # stdlib fallback: always available
    if fj.orjson is not None:
        backends.append(True)          # real orjson path
    return backends


BACKENDS = _backends()
BACKEND_IDS = {True: "orjson", False: "stdlib"}


# --------------------------------------------------------------------------- #
# 1. Round-trip of a mixed-script object through every consumer, including the
#    upstream-Windows locale-mode reader simulated via cp1252 / latin-1.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_mixed_script_roundtrips_and_is_ascii(backend):
    obj = {
        "objekt-č-ñ-李-🔬": {
            "comment": "µm dendrite — Σ 日本語 한국어 🧠",
            "tags": ["čpermак", "naïve", "𝔘𝔫𝔦𝔠𝔬𝔡𝔢"],  # astral math-fraktur
            "count": 7,
        }
    }
    with force_backend(backend):
        raw = fast_dumps(obj)

    # (a) pure ASCII: every byte < 0x80
    assert isinstance(raw, bytes)
    assert raw.isascii(), f"non-ASCII byte leaked on backend={BACKEND_IDS[backend]}"
    assert max(raw) < 0x80

    # (b) parses back identically via fast_loads AND stdlib json.loads
    assert fast_loads(raw) == obj
    assert json.loads(raw.decode("ascii")) == obj

    # (c) the actual interop contract: an upstream Windows reader opening the
    #     file in cp1252 / latin-1 text mode gets the identical characters
    #     (ASCII is a common subset), so json.loads reproduces the original.
    for enc in ("cp1252", "latin-1"):
        text = raw.decode(enc)
        assert text == raw.decode("ascii")
        assert json.loads(text) == obj


# --------------------------------------------------------------------------- #
# 2. Equivalence with stdlib ensure_ascii=True over a nasty corpus.
#    Parsed results (not byte layout) must be equal -- fast_dumps is compact,
#    json.dumps is not, but json.loads of each must agree.
# --------------------------------------------------------------------------- #
NASTY_CORPUS = [
    {},
    {"empty_str": "", "empty_dict": {}, "empty_list": []},
    {"ascii_only": "plain old ascii 123 !@#"},
    {"latin1": "café ñoño µm ¡Hola!"},
    {"cjk": "日本語 中文 한국어"},
    {"astral": "🔬🧠🧬 𝔘𝔫𝔦 😀"},
    {"mixed": "objekt-č-ñ-李-🔬"},
    {"control": "tab\tnewline\ncr\rbell\x07nul\x00"},
    {"quotes_backslash": 'she said "hi"\\ and \\n stayed literal'},
    # literal backslash-u: must NOT be double-escaped into a real \uXXXX
    {"literal_backslash_u": r"A and \\uFFFF"},
    {"nested": {"a": ["ç", {"b": "𝔊"}], "c": {"d": {"e": "Ω"}}}},
    {"key-é-🔬": "value", "键": "值"},   # non-ASCII in keys too
    {"astral_boundary": "\U00010000\U0010FFFF"},  # first + last astral cp
    {"bmp_boundary": "￿퟿"},        # around the surrogate gap
    [1, "ç", {"k": "🔬"}, None, True, -3.25],       # top-level list
]


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
@pytest.mark.parametrize("i", range(len(NASTY_CORPUS)))
def test_equivalent_to_stdlib_ensure_ascii(i, backend):
    obj = NASTY_CORPUS[i]
    oracle = json.dumps(obj, ensure_ascii=True)   # independent reference
    with force_backend(backend):
        raw = fast_dumps(obj)
    assert raw.isascii(), f"case {i} backend={BACKEND_IDS[backend]} not ASCII"
    # semantic equality: both parse to the same Python object
    assert json.loads(raw) == json.loads(oracle), f"case {i}"
    # and equal to the original input as well
    assert json.loads(raw) == json.loads(json.dumps(obj)), f"case {i}"


# --------------------------------------------------------------------------- #
# 3. Astral-plane characters produce a correct UTF-16 surrogate pair, matching
#    stdlib exactly (hand-derived expectation for the microscope emoji).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_astral_surrogate_pair_exact(backend):
    with force_backend(backend):
        raw = fast_dumps({"e": "🔬"})            # U+1F52C
    text = raw.decode("ascii")
    # hand-derived: 0x1F52C -> surrogate pair D83D DD2C
    assert "\\ud83d\\udd2c" in text
    assert json.loads(text) == {"e": "🔬"}
    # exactly what stdlib emits for the same string content
    assert json.loads(raw) == json.loads(json.dumps({"e": "🔬"}, ensure_ascii=True))


# --------------------------------------------------------------------------- #
# 4. No double-escaping: a string that literally contains backslash-u must stay
#    a literal backslash-u (orjson escapes the backslash; our pass must not turn
#    it into a real \uXXXX escape).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_literal_backslash_u_not_double_escaped(backend):
    original = r"é stays literal, é becomes escaped"
    with force_backend(backend):
        raw = fast_dumps({"s": original})
    assert raw.isascii()
    # round-trips to exactly the original 6-char-prefixed literal
    assert fast_loads(raw)["s"] == original
    assert json.loads(raw.decode("ascii"))["s"] == original


# --------------------------------------------------------------------------- #
# 5. Legacy files: raw-UTF-8 series/section files written by EARLIER fork builds
#    (orjson with no escaping) must STILL load unchanged, because the loaders
#    read binary and decode UTF-8. ASCII output is forward-compatible; this
#    proves the backward direction.
# --------------------------------------------------------------------------- #
def test_legacy_raw_utf8_file_still_loads(tmp_path):
    obj = {
        "objekt-č-ñ-李-🔬": {"comment": "µm 🧠 日本語", "count": 3},
        "plain": [1, 2, 3],
    }
    # Simulate exactly what an older fork build wrote: raw UTF-8, NOT escaped.
    legacy_bytes = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    assert not legacy_bytes.isascii()            # genuinely raw multi-byte UTF-8

    fp = tmp_path / "legacy.section"
    fp.write_bytes(legacy_bytes)

    # Loaders open "rb" and hand the bytes to fast_loads (utf-8 decode).
    with open(fp, "rb") as f:
        loaded = fast_loads(f.read())
    assert loaded == obj


def test_new_ascii_file_reads_as_utf8_and_cp1252(tmp_path):
    """A file written by the CURRENT (ASCII) build loads through the merged #70
    utf-8 readers AND through an upstream locale-mode (cp1252) reader."""
    obj = {"name": "č-ñ-李-🔬", "n": 5}
    fp = tmp_path / "new.section"
    fp.write_bytes(fast_dumps(obj))

    with open(fp, "rb") as f:                     # binary loader (fast path)
        assert fast_loads(f.read()) == obj
    with open(fp, "r", encoding="utf-8") as f:    # merged #70 explicit utf-8
        assert json.load(f) == obj
    with open(fp, "r", encoding="cp1252") as f:   # upstream Windows locale mode
        assert json.load(f) == obj
