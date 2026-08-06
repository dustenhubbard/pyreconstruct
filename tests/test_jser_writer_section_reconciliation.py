"""``Series.saveJser`` writes the sections the index has, not the files it finds.

``self.sections`` is the series' index: section number to filename in the hidden
working directory. The writer used to ignore it and build the .jser from
``os.listdir(self.hidden_dir)`` instead, sizing the sections array from the index
but filling it from the listing, with no reconciliation in either direction.

The two disagree after an ordinary section delete, with no error to say so.
``deleteSections`` removes the file and the index entry, but the field is still
holding the deleted ``Section`` object: ``changeSection`` parks it in
``field.b_section`` through ``swapABsections``, and ``MainWindow.saveAllData``
writes ``b_section``'s file back into the hidden dir on every save, including the
``recreateTables`` call inside the delete action itself. So the file comes back
while the index entry stays gone, and the writer used to believe the file.

Measured on a copy of ``shapes1.jser`` (5 sections, 4 z-traces) before the fix:

* delete section 2, hold it, re-save it, ``saveJser``, reopen: section 2 is back,
  the z-trace points that crossed it are gone (``deleteSections`` repointed the
  z-traces and nothing put them back), and the log carries a "Delete section"
  event that did not stick. Silent.
* the same with section 4, the highest-numbered one: ``IndexError: list
  assignment index out of range`` out of the writer, uncaught, because only
  ``OSError`` was handled. The progress dialog stayed on screen, and the stale
  file stayed in the hidden dir, so **every later save failed the same way**.
* remove a section file without touching the index: the section was written as
  ``null``, the save reported success, and the atomic write replaced the last
  good .jser with one short a section.

Two changes, and the tests below are split the same way:

* ``saveJser`` reads exactly the files the index names. A numbered file the index
  does not have is not part of the series and does not reach the .jser. The
  reverse disagreement, an index entry whose file is gone or unreadable, refuses
  the save before writing anything, because the write is atomic and a .jser
  missing a section would replace the last copy that still had it.
* ``Section.save`` declines to rewrite a section the series no longer has, so the
  stale file is not usually created at all. That matters beyond the .jser: the
  hidden dir is also what the crash-recovery path in ``openJser`` scans, and it
  rebuilds the index from the listing.

Byte output for a series whose index and hidden dir agree is unchanged, which is
the invariant ``tests/test_jser_canonical_format.py`` exists to protect. Pinned
here too, from the other side: planting a stale file changes nothing about the
bytes.

No ``gui`` marker: these drive the datatypes directly and build no widgets.
"""

import json
import os
import shutil

import pytest

from PyReconstruct.modules.backend.notifier import NullNotifier
from PyReconstruct.modules.backend.progress import (
    NullProgressReporter,
    ProgressReporter,
)
from PyReconstruct.modules.datatypes import Series
from PyReconstruct.modules.datatypes.series import SeriesSaveError

FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dev", "assets", "checker", "files", "shapes1.jser",
)


def open_fixture(tmp_path, name="s"):
    """A real Series opened from a private copy of the checked-in fixture.

    ``shapes1.jser`` rather than ``conftest.py``'s ``real_series``: that one is
    ``class_series.jser``, which has 198 sections and no z-traces, and the
    z-traces are what make a resurrected section visibly inconsistent.
    """
    if not os.path.exists(FIXTURE):  # pragma: no cover - repo layout guard
        pytest.skip(f"fixture missing: {FIXTURE}")
    fp = str(tmp_path / f"{name}.jser")
    shutil.copyfile(FIXTURE, fp)
    return reopen_at(fp)


def reopen_at(fp):
    """Open a .jser headlessly, with the Qt seams filled by the null adapters."""
    series = Series.openJser(fp, progress=NullProgressReporter)
    series.setProgressReporter(NullProgressReporter)
    series.setNotifier(NullNotifier())
    return series


@pytest.fixture
def series(tmp_path):
    s = open_fixture(tmp_path)
    yield s
    if os.path.isdir(s.hidden_dir):
        s.leave_open = False
        s.close()


