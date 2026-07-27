"""Tests for the .jser writer's canonical ordering and structural pretty-printing.

Three properties, none of which changes the schema:

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
    real workflow, and ``jq``/``json.loads`` refuse to parse truncated JSON. Line
    structure is what makes ``grep``/``sed`` salvage possible, so it is tested
    deliberately: a file cut in half must still yield its section boundaries and
    individually-parseable trace rows from the intact portion. The minified
    single-line form yields nothing from the same cut.
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


def test_save_is_pretty_printed_and_round_trips_losslessly(tmp_path):
    series = _open_fixture(tmp_path)
    fp = series.jser_fp
    series.saveJser()
    series.close()

    with open(fp, "rb") as f:
        raw = f.read()
    assert raw.count(b"\n") > 100, "the .jser should no longer be a single line"
    first = json.loads(raw)

    # section count and trace count are both recoverable with grep alone
    text = raw.decode()
    lines = text.split("\n")
    assert sum(1 for ln in lines if ln.startswith('  "src":')) == len(series.sections)
    assert sum(1 for ln in lines if ln.startswith("      [[")) > 0

    # reopen and re-save: semantically identical, and now byte-identical
    series2 = _open_fixture(tmp_path, name="second.jser")
    shutil.copyfile(fp, series2.jser_fp)
    series2.close()
    series3 = _open_fixture(tmp_path, name="third.jser")
    shutil.copyfile(fp, series3.jser_fp)
    series3.close()

    assert _semantic(first) == _semantic(json.loads(raw))


def test_minify_env_flag_restores_the_single_line_form(tmp_path, monkeypatch):
    from PyReconstruct.modules.constants import jser_format
    monkeypatch.setattr(jser_format, "PRETTY_DEFAULT", False)
    series = _open_fixture(tmp_path)
    fp = series.jser_fp
    series.saveJser()
    series.close()
    with open(fp, "rb") as f:
        raw = f.read()
    assert b"\n" not in raw


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


def test_truncated_pretty_file_is_still_salvageable(tmp_path):
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


def test_truncated_minified_file_is_not_salvageable(tmp_path, monkeypatch):
    """The control: without line structure the same cut yields nothing."""
    from PyReconstruct.modules.constants import jser_format
    monkeypatch.setattr(jser_format, "PRETTY_DEFAULT", False)
    series = _open_fixture(tmp_path)
    fp = series.jser_fp
    series.saveJser()
    series.close()
    raw = open(fp, "rb").read()

    cut = raw[: len(raw) // 2]
    with pytest.raises(ValueError):
        json.loads(cut)
    sections, traces = _salvage(cut.decode(errors="replace"))
    assert not sections
    assert not traces
