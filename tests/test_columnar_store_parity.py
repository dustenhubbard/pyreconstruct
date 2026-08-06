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
Measured on `dev/assets/checker/files/class_series.jser` at
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
import ast
import inspect
import json
import random
import shutil
from pathlib import Path

import numpy as np
import pytest

from PyReconstruct.modules.datatypes import Contour, Trace
from PyReconstruct.modules.datatypes.columnar_store import (
    BOOL_ATTRIBUTES,
    ContourView,
    FILL_MODE_CODES,
    FILL_MODE_OVERFLOW,
    SectionColumns,
    SegmentedCoordinates,
    TraceView,
)
from PyReconstruct.modules.datatypes.trace import normalizeObjectName

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


# --- D10: how a foreign trace's id enters this series' store -----------------
#
# `appendRow` takes two mutually exclusive id parameters, and the distinction
# between them is the whole of D10. `trace_id=` is an id THIS series already
# owns, carried verbatim without consulting the issuer -- it is in the issuer's
# index already, put there when it was issued. `foreign_id=` is an id from
# another series, registered through `TraceIDIssuer.adopt` before it is
# accepted, and replaced-and-reported when the issuer refuses it.
#
# The maintainer's decision, recorded in DECISIONS.md 2026-08-05: Q1 register
# via `adopt()`, Q2 on a clash issue a fresh local id for that row only and
# report it. The investigation is
# `specs/phase1-foreign-trace-id-acquisition-2026-08-05.md`.
#
# These use the REAL `TraceIDIssuer` rather than `StubIssuer`, because `adopt`
# and its collision log are the subject. `StubIssuer` stays valid for every
# test above it: the widened duck type applies only to a store that is passed a
# `foreign_id`.

def _aRow(store, name="axon", **kwargs):
    """One plausible row, so these tests are about ids and nothing else."""
    return store.appendRow(
        name=name, points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3], **kwargs
    )


def test_a_foreign_id_is_registered_with_the_local_issuer():
    """D10 Q1. The gap was that `_resolveID` registered a carried id with
    nothing.

    `trace_id.py`'s recorded policy is "at load and at merge -- detect and
    report by name, never silently adopt and never silently reissue", and
    accepting a foreign id verbatim is the silent adoption half of that.
    `TraceIDIssuer.adopt` has existed and been tested since wave B and had zero
    production callers; what was missing was only the call.
    """
    from PyReconstruct.modules.datatypes.trace_id import (
        TraceIDIssuer, encodeTraceID,
    )

    issuer = TraceIDIssuer()
    store = SectionColumns(1, id_issuer=issuer)
    foreign = encodeTraceID(4242)

    row = _aRow(store, foreign_id=foreign)

    assert store.getID(row) == foreign, "the foreign id was not kept"
    assert foreign in issuer.taken, (
        "the foreign id was accepted without being registered, so the issuer's "
        "index -- the whole of its uniqueness guarantee -- cannot see it"
    )
    assert issuer.collisions == ()
    assert store.foreign_id_reissues == ()


def test_registering_a_foreign_id_stops_the_issuer_handing_it_out_again():
    """R2 from the investigation, and the reason registration is the fix.

    An unregistered foreign id is invisible to `issue()`'s refuse-and-reissue
    loop, so the issuer can later mint the same id for a different trace. With
    the identical bits source, registration lets that loop see the id and step
    past it. The real `secrets.randbits(64)` source makes this ~4.1e-6 across
    the largest corpus on record rather than a live data-loss risk, but it is a
    hole in the issuer's stated contract either way, and unlike R1 it is closed
    completely by registration alone.
    """
    from PyReconstruct.modules.datatypes.trace_id import (
        TraceIDIssuer, encodeTraceID,
    )

    draws = iter([4242, 99])
    issuer = TraceIDIssuer(bits_source=lambda: next(draws))
    store = SectionColumns(1, id_issuer=issuer)
    foreign = encodeTraceID(4242)

    imported = _aRow(store, foreign_id=foreign)
    later = _aRow(store, name="dendrite")   # no id: the issuer mints one

    assert store.getID(imported) == foreign
    assert store.getID(later) == encodeTraceID(99), (
        "the issuer drew 4242 first and had to step past it; it did not"
    )
    assert store.getID(later) != store.getID(imported)


def test_a_clashing_foreign_id_is_reissued_and_reported(capsys):
    """D10 Q2, against R1 -- the CERTAIN case, not the rare one.

    `deriveTraceID` is a pure function of the trace's own stored row, and that
    is the property it exists for: two independent opens of one legacy file
    agree on every id with no save. The same property means two sibling series
    descended from one ancestor still hold the ancestor's id for two traces
    that have since diverged. When the merge keeps both -- which it does,
    correctly, whenever the overlap test fails -- both land in one store under
    one id. The investigation reproduced two live rows sharing an id with the
    issuer's collision log empty.

    `adopt` detects it and resolves nothing; he chose b4, a fresh local id for
    the clashing row only, reported rather than silent.
    """
    from PyReconstruct.modules.datatypes.trace_id import (
        TraceIDIssuer, deriveTraceID,
    )

    ## The ancestor row both series migrated, in `Trace.getList` shape.
    ancestor = [[0.0, 1.0], [0.0, 1.0], [1, 2, 3], True, False, False,
                ["none", "none"], []]
    a_id = deriveTraceID(5, "axon", ancestor)
    b_id = deriveTraceID(5, "axon", ancestor)
    assert a_id == b_id, (
        "the derivation stopped agreeing across two independent derivations, "
        "which is the property R1 depends on and tid-v1 is frozen to provide"
    )

    ## Series A holds it already; series B's copy arrives through an import.
    issuer = TraceIDIssuer(taken=[a_id])
    store = SectionColumns(5, id_issuer=issuer)
    mine = _aRow(store, trace_id=a_id)
    theirs = _aRow(store, foreign_id=b_id)

    fresh = store.getID(theirs)
    assert store.getID(mine) == a_id, "the trace this series owned lost its id"
    assert fresh is not None, (
        "the clashing row was given no id -- the store's own docstring calls "
        "that the worse failure, one a merge cannot place and nothing detects"
    )
    assert fresh != a_id, "TWO LIVE ROWS SHARE ONE ID: the R1 failure itself"
    assert fresh in issuer.taken

    ## Reported through both channels, which is what makes the reissue
    ## satisfy a policy whose wording forbids reissuing SILENTLY.
    assert issuer.collisions == ((a_id, "axon"),)
    assert store.foreign_id_reissues == ((theirs, b_id, fresh, "axon"),)
    printed = capsys.readouterr().err
    assert b_id in printed and fresh in printed, (
        f"the clash was resolved without saying so:\n{printed}"
    )


def test_a_carried_id_is_not_offered_to_the_issuer_a_second_time():
    """The load-bearing distinction, at the layer that has to keep it.

    A rebuild and a `copyRow` both re-append a trace this series ALREADY has an
    id for. That id is in the issuer's taken-set because this series put it
    there, so routing either through `adopt()` would report a clash of the
    trace against itself. A collision log that is wrong every time is worse
    than no log, because it trains a reader to ignore the entry that is right.
    """
    from PyReconstruct.modules.datatypes.trace_id import TraceIDIssuer

    issuer = TraceIDIssuer()
    store = SectionColumns(1, id_issuer=issuer)

    original = _aRow(store)
    issued = store.getID(original)
    copied = store.copyRow(original)                  # keeps the id by design
    carried = _aRow(store, name="axon", trace_id=issued)   # a rebuild's arm

    assert store.getID(copied) == issued
    assert store.getID(carried) == issued
    assert issuer.collisions == (), (
        f"carrying this series' own id reported a clash against itself: "
        f"{issuer.collisions}"
    )
    assert store.foreign_id_reissues == (), (
        "a carried id was replaced as though it had arrived from elsewhere"
    )


def test_the_two_id_parameters_are_mutually_exclusive():
    """They mean different things, so one id cannot be both."""
    from PyReconstruct.modules.datatypes.trace_id import (
        TraceIDIssuer, encodeTraceID,
    )

    store = SectionColumns(1, id_issuer=TraceIDIssuer())
    with pytest.raises(ValueError, match="not both"):
        _aRow(store, trace_id=encodeTraceID(1), foreign_id=encodeTraceID(2))


def test_a_foreign_id_needs_an_issuer_to_register_with():
    """An id cannot be registered with nothing.

    Accepting it into an issuer-less store would store it unregistered, which
    is precisely the silent adoption D10 removed, arriving through the fix. It
    refuses instead: a caller holding a foreign id and no issuer has no way to
    be correct, and a loud programming error at a boundary with no production
    caller costs nothing.
    """
    from PyReconstruct.modules.datatypes.trace_id import encodeTraceID

    store = SectionColumns(1)
    with pytest.raises(ValueError, match="no id issuer"):
        _aRow(store, foreign_id=encodeTraceID(7))
    ## The carried-id arm is unaffected: it never needed an issuer.
    assert store.getID(_aRow(store, trace_id="fromtheefile")) == "fromtheefile"


def test_a_malformed_foreign_id_leaves_the_store_untouched():
    """The refusal has to arrive before the first column is written.

    `adopt()` rejects a malformed id by raising, and `foreign_id` is the one
    parameter whose entire purpose is to accept an id from OUTSIDE this series,
    which is by definition untrusted. Resolving the id after the columns had
    been appended left `_names`, `_tags` and the coordinate backing advanced
    while `_ids`, `_live` and `_live_count` were not -- and the arity assertion
    on the NEXT append cannot catch that, because it compares `row` against
    `len(self._names)` and the failed call advanced BOTH. So the next append
    succeeded and `_ids` was off by one against the rows it described, for the
    rest of the store's life. That is worse than the missing id the module
    docstring already refuses: `getID` went on answering, with another row's id.
    """
    from PyReconstruct.modules.datatypes.trace_id import TraceIDIssuer

    issuer = TraceIDIssuer()
    store = SectionColumns(1, id_issuer=issuer)
    kept = {row: store.getID(row)
            for row in (_aRow(store), _aRow(store, name="dendrite"))}
    assert all(kept.values())
    before = len(store._names)
    taken_before = len(issuer.taken)

    with pytest.raises(ValueError, match="11 characters"):
        _aRow(store, foreign_id="not-a-valid-id")

    ## Nothing moved: no column, no id record, and not the issuer either --
    ## `adopt` decodes before it registers, so the refused id is not in `taken`.
    assert len(store._names) == before, "a column advanced past the refusal"
    assert len(store._ids) == before
    assert len(store._tags) == before
    assert store.rowCount == before and len(store) == before
    assert store.foreign_id_reissues == ()
    assert len(issuer.taken) == taken_before, (
        "the issuer registered the id it refused as malformed"
    )
    assert {row: store.getID(row) for row in kept} == kept

    ## The shift itself: the next append must be the row the failed one was
    ## going to be, and must not slide the existing rows' ids up by one.
    fresh = _aRow(store, name="dendrite")
    assert fresh == before, f"the failed append consumed row {before}"
    assert {row: store.getID(row) for row in kept} == kept, (
        "the existing rows' ids shifted under the row that failed to append"
    )
    assert store.getID(fresh) not in kept.values(), (
        "the new row was handed an id another row already holds"
    )


def test_the_foreign_id_clash_report_is_capped_but_the_record_is_not(capsys):
    """A common-ancestor merge clashes on every trace, not on a rare one.

    The report is teed into the per-user log file, which rotates at 2 MB, so an
    uncapped one would evict the history somebody opened the log to read --
    D11's `DRIFT_REPORT_LIMIT` precedent, for its reason. The RECORD is not
    capped, because a caller reporting in its own vocabulary needs all of it.
    """
    from PyReconstruct.modules.datatypes.columnar_store import (
        FOREIGN_ID_REPORT_LIMIT,
    )
    from PyReconstruct.modules.datatypes.trace_id import (
        TraceIDIssuer, encodeTraceID,
    )

    clashing = [encodeTraceID(n) for n in range(FOREIGN_ID_REPORT_LIMIT + 5)]
    issuer = TraceIDIssuer(taken=clashing)
    store = SectionColumns(1, id_issuer=issuer)

    capsys.readouterr()
    for foreign in clashing:
        _aRow(store, foreign_id=foreign)

    assert len(store.foreign_id_reissues) == len(clashing), (
        "the record was capped; it is the printing that is capped"
    )
    printed = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(printed) <= FOREIGN_ID_REPORT_LIMIT + 1, (
        f"the cap did not hold: {len(printed)} lines for {len(clashing)} clashes"
    )
    assert "will not be printed" in "\n".join(printed), (
        "printing stopped without saying that it had"
    )