def reopened(series):
    """Close ``series`` and open its .jser again, from the file itself.

    ``close`` removes the hidden dir, so the reopen parses the .jser rather than
    taking ``openJser``'s hidden-dir recovery path. That is the question these
    tests are asking: what is in the file.
    """
    fp = series.jser_fp
    series.close()
    return reopen_at(fp)


def numbered_files(series):
    """snum -> filename, for every numbered file actually in the hidden dir."""
    found = {}
    for filename in os.listdir(series.hidden_dir):
        if "." not in filename:  # the timer file
            continue
        ext = filename[filename.rfind(".") + 1:]
        if ext.isnumeric():
            found[int(ext)] = filename
    return found


def plant_stale_file(series, snum):
    """Write a numbered section file the index does not have.

    Copied from a section that does exist, so it is a valid section document:
    the writer has no content-based way to tell it is not wanted, which is the
    point. This goes around ``Section.save`` on purpose, so that these tests
    exercise the writer whatever the rest of the app does.
    """
    source = series.sections[min(series.sections)]
    dst = os.path.join(series.hidden_dir, f"{series.name}.{snum}")
    shutil.copyfile(os.path.join(series.hidden_dir, source), dst)
    assert snum not in series.sections, "a planted file must not be in the index"
    return dst


def jser_sections(fp):
    """The raw ``sections`` array from a .jser on disk, without opening a Series."""
    with open(fp, "rb") as f:
        return json.load(f)["sections"]


def ztrace_sections(series):
    """z-trace name -> the sorted section numbers its points sit on."""
    return {
        name: sorted({pt[2] for pt in ztrace.points})
        for name, ztrace in series.ztraces.items()
    }


class RecordingReporter(ProgressReporter):
    """A reporter that remembers whether it was finished. One per save."""

    created = []

    def __init__(self, text="", cancel=True):
        super().__init__(text, cancel)
        self.finished = False
        RecordingReporter.created.append(self)

    def set_progress(self, percent):
        pass

    def was_canceled(self):
        return False

    def finish(self):
        self.finished = True


@pytest.fixture
def reporters():
    """Collect the reporters a save creates, and clear the class-level list."""
    RecordingReporter.created = []
    yield RecordingReporter.created
    RecordingReporter.created = []


# --------------------------------------------------------------------------
# the premise
# --------------------------------------------------------------------------

def test_the_fixture_has_five_sections_and_ztraces_across_them(series):
    """Otherwise the assertions below would hold vacuously."""
    assert sorted(series.sections) == [0, 1, 2, 3, 4]
    per_ztrace = ztrace_sections(series)
    assert per_ztrace, "fixture has no z-traces"
    for name, snums in per_ztrace.items():
        assert snums == [0, 1, 2, 3, 4], f"z-trace {name!r} does not cross every section"


def test_the_field_gesture_leaves_a_section_object_pointing_at_a_deleted_file(series):
    """The setup the resurrection needs is real: a live Section outlives its entry.

    ``Section.filepath`` is resolved from ``series.sections`` at construction, so
    the object the field holds still names the file ``deleteSections`` removed.
    """
    held = series.loadSection(2)
    expected_fp = os.path.join(series.hidden_dir, "s.2")
    assert held.filepath == expected_fp
    series.deleteSections([2])
    assert 2 not in series.sections
    assert not os.path.isfile(expected_fp)
    assert held.filepath == expected_fp, "the held object still names the deleted file"


# --------------------------------------------------------------------------
# a deleted section stays deleted, through the gesture that used to resurrect it
# --------------------------------------------------------------------------

@pytest.mark.parametrize("snum", [2, 4], ids=["interior", "highest-numbered"])
def test_a_deleted_section_stays_deleted_when_the_field_re_saves_it(series, snum):
    """Delete, then let ``saveAllData`` write the held section, then save."""
    held = series.loadSection(snum)   # what changeSection parks in b_section
    series.deleteSections([snum])
    held.save(update_series_data=False)  # what MainWindow.saveAllData does with it

    series.saveJser()

    after = reopened(series)
    try:
        assert snum not in after.sections
        assert sorted(after.sections) == [n for n in [0, 1, 2, 3, 4] if n != snum]
        on_disk = jser_sections(after.jser_fp)
        if snum < max(after.sections):  # an interior deletion leaves a null hole
            assert on_disk[snum] is None
        else:                           # deleting the last one shortens the array
            assert len(on_disk) == snum
    finally:
        after.leave_open = False
        after.close()


