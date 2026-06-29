"""Roundtrip / contract tests for fast_json (orjson wrapper + stdlib fallback).

fast_json.py promises three things its callers rely on, independent of which
backend is active:
  * fast_dumps -> UTF-8 *bytes* (so files are opened in binary mode);
  * fast_loads accepts *both* bytes and str;
  * dumps -> loads is a faithful roundtrip for the finite, in-64-bit-range data
    PyReconstruct actually serializes (nested dict/list/int/float/str/bool/None,
    with point tuples decoding back as lists).

Expected values here are derived independently of fast_json: against Python's
stdlib ``json`` and against hand-written literals, never by echoing fast_json's
own output back at it.

We exercise BOTH code paths explicitly via ``force_backend``: the real orjson
path (the declared dependency, used in production) and the stdlib fallback (what
runs if orjson is ever absent). The roundtrip *semantics* must agree on both;
the byte-exact compactness guarantee is an orjson-path property (the docstring
calls the fallback "the slower stdlib path"), so it is asserted only there.

The orjson-vs-stdlib *divergences* (NaN/Infinity on dump, >64-bit ints on load)
are deliberately NOT retested here -- they are pinned in test_perf_equivalence.py.
"""
import json
import contextlib

import pytest

import PyReconstruct.modules.constants.fast_json as fj
from PyReconstruct.modules.constants.fast_json import fast_dumps, fast_loads


# --------------------------------------------------------------------------- #
# Backend control: force the orjson path or the stdlib-fallback path so the
# documented contract can be checked "whether or not orjson is installed".
# --------------------------------------------------------------------------- #
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
    """The backends worth testing on this machine.

    The stdlib fallback is always exercisable. The orjson path is only
    exercisable if orjson is actually importable (forcing the flag True without
    the module present would raise inside fast_json, which is not its contract).
    """
    backends = [False]                 # stdlib fallback: always available
    if fj.orjson is not None:
        backends.append(True)          # real orjson path
    return backends


BACKENDS = _backends()
BACKEND_IDS = {True: "orjson", False: "stdlib"}


def test_orjson_is_the_live_backend():
    """Sanity: in this declared-dependency environment orjson should be present
    and active. If it is somehow absent the rest of the suite still runs on the
    fallback path -- but flag it, because production is meant to use orjson."""
    if fj.orjson is None:
        pytest.skip("orjson not installed; only the stdlib fallback is exercised")
    assert fj._HAVE_ORJSON is True


# --------------------------------------------------------------------------- #
# Representative payloads. Every value is finite and within signed/unsigned
# 64-bit range -- i.e. the data PyReconstruct genuinely writes -- so the two
# backends must agree and the roundtrip must be lossless.
# --------------------------------------------------------------------------- #
ROUNDTRIP_CASES = {
    "scalar_mix": {"i": -7, "f": -3.25, "s": "hi", "t": True, "fl": False, "n": None},
    "nested": {"a": 1, "b": [1, 2, 3], "c": {"d": 4.5, "e": [None, True]}},
    "deep": {"x": [{"y": [1, {"z": [False, {"w": "leaf"}]}]}]},
    "top_level_list": [1, 2, [3, 4], {"k": "v"}, None, True],
    "empty_containers": {"d": {}, "l": [], "s": ""},
    "floats": {"vals": [0.0, -0.0, 1.5, -3.25, 1e-9, 1e9, 0.1, 1.0 / 3.0]},
    "ints_in_range": {"vals": [0, -1, 2 ** 40, -(2 ** 40), 2 ** 63 - 1, -(2 ** 63),
                               2 ** 64 - 1]},
    "negatives": {"coords": [-5, -12.5, -0.0, -(2 ** 30)]},
}


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
@pytest.mark.parametrize("name", list(ROUNDTRIP_CASES))
def test_roundtrip_matches_stdlib_json(name, backend):
    """dumps->loads must reproduce exactly what stdlib json would, on both
    backends. stdlib is the independent oracle (not fast_json's own output)."""
    obj = ROUNDTRIP_CASES[name]
    expected = json.loads(json.dumps(obj))   # independent reference
    with force_backend(backend):
        got = fast_loads(fast_dumps(obj))
    # Compare structurally with sorted keys so dict ordering can't matter.
    assert json.dumps(got, sort_keys=True) == json.dumps(expected, sort_keys=True), \
        f"{name} / backend={BACKEND_IDS[backend]}"


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_roundtrip_is_identity_for_plain_objects(backend):
    """For objects with only str keys and no tuples, dumps->loads is a true
    Python-equality identity (== against the original input, not its dump)."""
    obj = {"a": 1, "b": [1, 2, 3], "c": {"d": 4.5}, "n": None,
           "bl": [True, False], "neg": -7, "f": -3.25}
    with force_backend(backend):
        assert fast_loads(fast_dumps(obj)) == obj


