"""`schema_version` at the root of the series object, and the two things it is not.

The writer stamps `schema_version` into the series object, first key, from
`Series.getDict`. The reader tolerates it being absent -- which is the ordinary
case, not the exotic one. That much is three lines of production code. The
reason this file exists is the part that is easy to get wrong later:

**The field is a hint for external consumers. It is never a reader's dispatch
key.** Two independent reasons, and the tests below pin both.

1. **An older build silently deletes it, and keeps the rows it wrote.** The
   series object is rebuilt from the in-memory model on every save
   (`docs/JSER_FORMAT.md` divergence 1: "sections pass through opaquely; the
   series object does not"), and no build before this one has `schema_version`
   in its `Series.getDict`. So a colleague on the shipped v1.21.0 build opens a
   file this build wrote, gets every trace correctly, saves, and hands back a
   file with the key gone and every row untouched.
   `test_the_shipped_v1_21_0_reader_drops_the_schema_version` runs exactly that,
   against a `git archive` of the v1.21.0 tag -- the real shipped reader, not a
   model of one. **Absence is therefore not evidence about a file's age or its
   shape**, so a reader that treated absence as "legacy" would be wrong about a
   file written by this build ten minutes ago and round-tripped once.
2. **It could not describe the rows even if it survived.** Row shape is decided
   per row: every shipped reader back to v1.19.0 accepts a positional trace row
   and a keyed one in the same contour, so one document can legitimately hold
   both. A single document-level integer has nothing true to say about that
   mixture. **Per-row shape detection stays authoritative.**

`test_the_reader_never_dispatches_on_the_stored_value` is the guard against
reason 2 being quietly forgotten: a file claiming version 9999, a file claiming
nothing, and a file claiming the truth all load to the same document and save to
the same bytes.

What the field *is* good for is what survives its own unreliability: a converter,
an archive checker or a lab script reading `.jser` without PyReconstruct gets a
positive statement of the schema the last writer intended, when there is one.
Present means "written by a build that stamps this"; absent means "no claim".
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
    JSER_SCHEMA_VERSION,
    SERIES_KEYS,
)
from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes.series import Series


REPO_ROOT = Path(__file__).resolve().parents[1]

#: Three sections, eight stored trace rows. Small enough to open and save
#: several times per test, real enough to be a .jser rather than a hand-built
#: dict.
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "parity_series.jser"

#: The tag standing in for "a shipped build older than this change".
OLD_READER_TAG = "v1.21.0"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _open_and_save(jser_fp) -> bytes:
    """Open `jser_fp` through the real reader, save it back, return the bytes."""
    series = Series.openJser(str(jser_fp), progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    try:
        series.saveJser()
    finally:
        series.close()
    return Path(jser_fp).read_bytes()


@pytest.fixture
def fixture_copy(tmp_path):
    """A writable copy of the fixture: `openJser` writes a hidden dir beside it."""
    destination = tmp_path / "schema_version.jser"
    shutil.copyfile(FIXTURE, destination)
    return destination


# --------------------------------------------------------------------------
# the writer stamps it
# --------------------------------------------------------------------------

def test_getdict_stamps_the_schema_version(fixture_copy):
    """`Series.getDict` emits the constant, as its first key."""
    series = Series.openJser(str(fixture_copy), progress=NullProgressReporter)
    try:
        d = series.getDict()
    finally:
        series.close()
    assert d["schema_version"] == JSER_SCHEMA_VERSION
    assert next(iter(d)) == "schema_version"


def test_a_saved_jser_carries_the_schema_version_in_the_series_object(fixture_copy):
    """A real save puts it at the root of the series object, first.

    Root of the *series object*, which is where `Series.getDict` writes and where
    `SERIES_KEYS` orders. The document's own top level is unchanged and still
    holds exactly `sections`, `series`, `log`.
    """
    doc = json.loads(_open_and_save(fixture_copy))

    assert list(doc) == ["sections", "series", "log"]
    assert doc["series"]["schema_version"] == JSER_SCHEMA_VERSION
    assert list(doc["series"])[0] == "schema_version"
    assert "schema_version" not in doc


def test_schema_version_leads_the_canonical_series_key_order():
    """The canonical order declares the version before the data it describes."""
    assert SERIES_KEYS[0] == "schema_version"


def test_no_section_object_grows_a_schema_version(fixture_copy):
    """The key is series-level only; sections are untouched by this slice."""
    doc = json.loads(_open_and_save(fixture_copy))
    for section_data in doc["sections"]:
        if section_data is not None:
            assert "schema_version" not in section_data


# --------------------------------------------------------------------------
# the reader tolerates it
# --------------------------------------------------------------------------

def test_updatejson_tolerates_an_absent_schema_version():
    """The empty template has no `schema_version`; `updateJSON` supplies one.

    Absence is the ordinary case, not a corruption: every file written before
    this key existed lacks it, and so does every file whose last writer was an
    older build (see the module docstring).
    """
    series_data = Series.getEmptyDict()
    assert "schema_version" not in series_data

    Series.updateJSON(series_data)

    assert series_data["schema_version"] == JSER_SCHEMA_VERSION


def test_updatejson_restates_rather_than_trusts_a_foreign_schema_version():
    """A number from some other build does not survive into this build's model.

    `updateJSON` *is* the migration to the shape this build understands, so what
    it stamps is a true statement about the dict that leaves it. Carrying a
    foreign claim forward would label this build's in-memory document with a
    version that is not about it.
    """
    for foreign in (0, 9999, "banana", None, [1]):
        series_data = Series.getEmptyDict()
        series_data["schema_version"] = foreign
        Series.updateJSON(series_data)  # tolerated: no raise, whatever it was
        assert series_data["schema_version"] == JSER_SCHEMA_VERSION


def test_the_reader_never_dispatches_on_the_stored_value(tmp_path):
    """Claiming 9999, claiming nothing and claiming the truth all load alike.

    This is the guard on the property the field must keep: **per-row shape
    detection is authoritative and this value decides nothing.** If some future
    change starts branching on it, this test is what goes red.
    """
    baseline_fp = tmp_path / "baseline.jser"
    shutil.copyfile(FIXTURE, baseline_fp)
    baseline = _open_and_save(baseline_fp)
    assert json.loads(baseline)["series"]["schema_version"] == JSER_SCHEMA_VERSION

    for label, claim in (("absent", ...), ("future", 9999), ("garbage", "banana")):
        doc = json.loads(baseline)
        if claim is ...:
            del doc["series"]["schema_version"]
        else:
            doc["series"]["schema_version"] = claim

        variant_fp = tmp_path / f"{label}.jser"
        variant_fp.write_bytes(json.dumps(doc).encode())

        assert _open_and_save(variant_fp) == baseline, (
            f"a stored schema_version of {label!r} changed what the reader "
            "produced; the value is a hint and must decide nothing"
        )


# --------------------------------------------------------------------------
# and a shipped older build deletes it
# --------------------------------------------------------------------------

_OLD_READER_DRIVER = '''\
"""Open a .jser with THIS checkout's build and save it back.

