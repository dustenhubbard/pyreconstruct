"""Regression tests: importing alignments from another series must be undoable.

`Series.importTransforms` declares a `series_states` parameter and the only
caller that has one to give (`MainWindow.importFromSeries`, the
"alignments" branch of the import-from-series dialog) passes it. The method
then dropped it on the floor: its `enumerateSections` call was made with no
`series_states=`, so `SeriesIterator` never called `SeriesStates.addState()`
and never called `SectionStates.addState()` per section. The import rewrote
`section.tforms` on every section in the series and saved each one with no
undo state recorded anywhere, which made a series-wide, destructive change
permanent.

Every sibling that touches transforms series-wide already threads the states
through: `Series.modifyAlignments` and the `.txt` importer
(`modules/backend/func/import_transforms.importTransforms`) both pass
`series_states=series_states, breakable=False`, and
`SectionStates.undoState`/`redoState` already restore `section.tforms` from
the stored `FieldState`. So the missing piece was the argument, not the
machinery.

`breakable=False` matters as much as the argument does. A breakable series
state can be dissolved into independent per-section undos
(`SeriesStates.undoSection` removes it from `self.undos` and undoes one
section), which for an alignment import would leave the series with the
imported alignment present on some sections and absent on others. That state
is not just wrong, it raises from `Series.alignments` ("Sections have
differently named alignments"). An alignment import is all-or-nothing, so the
state has to be unbreakable, exactly as the `.txt` importer's is.

The tests run against real series (two copies of the checked-in fixture) and a
real `SeriesStates`, and assert on transform values reloaded from disk, not on
call counts: the point of the fix is that the numbers come back.
"""

import pytest

from PyReconstruct.modules.datatypes import Series, Transform
from PyReconstruct.modules.backend.func.state_manager import SeriesStates
from PyReconstruct.modules.backend.progress import NullProgressReporter


NEW_ALIGNMENT = "from-other-series"


