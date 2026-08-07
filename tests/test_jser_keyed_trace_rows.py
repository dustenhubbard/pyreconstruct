"""The writer emits keyed trace rows with ids, behind an off-by-default switch.

`Section.getDict` can write a trace as a JSON object keyed by
`KEYED_TRACE_ROW_KEYS` -- `id` first, then the eight positional fields in
positional order -- instead of the 8-element array every build has written since
the format existed. `PYRECON_JSER_KEYED_ROWS=1` selects it, the same spelling
convention and the same read-on-every-call semantics as `PYRECON_JSER_PRETTY`.

Three claims are worth a test file, and only one of them is about the happy path.

**1. Off is off, byte for byte.** A switch that changes the default output by one
byte is not off. `test_the_switch_off_output_is_byte_identical_to_the_positional_
writer` and its revert-and-fail twin pin that, and the same comparison was run
outside the suite against a `git archive` of the base commit on three corpora
including a 50 MB, 125,218-row hand-traced series: identical sha256 on every one.

**2. On is idempotent and id-stable, and the reason is subtler than it looks.**
This build's reader does *not* adopt the id it finds on a keyed row -- lifting the
stored id into the store is S3's slice, not this one. The round trip is id-stable
anyway, because S1 **derives** each id from the row's own content, so a reader that
throws the stored id away re-derives the same one. That is a real property and it
is also a trap: it means an id follows the row's canonical content, so
canonicalizing a non-canonical file changes its ids once, on the first save. Both
halves are pinned below, the second deliberately, because it would otherwise be
discovered as a bug.

**3. The shipped `v1.21.0` reader CANNOT OPEN the output, and that is the price of
the key set.** The legacy keyed branch that has shipped unchanged since `v1.19.0`
reads the fill mode under the key `mode`. This writer spells it `fill_mode` -- the
name the model, this codebase and `docs/JSER_FORMAT.md` all use. Every shipped
build therefore raises `KeyError: 'mode'` on the first keyed row and refuses the
file. `test_the_shipped_v1_21_0_reader_cannot_open_a_fill_mode_keyed_file` runs
exactly that against a `git archive` of the tag, and its sibling runs the
counterfactual -- the same document with the key renamed to `mode` -- which opens
cleanly, matches the object model field for field, and silently deletes every id
on save. The two together are the whole trade: a schema that says what it means,
bought with a hard failure in older builds instead of a silent one.

That third result contradicts the done criterion S5 was dispatched with (which
expected the shipped reader to open the switch-on output with the id loss as the
sole difference). It cannot hold for `fill_mode`; it holds exactly for `mode`.
Both are measured here so the contradiction is on the record rather than in
somebody's memory.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from PyReconstruct.modules.constants.jser_format import (
    FILL_MODE_ROW_KEYS,
    KEYED_ROWS_ENV_VAR,
    KEYED_TRACE_ROW_KEYS,
    keyed_rows_default,
    keyed_trace_row_to_positional,
)
from PyReconstruct.modules.backend.func.state_manager import FieldState
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes.section import Section
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.trace import Trace


REPO_ROOT = Path(__file__).resolve().parents[1]

#: Three sections, eight stored trace rows, six of which survive the reader's own
#: defective-row screens. Small enough to open and save several times per test.
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "parity_series.jser"

#: The tag standing in for "a shipped build older than this change".
OLD_READER_TAG = "v1.21.0"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _open_and_save(jser_fp, keyed=None) -> bytes:
    """Open, push every section through `Section.getDict`, save, return bytes.

    Every section, deliberately. `saveJser` copies the hidden directory
    verbatim (`docs/JSER_FORMAT.md` divergence 1), so a section nobody loaded
    never reaches the writer at all and keeps whatever shape it arrived in. A
    test that only called `saveJser` would show the switch doing nothing and
    would be measuring the copy, not the writer.
    """
    env_backup = os.environ.get(KEYED_ROWS_ENV_VAR)
    if keyed is not None:
        os.environ[KEYED_ROWS_ENV_VAR] = "1" if keyed else "0"
    try:
        series = Series.openJser(str(jser_fp), progress=NullProgressReporter)
        series.setProgressReporter(NullProgressReporter)
        try:
            for n in sorted(series.sections):
                series.loadSection(n).save()
            series.saveJser()
        finally:
            series.close()
    finally:
        if keyed is not None:
            if env_backup is None:
                os.environ.pop(KEYED_ROWS_ENV_VAR, None)
            else:
                os.environ[KEYED_ROWS_ENV_VAR] = env_backup
    return Path(jser_fp).read_bytes()


def _settled(jser_fp) -> bytes:
    """Save twice with the switch off, so the file is one this build agrees with.

    The fixture on disk is not canonical (its rows predate the canonical
    writer), and the first save both canonicalizes it and -- because ids are
    derived from row content -- changes four of its six ids. Comparing anything
    against an unsettled file measures that one-time migration instead of the
    thing under test. `test_canonicalizing_a_file_changes_its_derived_ids` is
    where the migration itself is pinned.
    """
    _open_and_save(jser_fp, keyed=False)
    return _open_and_save(jser_fp, keyed=False)


def _trace_rows(document : bytes):
    """`[(section number, contour, row), ...]` for every stored trace row."""
    doc = json.loads(document)
    rows = []
    for n, section_data in enumerate(doc["sections"]):
        if not section_data:
            continue
        for cname, contour_rows in section_data["contours"].items():
            for row in contour_rows:
                rows.append((n, cname, row))
    return rows


def _model(jser_fp):
    """Every trace's values, read through the object model, as plain JSON types."""
    series = Series.openJser(str(jser_fp), progress=NullProgressReporter)
    try:
        out = []
        for n in sorted(series.sections):
            section = series.loadSection(n)
            for cname in sorted(section.contours):
                for trace in section.contours[cname]:
                    out.append({
                        "section": n,
                        "contour": cname,
                        "name": trace.name,
                        "points": [[round(x, 7), round(y, 7)] for x, y in trace.points],
                        "color": list(trace.color),
                        "closed": bool(trace.closed),
                        "negative": bool(trace.negative),
                        "hidden": bool(trace.hidden),
                        "fill_mode": list(trace.fill_mode),
                        "tags": sorted(trace.tags),
                    })
    finally:
        series.close()
    return out


