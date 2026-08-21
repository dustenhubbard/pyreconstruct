"""Tests for invert-selection and "hide others" (object- and section-level).

Auto-seg proofreading: isolate the object(s) you're working on and push the
rest out of the way. The isolation a proofreader needs is OBJECT-level and
VOLUME-wide -- an object spans many sections, so hiding the others must persist
as you page through the volume. A section-scoped "hide the rest on THIS
section" is offered separately, in the field's trace menu.

Covered here:

  * Invert selection
      - objects (object list): ``invert_object_rows`` -- the pure row logic
        behind ``ObjectTableWidget.invertSelection`` (the Qt selection is driven
        end-to-end by the offscreen driver).
      - traces (field / current section): ``Section.invertTraceSelection`` and
        the ``FieldWidgetTrace`` wrapper.

  * Hide Other Objects (volume-wide): ``FieldWidgetObject.hideOtherObjects``
    hides every non-selected object across ALL sections via the fork's
    series-wide ``Series.hideObjects``. Locked objects ARE hidden (locking
    guards edits, not visibility). The crux is exercised end-to-end on a real
    multi-section series (``shapes1.jser``, 4 objects on all 5 sections): the
    complement -- including a locked object -- is hidden on every section and a
    single undo restores every section.

  * Restore previous visibility (2026-07-31):
    ``FieldWidgetObject.restorePreviousVisibility``, the inverse the isolate
    never had. ``unhideAllObjects`` used to be offered as the way back and its
    docstring called itself "the clear restore for 'Hide other objects'", which
    is the flaw rather than the feature: it unhides everything and so discards
    every hide the user made on purpose before isolating. The restore replays the
    per-trace hidden flags recorded at the moment of the isolate. The pair of
    tests that matters is
    ``test_restore_puts_back_a_hide_made_before_isolating`` and its contrast
    ``test_unhide_all_objects_discards_a_hide_made_before_isolating``: the second
    is the assertion the old answer fails.

  * Hide Other Traces on this Section: ``Section.hideOtherTraces`` +
    ``FieldWidgetTrace.hideOtherTraces`` -- current section only, hides locked
    too, single-section undo. Proven to leave other sections untouched.

``Section`` cannot be constructed without real series files, so the pure
section tests drive ``Section.__new__`` instances carrying only the attributes
the methods touch. The volume-wide tests load a real series from the shipped
``.jser`` and drive the real field methods against it.
"""
import os
import types
import shutil

import pytest

from PyReconstruct.modules.datatypes.trace import Trace
from PyReconstruct.modules.datatypes.contour import Contour
from PyReconstruct.modules.datatypes.section import Section

from PyReconstruct.modules.gui.table.object import invert_object_rows
from PyReconstruct.modules.gui.main import field_widget_2_trace as fwt
from PyReconstruct.modules.gui.main import field_widget_3_object as fwo
from PyReconstruct.modules.gui.main.context_menu_list import (
    get_context_menu_list_trace,
    get_context_menu_list_obj,
    get_field_menu_list,
)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(
    REPO_ROOT, "PyReconstruct", "assets", "checker", "files", "shapes1.jser"
)


# --------------------------------------------------------------------------- #
# section-level helpers (no Qt)
# --------------------------------------------------------------------------- #
def mk(name, hidden=False):
    t = Trace(name, (255, 0, 0), True)
    t.points = [(0, 0), (1, 0), (1, 1)]
    t.hidden = hidden
    return t


class _SeriesStub:
    def __init__(self, locked_names=()):
        self.locked_names = set(locked_names)
        self.log = []

    def getAttr(self, name, attr):
        assert attr == "locked"
        return name in self.locked_names

    def addLog(self, *args):
        self.log.append(args)


def bare_section(traces, locked_names=()):
    s = Section.__new__(Section)
    s.n = 0
    s.series = _SeriesStub(locked_names)
    s.contours = {}
    for t in traces:
        s.contours.setdefault(t.name, Contour(t.name)).append(t)
    s.selected_traces = []
    s.selected_ztraces = []
    s.selected_flags = []
    s.temp_hide = []
    s.traces_group_hide = []
    s.modified_contours = set()
    s.added_traces = []
    s.removed_traces = []
    return s


# --------------------------------------------------------------------------- #
# Section.invertTraceSelection
# --------------------------------------------------------------------------- #
def test_invert_flips_selected_and_unselected():
    a, b, c, d = mk("a"), mk("b"), mk("c"), mk("d")
    s = bare_section([a, b, c, d])
    s.selected_traces = [a, c]
    s.invertTraceSelection()
    assert set(s.selected_traces) == {b, d}


def test_invert_empty_selection_selects_all_visible():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b])
    s.invertTraceSelection()
    assert set(s.selected_traces) == {a, b}


def test_invert_full_selection_deselects_all():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b])
    s.selected_traces = [a, b]
    s.invertTraceSelection()
    assert s.selected_traces == []


