"""A save copies the sections it did not change, and the file is still exact.

``write_jser`` with ``splice=`` copies a section whose working file has the
same bytes it had at the last save from the .jser that save wrote, and encodes
the rest (``jser_splice.py``). Every test here compares the saved file with
``old_path_bytes``, the whole-document reference from the streaming tests, so
a spliced save must be byte for byte a full save.

Two things are checked on every save: the bytes, and how many sections were
copied. A splice that copied nothing would pass the byte checks forever.

The other half is the fallbacks. Each one ends in a full write with the right
bytes: no previous file, a previous file changed by someone else, a changed
file that kept its size and mtime, a stale index, the pretty form, the stdlib
fallback, and a save that fails partway through a copy.
"""

import errno
import os

import pytest

from PyReconstruct.modules.constants import jser_splice
from PyReconstruct.modules.constants.jser_format import PRETTY_ENV_VAR
from PyReconstruct.modules.datatypes.transform import Transform
from tests.test_jser_streaming_save import (
    FIXTURES,
    RecordingNotifier,
    lone_surrogate_in_last_section,
    old_path_bytes,
    open_copy,
    temp_files,
)


@pytest.fixture
def copies(monkeypatch):
    """Counts the sections each save copied, in a list reset by the caller."""
    counted = []
    real = jser_splice._SectionWriter._copy

    def counting(self, f, offset, length, digest):
        counted.append(offset)
        return real(self, f, offset, length, digest)

    monkeypatch.setattr(jser_splice._SectionWriter, "_copy", counting)
    return counted


def save_and_check(series, copies):
    """Save, check the bytes against the full-write reference, return the copy count."""
    series.save()  # saveJser writes the .ser first; the reference reads it
    expected = old_path_bytes(series)
    copies.clear()
    series.saveJser()
    with open(series.jser_fp, "rb") as f:
        assert f.read() == expected
    assert temp_files(series.jser_fp) == []
    return len(copies)


def opened(tmp_path, source):
    series = open_copy(tmp_path, source)
    if len(series.sections) < 2:  # pragma: no cover - fixture guard
        pytest.skip("fixture has one section")
    return series


def first_traced_section(series):
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        if section.tracesAsList():
            return section
    pytest.skip("fixture has no traces")  # pragma: no cover


# ---------------------------------------------------------------------------
# the edits a user makes, on every fixture
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_a_save_with_no_change_copies_every_section(tmp_path, copies, source):
    series = opened(tmp_path, source)
    assert save_and_check(series, copies) == 0  # no previous save to copy from
    first = open(series.jser_fp, "rb").read()

    assert save_and_check(series, copies) == len(series.sections)
    assert open(series.jser_fp, "rb").read() == first


@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_one_trace_edit_encodes_only_its_section(tmp_path, copies, source):
    series = opened(tmp_path, source)
    save_and_check(series, copies)

    section = first_traced_section(series)
    trace = section.tracesAsList()[0]
    trace.points = [(x + 0.5, y) for x, y in trace.points]
    section.save()

    assert save_and_check(series, copies) == len(series.sections) - 1


@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_an_object_rename_is_exact(tmp_path, copies, source):
    series = opened(tmp_path, source)
    save_and_check(series, copies)

    section = first_traced_section(series)
    name = section.tracesAsList()[0].name
    series.editObjectAttributes([name], name=name + "_renamed", log_event=False)

    touched = sum(
        1 for snum in series.sections
        if name + "_renamed" in series.loadSection(snum).contours
    )
    assert touched
    assert save_and_check(series, copies) == len(series.sections) - touched


@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_an_alignment_change_is_exact(tmp_path, copies, source):
    series = opened(tmp_path, source)
    save_and_check(series, copies)

    # one section's transform
    snum = sorted(series.sections)[-1]
    section = series.loadSection(snum)
    section.tform = Transform([1, 0, 3.5, 0, 1, -2.25])
    section.save()
    assert save_and_check(series, copies) == len(series.sections) - 1

    # a new alignment on every section
    old = list(series.loadSection(snum).tforms)
    series.modifyAlignments({**{a: a for a in old}, "spliced": old[0]})
    assert save_and_check(series, copies) == 0
    assert save_and_check(series, copies) == len(series.sections)