def test_the_ztraces_and_the_log_agree_with_the_deleted_section(series):
    """The resurrection was not just a stray section, it was an inconsistent one.

    Before the fix the section came back while the z-trace points on it stayed
    deleted, and the log kept the deletion event. Three records of the same
    series, two of them saying the section was gone.
    """
    held = series.loadSection(2)
    series.deleteSections([2])
    held.save(update_series_data=False)
    series.saveJser()

    after = reopened(series)
    try:
        assert 2 not in after.sections
        for name, snums in ztrace_sections(after).items():
            assert 2 not in snums, f"z-trace {name!r} still has a point on section 2"
        assert "Delete section" in str(after.getFullHistory())
    finally:
        after.leave_open = False
        after.close()


def test_deleting_the_highest_numbered_section_does_not_wedge_later_saves(series):
    """This one used to raise, and then raise on every save after it.

    The stale file's number was past the end of an array sized from the index, so
    ``IndexError`` came out of the writer. Only ``OSError`` was caught, so it
    reached the excepthook as a crash, and nothing removed the file that caused
    it: the next save failed identically, and the one after that.
    """
    held = series.loadSection(4)
    series.deleteSections([4])
    held.save(update_series_data=False)

    series.saveJser()   # used to raise IndexError
    series.saveJser()   # ... and to keep raising it
    series.saveJser()

    after = reopened(series)
    try:
        assert sorted(after.sections) == [0, 1, 2, 3]
    finally:
        after.leave_open = False
        after.close()


def test_section_save_does_not_rewrite_a_section_the_series_has_deleted(series):
    """The stale file is not created in the first place.

    Belt as well as braces: the writer ignores the file, and the hidden dir is
    also what ``openJser``'s recovery path scans after a crash, where ignoring is
    not an option because there is no index to compare against.
    """
    held = series.loadSection(2)
    series.deleteSections([2])

    held.save(update_series_data=False)

    assert sorted(numbered_files(series)) == [0, 1, 3, 4]
    assert not os.path.isfile(os.path.join(series.hidden_dir, "s.2"))


# --------------------------------------------------------------------------
# the writer on its own: a stale file it is handed anyway
# --------------------------------------------------------------------------

@pytest.mark.parametrize("snum", [2, 4], ids=["interior", "past-the-last-section"])
def test_a_numbered_file_the_index_does_not_have_is_not_written(series, snum):
    """The writer's own guarantee, independent of who put the file there."""
    series.deleteSections([snum])
    plant_stale_file(series, snum)

    series.saveJser()

    assert snum in numbered_files(series), \
        "the stale file should still be on disk; this test is about ignoring it"
    after = reopened(series)
    try:
        assert snum not in after.sections
    finally:
        after.leave_open = False
        after.close()


def test_a_stale_file_far_past_the_last_section_is_ignored(series):
    """The array is sized from the index, so an arbitrary number cannot overflow it."""
    plant_stale_file(series, 4096)

    series.saveJser()

    assert len(jser_sections(series.jser_fp)) == 5


def test_a_stale_file_does_not_change_the_saved_bytes(series):
    """Reconciliation makes the file invisible, not merely harmless."""
    series.saveJser()
    clean = open(series.jser_fp, "rb").read()

    plant_stale_file(series, 9)
    series.saveJser()

    assert open(series.jser_fp, "rb").read() == clean


# --------------------------------------------------------------------------
# the reverse disagreement: an index entry whose file is gone
# --------------------------------------------------------------------------

def test_a_missing_section_file_refuses_the_save_and_keeps_the_good_jser(series):
    """The worst of the three: silent, permanent, and delivered atomically.

    A .jser missing a section used to replace the .jser that had it. The section
    is unrecoverable from the hidden dir either way, so the file on disk is the
    only copy left and the save must not touch it.
    """
    series.saveJser()
    good = open(series.jser_fp, "rb").read()

    os.remove(os.path.join(series.hidden_dir, series.sections[2]))

    with pytest.raises(SeriesSaveError):
        series.saveJser()

    assert open(series.jser_fp, "rb").read() == good
    assert jser_sections(series.jser_fp)[2] is not None, \
        "the section the writer could not save is still in the file on disk"