def test_invert_twice_restores_original_selection():
    a, b, c = mk("a"), mk("b"), mk("c")
    s = bare_section([a, b, c])
    s.selected_traces = [b]
    s.invertTraceSelection()
    s.invertTraceSelection()
    assert set(s.selected_traces) == {b}


def test_invert_skips_hidden_and_group_hidden_by_default():
    a, b, h, g = mk("a"), mk("b"), mk("h", hidden=True), mk("g")
    s = bare_section([a, b, h, g])
    s.traces_group_hide = [g]
    s.selected_traces = [a]
    s.invertTraceSelection()
    assert set(s.selected_traces) == {b}   # h hidden, g group-hidden -> skipped


def test_invert_includes_hidden_in_show_all_mode():
    a, h = mk("a"), mk("h", hidden=True)
    s = bare_section([a, h])
    s.selected_traces = [a]
    s.invertTraceSelection(include_hidden=True)
    assert set(s.selected_traces) == {h}


def test_invert_selects_locked_objects():
    """Deliberately the inverse of what this test used to assert.

    It pinned `Section.addSelectedTrace` refusing a locked object's trace, so
    inverting in the field skipped locked objects while
    `test_object_invert_does_not_exclude_locked_rows` had the object list
    selecting locked rows freely. Two inverts, opposite answers, same question.
    Lock guards mutations that change quantitative data and nothing else, so the
    field was the side that was wrong. The two now agree.
    """
    a, locked = mk("a"), mk("locked")
    s = bare_section([a, locked], locked_names={"locked"})
    s.selected_traces = [a]
    s.invertTraceSelection()
    assert s.selected_traces == [locked]   # a deselected, locked selected


def test_invert_leaves_ztrace_and_flag_selection_untouched():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b])
    s.selected_traces = [a]
    s.selected_ztraces = ["z"]
    s.selected_flags = ["f"]
    s.invertTraceSelection()
    assert s.selected_ztraces == ["z"] and s.selected_flags == ["f"]


# --------------------------------------------------------------------------- #
# Section.hideOtherTraces (hides locked too; single section)
# --------------------------------------------------------------------------- #
def test_hide_other_traces_hides_the_complement():
    a, b, c = mk("a"), mk("b"), mk("c")
    s = bare_section([a, b, c])
    s.selected_traces = [a]
    assert s.hideOtherTraces() is True
    assert [a.hidden, b.hidden, c.hidden] == [False, True, True]
    assert s.selected_traces == [a]        # kept trace stays selected
    assert s.modified_contours == {"b", "c"}


def test_hide_other_traces_hides_locked_traces_too():
    a, locked = mk("a"), mk("locked")
    s = bare_section([a, locked], locked_names={"locked"})
    s.selected_traces = [a]
    assert s.hideOtherTraces() is True
    # locking guards edits, not visibility -> the locked trace is hidden
    assert locked.hidden is True


def test_hide_other_traces_empty_selection_never_blanks_section():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b])
    assert s.hideOtherTraces() is False
    assert not a.hidden and not b.hidden


def test_hide_other_traces_skips_already_hidden():
    a, b, h = mk("a"), mk("b"), mk("h", hidden=True)
    s = bare_section([a, b, h])
    s.selected_traces = [a]
    s.hideOtherTraces()
    assert s.modified_contours == {"b"}    # h already hidden -> not re-logged
    assert len(s.series.log) == 1


# --------------------------------------------------------------------------- #
# FieldWidgetTrace wrappers (duck-typed stubs, no Qt loop)
# --------------------------------------------------------------------------- #
def test_field_invert_disabled_while_trace_layer_hidden():
    a = mk("a")
    s = bare_section([a])
    stub = types.SimpleNamespace(hide_trace_layer=True, show_all_traces=False,
                                 section=s, generateView=lambda *a_, **k: None)
    fwt.FieldWidgetTrace.invertTraceSelection(stub)
    assert s.selected_traces == []


def test_field_invert_selects_complement_and_regenerates():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b])
    s.selected_traces = [a]
    views = []
    stub = types.SimpleNamespace(hide_trace_layer=False, show_all_traces=False,
                                 section=s, generateView=lambda *a_, **k: views.append(1))
    fwt.FieldWidgetTrace.invertTraceSelection(stub)
    assert s.selected_traces == [b] and views


def _trace_field_stub(section):
    events = []
    stub = types.SimpleNamespace(
        section=section,
        hide_trace_layer=False,
        saveState=lambda: events.append("saveState"),
        generateView=lambda *a_, **k: events.append("generateView"),
    )
    return stub, events


def test_field_hide_other_traces_records_single_section_undo():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b])
    s.selected_traces = [a]
    stub, events = _trace_field_stub(s)
    fwt.FieldWidgetTrace.hideOtherTraces(stub)
    assert b.hidden and not a.hidden
    assert "saveState" in events and "generateView" in events