@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_a_section_insert_and_delete_are_exact(tmp_path, copies, source):
    series = opened(tmp_path, source)
    save_and_check(series, copies)
    n = len(series.sections)

    # insert in the middle renumbers every section after it
    snums = sorted(series.sections)
    middle = snums[len(snums) // 2]
    first = series.loadSection(snums[0])
    series.insertSection(middle, first.src, first.mag, first.thickness, log_event=False)
    assert len(series.sections) == n + 1
    copied = save_and_check(series, copies)
    assert 0 < copied < n + 1

    # delete one: every other section is copied, wherever it now sits
    series.deleteSections([sorted(series.sections)[1]], log_event=False)
    assert save_and_check(series, copies) == n


@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_series_level_edits_copy_every_section(tmp_path, copies, source):
    series = opened(tmp_path, source)
    save_and_check(series, copies)

    series.setOption("small_dist", 0.0123)
    series.addLog(None, None, "Splice save test")
    series.save()
    assert save_and_check(series, copies) == len(series.sections)


def test_a_backup_save_splices_and_keeps_the_index_on_the_series_file(
        tmp_path, copies):
    series = opened(tmp_path, FIXTURES[1])
    save_and_check(series, copies)
    index = series._jser_splice_index

    backup = str(tmp_path / "backup.jser")
    series.save()
    expected = old_path_bytes(series)
    copies.clear()
    series.saveJser(backup)
    assert open(backup, "rb").read() == expected
    assert len(copies) == len(series.sections)
    assert series._jser_splice_index is index

    assert save_and_check(series, copies) == len(series.sections)


# ---------------------------------------------------------------------------
# the fallbacks: each one is a full write with the right bytes
# ---------------------------------------------------------------------------

@pytest.fixture
def spliceable(tmp_path, copies):
    """A series saved once, so the next save has an index to copy from."""
    series = opened(tmp_path, FIXTURES[1])
    save_and_check(series, copies)
    assert series._jser_splice_index is not None
    notifier = RecordingNotifier()
    series.setNotifier(notifier)
    yield series, notifier
    series.leave_open = False
    series.close()


def test_a_file_replaced_by_someone_else_is_not_copied_from(spliceable, copies):
    series, _ = spliceable
    with open(series.jser_fp, "rb") as f:
        data = f.read()
    tmp = series.jser_fp + ".other"
    with open(tmp, "wb") as f:
        f.write(data[:-1] + b" }")
    os.replace(tmp, series.jser_fp)

    assert save_and_check(series, copies) == 0


def test_a_file_edited_in_place_with_its_stat_kept_fails_the_checksum(
        spliceable, copies):
    series, _ = spliceable
    st = os.stat(series.jser_fp)
    index = series._jser_splice_index
    offset = min(r[0] for r in index.ranges.values())
    with open(series.jser_fp, "r+b") as f:
        f.seek(offset)
        b = f.read(1)
        f.seek(offset)
        f.write(b"0" if b != b"0" else b"1")
    os.utime(series.jser_fp, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert index.matchesDisk()

    assert save_and_check(series, copies) == 1  # the one bad copy, then a full write


@pytest.mark.parametrize("damage", ["shifted", "past_the_end", "wrong_digest"])
def test_a_stale_index_is_a_full_write(spliceable, copies, damage):
    series, _ = spliceable
    index = series._jser_splice_index
    size = os.path.getsize(series.jser_fp)
    for key, (offset, length, digest) in list(index.ranges.items()):
        if damage == "shifted":
            index.ranges[key] = (offset + 1, length, digest)
        elif damage == "past_the_end":
            index.ranges[key] = (size - 1, length, digest)
        else:
            index.ranges[key] = (offset, length, bytes(32))

    assert save_and_check(series, copies) == 1
    assert save_and_check(series, copies) == len(series.sections)


def test_a_previous_file_gone_is_a_full_write(spliceable, copies):
    series, _ = spliceable
    os.remove(series.jser_fp)
    assert save_and_check(series, copies) == 0


@pytest.mark.parametrize("nth", [1, 3])
def test_a_save_that_fails_mid_copy_keeps_the_old_file(spliceable, monkeypatch, nth):
    series, notifier = spliceable
    good = open(series.jser_fp, "rb").read()
    index = series._jser_splice_index
    real = jser_splice._SectionWriter._copy
    calls = []

    def failing(self, f, offset, length, digest):
        calls.append(offset)
        if len(calls) == nth:
            f.write(b"partial")
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, f, offset, length, digest)

    monkeypatch.setattr(jser_splice._SectionWriter, "_copy", failing)
    with pytest.raises(OSError):
        series.saveJser()
    monkeypatch.undo()

    assert open(series.jser_fp, "rb").read() == good
    assert temp_files(series.jser_fp) == []
    assert "Save failed" in notifier.errors[0]
    # the old index still describes the old file, and the next save uses it
    assert series._jser_splice_index is index
    counted = []
    monkeypatch.setattr(
        jser_splice._SectionWriter, "_copy",
        lambda self, *a: counted.append(1) or real(self, *a),
    )
    series.save()
    expected = old_path_bytes(series)
    series.saveJser()
    assert open(series.jser_fp, "rb").read() == expected
    assert len(counted) == len(series.sections)


def test_a_pretty_save_records_no_index(spliceable, copies, monkeypatch):
    series, _ = spliceable
    monkeypatch.setenv(PRETTY_ENV_VAR, "1")
    series.save()
    expected = old_path_bytes(series)
    copies.clear()
    series.saveJser()
    assert open(series.jser_fp, "rb").read() == expected
    assert copies == []
    assert series._jser_splice_index is None

    monkeypatch.delenv(PRETTY_ENV_VAR)
    assert save_and_check(series, copies) == 0
    assert save_and_check(series, copies) == len(series.sections)


def test_the_stdlib_fallback_records_no_index(spliceable, copies):
    series, _ = spliceable
    lone_surrogate_in_last_section(series)
    series.save()
    expected = old_path_bytes(series)
    assert b'{"sections": [' in expected[:20]
    copies.clear()
    series.saveJser()
    assert open(series.jser_fp, "rb").read() == expected
    assert series._jser_splice_index is None
    assert save_and_check(series, copies) == 0


def test_the_source_file_is_closed_before_the_replace(spliceable, monkeypatch):
    """Windows refuses to replace a file that is open, so the copy must close it."""
    series, _ = spliceable
    opened_files = []
    real_open = open

    def tracking_open(fp, mode="r", *a, **k):
        f = real_open(fp, mode, *a, **k)
        if fp == series.jser_fp and "r" in mode:
            opened_files.append(f)
        return f

    real_replace = os.replace

    def checking_replace(src, dst):
        if dst == series.jser_fp:
            assert opened_files and all(f.closed for f in opened_files)
        return real_replace(src, dst)

    monkeypatch.setattr(jser_splice, "open", tracking_open, raising=False)
    monkeypatch.setattr(os, "replace", checking_replace)
    series.saveJser()
    assert opened_files
