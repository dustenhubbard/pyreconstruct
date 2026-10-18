"""The first save after an open splices too, and the file is still exact.

The open records where each section sits in the .jser it unpacks, when the
file holds exactly the working file's bytes (``OpenedJserIndex`` in
``jser_splice.py``). The first save then copies those sections, as later saves
copy from the file the last save wrote.

Every save here is compared with ``old_path_bytes``, the whole-document
reference, and counts its copies. A file this app saved is opened from a save
of each fixture: the fixtures themselves are older formats, so they open with
no index at all, and that is checked too.
"""

import os
import shutil

import pytest

from PyReconstruct.modules.constants import jser_splice
from PyReconstruct.modules.constants.jser_format import PRETTY_ENV_VAR
from PyReconstruct.modules.datatypes.series import _StreamedJser
from tests.test_jser_splice_save import first_traced_section, save_and_check
from tests.test_jser_streaming_save import (
    FIXTURES,
    RecordingNotifier,
    lone_surrogate_in_last_section,
    old_path_bytes,
    open_copy,
    reopen_at,
)


@pytest.fixture
def copies(monkeypatch):
    """Counts the sections each save copied (test_jser_splice_save's, owned
    here: importing a fixture by name trips the F811 gate)."""
    counted = []
    real = jser_splice._SectionWriter._copy

    def counting(self, f, offset, length, digest):
        counted.append(offset)
        return real(self, f, offset, length, digest)

    monkeypatch.setattr(jser_splice._SectionWriter, "_copy", counting)
    return counted


def close(series):
    series.leave_open = False
    series.close()


def reopened(series):
    """Close `series` (its hidden folder goes) and open its .jser again."""
    fp = series.jser_fp
    close(series)
    return reopen_at(fp)


def saved_once(tmp_path, source, copies):
    """`source` saved once by this build, closed, and opened again."""
    series = open_copy(tmp_path, source)
    save_and_check(series, copies)
    return reopened(series)


@pytest.fixture
def resaved(tmp_path, copies):
    """A file this build saved, just opened, with a notifier that records."""
    series = saved_once(tmp_path, FIXTURES[1], copies)
    series.setNotifier(RecordingNotifier())
    yield series
    close(series)


# ---------------------------------------------------------------------------
# the first save copies
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_the_first_save_after_an_open_copies_every_section(tmp_path, copies, source):
    series = saved_once(tmp_path, source, copies)
    assert len(series._jser_splice_index.ranges) == len(series.sections)
    before = open(series.jser_fp, "rb").read()

    assert save_and_check(series, copies) == len(series.sections)
    assert open(series.jser_fp, "rb").read() == before
    close(series)


@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_one_edit_before_the_first_save_encodes_only_its_section(
        tmp_path, copies, source):
    series = saved_once(tmp_path, source, copies)
    section = first_traced_section(series)
    trace = section.tracesAsList()[0]
    moved = trace.copy()
    moved.points = [(x + 0.5, y) for x, y in trace.points]
    section.removeTrace(trace, log_event=False)
    section.addTrace(moved, log_event=False)
    section.save()

    assert save_and_check(series, copies) == len(series.sections) - 1
    # and the index that save recorded is used by the next one
    assert save_and_check(series, copies) == len(series.sections)
    close(series)


def test_a_backup_save_first_copies_and_keeps_the_open_index(resaved, copies, tmp_path):
    series = resaved
    index = series._jser_splice_index
    backup = str(tmp_path / "backup.jser")
    series.save()
    expected = old_path_bytes(series)
    copies.clear()
    series.saveJser(backup)
    assert open(backup, "rb").read() == expected
    assert len(copies) == len(series.sections)
    assert series._jser_splice_index is index


# ---------------------------------------------------------------------------
# the file changed between the open and the save
# ---------------------------------------------------------------------------

def test_a_file_changed_on_disk_after_the_open_is_not_copied_from(resaved, copies):
    series = resaved
    with open(series.jser_fp, "ab") as f:
        f.write(b" ")
    assert not series._jser_splice_index.matchesDisk()
    assert save_and_check(series, copies) == 0