def test_field_hide_other_traces_empty_selection_no_undo():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b])
    stub, events = _trace_field_stub(s)
    fwt.FieldWidgetTrace.hideOtherTraces(stub)
    assert not a.hidden and not b.hidden
    assert "saveState" not in events


def test_field_hide_other_traces_disabled_while_layer_hidden():
    a, b = mk("a"), mk("b")
    s = bare_section([a, b])
    s.selected_traces = [a]
    stub, events = _trace_field_stub(s)
    stub.hide_trace_layer = True
    fwt.FieldWidgetTrace.hideOtherTraces(stub)
    assert not b.hidden and "saveState" not in events


# --------------------------------------------------------------------------- #
# invert_object_rows -- pure logic behind ObjectTableWidget.invertSelection
# --------------------------------------------------------------------------- #
def test_object_invert_returns_unselected_rows():
    assert invert_object_rows(["a", "b", "c", "d"], {"a", "c"}) == [1, 3]


def test_object_invert_empty_selects_all_rows():
    assert invert_object_rows(["a", "b", "c"], set()) == [0, 1, 2]


def test_object_invert_all_selected_selects_nothing():
    assert invert_object_rows(["a", "b"], {"a", "b"}) == []


def test_object_invert_does_not_exclude_locked_rows():
    # object rows are freely selectable; lock does not affect selection here
    assert invert_object_rows(["a", "b", "c"], {"a"}) == [1, 2]


def test_object_invert_double_invert_returns_to_start():
    rows = ["a", "b", "c", "d"]
    first = {rows[i] for i in invert_object_rows(rows, {"b"})}
    second = {rows[i] for i in invert_object_rows(rows, first)}
    assert second == {"b"}


# --------------------------------------------------------------------------- #
# FieldWidgetObject.hideOtherObjects / unhideAllObjects (recording stubs)
# --------------------------------------------------------------------------- #
class _FakeSeries:
    def __init__(self, objects):
        self.data = {"objects": {n: object() for n in objects}}
        self.hide_calls = []
        self.snapshot_calls = []
        self.restore_calls = []

    def hideObjects(self, names, hide, series_states=None, log_event=True):
        self.hide_calls.append((sorted(names), hide))

    def snapshotObjectVisibility(self, names):
        """Stand-in for the real per-trace read; records what was asked for and
        returns something truthy so the caller stores a snapshot."""
        self.snapshot_calls.append(sorted(names))
        return {n: {0: [False]} for n in names}

    def restoreObjectVisibility(self, snapshot, series_states=None, log_event=True):
        self.restore_calls.append(snapshot)
        return True


def _obj_field_stub(series, selected_names):
    events = []
    stub = types.SimpleNamespace(
        visibility_snapshot=None,
        series=series,
        series_states="STATES",
        section=types.SimpleNamespace(
            selected_traces=[types.SimpleNamespace(name=n) for n in selected_names]
        ),
        table_manager=types.SimpleNamespace(
            hasFocus=lambda: None,
            updateObjects=lambda names: events.append(("updateObjects", sorted(names))),
        ),
        mainwindow=types.SimpleNamespace(
            saveAllData=lambda: events.append("saveAllData"),
            seriesModified=lambda *a: events.append("seriesModified"),
        ),
        reload=lambda: events.append("reload"),
    )
    return stub, events


def test_hide_other_objects_hides_complement_including_locked():
    # 'd' would be a locked object in the real series; hideOtherObjects does NOT
    # filter it out -> it lands in the hide set.
    series = _FakeSeries(["a", "b", "c", "d"])
    stub, events = _obj_field_stub(series, ["a"])
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert series.hide_calls == [(["b", "c", "d"], True)]
    assert "reload" in events
    assert ("updateObjects", ["b", "c", "d"]) in events


def test_hide_other_objects_empty_selection_is_a_noop():
    series = _FakeSeries(["a", "b"])
    stub, events = _obj_field_stub(series, [])
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert series.hide_calls == [] and "reload" not in events


def test_hide_other_objects_everything_selected_is_a_noop():
    series = _FakeSeries(["a", "b"])
    stub, events = _obj_field_stub(series, ["a", "b"])
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert series.hide_calls == [] and "reload" not in events


def test_unhide_all_objects_unhides_every_object():
    series = _FakeSeries(["a", "b", "c"])
    stub, events = _obj_field_stub(series, [])
    fwo.FieldWidgetObject.unhideAllObjects(stub)
    assert series.hide_calls == [(["a", "b", "c"], False)]
    assert "reload" in events


def test_unhide_all_objects_on_empty_series_does_nothing():
    series = _FakeSeries([])
    stub, events = _obj_field_stub(series, [])
    fwo.FieldWidgetObject.unhideAllObjects(stub)
    assert series.hide_calls == [] and "reload" not in events