def _ids(jser_fp):
    """`{(section, contour, index): id}` read out of the columnar store."""
    series = Series.openJser(str(jser_fp), progress=NullProgressReporter)
    try:
        out = {}
        for n in sorted(series.sections):
            section = series.loadSection(n)
            for cname in sorted(section.contours):
                for i, trace in enumerate(section.contours[cname]):
                    row = section._column_rows.get(trace)
                    out[(n, cname, i)] = (
                        None if row is None else section._columns.getID(row)
                    )
    finally:
        series.close()
    return out


@pytest.fixture
def fixture_copy(tmp_path):
    """A writable copy of the fixture: `openJser` writes a hidden dir beside it."""
    destination = tmp_path / "keyed_rows.jser"
    shutil.copyfile(FIXTURE, destination)
    return destination


@pytest.fixture(autouse=True)
def _no_ambient_switch(monkeypatch):
    """No test inherits the switch from the shell that started pytest."""
    monkeypatch.delenv(KEYED_ROWS_ENV_VAR, raising=False)


# --------------------------------------------------------------------------
# the switch
# --------------------------------------------------------------------------

def test_the_switch_is_off_unless_the_environment_says_exactly_one(monkeypatch):
    """Exactly `"1"`, matching `PYRECON_JSER_PRETTY`.

    The exact-match rule is not fussiness: it means a stale
    `PYRECON_JSER_KEYED_ROWS=0` in a shell profile cannot be misread as truthy,
    and neither can `false`, `no` or an empty string.
    """
    assert KEYED_ROWS_ENV_VAR == "PYRECON_JSER_KEYED_ROWS"

    monkeypatch.delenv(KEYED_ROWS_ENV_VAR, raising=False)
    assert keyed_rows_default() is False

    for off in ("", "0", "false", "False", "no", "true", "TRUE", "yes", "2", " 1"):
        monkeypatch.setenv(KEYED_ROWS_ENV_VAR, off)
        assert keyed_rows_default() is False, off

    monkeypatch.setenv(KEYED_ROWS_ENV_VAR, "1")
    assert keyed_rows_default() is True


