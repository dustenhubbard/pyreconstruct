"""The .jser byte-layout contract: a saved file is byte-for-byte json.dumps.

``.jser`` is not a private format. A second, independent implementation reads it
and re-writes it, lab analysis scripts parse it, and people hand-edit it. Those
readers were written against the bytes stdlib ``json.dumps`` produces, because
that is what this program emitted for its entire history until ``orjson`` reached
the write path -- at which point ``,`` and ``:`` replaced ``", "`` and ``": "``
and the artifact's byte convention changed as a side effect of a *performance*
change. Nothing tested the pair together, so nobody noticed for two releases: a
byte-for-byte re-export by the other implementation stopped matching, and its
parallel importer -- which recognises a document by its first fourteen bytes --
rejected every file this program wrote and fell back to a sequential parse ~27x
slower on a 427 MB series.

The lesson is not about separators. It is that **a byte-level contract with a
second implementation, left untested, breaks on the next unrelated performance
change.** So the contract is asserted here directly and mechanically:

  * ``std_dumps(x)`` is byte-identical to ``json.dumps(x).encode()`` -- not just
    for separators but for number formatting and ASCII escaping too -- over an
    unfriendly battery, hundreds of thousands of random float64 draws, and
    hostile strings built from the exact characters that could fool the widener.
  * a minified document is byte-identical to ``json.dumps(document)``, and begins
    with the fourteen bytes the other implementation's fast importer requires.
  * the assumptions this makes about *orjson's* output are pinned, so an orjson
    upgrade that changes number formatting or separators fails this suite instead
    of silently corrupting the artifact the way the original adoption did.

``fast_dumps`` is deliberately left alone: it still writes orjson-compact bytes
for the working files inside the hidden series directory, which nothing but this
build ever reads.
"""
import json
import math
import os
import random
import shutil
import struct

import pytest

from PyReconstruct.modules.constants.fast_json import (
    _diverging_number,
    _STR_LITERAL,
    _widen_separators,
    fast_dumps,
    std_dumps,
)
from PyReconstruct.modules.constants.jser_format import dumps_jser, pretty_default

orjson = pytest.importorskip("orjson")


def _stdlib(obj) -> bytes:
    """What stdlib json.dumps writes, which is the contract std_dumps must meet."""
    return json.dumps(obj).encode()


# --------------------------------------------------------------------------
# the contract, on values chosen to break it
# --------------------------------------------------------------------------

#: Values grouped by the mechanism each one probes. Every case must serialize
#: byte-identically to stdlib json.
HOSTILE_VALUES = [
    # empties and scalars
    {}, [], [[]], [{}], {"a": {}}, {"a": []}, 0, -1, True, False, None, "",
    # separators appearing *inside* string data, which must never be widened
    {"a": "x,y"}, {"a": "x: y"}, {"k,1": "v:2"}, {"a": ",,,"}, {"a": ":::"},
    {"a": 'he said "hi", ok'}, {"a": "esc\\\"quote, and: colon"},
    {"a": "back\\slash"}, {"a": "trailing\\\\"}, {"a": '","'}, {"a": '\\",\\"'},
    # text that mimics the number patterns the widener's guard looks for
    {"a": "0.0000"}, {"a": "1e-5"}, {"a": "gene-5"}, {"a": "e-7"},
    {"a": "true"}, {"a": "false"}, {"a": "eeee"}, {"a": "1E-7"},
    {"a": "value-7e-9end"}, {"true": "e"}, {"0.0000": [1, 2]},
    # control characters and non-ASCII, which must come out as \uXXXX
    {"a": "tab\there"}, {"a": "nl\nhere"}, {"a": "\x00nul"}, {"a": "\x1f"},
    {"a": "µm"}, {"a": "\U0001f52c"}, {"a": "é"}, {"µ": "\U0001f9e0"},
    # the number bands where orjson and stdlib disagree
    1e-4, 1e-5, 1e-6, 1e-7, 1e-8, -1e-5, -1e-7, 5e-324, 1e16, 1e17, 1e21, 1e22,
    2.2250738585072014e-308, 1.7976931348623157e308, 0.1, 1 / 3, -0.0, 0.0,
    123456789.123456789, [1e-7, 2.0], {"m": 0.00254}, {"t": [1e-9, 1.0, 2.5]},
    # integers around orjson's 64-bit limits, where it raises and stdlib is used
    2**63 - 1, 2**63, 2**64 - 1, 2**64, -(2**63), -(2**63) - 1, 10**40, -(10**40),
    # non-string keys
    {1: "a", 2: "b"}, {10: [1, 2]}, {True: 1}, {1.5: "x"},
    # shapes the writer actually emits
    [[1.0, 2.0], [3.0, 4.0], [255, 0, 0], True, False, True, ["tag,1", "t:2"], []],
    [[1e-7, 2.0], [3.0, 4.0], [0, 0, 0], False, False, False, [], ["c,d"]],
    {"tforms": {"default": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]}},
    {"contours": {"d01": [[[1.5], [2.5], [0, 0, 0], True, True, True, [], []]]}},
]