def test_hide_all_objects_hides_every_object():
    series = _FakeSeries(["a", "b", "c"])
    stub, events = _obj_field_stub(series, [])
    fwo.FieldWidgetObject.hideAllObjects(stub)
    assert series.hide_calls == [(["a", "b", "c"], True)]
    assert "reload" in events


def test_hide_all_objects_on_empty_series_does_nothing():
    series = _FakeSeries([])
    stub, events = _obj_field_stub(series, [])
    fwo.FieldWidgetObject.hideAllObjects(stub)
    assert series.hide_calls == [] and "reload" not in events


# --------------------------------------------------------------------------- #
# the snapshot the isolate takes, and the restore that spends it
# --------------------------------------------------------------------------- #
def test_hide_other_objects_snapshots_the_whole_series_before_isolating():
    """The whole series, not just the complement it is about to hide.

    "Restore previous visibility" promises the state as it was, so a hide made to
    the KEPT object while isolated has to come out too. The snapshot is also read
    BEFORE the hide, which is the only ordering that records anything useful.
    """
    series = _FakeSeries(["a", "b", "c", "d"])
    stub, _ = _obj_field_stub(series, ["a"])
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert series.snapshot_calls == [["a", "b", "c", "d"]]
    assert stub.visibility_snapshot


def test_hide_other_objects_takes_no_snapshot_when_it_hides_nothing():
    """Two no-op paths, and neither may clobber a snapshot from a real isolate:
    an empty selection (the decorator returns first) and everything selected."""
    series = _FakeSeries(["a", "b"])
    stub, _ = _obj_field_stub(series, [])
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert series.snapshot_calls == [] and stub.visibility_snapshot is None

    series = _FakeSeries(["a", "b"])
    stub, _ = _obj_field_stub(series, ["a", "b"])
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert series.snapshot_calls == [] and stub.visibility_snapshot is None


def test_a_second_isolate_overwrites_the_snapshot_rather_than_stacking():
    """Single level, by design: "previous" always means "before the most recent
    isolate", so there is no history to reason about and no stack to leak."""
    series = _FakeSeries(["a", "b", "c"])
    stub, _ = _obj_field_stub(series, ["a"])
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    first = stub.visibility_snapshot
    stub.section.selected_traces = [types.SimpleNamespace(name="b")]
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert len(series.snapshot_calls) == 2
    assert stub.visibility_snapshot is not first
    assert isinstance(stub.visibility_snapshot, dict)


def test_restore_previous_visibility_without_a_snapshot_does_nothing():
    """Backstop for the enablement below: with nothing recorded the command must
    not guess, must not blanket-unhide, and must not touch the series."""
    series = _FakeSeries(["a", "b"])
    stub, events = _obj_field_stub(series, [])
    fwo.FieldWidgetObject.restorePreviousVisibility(stub)
    assert series.restore_calls == []
    assert series.hide_calls == []
    assert events == []


def test_restore_previous_visibility_consumes_the_snapshot():
    """One restore per isolate: after it there is nothing left to restore, so the
    snapshot is cleared and the action disables itself again. Undoing the restore
    is Ctrl+Z, not a second press."""
    series = _FakeSeries(["a", "b", "c"])
    stub, events = _obj_field_stub(series, ["a"])
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    fwo.FieldWidgetObject.restorePreviousVisibility(stub)
    assert len(series.restore_calls) == 1
    assert stub.visibility_snapshot is None
    assert "reload" in events

    fwo.FieldWidgetObject.restorePreviousVisibility(stub)
    assert len(series.restore_calls) == 1


def test_restore_goes_through_series_states_so_it_is_undoable():
    """The restore must be undoable through the same machinery every other
    volume-wide visibility change uses, which means handing series_states down."""
    series = _FakeSeries(["a", "b"])
    captured = {}

    def restore(snapshot, series_states=None, log_event=True):
        captured["states"] = series_states
        return True

    series.restoreObjectVisibility = restore
    stub, _ = _obj_field_stub(series, ["a"])
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    fwo.FieldWidgetObject.restorePreviousVisibility(stub)
    assert captured["states"] == "STATES"


# --------------------------------------------------------------------------- #
# enablement: no snapshot means the row is not reachable
# --------------------------------------------------------------------------- #
class _FakeAction:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, enabled):
        self.enabled = enabled


def test_restore_action_is_disabled_without_a_snapshot_and_enabled_with_one():
    from PyReconstruct.modules.gui.main.context_menu_list import (
        sync_restore_visibility_action,
    )
    widget = types.SimpleNamespace(restorevisibility_act=_FakeAction())

    sync_restore_visibility_action(widget, None)
    assert widget.restorevisibility_act.enabled is False

    sync_restore_visibility_action(widget, {})   # empty snapshot is no snapshot
    assert widget.restorevisibility_act.enabled is False

    sync_restore_visibility_action(widget, {"a": {0: [False]}})
    assert widget.restorevisibility_act.enabled is True


