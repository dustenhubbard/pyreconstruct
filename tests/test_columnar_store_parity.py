"""Parity between the columnar store and the object model, on real sections.

The store in `datatypes/columnar_store.py` is a parallel representation with no
consumers: nothing in the application reads it and no call site is rewired. So
the only thing that can be wrong with it is that it does not hold what the object
model holds, and that is what this module measures.

WHAT PARITY IS DEFINED AGAINST, AND WHY IT MATTERS THAT IT IS NOT `getList`
--------------------------------------------------------------------------
`Trace.getList` rounds coordinates with `round(p[0], 7)` while `trace.points` in
memory is unrounded. A parity suite written against a `getList` round trip
compares two lossy things and passes while proving nothing about either.

Every coordinate assertion here is against `trace.points`, the in-memory value,
and `test_the_store_is_on_the_unrounded_side_of_the_seven_dp_rounding` makes the
distinction observable rather than merely stated. That test matters on this
fixture specifically: every coordinate in the checked-in series is already exact
at 7 decimal places (measured: 20,105 of 20,105), so on the real material alone
the two definitions of parity are indistinguishable and a suite that got this
wrong would still be green.

WHAT THE FIXTURE SERIES CANNOT EXERCISE
---------------------------------------
Measured on `PyReconstruct/assets/checker/files/class_series.jser` at
`d92408d3`: 198 sections, 221 contours, 232 traces, 9 contours holding more than
one trace, and

  * **no tagged trace at all**, so the tags column gets no real material;
  * **no negative and no hidden trace**, same;
  * two of the nine `fill_mode` pairs, `("none", "none")` and
    `("solid", "unselected")`;
  * no coordinate needing more than 7 decimal places.

Those gaps are covered twice, deliberately. Tests below mutate real traces on
real sections, so the mutation entry points get covered against real material.
And `tests/fixtures/parity_series.jser` -- a checked-in synthetic series added
because review-246 found the real fixture cannot distinguish the parity
definitions that matter -- carries the missing domains in the *file itself*:
positional (list) contour rows, coordinates inexact at 7 decimal places,
tagged/negative/hidden traces, and single-point traces the load path screens.
The synthetic tests say which gap they close; a raw-file census pins that the
fixture keeps carrying all of them.

The coordinate backing is `SegmentedCoordinates`, and it is the decided one:
the paired undo-snapshot measurement found the per-section packed alternative
0.32% dearer on the workload it was hypothesized to win, the A1 open-pass
split leans the same way, and the losing backing was deleted rather than kept
as an option. The store still reaches its backing only through the five-method
interface, so these tests exercise the seam a future layout would arrive
behind.
"""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.columnar_store import (
    BOOL_ATTRIBUTES,
    FILL_MODE_CODES,
    FILL_MODE_OVERFLOW,
    SectionColumns,
    SegmentedCoordinates,
    TraceView,
)

class StubIssuer():
    """A deterministic stand-in for `trace_id.TraceIDIssuer`.

    The store takes its issuer by injection, so these tests do not depend on the
    real one existing. That is deliberate: the layout and the identity plumbing
    are separate concerns and neither should be able to break the other's tests.
    """

    def __init__(self):
        self.count = 0

    def issue(self):
        self.count += 1
        return f"stub{self.count:07d}"


@pytest.fixture
def loaded_sections(real_series):
    """Every section of the fixture series that holds at least one trace.

    Returned as a list of live `Section` objects. The fixture series is small
    enough (198 sections, 232 traces) to hold at once; a test that walks a real
    autoseg series would have to hold one at a time as the application does.
    """
    sections = []
    for snum in sorted(real_series.sections):
        section = real_series.loadSection(snum)
        if section.contours:
            sections.append(section)
    assert sections, "the fixture series has no populated sections"
    return sections


## The checked-in synthetic series. It exists because the real fixture cannot
## prove the parity this suite claims (review-246): every one of its 40,210
## coordinate values is exact at 7 dp, none of its traces is tagged, negative
## or hidden, and its contour rows are legacy dicts. This file carries, in the
## raw bytes rather than through an in-test mutation: positional (list) contour
## rows, coordinates inexact at 7 dp, tagged/negative/hidden traces, and
## single-point traces (which the load path screens out).
SYNTHETIC_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity_series.jser"


@pytest.fixture
def synthetic_sections(tmp_path):
    """Every populated section of the synthetic series, from a writable copy.

    A copy for the same reason `series_jser` copies: `Series.openJser` builds
    a hidden working directory beside the file it is given.
    """
    from PyReconstruct.modules.datatypes import Series

    destination = tmp_path / "parity_series.jser"
    shutil.copy(SYNTHETIC_FIXTURE, destination)
    series = Series.openJser(str(destination))
    sections = [series.loadSection(n) for n in sorted(series.sections)]
    yield [section for section in sections if section.contours]
    series.close()


def _assert_trace_parity(store, row, trace):
    """Every column of one row against every attribute of one trace."""
    assert store.getName(row) == trace.name

    ## Coordinates, against the IN-MEMORY floats, exactly. Not approximately:
    ## float64 in and float64 out is bit-identical or it is a defect.
    stored = store.getCoordinates(row)
    assert stored.dtype == np.float64
    assert stored.shape == (len(trace.points), 2)
    assert store.getPoints(row) == [tuple(p) for p in trace.points]
    assert np.array_equal(stored, np.array(trace.points, dtype=np.float64))

    assert list(store.getColor(row)) == list(trace.color)
    assert all(isinstance(v, int) for v in store.getColor(row))
    assert store.getFlag(row, "closed") == trace.closed
    assert store.getFlag(row, "negative") == trace.negative
    assert store.getFlag(row, "hidden") == trace.hidden
    assert list(store.getFillMode(row)) == list(trace.fill_mode)
    assert store.getTags(row) == trace.tags


# --- the whole fixture series -------------------------------------------------


def test_every_trace_of_every_real_section_round_trips(loaded_sections):
    """The headline parity assertion, over all 232 traces of the real series.

    Contour names, within-contour order, and every column of every row.
    """
    n_traces = 0
    for section in loaded_sections:
        store = SectionColumns.fromSection(section)
        ## Non-empty contours only, which is the set `Section.getDict` writes:
        ## an empty `Contour` holds no rows, so it has no index entry. On this
        ## fixture the two sets are identical, because `Section.updateJSON`
        ## removes empty contours on unpack; the distinction is stated so a
        ## series that carried one would not read as a parity failure.
        assert store.contourNames() == sorted(
            (n for n, c in section.contours.items() if len(c)), key=str
        )
        for name in store.contourNames():
            rows = store.rowsForContour(name)
            traces = list(section.contours[name])
            assert len(rows) == len(traces)
            for row, trace in zip(rows, traces):
                _assert_trace_parity(store, row, trace)
                n_traces += 1
    assert n_traces > 200, f"expected the fixture's ~232 traces, walked {n_traces}"


