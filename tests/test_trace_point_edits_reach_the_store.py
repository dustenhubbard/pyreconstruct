"""Every edit of a trace's points reaches the section's store.

The draw cull and the hover lookup read each trace's bounds from the
section's columnar store, keyed on the store's generation. A point edit that
leaves the store as it was, with the same point count, keeps the old box
until the next save: the draw can drop a trace that moved onto the screen,
and the hover can miss it. So every operation that changes the points of a
trace a section holds must move the store with it, through a Section method
or through resyncColumnarStore().

test_section_columnar_dual_write.py scans the source for a new direct edit
site. The tests here drive the operations the application has, in three
groups, each checked with the instrument its path allows:

- Section methods, a merge, and the field's smoothing, undo and redo act on
  a section the test holds. After each, the store must match the object
  model, its generation must have moved, and a trace layer's bounds must be
  the bounds of the live points.
- Series methods (smoothing an object, the self-crossing repair, copying
  traces to sections) load and save each section themselves, and the save
  rebuilds the store and reports any drift it finds. After each, no drift
  report may appear and the reloaded points must show the edit.
- A planted direct edit shows that the store check, the generation and the
  cached bounds each see it, that resyncColumnarStore() clears it, and that
  a save reports it and leaves a current store.
"""

import numpy as np
import pytest

from PyReconstruct.modules.backend.view.trace_layer import TraceLayer, pointBounds
from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.section import ColumnarDualWriteMismatch


# the save's report of a store that an edit outside Section left behind
DRIFT = "outside Section without calling resyncColumnarStore()"

SQUARE = [(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)]
# a closed outline that crosses itself: the self-crossing repair accepts it
SPIKED_SQUARE = [
    (0.0, 0.0), (10.0, 0.0), (10.0, 10.0),
    (5.0, 10.0), (5.0, 10.5), (5.0, 10.0),
    (0.0, 10.0),
]
# an object of the fixture series with traces on more than one section
OBJECT = "d03p12"


def _busiest(series):
    sections = [series.loadSection(n) for n in sorted(series.sections)]
    populated = [s for s in sections if s.contours]
    assert populated, "the fixture series has no populated section"
    return max(populated, key=lambda s: len(s.tracesAsList()))


def _firstTrace(section):
    name = sorted(section.contours, key=str)[0]
    return section.contours[name][0]


def _points(trace):
    return [tuple(p) for p in trace.points]


def _aTrace(name, points=SQUARE):
    trace = Trace(name, (11, 22, 33), closed=True)
    trace.points = list(points)
    return trace


def _warmLayer(section, series):
    """A trace layer whose bounds cache already holds this section's store."""
    layer = TraceLayer(section, series)
    layer._rawBounds(section.tracesAsList())
    return layer


def _storeIsCurrent(section, layer, generation, operation):
    """The store holds the object model, its generation moved, the bounds are live."""
    section._assertColumnsMatchObjectModel(operation)
    assert section._columns.generation > generation, (
        f"{operation} changed trace points and left the store generation at "
        f"{generation}: every generation-keyed cache still holds the old points"
    )
    traces = section.tracesAsList()
    bounds = layer._rawBounds(traces)
    expected = np.array([pointBounds(t.points) for t in traces])
    assert np.array_equal(bounds, expected, equal_nan=True), (
        f"after {operation} the trace layer's bounds are not the live points' bounds"
    )


@pytest.fixture
def section(real_series):
    section = _busiest(real_series)
    assert section._columns is not None
    return section


@pytest.fixture
def layer(section, real_series):
    return _warmLayer(section, real_series)


# --- edits through Section ---------------------------------------------------

def _translate(section, trace):
    section.addSelectedTrace(trace)
    section.translateTraces(0.25, -0.5)


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(_translate, id="translateTraces"),
        pytest.param(lambda s, t: s.editTraceRadius([t], 0.9), id="editTraceRadius"),
        pytest.param(lambda s, t: s.editTraceShape([t], SQUARE), id="editTraceShape"),
        pytest.param(lambda s, t: s.setMag(s.mag * 2), id="setMag"),
    ],
)
def test_a_section_edit_moves_the_store_and_the_bounds(section, layer, operation):
    trace = _firstTrace(section)
    before = _points(trace)
    generation = section._columns.generation

    operation(section, trace)

    assert _points(trace) != before, "the operation did not move the points"
    assert trace in section.contours[trace.name].getTraces()
    _storeIsCurrent(section, layer, generation, "a Section edit")


def test_a_merge_from_another_magnification_moves_both_stores(real_series, section, layer):
    """importTraces scales the donor's traces in place before it compares them."""
    donor = real_series.loadSection(section.n)
    donor.addTrace(_aTrace("merged_in"), log_event=False)
    donor.mag = section.mag * 2
    donor_layer = _warmLayer(donor, real_series)
    donor_before = {id(t): _points(t) for t in donor.tracesAsList()}
    keeper_generation = section._columns.generation
    donor_generation = donor._columns.generation

    section.importTraces(donor)

    assert any(
        _points(t) != donor_before[id(t)]
        for t in donor.tracesAsList() if id(t) in donor_before
    ), "the donor's points were not scaled"
    _storeIsCurrent(section, layer, keeper_generation, "importTraces on the keeper")
    _storeIsCurrent(donor, donor_layer, donor_generation, "importTraces on the donor")