def test_restore_action_sync_is_a_noop_on_a_widget_without_the_action():
    """The helper runs against both surfaces and against windows whose menus are
    not built yet, so an absent action is a no-op rather than an AttributeError."""
    from PyReconstruct.modules.gui.main.context_menu_list import (
        sync_restore_visibility_action,
    )
    sync_restore_visibility_action(types.SimpleNamespace(), {"a": {0: [True]}})


# --------------------------------------------------------------------------- #
# CRUX: volume-wide hide + undo on a REAL multi-section series
# --------------------------------------------------------------------------- #
from PyReconstruct.modules.datatypes.series import Series
from PyReconstruct.modules.datatypes.series_data import SeriesData
from PyReconstruct.modules.backend.func.state_manager import SeriesStates


def _open_shapes(tmp_path):
    if not os.path.exists(FIXTURE):
        pytest.skip("fixture shapes1.jser not found")
    fp = str(tmp_path / "s.jser")
    shutil.copyfile(FIXTURE, fp)
    series = Series.openJser(fp)
    sd = SeriesData(series)
    sd.refresh()
    series.data = sd
    return series


def _hidden_by_section(series, name):
    res = {}
    for snum in sorted(series.sections):
        sec = series.loadSection(snum)
        if name in sec.contours:
            res[snum] = all(t.hidden for t in sec.contours[name])
    return res


def _real_field_stub(series, states, selected_names):
    return types.SimpleNamespace(
        visibility_snapshot=None,
        series=series,
        series_states=states,
        section=types.SimpleNamespace(
            selected_traces=[types.SimpleNamespace(name=n) for n in selected_names]
        ),
        table_manager=types.SimpleNamespace(
            hasFocus=lambda: None,
            updateObjects=lambda names: None,
        ),
        mainwindow=types.SimpleNamespace(
            saveAllData=lambda: None,
            seriesModified=lambda *a: None,
        ),
        reload=lambda: None,
    )


def test_fixture_objects_span_multiple_sections(tmp_path):
    series = _open_shapes(tmp_path)
    assert len(series.sections) >= 3
    for name in series.data["objects"]:
        assert len(_hidden_by_section(series, name)) >= 3


def test_hide_other_objects_persists_across_every_section(tmp_path):
    series = _open_shapes(tmp_path)
    all_names = set(series.data["objects"].keys())
    keep = "star"
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, [keep])

    fwo.FieldWidgetObject.hideOtherObjects(stub)

    for name in all_names:
        hidden = _hidden_by_section(series, name)
        if name == keep:
            assert all(v is False for v in hidden.values()), f"kept {name}: {hidden}"
        else:
            assert hidden and all(v is True for v in hidden.values()), \
                f"{name} not hidden on every section: {hidden}"


def test_hide_other_objects_hides_locked_object_across_sections(tmp_path):
    series = _open_shapes(tmp_path)
    series.setAttr("square", "locked", True)   # lock one of the "others"
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    fwo.FieldWidgetObject.hideOtherObjects(stub)

    hidden = _hidden_by_section(series, "square")
    assert hidden and all(v is True for v in hidden.values()), \
        f"locked object was not hidden across sections: {hidden}"


def test_single_undo_restores_hidden_on_every_section(tmp_path):
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert any(all(v is True for v in _hidden_by_section(series, n).values())
               for n in series.data["objects"] if n != "star")

    states.undoState()

    for name in series.data["objects"]:
        hidden = _hidden_by_section(series, name)
        assert all(v is False for v in hidden.values()), \
            f"{name} still hidden after undo: {hidden}"


def test_show_all_objects_clears_isolation_volume_wide(tmp_path):
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    fwo.FieldWidgetObject.hideOtherObjects(stub)
    # now unhide everything (Show all objects)
    fwo.FieldWidgetObject.unhideAllObjects(stub)

    for name in series.data["objects"]:
        hidden = _hidden_by_section(series, name)
        assert all(v is False for v in hidden.values()), \
            f"{name} still hidden after Show all: {hidden}"


def test_hide_all_objects_hides_every_object_volume_wide(tmp_path):
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, [])

    fwo.FieldWidgetObject.hideAllObjects(stub)

    for name in series.data["objects"]:
        hidden = _hidden_by_section(series, name)
        assert hidden and all(v is True for v in hidden.values()), \
            f"{name} not hidden on every section: {hidden}"

    # a single undo restores every object on every section
    states.undoState()
    for name in series.data["objects"]:
        hidden = _hidden_by_section(series, name)
        assert all(v is False for v in hidden.values()), \
            f"{name} still hidden after undo: {hidden}"


def test_hide_all_then_show_all_restores_volume_wide(tmp_path):
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, [])

    fwo.FieldWidgetObject.hideAllObjects(stub)
    fwo.FieldWidgetObject.unhideAllObjects(stub)

    for name in series.data["objects"]:
        hidden = _hidden_by_section(series, name)
        assert all(v is False for v in hidden.values()), \
            f"{name} still hidden after Show all: {hidden}"


