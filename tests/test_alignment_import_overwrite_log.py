"""Importing an alignment over one that already exists is logged as an update.

`Series.importTransforms` already replaces a same-named alignment, and
`MultiImportAs.confirmOverwrite` already names the alignments about to be
replaced and asks first. What the log did not say was which of the two happened:
one line went out per import, `"Import alignments <names> from another series"`,
whether the names were new or were overwriting a colleague's earlier work. An
alignment quietly replaced on all 198 sections is the change a reader of the log
most needs to find, so the two cases now get separate events, `Import` for names
that did not exist and `Update` for names that did.

Three details of the implementation are what these tests actually guard.

The create/replace split is decided *before* the loop. `Section.save()` feeds
`section.tforms` back into `series.data` and `Series.alignments` reads that, so
after the first section saves, every imported name looks pre-existing and a
split computed afterwards reports the whole import as an update.

The log names the *target* alignment, not the source. The log describes this
series; a source name the user renamed on the way in names an alignment that
does not exist here. On an import that does not rename, the two are the same
string, which is why the common case reads exactly as it used to.

The events carry no object name. `LogSet.addLog` treats a `"Delete object"`
event as a sweep instruction and drops every earlier log sharing that object
name, so an alignment log filed under an object name would vanish the moment
someone deleted an object called that. `test_an_object_deletion_does_not_sweep`
pins that these survive.

The tests run against real series (two copies of the checked-in fixture) and
assert on `series.log_set.all_logs`, the same objects `Series.getFullHistory`
serializes.
"""

import pytest

from PyReconstruct.modules.datatypes import Series, Transform
from PyReconstruct.modules.backend.progress import NullProgressReporter


EXISTING = "LOCAL_d03"  # an alignment the fixture already has on every section
NEW = "from-other-series"


@pytest.fixture
def two_series(series_jser, tmp_path):
    """A destination series and a source series, both real, both writable.

    Copies of the same fixture, so their magnifications match and
    `importTransforms` takes its no-rescale path.
    """
    import shutil

    other_fp = tmp_path / "other.jser"
    shutil.copy(series_jser, other_fp)

    series = Series.openJser(str(series_jser))
    other = Series.openJser(str(other_fp))
    for s in (series, other):
        s.setProgressReporter(NullProgressReporter)
    yield series, other
    series.close()
    other.close()


def _write_distinct_alignment(other, name):
    """Put `name` on every section of `other`, a different transform each.

    Unique per section is what makes a wrong copy visible: an import that wrote
    the same transform everywhere could not tell a correct overwrite from one
    that put section 3's transform onto section 7.
    """
    written = {}
    for i, snum in enumerate(sorted(other.sections)):
        section = other.loadSection(snum)
        tform = Transform([1, 0, 2.25 + i, 0, 1, -1.5 - i])
        section.tforms[name] = tform
        section.save()
        written[snum] = tform.copy()
    other.save()
    return written


def _alignment_events(series):
    """The alignment import/update events, in the order they were logged."""
    return [
        log.event
        for log in series.log_set.all_logs
        if log.event.startswith(("Import alignments", "Update alignments"))
    ]


# --------------------------------------------------------------------------- #
# 1. the two events, separately
# --------------------------------------------------------------------------- #
def test_importing_a_new_alignment_logs_an_import_and_no_update(two_series):
    series, other = two_series
    _write_distinct_alignment(other, NEW)
    assert NEW not in series.alignments, "fixture must not already carry the name"

    series.importTransforms(other, [(NEW, NEW)])

    assert _alignment_events(series) == [
        f"Import alignments {NEW} from another series"
    ], "a name that did not exist is an import, and nothing else"


def test_replacing_an_existing_alignment_logs_an_update_and_no_import(two_series):
    """The half of the card that the log did not record at all."""
    series, other = two_series
    written = _write_distinct_alignment(other, EXISTING)
    assert EXISTING in series.alignments, "fixture must already carry the name"

    series.importTransforms(other, [(EXISTING, EXISTING)])

    assert _alignment_events(series) == [
        f"Update alignments {EXISTING} from another series"
    ], (
        "replacing an alignment must be logged as an update, not as an import "
        "of a name the series already had"
    )

    # and the replacement really happened, per section
    for snum in sorted(series.sections):
        assert series.loadSection(snum).tforms[EXISTING].equals(written[snum]), (
            f"section {snum} must carry the source series' transform"
        )


def test_a_mixed_import_logs_each_name_under_the_right_event(two_series):
    """One import, one replacement, one call: each name under its own event."""
    series, other = two_series
    _write_distinct_alignment(other, EXISTING)
    _write_distinct_alignment(other, NEW)

    series.importTransforms(other, [(EXISTING, EXISTING), (NEW, NEW)])

    assert _alignment_events(series) == [
        f"Import alignments {NEW} from another series",
        f"Update alignments {EXISTING} from another series",
    ], "the new name belongs to the import line and the taken name to the update line"


# --------------------------------------------------------------------------- #
# 2. the split is read before the loop, and names the target
# --------------------------------------------------------------------------- #
def test_a_new_name_is_still_an_import_after_the_first_section_saves(two_series):
    """`Section.save()` writes back into `series.data`, which `alignments` reads.

    A split computed after the loop sees the imported name on every section and
    reports a brand new alignment as an update. 198 sections save here, so the
    write-back has certainly happened by the time the log line is built.
    """
    series, other = two_series
    _write_distinct_alignment(other, NEW)

    series.importTransforms(other, [(NEW, NEW)])

    assert NEW in series.alignments, "the import must have landed in series.data"
    assert not any(e.startswith("Update alignments") for e in _alignment_events(series)), (
        "a name that did not exist before the loop is not an update, however "
        "much it exists afterwards"
    )