# --- edits through Series, which save each section they touch ---------------
#
# These load their own Section objects and save them before returning, so the
# generation and bounds of a section the test holds say nothing about them.
# The save rebuilds the store and prints DRIFT when the store it replaces had
# fallen behind the object model: a missing store update on any of these
# paths shows up there.

def test_smoothing_an_object_leaves_no_drift_for_the_save_to_find(real_series, capsys):
    numbers = sorted(real_series.getObjectSections([OBJECT]))
    assert numbers
    before = {
        n: [_points(t) for t in real_series.loadSection(n).contours[OBJECT]]
        for n in numbers
    }

    real_series.smoothObject([OBJECT], log_event=False)

    assert DRIFT not in capsys.readouterr().err
    after = {
        n: [_points(t) for t in real_series.loadSection(n).contours[OBJECT]]
        for n in numbers
    }
    assert after != before, "smoothing did not move the points"


def test_repairing_a_self_crossing_trace_leaves_no_drift(real_series, section, capsys):
    section.addTrace(_aTrace("crossed", SPIKED_SQUARE), log_event=False)
    section.save()
    records = [
        r for r in real_series.findSelfCrossingTraces()
        if r["name"] == "crossed" and r["section"] == section.n
    ]
    assert records and records[0]["repairable"]
    capsys.readouterr()

    repaired = real_series.repairSelfCrossingTraces(records)

    assert repaired == records
    assert DRIFT not in capsys.readouterr().err
    reloaded = real_series.loadSection(section.n).contours["crossed"][0]
    assert _points(reloaded) != SPIKED_SQUARE


def test_copying_traces_to_sections_leaves_no_drift(real_series, section, capsys):
    targets = {n for n in real_series.sections if n != section.n}
    assert targets

    copied_to, skipped = real_series.copyTracesToSections(
        [_aTrace("copied")], targets, log_event=False
    )

    assert sorted(copied_to) == sorted(targets) and skipped == []
    assert DRIFT not in capsys.readouterr().err
    for n in targets:
        target = real_series.loadSection(n)
        copied = target.contours["copied"].getTraces()
        assert len(copied) == 1
        # each copy sits at the source's field position: its points, mapped
        # through its own section's transform, are the points given
        in_field = [target.tform.map(*p) for p in copied[0].points]
        assert np.allclose(in_field, SQUARE, atol=1e-9), n


# --- edits through the field ------------------------------------------------

@pytest.mark.gui
def test_smoothing_the_selection_in_the_field(main_window):
    field = main_window.field
    section = field.section
    layer = field.section_layer
    traces = [t for t in section.tracesAsList() if len(t.points) >= 6][:3]
    assert traces
    for trace in traces:
        section.addSelectedTrace(trace)
    layer._rawBounds(section.tracesAsList())
    before = [_points(t) for t in traces]
    generation = section._columns.generation

    # trace_function hands the selection to the method
    field.smoothTraces()

    assert [_points(t) for t in traces] != before, "smoothing did not move the points"
    _storeIsCurrent(section, layer, generation, "smoothTraces")


@pytest.mark.gui
def test_undo_and_redo_of_a_move(main_window):
    field = main_window.field
    section = field.section
    layer = field.section_layer
    trace = _firstTrace(section)
    name, original = trace.name, _points(trace)
    section.addSelectedTrace(trace)
    field.translate(0.25, -0.5)
    moved = _points(section.contours[name][0])
    assert moved != original
    layer._rawBounds(section.tracesAsList())

    generation = section._columns.generation
    field.undoState()
    assert _points(section.contours[name][0]) == original
    _storeIsCurrent(section, layer, generation, "undo")

    generation = section._columns.generation
    field.undoState(redo=True)
    assert _points(section.contours[name][0]) == moved
    _storeIsCurrent(section, layer, generation, "redo")


# --- the checks above fire on a direct edit ---------------------------------

def _editInPlace(trace):
    """Move every point outside Section, keeping the point count."""
    for i, (x, y) in enumerate(trace.points):
        trace.points[i] = (x + 0.3, y)


def test_a_direct_edit_fails_each_check_until_the_store_is_resynced(section, layer):
    trace = _firstTrace(section)
    generation = section._columns.generation
    stale = layer._rawBounds([trace])[0].copy()

    _editInPlace(trace)

    with pytest.raises(ColumnarDualWriteMismatch):
        section._assertColumnsMatchObjectModel("a direct edit")
    assert section._columns.generation == generation
    # the same point count, so the layer trusts its cached box: the old one
    assert np.array_equal(layer._rawBounds([trace])[0], stale)
    assert not np.array_equal(stale, pointBounds(trace.points))

    section.resyncColumnarStore()

    _storeIsCurrent(section, layer, generation, "resyncColumnarStore")


def test_the_save_reports_a_direct_edit_and_leaves_a_current_store(section, layer, capsys):
    generation = section._columns.generation
    _editInPlace(_firstTrace(section))

    section.save()

    assert DRIFT in capsys.readouterr().err
    _storeIsCurrent(section, layer, generation, "save")