def test_a_file_edited_in_place_after_the_open_fails_the_checksum(resaved, copies):
    series = resaved
    st = os.stat(series.jser_fp)
    index = series._jser_splice_index
    offset = min(r[0] for r in index.ranges.values())
    with open(series.jser_fp, "r+b") as f:
        f.seek(offset + 1)
        b = f.read(1)
        f.seek(offset + 1)
        f.write(b"0" if b != b"0" else b"1")
    os.utime(series.jser_fp, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert index.matchesDisk()

    assert save_and_check(series, copies) == 1  # the one bad copy, then a full write


def test_a_file_moved_away_after_the_open_is_a_full_write(resaved, copies):
    series = resaved
    os.replace(series.jser_fp, series.jser_fp + ".moved")
    assert save_and_check(series, copies) == 0


def test_a_file_replaced_by_a_copy_of_itself_is_not_copied_from(resaved, copies):
    series = resaved
    shutil.copyfile(series.jser_fp, series.jser_fp + ".other")
    os.replace(series.jser_fp + ".other", series.jser_fp)
    assert save_and_check(series, copies) == 0


def test_a_file_changed_after_the_last_read_records_no_index(resaved):
    series = resaved
    source = _StreamedJser.open(series.jser_fp)
    try:
        for _ in source.sections():
            pass
        assert source.unchangedStat() is not None
        st = os.stat(series.jser_fp)
        os.utime(series.jser_fp, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        assert source.unchangedStat() is None
    finally:
        source.close()


# ---------------------------------------------------------------------------
# what the open does not record
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", FIXTURES, ids=os.path.basename)
def test_a_series_in_an_older_format_saves_in_full(tmp_path, copies, source):
    series = open_copy(tmp_path, source)
    assert series._jser_splice_index is None
    assert save_and_check(series, copies) == 0
    close(series)


def test_a_section_the_open_changes_is_encoded(resaved, copies):
    # One section saved unlocked: the open locks it, so its working file is
    # not the file's bytes. Every other section still copies.
    series = resaved
    fp = series.jser_fp
    close(series)
    data = open(fp, "rb").read()
    assert data.count(b'"align_locked":true') == len(series.sections)
    with open(fp, "wb") as f:
        f.write(data.replace(b'"align_locked":true', b'"align_locked":false', 1))
    series = reopen_at(fp)

    assert len(series._jser_splice_index.ranges) == len(series.sections) - 1
    assert save_and_check(series, copies) == len(series.sections) - 1
    close(series)


def test_a_file_the_stdlib_wrote_records_no_range(resaved, copies):
    # A section orjson refuses sends the whole file through the stdlib, with
    # other separators. None of it may be copied into an orjson save.
    series = resaved
    lone_surrogate_in_last_section(series)
    save_and_check(series, copies)
    assert b'{"sections": [' in open(series.jser_fp, "rb").read(20)
    series = reopened(series)

    assert series._jser_splice_index is None
    assert save_and_check(series, copies) == 0
    close(series)


def test_a_pretty_file_records_no_range(resaved, copies, monkeypatch):
    series = resaved
    monkeypatch.setenv(PRETTY_ENV_VAR, "1")
    save_and_check(series, copies)
    monkeypatch.delenv(PRETTY_ENV_VAR)
    series = reopened(series)

    assert series._jser_splice_index is None
    assert save_and_check(series, copies) == 0
    close(series)


def test_a_section_too_deep_for_the_writer_is_not_recorded():
    # orjson takes this dict alone but not wrapped as the writer wraps a
    # section, so a save would write the whole file through the stdlib.
    deep = 0
    for _ in range(252):
        deep = [deep]
    sd = {"deep": deep}
    raw = jser_splice.fast_dumps(sd)
    assert raw.startswith(b'{"deep":[[')  # the orjson form, not the stdlib's
    index = jser_splice.OpenedJserIndex("unused.jser")

    assert bytes(index.working(sd, (0, raw))) == raw
    assert index.ranges == {}


def test_the_working_file_bytes_are_unchanged():
    sd = {"src": "a.tif", "contours": {"é": [[[1.5, 2], [3, 4.25]]]}, "n": None}
    index = jser_splice.OpenedJserIndex("unused.jser")
    raw = jser_splice.fast_dumps(sd)

    assert bytes(index.working(sd, (7, raw))) == raw
    key = jser_splice.section_digest(raw)
    assert index.ranges == {key: (7, len(raw), key)}
    assert bytes(index.working(sd)) == raw  # no range: nothing more recorded
    assert len(index.ranges) == 1