def test_the_switch_is_read_on_every_call_not_cached_at_import(monkeypatch):
    """A flag evaluated once at import cannot be changed in a running process."""
    monkeypatch.setenv(KEYED_ROWS_ENV_VAR, "1")
    assert keyed_rows_default() is True
    monkeypatch.setenv(KEYED_ROWS_ENV_VAR, "0")
    assert keyed_rows_default() is False


def test_the_explicit_argument_beats_the_environment(fixture_copy, monkeypatch):
    """`getDict(keyed_rows=...)` is authoritative, in both directions."""
    series = Series.openJser(str(fixture_copy), progress=NullProgressReporter)
    try:
        section = series.loadSection(min(series.sections))

        monkeypatch.setenv(KEYED_ROWS_ENV_VAR, "1")
        assert _shapes(section.getDict(keyed_rows=False)) == {"list"}
        assert _shapes(section.getDict()) == {"dict"}

        monkeypatch.delenv(KEYED_ROWS_ENV_VAR)
        assert _shapes(section.getDict(keyed_rows=True)) == {"dict"}
        assert _shapes(section.getDict()) == {"list"}
    finally:
        series.close()


def _shapes(section_dict) -> set:
    return {
        "dict" if isinstance(row, dict) else "list"
        for rows in section_dict["contours"].values()
        for row in rows
    }


# --------------------------------------------------------------------------
# 1. off is off
# --------------------------------------------------------------------------

def test_the_switch_off_output_is_byte_identical_to_the_positional_writer(tmp_path):
    """Two saves of one series, switch off both times, byte for byte equal.

    The in-suite form of the claim. The out-of-suite form -- the same file saved
    by a `git archive` of the base commit, which has no switch at all -- was run
    on `parity_series` (7,190 B), `class_series` (471,510 B) and a 50 MB,
    125,218-row hand-traced series (50,631,588 B) and matched on sha256 in every
    case. That comparison cannot live in the suite, because it needs a second
    checkout.
    """
    first_fp = tmp_path / "first.jser"
    second_fp = tmp_path / "second.jser"
    shutil.copyfile(FIXTURE, first_fp)
    shutil.copyfile(FIXTURE, second_fp)

    assert _settled(first_fp) == _settled(second_fp)


def test_switching_on_actually_changes_the_bytes(tmp_path):
    """The revert-and-fail probe for the test above.

    A byte-identity assertion is only worth having if the thing it holds fixed
    can move. Same series, same code path, switch flipped: the document changes,
    every row becomes an object, and the file grows.
    """
    fp = tmp_path / "probe.jser"
    shutil.copyfile(FIXTURE, fp)
    positional = _settled(fp)
    keyed = _open_and_save(fp, keyed=True)

    assert keyed != positional
    assert len(keyed) > len(positional)
    assert {type(row) for _, _, row in _trace_rows(positional)} == {list}
    assert {type(row) for _, _, row in _trace_rows(keyed)} == {dict}


def test_the_switch_off_writer_still_emits_the_documented_positional_row(tmp_path):
    """8 elements, no name, unchanged. The default path is not being edited."""
    fp = tmp_path / "positional.jser"
    shutil.copyfile(FIXTURE, fp)
    rows = _trace_rows(_settled(fp))

    assert rows
    for _, _, row in rows:
        assert isinstance(row, list)
        assert len(row) == 8


# --------------------------------------------------------------------------
# 2. on: every row keyed, every id present, and the cycle is stable
# --------------------------------------------------------------------------

def test_every_row_is_keyed_and_every_id_is_present(tmp_path):
    """The done criterion, stated as one assertion per clause."""
    fp = tmp_path / "keyed.jser"
    shutil.copyfile(FIXTURE, fp)
    _settled(fp)
    rows = _trace_rows(_open_and_save(fp, keyed=True))

    assert rows
    ids = []
    for _, _, row in rows:
        assert isinstance(row, dict)
        assert tuple(row) == KEYED_TRACE_ROW_KEYS, (
            "the key set AND the key order are both normative: the order is what "
            "makes two saves of identical content produce identical bytes"
        )
        assert isinstance(row["id"], str) and len(row["id"]) == 11
        ids.append(row["id"])

    assert len(set(ids)) == len(ids), "ids must be unique across the whole series"