Written into the extracted tag so that its own directory is sys.path[0] and the
extracted PyReconstruct wins over anything installed in the interpreter.
"""
import json, os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PyReconstruct
from PyReconstruct.modules.datatypes.series import Series

jser_fp, result_fp = sys.argv[1], sys.argv[2]

series = Series.openJser(jser_fp)
series.saveJser()
series.close()

with open(jser_fp, "rb") as f:
    doc = json.loads(f.read())

rows = 0
shapes = set()
for section_data in doc["sections"]:
    if not section_data:
        continue
    for rows_of in section_data.get("contours", {}).values():
        for row in rows_of:
            rows += 1
            shapes.add("dict:%d" % len(row) if isinstance(row, dict)
                       else "list:%d" % len(row))

with open(result_fp, "w", encoding="utf-8") as f:
    json.dump({
        "package": PyReconstruct.__file__,
        "series_keys": list(doc["series"]),
        "sections": doc["sections"],
        "rows": rows,
        "shapes": sorted(shapes),
    }, f)
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
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
        # `filter=` is 3.12+; 3.11 has no filtering and no deprecation warning.
        try:
            archive.extractall(destination, filter="data")
        except TypeError:  # pragma: no cover - Python < 3.12
            archive.extractall(destination)
    return destination


def test_the_shipped_v1_21_0_reader_drops_the_schema_version(tmp_path, fixture_copy):
    """THE CAVEAT, RUN RATHER THAN ASSERTED. Real reader, real file, real loss.

    A `git archive` of the v1.21.0 tag is the shipped stable build: it opens a
    file this build wrote, reads every trace correctly, and its save deletes
    `schema_version` while leaving every row exactly as it found it.

    Recorded here as an expectation on purpose, so that whoever later reaches for
    this field as a version gate meets the loss in a test rather than in a
    colleague's file.

    Two things the assertions below deliberately do *not* treat as damage,
    because they are v1.21.0 behaviors unrelated to this key and both are
    already fixed on main: it re-emits `log_set` into the series object, and it
    forces `align_locked` to true on unpack (`docs/JSER_FORMAT.md` divergence 3).
    """
    written = json.loads(_open_and_save(fixture_copy))
    assert written["series"]["schema_version"] == JSER_SCHEMA_VERSION, (
        "the file handed to the old reader must actually carry the key, or the "
        "disappearance below proves nothing"
    )

    old_reader = _extract_old_reader(tmp_path)
    driver_fp = old_reader / "_schema_version_roundtrip.py"
    driver_fp.write_text(_OLD_READER_DRIVER, encoding="utf-8")

    handed_over = tmp_path / "handed_over.jser"
    handed_over.write_bytes(Path(fixture_copy).read_bytes())

    result_fp = tmp_path / "old_reader_result.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(
        [sys.executable, driver_fp.name, str(handed_over), str(result_fp)],
        cwd=str(old_reader),
        env=env,
        capture_output=True,
    )
    assert proc.returncode == 0, (
        f"the {OLD_READER_TAG} reader failed on a file this build wrote:\n"
        f"{proc.stdout.decode('utf-8', 'replace')[-2000:]}\n"
        f"{proc.stderr.decode('utf-8', 'replace')[-4000:]}"
    )
    result = json.loads(result_fp.read_text())

    # the reader really was the extracted tag, not the installed package
    assert str(old_reader) in result["package"]

    # 1. the key is gone, silently: no error, no warning, no note in the file
    assert "schema_version" not in result["series_keys"]

    # 2. and nothing else about the traces changed. The rows the old build wrote
    #    are the rows it was given -- which is exactly why the loss is silent.
    expected_rows = sum(
        len(rows)
        for section_data in written["sections"] if section_data
        for rows in section_data["contours"].values()
    )
    assert result["rows"] == expected_rows
    assert result["shapes"] == ["list:8"]
    for ours, theirs in zip(written["sections"], result["sections"]):
        if ours is None or theirs is None:
            assert ours is theirs
            continue
        assert theirs["contours"] == ours["contours"]
        assert theirs["flags"] == ours["flags"]