def test_materializing_rebuilds_traces_equal_to_the_originals(loaded_sections):
    """`materializeTrace` against `Trace.isSameTrace`, which compares name, color
    and points, plus the four attributes it does not compare.

    `isSameTrace` is the codebase's own value-equality predicate for a trace, and
    it exists because `Trace` defines no `__eq__`. Using it here rather than a
    hand-rolled comparison means the parity bar is the one the application
    already uses.
    """
    for section in loaded_sections:
        store = SectionColumns.fromSection(section)
        for name in store.contourNames():
            for row, original in zip(store.rowsForContour(name),
                                     section.contours[name]):
                rebuilt = store.materializeTrace(row)
                assert isinstance(rebuilt, Trace)
                assert rebuilt.isSameTrace(original)
                assert rebuilt.negative == original.negative
                assert rebuilt.hidden == original.hidden
                assert list(rebuilt.fill_mode) == list(original.fill_mode)
                assert rebuilt.tags == original.tags


def test_materialized_contours_match_the_sections_own_dict(loaded_sections):
    """`materializeContours` against `Section.contours`, contour by contour.

    Built through `Contour(name, traces)`, the checking constructor, so a name
    that failed to survive the round trip raises inside the store rather than
    producing a quietly mismatched contour.
    """
    for section in loaded_sections:
        store = SectionColumns.fromSection(section)
        rebuilt = store.materializeContours()
        assert sorted(rebuilt, key=str) == sorted(section.contours, key=str)
        for name, contour in rebuilt.items():
            assert contour.name == name
            assert len(contour) == len(section.contours[name])
            for a, b in zip(contour, section.contours[name]):
                assert a.isSameTrace(b)


def test_the_stored_row_reserializes_to_the_same_bytes(loaded_sections):
    """A second, independent parity check: `getList` of a materialized trace
    equals `getList` of the original.

    This is the weaker check of the two and is here on purpose, as the *other*
    direction. It proves the store loses nothing the file format carries, while
    the coordinate assertions above prove it loses nothing the file format
    itself drops. Neither alone is sufficient: this one would pass for a store
    that rounded to 7 dp on the way in.
    """
    for section in loaded_sections:
        store = SectionColumns.fromSection(section)
        for name in store.contourNames():
            for row, original in zip(store.rowsForContour(name),
                                     section.contours[name]):
                assert (store.materializeTrace(row).getList(include_name=False)
                        == original.getList(include_name=False))


# --- the rounding seam -------------------------------------------------------


def test_the_store_is_on_the_unrounded_side_of_the_seven_dp_rounding(loaded_sections):
    """The store keeps a coordinate that `getList` would throw away.

    Written because the real material cannot show this: every one of the 20,105
    coordinates in the fixture series is already exact at 7 decimal places, so a
    store that silently rounded would pass every other test in this file. A real
    trace on a real section is given a coordinate with twelve decimal places, and
    then both sides are asked what they kept.
    """
    section = loaded_sections[0]
    name = sorted(section.contours, key=str)[0]
    trace = section.contours[name][0]

    precise = 5.0123456789012
    assert round(precise, 7) != precise, "pick a value the rounding actually moves"
    trace.points = [(precise, 6.0987654321098)] + list(trace.points[1:])

    store = SectionColumns.fromSection(section)
    row = store.rowsForContour(name)[0]

    ## The store kept the full value.
    assert store.getCoordinates(row)[0][0] == precise
    assert store.getPoints(row)[0][0] == precise

    ## The serialized row did not, which is what makes the distinction real
    ## rather than a matter of phrasing.
    assert trace.getList(include_name=False)[0][0] == round(precise, 7)
    assert trace.getList(include_name=False)[0][0] != precise

    ## And a trace rebuilt from the store still holds the full value, so the
    ## in-memory round trip through the store is lossless.
    assert store.materializeTrace(row).points[0][0] == precise


# --- the synthetic series: the domains the real fixture cannot carry ---------


def _synthetic_rows():
    """Every 8-field contour row of the checked-in synthetic file, raw."""
    data = json.loads(SYNTHETIC_FIXTURE.read_text())
    return [
        row
        for section in data["sections"] if section
        for contour in section["contours"].values()
        for row in contour
    ]


def test_the_synthetic_file_itself_carries_what_the_real_series_cannot():
    """The raw-file census, so the fixture cannot silently lose its point.

    Asserted against the bytes on disk, not against anything loaded: the rows
    are positional lists (the current format, so no legacy dict migration runs
    over them), at least one coordinate is inexact at 7 decimal places, and
    tagged, negative, hidden and single-point traces are all present, and more
    than one fill mode is used. If an edit to the fixture drops any of these,
    the parity tests below quietly stop discriminating, and this census is what
    makes that loud instead.
    """
    rows = _synthetic_rows()
    assert rows
    assert all(type(row) is list and len(row) == 8 for row in rows)

    coordinates = [value for row in rows for value in row[0] + row[1]]
    assert any(round(value, 7) != value for value in coordinates)

    assert any(row[7] for row in rows), "no tagged trace in the fixture"
    assert any(row[4] for row in rows), "no negative trace in the fixture"
    assert any(row[5] for row in rows), "no hidden trace in the fixture"
    assert any(len(row[0]) == 1 for row in rows), "no single-point trace"

    ## The fill mode is a (mode, condition) pair and the parity walk compares it
    ## column by column, so a fixture that carried one pair everywhere would let
    ## a store that dropped the column entirely still pass. Three pairs are
    ## checked in (none/none x6, solid/unselected, transparent/selected), which
    ## is the number the PR body claims, so the count is asserted rather than
    ## the exact pairs: a re-cut is free to change which three, not free to
    ## flatten the variety (review-248 N01).
    fill_modes = {tuple(row[6]) for row in rows}
    assert len(fill_modes) >= 3, (
        f"the fixture carries only {len(fill_modes)} fill-mode pair(s), "
        f"{sorted(fill_modes)}; the parity walk stops discriminating on that "
        "column when they are all the same"
    )


def test_every_trace_of_every_synthetic_section_round_trips(synthetic_sections):
    """The headline parity walk, over material the real series cannot supply.

    Same assertions as the real-series walk -- every column of every row,
    within-contour order, materialization equality and `getList` byte
    equality -- but here the tagged/negative/hidden values and the inexact
    coordinates arrived from a checked-in file, not from an in-test mutation,
    so this is the walk that can actually prove object-model parity.
    """
    tagged = negative = hidden = 0
    for section in synthetic_sections:
        store = SectionColumns.fromSection(section)
        assert store.contourNames() == sorted(
            (n for n, c in section.contours.items() if len(c)), key=str
        )
        for name in store.contourNames():
            rows = store.rowsForContour(name)
            traces = list(section.contours[name])
            assert len(rows) == len(traces)
            for row, trace in zip(rows, traces):
                _assert_trace_parity(store, row, trace)
                rebuilt = store.materializeTrace(row)
                assert rebuilt.isSameTrace(trace)
                assert (rebuilt.getList(include_name=False)
                        == trace.getList(include_name=False))
                tagged += bool(trace.tags)
                negative += trace.negative
                hidden += trace.hidden
    assert tagged and negative and hidden, (
        "the synthetic material lost the attribute domain it exists to carry"
    )