def test_a_rebuild_carries_the_ids_it_is_given_and_issues_for_the_rest(
    loaded_sections
):
    """`fromSection`'s `carried_ids`, over a real section.

    The rebuild path. Until D10 this appended every row with no id, so the
    issuer minted a fresh one for each -- and `Section.resyncColumnarStore`
    reaches it from fourteen call sites, plus every `save()` since D11.

    Keyed on the `Trace` object because that is the only correlation there is:
    `Trace` carries no id attribute of any kind, so an id cannot be read off
    the object being re-appended.
    """
    from PyReconstruct.modules.datatypes.trace_id import TraceIDIssuer

    section = max(loaded_sections, key=lambda s: sum(len(c) for c in s.contours.values()))
    issuer = TraceIDIssuer()
    first = SectionColumns.fromSection(section, id_issuer=issuer)

    carried = {}
    for name in sorted(section.contours, key=str):
        for trace, row in zip(section.contours[name].getTraces(),
                              first.rowsForContour(name)):
            carried[trace] = first.getID(row)
    assert carried and all(carried.values())

    ## One trace deliberately left out: the "never seen before" arm.
    newcomer = next(iter(carried))
    del carried[newcomer]
    taken_before = len(issuer.taken)

    second = SectionColumns.fromSection(
        section, id_issuer=issuer, carried_ids=carried,
    )

    rebuilt = {}
    for name in sorted(section.contours, key=str):
        for trace, row in zip(section.contours[name].getTraces(),
                              second.rowsForContour(name)):
            rebuilt[trace] = second.getID(row)

    assert {t: i for t, i in rebuilt.items() if t in carried} == carried, (
        "the rebuild re-identified traces it was handed ids for"
    )
    assert rebuilt[newcomer] is not None
    assert rebuilt[newcomer] not in carried.values(), (
        "the trace with no carried id was handed one another trace holds"
    )
    assert len(set(rebuilt.values())) == len(rebuilt), (
        "the rebuild produced two rows sharing one id"
    )
    assert len(issuer.taken) == taken_before + 1, (
        "the rebuild leaked ids into the issuer's index: only the one trace "
        "without a carried id should have drawn a new one"
    )
    assert issuer.collisions == (), "the carry reported a clash against itself"

    ## Two DISTINCT traces mapped to ONE id -- the shape a guard keyed on trace
    ## identity cannot see, because both lookups are of different objects. The
    ## issuer cannot catch it either: a carried id is deliberately never offered
    ## to `adopt()`, so its collision log stays empty while two live rows share
    ## one id. That is the R1 duplicate this whole mechanism exists to prevent,
    ## and the rebuild would otherwise propagate it forward on every save.
    assert len(carried) >= 2
    one, other = list(carried)[:2]
    shared = carried[one]
    doubled = dict(carried)
    doubled[other] = shared          # `one` already holds it
    taken_before_doubled = len(issuer.taken)

    third = SectionColumns.fromSection(
        section, id_issuer=issuer, carried_ids=doubled,
    )
    tripled = {}
    for name in sorted(section.contours, key=str):
        for trace, row in zip(section.contours[name].getTraces(),
                              third.rowsForContour(name)):
            tripled[trace] = third.getID(row)

    pair = [tripled[one], tripled[other]]
    assert pair.count(shared) == 1, (
        f"one carried id was spent {pair.count(shared)} times, not once: {pair}"
    )
    fell_through = next(i for i in pair if i != shared)
    assert fell_through is not None, "the second row was left with no id at all"
    assert fell_through not in doubled.values(), (
        "the trace whose carried id was already spent was handed an id another "
        "trace holds, rather than a fresh one"
    )
    assert fell_through in issuer.taken, "the fresh id was not registered"
    assert len(set(tripled.values())) == len(tripled), (
        "TWO LIVE ROWS SHARE ONE ID: the R1 duplicate, arriving through the "
        "rebuild's own carry"
    )
    ## Exactly two draws: the newcomer that has no carried id, and the trace
    ## whose id was already spent. Nothing else re-identified.
    assert len(issuer.taken) == taken_before_doubled + 2, (
        "the rebuild drew more ids than the two traces that needed one"
    )
    assert issuer.collisions == (), "the carry reported a clash against itself"


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
            f"TraceView.{field} is not a property"
        )
        assert attribute.fget is not None, f"TraceView.{field} cannot be read"
        assert attribute.fset is not None, (
            f"TraceView.{field} has no setter; every one of the eight fields "
            f"writes through, and one that did not would be a field a consumer "
            f"could read but not assign -- which is not the `Trace` surface"
        )
        ## No deleter, on any of them. `del trace.color` is not a thing a
        ## `Trace` supports and the store has no entry point for removing an
        ## attribute from a row -- only for removing the whole row.
        assert attribute.fdel is None, f"TraceView.{field} has a deleter"

    ## `row` is deliberately not a `Trace` field and deliberately not writable:
    ## it names the thing being viewed, which a view with no way to say what it
    ## views cannot be debugged without, and a view that could be repointed at
    ## another row would be a different object rather than a written one.
    assert TraceView.row.fget is not None
    assert TraceView.row.fset is None, "a view must not be repointable"

    ## And no other `Trace` field arrived by accident.
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


def test_a_view_refuses_the_writes_it_has_no_property_for():
    """The eight fields write through; nothing else does.

    `__slots__` is what closes the hole a plain class leaves open, and it
    matters more now that the eight accept writes, not less: under a plain
    class `view.colour = ...` would silently create an instance attribute and
    then read back convincingly, which is exactly the failure a write-through
    view must not have. A misspelt field has to raise, not appear to work.

    `row` is refused for a different reason: a view that could be repointed at
    another row is a different object, not a written one.
    """
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)],
                          color=[1, 2, 3])
    view = TraceView(store, row)
    generation = store.generation

    with pytest.raises(AttributeError):
        view.row = 7
    with pytest.raises(AttributeError):
        view.not_a_field = "written"
    ## The near-miss that motivates `__slots__`: one letter off a real field.
    with pytest.raises(AttributeError):
        view.colour = [9, 9, 9]
    ## And a `Trace` method name, which is the other way a consumer ported from
    ## the object model could land on a name the view has no column for.
    with pytest.raises(AttributeError):
        view.fill_modes = ("solid", "unselected")

    assert store.generation == generation, "a refused write moved the store"
    assert view.name == "axon"
    assert view.points == [(0.0, 0.0), (1.0, 1.0)]
    assert view.color == [1, 2, 3]


# --- TraceView: the write path ------------------------------------------------
#
# Slice 6. Each of the eight properties grows a setter that is one call into a
# mutation entry point `SectionColumns` already had -- `setAttribute` for the
# six scalars, `setTags` for `tags`, `setCoordinates` for `points` -- and does
# nothing else. No cache is added, no identity map, and no consumer: the view
# still has exactly one caller, this file.
#
# The bar for "it wrote through" is deliberately NOT "read it back off the
# view". The view and the setter are the same object, so a view that quietly
# kept the written value in a slot would pass that check while the column still
# held the old bytes. Every assertion below reads the result back through
# `SectionColumns`' OWN getters, and the fresh-view test reads it through a
# second view object that never saw the write.


## One write per field: the value assigned, the store reader that must show it,
## and what that reader must return. Keyed by field so the guard below can
## assert the table covers all eight rather than however many are listed.
##
## The expected values are not always the written ones, and that is the point of
## writing them out: `fill_mode` is written as a tuple and read back as a list,
## and `tags` is written as a set and read back as a fresh set, because those
## are the shapes the store's readers promise.
WRITE_THROUGH_CASES = {
    "name": ("dendrite01", lambda s, r: s.getName(r), "dendrite01"),
    "color": ([9, 8, 7], lambda s, r: s.getColor(r), [9, 8, 7]),
    "closed": (False, lambda s, r: s.getFlag(r, "closed"), False),
    "negative": (True, lambda s, r: s.getFlag(r, "negative"), True),
    "points": ([(4.0, 5.0), (6.0, 7.0), (8.0, 9.0)],
               lambda s, r: s.getPoints(r),
               [(4.0, 5.0), (6.0, 7.0), (8.0, 9.0)]),
    "hidden": (True, lambda s, r: s.getFlag(r, "hidden"), True),
    "tags": ({"beta", "alpha"}, lambda s, r: s.getTags(r), {"alpha", "beta"}),
    "fill_mode": (("solid", "unselected"), lambda s, r: s.getFillMode(r),
                  ["solid", "unselected"]),
}


def _aStoredRow():
    """A store holding one row whose every field differs from every value
    `WRITE_THROUGH_CASES` writes.

    So that no case can pass by writing back what was already there -- the
    before/after assertions below check that the store's own reader *moved*,
    not merely that it ends up equal to the expectation.
    """
    store = SectionColumns(1)
    row = store.appendRow(
        name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3],
        closed=True, negative=False, hidden=False,
        fill_mode=("none", "none"), tags={"before"},
    )
    return store, row


def test_the_write_through_table_covers_every_field_the_view_carries():
    """The coverage guard for the table, so a ninth field cannot be untested.

    Same derivation as the completeness guard above: `TRACE_FIELDS` is itself
    checked against `vars(Trace(...))`, so this chains a new `Trace` field
    through to a missing write-through case rather than letting the
    parametrization quietly shrink.
    """
    assert set(WRITE_THROUGH_CASES) == set(TRACE_FIELDS), (
        f"the write-through table and the view's field list have diverged: "
        f"{set(WRITE_THROUGH_CASES) ^ set(TRACE_FIELDS)}"
    )


@pytest.mark.parametrize("field", TRACE_FIELDS)
def test_a_setter_moves_the_underlying_column_and_bumps_the_generation(field):
    """Each setter, individually: the store's own reader changes, once.

    Read back through `SectionColumns`, not through the view, because the view
    is the thing under test -- one that memoized the assignment would satisfy a
    read through itself while the column still held the old value.

    The counter delta is asserted as exactly one, not merely as an increase. A
    setter that both wrote through *and* bumped a counter of its own, or that
    routed through two entry points, would show up as two, and "the store bumps
    it because the store is what bumps it" is the property this slice claims.
    """
    written, readStore, expected = WRITE_THROUGH_CASES[field]
    store, row = _aStoredRow()
    view = TraceView(store, row)

    before = readStore(store, row)
    generation = store.generation
    assert before != expected, (
        f"the {field} case writes the value the row already held, so it cannot "
        f"tell a working setter from one that does nothing"
    )

    setattr(view, field, written)

    after = readStore(store, row)
    assert after == expected, (
        f"the store's own reader still reports {after!r} after view.{field} "
        f"was assigned {written!r}"
    )
    assert after != before
    assert store.generation == generation + 1, (
        f"view.{field} = ... moved the generation by "
        f"{store.generation - generation}, not by one"
    )
    ## And the view agrees with the column, which is the weaker of the two.
    assert getattr(view, field) == expected


@pytest.mark.parametrize("field", TRACE_FIELDS)
def test_a_write_through_one_view_is_visible_to_a_view_built_afterwards(field):
    """Slice 4's no-cache property, continuing to hold across a write.

    A view built *after* the write has never touched the row and holds no
    state, so it can only be reading the column. This is the assertion that a
    per-instance cache -- the thing this slice is explicitly not allowed to
    build -- would fail, and it is the write-direction counterpart of
    `test_a_view_holds_no_value_and_so_cannot_go_stale`.

    Both directions are covered: the writing view still reports the new value
    (so the write did not leave it stale), and a third view built *before* the
    write reports it too (so visibility is not a property of construction
    order).
    """
    written, _, expected = WRITE_THROUGH_CASES[field]
    store, row = _aStoredRow()

    writer = TraceView(store, row)
    earlier = TraceView(store, row)

    setattr(writer, field, written)

    later = TraceView(store, row)
    assert later is not writer and later is not earlier
    assert getattr(later, field) == expected, (
        f"a view built after the write does not see {field}; the write did not "
        f"reach the column, or something is caching"
    )
    assert getattr(earlier, field) == expected
    assert getattr(writer, field) == expected


@pytest.mark.parametrize("field", TRACE_FIELDS)
def test_a_setter_writes_its_own_row_and_leaves_its_neighbours_alone(field):
    """The row number is the view's only state, so writing the wrong one is its
    characteristic bug.

    Every other test in this section builds a store with a single row, where an
    off-by-one is invisible: `row - 1` clamps back onto the row being tested and
    a broken setter passes. Measured, not assumed -- planting exactly that
    mutation survived the rest of this file. So here there are three rows, the
    view sits on the middle one, and both neighbours are read back afterwards.

    The neighbours are given values distinct from the middle row's *and* from
    what the case writes, so a setter that wrote all three rows, or the row
    before, or the row after, moves something this can see.
    """
    written, readStore, expected = WRITE_THROUGH_CASES[field]

    store = SectionColumns(1)
    rows = []
    for i in range(3):
        rows.append(store.appendRow(
            name=f"axon{i}", points=[(float(i), 0.0), (float(i), 1.0)],
            color=[i, i, i], closed=True, negative=False, hidden=False,
            fill_mode=("none", "none"), tags={f"before{i}"},
        ))
    before = [readStore(store, row) for row in rows]
    assert before[1] != expected, "the case writes what the middle row held"

    TraceView(store, rows[1]).__setattr__(field, written)

    assert readStore(store, rows[1]) == expected
    assert readStore(store, rows[0]) == before[0], (
        f"view.{field} = ... also wrote the row before it"
    )
    assert readStore(store, rows[2]) == before[2], (
        f"view.{field} = ... also wrote the row after it"
    )


def test_a_write_through_a_view_is_recorded_by_the_stores_own_tracking():
    """The view adds no entry point, so the store's bookkeeping just happens.

    `_modified_contours`, the added/removed lists and the rename reindex are
    all `setAttribute`/`setTags`/`setCoordinates`' work. A setter that reached
    past them into a column directly would leave every one of these empty while
    the value still changed -- a store that reported no modification for a
    modification, which is the shape of the existing stale-render bug family.
    """
    store, row = _aStoredRow()
    view = TraceView(store, row)
    store.clearTracking()

    view.color = [4, 4, 4]
    assert store.modified_contours == {"axon"}
    assert store.getAllModifiedNames() == {"axon"}

    view.tags = {"tagged"}
    view.points = [(3.0, 3.0), (4.0, 4.0)]
    assert store.getAllModifiedNames() == {"axon"}

    ## A rename is the case with a visible structural consequence: the row moves
    ## between contour indices and both names are reported.
    view.name = "dendrite01"
    assert store.rowsForContour("axon") == []
    assert store.rowsForContour("dendrite01") == [row]
    assert store.contourNames() == ["dendrite01"]
    assert store.getAllModifiedNames() == {"axon", "dendrite01"}

    ## And the view followed the row, not the name.
    assert view.row == row
    assert view.name == "dendrite01"

    ## Nothing was added or removed: an attribute edit through a view is an edit
    ## in place, not the remove/copy/add shape `editTraceAttributes` uses.
    assert store.added_rows == []
    assert store.removed_rows == []
    assert len(store) == 1