# --------------------------------------------------------------------------- #
# Return / accept types.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_dumps_returns_utf8_bytes(backend):
    with force_backend(backend):
        out = fast_dumps({"k": "v", "n": [1, 2]})
    assert isinstance(out, bytes)
    assert out.decode("utf-8")            # valid UTF-8; no exception


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_loads_accepts_bytes_and_str(backend):
    """fast_loads must take both bytes and str and give the same result."""
    obj = {"k": "v", "nums": [1, 2, 3], "nested": {"x": True}}
    with force_backend(backend):
        raw = fast_dumps(obj)
        from_bytes = fast_loads(raw)
        from_str = fast_loads(raw.decode("utf-8"))
    assert from_bytes == obj
    assert from_str == obj
    assert from_bytes == from_str


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_loads_accepts_bytearray(backend):
    """The fallback explicitly handles bytearray; orjson accepts it too."""
    obj = {"x": 1, "y": [2, 3]}
    with force_backend(backend):
        ba = bytearray(fast_dumps(obj))
        assert fast_loads(ba) == obj


# --------------------------------------------------------------------------- #
# Point tuples -> lists. PyReconstruct stores geometry as lists of (x, y)
# tuples; JSON has no tuple type, so they must come back as lists with the
# values preserved.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_point_tuples_decode_as_lists(backend):
    traces = {"traces": [[(1.5, 2.5), (3.0, 4.0)], [(0.0, 0.0)]]}
    with force_backend(backend):
        got = fast_loads(fast_dumps(traces))
    # Independently hand-derived expectation: tuples flattened to lists.
    assert got == {"traces": [[[1.5, 2.5], [3.0, 4.0]], [[0.0, 0.0]]]}
    # And every decoded container is a list, never a tuple.
    for contour in got["traces"]:
        assert type(contour) is list
        for pt in contour:
            assert type(pt) is list


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_nested_tuple_roundtrip_matches_listified_input(backend):
    """A tuple roundtrips to the same thing its list-equivalent does."""
    tup_obj = {"p": (1, 2, 3), "q": [(4, 5), (6, 7)]}
    list_obj = {"p": [1, 2, 3], "q": [[4, 5], [6, 7]]}
    with force_backend(backend):
        assert fast_loads(fast_dumps(tup_obj)) == list_obj


# --------------------------------------------------------------------------- #
# Non-string dict keys. orjson is invoked with OPT_NON_STR_KEYS, and stdlib
# json coerces non-str keys too. The verified, asserted behavior is that keys
# come back as their JSON-string forms -- identical to stdlib json -- so a
# round-trip is NOT key-type-preserving (int 1 -> "1").
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_int_keys_become_string_keys(backend):
    with force_backend(backend):
        got = fast_loads(fast_dumps({1: "a", 2: "b", 10: "c"}))
    # Hand-derived: integer keys serialize to their decimal string form.
    assert got == {"1": "a", "2": "b", "10": "c"}
    assert all(isinstance(k, str) for k in got)


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_nonstr_keys_match_stdlib_exactly(backend):
    """Whatever non-str keys do, they must do *the same thing stdlib json does*.
    stdlib is the independent oracle: int->"1", float->"3.5".

    (A bool key is deliberately omitted here: in a Python dict literal True
    collides with the int key 1 -- True == 1 and hash(True) == hash(1) -- so it
    would never reach the serializer as a distinct key. Bool keys get their own
    collision-free case below.)"""
    obj = {1: "int", 3.5: "float", "s": "str"}
    expected = json.loads(json.dumps(obj))     # {"1":.., "3.5":.., "s":..}
    with force_backend(backend):
        got = fast_loads(fast_dumps(obj))
    assert got == expected
    assert set(got.keys()) == {"1", "3.5", "s"}


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_bool_keys_become_json_string_keys(backend):
    """Bool dict keys serialize to JSON's lowercase 'true'/'false', exactly as
    stdlib json does. Kept collision-free (no 0/1 int keys present)."""
    obj = {True: "yes", False: "no"}
    expected = json.loads(json.dumps(obj))     # {"true": "yes", "false": "no"}
    with force_backend(backend):
        got = fast_loads(fast_dumps(obj))
    assert got == {"true": "yes", "false": "no"}   # hand-derived
    assert got == expected