def test_synthetic_coordinates_stay_unrounded_from_file_to_store(synthetic_sections):
    """The two parity definitions, distinguished on checked-in material.

    The real series cannot tell a silently rounding store from a faithful one
    (all 40,210 values exact at 7 dp), which is review-246's finding against
    this suite's own fixture. Here coordinates that a `getList` round trip
    would move arrive from the file, survive `Trace.fromList` verbatim, and
    must come back out of the store bit-identical -- so a store that rounded
    on the way in fails on the fixture alone, with nothing mutated in-test.
    """
    inexact = 0
    for section in synthetic_sections:
        store = SectionColumns.fromSection(section)
        for name in store.contourNames():
            for row, trace in zip(store.rowsForContour(name),
                                  section.contours[name]):
                for stored, held in zip(store.getPoints(row), trace.points):
                    for stored_value, held_value in zip(stored, held):
                        if round(held_value, 7) != held_value:
                            inexact += 1
                        assert stored_value == held_value
    assert inexact >= 4, (
        f"only {inexact} coordinates discriminate the rounding seam; the "
        f"fixture is supposed to carry them in quantity"
    )


def test_single_point_traces_are_screened_and_the_store_matches_the_model(
        synthetic_sections):
    """Parity is with the object model, not with the file.

    The fixture carries two single-point rows: one beside a valid trace in
    `spine01` (section 0), and one as the only row of `lone` (section 1).
    `Section.updateJSON`/`Section.__init__` screen both out, taking the `lone`
    contour with them, so a store built from the section must hold the
    screened counts and never resurrect what the load path dropped.
    """
    raw = json.loads(SYNTHETIC_FIXTURE.read_text())
    assert len(raw["sections"][0]["contours"]["spine01"]) == 2
    assert len(raw["sections"][1]["contours"]["lone"]) == 1

    by_number = {section.n: section for section in synthetic_sections}

    store = SectionColumns.fromSection(by_number[0])
    assert len(store.rowsForContour("spine01")) == 1
    assert len(by_number[0].contours["spine01"]) == 1

    store = SectionColumns.fromSection(by_number[1])
    assert "lone" not in store.contourNames()
    assert "lone" not in by_number[1].contours
    assert all(len(store.getPoints(row)) > 1
               for name in store.contourNames()
               for row in store.rowsForContour(name))


# --- the attribute domain the fixture does not reach -------------------------


def test_tags_negative_and_hidden_round_trip_on_a_real_trace(loaded_sections):
    """The fixture series has no tagged, negative or hidden trace.

    Measured, not assumed: 0 of 232 for each. So real traces on a real section
    are given those attributes here, rather than leaving three columns
    untested against a series that cannot exercise them.
    """
    section = loaded_sections[0]
    name = sorted(section.contours, key=str)[0]
    trace = section.contours[name][0]
    trace.tags = {"beta", "alpha", "checked"}
    trace.negative = True
    trace.hidden = True

    store = SectionColumns.fromSection(section)
    row = store.rowsForContour(name)[0]
    assert store.getTags(row) == {"alpha", "beta", "checked"}
    assert store.getFlag(row, "negative") is True
    assert store.getFlag(row, "hidden") is True
    _assert_trace_parity(store, row, trace)


def test_the_tags_column_cannot_be_mutated_through_a_value_it_handed_out(loaded_sections):
    """`getTags` returns a fresh set, so a caller cannot reach into the column.

    `Contour.copy()` gives each copied trace its own `tags` set for the same
    reason, and `series_data.TraceData` aliasing a trace's tags is a known live
    dependency the store must not extend into itself.
    """
    section = loaded_sections[0]
    name = sorted(section.contours, key=str)[0]
    section.contours[name][0].tags = {"alpha"}
    store = SectionColumns.fromSection(section)
    row = store.rowsForContour(name)[0]

    handed_out = store.getTags(row)
    handed_out.add("injected")
    assert store.getTags(row) == {"alpha"}


def test_every_fill_mode_in_the_vocabulary_round_trips():
    """All nine `convertMode` pairs, against a fixture that carries two of them."""
    store = SectionColumns(1)
    for style, condition in FILL_MODE_CODES:
        row = store.appendRow(
            name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3],
            fill_mode=(style, condition),
        )
        assert store.getFillMode(row) == [style, condition]
    assert store.fillModeColumn.dtype == np.uint8
    assert not (store.fillModeColumn == FILL_MODE_OVERFLOW).any()


def test_a_fill_mode_outside_the_vocabulary_is_kept_rather_than_raising():
    """A `.jser` can carry a pair the vocabulary does not have.

    `Trace.fromList` assigns `fill_mode` verbatim from the file, so a hand-edited
    or foreign file can hold anything. A coded column needs a defined fallback or
    it turns that into a `KeyError` on open, which would be a new way to fail to
    load a series that loads today.
    """
    store = SectionColumns(1)
    row = store.appendRow(
        name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3],
        fill_mode=("hatched", "always"),
    )
    assert int(store.fillModeColumn[row]) == FILL_MODE_OVERFLOW
    assert store.getFillMode(row) == ["hatched", "always"]
    assert store.materializeTrace(row).fill_mode == ["hatched", "always"]


# --- the types that a save would trip over -----------------------------------


def test_materialized_attributes_are_native_python_types():
    """A `numpy` scalar reaching `Trace.getList` would break a save.

    `getList` output goes to `json.dump`, which cannot serialize `numpy.bool_` or
    `numpy.uint8`. They compare equal to their Python counterparts, so a store
    that handed them out would pass a value comparison and fail at the point of
    writing the file. Checked by type, and then by actually serializing.
    """
    store = SectionColumns(1)
    row = store.appendRow(
        name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[10, 20, 30],
        closed=False, negative=True, hidden=True, tags={"a"},
    )
    trace = store.materializeTrace(row)
    assert type(trace.closed) is bool
    assert type(trace.negative) is bool
    assert type(trace.hidden) is bool
    assert all(type(v) is int for v in trace.color)
    assert all(type(v) is float for p in trace.points for v in p)
    json.dumps(trace.getList(include_name=False))