def test_a_written_value_survives_materialization_and_a_save():
    """The write lands in the column the rest of the store reads from.

    `materializeTrace` is the independent second reader of a row -- it existed
    before the view and shares no code with it -- so a value written through
    the view appearing there is evidence the write reached the actual column
    rather than some parallel place only the view consults. Serializing closes
    it: a write that put a `numpy` scalar or a tuple where the column expects
    its own type would pass a value comparison and fail at `json.dump`.
    """
    store, row = _aStoredRow()
    view = TraceView(store, row)

    view.name = "dendrite01"
    view.color = [9, 8, 7]
    view.closed = False
    view.negative = True
    view.hidden = True
    view.points = [(4.0, 5.0), (6.0, 7.0)]
    view.tags = {"alpha", "beta"}
    view.fill_mode = ("solid", "unselected")

    rebuilt = store.materializeTrace(row)
    assert rebuilt.name == "dendrite01"
    assert rebuilt.color == [9, 8, 7]
    assert rebuilt.closed is False
    assert rebuilt.negative is True
    assert rebuilt.hidden is True
    assert rebuilt.points == [(4.0, 5.0), (6.0, 7.0)]
    assert rebuilt.tags == {"alpha", "beta"}
    assert rebuilt.fill_mode == ["solid", "unselected"]

    ## Native Python types throughout, or the save breaks rather than the read.
    assert type(rebuilt.closed) is bool and type(rebuilt.negative) is bool
    assert all(type(v) is int for v in rebuilt.color)
    assert all(type(v) is float for p in rebuilt.points for v in p)
    json.dumps(rebuilt.getList(include_name=False))


def test_a_write_through_a_view_does_not_alias_what_it_was_handed():
    """The column must not end up sharing memory with the caller's containers.

    `getTags` handing out a fresh set is already pinned; this is the same
    invariant on the way in, which the write path newly makes reachable. A
    caller that assigns a list of points and then mutates its own list must not
    thereby edit the row.
    """
    store, row = _aStoredRow()
    view = TraceView(store, row)

    points = [(4.0, 5.0), (6.0, 7.0)]
    tags = {"alpha"}
    color = [9, 8, 7]
    view.points = points
    view.tags = tags
    view.color = color

    points.append((8.0, 9.0))
    tags.add("injected")
    color[0] = 200

    assert store.getPoints(row) == [(4.0, 5.0), (6.0, 7.0)]
    assert store.getTags(row) == {"alpha"}
    assert store.getColor(row) == [9, 8, 7]

    ## The list case above cannot show the aliasing hazard, because coercing a
    ## list allocates regardless. The one that can is a float64 array, which is
    ## what `np.asarray` would hand straight back: `_asCoordinateArray` copies
    ## it anyway, and this is the write-path reach to that guarantee.
    array = np.array([(1.5, 2.5), (3.5, 4.5)], dtype=np.float64)
    view.points = array
    assert not np.shares_memory(store.getCoordinates(row), array)
    array[0, 0] = 99.0
    assert store.getPoints(row) == [(1.5, 2.5), (3.5, 4.5)]


def test_a_write_to_a_removed_row_raises_through_the_stores_liveness_check():
    """Liveness stays the store's on the way in, as it is on the way out.

    Every one of the three entry points calls `_requireLive` first, so a write
    to a tombstoned row raises `IndexError` without the view carrying a
    liveness rule of its own. Note this is *not* the asymmetric case the read
    side has: `getName` answers for a dead row, but `setAttribute(row, "name",
    ...)` does not, so the write path is uniform where the read path is not.
    """
    store, row = _aStoredRow()
    view = TraceView(store, row)
    store.removeRow(row)
    generation = store.generation

    for field in TRACE_FIELDS:
        written, _, _ = WRITE_THROUGH_CASES[field]
        with pytest.raises(IndexError):
            setattr(view, field, written)

    assert store.generation == generation, (
        "a refused write moved the store's generation counter"
    )


# --- the name-validation split between Trace and the store -------------------


## `Trace.name`'s setter does two things: `assert (value is None or type(value)
## is str)`, then `normalizeObjectName(value)`. `SectionColumns.setAttribute`
## does the second and not the first, and `TraceView.name`'s setter delegates
## rather than replicating the assertion -- so these four rows are the whole
## observable difference between assigning a name to a `Trace` and assigning
## one to a view.
##
## Each row is (value, what `Trace` does, what the view does), where a `type`
## means "raises that" and anything else means "stores that".
##
## The decision this pins: normalization is the half with a correctness
## consequence (a comma in a name shifts every field of the log entry carrying
## it and the entry stops parsing), the store runs it, and the two sides agree
## on it. The `assert` is a debug-time type guard that `python -O` strips, so a
## view replicating it would match `Trace` in some runs and not others; and
## `None` is not the view's to accept in any case, because `_names` is a list of
## `str` that `_index` keys on and the store has no representation for a
## nameless row.
class _StrSubclass(str):
    pass


NAME_VALIDATION_SPLIT = [
    ## The row that matters, and the two sides agree on it.
    (" a,b ", "a_b", "a_b"),
    ("two words,and a comma", "two_words_and_a_comma", "two_words_and_a_comma"),
    ## `Trace` accepts `None`; the store has nowhere to put it.
    (None, None, AttributeError),
    ## Both refuse a non-string, by different mechanisms.
    (5, AssertionError, AttributeError),
    ## And the store is the more permissive of the two on a `str` subclass,
    ## which it normalizes down to a plain `str`.
    (_StrSubclass("a b"), AssertionError, "a_b"),
]


@pytest.mark.parametrize("value,on_trace,on_view", NAME_VALIDATION_SPLIT)
def test_name_validation_is_the_stores_and_the_divergence_is_pinned(
        value, on_trace, on_view):
    """Both sides of the table, measured rather than described.

    This test exists so the delegation is a recorded decision with a known
    blast radius, not an oversight. If a consumer ever needs `Trace`'s exact
    type-error behavior through a view, this is the list of what it would be
    asking for.
    """
    trace = Trace("axon", [1, 2, 3])
    if isinstance(on_trace, type) and issubclass(on_trace, BaseException):
        with pytest.raises(on_trace):
            trace.name = value
    else:
        trace.name = value
        assert trace.name == on_trace
        assert trace.name is None or type(trace.name) is str

    store, row = _aStoredRow()
    view = TraceView(store, row)
    generation = store.generation
    if isinstance(on_view, type) and issubclass(on_view, BaseException):
        with pytest.raises(on_view):
            view.name = value
        assert store.generation == generation, "a refused write moved the store"
        assert store.getName(row) == "axon"
    else:
        view.name = value
        assert store.getName(row) == on_view
        ## Normalized to a plain `str`, whatever went in.
        assert type(store.getName(row)) is str
        assert store.rowsForContour(on_view) == [row]


def test_the_normalization_a_name_gets_is_the_same_one_a_trace_name_gets():
    """The half of the validation the two sides DO share, on one function.

    `test_a_name_entering_the_store_is_normalized_the_way_a_trace_name_is`
    pins this for `appendRow`. This is the same pin for the write path, where
    the risk is newly reachable: a view setter that normalized on its own
    before calling the store would double-normalize (harmlessly, since the
    function is idempotent) and would then be a second place to keep in step
    with `Trace.name` when the rule changes.
    """
    messy = "  two words,and a comma  "
    store, row = _aStoredRow()
    view = TraceView(store, row)
    view.name = messy

    assert store.getName(row) == Trace(messy, (1, 2, 3)).name
    assert view.name == Trace(messy, (1, 2, 3)).name
    assert store.rowsForContour(messy) == [row]
    assert store.contourNames() == [Trace(messy, (1, 2, 3)).name]


def test_a_write_through_a_view_over_a_real_section_reaches_the_column(
        loaded_sections):
    """The write path on real material, not only on hand-built rows.

    Every test above builds its store with `appendRow`. This one builds it
    from a real section of the fixture series, writes every field of every row
    through a view, and checks the store's own readers -- so the write path is
    exercised against the same rows the read parity walk covers.
    """
    section = max(loaded_sections, key=lambda s: sum(len(c) for c in s.contours.values()))
    store = SectionColumns.fromSection(section)
    rows = [row for name in store.contourNames() for row in store.rowsForContour(name)]
    assert rows, "the busiest section of the fixture series holds no rows"

    generation = store.generation
    was_closed = {row: store.getFlag(row, "closed") for row in rows}
    for row in rows:
        view = TraceView(store, row)
        view.color = [7, 7, 7]
        view.closed = not view.closed
        view.negative = True
        view.hidden = True
        view.tags = {f"row{row}"}
        view.fill_mode = ("transparent", "selected")
        view.points = [(float(row), 0.0), (float(row), 1.0)]

    ## Seven writes per row, each one entry point, each one bump.
    assert store.generation == generation + 7 * len(rows)

    for row in rows:
        assert store.getColor(row) == [7, 7, 7]
        assert store.getFlag(row, "closed") is (not was_closed[row])
        assert store.getFlag(row, "negative") is True
        assert store.getFlag(row, "hidden") is True
        assert store.getTags(row) == {f"row{row}"}
        assert store.getFillMode(row) == ["transparent", "selected"]
        assert store.getPoints(row) == [(float(row), 0.0), (float(row), 1.0)]
        ## And a fresh view over the same row reads what the store reads.
        assert TraceView(store, row).points == store.getPoints(row)


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


# --- ContourView: the read half of the container protocol ---------------------
#
# `ContourView` is slice 7a: the read-only half of a `Contour`-shaped surface
# over the store's per-contour row index, mirroring the shape `TraceView` took
# in slices 4 and 6. It caches nothing, it mutates nothing, and nothing in the
# application references it. Its identity semantics arrived later, in 7b', and
# are the row's rather than the object's -- see the section at the bottom of
# this file.
#
# The bar is the same as `TraceView`'s and for the same reason: every contour of
# every populated section of both fixture series, every index, a battery of
# slices, and each element compared against BOTH a materialized `Trace` and the
# object-model `Trace` the section actually holds -- the second arm being what
# keeps the first from being vacuous.


## `Contour`'s whole defined surface, split three ways. Checked against
## `vars(Contour)` below rather than trusted, so a method added to `Contour`
## lands in no group and turns the split red instead of silently becoming a
## thing the view is missing.
## `index` moved groups in 7b': it is a pure read, and the row route answers it
## without a cache, an `__eq__` or an id comparison. `__contains__` is not in
## either group because `Contour` does not define it at all -- it comes along
## with `index` as the same question spelled twice.
CONTOUR_READ_ONLY_SURFACE = frozenset(
    {"__iter__", "__getitem__", "__len__", "isEmpty", "getTraces", "index"}
)
CONTOUR_IDENTITY_OR_MUTATION = frozenset(
    {"append", "remove", "importTraces", "__add__"}
)
CONTOUR_DEFERRED_ELSEWHERE = frozenset({"copy", "getBounds", "getMidpoint"})

## What Python puts on every class, plus the constructor, which both classes
## have and which is not part of the split.
CONTOUR_NOISE = frozenset(
    {"__dict__", "__doc__", "__module__", "__weakref__", "__init__"}
)


def test_contours_surface_is_split_exhaustively_between_this_slice_and_the_next():
    """The scope boundary, derived from `Contour` rather than asserted about it.

    Three groups, and their union must be exactly what `Contour` defines. A
    fourth method arriving on `Contour` fails here rather than quietly becoming
    a gap in the view, which is the same guard
    `test_the_view_carries_exactly_the_fields_a_trace_constructor_produces`
    gives `TraceView` against `Trace.__init__`.
    """
    defined = set(vars(Contour)) - CONTOUR_NOISE
    accounted = (CONTOUR_READ_ONLY_SURFACE | CONTOUR_IDENTITY_OR_MUTATION
                 | CONTOUR_DEFERRED_ELSEWHERE)
    assert defined == accounted, (
        f"Contour's surface and this suite's split have diverged: "
        f"{defined ^ accounted}"
    )

    ## The read half is present.
    for member in sorted(CONTOUR_READ_ONLY_SURFACE):
        assert hasattr(ContourView, member), f"ContourView is missing {member}"

    ## `index` is in the read group and is present. It got there in 7b' by
    ## matching on `TraceView.row`, which caches nothing and defines no `__eq__`
    ## -- so it is neither §5(A) nor §5(B), and it needed no D1 answer. It
    ## brought `__contains__`, which `Contour` does not define, with it.
    assert hasattr(ContourView, "__contains__")

    ## And nothing from the other two groups arrived with it. `copy` is the
    ## pattern table's whole-object-clone row, and the geometry pair waits on
    ## the batched coordinate pass that `TraceView` deliberately has no
    ## `getBounds` for.
    ##
    ## The identity-or-mutation group was 7b's, and 7b has now been attempted:
    ## the four that remain stay out, and the measured reasons are the section
    ## at the bottom of this file. This assertion is no longer "not yet" -- it
    ## is the standing statement that none of them may arrive without one of
    ## the read/write boundary, a store reorder decision (D9), or the §10
    ## id-carry rule (D10) being settled first.
    for member in sorted(CONTOUR_IDENTITY_OR_MUTATION | CONTOUR_DEFERRED_ELSEWHERE):
        assert not hasattr(ContourView, member), (
            f"ContourView carries {member}, which is a later slice's"
        )

    ## `traces` is absent deliberately: on a `Contour` it is the live list, and
    ## a fresh list handed out under that name would make an append to it a
    ## silent no-op. `getTraces()` is the copy-returning read surface, and it
    ## is what the production readers call.
    assert not hasattr(ContourView, "traces")

    ## `Contour` defines no `__contains__`, so `in` falls back to `__iter__`
    ## plus `==`; `ContourView` now defines one, over the row. What neither
    ## defines -- and what 7b' did NOT reach for, because it is §5(B) and
    ## `DECISIONS.md` rejects it -- is `__eq__`.
    assert "__contains__" not in vars(Contour)
    assert "__contains__" in vars(ContourView)
    assert "__eq__" not in vars(Contour)
    assert "__eq__" not in vars(ContourView)
    assert "__eq__" not in vars(Trace)
    assert "__eq__" not in vars(TraceView)

    ## `name` is read-only, for the reason `TraceView.row` is: a view that could
    ## be renamed would be pointed at a different contour, not a written one.
    assert ContourView.name.fget is not None
    assert ContourView.name.fset is None
    assert ContourView.name.fdel is None