def test_hide_all_objects_hides_locked_object_across_sections(tmp_path):
    series = _open_shapes(tmp_path)
    series.setAttr("square", "locked", True)   # locking guards edits, not visibility
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, [])

    fwo.FieldWidgetObject.hideAllObjects(stub)

    hidden = _hidden_by_section(series, "square")
    assert hidden and all(v is True for v in hidden.values()), \
        f"locked object was not hidden across sections: {hidden}"


# --------------------------------------------------------------------------- #
# CRUX: "Restore previous visibility" on a REAL multi-section series
# --------------------------------------------------------------------------- #
def _any_hidden(series, name):
    """Per-trace hidden flags of one object, by section.

    Distinct from _hidden_by_section, which collapses a contour to "are ALL its
    traces hidden". The restore works per trace, so a partially hidden contour has
    to be visible to the assertions.
    """
    res = {}
    for snum in sorted(series.sections):
        sec = series.loadSection(snum)
        if name in sec.contours:
            res[snum] = [t.hidden for t in sec.contours[name]]
    return res


def test_restore_puts_back_a_hide_made_before_isolating(tmp_path):
    """THE point of the command, and the assertion "Unhide all objects" fails.

    The user hides "square" on purpose, then isolates "star" to work on it. Going
    back must leave "square" hidden: it was hidden before the isolate and the
    isolate is the only thing being undone.
    """
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    ## the deliberate hide, before any isolate
    series.hideObjects(["square"], True, states)
    assert all(v is True for v in _hidden_by_section(series, "square").values())

    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert stub.visibility_snapshot, "the isolate recorded nothing to restore"

    fwo.FieldWidgetObject.restorePreviousVisibility(stub)

    ## the deliberate hide survived
    square = _hidden_by_section(series, "square")
    assert square and all(v is True for v in square.values()), \
        f"the pre-isolate hide was discarded: {square}"

    ## and everything else is visible again
    for name in series.data["objects"]:
        if name == "square":
            continue
        hidden = _hidden_by_section(series, name)
        assert all(v is False for v in hidden.values()), \
            f"{name} not restored to visible: {hidden}"


def test_unhide_all_objects_discards_a_hide_made_before_isolating(tmp_path):
    """The contrast that makes the test above worth having.

    Same setup, but taking the old way back. "Unhide all objects" unhides
    everything, "square" included, which is exactly the state loss the restore
    exists to prevent. It is correct for what its own label says and wrong as an
    answer to "put it back", which is why its docstring no longer claims to be
    the restore for the isolate.
    """
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    series.hideObjects(["square"], True, states)
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    fwo.FieldWidgetObject.unhideAllObjects(stub)

    square = _hidden_by_section(series, "square")
    assert square and all(v is False for v in square.values()), \
        f"expected the blanket unhide to lose the hide, got {square}"


def test_restore_puts_back_a_single_hidden_trace_not_the_whole_object(tmp_path):
    """Why the snapshot is per trace rather than per object.

    There is no object-level `hidden` attribute: the flag lives on `Trace.hidden`,
    and the trace menu's "Hide selected traces" can hide ONE trace of a contour on
    ONE section. An object-level snapshot would record "square was not fully
    hidden on this section" and restore it by unhiding all of it, quietly undoing
    that hide.

    The fixture ships one trace per contour per section, where object-level and
    per-trace snapshots are indistinguishable -- so this test BUILDS the
    two-trace contour it needs. Without that, an object-atomic snapshot passes
    the whole suite (measured).
    """
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    ## give "square" a second trace on the first section, then hide only the first
    snum = sorted(series.sections)[0]
    section = series.loadSection(snum)
    section.addTrace(section.contours["square"][0].copy(), log_event=False)
    assert len(section.contours["square"]) == 2
    section.hideTraces([section.contours["square"][0]], True)
    section.save()

    before = _any_hidden(series, "square")
    assert before[snum] == [True, False], \
        f"setup failed to produce a partially hidden contour: {before[snum]}"

    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert _any_hidden(series, "square")[snum] == [True, True], "isolate hid both"

    fwo.FieldWidgetObject.restorePreviousVisibility(stub)

    assert _any_hidden(series, "square") == before


def test_restore_is_undoable_in_one_undo(tmp_path):
    """Through the same series_states machinery as every other volume-wide
    visibility change, so one undo puts the isolation back."""
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    fwo.FieldWidgetObject.hideOtherObjects(stub)
    isolated = {n: _hidden_by_section(series, n) for n in series.data["objects"]}
    assert any(all(v is True for v in h.values())
               for n, h in isolated.items() if n != "star")

    fwo.FieldWidgetObject.restorePreviousVisibility(stub)
    for name in series.data["objects"]:
        hidden = _hidden_by_section(series, name)
        assert all(v is False for v in hidden.values()), \
            f"{name} not visible after restore: {hidden}"

    states.undoState()

    for name in series.data["objects"]:
        assert _hidden_by_section(series, name) == isolated[name], \
            f"{name} did not return to the isolated state on undo"