def test_freeze_releases_the_growth_slack_without_changing_a_value():
    """A snapshot must not be measured as costing its allocator slack.

    The columns grow by amortized doubling, so a store holding two rows can
    hold buffers for sixty-four. That is the right trade while a store is
    being built and the wrong one for a snapshot, which is immutable after
    construction. Found while adapting
    the undo-growth harness, where the slack would have dominated the figure the
    measurement exists to produce.
    """
    store = SectionColumns(1)
    rows = [store.appendRow(name="axon",
                            points=[(float(i), 0.0), (float(i), 1.0)],
                            color=[i, i, i], tags={"t"})
            for i in range(3)]

    before = [(store.getPoints(r), store.getColor(r), store.getTags(r)) for r in rows]
    generation = store.generation
    allocated = _allocated_bytes(store)

    store.freeze()

    assert _allocated_bytes(store) < allocated, (
        "freeze() released nothing, so a snapshot would carry its growth slack"
    )
    assert store.generation == generation, "freeze() is not a mutation"
    assert [(store.getPoints(r), store.getColor(r), store.getTags(r))
            for r in rows] == before

    ## Appending after a freeze is allowed and simply grows the columns again.
    added = store.appendRow(name="axon", points=[(9.0, 9.0), (9.0, 8.0)], color=[1, 2, 3])
    assert store.getPoints(added) == [(9.0, 9.0), (9.0, 8.0)]
    assert store.rowsForContour("axon")[-1] == added


def _allocated_bytes(store):
    """Bytes the store's numeric buffers hold, slack included.

    Reaches past the public surface on purpose: the slack is invisible through
    `colorColumn` and friends, which return views over the live prefix, and the
    slack is the whole subject of the test above.
    """
    total = store._colors._array.nbytes + store._fill_modes._array.nbytes
    total += sum(c._array.nbytes for c in store._bools.values())
    backing = store.coordinateBacking
    total += sum(a.nbytes for a in backing._arrays if a is not None)
    return total


def test_the_columns_are_the_dtypes_the_layout_claims():
    store = SectionColumns(1)
    store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    assert store.colorColumn.dtype == np.uint8
    assert store.fillModeColumn.dtype == np.uint8
    for attribute in BOOL_ATTRIBUTES:
        assert store.flagColumn(attribute).dtype == np.bool_
    assert store.getCoordinates(0).dtype == np.float64


# --- layout invariants -------------------------------------------------------


## The method surface a coordinate backing has, in the order the module docstring
## lists it. `SectionColumns` calls exactly these five on whatever it is handed
## (`get` at columnar_store.py:414, `freeze` 490, `append` 570, `release` 599,
## `set` 606), so a class carrying them is a backing whatever it is called.
##
## `totalPoints` was a sixth member of this tuple and is not one any more. Its
## only consumer anywhere in the tree was `PackedCoordinates.deadPoints`, which
## this PR deleted, so pinning it here would have made the regression net defend
## dead code -- against this PR's own stated principle that code nobody consumes
## is unreleased scope (review-246 F06). The property went with the tuple entry,
## in this commit (review-248 F02).
COORDINATE_BACKING_SURFACE = ("append", "get", "set", "release", "freeze")

## How much of that surface makes a class a backing for the purpose of the pin
## below. Not all five, because a partial reimplementation is still a second
## backing and would walk straight through an all-five bar. Three, because the
## namespace has a wide gap to sit in: measured over `vars(columnar_store)`, an
## exhaustive census of all five classes it holds -- `SegmentedCoordinates`
## carries 5, `_NumericColumn` 2 (`append`, `freeze`), `SectionColumns` 1
## (`freeze`), the imported `Contour` 1 (`append`) and `Trace` 0. So the bar is
## in open space, not on a boundary, and `test_the_backing_scan_sits_in_a_gap`
## pins that.
BACKING_SURFACE_THRESHOLD = 3


def _backingsInNamespace(module) -> list:
    """Every class reachable in `module`'s namespace shaped like a backing.

    By surface, deliberately not by name -- see the test below for why.

    Deduplicated on identity first. One class bound under two names -- a
    deprecation alias such as `LegacyCoordinates = SegmentedCoordinates` --
    introduces no second backing, but a plain scan of `vars()` would return it
    twice and fail the pin below with a message asserting a second backing
    exists when it does not (review-248 F03). Names are not the unit here; the
    objects are.
    """
    unique = {
        id(obj): obj for obj in vars(module).values()
        if isinstance(obj, type)
        and sum(hasattr(obj, m) for m in COORDINATE_BACKING_SURFACE)
        >= BACKING_SURFACE_THRESHOLD
    }
    return sorted(unique.values(), key=lambda cls: cls.__name__)


def test_the_decided_backing_is_segmented_and_the_module_carries_no_other():
    """The backing decision, pinned so reverting it is loud.

    Design question 1 (one coordinate array per section versus one per trace)
    was decided for the segmented pole after the paired undo-snapshot
    measurement found `PackedCoordinates` 0.32% dearer on the workload it was
    hypothesized to win, with A1's open-pass split leaning the same way. The
    loser was deleted, not parked: a second backing nobody consumes is
    unreleased scope (review-246 F06), and this test is what makes
    reintroducing it a decision rather than a drift.

    PINNED ON THE SURFACE, NOT ON THE NAME
    --------------------------------------
    The `hasattr` line below is a tripwire for the one drift it can see: a
    revert, or the old class cherry-picked back under its old name. It is not
    the property. On its own it enforced a *name* -- the identical deleted
    class re-inserted as `ArenaCoordinates` passed this module 35/35
    (review-wave-b F01) -- while this test's own name promises the module
    carries no other backing at all. So the property is asserted directly: no
    class reachable in the module's namespace but `SegmentedCoordinates` has a
    coordinate backing's shape.

    Scanning the namespace rather than the classes defined here is deliberate:
    a backing defined elsewhere and imported in is still a second backing this
    module carries, and the scan sees it. What it does not reach is a backing
    that is never named in this module and is injected through
    `SectionColumns(coordinates=...)`; the first assertion below pins what the
    store constructs when nobody injects anything, and injection is what that
    parameter is for.
    """
    import PyReconstruct.modules.datatypes.columnar_store as columnar_store

    assert type(SectionColumns(1).coordinateBacking) is SegmentedCoordinates
    assert not hasattr(columnar_store, "PackedCoordinates")
    assert _backingsInNamespace(columnar_store) == [SegmentedCoordinates], (
        "the module's namespace carries a class other than SegmentedCoordinates "
        "with a coordinate backing's shape; one backing was the decision, so a "
        "second one is a decision to re-open and not a refactor"
    )