def _assert_element_parity(store, view, trace):
    """One `TraceView` from a contour against the `Trace` at the same position,
    through the same two-armed comparison the row walk uses."""
    _assert_view_parity(view, store.materializeTrace(view.row), trace)


def _sliceBattery(n):
    """The slices worth taking of a contour of length `n`.

    `slice(i, None)` for every `i` in `0..n` is not padding: it is exactly the
    shape `Contour.importTraces` takes (`self[i:]` / `other[i:]`, at whatever
    index the optimistic positional walk stopped), which is the reason the
    bare-`list` return is load-bearing at all.
    """
    battery = [slice(i, None) for i in range(n + 1)]
    battery += [
        slice(None), slice(0, n), slice(None, 1), slice(None, -1),
        slice(-1, None), slice(0, 0), slice(n + 5, None), slice(-2, -1),
        slice(None, None, 2), slice(None, None, -1), slice(1, n - 1),
    ]
    return battery


def _assert_contour_parity(store, view, contour):
    """Every read `ContourView` carries, against a real `Contour`, exhaustively."""
    n = len(contour)

    assert len(view) == n
    assert view.name == contour.name
    assert view.isEmpty() == contour.isEmpty()
    assert type(view.isEmpty()) is bool

    ## Iteration: same order, same length, same iterator type. `list_iterator`
    ## on both sides -- `Contour.__iter__` returns `self.traces.__iter__()` and
    ## a generator here would be distinguishable from it by type.
    assert type(iter(view)) is type(iter(contour))
    viewed = list(view)
    assert len(viewed) == n
    for element, trace in zip(viewed, contour):
        _assert_element_parity(store, element, trace)

    ## getTraces: a bare list on both sides, same order, fresh each call.
    got = view.getTraces()
    expected = contour.getTraces()
    assert type(got) is list and type(expected) is list
    assert len(got) == len(expected) == n
    for element, trace in zip(got, expected):
        _assert_element_parity(store, element, trace)
    assert view.getTraces() is not got

    ## Every position, from both ends.
    for i in range(n):
        _assert_element_parity(store, view[i], contour[i])
        _assert_element_parity(store, view[i - n], contour[i - n])

    ## Every slice in the battery, against the real contour's own slice.
    for s in _sliceBattery(n):
        sliced = view[s]
        reference = contour[s]
        assert type(reference) is list, (
            f"Contour[{s}] stopped returning a bare list -- the premise this "
            f"whole class mirrors"
        )
        assert type(sliced) is list, (
            f"ContourView[{s}] returned {type(sliced).__name__}, not a bare "
            f"list; importTraces (slice 7b) walks and mutates this result"
        )
        assert len(sliced) == len(reference)
        for element, trace in zip(sliced, reference):
            _assert_element_parity(store, element, trace)

    ## Out of range and the wrong type raise what the underlying list raises,
    ## on both sides.
    for bad in (n, -n - 1):
        with pytest.raises(IndexError):
            contour[bad]
        with pytest.raises(IndexError):
            view[bad]
    with pytest.raises(TypeError):
        contour["not an index"]
    with pytest.raises(TypeError):
        view["not an index"]


def _walkContourParity(sections):
    """Every contour of every section, viewed against the real `Contour`."""
    contours = traces = multi = 0
    for section in sections:
        store = SectionColumns.fromSection(section)
        for name in store.contourNames():
            contour = section.contours[name]
            _assert_contour_parity(store, ContourView(store, name), contour)
            contours += 1
            traces += len(contour)
            multi += len(contour) > 1
    return contours, traces, multi


def test_every_contour_view_over_the_real_series_matches_its_contour(
        loaded_sections):
    """The headline container parity, over all ~221 contours of the real series."""
    contours, traces, multi = _walkContourParity(loaded_sections)
    assert contours > 200, f"expected the fixture's ~221 contours, walked {contours}"
    assert traces > 200, f"expected the fixture's ~232 traces, walked {traces}"
    assert multi, (
        "every contour walked held one trace, so indexing and slicing were "
        "never exercised past position zero"
    )


def test_every_contour_view_over_the_synthetic_series_matches_its_contour(
        synthetic_sections):
    """The same walk over the attribute domain the real fixture cannot carry.

    The elements are `TraceView`s, so a contour walk is also a field walk, and
    the real series has no tagged, negative or hidden trace to compare four of
    those fields against more than one value.
    """
    contours, traces, _ = _walkContourParity(synthetic_sections)
    assert contours, "the synthetic contour walk covered no contours at all"
    assert traces, "the synthetic contour walk covered no traces at all"


def test_a_contour_view_slice_is_a_bare_list_and_takes_what_importTraces_does(
        loaded_sections):
    """The load-bearing property, stated directly rather than only in the walk.

    `Contour.importTraces` -- slice 7b, not this one -- does this to the result
    of `self[i:]`: iterates it with `enumerate`, calls `.copy()` on it, calls
    `.pop(found_i)`, `+`-concatenates it, and takes `len()` of the contour it
    came from. All of that is `list` mechanics and all of it is exercised here
    on a `ContourView` slice, on a real multi-trace contour from the fixture.

    The one operation NOT exercised is `rem_o_traces.remove(o_trace)`, which
    resolves a trace to a position through `Trace`'s inherited `==` -- object
    identity. That is precisely the line that makes 7b a port rather than a
    mechanical translation, and it is out of this slice deliberately.
    """
    for section in loaded_sections:
        store = SectionColumns.fromSection(section)
        for name in store.contourNames():
            if len(section.contours[name]) > 2:
                break
        else:
            continue
        break
    else:
        pytest.fail("the fixture has no contour with more than two traces")

    contour = section.contours[name]
    view = ContourView(store, name)
    n = len(contour)

    remainder = view[1:]
    assert type(remainder) is list
    assert type(contour[1:]) is list
    assert len(remainder) == n - 1

    ## The exact operations importTraces performs on it.
    copied = remainder.copy()
    assert type(copied) is list and copied == remainder and copied is not remainder
    popped = remainder.pop(0)
    assert popped.row == store.rowsForContour(name)[1]
    assert len(remainder) == n - 2
    joined = remainder + view[:1]
    assert type(joined) is list and len(joined) == n - 1

    ## And the slice is in the contour's own order, positionally.
    rows = store.rowsForContour(name)
    assert [element.row for element in copied] == rows[1:]
    assert [index for index, _ in enumerate(copied)] == list(range(n - 1))
    assert [element.row for element in joined] == rows[2:] + rows[:1]

    ## Mutating the slice reached nothing behind it: the contour is unchanged.
    assert len(view) == n == len(contour)
    assert [element.row for element in view] == rows


def test_a_contour_view_holds_no_value_and_so_cannot_go_stale():
    """The no-cache property, asserted as behavior rather than as an absence.

    One `ContourView` instance, held across an append, a removal and a rename,
    reports the store's current answer every time. A view that memoized its row
    list would fail this without needing an invalidation mechanism to be
    reviewed, because it has no state to invalidate -- the same argument
    `test_a_view_holds_no_value_and_so_cannot_go_stale` makes for `TraceView`.
    """
    store = SectionColumns(1)
    first = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)],
                            color=[1, 2, 3])
    view = ContourView(store, "axon")
    assert len(view) == 1 and view.isEmpty() is False
    assert [element.row for element in view] == [first]

    second = store.appendRow(name="axon", points=[(2.0, 2.0), (3.0, 3.0)],
                             color=[4, 5, 6])
    assert len(view) == 2
    assert [element.row for element in view] == [first, second]
    assert view[1].points == [(2.0, 2.0), (3.0, 3.0)]

    ## A removal retires the row out of the index, and the view shortens.
    store.removeRow(first)
    assert len(view) == 1
    assert [element.row for element in view] == [second]

    ## A rename moves the row between contour indices, and the view follows the
    ## name, not the row -- the mirror image of `TraceView`, which follows the
    ## row and not the name.
    store.setAttribute(second, "name", "dendrite01")
    assert len(view) == 0 and view.isEmpty() is True
    assert list(view) == [] and view.getTraces() == []
    assert len(ContourView(store, "dendrite01")) == 1


def test_a_contour_view_over_an_unknown_name_is_an_empty_contour(loaded_sections):
    """A name the store has no rows for behaves as an empty `Contour` does.

    Which is also all the store can say about it: a contour with no rows has no
    entry in the index, so "empty" and "absent" are the same state there --
    exactly as `Section.contours` treats them, deleting the key the moment
    `isEmpty()` goes true (`section.py`, three sites).
    """
    store = SectionColumns.fromSection(loaded_sections[0])
    view = ContourView(store, "no_such_object")
    empty = Contour("no_such_object")

    assert len(view) == len(empty) == 0
    assert view.isEmpty() is empty.isEmpty() is True
    assert list(view) == list(empty) == []
    assert view.getTraces() == empty.getTraces() == []
    assert view[:] == empty[:] == []
    assert type(view[:]) is type(empty[:]) is list
    assert view[3:] == empty[3:] == []
    for bad in (0, -1):
        with pytest.raises(IndexError):
            empty[bad]
        with pytest.raises(IndexError):
            view[bad]


def test_a_contour_views_name_is_normalized_the_way_a_contour_key_is():
    """The name a view reports and the name it looks rows up under are one.

    `rowsForContour` normalizes its argument, so a view that kept the raw name
    would find rows under `"a_b"` while reporting itself as `"a b"`. Normalizing
    once in the constructor closes that rather than adding a rule: it is the
    same `normalizeObjectName` the store runs in `appendRow` and that
    `Trace.name`'s setter runs, which is why a real `Contour` holding traces
    can only ever be keyed by the normalized form.
    """
    store = SectionColumns(1)
    store.appendRow(name="a b, c", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    assert store.contourNames() == ["a_b__c"]

    for raw in ("a b, c", "  a b, c  ", "a_b__c"):
        view = ContourView(store, raw)
        assert view.name == normalizeObjectName(raw) == "a_b__c"
        assert len(view) == 1
        assert view[0].name == view.name

    ## And that is the form a real trace, and so a real contour key, takes.
    assert Trace("  a b, c  ", [1, 2, 3]).name == "a_b__c"


def test_a_contour_view_refuses_the_writes_it_has_no_property_for():
    """`__slots__`, for the reason `TraceView` has it.

    A view whose contract is that it holds no values must not let a misspelled
    or invented name land as an instance attribute and then read back
    convincingly. `name` is read-only for the same reason a `TraceView` cannot
    be repointed at another row.
    """
    store = SectionColumns(1)
    store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    view = ContourView(store, "axon")

    assert not hasattr(view, "__dict__")
    for attribute in ("traces", "nmae", "isempty", "_rows"):
        with pytest.raises(AttributeError):
            setattr(view, attribute, object())
    with pytest.raises(AttributeError):
        view.name = "dendrite01"
    assert view.name == "axon"


def test_constructing_a_contour_view_touches_no_column():
    """A contour view is as cheap as a tuple, like a row view.

    Construction reads nothing, indexes nothing and bumps nothing -- the only
    work it does is normalizing the name, which touches no column. Asserted on a
    store with no rows at all.
    """
    store = SectionColumns(1)
    generation = store.generation
    view = ContourView(store, "never appended")
    assert store.generation == generation
    assert view.name == "never_appended"
    assert len(view) == 0


def test_membership_is_object_identity_on_a_contour_and_row_identity_on_a_view():
    """The identity seam, pinned rather than papered over -- and where it moved.

    `Contour` defines no `__contains__`, so `in` falls through to the `__iter__`
    protocol and compares with `==`, which `Trace` does not define and so is
    CPython object identity. `ContourView` cannot answer that question at all:
    its elements are freshly built `TraceView`s, so no object a caller can hold
    is ever `is`-equal to one, not even the object it handed out one line ago.

    7a read that as "identity has no answer here" and left `index` and
    `__contains__` absent. 7b' answers it a different way -- by row -- which is
    what the two assertions in the middle of this test are. The divergence that
    survives is the last one: a materialized `Trace` holds no row and so is
    never a member, which is the honest answer rather than a guess and is the
    reason a caller holding real `Trace`s cannot use these methods at all.
    """
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)],
                          color=[1, 2, 3])
    view = ContourView(store, "axon")

    trace = store.materializeTrace(row)
    contour = Contour("axon", [trace])
    assert trace in contour, "Contour's membership is identity, via __iter__"
    assert contour.index(trace) == 0

    ## The mechanism has not changed: object identity still fails on the view.
    assert not any(element is view[0] for element in view)

    ## But the question now has an answer, and it is the row's.
    assert TraceView(store, row) in view
    assert view.index(view[0]) == 0

    ## And the divergence that does NOT go away.
    assert trace not in view
    with pytest.raises(ValueError):
        view.index(trace)