@pytest.mark.parametrize("obj", HOSTILE_VALUES, ids=lambda o: repr(o)[:48])
def test_std_dumps_is_byte_identical_to_stdlib_json(obj):
    assert std_dumps(obj) == _stdlib(obj)


def test_std_dumps_output_is_pure_ascii():
    for obj in HOSTILE_VALUES:
        assert std_dumps(obj).isascii(), repr(obj)


def test_std_dumps_matches_stdlib_over_random_float64_draws():
    """The float formatter is where the two encoders actually disagree.

    Random 64-bit patterns land overwhelmingly in the extreme exponent ranges,
    which is exactly where the divergence lives, so this is a hostile sample
    rather than a representative one.
    """
    rng = random.Random(20260727)
    checked = 0
    for _ in range(120_000):
        f = struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0]
        if not math.isfinite(f):
            continue
        checked += 1
        assert std_dumps([f]) == _stdlib([f]), repr(f)
    assert checked > 100_000


def test_std_dumps_matches_stdlib_across_the_whole_exponent_range():
    """Log-uniform magnitudes, which concentrate draws near the decision points."""
    rng = random.Random(4242)
    for _ in range(60_000):
        try:
            f = rng.choice((1, -1)) * 10.0 ** rng.uniform(-320, 300)
        except OverflowError:
            continue
        if not math.isfinite(f) or f == 0.0:
            continue
        assert std_dumps([f]) == _stdlib([f]), repr(f)


def test_std_dumps_matches_stdlib_on_plain_decimals_and_integers():
    """The values real coordinate data is actually made of."""
    for i in range(-3000, 3001):
        for v in (i, float(i), i / 8.0, i / 1000.0, i / 100_000.0, i * 1e-7):
            assert std_dumps([v]) == _stdlib([v]), repr(v)


def test_std_dumps_matches_stdlib_on_hostile_strings():
    """Strings drawn from exactly the characters that could fool the widener."""
    alphabet = ',:"\\\n\t eE-0159.\x00{}[]' + "truefalsnµ\U0001f52c"
    rng = random.Random(31337)
    for _ in range(40_000):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 16)))
        obj = {s: [s, 1.0, True, False, None, "0.0000", "1e-5"]}
        assert std_dumps(obj) == _stdlib(obj), repr(s)


def test_non_finite_floats_keep_orjson_null_not_stdlib_nan():
    """A deliberate, pre-existing divergence, pinned so it cannot drift.

    stdlib writes bare ``NaN``/``Infinity``, which is not valid JSON and which no
    other implementation is obliged to read. orjson's ``null`` is valid, is what
    this program has written since orjson arrived, and round-trips through the
    other implementation unchanged -- so for the byte contract this module
    protects, ``null`` is the better answer. Unreachable from this program's own
    data; only a foreign or hand-edited file can carry a non-finite value.
    """
    for value in (float("nan"), float("inf"), float("-inf")):
        assert std_dumps({"v": value}) == b'{"v": null}'


# --------------------------------------------------------------------------
# the guard, and the orjson behaviour it assumes
# --------------------------------------------------------------------------

def test_guard_fires_on_the_bands_where_the_encoders_disagree():
    """Bands the widener must refuse to touch, or it would emit wrong bytes."""
    for value in (1e-5, 1e-6, 1e-7, -1e-5, 5e-324, 1e16, 1e21):
        raw = orjson.dumps([value])
        assert _diverging_number(raw), repr(value)
        assert _widen_separators(raw) is None, repr(value)