def test_the_backing_scan_sits_in_a_gap():
    """What the scan above counts, so its threshold is a measurement.

    A surface scan is only as good as its bar, and a bar nobody can see the
    margin around is a bar the next person will not trust. This records the
    margin: the decided backing carries the whole surface, and nothing else in
    the namespace carries even the threshold. If a future class lands between
    these two facts, one of these assertions breaks and the bar gets re-decided
    on purpose rather than drifting.
    """
    import PyReconstruct.modules.datatypes.columnar_store as columnar_store

    counted = {
        cls.__name__: sum(hasattr(cls, m) for m in COORDINATE_BACKING_SURFACE)
        for cls in vars(columnar_store).values()
        if isinstance(cls, type)
    }
    assert counted["SegmentedCoordinates"] == len(COORDINATE_BACKING_SURFACE)
    others = {name: n for name, n in counted.items() if name != "SegmentedCoordinates"}
    assert others, "the scan found no other class at all, so it proves nothing"
    assert max(others.values()) < BACKING_SURFACE_THRESHOLD, (
        f"a class now sits at the scan's threshold: {others}"
    )


def test_the_store_is_exported_through_the_datatypes_package():
    """The deferred `datatypes/__init__.py` export, taken in this PR.

    Neither wave-B PR could take it without colliding with the other, so it
    was parked for the PR that decides the backing (2026-08-03 realign, Part
    2, wave B, order 1). Identity is asserted, not just importability: the
    package must hand out the same objects this suite tests.
    """
    from PyReconstruct.modules import datatypes

    assert datatypes.SectionColumns is SectionColumns
    assert datatypes.SegmentedCoordinates is SegmentedCoordinates


def test_rows_are_append_only_and_row_numbers_are_never_reused():
    """A removed row's number retires with it.

    This is what lets the per-contour index and any later operation log refer to
    a row by number without a generation of its own. It is also why nothing here
    ever performs a mid-array insert.
    """
    store = SectionColumns(1)
    first = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    second = store.appendRow(name="axon", points=[(2.0, 2.0), (3.0, 3.0)], color=[1, 2, 3])
    assert [first, second] == [0, 1]

    store.removeRow(first)
    third = store.appendRow(name="axon", points=[(4.0, 4.0), (5.0, 5.0)], color=[1, 2, 3])
    assert third == 2
    assert store.rowCount == 3
    assert len(store) == 2
    assert store.rowsForContour("axon") == [second, third]
    with pytest.raises(IndexError):
        store.getCoordinates(first)


def test_within_contour_order_survives_every_operation():
    """Within-contour trace order is semantically significant.

    `Contour.importTraces` walks `self[i]` against `other[i]` positionally and
    stops at the first non-overlap, so a layout that reordered a contour would
    change import behavior on real data. Appends land at the end and a removal
    closes the gap without disturbing the survivors.
    """
    store = SectionColumns(1)
    rows = [store.appendRow(name="axon", points=[(float(i), 0.0), (float(i), 1.0)],
                            color=[1, 2, 3]) for i in range(5)]
    assert store.rowsForContour("axon") == rows

    store.removeRow(rows[2])
    assert store.rowsForContour("axon") == [rows[0], rows[1], rows[3], rows[4]]

    added = store.appendRow(name="axon", points=[(9.0, 0.0), (9.0, 1.0)], color=[1, 2, 3])
    assert store.rowsForContour("axon")[-1] == added


