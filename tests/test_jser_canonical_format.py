"""Tests for the .jser writer's canonical ordering and its opt-in pretty printer.

The writer's normative output is **minified with canonical ordering**. Pretty
printing is available behind ``PYRECON_JSER_PRETTY=1`` and is off by default,
because ordering is free while the whitespace costs about 11% of save time and
about 27% more transient memory in the save path.

Four properties, none of which changes the schema:

  * **Canonical ordering.** The five structures that are Python sets in memory
    and JSON arrays on disk (trace ``tags``, series ``editors``, the member lists
    of ``object_groups`` and ``ztrace_groups``, and the host lists of
    ``host_tree``) are sorted, and object key order is fixed. Before this, a save
    that re-serialized a section emitted set-iteration order, so identical
    content produced different bytes -- byte reproducibility failed after any
    real edit.

  * **Byte reproducibility across processes.** Verified the only way it can be:
    two *separate interpreters*, with different hash seeds, perform the same
    open -> tag edit -> save, and the resulting files are byte-compared.

  * **Truncated-file salvage.** Recovery by reading a damaged .jser directly is a
    real workflow, and ``jq``/``json.loads`` refuse to parse truncated JSON. A
    pretty file cut in half must still yield its section boundaries and
    individually-parseable trace rows from the intact portion via *line-anchored*
    patterns. Tested alongside the honest control: the same cut on the minified
    form yields nothing to a line-anchored method and the *same* rows to a
    non-anchored one, so line structure buys convenience, not recoverability.

  * **The output form is selectable, honestly.** ``PYRECON_JSER_PRETTY`` is read
    on every write rather than once at import, and the tests set the real
    variable -- including in a fresh subprocess -- instead of monkeypatching a
    module global, so the variable's name is itself under test.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from PyReconstruct.modules.constants.jser_format import (
    canon_keys,
    canon_keys_inplace,
    dumps_jser,
    SECTION_KEYS,
    SERIES_KEYS,
)
from PyReconstruct.modules.constants.fast_json import fast_dumps


FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "PyReconstruct", "assets",
    "checker", "files", "shapes1.jser",
)


# --------------------------------------------------------------------------
# canonical ordering -- unit level
# --------------------------------------------------------------------------

def test_canon_keys_orders_known_keys_and_preserves_unknown():
    """Known keys take the canonical order; unknown ones survive, sorted, after."""
    d = {"zzz_extra": 1, "calgrid": False, "src": "a.tif", "aaa_extra": 2,
         "mag": 0.5}
    out = canon_keys(d, SECTION_KEYS)
    assert list(out) == ["src", "mag", "calgrid", "aaa_extra", "zzz_extra"]
    assert out == d  # nothing added, nothing dropped


def test_canon_keys_preserves_the_legacy_brightness_contrast_pair():
    """A real section carries 11 keys where the documented shape has 9.

    The legacy scalar ``brightness``/``contrast`` pair survives on any section
    that has only ever been shuttled opaquely. Canonicalizing must not drop it.
    """
    d = {"contrast": 26, "src": "a.tif", "brightness": -2}
    out = canon_keys(d, SECTION_KEYS)
    assert list(out) == ["src", "brightness", "contrast"]
    assert out["brightness"] == -2 and out["contrast"] == 26


def test_canon_keys_inplace_keeps_the_dict_identity():
    d = {"calgrid": False, "src": "a.tif"}
    before = id(d)
    canon_keys_inplace(d, SECTION_KEYS)
    assert id(d) == before
    assert list(d) == ["src", "calgrid"]


def test_trace_tags_are_sorted_on_write():
    from PyReconstruct.modules.datatypes.trace import Trace
    t = Trace("obj", (0, 0, 0))
    t.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    t.tags = {"was named rb", "but it is a very long PR",
              "that extends from shaft through the neck"}
    tags = t.getList(include_name=False)[-1]
    assert tags == sorted(tags)
    assert set(tags) == t.tags


def test_object_groups_are_sorted_on_write():
    from PyReconstruct.modules.datatypes.obj_group_dict import ObjGroupDict
    g = ObjGroupDict(None, "objects", {"zg": ["d02", "d01"], "ag": ["b", "a"]})
    d = g.getGroupDict()
    assert list(d) == ["ag", "zg"]
    assert d["zg"] == ["d01", "d02"]
    assert d["ag"] == ["a", "b"]


def test_host_tree_hosts_are_sorted_on_write():
    from PyReconstruct.modules.datatypes.host_tree import HostTree
    tree = HostTree({"zzz": ["h2", "h1"], "aaa": ["h3"]}, None)
    d = tree.getDict()
    assert list(d) == ["aaa", "zzz"]
    assert d["zzz"] == ["h1", "h2"]


def test_editors_are_sorted_on_write(tmp_path):
    series = _open_fixture(tmp_path)
    series.editors = {"zoe", "adam", "mia"}
    assert series.getDict()["editors"] == ["adam", "mia", "zoe"]


# --------------------------------------------------------------------------
# canonical ordering -- through the real migration
# --------------------------------------------------------------------------

def test_section_updatejson_emits_the_writer_key_order():
    """The back-fill loop appends missing keys at the tail; canon fixes that."""
    from PyReconstruct.modules.datatypes.section import Section
    # a section missing thickness and tforms: before canonicalization those two
    # came out *after* calgrid
    sd = {
        "src": "a.tif",
        "brightness_contrast_profiles": {"default": [0, 0]},
        "mag": 0.00254,
        "align_locked": True,
        "contours": {},
        "flags": [],
        "calgrid": False,
        "brightness": -2,
        "contrast": 26,
    }
    Section.updateJSON(sd, 0)
    known = [k for k in sd if k in SECTION_KEYS]
    assert known == list(SECTION_KEYS)
    # the unknown legacy pair is preserved, after the documented nine
    assert list(sd)[len(SECTION_KEYS):] == ["brightness", "contrast"]


def test_section_updatejson_sorts_contour_names():
    from PyReconstruct.modules.datatypes.section import Section
    row = [[0.0, 1.0, 1.0], [0.0, 0.0, 1.0], [0, 0, 0], True, False, False,
           ["none", "none"], []]
    sd = Section.getEmptyDict()
    sd["contours"] = {"zzz": [list(row)], "aaa": [list(row)], "mmm": [list(row)]}
    Section.updateJSON(sd, 0)
    assert list(sd["contours"]) == ["aaa", "mmm", "zzz"]


def test_series_updatejson_emits_the_writer_key_order():
    from PyReconstruct.modules.datatypes.series import Series
    sd = Series.getEmptyDict()
    # drop a key so the back-fill appends it at the tail, then canonicalize
    del sd["window"]
    Series.updateJSON(sd)
    known = [k for k in sd if k in SERIES_KEYS]
    assert known == [k for k in SERIES_KEYS if k in sd]
    assert known.index("window") == 2


def test_series_updatejson_canonicalises_the_options_bag():
    from PyReconstruct.modules.datatypes.series import Series
    template = list(Series.getEmptyDict()["options"])
    sd = Series.getEmptyDict()
    # reverse the bag and drop one key: back-fill would append it at the tail
    reversed_opts = {k: sd["options"][k] for k in reversed(template)}
    del reversed_opts[template[0]]
    sd["options"] = reversed_opts
    Series.updateJSON(sd)
    assert list(sd["options"]) == template


# --------------------------------------------------------------------------
# structural pretty-printing
# --------------------------------------------------------------------------

def _doc():
    row = [[0.0, 1.0, 1.0], [0.0, 0.0, 1.0], [0, 0, 0], True, False, False,
           ["none", "none"], ["a", "b"]]
    section = {
        "src": "a.tif",
        "brightness_contrast_profiles": {"default": [0, 0]},
        "mag": 0.00254,
        "align_locked": True,
        "tforms": {"default": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]},
        "thickness": 0.05,
        "contours": {"d01": [list(row), list(row)], "d02": [list(row)]},
        "flags": [["abc", "f1", 1.0, 2.0, [255, 0, 0], [], False]],
        "calgrid": False,
    }
    series = {
        "current_section": 0,
        "src_dir": "",
        "window": [0, 0, 1, 1],
        "palette_traces": {"palette1": [["p"] + list(row)]},
        "palette_index": ["palette1", 0],
        "ztraces": {"z1": {"color": [255, 255, 0], "points": [[0.0, 0.0, 0]]}},
        "alignment": "default",
        "object_groups": {"g": ["d01"]},
        "ztrace_groups": {},
        "obj_attrs": {"d01": {"comment": "hi"}},
        "ztrace_attrs": {},
        "current_brightness_contrast_profile": "default",
        "options": {"small_dist": 0.01},
        "log_set": [],
        "editors": ["a"],
        "code": "",
        "user_columns": {},
        "host_tree": {"d02": ["d01"]},
    }
    return {"sections": [None, section], "series": series,
            "log": "Date, Time, User, Obj, Sections, Event"}


def test_pretty_output_parses_to_the_same_document():
    doc = _doc()
    assert json.loads(dumps_jser(doc, pretty=True)) == json.loads(fast_dumps(doc))


def test_minified_output_is_byte_identical_to_the_old_writer():
    """The flag really is a whitespace switch, not a second serializer."""
    doc = _doc()
    assert dumps_jser(doc, pretty=False) == fast_dumps(doc)


def test_pretty_output_is_pure_ascii_with_no_trailing_newline():
    raw = dumps_jser(_doc(), pretty=True)
    assert raw.isascii()
    assert not raw.endswith(b"\n")


def test_pretty_line_structure_is_greppable():
    lines = dumps_jser(_doc(), pretty=True).decode().split("\n")

    # section boundaries: one "  \"src\":" line per live section
    assert sum(1 for ln in lines if ln.startswith('  "src":')) == 1
    # a null section stays on its own line
    assert "null," in lines

    # one trace per line, at a fixed indent, each independently parseable
    trace_lines = [ln for ln in lines if ln.startswith("      [[")]
    assert len(trace_lines) == 3
    for ln in trace_lines:
        assert json.loads(ln.strip().rstrip(","))

    # the enclosing object name is on its own line, so it shows up as diff context
    assert '    "d01": [' in lines
    assert '    "d02": [' in lines

    # coordinates never get a line of their own
    assert not any(ln.strip().replace(",", "").replace(".", "").isdigit()
                   for ln in lines if ln.startswith("        "))


def test_pretty_writer_preserves_unknown_top_level_keys():
    doc = _doc()
    doc["hand_added"] = {"k": 1}
    assert json.loads(dumps_jser(doc, pretty=True))["hand_added"] == {"k": 1}


@pytest.mark.parametrize("keep", [(), ("series",), ("log",), ("series", "log")])
@pytest.mark.parametrize("extras", [False, True])
def test_pretty_writer_invents_no_top_level_key(keep, extras):
    """The two writers must agree on the *key set*, not just the values.

    The pretty printer used to emit ``"series"`` and ``"log"`` unconditionally,
    defaulting them to ``{}`` and ``""``. On a document lacking either, that added
    a key the compact writer does not write -- so the two forms parsed to
    different documents, contradicting the module's own guarantee. Unreachable
    through ``saveJser``, which always populates all three, but reachable for
    anything assembling a document by hand.
    """
    full = _doc()
    doc = {"sections": full["sections"]}
    for k in keep:
        doc[k] = full.get(k, {} if k == "series" else "")
    if extras:
        doc["hand_added"] = {"k": 1}
        doc["aaa_first"] = [1, 2]

    pretty = dumps_jser(doc, pretty=True)
    compact = dumps_jser(doc, pretty=False)
    assert json.loads(pretty) == json.loads(compact)
    # stated separately so a key-set difference names itself in the failure
    assert set(json.loads(pretty)) == set(doc), "the pretty writer changed the key set"
    assert set(json.loads(compact)) == set(doc)


def test_pretty_handles_empty_containers():
    doc = _doc()
    doc["sections"][1]["contours"] = {}
    doc["sections"][1]["flags"] = []
    doc["sections"][1]["tforms"] = {}
    doc["series"]["ztraces"] = {}
    doc["series"]["palette_traces"] = {}
    assert json.loads(dumps_jser(doc, pretty=True)) == json.loads(fast_dumps(doc))


# --------------------------------------------------------------------------
# end to end: a real fixture through open and save
# --------------------------------------------------------------------------

def _open_fixture(tmp_path, name="shapes1.jser"):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / name)
    shutil.copyfile(FIXTURE, fp)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    return series


def _semantic(doc):
    """A provenance-free digest: every set-derived array normalized to sorted."""
    def trace(r):
        r = list(r)
        r[-1] = sorted(r[-1])
        return r

    sections = []
    for sd in doc["sections"]:
        if sd is None:
            sections.append(None)
            continue
        sd = dict(sd)
        sd["contours"] = {k: [trace(r) for r in v]
                          for k, v in sd.get("contours", {}).items()}
        sections.append(sd)
    series = dict(doc["series"])
    if "editors" in series:
        series["editors"] = sorted(series["editors"])
    for gk in ("object_groups", "ztrace_groups", "host_tree"):
        if isinstance(series.get(gk), dict):
            series[gk] = {k: sorted(v) for k, v in series[gk].items()}
    if isinstance(series.get("palette_traces"), dict):
        series["palette_traces"] = {k: [trace(r) for r in v]
                                    for k, v in series["palette_traces"].items()}
    return json.dumps({"sections": sections, "series": series,
                       "log": doc.get("log", "")}, sort_keys=True)


def _rich_source(tmp_path, name="rich.jser"):
    """The fixture with content the round trip is supposed to preserve.

    ``shapes1.jser`` has an empty log, no flags, no tags, no groups and no hosts,
    so a save that silently discarded any of them round-trips perfectly. Nothing
    can be shown to survive a round trip unless it is there to begin with.
    """
    doc = json.loads(open(FIXTURE, "rb").read())
    doc["log"] = ("Date, Time, User, Obj, Sections, Event\n"
                  "2026-07-27, 10:00:00, alice, d01, 1, created trace\n"
                  "2026-07-27, 10:00:01, bob, d02, 2, modified trace\n")
    for i, sd in enumerate(doc["sections"]):
        if not sd:
            continue
        # a 7-field flag is already fully migrated, so updateJSON leaves it alone
        sd["flags"] = [["flag%d" % i, "check this", 1.5, 2.5, [255, 0, 0],
                        [["alice", "2026-07-27", "have a look"]], False]]
        for rows in sd["contours"].values():
            for row in rows:
                row[7] = ["zzz_tag", "mmm_tag", "aaa_tag"]
    ser = doc["series"]
    ser["editors"] = ["zoe", "adam", "mia"]
    ser["object_groups"] = {"zg": ["square", "star"], "ag": ["triangle"]}
    ser["ztrace_groups"] = {"zt": ["square"]}
    # no transitive edge: HostTree deliberately prunes a host that is already
    # reachable through another host, and that pruning is not a round-trip loss
    ser["host_tree"] = {"star": ["square"], "triangle": ["star"]}
    ser["obj_attrs"] = {"square": {"comment": "a comment", "curation": ["", "", ""]}}
    ser["user_columns"] = {"MyColumn": ["yes", "no"]}
    fp = str(tmp_path / name)
    with open(fp, "wb") as f:
        f.write(json.dumps(doc).encode())
    return fp, doc


def _bc(sd):
    """Brightness/contrast normalized across the legacy migration.

    A pre-profiles section carries the scalar pair; the migration folds it into
    ``brightness_contrast_profiles``, so the two shapes must compare equal.
    """
    bc = sd.get("brightness_contrast_profiles")
    if bc is None:
        bc = {"default": [sd.get("brightness", 0), int(sd.get("contrast", 0))]}
    return {k: list(v) for k, v in bc.items()}


def _content(doc):
    """Everything a save must preserve, normalized for what a save may legally change.

    A save is allowed to: lock sections (``align_locked``), drop a trace row's
    trailing history field, sort tags, sort contour names, and reorder keys.
    It is not allowed to lose anything.
    """
    out = {"log": doc.get("log", ""), "sections": {}}
    for i, sd in enumerate(doc["sections"]):
        if not sd:
            continue
        out["sections"][i] = {
            "src": sd["src"], "mag": sd["mag"], "thickness": sd["thickness"],
            "tforms": sd["tforms"], "calgrid": sd["calgrid"],
            "bc": _bc(sd),
            "flags": sd.get("flags", []),
            "contours": {name: sorted([list(r[:7]) + [sorted(r[7])] for r in rows])
                         for name, rows in sd["contours"].items()},
        }
    ser = doc["series"]
    out["series"] = {
        k: ser.get(k) for k in
        ("current_section", "window", "alignment", "obj_attrs", "user_columns")
    }
    out["series"]["editors"] = sorted(ser.get("editors", []))
    for gk in ("object_groups", "ztrace_groups", "host_tree"):
        out["series"][gk] = {k: sorted(v) for k, v in (ser.get(gk) or {}).items()}
    out["series"]["ztraces"] = ser.get("ztraces")
    return out


def _assert_actually_rich(doc):
    """Guard the round trip against going vacuous again.

    Comparing ``_content(saved) == _content(source)`` only proves something if the
    source has content. If a future fixture change left any of these empty, the
    comparison would quietly succeed while proving nothing about that field --
    which is the exact defect this test was rewritten to remove. So assert the
    inputs are non-empty before asserting they survive.
    """
    c = _content(doc)
    assert c["log"].strip(), "source log is empty: losslessness of the log is untested"
    assert c["sections"], "source has no sections"
    ser = c["series"]
    for key in ("editors", "object_groups", "ztrace_groups", "host_tree",
                "obj_attrs", "user_columns"):
        assert ser.get(key), f"source {key} is empty: its preservation is untested"
    n_flags = sum(len(s["flags"]) for s in c["sections"].values())
    n_traces = sum(len(rows) for s in c["sections"].values()
                   for rows in s["contours"].values())
    n_tagged = sum(1 for s in c["sections"].values()
                   for rows in s["contours"].values() for r in rows if r[7])
    assert n_flags, "source has no flag rows"
    assert n_traces, "source has no traces"
    assert n_tagged == n_traces, f"only {n_tagged}/{n_traces} traces carry tags"


@pytest.mark.parametrize("form", ["minified", "pretty"])
def test_save_round_trips_losslessly(tmp_path, monkeypatch, form):
    """Losslessness must hold in the form users actually get, and in the other one.

    Parametrized deliberately: minified is the default and therefore the form
    that matters, but pretty stays available and a divergence between them would
    be a data bug, not a formatting one.
    """
    if form == "pretty":
        monkeypatch.setenv("PYRECON_JSER_PRETTY", "1")
    else:
        monkeypatch.delenv("PYRECON_JSER_PRETTY", raising=False)

    src_fp, src_doc = _rich_source(tmp_path)
    # the comparison below is only meaningful if there is something to lose
    _assert_actually_rich(src_doc)

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(src_fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    n_sections = len(series.sections)
    series.saveJser()
    series.close()

    with open(src_fp, "rb") as f:
        raw = f.read()
    first = json.loads(raw)

    if form == "pretty":
        assert raw.count(b"\n") > 100, "pretty output should be line-structured"
        # section count and trace count are both recoverable with grep alone
        lines = raw.decode().split("\n")
        assert sum(1 for ln in lines if ln.startswith('  "src":')) == n_sections
        assert sum(1 for ln in lines if ln.startswith("      [[")) > 0
    else:
        assert b"\n" not in raw, "the default output should be a single line"

    # NOTHING WAS LOST. Compared against the SOURCE, not against another output
    # of the same writer: a writer that consistently discards the log or every
    # flag agrees with itself on every subsequent save.
    assert _content(first) == _content(src_doc)
    assert first["log"] == src_doc["log"]
    for i, sd in enumerate(first["sections"]):
        if sd is None:
            continue
        assert sd["flags"] == src_doc["sections"][i]["flags"], f"flags lost on {i}"

    # and the round trip is a fixed point: reopening and re-saving what this
    # build wrote reproduces it byte for byte
    second_fp = str(tmp_path / "second.jser")
    shutil.copyfile(src_fp, second_fp)
    shutil.rmtree(str(tmp_path / ".second"), ignore_errors=True)
    series2 = Series.openJser(second_fp, progress=NullProgressReporter)
    series2.setProgressReporter(NullProgressReporter)
    series2.saveJser()
    series2.close()
    with open(second_fp, "rb") as f:
        raw2 = f.read()
    assert _content(json.loads(raw2)) == _content(first)
    assert raw == raw2, "a second save of unchanged content changed the bytes"


def test_pretty_env_var_is_read_at_call_time_not_import_time(monkeypatch):
    """The opt-in must be togglable in a running process.

    The previous flag was evaluated once at import, so it could not be changed
    after start-up -- and the test that claimed to cover it monkeypatched the
    module global instead, which meant the variable *name* was never exercised
    and a typo in it would have gone unnoticed. This sets the real variable,
    after import, and requires the very next call to honour it.
    """
    from PyReconstruct.modules.constants import jser_format
    doc = _doc()

    monkeypatch.delenv(jser_format.PRETTY_ENV_VAR, raising=False)
    assert jser_format.pretty_default() is False
    assert b"\n" not in dumps_jser(doc), "minified is the default"

    monkeypatch.setenv("PYRECON_JSER_PRETTY", "1")
    assert jser_format.pretty_default() is True
    assert dumps_jser(doc).count(b"\n") > 5, "the env var did not take effect"

    # and back again, in the same process
    monkeypatch.setenv("PYRECON_JSER_PRETTY", "0")
    assert jser_format.pretty_default() is False
    assert b"\n" not in dumps_jser(doc)

    monkeypatch.delenv("PYRECON_JSER_PRETTY")
    assert b"\n" not in dumps_jser(doc)


def test_pretty_env_var_is_honoured_when_set_before_the_process_starts():
    """The same variable also works the ordinary way: exported, then run.

    Uses a real subprocess rather than monkeypatch so that the environment is
    genuinely inherited at interpreter start-up -- the case a user actually hits.
    """
    prog = (
        "import sys;"
        "sys.path.insert(0, sys.argv[1]);"
        "from PyReconstruct.modules.constants.jser_format import dumps_jser;"
        "d={'sections':[None,{'src':'a.tif','mag':1.0,'thickness':0.05,"
        "'align_locked':True,'tforms':{'default':[1,0,0,0,1,0]},'contours':{},"
        "'flags':[],'calgrid':False}],'series':{},'log':''};"
        "print(dumps_jser(d).count(b'\\n'))"
    )
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def newlines(env_value):
        env = dict(os.environ)
        env.pop("PYRECON_JSER_PRETTY", None)
        if env_value is not None:
            env["PYRECON_JSER_PRETTY"] = env_value
        env["QT_QPA_PLATFORM"] = "offscreen"
        r = subprocess.run([sys.executable, "-c", prog, repo],
                           check=True, capture_output=True, env=env)
        return int(r.stdout.strip())

    assert newlines(None) == 0, "default in a fresh process must be minified"
    assert newlines("1") > 0, "PYRECON_JSER_PRETTY=1 must pretty-print"
    assert newlines("0") == 0


def test_explicit_pretty_argument_overrides_the_environment(monkeypatch):
    doc = _doc()
    monkeypatch.setenv("PYRECON_JSER_PRETTY", "1")
    assert b"\n" not in dumps_jser(doc, pretty=False)
    monkeypatch.delenv("PYRECON_JSER_PRETTY")
    assert dumps_jser(doc, pretty=True).count(b"\n") > 5


def test_default_save_is_minified(tmp_path, monkeypatch):
    """A save with nothing set writes one line."""
    monkeypatch.delenv("PYRECON_JSER_PRETTY", raising=False)
    series = _open_fixture(tmp_path)
    fp = series.jser_fp
    series.saveJser()
    series.close()
    with open(fp, "rb") as f:
        raw = f.read()
    assert b"\n" not in raw
    json.loads(raw)          # still a valid document


def test_pretty_env_var_opts_a_save_into_line_structure(tmp_path, monkeypatch):
    """The opt-in reaches saveJser, not just dumps_jser."""
    monkeypatch.setenv("PYRECON_JSER_PRETTY", "1")
    series = _open_fixture(tmp_path)
    fp = series.jser_fp
    series.saveJser()
    series.close()
    with open(fp, "rb") as f:
        raw = f.read()
    assert raw.count(b"\n") > 100
    lines = raw.decode().split("\n")
    assert sum(1 for ln in lines if ln.startswith('  "src":')) > 0
    json.loads(raw)


def test_pretty_and_minified_saves_carry_the_same_document(tmp_path, monkeypatch):
    """Whitespace only: the two forms must parse to the same document."""
    monkeypatch.delenv("PYRECON_JSER_PRETTY", raising=False)
    s1 = _open_fixture(tmp_path, name="mini.jser")
    f1 = s1.jser_fp
    s1.saveJser()
    s1.close()
    mini = json.loads(open(f1, "rb").read())

    monkeypatch.setenv("PYRECON_JSER_PRETTY", "1")
    s2 = _open_fixture(tmp_path, name="pretty.jser")
    f2 = s2.jser_fp
    s2.saveJser()
    s2.close()
    prettied = json.loads(open(f2, "rb").read())

    assert _content(mini) == _content(prettied)


# --------------------------------------------------------------------------
# byte reproducibility across separate processes
# --------------------------------------------------------------------------

_DRIVER = r'''
import os, shutil, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.backend.progress import NullProgressReporter

src, dst = sys.argv[1], sys.argv[2]
work = dst + ".work.jser"
shutil.copyfile(src, work)
d, name = os.path.dirname(os.path.abspath(work)), os.path.basename(work)[:-5]
shutil.rmtree(os.path.join(d, "." + name), ignore_errors=True)

series = Series.openJser(work, progress=NullProgressReporter)
series.setProgressReporter(NullProgressReporter)

# an edit that forces a section back through the model AND populates a set:
# three tags, whose set iteration order depends on the interpreter hash seed
for snum in sorted(series.sections):
    section = series.loadSection(snum)
    names = sorted(n for n in section.contours if not section.contours[n].isEmpty())
    if not names:
        continue
    trace = section.contours[names[0]][0]
    trace.tags = {"zzz_edit", "aaa_edit", "mmm_edit"}
    series.editors = {"zoe", "adam", "mia"}
    series.object_groups.groups["grp"] = {"d02", "d01", "d03"}
    section.save()
    break

series.saveJser()
series.close()
shutil.move(work, dst)
shutil.rmtree(os.path.join(d, "." + name), ignore_errors=True)
'''


def _run_save(tmp_path, out_name, seed):
    driver = tmp_path / "driver.py"
    driver.write_text(_DRIVER)
    src = tmp_path / "src.jser"
    if not src.exists():
        shutil.copyfile(FIXTURE, src)
    out = tmp_path / out_name
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    env["QT_QPA_PLATFORM"] = "offscreen"
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env["PYTHONPATH"] = repo + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(
        [sys.executable, str(driver), str(src), str(out)],
        check=True, env=env, cwd=str(tmp_path),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    return out


def test_noop_save_byte_reproducible_across_processes(tmp_path):
    """The point of canonical ordering: two processes, one byte sequence.

    Run twice with *different* hash seeds so set iteration order genuinely
    differs -- this failed before canonical ordering, by ~150 bytes of trace-tag
    reordering on a real series.
    """
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    a = _run_save(tmp_path, "a.jser", seed=1)
    b = _run_save(tmp_path, "b.jser", seed=2)
    ra, rb = a.read_bytes(), b.read_bytes()
    assert len(ra) == len(rb)
    assert ra == rb, "two saves of identical content produced different bytes"

    # and a third run with the same seed as the first, to catch any
    # within-seed nondeterminism
    c = _run_save(tmp_path, "c.jser", seed=1)
    assert c.read_bytes() == ra


# --------------------------------------------------------------------------
# truncated-file salvage
# --------------------------------------------------------------------------

def _salvage(text):
    """What a person with only coreutils can recover from a damaged file."""
    lines = text.split("\n")
    sections = [i for i, ln in enumerate(lines) if ln.startswith('  "src":')]
    traces = []
    for ln in lines:
        if ln.startswith("      [["):
            try:
                traces.append(json.loads(ln.strip().rstrip(",")))
            except ValueError:
                pass  # the line the truncation landed in the middle of
    return sections, traces


def test_truncated_pretty_file_is_still_salvageable(tmp_path, monkeypatch):
    monkeypatch.setenv("PYRECON_JSER_PRETTY", "1")
    series = _open_fixture(tmp_path)
    fp = series.jser_fp
    series.saveJser()
    series.close()
    raw = open(fp, "rb").read()

    intact_sections, intact_traces = _salvage(raw.decode())
    assert intact_sections and intact_traces

    for fraction in (0.25, 0.5, 0.75):
        cut = raw[: int(len(raw) * fraction)]

        # no JSON parser will touch it -- this is the premise of the whole test
        with pytest.raises(ValueError):
            json.loads(cut)

        sections, traces = _salvage(cut.decode(errors="replace"))
        assert sections, f"no section boundary recoverable at {fraction:.0%}"
        assert traces, f"no trace row recoverable at {fraction:.0%}"
        # everything recovered is real: a prefix of the undamaged file's content
        assert len(sections) <= len(intact_sections)
        assert traces == intact_traces[: len(traces)]
        # and each recovered trace is a well-formed positional row
        for row in traces:
            assert len(row) in (8, 9)
            assert len(row[0]) == len(row[1])  # x and y agree


def _scan_trace_rows(text):
    """Recover complete positional trace rows *without* relying on line structure.

    Walks balanced brackets from each ``[[`` and keeps whatever parses as a trace
    row, which is what someone salvaging a damaged file would actually do. Works
    the same on both output forms, which is the point being demonstrated.
    """
    out, i, n = [], 0, len(text)
    while i < n:
        i = text.find("[[", i)
        if i < 0:
            break
        depth, j, instr, esc = 0, i, False, False
        while j < n:
            c = text[j]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
            elif c == '"':
                instr = True
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= n or depth != 0:
            break                       # ran into the truncation
        try:
            row = json.loads(text[i:j + 1])
        except ValueError:
            row = None
        ok = (isinstance(row, list) and len(row) >= 8
              and isinstance(row[0], list) and isinstance(row[1], list)
              and row[0] and len(row[0]) == len(row[1])
              and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                      for v in row[0]))
        if ok:
            out.append(row)
            i = j + 1
        else:
            i += 1                      # only past this bracket, not past the row
    return out


def test_line_anchored_salvage_finds_nothing_in_a_minified_file(tmp_path, monkeypatch):
    """What line structure actually buys: anchored patterns, not recoverability.

    Named for what it measures. ``_salvage`` is line-anchored, so of course it
    returns nothing from a file with no lines -- that is a property of the
    *method*, not of the format, and reading it as "minified data is lost" was
    the circular step in the original argument for pretty-printing by default.
    The companion test below shows the same cut is in fact recoverable.
    """
    monkeypatch.delenv("PYRECON_JSER_PRETTY", raising=False)
    series = _open_fixture(tmp_path)
    fp = series.jser_fp
    series.saveJser()
    series.close()
    raw = open(fp, "rb").read()
    assert b"\n" not in raw

    cut = raw[: len(raw) // 2]
    with pytest.raises(ValueError):
        json.loads(cut)
    sections, traces = _salvage(cut.decode(errors="replace"))
    assert not sections
    assert not traces


def test_truncated_minified_file_is_still_recoverable_without_line_anchors(
        tmp_path, monkeypatch):
    """The honest control: non-anchored patterns recover the same content.

    This is why pretty-printing is not worth +11% wall time and double the
    save-path memory on every save: the salvage argument for it was measured with
    a line-anchored method against a file with no lines.
    """
    monkeypatch.delenv("PYRECON_JSER_PRETTY", raising=False)
    series = _open_fixture(tmp_path)
    fp = series.jser_fp
    series.saveJser()
    series.close()
    raw = open(fp, "rb").read()

    cut = raw[: len(raw) // 2]
    with pytest.raises(ValueError):
        json.loads(cut)

    text = cut.decode(errors="replace")
    # sections are still countable without an anchor
    assert text.count('"src":') > 0

    rows = _scan_trace_rows(text)
    assert rows, "no trace row recoverable from the minified cut"
    for row in rows:
        assert len(row[0]) == len(row[1])   # x and y agree

    # and it is not a worse result than the pretty form gets from the same cut
    monkeypatch.setenv("PYRECON_JSER_PRETTY", "1")
    s2 = _open_fixture(tmp_path, name="pretty_cut.jser")
    f2 = s2.jser_fp
    s2.saveJser()
    s2.close()
    praw = open(f2, "rb").read()
    prows = _scan_trace_rows(praw[: len(praw) // 2].decode(errors="replace"))
    assert len(rows) == len(prows), (
        f"minified recovered {len(rows)} rows, pretty recovered {len(prows)}")


# --------------------------------------------------------------------------
# regressions found reviewing the writer
# --------------------------------------------------------------------------

@pytest.mark.parametrize("where", ["obj_attrs", "host_tree", "options",
                                   "user_columns", "ztrace_groups"])
def test_pretty_writer_emits_string_keys_like_the_compact_writer(where):
    """A non-string key must not turn the file into non-JSON.

    ``fast_dumps`` passes ``orjson.OPT_NON_STR_KEYS``, so the compact writer
    coerces ``1`` to ``"1"``. Dumping a key on its own does not, and the writer
    used to emit ``  1: {...}`` -- a save that succeeds and leaves a file no
    parser will reopen.
    """
    doc = _doc()
    doc["series"][where] = {1: (["a"] if where != "obj_attrs" else {"comment": "x"})}
    pretty = dumps_jser(doc, pretty=True)
    # the whole point: it still parses, and to the same document
    assert json.loads(pretty) == json.loads(dumps_jser(doc, pretty=False))
    assert b"\n  1:" not in pretty and b'\n    1:' not in pretty


def test_pretty_writer_emits_string_contour_and_section_keys():
    doc = _doc()
    doc["sections"][1]["contours"] = {7: [list(_doc()["sections"][1]["contours"]["d01"][0])]}
    doc["sections"][1][3] = "unknown numeric key"
    pretty = dumps_jser(doc, pretty=True)
    assert json.loads(pretty) == json.loads(dumps_jser(doc, pretty=False))


def test_empty_group_is_written_as_an_array_not_a_set():
    """A bare set reaching the writer raises TypeError in orjson AND stdlib."""
    from PyReconstruct.modules.datatypes.obj_group_dict import ObjGroupDict
    g = ObjGroupDict(None, "objects", {"a": ["x"]})
    g.groups["empty"] = set()          # what a direct manipulation leaves behind
    d = g.getGroupDict()
    assert d["empty"] == []
    fast_dumps(d)                      # would raise TypeError on a set


def test_tags_are_sorted_even_when_the_section_is_never_touched(tmp_path):
    """The writer's "tags are sorted" guarantee must not depend on provenance.

    ``Trace.getList`` sorts tags, but it only runs for a section that goes back
    through the model. ``saveJser`` reads the hidden dir verbatim, so a section
    the user never opened used to keep whatever tag order its source file had --
    and two files with identical content then differed by thousands of bytes.
    """
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    descending = ["zzz_tag", "mmm_tag", "aaa_tag"]
    doc = json.loads(open(FIXTURE, "rb").read())
    n = 0
    for sd in doc["sections"]:
        if not sd:
            continue
        for rows in sd["contours"].values():
            for row in rows:
                row[7] = list(descending)
                n += 1
    assert n, "fixture has no traces to tag"

    src = str(tmp_path / "unsorted.jser")
    with open(src, "wb") as f:
        f.write(json.dumps(doc).encode())

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(["test"])
    from PyReconstruct.modules.datatypes.series import Series
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    series = Series.openJser(src, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    series.saveJser()          # NO edit: every section is shuttled opaquely
    series.close()

    out = json.loads(open(src, "rb").read())
    checked = 0
    for sd in out["sections"]:
        if not sd:
            continue
        for rows in sd["contours"].values():
            for row in rows:
                assert row[7] == sorted(row[7]), f"unsorted tags survived: {row[7]}"
                assert set(row[7]) == set(descending), "tags were altered, not reordered"
                checked += 1
    assert checked == n