def test_guard_does_not_fire_on_ordinary_coordinate_values():
    """If the guard fired on real data the fast path would be dead weight."""
    row = [[1.5, 2.25], [3.0, 4.125], [255, 0, 0], True, False, True, [], []]
    raw = orjson.dumps(row)
    assert not _diverging_number(b"".join(
        p for i, p in enumerate(raw.split(b'"')) if i % 2 == 0
    ))
    assert _widen_separators(raw) == _stdlib(row)


def test_keywords_containing_e_do_not_trip_the_guard():
    """``true`` and ``false`` are the only non-number tokens carrying an ``e``."""
    assert not _diverging_number(b"[true, false, null, 1, 2.5]")
    assert _diverging_number(b"[1e-7]")
    assert _diverging_number(b"[0.00001]")
    assert _diverging_number(b"[1E5]")


def test_orjson_still_writes_the_separators_this_module_assumes():
    """If orjson ever emits spaces, the widener would double them."""
    assert orjson.dumps({"a": [1, 2], "b": 3}) == b'{"a":[1,2],"b":3}'


def test_orjson_still_writes_lowercase_exponents():
    """An uppercase ``E`` would slip past a lowercase-only exponent count."""
    for value in (1e-7, 1e16, 1e300, 5e-324):
        assert b"E" not in orjson.dumps(value)


def test_fast_dumps_is_untouched_and_still_compact():
    """Working files inside the hidden directory keep the cheaper layout."""
    assert fast_dumps({"a": [1, 2], "b": 3}) == b'{"a":[1,2],"b":3}'


# --------------------------------------------------------------------------
# the document, and the fourteen bytes the other implementation looks for
# --------------------------------------------------------------------------

def _document():
    return {
        "sections": [
            None,
            {"src": "a.tif", "mag": 0.00254, "align_locked": True,
             "tforms": {"default": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]},
             "thickness": 0.05,
             "contours": {"d01": [[[1.5, 2.5], [3.5, 4.5], [255, 0, 0],
                                   True, True, True, ["tag,a"], ["note: x"]]]},
             "flags": [], "calgrid": False,
             "brightness_contrast_profiles": {}},
        ],
        "series": {"current_section": 0, "src_dir": "", "window": [0, 0, 1, 1],
                   "editors": ["a"], "object_groups": {"g": ["d01"]},
                   "options": {"small_dist": 0.01}, "code": "",
                   "host_tree": {"d02": ["d01"]}},
        "log": "Date, Time, User, Obj, Sections, Event",
    }


def test_minified_document_is_byte_identical_to_stdlib_json_dumps():
    doc = _document()
    assert dumps_jser(doc, pretty=False) == json.dumps(doc).encode()


#: Documents that exercise the minified assembler's branches: a hole in
#: ``sections``, an empty section list, an unknown top-level key, a non-string key,
#: a ``sections`` value that is not a list, a missing ``sections``, a value in the
#: band where the widener defers to stdlib, and things that are not documents.
MINIFY_SHAPES = [
    {"sections": [None, {"src": "a.tif"}], "series": {"a": 1}, "log": ""},
    {"sections": [], "series": {}, "log": "x"},
    {"sections": [None], "series": {}, "log": "", "extra": {"k": [1, 2]}},
    {"sections": [{"src": "a"}], "series": {}, "log": "", 1: "nonstr"},
    {"sections": "not a list", "series": {}, "log": ""},
    {"series": {}, "log": ""},
    {"sections": [{"m": 1e-5}, {"m": 0.5}], "series": {}, "log": ""},
    [1, 2, 3], {}, None,
]


@pytest.mark.parametrize("doc", MINIFY_SHAPES, ids=lambda d: repr(d)[:44])
def test_minified_assembly_matches_stdlib_on_every_document_shape(doc):
    """Assembling per section must not diverge from serializing in one go."""
    assert dumps_jser(doc, pretty=False) == json.dumps(doc).encode()


def test_minified_document_starts_with_the_fast_import_prefix():
    """The other implementation recognises a document by these bytes alone.

    It compares the first fourteen bytes and, on a mismatch, abandons its
    parallel 64 MB-window importer before a worker pool even exists -- which is
    how a whitespace change cost a 27x import slowdown.
    """
    raw = dumps_jser(_document(), pretty=False)
    assert raw.startswith(b'{"sections": [')