def test_the_keyed_row_writes_fill_mode_and_never_mode(tmp_path):
    """THE SETTLED KEY-SET DECISION, pinned so it cannot drift back.

    `fill_mode` is what the model calls the field and what
    `docs/JSER_FORMAT.md` calls it. `mode` is the legacy keyed spelling, which
    this writer does not emit -- not alongside `fill_mode` either. What it costs
    is measured further down this file.
    """
    fp = tmp_path / "spelling.jser"
    shutil.copyfile(FIXTURE, fp)
    _settled(fp)

    assert KEYED_TRACE_ROW_KEYS[0] == "id", "id leads, as it does on a flag row"
    assert "fill_mode" in KEYED_TRACE_ROW_KEYS
    assert "mode" not in KEYED_TRACE_ROW_KEYS

    for _, _, row in _trace_rows(_open_and_save(fp, keyed=True)):
        assert "fill_mode" in row
        assert "mode" not in row
        assert isinstance(row["fill_mode"], list) and len(row["fill_mode"]) == 2


def test_the_keyed_row_carries_the_same_values_as_the_positional_row(tmp_path):
    """Only the container differs. Every value is the positional row's value.

    Both shapes are produced by `Trace.getList`, so this is really a test that
    the keyed writer did not grow a second encoder -- which is the way a shape
    change quietly becomes a value change.
    """
    fp = tmp_path / "values.jser"
    shutil.copyfile(FIXTURE, fp)
    positional = _trace_rows(_settled(fp))
    keyed = _trace_rows(_open_and_save(fp, keyed=True))

    assert len(positional) == len(keyed)
    for (pn, pc, prow), (kn, kc, krow) in zip(positional, keyed):
        assert (pn, pc) == (kn, kc)
        assert keyed_trace_row_to_positional(krow) == prow


def test_the_full_open_save_open_save_cycle_is_byte_idempotent_and_id_stable(tmp_path):
    """The done criterion's round trip, in the reader that is shipping with it.

    Note what makes it hold: this build's reader **drops** the stored id (S3
    owns adoption) and derives a fresh one from the row's content, which is the
    same one, because derivation is a function of content. So the cycle is
    id-stable through a reader that never reads the ids being tested. That is
    genuinely the design and not an accident -- but it means this test would
    still pass if the writer wrote the ids into a black hole, which is why
    `test_every_row_is_keyed_and_every_id_is_present` checks the file itself.
    """
    fp = tmp_path / "cycle.jser"
    shutil.copyfile(FIXTURE, fp)
    _settled(fp)

    first = _open_and_save(fp, keyed=True)
    ids_after_first = _ids(fp)
    second = _open_and_save(fp, keyed=True)
    ids_after_second = _ids(fp)

    assert first == second, "the second keyed save is not byte-idempotent"
    assert ids_after_first == ids_after_second
    assert set(ids_after_first.values()) == {
        row["id"] for _, _, row in _trace_rows(second)
    }


def test_a_keyed_file_saved_with_the_switch_off_returns_to_the_positional_bytes(
    tmp_path,
):
    """The switch is reversible in the file, not only in the process.

    Turning it off after a keyed save must not leave a half-converted document
    behind: the file comes back byte-for-byte to what the positional writer
    produces. Measured out of suite on the 125,218-row series as well.
    """
    fp = tmp_path / "reversible.jser"
    shutil.copyfile(FIXTURE, fp)
    positional = _settled(fp)
    _open_and_save(fp, keyed=True)

    assert _open_and_save(fp, keyed=False) == positional


def test_the_object_model_is_unchanged_by_a_round_trip_through_keyed_rows(tmp_path):
    """Geometry, color, closed, negative, hidden, fill mode and tags, all equal."""
    fp = tmp_path / "model.jser"
    shutil.copyfile(FIXTURE, fp)
    _settled(fp)
    before = _model(fp)

    _open_and_save(fp, keyed=True)

    assert _model(fp) == before