def test_a_name_entering_the_store_is_normalized_the_way_a_trace_name_is():
    """`Trace.name`'s setter runs `normalizeObjectName`, and so must the store.

    A comma in an object name breaks the log's comma-delimited field parsing,
    which is why the normalization exists and why `Trace.name` and
    `Section.updateJSON` share one function. A store that skipped it would let a
    name written through the store diverge from the same name written through a
    `Trace`.
    """
    store = SectionColumns(1)
    row = store.appendRow(name="two words,and a comma",
                          points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    expected = Trace("two words,and a comma", (1, 2, 3)).name
    assert store.getName(row) == expected
    assert store.rowsForContour("two words,and a comma") == [row]
    assert store.contourNames() == [expected]


def test_a_rename_moves_the_row_between_contour_indices():
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    store.setAttribute(row, "name", "dendrite01")
    assert store.rowsForContour("axon") == []
    assert store.rowsForContour("dendrite01") == [row]
    assert store.contourNames() == ["dendrite01"]
    assert store.getAllModifiedNames() >= {"axon", "dendrite01"}


def test_a_copied_row_does_not_share_coordinate_memory_with_its_source():
    """The aliasing class the coordinate coercion exists to close.

    `np.asarray` of an existing float64 array returns the same memory, so a row
    copied from another row would share its coordinates and a later in-place
    write to one would silently change the other. That is a data-loss shape, not
    a slowness shape.
    """
    store = SectionColumns(1)
    source = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    copied = store.duplicateRow(source)

    ## Checked immediately, before any write. Checking it after a write does NOT
    ## discriminate: the backing replaces a row's array on a length-changing
    ## write, so two rows that started out sharing memory look independent
    ## afterward. The invariant is that they never shared it.
    assert not np.shares_memory(store.getCoordinates(source),
                                store.getCoordinates(copied))

    ## And the same for a store built twice from one section: the second store's
    ## rows must not be views into the first store's arrays.
    store.setCoordinates(copied, [(7.0, 7.0), (8.0, 8.0)])
    assert store.getPoints(source) == [(0.0, 0.0), (1.0, 1.0)]
    assert store.getPoints(copied) == [(7.0, 7.0), (8.0, 8.0)]


def test_a_store_does_not_alias_the_arrays_of_a_store_built_beside_it():
    """Two stores built from one section hold independent coordinates.

    The same coercion invariant, reached by the path a caller is most likely to
    take: build a store, build another, and write through one of them.
    """
    trace = Trace("axon", [1, 2, 3])
    trace.points = [(0.0, 0.0), (1.0, 1.0)]

    class StubSection():
        n = 3
        contours = {"axon": [trace]}

    first = SectionColumns.fromSection(StubSection())
    second = SectionColumns.fromSection(StubSection())
    assert not np.shares_memory(first.getCoordinates(0), second.getCoordinates(0))

    ## And neither of them aliases the live trace's own point list.
    first.getCoordinates(0)[0, 0] = 99.0
    assert trace.points[0] == (0.0, 0.0)
    assert second.getPoints(0)[0] == (0.0, 0.0)


# --- the transform key set, across a rebuild from a file ---------------------


def test_a_section_rebuilt_from_a_files_key_set_still_carries_no_alignment(
        loaded_sections):
    """The `TransformsDict` hazard a coordinates-and-attributes suite cannot see.

    The object model always carries the `no-alignment` transform because
    `TransformsDict.__init__` seeds it unconditionally (`section.py`), while
    the file's key set never carries it: `Section.getDict` drops it on save
    and `Section.updateJSON` deletes it on unpack. So a consumer that rebuilt
    a section's transforms from the file's key set through a plain dict would
    lose `no-alignment` on every section, and every other test in this file
    would pass clean over the loss -- which is why the 2026-08-03 realign
    requires this pin before any consumer parity claim is accepted (Part 2,
    wave B, order 2).

    Every section here IS a rebuild from a file's key set: `Section.__init__`
    walks `section_data["tforms"]` into a fresh `TransformsDict`. Both halves
    are asserted -- the file side carries no `no-alignment` key (so the test
    cannot pass vacuously) and the rebuilt side carries it on every section,
    as the identity, through the exact walk the load path runs.
    """
    from PyReconstruct.modules.datatypes import Transform
    from PyReconstruct.modules.datatypes.section import TransformsDict

    identity = Transform.identity()
    for section in loaded_sections:
        serialized = section.getDict()["tforms"]

        ## The file's key set does not carry it, and a plain-dict rebuild of
        ## that key set loses it. This is the half that makes the pin real.
        assert "no-alignment" not in serialized
        assert "no-alignment" not in dict(serialized)

        ## The load path's exact walk over the file's key set.
        rebuilt = TransformsDict()
        for alignment in serialized:
            rebuilt[alignment] = Transform(serialized[alignment])
        assert "no-alignment" in rebuilt
        assert rebuilt["no-alignment"].equals(identity)

        ## And the section this test was handed, itself rebuilt from a file,
        ## carries it on every alignment surface a consumer would read.
        assert "no-alignment" in section.tforms
        assert section.tforms["no-alignment"].equals(identity)


# --- the generation counter, beside the name tracking ------------------------


def test_every_mutation_entry_point_bumps_the_generation():
    """All six of them, enumerated in the module docstring so a later operation
    log can attach at the same points."""
    store = SectionColumns(1)
    generations = [store.generation]

    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    generations.append(store.generation)
    store.setCoordinates(row, [(2.0, 2.0), (3.0, 3.0)])
    generations.append(store.generation)
    store.setAttribute(row, "color", [9, 9, 9])
    generations.append(store.generation)
    store.setTags(row, {"a"})
    generations.append(store.generation)
    store.noteTransformChange()
    generations.append(store.generation)
    store.removeRow(row)
    generations.append(store.generation)

    assert generations == sorted(generations)
    assert len(set(generations)) == len(generations), (
        f"a mutation did not bump the generation: {generations}"
    )


def test_a_transform_change_bumps_the_counter_without_touching_a_row():
    """An alignment change rewrites every trace's rendered geometry while every
    section file stays byte-identical.

    A counter that did not move here would let a cache keyed on it serve stale
    geometry, which is a measured bug class rather than a hypothetical one. No
    row changed, so no name enters the modified set, and that asymmetry is the
    thing to notice: the counter and the name set answer different questions.
    """
    store = SectionColumns(1)
    store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    store.clearTracking()

    before = store.generation
    store.noteTransformChange()
    assert store.generation > before
    assert store.getAllModifiedNames() == set()


def test_clear_tracking_empties_the_names_and_leaves_the_counter_alone():
    """The lifetime asymmetry, asserted rather than described.

    The existing stale-render family is caused by two mechanisms with different
    lifetimes: the table manager empties the tracking lists through
    `clearTracking()` and the render cache does not know it happened. A counter
    reset here would reproduce that bug in a new costume, so the counter is
    monotonic and nothing resets it.
    """
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    store.setTags(row, {"a"})
    assert store.getAllModifiedNames() == {"axon"}

    before = store.generation
    store.clearTracking()
    assert store.getAllModifiedNames() == set()
    assert store.added_rows == []
    assert store.removed_rows == []
    assert store.modified_contours == set()
    assert store.generation == before, (
        "clearTracking() must not reset the generation counter"
    )


def test_the_name_set_reports_added_removed_and_modified_alike():
    """`getAllModifiedNames`'s contract, which four consumer roles need and a
    scalar counter cannot answer, including `SectionStates.addState`, which uses
    it as the scope of the undo snapshot."""
    store = SectionColumns(1)
    kept = store.appendRow(name="kept", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    doomed = store.appendRow(name="doomed", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    touched = store.appendRow(name="touched", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    store.clearTracking()

    added = store.appendRow(name="added", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    store.removeRow(doomed)
    store.setCoordinates(touched, [(5.0, 5.0), (6.0, 6.0)])

    assert store.getAllModifiedNames() == {"added", "doomed", "touched"}
    assert store.added_rows == [added]
    assert store.removed_rows == [doomed]
    assert store.modified_contours == {"touched"}
    assert store.getName(kept) == "kept"


def test_building_from_a_section_leaves_the_tracking_clean_but_the_counter_moved():
    """Loading is not an edit.

    `fromSection` clears the tracking it generated, because a freshly built store
    has no user modifications to report. It does not rewind the counter, because
    a cache built against generation 0 must not be told that a store holding 232
    rows is still at generation 0.
    """
    store = SectionColumns(7)
    store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])

    class StubSection():
        n = 7
        contours = {"axon": [Trace("axon", [1, 2, 3])]}

    StubSection.contours["axon"][0].points = [(0.0, 0.0), (1.0, 1.0)]
    built = SectionColumns.fromSection(StubSection())
    assert built.getAllModifiedNames() == set()
    assert built.generation > 0
    assert len(built) == 1


# --- identity carry rules ----------------------------------------------------


def test_a_store_without_an_issuer_carries_no_ids():
    """The state of every section in the shipped application."""
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    assert store.getID(row) is None


def test_copy_keeps_the_id_and_duplicate_issues_a_new_one():
    """The carry asymmetry, and it is the whole argument for this arrangement.

    `copyRow` is the `editTraceAttributes` shape: remove, copy, mutate, add,
    which is how an attribute edit and a rename are implemented and which
    produces the same annotation. `duplicateRow` is the duplicate-object and
    copy-to-sections shape, which produces a new one.

    A missed duplication site under this arrangement produces a collision, which
    an issuer's index refuses and reports. Under the alternative, where a copy
    drops the id and every edit path re-attaches it, a missed site produces a
    trace with no id, which nothing detects and a merge cannot place.
    """
    issuer = StubIssuer()
    store = SectionColumns(1, id_issuer=issuer)
    original = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])

    copied = store.copyRow(original)
    duplicated = store.duplicateRow(original)

    assert store.getID(copied) == store.getID(original)
    assert store.getID(duplicated) != store.getID(original)
    assert store.getID(duplicated) is not None


def test_an_id_survives_every_attribute_edit_including_a_rename():
    """A rename goes through the attribute-edit path, so it is the same trace.

    This is the case the carry rules exist for: `editTraceAttributes` implements
    a rename as remove, copy, mutate the name, add, and the result must keep its
    identity or a rename would look like a delete plus a create to a merge.
    """
    issuer = StubIssuer()
    store = SectionColumns(1, id_issuer=issuer)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    before = store.getID(row)

    store.setAttribute(row, "name", "renamed")
    store.setAttribute(row, "color", [9, 9, 9])
    store.setTags(row, {"tagged"})
    store.setCoordinates(row, [(3.0, 3.0), (4.0, 4.0)])

    assert store.getID(row) == before


def test_an_explicit_id_is_carried_in_rather_than_reissued():
    """The load path: an id read from a file is adopted, not minted.

    Reissuing at load is the recorded `Flag.deriveID` failure, so the store never
    asks the issuer for an id it was handed one for.
    """
    issuer = StubIssuer()
    store = SectionColumns(1, id_issuer=issuer)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3],
                          trace_id="fromtheefile")
    assert store.getID(row) == "fromtheefile"
    assert issuer.count == 0