def test_the_refusal_names_the_section_and_the_directory(series):
    """A refusal the user cannot act on is only half a fix."""
    series.saveJser()
    os.remove(os.path.join(series.hidden_dir, series.sections[3]))

    with pytest.raises(SeriesSaveError) as excinfo:
        series.saveJser()

    message = str(excinfo.value)
    assert "3" in message
    assert series.hidden_dir in message


def test_an_unreadable_section_file_refuses_the_save(series):
    """Same reasoning as a missing one, and it used to be an uncaught ValueError."""
    series.saveJser()
    good = open(series.jser_fp, "rb").read()

    with open(os.path.join(series.hidden_dir, series.sections[1]), "wb") as f:
        f.write(b"{not json")

    with pytest.raises(SeriesSaveError):
        series.saveJser()

    assert open(series.jser_fp, "rb").read() == good


def test_a_series_with_no_sections_refuses_the_save(series):
    """``max()`` on an empty index used to raise ``ValueError`` from the writer.

    Sizing the array is not the reason to refuse. A .jser with an empty sections
    array is one ``openJser`` rejects, so writing it would replace a working file
    with an unopenable one.
    """
    series.saveJser()
    good = open(series.jser_fp, "rb").read()

    series.deleteSections(list(series.sections))

    with pytest.raises(SeriesSaveError):
        series.saveJser()

    assert open(series.jser_fp, "rb").read() == good


# --------------------------------------------------------------------------
# the progress dialog
# --------------------------------------------------------------------------

def test_a_refused_save_finishes_the_progress_reporter(series, reporters):
    """The uncaught raise used to leave the progress dialog on screen.

    ``reporter.finish()`` was the last statement of the function, so any
    exception skipped it, and a ``QProgressDialog`` that is never taken to 100%
    is never dismissed. Note this is deliberately not ``ProgressReporter``'s
    context-manager behavior, which leaves a failed operation's reporter where it
    stopped: here the reporter is a modal dialog over the main window.
    """
    series.setProgressReporter(RecordingReporter)
    with open(os.path.join(series.hidden_dir, series.sections[1]), "wb") as f:
        f.write(b"{not json")

    with pytest.raises(SeriesSaveError):
        series.saveJser()

    assert len(reporters) == 1
    assert reporters[0].finished


def test_a_save_refused_before_it_starts_shows_no_progress_at_all(series, reporters):
    """The two pre-flight checks are cheap stats, so nothing needs to be shown."""
    series.setProgressReporter(RecordingReporter)
    os.remove(os.path.join(series.hidden_dir, series.sections[2]))

    with pytest.raises(SeriesSaveError):
        series.saveJser()

    assert reporters == []


# --------------------------------------------------------------------------
# a correct save is unchanged
# --------------------------------------------------------------------------

def test_two_saves_of_an_unchanged_series_are_byte_identical(series):
    """The invariant the writer's canonical ordering exists to provide.

    Restructuring the loop must not disturb it. Covered from the other direction
    in ``tests/test_jser_canonical_format.py``; asserted here because this change
    is the one that rewrote the loop.
    """
    series.saveJser()
    first = open(series.jser_fp, "rb").read()
    series.saveJser()

    assert open(series.jser_fp, "rb").read() == first


def test_a_plain_save_round_trips_the_sections_the_ztraces_and_the_log(series):
    """The .ser and the log used to be found by scanning the listing too."""
    before_ztraces = ztrace_sections(series)
    before_history = str(series.getFullHistory())
    series.saveJser()

    after = reopened(series)
    try:
        assert sorted(after.sections) == [0, 1, 2, 3, 4]
        assert ztrace_sections(after) == before_ztraces
        assert str(after.getFullHistory()) == before_history
    finally:
        after.leave_open = False
        after.close()


def test_a_new_log_event_survives_the_save(series):
    """``log_set`` is appended to the existing log, and the order used to depend
    on which of the two files ``os.listdir`` happened to return first."""
    series.addLog(None, 1, "Probe event")
    series.saveJser()

    after = reopened(series)
    try:
        history = str(after.getFullHistory())
        assert "Probe event" in history
    finally:
        after.leave_open = False
        after.close()