def test_restore_puts_back_a_locked_objects_hide_with_no_lock_check(tmp_path):
    """Locking guards edits and quantification, NOT visibility.

    A locked object is hidden by the isolate (asserted above) and is restored by
    this command like any other. A branch that added lock checks to the
    isolate/invert path was deleted on 2026-07-31 for implementing the reading the
    maintainer rejected; this test is the standing form of the rule at the restore
    end of it.
    """
    series = _open_shapes(tmp_path)
    series.setAttr("square", "locked", True)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    ## the locked object is the one deliberately hidden before the isolate
    series.hideObjects(["square"], True, states)
    fwo.FieldWidgetObject.hideOtherObjects(stub)
    fwo.FieldWidgetObject.restorePreviousVisibility(stub)

    square = _hidden_by_section(series, "square")
    assert square and all(v is True for v in square.values()), \
        f"locked object's hide was not restored: {square}"


def test_restore_unhides_a_locked_object_the_isolate_hid(tmp_path):
    """The other half, and the one a lock check would break: a locked object that
    was VISIBLE before the isolate is unhidden by the restore, like any other."""
    series = _open_shapes(tmp_path)
    series.setAttr("square", "locked", True)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    fwo.FieldWidgetObject.hideOtherObjects(stub)
    assert all(v is True for v in _hidden_by_section(series, "square").values())

    fwo.FieldWidgetObject.restorePreviousVisibility(stub)

    square = _hidden_by_section(series, "square")
    assert square and all(v is False for v in square.values()), \
        f"locked object was not unhidden by the restore: {square}"


def test_restore_puts_back_a_hide_made_to_the_kept_object_while_isolated(tmp_path):
    """The snapshot covers the whole series, so a hide applied to the isolated
    object DURING the isolate is undone too -- "previous" means the state as it
    was, not "the complement as it was"."""
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    fwo.FieldWidgetObject.hideOtherObjects(stub)
    series.hideObjects(["star"], True, states)
    assert all(v is True for v in _hidden_by_section(series, "star").values())

    fwo.FieldWidgetObject.restorePreviousVisibility(stub)

    star = _hidden_by_section(series, "star")
    assert star and all(v is False for v in star.values()), \
        f"the kept object stayed hidden: {star}"


def test_snapshot_is_keyed_by_object_then_section_and_holds_one_flag_per_trace(tmp_path):
    """The shape the restore relies on, read out of the in-memory object index
    rather than off disk (Section.save keeps that index current, so the isolate
    pays no extra section loads for it)."""
    series = _open_shapes(tmp_path)
    snapshot = series.snapshotObjectVisibility(list(series.data["objects"].keys()))

    assert set(snapshot) == set(series.data["objects"])
    for name, by_section in snapshot.items():
        assert by_section, f"{name} recorded no sections"
        for snum, flags in by_section.items():
            section = series.loadSection(snum)
            assert len(flags) == len(section.contours[name])
            assert all(isinstance(f, bool) for f in flags)


def test_snapshot_ignores_names_the_series_does_not_have(tmp_path):
    """A stale selection must not put a phantom object into the snapshot, where
    the restore would then look for a contour that never existed."""
    series = _open_shapes(tmp_path)
    snapshot = series.snapshotObjectVisibility(["star", "not_an_object"])
    assert set(snapshot) == {"star"}


def test_restore_of_an_unchanged_series_writes_nothing(tmp_path):
    """Nothing to put back means no section writes and no undo state, so an
    accidental second restore cannot burn an undo step."""
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    snapshot = series.snapshotObjectVisibility(list(series.data["objects"].keys()))

    assert series.restoreObjectVisibility(snapshot, states) is False


def test_restore_leaves_traces_added_since_the_snapshot_alone(tmp_path):
    """Traces are matched by their index in the contour, so a contour that grew
    since the snapshot is restored over its overlap only.

    A stale index would otherwise hide the wrong trace, which is worse than
    leaving a new trace as the user left it.
    """
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    snum = sorted(series.sections)[0]

    snapshot = series.snapshotObjectVisibility(["square"])
    recorded = len(snapshot["square"][snum])

    ## grow the contour, and hide the newcomer
    section = series.loadSection(snum)
    extra = section.contours["square"][0].copy()
    extra.setHidden(True)
    section.addTrace(extra, log_event=False)
    section.save()
    assert len(series.loadSection(snum).contours["square"]) == recorded + 1

    series.restoreObjectVisibility(snapshot, states)

    flags = _any_hidden(series, "square")[snum]
    assert len(flags) == recorded + 1
    assert flags[:recorded] == snapshot["square"][snum]
    assert flags[recorded] is True, "the new trace was not left as it was"