# --- ContourView: the identity and import seam (slices 7b and 7b') ------------
#
# Slice 7b was dispatched as "`importTraces` + identity ops on `ContourView`".
# Its first pass shipped no production code and argued that neither half could
# be built. Half of that argument was then falsified by construction
# (review-274 F1), and 7b' is the repair: `index` and `__contains__` are now built,
# by row, and the tests below are split into what ships and what is still
# blocked.
#
# WHAT THE FIRST PASS GOT WRONG, RECORDED BECAUSE THE TESTS BELOW USED TO ASSERT IT
# ---------------------------------------------------------------------------------
# It claimed identity through a view "can never match", and that the only two
# routes were design §5(A)'s cached identity-stable views (D1, open) and §5(B)'s
# equality-over-id (`DECISIONS.md`: REJECTED) -- so that "there is no third
# option that is merely mechanical".
#
# There is a third, and it is mechanical: match on `TraceView.row`. It caches
# nothing, defines no `__eq__`, compares no trace ids, and needs no D1 answer,
# because there is no cache for D1 to be about. The measurement the first pass
# made was exactly right -- zero object-identity hits on six routes over 221
# real contours -- and the inference from it was too strong. Both survive below:
# the measurement is still asserted, and the row route is asserted on the same
# six routes and the same 221 contours.
#
# WHAT REMAINS BLOCKED, ONE TEST EACH
# -----------------------------------
#   1. `remove` -- not because it cannot be built (it can, in three lines on top
#      of `_rowOf`) but because `Contour.remove` DETACHES an object that is
#      often re-added a line later, while `removeRow` TOMBSTONES the row for
#      good. Six of `Section.removeTrace`'s eleven callers go on using the
#      removed object; five mean the removal.
#      Measured in `test_remove_would_not_be_the_operation_contour_remove_is`.
#
#   2. `importTraces` calls two `Trace` methods `TraceView` deliberately lacks:
#      `overlaps` (the geometry family, deferred to the batched coordinate pass)
#      and `mergeTags` (outside the eight-field surface).
#
#   3. LIFTED. `importTraces` ends by rebinding `self.traces` to a REORDERED
#      list, and the store now has a purpose-built way to say so:
#      `reorderContour(name, rows)`, built for D9. What it replaces is a rename
#      round-trip -- `setAttribute(row, "name", ...)` appends the row at the end
#      of its destination contour, so a rename away and back was a move-to-end,
#      and n-1 of those realized any permutation with no renumbering and no held
#      view invalidated -- whose one cost was that the scratch name leaked into
#      `modified_contours`, and so into the scope of an undo snapshot. The round
#      trip is retired: the tests below keep it only to measure that the two
#      routes reach the same order and that only one of them stays quiet.
#
#   4. PARTLY LIFTED. That rebound list may hold traces belonging to the OTHER
#      contour, which is a contour of a different section of a different series
#      with a different store. `section.py` then calls `Contour.remove` on
#      exactly those objects, by identity. Adopting a foreign trace into this
#      store was an id-carry decision (design §10), not a mechanical append --
#      and D10 has since made it: `appendRow(foreign_id=...)` registers the id
#      with the local issuer and reissues-and-reports on a clash. The id half
#      is answered; which store the adopted row belongs to is not, and nothing
#      threads a foreign id through yet.


def _everyWayOfGettingAnElement(view):
    """The six ways a caller can obtain an element of a contour-shaped thing.

    Written out rather than testing one of them, because `remove`, `index` and
    `in` all take whatever the caller happens to be holding, and the question is
    whether ANY of those routes produces something a subsequent walk recognizes.
    """
    return {
        "the object __getitem__ just handed out": view[0],
        "the first element of getTraces()": view.getTraces()[0],
        "the first element of list(view)": list(view)[0],
        "the first element of a slice": view[:][0],
        "the first element of a second iteration": next(iter(view)),
        "the last element of a negative index": view[-len(view)],
    }


def test_object_identity_still_fails_on_every_route_but_row_identity_answers(
        loaded_sections):
    """The 7b measurement and the 7b' repair, on the same real material.

    Two arms that must BOTH hold, because each is what makes the other mean
    something.

    The first is 7b's own measurement, kept verbatim and still true: object
    identity fails on every route. `Contour.remove(t)` is `self.traces.remove(t)`,
    which walks with `==`, which `Trace` does not define -- so it is `is`. Every
    route to an element of a `ContourView` builds a new `TraceView`, so `is`
    answers False for all six, including the object the container handed out one
    line earlier. If this arm ever goes green the other way, a caching or
    identity mechanism has arrived and D1 has been answered by accident.

    The second is the repair. The first pass concluded from the arm above that
    "there is no third option that is merely mechanical" and left `index` and
    `__contains__` unbuilt. There is one: `TraceView.row`. It caches nothing and
    defines no `__eq__`, so it is neither §5(A) nor the rejected §5(B), and it
    resolves all six routes on all 221 contours -- which is what this arm walks.

    The contrast arm on the real `Contour` stays, because it is what makes the
    first arm a divergence rather than a tautology about views.
    """
    checked = 0
    for section in loaded_sections:
        store = SectionColumns.fromSection(section)
        for name in store.contourNames():
            contour = section.contours[name]
            view = ContourView(store, name)

            for label, candidate in _everyWayOfGettingAnElement(view).items():
                ## Arm 1: object identity, still zero hits.
                assert not any(element is candidate for element in view), (
                    f"{label} is identically an element of the view -- a "
                    f"caching or identity mechanism has arrived and D1 has "
                    f"been answered by accident"
                )
                ## Arm 2: row identity, which answers where `is` cannot.
                assert candidate in view, (
                    f"{label} is not a member by row -- 7b's identity ops have "
                    f"regressed"
                )
                assert view.index(candidate) == 0, label

            ## The same six routes on the real Contour, which is what makes the
            ## first arm a divergence rather than a tautology about views.
            for label, candidate in _everyWayOfGettingAnElement(contour).items():
                assert any(element is candidate for element in contour), label
                assert candidate in contour, label

            assert contour.index(contour[0]) == 0
            ## The one identity op still absent, and the test below says why.
            assert not hasattr(view, "remove")
            checked += 1

    assert checked > 200, f"expected the fixture's ~221 contours, walked {checked}"


def test_a_materialized_trace_is_never_a_member_however_it_was_built(
        loaded_sections):
    """The divergence from `Contour` that 7b' does NOT erase.

    Row identity answers for things that HAVE a row. A `Trace` does not: it is
    an object built outside the store, and `materializeTrace` builds a fresh one
    on every call, so there is nothing for `_rowOf` to match. That is the honest
    answer rather than a guess, and it is the reason a caller still holding real
    `Trace`s cannot reach for these methods at all -- which is exactly what the
    slice that flips consumers has to know.

    Pinned on the real series and not on a synthetic row, because the failure
    mode this guards is a later slice quietly teaching `_rowOf` to fall back on
    matching by trace id, coordinates or name -- any of which would make a
    materialized trace a member here and would be §5(B) arriving under another
    name.

    The three other non-members are pinned too: a view over a different store, a
    view over a different contour of this store, and a view over a row this
    contour no longer holds.
    """
    checked = 0
    for section in loaded_sections:
        store = SectionColumns.fromSection(section)
        other_store = SectionColumns.fromSection(section)
        for name in store.contourNames():
            view = ContourView(store, name)
            rows = store.rowsForContour(name)

            trace = store.materializeTrace(rows[0])
            assert trace not in view, (
                "a materialized Trace became a member -- identity is no longer "
                "the row, and equality-over-id (§5(B), REJECTED) may have "
                "arrived under another name"
            )
            with pytest.raises(ValueError):
                view.index(trace)

            ## Same row number, different store: not this contour's row.
            assert TraceView(other_store, rows[0]) not in view

            ## Same store, a row of some other contour.
            foreign = [row for row in range(store.rowCount)
                       if store.isLive(row) and row not in rows]
            if foreign:
                assert TraceView(store, foreign[0]) not in view

            checked += 1

    assert checked > 200, f"expected the fixture's ~221 contours, walked {checked}"


def test_a_removed_rows_view_stops_being_a_member_immediately():
    """Membership tracks the index, because it re-reads it on every call.

    `ContourView` caches nothing, so `__contains__` and `index` answer against
    the row list as it is now. A view over a row that has since been removed is
    not a member, and `index` raises rather than returning a stale position --
    which is the behavior a caller doing `if v in contour: contour.index(v)`
    depends on and the one a cached implementation would have to work to keep.
    """
    store = SectionColumns(1)
    rows = [store.appendRow(name="axon", points=[(float(i), 0.0), (float(i), 1.0)],
                            color=[1, 2, 3])
            for i in range(3)]
    view = ContourView(store, "axon")
    held = [TraceView(store, row) for row in rows]

    assert [view.index(v) for v in held] == [0, 1, 2]

    store.removeRow(rows[0])
    assert held[0] not in view
    with pytest.raises(ValueError):
        view.index(held[0])
    ## And the survivors' positions moved, as they do in a list.
    assert [view.index(v) for v in held[1:]] == [0, 1]


def _outermostFunctions(tree):
    """Every function in `tree` that is not nested inside another function.

    Nested functions are folded into their enclosing one rather than reported
    separately, because `series.py`'s deletion methods do their removing inside
    a local `edit(section)` closure passed to `_forEachObjectSection`: the
    caller a reader would name is the method, not the closure.
    """
    found = []

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append(child)   # deliberately not descending
            else:
                visit(child)          # class bodies, `if`/`try` blocks, ...

    visit(tree)
    return found


def _removeTraceCallersIn(paths, root):
    """Map `"<path>:<function>" -> does that function re-add what it removed?`

    The classifier is `addTrace` appearing anywhere in the same function, which
    is what separates `Section.editTraceAttributes` (remove / mutate / add the
    same object) and `Series.splitObject` (remove / `.copy()` / add the copy)
    from `Section.deleteTraces` and `series.py`'s four deletion methods, which
    mean the removal.

    Takes the paths rather than finding them, so the test below can point it at
    a source file of its own and watch the classification move.
    """
    callers = {}
    for path in sorted(paths):
        for function in _outermostFunctions(ast.parse(path.read_text(encoding="utf-8"))):
            calls = {call.func.attr for call in ast.walk(function)
                     if isinstance(call, ast.Call)
                     and isinstance(call.func, ast.Attribute)}
            if "removeTrace" in calls:
                key = f"{path.relative_to(root).as_posix()}:{function.name}"
                callers[key] = "addTrace" in calls
    return callers


def _removeTraceCallers():
    """`_removeTraceCallersIn` over the whole `PyReconstruct` package.

    Over the package, not over `inspect.getsource(Section)`, which is what an
    earlier draft walked: a walk of one class sees six of the eleven callers
    and is structurally blind to the five in `series.py` -- four of them
    unconditional deletions, which is how "only `deleteTraces` means it" got
    into a docstring (review-274 N1/N2).
    """
    from PyReconstruct.modules.datatypes import section

    root = Path(inspect.getfile(section)).parents[2]
    assert root.name == "PyReconstruct", root
    return _removeTraceCallersIn(root.rglob("*.py"), root)


def test_the_removeTrace_caller_walk_sees_series_py_and_reclassifies_on_change(tmp_path):
    """The tripwire's own tripwire: does the walk move when the call graph does?

    A count nobody has watched change is not evidence. Two things are checked
    here, both against source this test writes itself:

      * a caller outside `class Section` is seen at all -- the failure that put
        "five of six" into production source; and
      * a caller that starts re-using the object it removed is *reclassified*,
        not merely counted, so the ratio the `remove` argument rests on cannot
        drift silently in either direction.
    """
    package = tmp_path / "PyReconstruct"
    package.mkdir()
    (package / "section.py").write_text(
        "class Section:\n"
        "    def deleteTraces(self, traces):\n"
        "        for trace in traces:\n"
        "            self.removeTrace(trace)\n",
        encoding="utf-8",
    )
    ## Outside any class, and inside a nested closure: both of the shapes the
    ## old `inspect.getsource(Section)` walk could not see.
    (package / "series.py").write_text(
        "class Series:\n"
        "    def splitObject(self, name):\n"
        "        def edit(section):\n"
        "            for trace in section.contours[name]:\n"
        "                section.removeTrace(trace)\n"
        "                section.addTrace(trace.copy())\n"
        "        self._forEachObjectSection(edit)\n",
        encoding="utf-8",
    )

    before = _removeTraceCallersIn(package.rglob("*.py"), package)
    assert before == {"section.py:deleteTraces": False,
                      "series.py:splitObject": True}, before

    ## Now make the unconditional deletion re-use what it removed. The count is
    ## unchanged; the classification is not.
    (package / "section.py").write_text(
        "class Section:\n"
        "    def deleteTraces(self, traces):\n"
        "        for trace in traces:\n"
        "            self.removeTrace(trace)\n"
        "            self.addTrace(trace)\n",
        encoding="utf-8",
    )
    after = _removeTraceCallersIn(package.rglob("*.py"), package)
    assert len(after) == len(before)
    assert after["section.py:deleteTraces"] is True
    assert sum(after.values()) == sum(before.values()) + 1

    ## And a new caller anywhere in the package enters the set.
    (package / "gui.py").write_text(
        "def someHandler(section, trace):\n"
        "    section.removeTrace(trace)\n",
        encoding="utf-8",
    )
    grown = _removeTraceCallersIn(package.rglob("*.py"), package)
    assert set(grown) - set(after) == {"gui.py:someHandler"}