def _split_literals(raw : bytes):
    """Split `raw` into (structure-only bytes, list of string literals)."""
    parts = _STR_LITERAL.split(raw)
    return b"".join(parts[0::2]), parts[1::2]


def _outside_strings(raw : bytes) -> bytes:
    """`raw` with every JSON string literal removed, leaving only structure."""
    return _split_literals(raw)[0]


@pytest.mark.parametrize("pretty", [True, False])
def test_no_compact_separator_survives_anywhere_outside_a_string(pretty):
    """Both modes use one serializer, so leaf bytes cannot differ between them.

    A comma or colon outside string data is always followed by a space (minified)
    or a newline (pretty). This is the invariant that was silently violated.
    """
    raw = dumps_jser(_document(), pretty=pretty)
    structure = _outside_strings(raw)
    for i, byte in enumerate(structure[:-1]):
        if byte in b",:":
            assert structure[i + 1:i + 2] in (b" ", b"\n"), (
                f"compact {chr(byte)!r} at offset {i}: "
                f"{structure[max(0, i - 20):i + 20]!r}"
            )
    assert structure[-1:] == b"}"


def test_pretty_and_minified_differ_only_in_whitespace():
    """The flag is a whitespace switch, not a second serializer.

    Both modes must emit the same string literals in the same order and the same
    structural tokens in the same order -- so the only difference between the two
    files is whitespace. If the modes ever encoded a *value* differently, a
    different float spelling say, one of these two assertions fails. That
    distinction matters because the two modes now serve different audiences and
    it would be easy to let them drift into two serializers.
    """
    doc = _document()
    pretty_struct, pretty_lits = _split_literals(dumps_jser(doc, pretty=True))
    mini_struct, mini_lits = _split_literals(dumps_jser(doc, pretty=False))
    assert pretty_lits == mini_lits
    assert b"".join(pretty_struct.split()) == b"".join(mini_struct.split())


# --------------------------------------------------------------------------
# the flag, honoured when it is set rather than when the module was imported
# --------------------------------------------------------------------------

def test_pretty_default_reads_the_environment_at_call_time(monkeypatch):
    """Exporting the variable mid-session must affect the next save.

    It used to be read once at import, so a session that set it saw no effect --
    and the test that claimed to cover it monkeypatched the resulting module
    global instead of setting the variable, so the documented interface was never
    exercised at all.
    """
    monkeypatch.delenv("PYRECON_JSER_MINIFY", raising=False)
    assert pretty_default() is True
    monkeypatch.setenv("PYRECON_JSER_MINIFY", "1")
    assert pretty_default() is False
    assert b"\n" not in dumps_jser(_document())
    monkeypatch.setenv("PYRECON_JSER_MINIFY", "0")
    assert pretty_default() is True
    assert b"\n" in dumps_jser(_document())


def test_explicit_pretty_argument_overrides_the_environment(monkeypatch):
    monkeypatch.setenv("PYRECON_JSER_MINIFY", "1")
    assert b"\n" in dumps_jser(_document(), pretty=True)
    monkeypatch.delenv("PYRECON_JSER_MINIFY", raising=False)
    assert b"\n" not in dumps_jser(_document(), pretty=False)


# --------------------------------------------------------------------------
# end to end: the saved file must still contain the series that went in
# --------------------------------------------------------------------------

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)


def _content(doc : dict) -> dict:
    """Everything about a .jser that a writer change must not silently drop.

    Deliberately provenance-free -- sets are compared as sets and arrays whose
    order this writer canonicalizes are sorted -- so the digest is sensitive to
    lost *content* and blind to layout and ordering. Coordinates are compared as
    exact floats, not rounded, since precision loss is the other way a save can
    quietly damage a series.
    """
    def trace(t):
        # a row is [x, y, colour, closed, negative, hidden, fill_mode, tags,
        # history]; tags is the only set-derived field, so only tags is
        # order-normalized -- everything else must survive verbatim
        t = list(t)
        if len(t) > 7 and isinstance(t[7], list):
            t[7] = sorted(t[7], key=str)
        return json.dumps(t, sort_keys=True)

    sections = []
    for sd in doc["sections"]:
        if sd is None:
            sections.append(None)
            continue
        contours = {}
        for name, traces in sd.get("contours", {}).items():
            contours[name] = sorted(trace(t) for t in traces)
        sections.append({
            "src": sd.get("src"), "mag": sd.get("mag"),
            "thickness": sd.get("thickness"),
            "tforms": {k: tuple(v) for k, v in sd.get("tforms", {}).items()},
            "flags": sorted(map(repr, sd.get("flags", []))),
            "contours": contours,
        })
    series = doc.get("series", {})
    return {
        "sections": sections,
        "ztraces": {k: json.dumps(v, sort_keys=True)
                    for k, v in series.get("ztraces", {}).items()},
        "editors": sorted(series.get("editors") or []),
        "object_groups": {k: sorted(v)
                          for k, v in (series.get("object_groups") or {}).items()},
        "obj_attrs": json.dumps(series.get("obj_attrs") or {}, sort_keys=True),
        "host_tree": {k: sorted(v)
                      for k, v in (series.get("host_tree") or {}).items()},
        "log": doc.get("log", ""),
    }


