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

Those gaps are covered by mutating real traces on real sections rather than by
building a synthetic series, so the material under test stays real and the
attribute domain gets covered. Where a test does that, it says so.

Both coordinate backings are parametrized over every test that touches
coordinates. The choice between them is an open measurement, and running the
suite against both is what keeps it open.
"""
import numpy as np
import pytest

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.columnar_store import (
    BOOL_ATTRIBUTES,
    FILL_MODE_CODES,
    FILL_MODE_OVERFLOW,
    PackedCoordinates,
    SectionColumns,
    SegmentedCoordinates,
)

BACKINGS = pytest.mark.parametrize(
    "backing", [SegmentedCoordinates, PackedCoordinates],
    ids=["segmented", "packed"],
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


# --- the whole fixture series, both backings ---------------------------------


@BACKINGS
def test_every_trace_of_every_real_section_round_trips(loaded_sections, backing):
    """The headline parity assertion, over all 232 traces of the real series.

    Contour names, within-contour order, and every column of every row.
    """
    n_traces = 0
    for section in loaded_sections:
        store = SectionColumns.fromSection(section, coordinates=backing())
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


@BACKINGS
def test_materializing_rebuilds_traces_equal_to_the_originals(loaded_sections, backing):
    """`materializeTrace` against `Trace.isSameTrace`, which compares name, color
    and points, plus the four attributes it does not compare.

    `isSameTrace` is the codebase's own value-equality predicate for a trace, and
    it exists because `Trace` defines no `__eq__`. Using it here rather than a
    hand-rolled comparison means the parity bar is the one the application
    already uses.
    """
    for section in loaded_sections:
        store = SectionColumns.fromSection(section, coordinates=backing())
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


@BACKINGS
def test_materialized_contours_match_the_sections_own_dict(loaded_sections, backing):
    """`materializeContours` against `Section.contours`, contour by contour.

    Built through `Contour(name, traces)`, the checking constructor, so a name
    that failed to survive the round trip raises inside the store rather than
    producing a quietly mismatched contour.
    """
    for section in loaded_sections:
        store = SectionColumns.fromSection(section, coordinates=backing())
        rebuilt = store.materializeContours()
        assert sorted(rebuilt, key=str) == sorted(section.contours, key=str)
        for name, contour in rebuilt.items():
            assert contour.name == name
            assert len(contour) == len(section.contours[name])
            for a, b in zip(contour, section.contours[name]):
                assert a.isSameTrace(b)


@BACKINGS
def test_the_stored_row_reserializes_to_the_same_bytes(loaded_sections, backing):
    """A second, independent parity check: `getList` of a materialized trace
    equals `getList` of the original.

    This is the weaker check of the two and is here on purpose, as the *other*
    direction. It proves the store loses nothing the file format carries, while
    the coordinate assertions above prove it loses nothing the file format
    itself drops. Neither alone is sufficient: this one would pass for a store
    that rounded to 7 dp on the way in.
    """
    for section in loaded_sections:
        store = SectionColumns.fromSection(section, coordinates=backing())
        for name in store.contourNames():
            for row, original in zip(store.rowsForContour(name),
                                     section.contours[name]):
                assert (store.materializeTrace(row).getList(include_name=False)
                        == original.getList(include_name=False))


# --- the rounding seam -------------------------------------------------------


@BACKINGS
def test_the_store_is_on_the_unrounded_side_of_the_seven_dp_rounding(
        loaded_sections, backing):
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

    store = SectionColumns.fromSection(section, coordinates=backing())
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


# --- the attribute domain the fixture does not reach -------------------------


@BACKINGS
def test_tags_negative_and_hidden_round_trip_on_a_real_trace(loaded_sections, backing):
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

    store = SectionColumns.fromSection(section, coordinates=backing())
    row = store.rowsForContour(name)[0]
    assert store.getTags(row) == {"alpha", "beta", "checked"}
    assert store.getFlag(row, "negative") is True
    assert store.getFlag(row, "hidden") is True
    _assert_trace_parity(store, row, trace)


@BACKINGS
def test_the_tags_column_cannot_be_mutated_through_a_value_it_handed_out(
        loaded_sections, backing):
    """`getTags` returns a fresh set, so a caller cannot reach into the column.

    `Contour.copy()` gives each copied trace its own `tags` set for the same
    reason, and `series_data.TraceData` aliasing a trace's tags is a known live
    dependency the store must not extend into itself.
    """
    section = loaded_sections[0]
    name = sorted(section.contours, key=str)[0]
    section.contours[name][0].tags = {"alpha"}
    store = SectionColumns.fromSection(section, coordinates=backing())
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
    import json

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


@BACKINGS
def test_freeze_releases_the_growth_slack_without_changing_a_value(backing):
    """A snapshot must not be measured as costing its allocator slack.

    The columns grow by amortized doubling, so a store holding two rows can hold
    buffers for sixty-four and the packed backing's initial capacity is 256
    points. That is the right trade while a store is being built and the wrong one
    for a snapshot, which is immutable after construction. Found while adapting
    the undo-growth harness, where the slack would have dominated the figure the
    measurement exists to produce.
    """
    store = SectionColumns(1, coordinates=backing())
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
    if isinstance(backing, PackedCoordinates):
        total += backing._array.nbytes
    else:
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


@BACKINGS
def test_rows_are_append_only_and_row_numbers_are_never_reused(backing):
    """A removed row's number retires with it.

    This is what lets the per-contour index and any later operation log refer to
    a row by number without a generation of its own. It is also why nothing here
    ever performs a mid-array insert.
    """
    store = SectionColumns(1, coordinates=backing())
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


@BACKINGS
def test_within_contour_order_survives_every_operation(backing):
    """Within-contour trace order is semantically significant.

    `Contour.importTraces` walks `self[i]` against `other[i]` positionally and
    stops at the first non-overlap, so a layout that reordered a contour would
    change import behavior on real data. Appends land at the end and a removal
    closes the gap without disturbing the survivors.
    """
    store = SectionColumns(1, coordinates=backing())
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


def test_packed_coordinates_never_insert_and_report_their_own_slack():
    """A length-changing write appends and tombstones rather than shifting.

    `addTrace` is an append today and must stay one, so the packed backing has no
    mid-array insert at all. The cost of that is dead space, and the backing
    reports it rather than hiding it, because deciding whether to compact needs a
    number and compaction reorders rows, which nothing here is allowed to do.
    """
    backing = PackedCoordinates()
    store = SectionColumns(1, coordinates=backing)
    row = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    assert backing.deadPoints == 0

    ## Same length: written in place, no slack.
    store.setCoordinates(row, [(2.0, 2.0), (3.0, 3.0)])
    assert backing.deadPoints == 0
    assert store.getPoints(row) == [(2.0, 2.0), (3.0, 3.0)]

    ## Longer: a fresh extent, and the old two points become slack.
    store.setCoordinates(row, [(4.0, 4.0), (5.0, 5.0), (6.0, 6.0)])
    assert backing.deadPoints == 2
    assert store.getPoints(row) == [(4.0, 4.0), (5.0, 5.0), (6.0, 6.0)]

    store.removeRow(row)
    assert backing.deadRows == 1


@BACKINGS
def test_a_copied_row_does_not_share_coordinate_memory_with_its_source(backing):
    """The aliasing class the coordinate coercion exists to close.

    `np.asarray` of an existing float64 array returns the same memory, so a row
    copied from another row would share its coordinates and a later in-place
    write to one would silently change the other. That is a data-loss shape, not
    a slowness shape.
    """
    store = SectionColumns(1, coordinates=backing())
    source = store.appendRow(name="axon", points=[(0.0, 0.0), (1.0, 1.0)], color=[1, 2, 3])
    copied = store.duplicateRow(source)

    ## Checked immediately, before any write. Checking it after a write does NOT
    ## discriminate: both backings replace a row's array on a length-changing
    ## write, so two rows that started out sharing memory look independent
    ## afterward. The invariant is that they never shared it.
    assert not np.shares_memory(store.getCoordinates(source),
                                store.getCoordinates(copied))

    ## And the same for a store built twice from one section: the second store's
    ## rows must not be views into the first store's arrays.
    store.setCoordinates(copied, [(7.0, 7.0), (8.0, 8.0)])
    assert store.getPoints(source) == [(0.0, 0.0), (1.0, 1.0)]
    assert store.getPoints(copied) == [(7.0, 7.0), (8.0, 8.0)]


@BACKINGS
def test_a_store_does_not_alias_the_arrays_of_a_store_built_beside_it(backing):
    """Two stores built from one section hold independent coordinates.

    The same coercion invariant, reached by the path a caller is most likely to
    take: build a store, build another, and write through one of them.
    """
    trace = Trace("axon", [1, 2, 3])
    trace.points = [(0.0, 0.0), (1.0, 1.0)]

    class StubSection():
        n = 3
        contours = {"axon": [trace]}

    first = SectionColumns.fromSection(StubSection(), coordinates=backing())
    second = SectionColumns.fromSection(StubSection(), coordinates=backing())
    assert not np.shares_memory(first.getCoordinates(0), second.getCoordinates(0))

    ## And neither of them aliases the live trace's own point list.
    first.getCoordinates(0)[0, 0] = 99.0
    assert trace.points[0] == (0.0, 0.0)
    assert second.getPoints(0)[0] == (0.0, 0.0)


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


@BACKINGS
def test_ids_are_issued_once_per_row_over_a_whole_real_section(loaded_sections, backing):
    """One id per trace across a real section, and no repeats."""
    section = max(loaded_sections, key=lambda s: sum(len(c) for c in s.contours.values()))
    issuer = StubIssuer()
    store = SectionColumns.fromSection(section, coordinates=backing(), id_issuer=issuer)

    ids = [store.getID(row) for name in store.contourNames()
           for row in store.rowsForContour(name)]
    assert len(ids) == len(store)
    assert all(i is not None for i in ids)
    assert len(set(ids)) == len(ids)
    assert issuer.count == len(ids)