def test_remove_would_not_be_the_operation_contour_remove_is():
    """Blocker 1, in what survives of it: `remove` is buildable and is not built.

    Row identity makes `ContourView.remove` mechanical -- `removeRow(row)` once
    `_rowOf` has the row. It is still absent, for two reasons, and this test
    pins the second because it is the one that is not a matter of taste.

    `Contour.remove(trace)` DETACHES: the object survives the call and is often
    re-added a line later. `Section.removeTrace` is its only production caller
    besides `importTraces`, and six of `removeTrace`'s own eleven callers go on
    using the removed object afterwards -- five of them are remove / mutate /
    add on the same object (`Section.editTraceAttributes`, `editTraceRadius`,
    `editTraceShape`, `makeNegative`, `translateTraces`) and the sixth,
    `Series.splitObject`, is remove / `.copy()` / add-the-copy. The other five
    mean the removal: `Section.deleteTraces` and, in `series.py`,
    `deleteObjects`, `deleteAllTraces`, `deleteMalformedTraces` and
    `deleteDuplicateTraces`. `SectionColumns.removeRow` TOMBSTONES: the row
    number retires and every view over it raises from then on, so the *mutate*
    step has nothing left to write through, as this test measures.

    An earlier draft of this test said "five of six, and only `deleteTraces`
    means it". That count came from an AST walk over `inspect.getsource(Section)`
    -- one class -- which cannot see the five callers that live in `series.py`,
    four of which are unconditional deletions too. The walk below is over the
    whole `PyReconstruct` package for that reason.

    A `ContourView.remove` would therefore be a differently-shaped operation
    under `Contour.remove`'s name. Whether the shim carries it anyway is the
    write half's call; this fails the day it is made, so it cannot be made
    silently.
    """
    assert not hasattr(ContourView, "remove")
    assert not hasattr(ContourView, "append")

    ## The remove/mutate/add shape, read out of the package with an AST walk
    ## rather than asserted from memory, so "six of eleven" has a source and
    ## changes shape loudly if the call graph does.
    readds = _removeTraceCallers()

    assert set(readds) == {
        "modules/datatypes/section.py:editTraceAttributes",
        "modules/datatypes/section.py:editTraceRadius",
        "modules/datatypes/section.py:editTraceShape",
        "modules/datatypes/section.py:makeNegative",
        "modules/datatypes/section.py:translateTraces",
        "modules/datatypes/section.py:deleteTraces",
        "modules/datatypes/series.py:deleteObjects",
        "modules/datatypes/series.py:deleteAllTraces",
        "modules/datatypes/series.py:deleteMalformedTraces",
        "modules/datatypes/series.py:deleteDuplicateTraces",
        "modules/datatypes/series.py:splitObject",
    }, readds
    assert len(readds) == 11, readds
    assert sum(readds.values()) == 6, (
        f"the remove/mutate/add shape has changed: {readds}. The argument for "
        f"keeping `remove` off the view rests on it."
    )
    ## The five that mean the removal -- named, so a caller that starts reusing
    ## the object it just removed flips one of these and fails here.
    assert [key for key, readd in sorted(readds.items()) if not readd] == [
        "modules/datatypes/section.py:deleteTraces",
        "modules/datatypes/series.py:deleteAllTraces",
        "modules/datatypes/series.py:deleteDuplicateTraces",
        "modules/datatypes/series.py:deleteMalformedTraces",
        "modules/datatypes/series.py:deleteObjects",
    ], readds

    ## And the reason that shape cannot route through `removeRow`: the object
    ## the object model would go on mutating is dead here.
    store = SectionColumns(1)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)],
                          color=[1, 2, 3])
    held = TraceView(store, row)
    store.removeRow(row)
    with pytest.raises(IndexError):
        held.points = [(5.0, 5.0), (6.0, 6.0)]
    with pytest.raises(IndexError):
        held.points

    ## Whereas the object model's `remove` leaves the trace fully usable.
    trace = Trace("axon", color=(1, 2, 3))
    trace.points = [(0.0, 0.0), (1.0, 1.0)]
    contour = Contour("axon", [trace])
    contour.remove(trace)
    trace.points = [(5.0, 5.0), (6.0, 6.0)]
    assert trace.points == [(5.0, 5.0), (6.0, 6.0)]


def test_the_import_walk_needs_two_trace_methods_the_row_view_does_not_carry():
    """Blocker 2: `importTraces` calls `overlaps` and `mergeTags` on its elements.

    Both are on `Trace` and neither is on `TraceView`, each for a reason that
    predates this slice and that this slice is not entitled to overturn:

      * `overlaps` is the geometry family. `TraceView` carries no `getBounds`,
        no `getCentroid` and no `getOverlapRatio` because the rewiring plan's
        pattern table makes geometry a batched whole-section pass over the
        coordinate column. Adding a per-trace `overlaps` here would ship the
        exact per-trace shape that work exists to replace.
      * `mergeTags` is outside the eight fields `Trace.__init__` assigns, which
        is `TraceView`'s whole stated surface.

    A tripwire in both directions: it fails if `TraceView` grows either method
    (7b's second blocker is then lifted) and it fails if `Contour.importTraces`
    stops calling either (the port's shape has changed).
    """
    source = inspect.getsource(Contour.importTraces)
    for method in ("overlaps", "mergeTags"):
        assert f".{method}(" in source, (
            f"Contour.importTraces no longer calls {method} -- the port this "
            f"test describes has changed shape"
        )
        assert hasattr(Trace, method)
        assert not hasattr(TraceView, method), (
            f"TraceView has grown {method}; 7b's geometry/surface blocker is "
            f"lifted and the import walk may now be portable"
        )

    ## Not a private naming accident: the geometry family is absent wholesale.
    for geometry in ("getBounds", "getMidpoint", "getCentroid", "getRadius",
                     "getFeret", "getOverlapRatio", "pointsMatch"):
        assert hasattr(Trace, geometry)
        assert not hasattr(TraceView, geometry)


def _threeRowContour():
    """A fresh store holding one three-row contour, tracking already cleared."""
    store = SectionColumns(1)
    rows = [store.appendRow(name="axon", points=[(float(i), 0.0), (float(i), 1.0)],
                            color=[1, 2, 3])
            for i in range(3)]
    assert store.rowsForContour("axon") == rows == [0, 1, 2]
    store.clearTracking()
    return store, rows


## The argument shapes a within-contour reorder entry point could plausibly
## take, as `(positional, keyword)` pairs. Not an exhaustive fuzz: the point is
## that the probe below is driven by what an API *does* when called, not by what
## it is *called*, so a reorder added under a name nobody guessed is still
## found. The keyword and callable shapes are here because name-independence was
## not enough on its own: review-274 N3 planted `arrangeContour(name, *, order)`
## and `sortContourBy(name, key)`, both capability-identical reorders, and both
## escaped a matrix of positional tuples by raising `TypeError` on every one.
_REORDER_PROBE_ARGUMENTS = (
    (("axon", [2, 1, 0]), {}),          # reindexContour(name, rows)
    (([2, 1, 0], "axon"), {}),
    (([2, 1, 0],), {}),
    (("axon", 0, 2), {}),               # moveWithinContour(name, from, to)
    (("axon", 2, 0), {}),
    ((0, 2), {}),                       # moveRow(row, position) / swapRows(a, b)
    ((2, 0), {}),
    ((0, -1), {}),
    (("axon", 2), {}),
    (("axon",), {}),
    ((2,), {}),
    ## Keyword-only orders: arrangeContour(name, *, order) and its spellings.
    (("axon",), {"order": [2, 1, 0]}),
    (("axon",), {"rows": [2, 1, 0]}),
    (("axon",), {"indices": [2, 1, 0]}),
    ((), {"name": "axon", "order": [2, 1, 0]}),
    ((), {"name": "axon", "rows": [2, 1, 0]}),
    ## Sort-by-callable: sortContourBy(name, key), positionally and by keyword.
    (("axon", (lambda row: -row)), {}),
    (("axon",), {"key": (lambda row: -row)}),
    (("axon",), {"reverse": True}),
    ((), {"name": "axon", "key": (lambda row: -row)}),
)


def _entryPointsThatReorderCleanly():
    """Every public callable on `SectionColumns` that reorders a contour cleanly.

    "Cleanly" is the whole definition, and it is behavioral rather than nominal:
    after one call, the contour's row list is a **different order of the same
    rows**, every one of those rows is still live, and nothing foreign has
    entered the tracking sets. That is what a purpose-built reorder API would
    do, whatever it were named.

    A fresh store per attempt, because a probe that shared one would let an
    earlier call's damage answer a later call's question.
    """
    found = []
    for name in dir(SectionColumns):
        if name.startswith("_"):
            continue
        if not callable(getattr(SectionColumns, name, None)):
            continue
        for arguments, keywords in _REORDER_PROBE_ARGUMENTS:
            store, rows = _threeRowContour()
            try:
                getattr(store, name)(*arguments, **keywords)
            except Exception:
                continue
            after = store.rowsForContour("axon")
            if sorted(after) != sorted(rows) or after == rows:
                continue                       # not a reorder of the same rows
            if not all(store.isLive(row) for row in rows):
                continue                       # rows were retired: not clean
            if store.getAllModifiedNames() - {"axon"}:
                continue                       # a foreign name leaked: not clean
            found.append((name, (arguments, keywords), after))
    return found


def test_exactly_one_entry_point_reorders_a_contour_cleanly():
    """Blocker 3's tripwire, inverted by D9's answer. It now names the API.

    This assertion used to be `found == []`, with the message "SectionColumns
    can now reorder a contour cleanly ... D9 has been answered by an
    implementation". D9 has been answered by an implementation, so the tripwire
    becomes the acceptance test for it -- and it is a good one precisely because
    it was not written for `reorderContour`: it was written to catch a reorder
    *whatever it was named and whatever its signature*, so what it certifies
    here is capability, not spelling. "Cleanly" is still `_entryPointsThatReorder
    Cleanly`'s own definition, unchanged: after ONE call the contour holds the
    same rows in a different order, every one of them is still live, and nothing
    foreign has entered the tracking sets.

    Exactly one, and that is the second half of the assertion. The decision was
    to build a reorder entry point and retire the round trip, not to grow a
    family of them; a second clean reorder arriving under some other name would
    mean the store had two ways to say one thing, which is what the probe
    catches for free.

    What the probe still cannot reach, and deliberately: the two routes that
    predate the entry point. Destroy-and-rebuild takes many calls and renumbers;
    the `setAttribute` rename round-trip takes two calls and leaks a name. Each
    keeps its own test below, because their costs are what the new entry point
    is measured against.
    """
    found = _entryPointsThatReorderCleanly()
    assert sorted({entry[0] for entry in found}) == ["reorderContour"], (
        f"the clean single-call reorder is not (only) reorderContour: {found}"
    )
    assert all(entry[2] == [2, 1, 0] for entry in found), found

    ## The two docstring pins the first pass relied on. Still true, and still
    ## the reason the entry point had to be built rather than assembled out of
    ## these two: an append cannot insert and a removal cannot come back.
    assert "An append, never an insert" in SectionColumns.appendRow.__doc__
    assert "is not reused" in SectionColumns.removeRow.__doc__


def test_the_reorder_tripwire_fires_on_a_reorder_added_under_an_unguessed_name(
        monkeypatch):
    """The tripwire above, tested against the mutation that escaped the old one.

    This is the review's seventh planted mutation, brought inside the suite: a
    real within-contour reorder named `reindexContour`, a name containing none
    of the four substrings the old assertion searched for. Both halves are
    asserted -- that the old nominal check would have passed it, and that the
    new behavioral one does not -- because a tripwire nobody has watched fail is
    not yet evidence of anything.
    """
    def reindexContour(self, name, rows):
        """Set a contour's rows to exactly this order: a within-contour reorder."""
        assert sorted(rows) == sorted(self._index[name])
        self._index[name] = list(rows)
        self._bump()

    monkeypatch.setattr(SectionColumns, "reindexContour", reindexContour,
                        raising=False)

    ## The old check, on the mutated class: `reindexContour` is invisible to
    ## it. Asserted as a membership rather than as the old literal list, because
    ## `reorderContour` now answers that substring search legitimately and the
    ## property being demonstrated was never about how many names matched -- it
    ## is that a real reorder can carry a name that matches none of them.
    named = [m for m in dir(SectionColumns)
             if any(k in m.lower() for k in ("insert", "reorder", "move", "swap"))]
    assert "reindexContour" not in named, (
        "the old name-substring check no longer passes on `reindexContour`, so "
        "this test is no longer demonstrating what it claims"
    )

    ## The new one, on the same class: it fires. Deduplicated by name, because
    ## the widened matrix reaches this signature by three spellings.
    ## `reorderContour` is found alongside it and that is the point of the
    ## test above; what this one adds is that the planted twin is found too.
    found = _entryPointsThatReorderCleanly()
    assert sorted({entry[0] for entry in found}) == ["reindexContour",
                                                     "reorderContour"], found
    assert all(entry[2] == [2, 1, 0] for entry in found), found