@pytest.fixture
def two_series(series_jser, tmp_path):
    """A destination series and a source series, both real, both writable.

    Copies of the same fixture, so their magnifications match and
    `importTransforms` takes its no-rescale path (the rescale path mutates the
    *source* section's transform in place, which is a separate concern).
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


def _give_other_a_distinct_alignment(other, name):
    """Put an alignment on every section of `other`, unique per section.

    Unique per section is what makes a partial restore visible: a test that
    imported the same transform everywhere could not tell a correct undo from
    one that restored section 3's transform onto section 7.
    """
    written = {}
    for i, snum in enumerate(sorted(other.sections)):
        section = other.loadSection(snum)
        tform = Transform([1, 0, 1.5 + i, 0, 1, -0.75 - i])
        section.tforms[name] = tform
        section.save()
        written[snum] = tform.copy()
    other.save()
    return written


def _snapshot(series):
    """alignment name -> Transform, per section, read back from disk."""
    return {
        snum: {
            name: tform.copy()
            for name, tform in series.loadSection(snum).tforms.items()
        }
        for snum in sorted(series.sections)
    }


def _assert_tforms_equal(got, expected, message):
    assert set(got) == set(expected), message
    for snum in expected:
        assert set(got[snum]) == set(expected[snum]), (
            f"{message} (section {snum}: alignment names differ, "
            f"{sorted(got[snum])} != {sorted(expected[snum])})"
        )
        for name, tform in expected[snum].items():
            assert got[snum][name].equals(tform), (
                f"{message} (section {snum}, alignment {name})"
            )


def test_import_alignments_records_an_undoable_series_state(two_series):
    """Importing a new alignment leaves a series undo that removes it again."""
    series, other = two_series
    written = _give_other_a_distinct_alignment(other, NEW_ALIGNMENT)
    before = _snapshot(series)
    assert all(
        NEW_ALIGNMENT not in tforms for tforms in before.values()
    ), "fixture must not already carry the imported alignment name"

    series_states = SeriesStates(series)
    series.importTransforms(
        other, [(NEW_ALIGNMENT, NEW_ALIGNMENT)], series_states
    )

    # the import happened, with each section getting its own source transform
    after = _snapshot(series)
    for snum in before:
        assert after[snum][NEW_ALIGNMENT].equals(written[snum]), (
            f"section {snum} must receive the source series' transform"
        )

    can_3D, _, _ = series_states.canUndo()
    assert can_3D, "an alignment import must leave an undoable series state"

    series_states.undoState()

    _assert_tforms_equal(
        _snapshot(series), before,
        "undo must restore every section's transforms exactly",
    )
    assert NEW_ALIGNMENT not in series.alignments, (
        "undo must remove the imported alignment from the series"
    )


def test_import_alignments_undo_restores_an_overwritten_alignment(two_series):
    """Importing onto an existing alignment name is the destructive case.

    The import-from-series dialog lets the user name the imported alignment
    after one that already exists, which replaces that alignment's transform on
    every section. Undo has to give the old numbers back, not merely drop the
    key.
    """
    series, other = two_series
    _give_other_a_distinct_alignment(other, NEW_ALIGNMENT)

    # give the destination its own alignment under the name being imported to
    existing = {}
    for i, snum in enumerate(sorted(series.sections)):
        section = series.loadSection(snum)
        tform = Transform([1, 0, -10.0 - i, 0, 1, 20.0 + i])
        section.tforms[NEW_ALIGNMENT] = tform
        section.save()
        existing[snum] = tform.copy()
    series.save()

    before = _snapshot(series)
    series_states = SeriesStates(series)
    series.importTransforms(
        other, [(NEW_ALIGNMENT, NEW_ALIGNMENT)], series_states
    )

    # sanity: the pre-existing transforms really were overwritten
    for snum, tform in existing.items():
        assert not series.loadSection(snum).tforms[NEW_ALIGNMENT].equals(tform), (
            f"section {snum}'s alignment must have been overwritten"
        )

    series_states.undoState()

    _assert_tforms_equal(
        _snapshot(series), before,
        "undo must restore the overwritten alignment's original transforms",
    )


def test_import_alignments_redo_reapplies_the_import(two_series):
    """Undo then redo puts the imported transforms back.

    A one-way undo would be its own trap: the user who undoes to look at the old
    alignment and then wants the import back must not have to run it again.
    """
    series, other = two_series
    written = _give_other_a_distinct_alignment(other, NEW_ALIGNMENT)
    before = _snapshot(series)

    series_states = SeriesStates(series)
    series.importTransforms(
        other, [(NEW_ALIGNMENT, NEW_ALIGNMENT)], series_states
    )
    imported = _snapshot(series)
    series_states.undoState()
    _assert_tforms_equal(_snapshot(series), before, "undo must restore")

    can_3D, _, _ = series_states.canUndo(redo=True)
    assert can_3D, "a redo must be available after the undo"
    series_states.undoState(redo=True)

    _assert_tforms_equal(
        _snapshot(series), imported,
        "redo must re-apply the imported transforms",
    )
    for snum, tform in written.items():
        assert series.loadSection(snum).tforms[NEW_ALIGNMENT].equals(tform)


def test_import_alignments_undo_is_not_breakable_into_one_section(two_series):
    """A 2D (single-section) undo must not be able to dissolve the import.

    Undoing one section of an alignment import would leave that section without
    the alignment the rest of the series has, which `Series.alignments` treats
    as corrupt. `breakable=False` is what forbids it.
    """
    series, other = two_series
    _give_other_a_distinct_alignment(other, NEW_ALIGNMENT)

    series.current_section = sorted(series.sections)[0]
    series_states = SeriesStates(series)
    series.importTransforms(
        other, [(NEW_ALIGNMENT, NEW_ALIGNMENT)], series_states
    )

    can_3D, can_2D, _ = series_states.canUndo()
    assert can_3D, "the series-wide undo must be available"
    assert not can_2D, (
        "a single-section undo must not be offered for a series-wide "
        "alignment import"
    )


def test_import_alignments_without_series_states_still_works(two_series):
    """The no-GUI path (`series_states=None`) must be unaffected."""
    series, other = two_series
    written = _give_other_a_distinct_alignment(other, NEW_ALIGNMENT)

    series.importTransforms(other, [(NEW_ALIGNMENT, NEW_ALIGNMENT)])

    for snum, tform in written.items():
        assert series.loadSection(snum).tforms[NEW_ALIGNMENT].equals(tform)