def test_canonicalizing_a_file_changes_its_derived_ids(tmp_path):
    """A trap, pinned deliberately rather than left to be found later.

    S1 derives a trace's id from the trace's own stored content. The fixture on
    disk is not canonical, so its first save through this build's writer changes
    that content -- rounding, tag order, the two-point `closed` repair -- and the
    ids move with it, once. They are stable from then on.

    This is not a defect and it is not caused by keyed rows (it is measurable
    with the switch off, where the ids are not even written). It is a property of
    deriving identity from content, and it means "the id of this trace" is only
    well defined relative to a canonical encoding of the trace.
    """
    fp = tmp_path / "churn.jser"
    shutil.copyfile(FIXTURE, fp)

    # read off the file as it sits on disk, before any save rewrites it
    as_shipped = _ids(fp)

    _open_and_save(fp, keyed=False)
    after_first = _ids(fp)
    _open_and_save(fp, keyed=False)
    after_second = _ids(fp)

    assert as_shipped.keys() == after_first.keys()
    assert as_shipped != after_first, (
        "the fixture is expected to be non-canonical on disk; if it has become "
        "canonical this test no longer demonstrates anything and should be "
        "given a non-canonical file of its own"
    )
    assert after_first == after_second, "ids must settle after one canonical save"


# --------------------------------------------------------------------------
# the two readers that have to know the shape
# --------------------------------------------------------------------------

def test_the_decoder_accepts_both_spellings_of_the_fill_mode(monkeypatch):
    """Tolerance on the read side is free, and is required forever.

    "The reader must keep reading every past shape forever" -- and `mode` is a
    past shape with files in the wild, written by the legacy keyed branch that
    has shipped unchanged since v1.19.0.
    """
    assert FILL_MODE_ROW_KEYS == ("fill_mode", "mode")

    base = {
        "x": [1.0, 2.0], "y": [3.0, 4.0], "color": [1, 2, 3],
        "closed": False, "negative": False, "hidden": False, "tags": ["t"],
    }
    expected = [[1.0, 2.0], [3.0, 4.0], [1, 2, 3], False, False, False,
                ["none", "none"], ["t"]]

    assert keyed_trace_row_to_positional({**base, "fill_mode": ["none", "none"]}) == expected
    assert keyed_trace_row_to_positional({**base, "mode": ["none", "none"]}) == expected

    # newest spelling wins when a row somehow carries both
    both = {**base, "fill_mode": ["solid", "always"], "mode": ["none", "none"]}
    assert keyed_trace_row_to_positional(both)[6] == ["solid", "always"]

    # and a row with neither is reported against the name this build writes
    with pytest.raises(KeyError) as raised:
        keyed_trace_row_to_positional(base)
    assert raised.value.args[0] == "fill_mode"


def test_updatejson_reads_a_keyed_row_this_build_wrote(tmp_path):
    """The unpack path: keyed rows in, positional rows out, values intact.

    A mixed contour on purpose -- one keyed row with an id, one keyed row
    without, one keyed row using the legacy `mode` spelling, one positional row
    -- because the reader decides per row and one document may legitimately hold
    all four.
    """
    section_data = Section.getEmptyDict()
    section_data["contours"] = {"d01": [
        {"id": "abcdefghijk", "x": [0.0, 1.0, 2.0], "y": [0.0, 1.0, 0.0],
         "color": [1, 2, 3], "closed": True, "negative": False, "hidden": False,
         "fill_mode": ["solid", "always"], "tags": ["b", "a"]},
        {"x": [0.0, 1.0, 2.0], "y": [1.0, 2.0, 1.0], "color": [4, 5, 6],
         "closed": False, "negative": True, "hidden": True,
         "fill_mode": ["none", "none"], "tags": []},
        {"x": [0.0, 1.0, 2.0], "y": [2.0, 3.0, 2.0], "color": [7, 8, 9],
         "closed": True, "negative": False, "hidden": False,
         "mode": ["transparent", "selected"], "tags": ["z"]},
        [[0.0, 1.0, 2.0], [3.0, 4.0, 3.0], [10, 11, 12], True, False, False,
         ["none", "none"], []],
    ]}

    Section.updateJSON(section_data, 0)

    rows = section_data["contours"]["d01"]
    assert [type(row) for row in rows] == [list, list, list, list]
    assert [len(row) for row in rows] == [8, 8, 8, 8]
    assert rows[0][6] == ["solid", "always"]
    assert rows[0][7] == ["a", "b"], "tags are sorted on unpack, keyed or not"
    assert rows[2][6] == ["transparent", "selected"], "the legacy spelling is read"
    assert rows[3][2] == [10, 11, 12], "the positional row is untouched"