def test_the_log_names_the_target_alignment_not_the_source(two_series):
    """Renaming on the way in: the log has to name what this series now holds."""
    series, other = two_series
    _write_distinct_alignment(other, EXISTING)
    target = "colleagues-local"
    assert target not in series.alignments

    series.importTransforms(other, [(EXISTING, target)])

    assert _alignment_events(series) == [
        f"Import alignments {target} from another series"
    ], (
        f"the log must name {target}, the alignment this series now has, not "
        f"{EXISTING}, which is a name in the other series"
    )


def test_renaming_onto_a_taken_name_is_an_update_of_that_name(two_series):
    """Source and target both exist here, under different names."""
    series, other = two_series
    written = _write_distinct_alignment(other, NEW)  # source: new name in `other`
    assert EXISTING in series.alignments

    series.importTransforms(other, [(NEW, EXISTING)])

    assert _alignment_events(series) == [
        f"Update alignments {EXISTING} from another series"
    ], "the collision is decided by the target name, so this is an update"
    assert NEW not in series.alignments, "the source name is not imported as itself"
    for snum in sorted(series.sections):
        assert series.loadSection(snum).tforms[EXISTING].equals(written[snum])


# --------------------------------------------------------------------------- #
# 3. the case the card is really about: a replacement of an alignment in use
# --------------------------------------------------------------------------- #
def test_replacing_an_alignment_in_use_on_some_sections_and_not_others(two_series):
    """The source covers part of the series, and objects point at the alignment.

    Two things are in flight at once. The source series is missing sections, so
    `importTransforms` takes its `Transform.identity()` branch for those and its
    copy branch for the rest: the replacement is genuinely partial in what it
    writes. And the alignment is in use, both as `series.alignment` and as the
    per-object `alignment` attribute on objects whose traces sit on only some
    sections.

    What must hold afterwards: one update event naming the alignment once, no
    matter how many sections were involved or how they split; every section
    still agreeing on the set of alignment names, which `Series.alignments`
    checks by raising when they do not; and every reference to the alignment
    still naming something that exists, because the replacement reuses the key
    rather than adding a name and orphaning the old one.
    """
    series, other = two_series
    written = _write_distinct_alignment(other, EXISTING)

    # the source covers only part of the destination: drop the tail and a middle
    # stripe from `other.sections`, which is the dict importTransforms tests
    all_sections = sorted(series.sections)
    covered = set(all_sections[:100]) - {40, 41, 42}
    uncovered = set(all_sections) - covered
    for snum in uncovered:
        del other.sections[snum]
    assert covered and uncovered, "the split has to be a real split"

    # the alignment is in use: displayed, and assigned to two objects whose
    # traces do not span the same sections
    series.alignment = EXISTING
    series.setAttr("d03", "alignment", EXISTING)
    series.setAttr("d03p12", "alignment", EXISTING)

    series.importTransforms(other, [(EXISTING, EXISTING)])

    # one event, naming the alignment once
    assert _alignment_events(series) == [
        f"Update alignments {EXISTING} from another series"
    ], "a partial replacement is one update of one alignment, not one per section"

    # every section still agrees on the names, so nothing is half-imported
    assert EXISTING in series.alignments  # raises if the sections disagree

    # the two branches wrote what they each write
    for snum in sorted(covered):
        assert series.loadSection(snum).tforms[EXISTING].equals(written[snum]), (
            f"section {snum} is in the source and must take its transform"
        )
    for snum in sorted(uncovered):
        assert series.loadSection(snum).tforms[EXISTING].equals(
            Transform.identity()
        ), (
            f"section {snum} is not in the source and takes the blank transform"
        )

    # nothing that pointed at the alignment is left pointing at nothing
    assert series.alignment == EXISTING
    assert series.alignment in series.alignments
    for obj_name in ("d03", "d03p12"):
        assert series.getAttr(obj_name, "alignment") == EXISTING, (
            f"{obj_name}'s alignment assignment must survive the replacement"
        )
        assert series.getAttr(obj_name, "alignment") in series.alignments, (
            f"{obj_name} must not be left naming an alignment that is gone"
        )


# --------------------------------------------------------------------------- #
# 4. the LogSet trap, and the suppression flag
# --------------------------------------------------------------------------- #
def test_an_object_deletion_does_not_sweep_the_alignment_events(two_series):
    """`addLog` drops every earlier log carrying a deleted object's name.

    That sweep is why these events are filed with `obj_name=None`. Filing them
    under the alignment name would read better in an object column and would
    disappear the first time anyone deleted an object with that name.
    """
    series, other = two_series
    _write_distinct_alignment(other, EXISTING)
    series.importTransforms(other, [(EXISTING, EXISTING)])
    before = _alignment_events(series)
    assert before, "the import must have logged something to sweep"

    series.addLog(EXISTING, None, "Delete object")
    series.addLog("d03", None, "Delete object")

    assert _alignment_events(series) == before, (
        "deleting an object must not take the alignment history with it"
    )


def test_log_event_false_writes_no_alignment_event(two_series):
    series, other = two_series
    _write_distinct_alignment(other, EXISTING)

    series.importTransforms(other, [(EXISTING, EXISTING)], log_event=False)

    assert _alignment_events(series) == []