def test_restore_with_an_empty_snapshot_is_a_no_op(tmp_path):
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    assert series.restoreObjectVisibility({}, states) is False
    assert series.restoreObjectVisibility(None, states) is False


def test_restore_with_no_snapshot_leaves_a_real_series_alone(tmp_path):
    """No isolate behind it, so nothing to restore and nothing may change --
    including no blanket unhide as a fallback."""
    series = _open_shapes(tmp_path)
    states = SeriesStates(series)
    stub = _real_field_stub(series, states, ["star"])

    series.hideObjects(["square"], True, states)
    before = {n: _any_hidden(series, n) for n in series.data["objects"]}

    fwo.FieldWidgetObject.restorePreviousVisibility(stub)

    assert {n: _any_hidden(series, n) for n in series.data["objects"]} == before


# --------------------------------------------------------------------------- #
# Section-level "Hide Other Traces" affects ONLY the current section
# --------------------------------------------------------------------------- #
def test_hide_other_traces_is_scoped_to_one_section(tmp_path):
    series = _open_shapes(tmp_path)
    snums = sorted(series.sections)
    first, rest = snums[0], snums[1:]

    sec0 = series.loadSection(first)
    keep = [t for t in sec0.tracesAsList() if t.name == "star"]
    assert keep
    modified = sec0.hideOtherTraces(keep=keep)
    sec0.save()
    assert modified is True

    # on the acted section, only 'star' is visible
    sec0b = series.loadSection(first)
    for name, contour in sec0b.contours.items():
        vis_expected = (name == "star")
        assert all((not t.hidden) == vis_expected for t in contour), \
            f"{name} visibility wrong on the acted section"

    # every OTHER section is completely untouched
    for snum in rest:
        sec = series.loadSection(snum)
        assert not any(t.hidden for t in sec.tracesAsList()), \
            f"section {snum} was affected by a section-scoped hide"


# --------------------------------------------------------------------------- #
# wiring: menus
# --------------------------------------------------------------------------- #
class _ObjMenuStub:
    def __init__(self):
        self.series = types.SimpleNamespace(
            user_columns={}, alignments=set(), groups_visibility={}
        )

    def __getattr__(self, name):
        return lambda *a, **k: None


class _Anything:
    """Any attribute access yields a callable that returns an empty list, so
    submenu builders like ``self.field.getTraceMenu()`` return something
    iterable and every callback slot is harmless."""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return lambda *a, **k: []


class _FieldMenuStub(_Anything):
    def __init__(self):
        super().__init__(
            series=_Anything(user_columns={}, alignments=set(), groups_visibility={}),
            field=_Anything(),
        )


def _act_names(menu):
    names = []
    for entry in menu:
        if isinstance(entry, tuple):
            names.append(entry[0])
        elif isinstance(entry, dict):
            names.extend(_act_names(entry["opts"]))
    return names


def test_trace_field_menu_offers_hide_other_traces_after_hide():
    """Field variant: "Hide other traces (this section)" follows "Hide".

    The stable line keeps upstream's menu organization, so "Hide" lives inside
    the trace submenu (no top strip) and this line's shipped isolate row sits
    directly after it, reading as a pair.
    """
    class _Stub:
        series = object()
        def __getattr__(self, name):
            return lambda *a, **k: None

    names = _act_names(get_context_menu_list_trace(_Stub(), is_in_field=True))
    assert "hidetraces_act" in names
    assert "hideothertraces_act" in names
    assert names.index("hideothertraces_act") == names.index("hidetraces_act") + 1


def test_hide_other_traces_is_field_only_not_in_trace_list():
    class _Stub:
        series = object()
        def __getattr__(self, name):
            return lambda *a, **k: None

    list_names = _act_names(get_context_menu_list_trace(_Stub(), is_in_field=False))
    assert "hideothertraces_act" not in list_names


def test_object_menu_offers_hide_other_and_unhide_all_next_to_hide():
    names = _act_names(get_context_menu_list_obj(_ObjMenuStub()))
    assert "hideotherobj_act" in names and "showallobj_act" in names
    assert "hideallobj_act" in names
    assert "restorevisibility_act" in names
    # order, three hide/unhide pairs by scope of action:
    #   Hide object      Unhide object                 (one object, series-wide)
    #   Hide others      Restore previous visibility    (isolate, and its inverse)
    #   Hide all         Unhide all objects             (whole series)
    assert names.index("hideotherobj_act") == names.index("unhideobj_act") + 1
    assert names.index("restorevisibility_act") == names.index("hideotherobj_act") + 1
    assert names.index("hideallobj_act") == names.index("restorevisibility_act") + 1
    assert names.index("showallobj_act") == names.index("hideallobj_act") + 1


def test_field_menu_offers_invert_selection():
    names = _act_names(get_field_menu_list(_FieldMenuStub()))
    assert "invertselection_act" in names
    assert names.index("invertselection_act") == names.index("deselect_act") + 1