def test_ids_are_issued_once_per_row_over_a_whole_real_section(loaded_sections):
    """One id per trace across a real section, and no repeats."""
    section = max(loaded_sections, key=lambda s: sum(len(c) for c in s.contours.values()))
    issuer = StubIssuer()
    store = SectionColumns.fromSection(section, id_issuer=issuer)

    ids = [store.getID(row) for name in store.contourNames()
           for row in store.rowsForContour(name)]
    assert len(ids) == len(store)
    assert all(i is not None for i in ids)
    assert len(set(ids)) == len(ids)
    assert issuer.count == len(ids)


# --- TraceView: the read-only row view ---------------------------------------
#
# `TraceView` is the first `Trace`-shaped surface over the columns. It is
# read-only, it caches nothing, and nothing in the application references it --
# the same shape wave B's other work took, built behind the seam and proved
# against `materializeTrace` before a single call site is asked to trust it.
#
# The bar here is exhaustive rather than sampled: every row of every populated
# section of both fixture series, every field, compared against both a
# materialized `Trace` and the object-model trace the section actually holds.
# The second comparison is what keeps the first from being vacuous -- the view
# and `materializeTrace` both read the store, so on their own they could agree
# perfectly about a value neither of them got right.


## The fields a `Trace` constructor produces, in `__init__`'s own order, under
## the names a reader uses. `_name` is the storage behind the `name` property,
## and `name` is what any consumer touches, so the view carries `name`.
TRACE_FIELDS = ("name", "color", "closed", "negative", "points", "hidden",
                "tags", "fill_mode")

## The single rename between `vars(Trace(...))` and the surface above.
TRACE_FIELD_STORAGE = {"name": "_name"}


def test_the_view_carries_exactly_the_fields_a_trace_constructor_produces():
    """The completeness guard, derived rather than listed.

    `TRACE_FIELDS` is checked against `vars()` of a real `Trace` instead of
    being trusted, so a ninth field added to `Trace.__init__` turns this red
    instead of leaving the view quietly short of the object model -- the same
    failure mode `test_copy_carries_every_field` exists to close for `copy()`.

    Both directions are asserted. A field on a `Trace` and not on the view is
    an incomplete view; a `Trace`-field-shaped property on the view and not on
    a `Trace` is the view inventing surface, which for a compatibility shim is
    the more expensive mistake of the two.
    """
    constructed = set(vars(Trace("axon", [1, 2, 3])))
    expected = {TRACE_FIELD_STORAGE.get(f, f) for f in TRACE_FIELDS}
    assert constructed == expected, (
        f"Trace.__init__ and this suite's field list have diverged: "
        f"{constructed ^ expected}"
    )

    for field in TRACE_FIELDS:
        attribute = getattr(TraceView, field, None)
        assert isinstance(attribute, property), (
            f"TraceView.{field} is not a read-only property"
        )
        assert attribute.fset is None, (
            f"TraceView.{field} has a setter; this slice is read-only and the "
            f"write path belongs to the store's six mutation entry points"
        )
        assert attribute.fdel is None, f"TraceView.{field} has a deleter"

    ## And no other `Trace` field arrived by accident. `row` is deliberately
    ## not a `Trace` field: it names the thing being viewed, which a view with
    ## no way to say what it views cannot be debugged without.
    properties = {name for name, value in vars(TraceView).items()
                  if isinstance(value, property)}
    assert properties == set(TRACE_FIELDS) | {"row"}, (
        f"TraceView's property surface is not the eight fields plus row: "
        f"{properties}"
    )


def _assert_view_parity(view, materialized, original):
    """Every field of one view against a materialized `Trace` and the original.

    Against `materializeTrace`'s output *exactly*, including type: the view and
    the materialization are the two ways to read a row and they must not be
    distinguishable by anything but identity. Against the object-model trace
    the section holds by value, because the store hands out fresh containers
    where a `Trace` holds its own.
    """
    assert view.name == materialized.name == original.name
    assert type(view.name) is str

    ## Coordinates, against the in-memory floats, exactly -- not approximately.
    assert view.points == materialized.points
    assert view.points == [tuple(p) for p in original.points]
    assert all(type(v) is float for p in view.points for v in p)

    assert view.color == materialized.color
    assert list(view.color) == list(original.color)
    assert all(type(v) is int for v in view.color)

    for flag in ("closed", "negative", "hidden"):
        assert getattr(view, flag) == getattr(materialized, flag)
        assert getattr(view, flag) == getattr(original, flag)
        assert type(getattr(view, flag)) is bool

    assert view.fill_mode == materialized.fill_mode
    assert list(view.fill_mode) == list(original.fill_mode)
    assert all(type(v) is str for v in view.fill_mode)

    assert view.tags == materialized.tags == original.tags
    assert type(view.tags) is set


def _walkViewParity(sections):
    """Every row of every section, viewed and materialized. Returns the counts
    the callers assert on, so neither can pass over an empty walk."""
    rows = 0
    tagged = negative = hidden = 0
    for section in sections:
        store = SectionColumns.fromSection(section)
        for name in store.contourNames():
            traces = list(section.contours[name])
            row_numbers = store.rowsForContour(name)
            assert len(row_numbers) == len(traces)
            for row, original in zip(row_numbers, traces):
                _assert_view_parity(
                    TraceView(store, row), store.materializeTrace(row), original,
                )
                rows += 1
                tagged += bool(original.tags)
                negative += original.negative
                hidden += original.hidden
    return rows, tagged, negative, hidden


def test_every_view_over_the_real_series_matches_its_materialized_trace(
        loaded_sections):
    """The headline view parity, over all ~232 traces of the real series."""
    rows, _, _, _ = _walkViewParity(loaded_sections)
    assert rows > 200, f"expected the fixture's ~232 traces, walked {rows}"