def _open(tmp_path, name):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.datatypes.series import Series

    fp = str(tmp_path / name)
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    return series


def test_resaving_a_series_preserves_every_category_of_content(tmp_path):
    """A real round trip: the file that goes in and the file that comes out.

    The end-to-end test this stands in for compared ``_semantic(first)`` with
    ``_semantic(json.loads(raw))`` where ``first`` *was* ``json.loads(raw)`` --
    literally ``X == X``, which passes even if the save discards the entire audit
    log, or every flag, tag, transform, editor and group. Two things make this
    version failable instead:

      * the comparison is between **two different files**, one written by an
        earlier save and one by a later save of what that file contained, so
        anything dropped on the way through is missing on only one side;
      * every category the vacuous test could not see is **populated first, and
        asserted non-empty**, because the original fixture carries no log, no
        flags, no editors and no groups -- so a digest of it proves nothing about
        those fields no matter how it is compared.

    The fixture is also an older schema that opening migrates, which is why the
    input to the compared round trip is a *saved* file rather than the fixture.
    """
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")

    # Migrate to the current schema and populate what the fixture lacks. Note
    # opening the legacy fixture drops the 9th, legacy per-trace history field --
    # this build has no Trace.history at all -- so the round trip below is
    # measured on the migrated file, not on the fixture, and history is not among
    # the categories it can assert on. That drop is pre-existing behaviour and
    # not what this test is about.
    shutil.copyfile(FIXTURE, str(tmp_path / "first.jser"))
    series = _open(tmp_path, "first.jser")
    series.editors = {"zoe", "adam", "mia"}
    series.object_groups.groups["grp"] = {"star", "square", "triangle"}
    series.obj_attrs["star"] = {"comment": "a comment, with: punctuation"}
    section = series.loadSection(sorted(series.sections)[0])
    for name in sorted(section.contours):
        if not section.contours[name].isEmpty():
            section.contours[name][0].tags = {"zzz", "aaa", "mmm"}
    section.save()
    series.saveJser()
    series.close()

    with open(str(tmp_path / "first.jser"), "rb") as f:
        first = json.loads(f.read())

    # the digest must have looked at a real series, or nothing below is proven
    rows = [t for sd in first["sections"] if sd
            for traces in sd.get("contours", {}).values() for t in traces]
    assert sum(1 for sd in first["sections"] if sd is not None) == 5
    assert len(rows) == 20
    assert sum(len(r[0]) + len(r[1]) for r in rows) > 1000     # coordinates
    assert sum(len(r[7]) for r in rows) == 12                  # tags
    assert {len(r) for r in rows} == {8}                       # x,y,colour,3,fill,tags
    assert all(len(r[2]) == 3 and len(r[6]) == 2 for r in rows)  # colour, fill mode
    assert len(first["series"]["editors"]) == 3
    assert first["series"]["object_groups"]["grp"]
    assert first["series"]["obj_attrs"]["star"]
    assert first["series"]["ztraces"]
    assert all(sd["tforms"] for sd in first["sections"] if sd)

    # now the round trip that must change nothing
    shutil.copyfile(str(tmp_path / "first.jser"), str(tmp_path / "second.jser"))
    series2 = _open(tmp_path, "second.jser")
    series2.saveJser()
    series2.close()

    with open(str(tmp_path / "second.jser"), "rb") as f:
        second = json.loads(f.read())

    assert _content(second) == _content(first)