def test_the_reorder_tripwire_fires_on_reorders_whose_SIGNATURE_is_unguessed(
        monkeypatch):
    """The same tripwire against the second escape door: argument shape.

    Name-independence was demonstrated above and is not the whole story. The
    probe calls candidates with a matrix of argument shapes and swallows every
    exception, so a capability-identical reorder whose signature is outside the
    matrix used to raise `TypeError`, be swallowed, and never be probed at all
    (review-274 N3). These are the reviewer's two escaping mutations, verbatim:
    one keyword-only, one taking a callable. Both are caught now.
    """
    def arrangeContour(self, name, *, order):
        """Keyword-only: a capability-identical reorder the old matrix missed."""
        assert sorted(order) == sorted(self._index[name])
        self._index[name] = list(order)
        self._bump()

    def sortContourBy(self, name, key):
        """Takes a callable: also outside the old matrix."""
        self._index[name] = sorted(self._index[name], key=key)
        self._bump()

    for reorder in (arrangeContour, sortContourBy):
        monkeypatch.setattr(SectionColumns, reorder.__name__, reorder,
                            raising=False)
        ## Neither name contains "insert", "reorder", "move" or "swap" either,
        ## so the old nominal check is not what is doing the work here.
        assert not any(k in reorder.__name__.lower()
                       for k in ("insert", "reorder", "move", "swap"))
        found = _entryPointsThatReorderCleanly()
        ## Deduplicated: more than one shape in the matrix may reach the same
        ## method (`arrangeContour` answers both the keyword-only spelling and
        ## the all-keywords one), and what is being asserted is that it is
        ## reached at all.
        assert sorted({entry[0] for entry in found}) == sorted(
            [reorder.__name__, "reorderContour"]), found
        assert all(entry[2] == [2, 1, 0] for entry in found), found
        monkeypatch.delattr(SectionColumns, reorder.__name__)


def test_the_setAttribute_round_trip_reorders_without_renumbering_but_pollutes():
    """The RETIRED route, kept as the measurement D9 was decided on.

    Nothing calls this pattern any more -- `reorderContour` is the entry point,
    and the tests below are what exercise it. What this one holds is the
    evidence: the round trip really does reorder without renumbering, so the
    entry point replaces a working mechanism rather than a broken one, and its
    justification is the last three assertions here and nothing else. If those
    ever stop firing, the reason `reorderContour` exists has changed and the
    decision behind it wants re-reading.

    The first pass claimed "there is no reorder, insert, move or swap" and that
    "the only reorder available is destroy-and-rebuild, which renumbers every
    row and kills every `TraceView` a caller holds". The second half is true of
    destroy-and-rebuild (the next test measures it) and false as a statement
    about the store, as review-274 F2 demonstrated by construction.

    `setAttribute(row, "name", ...)` moves a row between contour indices and
    **appends it at the end of the destination** -- its own docstring says so.
    So renaming a row away and back is a move-to-end primitive, and n-1 of those
    realize any permutation. This test reverses a three-row contour with nothing
    but `setAttribute`, and measures that no row is renumbered, no row is
    tombstoned, and every held `TraceView` is still alive and still points where
    it did.

    The cost is real but much smaller than a missing capability, and it is the
    last two assertions: the temporary name leaks into `modified_contours` and
    into `getAllModifiedNames`, which is the scope of an undo snapshot. That
    leak, not the absence of an API, is what D9 asks about.
    """
    store, rows = _threeRowContour()
    held = [TraceView(store, row) for row in rows]
    before = [view.points for view in held]

    def moveToEnd(row):
        store.setAttribute(row, "name", "__reorder_tmp__")
        store.setAttribute(row, "name", "axon")

    for row in (1, 0):
        moveToEnd(row)

    ## The order importTraces would have wanted, and at none of the stated cost.
    assert store.rowsForContour("axon") == [2, 1, 0]
    assert [row for row in range(store.rowCount) if store.isLive(row)] == rows
    assert [view.row for view in held] == rows, "a row was renumbered"
    assert [view.points for view in held] == before, "a held view was invalidated"

    ## The view sees the new order too, which is the property a port would need.
    view = ContourView(store, "axon")
    assert [element.row for element in view] == [2, 1, 0]
    assert [view.index(element) for element in held] == [2, 1, 0]

    ## And the cost that is actually paid. `__reorder_tmp__` is not a contour --
    ## it holds no rows -- but every consumer of the tracking sets sees it.
    assert "__reorder_tmp__" not in store.contourNames()
    assert store.modified_contours == {"axon", "__reorder_tmp__"}
    assert store.getAllModifiedNames() == {"axon", "__reorder_tmp__"}


def test_destroy_and_rebuild_reorders_quietly_and_costs_the_row_numbers():
    """The other retired route, and the other half of what D9 chose between.

    `Contour.importTraces` ends with `self.traces = traces`, and `traces` is
    built as [matched duplicates, in positional order] + rem_s + rem_o -- a
    different order from the one the contour had. Three routes now reach that
    order. The round-trip above leaves the tracking sets dirty; this one leaves
    them clean and pays in row numbers instead: every row is renumbered and
    every `TraceView` anyone was holding is dead. `reorderContour` pays neither,
    which is the whole of why it was built, and this test is one of the two
    prices it is measured against.

    The name of this test used to begin "the only clean reorder is". It was not
    the only one even then -- the round trip above renumbers nothing -- and it
    is now not the clean one either.
    """
    store, rows = _threeRowContour()
    held = [TraceView(store, row) for row in rows]

    ## Ask for the reverse order, the clean way.
    for row in reversed(rows):
        store.removeRow(row)
    rebuilt = [store.appendRow(name="axon",
                               points=[(float(i), 0.0), (float(i), 1.0)],
                               color=[1, 2, 3])
               for i in (2, 1, 0)]

    ## The order is now what importTraces wanted -- at the stated price.
    assert store.rowsForContour("axon") == rebuilt == [3, 4, 5]
    assert not set(rebuilt) & set(rows), "row numbers were reused"
    for view in held:
        with pytest.raises(IndexError):
            view.points

    ## The price it does NOT pay, which is the whole of the contrast with the
    ## round-trip above: no name that is not a real contour enters the tracking.
    assert store.getAllModifiedNames() == {"axon"}


# =============================================================================
# `reorderContour`: D9's answer, and what it is required to cost
# =============================================================================
#
# The two tests above are the two routes that existed before it, each measured
# with its own price attached: the rename round trip renumbers nothing and leaks
# a scratch name into the undo scope, and destroy-and-rebuild keeps the tracking
# honest and renumbers every row. D9 decided that neither price is one a shim
# may impose silently and that the store should grow an entry point that pays
# neither. These tests are that entry point's acceptance: they assert each half
# of both prices is *not* paid, rather than asserting the method exists.


def _rowStateForComparison(store):
    """Everything observable about a store's rows, EXCEPT the generation.

    Used to compare two routes to the same reorder. The generation is
    deliberately outside this: the routes differ in how many mutations they
    take, so a comparison including it would compare bookkeeping rather than
    outcome, and the difference is asserted separately where it is the point.
    """
    return {
        "contours": store.contourNames(),
        "rows": {name: store.rowsForContour(name) for name in store.contourNames()},
        "live": [row for row in range(store.rowCount) if store.isLive(row)],
        "row_count": store.rowCount,
        "names": [store.getName(row) for row in range(store.rowCount)],
        "points": {row: store.getPoints(row)
                   for row in range(store.rowCount) if store.isLive(row)},
        "colors": {row: store.getColor(row)
                   for row in range(store.rowCount) if store.isLive(row)},
        "tags": {row: store.getTags(row)
                 for row in range(store.rowCount) if store.isLive(row)},
    }


def test_reorderContour_reorders_without_renumbering_or_invalidating_a_view():
    """The first two prices, neither paid: no row moves and no view dies.

    The same reversal the round-trip test performs, in one call. Every
    assertion here has a counterpart in one of the two tests above, which is why
    they are worth reading side by side: `[view.row for view in held] == rows`
    is the round trip's promise kept, and `view.points` not raising is
    destroy-and-rebuild's failure avoided.
    """
    store, rows = _threeRowContour()
    held = [TraceView(store, row) for row in rows]
    before = [view.points for view in held]
    ## Not zero: the counter is monotonic and `clearTracking` deliberately does
    ## not reset it, so the three appends are already in it.
    generation = store.generation

    store.reorderContour("axon", [2, 1, 0])

    ## The order `importTraces` would have wanted, in one call.
    assert store.rowsForContour("axon") == [2, 1, 0]

    ## Nothing was renumbered and nothing was tombstoned: the live rows are the
    ## rows that were there, under the numbers they had.
    assert [row for row in range(store.rowCount) if store.isLive(row)] == rows
    assert store.rowCount == len(rows), "a row was appended by a reorder"
    assert len(store) == len(rows)

    ## Every held view still reads its own row's own values.
    assert [view.row for view in held] == rows, "a row was renumbered"
    assert [view.points for view in held] == before, "a held view was invalidated"
    assert [view.name for view in held] == ["axon"] * 3

    ## And the contour view sees the new order, which is the property the
    ## `importTraces` port would consume.
    view = ContourView(store, "axon")
    assert [element.row for element in view] == [2, 1, 0]
    assert [view.index(element) for element in held] == [2, 1, 0]

    ## One mutation, so one bump.
    assert store.generation == generation + 1


def test_reorderContour_marks_the_contour_and_leaks_no_scratch_name():
    """The third price, not paid: the review's own finding, closed.

    review-274 F2 reproduced `modified_contours == {'axon', '__tmp__'}` after a
    round-trip reorder, with `'__tmp__' not in contourNames()` -- a name in the
    scope of an undo snapshot that names no contour. That is the finding D9 was
    raised by, and this is the test that it cannot happen through the entry
    point: the tracking sets hold the reordered contour and nothing else, and
    every name in them is a real contour.

    Marking the contour at all is a decision rather than an oversight, and it is
    the second assertion here. A reorder changes no trace, but within-contour
    order is serialized, so a reordered contour is a different section file that
    dirty/save detection has to see; and `SectionStates.addState` takes
    `getAllModifiedNames()` as the scope of the undo snapshot, so a reorder
    outside that scope would be a change the user could not undo.
    """
    store, rows = _threeRowContour()
    store.reorderContour("axon", [2, 1, 0])

    assert store.modified_contours == {"axon"}
    assert store.getAllModifiedNames() == {"axon"}
    assert store.added_rows == [] and store.removed_rows == []

    ## The F2 assertion, inverted: every tracked name is a contour that exists.
    assert store.getAllModifiedNames() <= set(store.contourNames())


def test_reorderContour_and_the_round_trip_reach_the_same_state():
    """Equivalence: the mechanism changed, the observable outcome did not.

    Both routes run on two independently built stores from the same starting
    point, and every row-level observable is compared -- the index, the live
    rows, the row count, the names, and each row's points, color and tags. They
    agree, which is what makes this a change of mechanism rather than of
    behavior.

    The two places they do NOT agree are asserted too, because a test that only
    checked the agreement would be hiding the reason for the change. The round
    trip takes four mutations to the entry point's one, and it ends with a name
    in the undo scope that names nothing.
    """
    clean, rows = _threeRowContour()
    dirty, dirty_rows = _threeRowContour()
    assert rows == dirty_rows
    assert _rowStateForComparison(clean) == _rowStateForComparison(dirty)
    assert clean.generation == dirty.generation
    started_at = clean.generation

    clean.reorderContour("axon", [2, 1, 0])
    for row in (1, 0):
        dirty.setAttribute(row, "name", "__reorder_tmp__")
        dirty.setAttribute(row, "name", "axon")

    assert _rowStateForComparison(clean) == _rowStateForComparison(dirty)
    assert clean.rowsForContour("axon") == dirty.rowsForContour("axon") == [2, 1, 0]

    ## Where they part. The leak is the reason D9 was asked.
    assert clean.getAllModifiedNames() == {"axon"}
    assert dirty.getAllModifiedNames() == {"axon", "__reorder_tmp__"}
    assert clean.generation - started_at == 1
    assert dirty.generation - started_at == 4