def test_the_undo_baseline_reads_a_keyed_section_file(tmp_path):
    """Mechanism 5, the one silent trap in the read path.

    `FieldState.getContours` parses a `shutil.copyfile` copy of the section file
    without going through `Section.updateJSON`, so it has to know the keyed shape
    itself. Handed one before this slice it did not raise: `len(dict)` is the key
    count and iterating a dict yields its keys, so an 8-key row unpacked eight
    KEY STRINGS into the eight fields and a 9-key row additionally took the first
    key as the name. The undo baseline silently became a `Trace` named `'x'`.

    The revert-and-fail form of this test is the second half: the same file
    decoded the old way is shown to produce that garbage, so the assertion above
    is known to be load-bearing.
    """
    baseline_fp = tmp_path / "baseline.s0"
    baseline_fp.write_text(json.dumps({"contours": {"d01": [
        {"id": "abcdefghijk", "x": [0.0, 1.0, 2.0], "y": [0.0, 1.0, 0.0],
         "color": [1, 2, 3], "closed": True, "negative": False, "hidden": False,
         "fill_mode": ["solid", "always"], "tags": ["a"]},
    ]}}), encoding="utf-8")

    state = FieldState.__new__(FieldState)
    state.contours_fp = str(baseline_fp)
    state.contours = None

    contours = state.getContours()

    assert list(contours) == ["d01"]
    trace = contours["d01"][0]
    assert trace.name == "d01"
    assert trace.points == [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]
    assert trace.color == [1, 2, 3]
    assert trace.closed is True
    assert trace.fill_mode == ["solid", "always"]
    assert trace.tags == {"a"}

    # revert-and-fail: what the pre-slice decode produced, run here so the
    # assertions above are known to be load-bearing rather than vacuous
    raw = json.loads(baseline_fp.read_text())["contours"]["d01"][0]
    garbage = Trace.fromList(raw, "d01")
    assert garbage.name == "id", (
        "the old path is expected to build a Trace named after a KEY; if it no "
        "longer does, this revert probe has stopped proving anything"
    )
    assert garbage.points != trace.points


# --------------------------------------------------------------------------
# 3. and the shipped reader
# --------------------------------------------------------------------------

_OLD_READER_DRIVER = '''\
"""Open a .jser with THIS checkout's build and report what it saw.

Written into the extracted tag so that its own directory is sys.path[0] and the
extracted PyReconstruct wins over anything installed in the interpreter.
"""
import json, os, sys, traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PyReconstruct
from PyReconstruct.modules.datatypes.series import Series

jser_fp, result_fp = sys.argv[1], sys.argv[2]

out = {"package": PyReconstruct.__file__}
try:
    series = Series.openJser(jser_fp)
    traces = []
    for n in sorted(series.sections):
        section = series.loadSection(n)
        for cname in sorted(section.contours):
            for trace in section.contours[cname]:
                traces.append({
                    "section": n, "contour": cname, "name": trace.name,
                    "points": [[round(x, 7), round(y, 7)] for x, y in trace.points],
                    "color": list(trace.color), "closed": bool(trace.closed),
                    "negative": bool(trace.negative), "hidden": bool(trace.hidden),
                    "fill_mode": list(trace.fill_mode), "tags": sorted(trace.tags),
                })
    series.saveJser()
    series.close()
    with open(jser_fp, "rb") as f:
        doc = json.loads(f.read())
    rows, shapes, ids = 0, set(), 0
    for section_data in doc["sections"]:
        if not section_data:
            continue
        for contour_rows in section_data.get("contours", {}).values():
            for row in contour_rows:
                rows += 1
                if isinstance(row, dict):
                    shapes.add("dict")
                    ids += "id" in row
                else:
                    shapes.add("list:%d" % len(row))
    out.update(ok=True, traces=traces, rows=rows, shapes=sorted(shapes),
               rows_with_id=ids)
except BaseException:
    out.update(ok=False, error=traceback.format_exc())

with open(result_fp, "w", encoding="utf-8") as f:
    json.dump(out, f)
'''