# --------------------------------------------------------------------------- #
# Unicode. Multi-byte and astral-plane (emoji) characters must survive intact.
# --------------------------------------------------------------------------- #
UNICODE_STRINGS = [
    "µm · dendrite — Σ",          # latin-1 + punctuation + greek
    "🧠 synapse 🔬",               # astral-plane emoji (surrogate pair territory)
    "∑ ∫ ∂ √ ≈ ≠",               # math symbols
    "日本語 한국어 Ελληνικά",        # CJK + hangul + greek
    "a\tb\nc",                     # control chars (tab, newline)
    "",                            # empty string
]


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
@pytest.mark.parametrize("s", UNICODE_STRINGS)
def test_unicode_roundtrips_unchanged(s, backend):
    with force_backend(backend):
        got = fast_loads(fast_dumps({"u": s}))["u"]
    assert got == s                      # identity against the original literal


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda b: BACKEND_IDS[b])
def test_unicode_key_roundtrips(backend):
    with force_backend(backend):
        got = fast_loads(fast_dumps({"µm": 1, "🧠": 2}))
    assert got == {"µm": 1, "🧠": 2}


# --------------------------------------------------------------------------- #
# Compactness. This is an orjson-path guarantee (no whitespace at all). The
# stdlib fallback uses json.dumps' default separators, which DO emit spaces --
# the docstring explicitly frames it as the slower path -- so we don't make a
# false no-space claim there; we only require it to still roundtrip.
# --------------------------------------------------------------------------- #
def test_orjson_output_has_no_whitespace():
    if fj.orjson is None:
        pytest.skip("orjson not installed")
    obj = {"a": 1, "b": [1, 2, 3], "c": {"d": 4.5}, "list": [{"x": 1}, {"y": 2}]}
    with force_backend(True):
        out = fast_dumps(obj)
    # orjson is fully compact: no space, tab, or newline anywhere.
    assert b" " not in out
    assert b"\t" not in out
    assert b"\n" not in out
    # Specifically: no space after ':' or ',' separators.
    assert b": " not in out
    assert b", " not in out


def test_stdlib_fallback_still_roundtrips_even_if_not_byte_compact():
    """The fallback need not be byte-compact, but it must still roundtrip and
    return bytes -- the part of the contract that holds without orjson."""
    obj = {"a": 1, "b": [1, 2, 3]}
    with force_backend(False):
        out = fast_dumps(obj)
        assert isinstance(out, bytes)
        assert fast_loads(out) == obj


# --------------------------------------------------------------------------- #
# Cross-backend agreement: when orjson is present, both paths must decode to
# equal Python objects for the data PyReconstruct serializes (a single check
# that the fallback is a faithful stand-in, not a behavior change).
# --------------------------------------------------------------------------- #
def test_orjson_and_stdlib_paths_decode_equal():
    if fj.orjson is None:
        pytest.skip("orjson not installed; cannot compare both paths")
    obj = {
        "traces": [[(1.5, 2.5), (3.0, 4.0)]],
        "meta": {"name": "µm 🧠", "i": -7, "f": -3.25, "flags": [True, False, None]},
        1: "int_key",
    }
    with force_backend(True):
        via_orjson = fast_loads(fast_dumps(obj))
    with force_backend(False):
        via_stdlib = fast_loads(fast_dumps(obj))
    assert via_orjson == via_stdlib