def test_reorderContour_realizes_an_arbitrary_permutation_on_real_contours(
        loaded_sections):
    """Not just a reversal, and not just on invented geometry.

    review-274 F2 reproduced the round trip one notch harder than the PR did, on
    a NON-reversal permutation, because a reversal is the one permutation a
    buggy implementation can reach by accident. The same standard applies to the
    replacement, and it is applied here on every multi-row contour of the real
    fixture series rather than on a three-row fixture.

    WHAT THIS MATERIAL CAN AND CANNOT DELIVER (review-277 F04)
    ----------------------------------------------------------
    An earlier form of this test rotated every contour by one and claimed that
    as "no fixed point and no symmetry to hide behind". That claim was false on
    most of what it ran against. The fixture series' contour row-count
    distribution is `{1: 212, 2: 7, 3: 2}`: of the nine multi-row contours here,
    SEVEN hold exactly two rows, and for a two-row contour rotate-by-one *is*
    the reversal -- the exact permutation the docstring said it was avoiding.
    Only two contours hold three rows.

    So the two sizes are exercised differently and counted separately, rather
    than being described with one claim that is only true of two of them:

    * **Three rows or more** -- a seeded shuffle, rejected and redrawn until it
      is neither the identity nor the reversal. This is the honest form of the
      original claim, and `checked_nontrivial` below asserts it was actually
      reached rather than skipped past.
    * **Exactly two rows** -- the swap, which is the *only* non-identity
      permutation a two-row contour has. There is no non-trivial permutation to
      exercise at this size and no amount of shuffling invents one; what these
      seven contours cover is that a reorder of a real contour preserves row
      numbers, held views and tracking, not that it survives an arbitrary
      permutation.

    Seeded rather than free-running: a permutation test that draws differently
    on every run either flakes or hides, and the seed makes a failure something
    that can be reproduced from the failure message alone.

    The views are built BEFORE the reorder and read after it, so this also says
    on real material what the fixture test says on invented material: a held
    view survives a reorder of the contour under it. And the new order is
    checked through `materializeContours` as well as through the index, because
    within-contour order being *serialized* is the whole justification for a
    reorder marking the contour modified.
    """
    rng = random.Random(20260805)
    checked_nontrivial = 0
    checked_two_row = 0
    for section in loaded_sections:
        store = SectionColumns.fromSection(section)
        store.clearTracking()
        for name in store.contourNames():
            original = store.rowsForContour(name)
            if len(original) < 2:
                continue
            held = {row: TraceView(store, row) for row in original}
            points = {row: view.points for row, view in held.items()}

            if len(original) >= 3:
                ## Redrawn until it is neither the identity nor the reversal.
                ## Both exist among the draws and both are the cases a buggy
                ## implementation reaches by accident.
                for _ in range(100):
                    permuted = rng.sample(original, len(original))
                    if permuted != original and permuted != original[::-1]:
                        break
                else:  # pragma: no cover - 1/3! odds per draw, 100 draws
                    raise AssertionError(f"no non-trivial draw for {name}")
                assert permuted != original
                assert permuted != original[::-1]
                checked_nontrivial += 1
            else:
                ## The only non-identity permutation two rows have. Not a
                ## non-trivial permutation, and not claimed as one.
                permuted = original[::-1]
                checked_two_row += 1

            store.reorderContour(name, permuted)
            assert store.rowsForContour(name) == permuted, (
                f"{name} did not take the order {permuted} (seeded shuffle)"
            )
            assert all(view.points == points[row] for row, view in held.items())
            assert store.getAllModifiedNames() <= set(store.contourNames())

            ## The order reaches the serialized form, not just the index.
            materialized = store.materializeContours()
            assert [trace.points for trace in materialized[name]] == [
                points[row] for row in permuted
            ], f"{name}'s materialized order is not the order it was given"

            store.reorderContour(name, original)
            assert store.rowsForContour(name) == original
            assert all(view.points == points[row] for row, view in held.items())

        ## Whatever was reordered, nothing that is not a contour was tracked --
        ## the property the round trip could not have held on this material.
        assert store.getAllModifiedNames() <= set(store.contourNames())
        ## And the store still materializes into the section it came from.
        materialized = store.materializeContours()
        assert sorted(materialized) == sorted(store.contourNames())

    ## Both counted, and the strong half asserted separately: if the fixture
    ## ever loses its three-row contours, this test must fail rather than
    ## quietly fall back to seven reversals and keep claiming "arbitrary".
    assert checked_two_row > 0, "the fixture offered no two-row contour"
    assert checked_nontrivial > 0, (
        "the fixture offered no contour of three or more rows, so no "
        "non-trivial permutation was exercised at all"
    )


def test_reorderContour_refuses_anything_that_is_not_a_permutation():
    """The check that keeps a reorder from becoming a corruption.

    Each of these four is a silent corruption if it goes through, and none of
    them is loud afterwards: a dropped row stays live and named for a contour
    that no longer lists it, a foreign row is indexed under one name while
    `getName` answers another (and `removeRow` then looks in the wrong index for
    it), a duplicate makes one row appear twice in a contour holding it once,
    and a row number that was never issued indexes nothing at all. The store is
    asserted unchanged after each refusal, because a validator that raised
    halfway through its own rebind would be worse than none.
    """
    store, rows = _threeRowContour()
    store.appendRow(name="dendrite", points=[(9.0, 9.0)], color=[4, 5, 6])
    store.clearTracking()
    before = _rowStateForComparison(store)

    for bad in ([2, 1], [2, 1, 0, 3], [2, 1, 3], [0, 0, 2], [0, 1, 99], []):
        with pytest.raises(ValueError) as caught:
            store.reorderContour("axon", bad)
        assert "permutation" in str(caught.value)
        assert _rowStateForComparison(store) == before, (
            f"the store changed while refusing {bad}"
        )
        assert store.getAllModifiedNames() == set(), (
            f"a refused reorder tracked a name: {bad}"
        )

    ## The refusal is not a name check: the right rows in a new order pass.
    store.reorderContour("axon", [1, 0, 2])
    assert store.rowsForContour("axon") == [1, 0, 2]


def test_reorderContour_refuses_non_integral_row_numbers_but_keeps_numpy_ints():
    """review-277 F01: the corruption a *value* comparison cannot see.

    `sorted(ordered) != sorted(current)` compares values, and `2.0 == 2`, so a
    `rows` holding `float` or `numpy.float64` elements was a valid permutation
    by value: it passed the guard, was written into the index verbatim, and
    marked the contour modified. The store then read as healthy and the damage
    surfaced somewhere else entirely -- `materializeContours()` subscripting a
    list with a float, raising a bare `TypeError` that named neither the contour
    nor the call that broke it. That is a fourth silent-corruption mode in a
    validator whose own docstring says it catches all of them.

    The fix is `operator.index` per element rather than a type check, and the
    second half of this test is why: `isinstance(row, int)` would also reject
    `numpy.int64`, which every other row-number path in this store accepts
    today. numpy is a hard dependency and an order computed through it arrives
    with a numpy dtype either way -- `int64` must keep working for the same
    reason `float64` must not.
    """
    store, rows = _threeRowContour()
    store.clearTracking()
    before = _rowStateForComparison(store)

    ## Each of these is a permutation by value and only by value.
    refused = [
        [2.0, 1, 0],
        [2, 1.0, 0],
        list(np.array([2.0, 1.0, 0.0])),
        [np.float64(2), 1, 0],
    ]
    for bad in refused:
        with pytest.raises(ValueError) as caught:
            store.reorderContour("axon", bad)
        ## The message names the offending value and its type, so the caller is
        ## not left to find it -- which is the whole complaint against the
        ## `TypeError` this replaces.
        message = str(caught.value)
        assert "integer row numbers" in message, message
        assert "float" in message, message
        assert _rowStateForComparison(store) == before, (
            f"the store changed while refusing {bad}"
        )
        assert store.getAllModifiedNames() == set(), (
            f"a refused reorder tracked a name: {bad}"
        )

    ## Non-numeric elements reach the same documented `ValueError` rather than
    ## the `TypeError` that `sorted()` used to raise from inside the guard.
    for bad in ([0, 1, None], [0, 1, "2"], [0, 1, (2,)]):
        with pytest.raises(ValueError):
            store.reorderContour("axon", bad)
        assert _rowStateForComparison(store) == before

    ## And the half that must NOT change: numpy integers are row numbers.
    store.reorderContour("axon", [np.int64(2), np.int64(1), np.int64(0)])
    assert store.rowsForContour("axon") == [2, 1, 0]
    assert store.getAllModifiedNames() == {"axon"}

    ## Coerced to exact `int` on the way in, not merely accepted: what the index
    ## holds is a plain Python int whatever integral dtype the caller used.
    assert all(type(row) is int for row in store.rowsForContour("axon"))

    ## The proof that this is the corruption that was reachable before: the
    ## store still materializes, in the requested order.
    materialized = store.materializeContours()
    assert [trace.points for trace in materialized["axon"]] == [
        store.getPoints(row) for row in [2, 1, 0]
    ]


def test_reorderContour_normalizes_its_name_and_no_ops_on_the_current_order():
    """Two smaller contracts, both inherited rather than invented.

    The name is normalized through `normalizeObjectName`, the same function
    `appendRow` and `rowsForContour` run, so a caller cannot reorder `"a b"`
    while the rows are indexed under `"a_b"` -- the trap `ContourView.__init__`
    closes for the same reason.

    A reorder to the order the contour already holds bumps the generation and
    tracks nothing, which is `setAttribute`'s own precedent for a rename to the
    name a row already has: the caller reached a mutation entry point, so the
    counter moves, but nothing entered the undo scope because nothing changed.
    An unknown contour with an empty order is the same no-op, and does not
    create an index entry for a contour that does not exist.
    """
    store = SectionColumns(1)
    rows = [store.appendRow(name="a b", points=[(float(i), 0.0)], color=[1, 2, 3])
            for i in range(2)]
    assert store.contourNames() == ["a_b"]
    store.clearTracking()

    ## The un-normalized spelling reaches the same contour.
    store.reorderContour("a b", list(reversed(rows)))
    assert store.rowsForContour("a_b") == list(reversed(rows))
    assert store.getAllModifiedNames() == {"a_b"}

    ## The no-op: a bump, and nothing tracked.
    store.clearTracking()
    generation = store.generation
    store.reorderContour("a_b", list(reversed(rows)))
    assert store.generation == generation + 1
    assert store.getAllModifiedNames() == set()
    assert store.rowsForContour("a_b") == list(reversed(rows))

    ## An empty order on a contour that does not exist: also a no-op, and it
    ## does not invent the contour.
    store.reorderContour("no_such_contour", [])
    assert "no_such_contour" not in store.contourNames()
    assert store.getAllModifiedNames() == set()


def test_importTraces_hands_back_the_contours_own_objects_and_may_hand_back_the_others(
        loaded_sections):
    """Blocker 4: the contract the port would have to meet, measured on a real pair.

    `Section.importTraces` takes the two lists `Contour.importTraces` returns
    and, for the traces the `keep_below` policy loses, calls
    `self.contours[cname].remove(trace2)` -- `Contour.remove`, so identity. That
    only works because the returned lists hold the very objects the rebound
    contour now holds. This test measures that, and measures the harder half
    with it: one of those objects belongs to the OTHER contour, which in
    production is a contour of a different section of a different series.

    A `ContourView.importTraces` would therefore have to adopt a foreign row
    into this store. That is design §10's id-carry question ("the id follows the
    surviving `Trace`"), not an append. D10 answered the id half --
    `appendRow(foreign_id=...)` exists and is tested above -- so what is left
    for the port is which store the adopted row belongs to, and threading the
    foreign id from `other`'s store to this one, which nothing does today.

    Built on two contours taken from the real fixture rather than on invented
    geometry, so the overlap arithmetic is the arithmetic production runs.
    """
    for section in loaded_sections:
        for name, contour in section.contours.items():
            if len(contour) >= 2:
                break
        else:
            continue
        break
    else:
        pytest.fail("the fixture has no contour with two traces")

    mine = contour.copy()
    theirs = contour.copy()

    ## Make one of theirs unmatchable, so both remainder pools are non-empty and
    ## the second loop -- the one holding `rem_o_traces.remove(o_trace)` -- runs.
    theirs[-1].points = [(x + 10_000.0, y + 10_000.0) for x, y in theirs[-1].points]

    before_mine = mine.getTraces()
    before_theirs = theirs.getTraces()
    rem_s, rem_o = mine.importTraces(theirs, threshold=0.95, keep_above="self",
                                     mag=section.mag)

    ## Every returned trace is identically in the rebound contour: the property
    ## `section.py`'s `self.contours[cname].remove(trace2)` depends on.
    for returned in rem_s + rem_o:
        assert any(element is returned for element in mine), (
            "importTraces returned a trace that is not identically in the "
            "contour it rebound; Section.importTraces' conflict removal relies "
            "on exactly this"
        )
        assert returned in mine

    ## The cross-contour half: `mine` now holds an object that is `theirs`'.
    ## Measured BEFORE the removal below, which would take one of them away.
    adopted = [t for t in before_theirs if any(e is t for e in mine)]
    assert adopted, (
        "this fixture pair produced no cross-contour adoption, so the harder "
        "half of blocker 4 went unmeasured"
    )
    assert [t for t in before_mine if any(e is t for e in mine)], (
        "the rebound contour kept none of its own objects either"
    )

    ## And `Contour.remove` does resolve them, which the view could not: this
    ## is `section.py`'s conflict-removal line, run on its own real input.
    victim = (rem_o or rem_s)[0]
    mine.remove(victim)
    assert not any(element is victim for element in mine)


def test_the_slice_guarantee_7b_inherits_still_holds_on_real_contours(
        loaded_sections):
    """D5's working default, re-verified as 7b's own precondition.

    Slice 7a established that `ContourView[i:]` is a bare `list` exactly as
    `Contour[i:]` is, which is what makes `importTraces`' `.copy()`/`.pop()`/
    `+` mechanics survive a view. A prior slice's guarantee is a fact to
    re-check, not one to inherit, so it is re-measured here on every contour of
    the real series -- and one notch harder than 7a's walk, which compares
    exception TYPES: this compares the exception MESSAGE STRINGS, the level the
    #270 review checked at but that no test held.

    It matters that this is the half of 7b that is NOT blocked: the container
    mechanics port cleanly and are pinned. What does not port is identity and
    the rebind, which the four tests above measure.
    """
    checked = slices = 0
    for section in loaded_sections:
        store = SectionColumns.fromSection(section)
        for name in store.contourNames():
            contour = section.contours[name]
            view = ContourView(store, name)
            n = len(contour)

            assert type(iter(view)) is type(iter(contour)) is type(iter([]))

            for i in range(n + 2):
                mine, theirs = contour[i:], view[i:]
                assert type(mine) is type(theirs) is list
                assert len(mine) == len(theirs)
                slices += 1

            for bad in (n, -n - 1):
                with pytest.raises(IndexError) as expected:
                    contour[bad]
                with pytest.raises(IndexError) as actual:
                    view[bad]
                assert str(actual.value) == str(expected.value)

            with pytest.raises(TypeError) as expected:
                contour["not an index"]
            with pytest.raises(TypeError) as actual:
                view["not an index"]
            assert str(actual.value) == str(expected.value)
            checked += 1

    assert checked > 200, f"expected the fixture's ~221 contours, walked {checked}"
    assert slices > 400
