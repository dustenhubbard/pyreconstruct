"""``Series.deleteSections`` must be all-or-nothing about its input.

The operation is irreversible by design: the section list warns, the caller saves
everything, and then files are removed. So its failure mode matters more than
most. Before this change the body was a bare loop over ``section_numbers`` that
did ``os.remove`` and ``del self.sections[snum]`` per entry, with the z-trace
repointing after the loop. Two consequences:

* a repeated section number raised ``KeyError`` on the second copy, after the
  first copy had already removed the file and the index entry, and before the
  z-trace loop ran at all
* a section number the series does not have raised at whatever point in the list
  it appeared, so everything before it in the list was already gone

Measured on a copy of ``shapes1.jser`` (5 sections, 4 z-traces),
``deleteSections([2, 2])``: ``KeyError: 2``, the file ``s.2`` deleted,
``series.sections`` down to ``[0, 1, 3, 4]``, and all four z-traces still holding
a point on section 2. That last part is the damage. A z-trace point on a section
that does not exist is not a cosmetic inconsistency, it is a point the field
cannot draw and the next save writes back.

Repeats are the caller's real-world failure mode, not a hypothetical one. The
section list is a six-column, cell-selectable table, so one selected row used to
yield the same section number five times, once per selectable column, and
``SectionTableWidget.deleteSections`` passed that straight through.
``DataTable.selectedRows`` de-duplicates by row now, and
``tests/test_section_list_real_widget.py`` covers that. These tests are about the
other half: the datatype no longer depends on being called correctly to avoid
half-deleting a series.

The assertions here are on the resulting series state, not on which exception
type comes out. The exception was never the defect.

No ``gui`` marker: these drive the datatype directly and build no widgets.
"""

import os
import shutil

import pytest

from PyReconstruct.modules.backend.progress import NullProgressReporter
from PyReconstruct.modules.datatypes import Series

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dev", "assets", "checker", "files", "shapes1.jser",
)


