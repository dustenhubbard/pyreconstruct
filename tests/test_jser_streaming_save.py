"""The .jser is written one section at a time, and the bytes have not changed.

``Series.saveJser`` used to read every section's working file into one document,
turn the whole document into one block of bytes with ``dumps_jser``, and only
then write it. It now streams the document through ``write_jser`` (fork #437).

These tests hold the promise that made the change safe to take: the file is
byte for byte what the old path wrote. ``old_path_bytes`` below is the old
assembly, kept here as the reference, and ``dumps_jser`` is still the encoder it
calls. The comparison runs on every checked-in series fixture, in both the
minified and the pretty form, and on synthetic documents that hit the places
where streaming could drift: gaps in the numbering, non-ASCII text, non-string
keys, and a value orjson refuses, which sends the whole document through the
stdlib with different separators.

The other half is atomicity: a section that cannot be read partway through the
stream fails the save, removes the temp file, and leaves the old .jser as it was.
"""

import filecmp
import io
import os
import shutil

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.constants import (
    canon_keys_inplace,
    dumps_jser,
    fast_loads,
    write_jser,
    SERIES_KEYS,
)
from PyReconstruct.modules.constants import fast_json
from PyReconstruct.modules.constants.jser_format import PRETTY_ENV_VAR
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.series import SeriesSaveError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(ROOT, "dev", "assets", "checker", "files")
FIXTURES = [
    os.path.join(CHECKER, "class_series.jser"),
    os.path.join(CHECKER, "shapes1.jser"),
    os.path.join(CHECKER, "shapes2.jser"),
    os.path.join(ROOT, "tests", "fixtures", "parity_series.jser"),
]


def reopen_at(fp):
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    return series


def open_copy(tmp_path, source):
    if not os.path.exists(source):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {source}")
    fp = str(tmp_path / os.path.basename(source))
    shutil.copyfile(source, fp)
    return reopen_at(fp)


def old_path_bytes(series):
    """What ``saveJser`` wrote before #437: the whole document, then dumps_jser."""
    snums = sorted(series.sections)
    jser_data = {
        "sections": [None] * (snums[-1] + 1),
        "series": {},
        "log": "",
    }
    for snum in snums:
        fp = os.path.join(series.hidden_dir, series.sections[snum])
        with open(fp, "rb") as f:
            jser_data["sections"][snum] = fast_loads(f.read())
    with open(series.filepath, "rb") as f:
        filedata = fast_loads(f.read())
    filedata.pop("log_set", None)
    log_set_str = str(series.log_set)
    if log_set_str:
        jser_data["log"] += "\n" + log_set_str
    jser_data["series"] = filedata
    existing_log_fp = os.path.join(series.hidden_dir, "existing_log.csv")
    if os.path.isfile(existing_log_fp):
        with open(existing_log_fp, "r", encoding="utf-8", errors="replace") as f:
            existing_log = "".join(line for line in f.readlines() if line.strip())
        jser_data["log"] = existing_log + jser_data["log"]
    canon_keys_inplace(jser_data["series"], SERIES_KEYS)
    return dumps_jser(jser_data)


def streamed(doc, pretty=None):
    """``write_jser`` into memory, from a document already built."""
    buf = io.BytesIO()
    rest = {k: v for k, v in doc.items() if k != "sections"}
    write_jser(buf, lambda: iter(doc["sections"]), lambda: rest, pretty=pretty)
    return buf.getvalue()


@pytest.fixture(params=[False, True], ids=["orjson", "stdlib-only"])
def orjson_state(request):
    saved = fast_json._HAVE_ORJSON
    fast_json._HAVE_ORJSON = saved and not request.param
    yield
    fast_json._HAVE_ORJSON = saved


# --------------------------------------------------------------------------
# the real save, on every fixture
# --------------------------------------------------------------------------

@pytest.mark.parametrize("pretty", ["", "1"], ids=["minified", "pretty"])
@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_the_streamed_save_matches_the_old_path(tmp_path, monkeypatch, source, pretty):
    monkeypatch.setenv(PRETTY_ENV_VAR, pretty)
    series = open_copy(tmp_path, source)
    try:
        # the session log carries an entry, so the "log" member is not empty
        series.addLog(None, None, "Streaming save test")
        series.save()
        reference = tmp_path / "reference.jser"
        reference.write_bytes(old_path_bytes(series))

        series.saveJser()

        assert filecmp.cmp(series.jser_fp, reference, shallow=False)
        assert not os.path.exists(series.jser_fp + ".tmp")
    finally:
        series.close()