def _extract_old_reader(tmp_path):
    """`git archive` the shipped tag into a directory, or skip saying why."""
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", OLD_READER_TAG],
        capture_output=True,
    )
    if proc.returncode != 0:
        pytest.skip(
            f"cannot `git archive {OLD_READER_TAG}` from {REPO_ROOT}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()[:300]}"
        )
    destination = tmp_path / "old_reader"
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
        # `filter=` is 3.12+; 3.11 has no filtering and no deprecation warning.
        try:
            archive.extractall(destination, filter="data")
        except TypeError:  # pragma: no cover - Python < 3.12
            archive.extractall(destination)
    return destination


def _run_old_reader(tmp_path, document : bytes, label : str):
    """Hand `document` to the extracted tag; return its report."""
    old_reader = _extract_old_reader(tmp_path / label)
    driver_fp = old_reader / "_keyed_row_roundtrip.py"
    driver_fp.write_text(_OLD_READER_DRIVER, encoding="utf-8")

    handed_over = tmp_path / f"{label}.jser"
    handed_over.write_bytes(document)
    result_fp = tmp_path / f"{label}_result.json"

    proc = subprocess.run(
        [sys.executable, driver_fp.name, str(handed_over), str(result_fp)],
        cwd=str(old_reader),
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True,
    )
    assert proc.returncode == 0, (
        f"the {OLD_READER_TAG} driver did not run:\n"
        f"{proc.stdout.decode('utf-8', 'replace')[-2000:]}\n"
        f"{proc.stderr.decode('utf-8', 'replace')[-4000:]}"
    )
    result = json.loads(result_fp.read_text())
    assert str(old_reader) in result["package"], (
        "the extracted tag must be the package under test, not an installed one"
    )
    return result


@pytest.fixture
def keyed_document(tmp_path):
    """A settled series saved with the switch on, plus its object model."""
    fp = tmp_path / "handover_source.jser"
    shutil.copyfile(FIXTURE, fp)
    _settled(fp)
    model = _model(fp)
    return _open_and_save(fp, keyed=True), model


def test_the_shipped_v1_21_0_reader_cannot_open_a_fill_mode_keyed_file(
    tmp_path, keyed_document
):
    """THE PRICE OF THE KEY SET, run rather than asserted.

    Real reader, real file, real refusal. `v1.21.0`'s keyed branch reads
    `trace["mode"]`, this writer emits `fill_mode`, and the open dies with
    `KeyError: 'mode'` before a single trace exists.

    This contradicts the done criterion S5 was dispatched with, which expected
    the shipped reader to open this file with the id loss as the sole
    difference. That criterion was written against the `mode` spelling. It
    cannot hold for `fill_mode`, and the counterfactual immediately below shows
    it holding exactly for `mode`, so the contradiction is the key-set decision
    and nothing else.
    """
    document, _ = keyed_document
    result = _run_old_reader(tmp_path, document, "fill_mode")

    assert result["ok"] is False
    assert "KeyError: 'mode'" in result["error"]
    assert 'trace["mode"]' in result["error"]


def test_the_same_document_spelled_mode_opens_and_loses_every_id(
    tmp_path, keyed_document
):
    """The counterfactual, and the row of the reader-x-writer matrix S7 needs.

    Byte for byte the same document with one key renamed. The shipped reader
    opens it, every trace matches the object model field for field -- geometry,
    color, closed, negative, hidden, fill mode, tags -- and its save writes
    positional rows with **every id deleted**, for every section in the file
    rather than only the ones a user touched, with no error and no warning.
    """
    document, model = keyed_document
    doc = json.loads(document)
    for section_data in doc["sections"]:
        if not section_data:
            continue
        for contour_rows in section_data["contours"].values():
            for row in contour_rows:
                row["mode"] = row.pop("fill_mode")

    result = _run_old_reader(tmp_path, json.dumps(doc).encode(), "mode")

    assert result["ok"] is True, result.get("error")
    assert result["traces"] == model, (
        "the shipped reader disagreed with the object model about a value, "
        "which would make the id loss the lesser problem"
    )
    assert result["shapes"] == ["list:8"], (
        "the resaved rows are positional: the keyed shape does not survive"
    )
    assert result["rows_with_id"] == 0, "every id is gone, silently"
    assert result["rows"] == len(model)