def open_fixture(tmp_path, name="s"):
    """A real Series opened from a private copy of the checked-in fixture.

    ``shapes1.jser`` rather than the ``real_series`` fixture in ``conftest.py``:
    that one is ``class_series.jser`` (198 sections) and has no z-traces, and the
    z-traces are what make a half-deleted series visible.
    """
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    fp = str(tmp_path / f"{name}.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    return series


@pytest.fixture
def series(tmp_path):
    s = open_fixture(tmp_path)
    yield s
    s.close()


def section_files(series):
    """snum -> filename, for every numbered file actually in the hidden dir."""
    found = {}
    for filename in os.listdir(series.hidden_dir):
        if "." not in filename:  # the timer file
            continue
        ext = filename[filename.rfind(".") + 1:]
        if ext.isnumeric():
            found[int(ext)] = filename
    return found


def ztrace_sections(series):
    """z-trace name -> the sorted section numbers its points sit on."""
    return {
        name: sorted({pt[2] for pt in ztrace.points})
        for name, ztrace in series.ztraces.items()
    }


def assert_consistent(series, expected_sections):
    """The series holds exactly these sections, everywhere it records them."""
    assert sorted(series.sections) == sorted(expected_sections)
    assert sorted(section_files(series)) == sorted(expected_sections), \
        "the files on disk and series.sections disagree"
    for name, snums in ztrace_sections(series).items():
        assert set(snums) <= set(expected_sections), (
            f"z-trace {name!r} has points on {sorted(set(snums) - set(expected_sections))}, "
            f"which the series no longer has"
        )


# --------------------------------------------------------------------------
# the premise
# --------------------------------------------------------------------------

def test_the_fixture_has_ztraces_on_every_section(series):
    """Otherwise the interesting assertion below would hold vacuously."""
    assert sorted(series.sections) == [0, 1, 2, 3, 4]
    per_ztrace = ztrace_sections(series)
    assert per_ztrace, "fixture has no z-traces"
    for name, snums in per_ztrace.items():
        assert 2 in snums, f"z-trace {name!r} has no point on section 2"


def test_a_plain_delete_still_works(series):
    """The honest path, unchanged."""
    series.deleteSections([2])
    assert_consistent(series, [0, 1, 3, 4])


def test_a_multi_section_delete_still_works(series):
    series.deleteSections([1, 3])
    assert_consistent(series, [0, 2, 4])


# --------------------------------------------------------------------------
# the defect: a repeated section number
# --------------------------------------------------------------------------

def test_a_repeated_section_number_deletes_it_once(series):
    """The regression test. Before: ``KeyError: 2`` with the series half done."""
    series.deleteSections([2, 2])
    assert_consistent(series, [0, 1, 3, 4])


def test_a_row_selections_worth_of_repeats_deletes_one_section(series):
    """The shape the caller actually produced: one entry per selected cell.

    Six columns, five of them selectable, so ``[2, 2, 2, 2, 2]``.
    """
    series.deleteSections([2, 2, 2, 2, 2])
    assert_consistent(series, [0, 1, 3, 4])


def test_repeats_do_not_stop_the_ztraces_being_repointed(series):
    """The part the old raise skipped entirely.

    The z-trace loop sits after the delete loop, so a mid-loop raise never
    reached it. This is the assertion that distinguishes "does not crash" from
    "leaves a coherent series".
    """
    before = ztrace_sections(series)
    assert all(2 in snums for snums in before.values())

    series.deleteSections([3, 3, 1])

    for name, snums in ztrace_sections(series).items():
        assert 1 not in snums and 3 not in snums, \
            f"z-trace {name!r} still has points on a deleted section: {snums}"
        assert 2 in snums, f"z-trace {name!r} lost a point it should have kept"


def logged_deletions(series):
    """Every section number the log records as deleted.

    ``LogSet.addLog`` merges repeat calls for the same event into one ``Log``
    whose ``section_ranges`` accumulate, so the log has to be read as coverage
    rather than as a list of entries.
    """
    covered = set()
    for log in series.log_set.all_logs:
        if log.event == "Delete section":
            for low, high in log.section_ranges:
                covered.update(range(low, high + 1))
    return covered


def test_the_log_records_the_sections_that_were_actually_deleted(series):
    """The log is the only record that the deletion happened, so it has to match.

    Read as coverage, not as a count: the repeats collapse before they reach the
    log, but ``addSection`` would have absorbed them anyway, so a count would
    pass whatever the input.
    """
    series.deleteSections([3, 0, 3, 1])

    assert logged_deletions(series) == {0, 1, 3}
    assert_consistent(series, [2, 4])


# --------------------------------------------------------------------------
# the defect: a section number the series does not have
# --------------------------------------------------------------------------

def test_an_unknown_section_number_deletes_nothing(series):
    """Still an error, but now raised before the series has been touched.

    Skipping it silently was the other option and is worse: passing a section
    number the series does not have is a caller defect, and the last one took a
    while to find.
    """
    with pytest.raises(KeyError):
        series.deleteSections([1, 99])

    assert_consistent(series, [0, 1, 2, 3, 4])
    assert not logged_deletions(series)


def test_an_unknown_section_number_is_named_in_the_error(series):
    with pytest.raises(KeyError, match="99"):
        series.deleteSections([99])


def test_an_empty_request_is_a_no_op(series):
    series.deleteSections([])
    assert_consistent(series, [0, 1, 2, 3, 4])


# --------------------------------------------------------------------------
# it survives a save and reopen
# --------------------------------------------------------------------------

def test_the_result_survives_a_save_and_reopen(series):
    """A repeated-input delete leaves a series that reopens clean.

    The failure this replaces was persistent: the z-trace points on the deleted
    section were written back out by the next save.
    """
    series.deleteSections([4, 4])
    fp = series.jser_fp
    series.saveJser()
    series.close()

    reopened = Series.openJser(fp, progress=NullProgressReporter)
    try:
        reopened.setProgressReporter(NullProgressReporter)
        assert_consistent(reopened, [0, 1, 2, 3])
    finally:
        reopened.close()