def test_two_streamed_saves_are_byte_identical(tmp_path):
    series = open_copy(tmp_path, FIXTURES[0])
    try:
        series.saveJser()
        first = open(series.jser_fp, "rb").read()
        series.saveJser()
        assert open(series.jser_fp, "rb").read() == first
    finally:
        series.close()


# --------------------------------------------------------------------------
# write_jser against dumps_jser, on the documents streaming could get wrong
# --------------------------------------------------------------------------

def _doc(**extra_series):
    series = {"current_section": 1, "src_dir": "", "editors": ["b", "a"]}
    series.update(extra_series)
    return {
        "sections": [
            None,
            {"src": "a.tif", "mag": 0.00254, "contours": {"d01": [[[1.5], [2.5], [0, 0, 0], True, False, False, "none", []]]}},
            None,
            {"src": "c.tif", "contours": {}, "flags": [], "tforms": {"default": [1, 0, 0, 0, 1, 0]}},
        ],
        "series": series,
        "log": "Date,Time\n2026-10-03,12:00",
    }


@pytest.mark.parametrize("pretty", [False, True], ids=["minified", "pretty"])
@pytest.mark.parametrize("doc", [
    _doc(),
    _doc(comment="café \U0001F600 中"),
    _doc(obj_attrs={1: "int key", "x": {2.5: "float key"}}),
    # past 64 bits: orjson raises, so the whole document goes to the stdlib
    _doc(huge=2 ** 70),
    {"sections": [], "series": {}, "log": ""},
    {"sections": [None], "series": {}, "log": "", "extra": [1, 2]},
], ids=["plain", "non-ascii", "non-str-keys", "orjson-refuses", "empty", "extra-member"])
def test_write_jser_matches_dumps_jser(doc, pretty, orjson_state):
    assert streamed(doc, pretty) == dumps_jser(doc, pretty)


def test_a_value_orjson_refuses_late_rewrites_every_part_with_stdlib_separators():
    """The fallback decides for the whole file, so earlier parts must change too."""
    doc = _doc()
    doc["sections"].append({"src": "big", "mag": 2 ** 70})
    out = streamed(doc, False)
    assert out == dumps_jser(doc, False)
    assert out.startswith(b'{"sections": [null, {"src": "a.tif", ')


def test_a_section_nested_to_orjson_limit_matches():
    """orjson's nesting limit counts the levels a section sits under."""
    deep = []
    node = deep
    for _ in range(252):
        child = []
        node.append(child)
        node = child
    doc = {"sections": [{"src": "x", "deep": deep}], "series": {}, "log": ""}
    assert streamed(doc, False) == dumps_jser(doc, False)


# --------------------------------------------------------------------------
# a save that fails partway leaves the old file alone
# --------------------------------------------------------------------------

def test_an_unreadable_last_section_fails_the_save_and_keeps_the_old_file(tmp_path):
    """The earlier sections are already in the temp file when this one fails."""
    series = open_copy(tmp_path, FIXTURES[0])
    try:
        series.saveJser()
        good = open(series.jser_fp, "rb").read()

        last = max(series.sections)
        with open(os.path.join(series.hidden_dir, series.sections[last]), "wb") as f:
            f.write(b"{not json")

        with pytest.raises(SeriesSaveError):
            series.saveJser()

        assert open(series.jser_fp, "rb").read() == good
        assert not os.path.exists(series.jser_fp + ".tmp")
    finally:
        series.close()


def test_a_section_file_gone_mid_save_fails_the_save_and_keeps_the_old_file(
        tmp_path, monkeypatch):
    """Deleted after the pre-flight check passed, while the stream is running."""
    series = open_copy(tmp_path, FIXTURES[0])
    try:
        series.saveJser()
        good = open(series.jser_fp, "rb").read()

        snums = sorted(series.sections)
        doomed = os.path.join(series.hidden_dir, series.sections[snums[len(snums) // 2]])
        first = os.path.join(series.hidden_dir, series.sections[snums[0]])
        real_open = open

        def open_and_delete(fp, *args, **kwargs):
            if fp == first and os.path.exists(doomed):
                os.remove(doomed)
            return real_open(fp, *args, **kwargs)

        monkeypatch.setattr("builtins.open", open_and_delete)
        with pytest.raises(SeriesSaveError):
            series.saveJser()
        monkeypatch.undo()

        assert open(series.jser_fp, "rb").read() == good
        assert not os.path.exists(series.jser_fp + ".tmp")
    finally:
        series.leave_open = False
        series.close()