def test_every_view_over_the_synthetic_series_matches_its_materialized_trace(
        synthetic_sections):
    """The same walk over the attribute domain the real fixture cannot carry.

    The real series has no tagged, no negative and no hidden trace and no
    coordinate inexact at 7 decimal places, so four of the eight fields are
    compared there against a single value each. This walk is the one that can
    actually discriminate them, and it asserts it reached them.
    """
    rows, tagged, negative, hidden = _walkViewParity(synthetic_sections)
    assert rows, "the synthetic walk covered no rows at all"
    assert tagged and negative and hidden, (
        "the synthetic material lost the attribute domain it exists to carry, "
        "so this walk stopped discriminating four of the eight fields"
    )


def test_a_view_reads_the_unrounded_coordinate_the_store_kept(loaded_sections):
    """The view sits on the same side of the 7-dp seam the store does.

    The store is on the in-memory side of `getList`'s rounding, and a view that
    coerced or rounded on the way out would undo that silently. The real
    fixture cannot show this -- every one of its coordinates is already exact at
    7 dp -- so a real trace on a real section is given one that is not.
    """
    section = loaded_sections[0]
    name = sorted(section.contours, key=str)[0]
    trace = section.contours[name][0]

    precise = 5.0123456789012
    assert round(precise, 7) != precise, "pick a value the rounding actually moves"
    trace.points = [(precise, 6.0987654321098)] + list(trace.points[1:])

    store = SectionColumns.fromSection(section)
    view = TraceView(store, store.rowsForContour(name)[0])
    assert view.points[0][0] == precise
    assert view.points[0][0] != round(precise, 7)


def test_a_view_holds_no_value_and_so_cannot_go_stale():
    """The no-cache property, asserted as behavior rather than as an absence.

    This slice builds no identity cache, no weak-value map and no
    generation-counter invalidation, because the shim's caching question is
    still open and a view that cached would answer it by accident. What that
    buys is asserted here directly: **one** view instance, held across every
    mutation entry point the store has, reports the new value every time. A
    view that had memoized anything would fail this without needing an
    invalidation mechanism to be reviewed for correctness -- it has no state to
    invalidate.
    """
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)],
                          color=[1, 2, 3], closed=True, tags={"before"})
    view = TraceView(store, row)
    assert (view.name, view.points, view.color, view.closed, view.tags) == (
        "axon", [(0.0, 0.0), (1.0, 1.0)], [1, 2, 3], True, {"before"}
    )

    store.setCoordinates(row, [(2.0, 2.0), (3.0, 3.0)])
    store.setAttribute(row, "color", [9, 9, 9])
    store.setAttribute(row, "closed", False)
    store.setAttribute(row, "negative", True)
    store.setAttribute(row, "hidden", True)
    store.setAttribute(row, "fill_mode", ("solid", "unselected"))
    store.setTags(row, {"after"})
    store.setAttribute(row, "name", "dendrite01")

    assert view.points == [(2.0, 2.0), (3.0, 3.0)]
    assert view.color == [9, 9, 9]
    assert view.closed is False
    assert view.negative is True
    assert view.hidden is True
    assert view.fill_mode == ["solid", "unselected"]
    assert view.tags == {"after"}
    assert view.name == "dendrite01"

    ## And it stays the same row throughout: a rename moves the row between
    ## contour indices, and the view follows the row, not the name.
    assert view.row == row
    assert store.rowsForContour("dendrite01") == [row]


def test_a_view_hands_out_fresh_containers_it_does_not_remember():
    """Reading twice gives two containers, and writing into one reaches nothing.

    `getPoints` and `getTags` build a fresh list and a fresh set per call, which
    is what makes the view safe to hand out with no cache behind it: a caller
    that mutates what it was given corrupts neither the column nor the next
    read. A memoizing view would have to answer this question with an
    invalidation rule instead.
    """
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)],
                          color=[1, 2, 3], tags={"alpha"})
    view = TraceView(store, row)

    assert view.points is not view.points
    assert view.tags is not view.tags
    assert view.color is not view.color

    view.points.append((5.0, 5.0))
    view.tags.add("injected")
    view.color[0] = 200
    assert view.points == [(0.0, 0.0), (1.0, 1.0)]
    assert view.tags == {"alpha"}
    assert view.color == [1, 2, 3]

    ## Two views of one row are two objects. Identity is explicitly not this
    ## slice's subject: nothing consumes the view, so nothing depends on it.
    other = TraceView(store, row)
    assert other is not view
    assert other.name == view.name and other.points == view.points


def test_a_view_refuses_every_write_including_ones_it_has_no_property_for():
    """No write path, and no way to fake one by shadowing a column.

    Each of the eight is a getter with no setter, so an assignment raises
    rather than landing as an instance attribute that would shadow the column
    and read back convincingly. `__slots__` extends that to a name the class has
    no property for, which is the hole a plain read-only class leaves open.
    Write-through is a later slice and belongs to the store's own mutation
    entry points.
    """
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)],
                          color=[1, 2, 3])
    view = TraceView(store, row)
    generation = store.generation

    for field in TRACE_FIELDS:
        with pytest.raises(AttributeError):
            setattr(view, field, "written")
    with pytest.raises(AttributeError):
        view.row = 7
    with pytest.raises(AttributeError):
        view.not_a_field = "written"

    assert store.generation == generation, "a refused write moved the store"
    assert view.name == "axon"
    assert view.points == [(0.0, 0.0), (1.0, 1.0)]
    assert view.color == [1, 2, 3]


def test_a_view_over_a_removed_row_answers_exactly_as_the_store_does():
    """The liveness asymmetry is the store's, and the view does not paper it.

    `SectionColumns.getName` answers for a tombstoned row while the other seven
    readers raise `IndexError` through `_requireLive`. Pinned here rather than
    corrected in the view, because a view that added a liveness check of its own
    would be a second, divergent answer to a question the store already answers
    -- and deciding what a view over a dead row should do is the business of the
    slice that gives the view a consumer, which this one deliberately does not.
    """
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)],
                          color=[1, 2, 3])
    view = TraceView(store, row)
    store.removeRow(row)

    assert view.name == store.getName(row) == "axon"
    assert repr(view) == "<TraceView row 0 of 'axon'>"
    for field in ("color", "closed", "negative", "points", "hidden",
                  "tags", "fill_mode"):
        with pytest.raises(IndexError):
            getattr(view, field)


def test_constructing_a_view_touches_no_column():
    """A view is as cheap as a tuple, so nothing has to ration them.

    Construction reads nothing, validates nothing and bumps nothing, which is
    what makes "construct one per read and throw it away" a usable strategy for
    a class with no identity cache. Asserted on a row that does not exist: a
    constructor that read a column would raise here.
    """
    store = SectionColumns(1)
    generation = store.generation
    view = TraceView(store, 4_000_000)
    assert store.generation == generation
    with pytest.raises(IndexError):
        view.points
