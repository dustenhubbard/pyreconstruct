"""The Set Attributes dialog offers the series' tag sets.

Each pick-one set gets its own labeled, restricted dropdown above the Tags
rows, blank allowed. The Tags rows are editable dropdowns that list every
pick-many tag with completion and show a tag's description as a tooltip. Typed
text is still accepted (pick many allows user values, his word on 2026-08-16).
Without tag sets the rows stay the plain line edits they were, so no existing
series changes shape.

The pins that matter most: an untouched OK on a trace returns the trace's own
tags, unchanged. This dialog has twice written a seeded value onto every
selected trace on an untouched OK (color, then fill condition); the tags rows
must not be the third. And a pick-one row the selection disagreed on shows
blank and, left alone, changes nothing on any trace.
"""
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QWidget

from PyReconstruct.modules.datatypes import Trace
from PyReconstruct.modules.datatypes.tag_sets import TagSets
from PyReconstruct.modules.gui.dialog.trace import TraceDialog
from PyReconstruct.modules.gui.utils.completer_box import CompleterBox

pytestmark = pytest.mark.gui

SETS = TagSets({
    "Protrusion type": {
        "mode": "one",
        "tags": ["spine", "shaft", "branched"],
        "descriptions": {"spine": "A protrusion with a head and a neck."},
    },
    "Qualifiers": {
        "mode": "many",
        "tags": ["estimated", "checked"],
        "descriptions": {"estimated": "Placed by eye, not measured."},
    },
})


def _trace(tags):
    t = Trace("probe", (10, 20, 30), closed=True)
    t.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    t.tags = set(tags)
    return t


def _resolved(dialog, trace, answer):
    """The trace's tags after the dialog's whole answer, as a consumer sees them."""
    return SETS.resolve(trace.tags, answer.tags, dialog.tag_choices)


@pytest.fixture
def accept(monkeypatch):
    monkeypatch.setattr(QDialog, "exec", lambda self: True)


# --- the free Tags rows ---------------------------------------------------------

def test_tags_rows_offer_the_pick_many_tags_and_accept_typed_text(qapp):
    dialog = TraceDialog(None, traces=[_trace({"shaft", "checked"})], tag_sets=SETS)
    try:
        row = dialog.tags_input.inputs[0]
        assert isinstance(row, CompleterBox)
        offered = [row.itemText(i) for i in range(row.count())]
        assert set(offered) == {"estimated", "checked"}, (
            "a pick-one value has its own row and is not offered here"
        )
        assert row.currentText() == "checked", "the row opens on the trace's own tag"
        assert dialog.tags_input.getEntries() == ["checked"], (
            "the pick-one value is shown in its own row, not here"
        )

        row.setCurrentText("brand new tag")
        assert dialog.tags_input.getEntries() == ["brand new tag"], (
            "pick many still accepts a value that is in no set"
        )
    finally:
        dialog.deleteLater()


def test_descriptions_show_as_tooltips(qapp):
    dialog = TraceDialog(None, traces=[_trace(set())], tag_sets=SETS)
    try:
        row = dialog.tags_input.inputs[0]
        tips = {
            row.itemText(i): row.itemData(i, Qt.ToolTipRole)
            for i in range(row.count())
        }
        assert tips["estimated"] == "Placed by eye, not measured."
        assert not tips["checked"], "a tag without a description gets no tooltip"

        combo = dialog.pick_one_inputs["Protrusion type"]
        assert combo.itemData(combo.findText("spine"), Qt.ToolTipRole) == (
            "A protrusion with a head and a neck."
        )
        assert not combo.itemData(combo.findText("shaft"), Qt.ToolTipRole)
    finally:
        dialog.deleteLater()


def test_added_row_is_a_dropdown_too(qapp):
    dialog = TraceDialog(None, traces=[_trace({"checked"})], tag_sets=SETS)
    try:
        dialog.tags_input.add()
        new_row = dialog.tags_input.inputs[-1]
        assert isinstance(new_row, CompleterBox)
        assert new_row.currentText() == "", "a new row starts blank, not on the first option"
        new_row.setCurrentText("estimated")
        assert dialog.tags_input.getEntries() == ["checked", "estimated"]
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("sets", [None, TagSets({})])
def test_without_tag_sets_the_rows_stay_line_edits(qapp, sets):
    dialog = TraceDialog(None, traces=[_trace({"shaft"})], tag_sets=sets)
    try:
        row = dialog.tags_input.inputs[0]
        assert type(row) is QLineEdit
        assert row.text() == "shaft"
        assert dialog.pick_one_inputs == {}
        assert dialog.tag_choices == {}
    finally:
        dialog.deleteLater()


def test_only_pick_one_sets_keeps_line_edits_for_the_free_rows(qapp):
    only_one = TagSets({"Protrusion type": {"mode": "one", "tags": ["spine", "shaft"]}})
    dialog = TraceDialog(None, traces=[_trace({"shaft", "mine"})], tag_sets=only_one)
    try:
        assert type(dialog.tags_input.inputs[0]) is QLineEdit
        assert dialog.tags_input.getEntries() == ["mine"]
        assert dialog.pick_one_inputs["Protrusion type"].currentText() == "shaft"
    finally:
        dialog.deleteLater()


# --- the pick-one rows --------------------------------------------------------

def test_one_restricted_row_per_pick_one_set_seeded_on_the_traces_value(qapp):
    dialog = TraceDialog(None, traces=[_trace({"shaft", "estimated"})], tag_sets=SETS)
    try:
        assert list(dialog.pick_one_inputs) == ["Protrusion type"]
        combo = dialog.pick_one_inputs["Protrusion type"]
        assert type(combo) is QComboBox
        assert not combo.isEditable(), "pick one is restricted to its values"
        assert [combo.itemText(i) for i in range(combo.count())] == [
            "", "spine", "shaft", "branched"
        ], "blank first, then the set's values in the set's order"
        assert combo.currentText() == "shaft"
        assert dialog.pick_one_mixed["Protrusion type"] is False
    finally:
        dialog.deleteLater()


def test_untouched_ok_returns_the_traces_own_tags(qapp, accept):
    trace = _trace({"shaft", "estimated", "mine"})
    dialog = TraceDialog(None, traces=[trace], tag_sets=SETS)
    try:
        answer, confirmed = dialog.exec()
        assert confirmed
        assert answer.tags == {"estimated", "mine"}, "the free rows' answer"
        assert dialog.tag_choices == {"Protrusion type": "shaft"}
        assert _resolved(dialog, trace, answer) == {"shaft", "estimated", "mine"}
    finally:
        dialog.deleteLater()


def test_choosing_a_value_replaces_the_traces_old_value(qapp, accept):
    trace = _trace({"shaft", "estimated"})
    dialog = TraceDialog(None, traces=[trace], tag_sets=SETS)
    try:
        combo = dialog.pick_one_inputs["Protrusion type"]
        combo.setCurrentIndex(combo.findText("spine"))
        answer, _ = dialog.exec()
        assert dialog.tag_choices == {"Protrusion type": "spine"}
        assert _resolved(dialog, trace, answer) == {"spine", "estimated"}
    finally:
        dialog.deleteLater()


def test_choosing_blank_clears_the_set_and_nothing_else(qapp, accept):
    trace = _trace({"shaft", "estimated"})
    dialog = TraceDialog(None, traces=[trace], tag_sets=SETS)
    try:
        combo = dialog.pick_one_inputs["Protrusion type"]
        combo.setCurrentIndex(0)
        answer, _ = dialog.exec()
        assert dialog.tag_choices == {"Protrusion type": ""}
        assert _resolved(dialog, trace, answer) == {"estimated"}
    finally:
        dialog.deleteLater()


def test_a_pick_one_value_typed_into_a_free_row_counts_as_the_choice(qapp, accept):
    trace = _trace(set())
    dialog = TraceDialog(None, traces=[trace], tag_sets=SETS)
    try:
        dialog.tags_input.inputs[0].setCurrentText("spine")
        answer, _ = dialog.exec()
        assert dialog.tag_choices == {"Protrusion type": "spine"}
        assert _resolved(dialog, trace, answer) == {"spine"}
    finally:
        dialog.deleteLater()


# --- a selection that disagrees ---------------------------------------------

def test_disagreeing_pick_one_row_is_blank_while_agreeing_free_tags_still_show(qapp):
    dialog = TraceDialog(
        None, traces=[_trace({"shaft", "checked"}), _trace({"spine", "checked"})], tag_sets=SETS
    )
    try:
        assert dialog.pick_one_inputs["Protrusion type"].currentText() == ""
        assert dialog.pick_one_mixed["Protrusion type"] is True
        assert dialog.tags_mixed is False, "the free tags agree, so they are shown"
        assert dialog.tags_input.getEntries() == ["checked"]
    finally:
        dialog.deleteLater()


def test_untouched_disagreeing_row_leaves_every_trace_alone(qapp, accept):
    a, b = _trace({"shaft", "checked"}), _trace({"spine", "checked"})
    dialog = TraceDialog(None, traces=[a, b], tag_sets=SETS)
    try:
        answer, _ = dialog.exec()
        assert dialog.tag_choices == {"Protrusion type": None}
        assert answer.tags == {"checked"}
        assert _resolved(dialog, a, answer) == {"shaft", "checked"}
        assert _resolved(dialog, b, answer) == {"spine", "checked"}
    finally:
        dialog.deleteLater()


def test_editing_free_tags_never_wipes_the_undisplayed_pick_one_values(qapp, accept):
    a, b = _trace({"shaft", "checked"}), _trace({"spine", "checked"})
    dialog = TraceDialog(None, traces=[a, b], tag_sets=SETS)
    try:
        dialog.tags_input.inputs[0].setCurrentText("estimated")
        answer, _ = dialog.exec()
        assert answer.tags == {"estimated"}
        assert _resolved(dialog, a, answer) == {"shaft", "estimated"}
        assert _resolved(dialog, b, answer) == {"spine", "estimated"}
    finally:
        dialog.deleteLater()


def test_choosing_blank_on_a_disagreeing_row_clears_the_set_on_every_trace(qapp, accept):
    a, b = _trace({"shaft", "checked"}), _trace({"spine", "checked"})
    dialog = TraceDialog(None, traces=[a, b], tag_sets=SETS)
    try:
        combo = dialog.pick_one_inputs["Protrusion type"]
        combo.activated.emit(0)  # the user picked the blank entry on purpose
        answer, _ = dialog.exec()
        assert dialog.tag_choices == {"Protrusion type": ""}
        assert _resolved(dialog, a, answer) == {"checked"}
        assert _resolved(dialog, b, answer) == {"checked"}
    finally:
        dialog.deleteLater()


def test_choosing_a_value_on_a_disagreeing_row_sets_it_on_every_trace(qapp, accept):
    a, b = _trace({"shaft", "checked"}), _trace({"spine", "checked"})
    dialog = TraceDialog(None, traces=[a, b], tag_sets=SETS)
    try:
        combo = dialog.pick_one_inputs["Protrusion type"]
        combo.setCurrentIndex(combo.findText("branched"))
        answer, _ = dialog.exec()
        assert _resolved(dialog, a, answer) == {"branched", "checked"}
        assert _resolved(dialog, b, answer) == {"branched", "checked"}
    finally:
        dialog.deleteLater()


def test_mixed_free_tags_untouched_ok_still_returns_none(qapp, accept):
    """The dropdown rows must not break the mixed-selection guard: a blank the
    user did not touch means leave alone, and the consumer reads None."""
    dialog = TraceDialog(
        None, traces=[_trace({"checked"}), _trace({"estimated"})], tag_sets=SETS
    )
    try:
        assert dialog.tags_mixed
        answer, confirmed = dialog.exec()
        assert confirmed
        assert answer.tags is None
        assert dialog.tag_choices == {"Protrusion type": ""}, (
            "both traces agree the set is empty, so blank is a real value"
        )
    finally:
        dialog.deleteLater()


# --- the object list path (no traces, a union of tags or None) ----------------

class _ObjListParent(QWidget):
    """The object list passes itself as parent; the dialog reads the section range."""

    class series:
        sections = {0: None, 1: None, 2: None}


@pytest.fixture
def obj_list_parent(qapp):
    parent = _ObjListParent()
    yield parent
    parent.deleteLater()


def test_object_union_with_one_value_seeds_the_row(qapp, accept, obj_list_parent):
    dialog = TraceDialog(
        obj_list_parent, tags={"shaft", "checked"}, is_obj_list=True, tag_sets=SETS
    )
    try:
        assert dialog.pick_one_inputs["Protrusion type"].currentText() == "shaft"
        assert dialog.tags_input.getEntries() == ["checked"]
        (answer, sections), _ = dialog.exec()
        assert dialog.tag_choices == {"Protrusion type": "shaft"}
        assert answer.tags == {"checked"}
    finally:
        dialog.deleteLater()


def test_object_union_with_two_values_is_blank_and_leaves_traces_alone(qapp, accept, obj_list_parent):
    dialog = TraceDialog(
        obj_list_parent, tags={"shaft", "spine", "checked"}, is_obj_list=True, tag_sets=SETS
    )
    try:
        assert dialog.pick_one_inputs["Protrusion type"].currentText() == ""
        assert dialog.pick_one_mixed["Protrusion type"] is True
        (answer, sections), _ = dialog.exec()
        assert dialog.tag_choices == {"Protrusion type": None}
    finally:
        dialog.deleteLater()


def test_several_objects_pass_none_and_every_row_is_mixed(qapp, accept, obj_list_parent):
    dialog = TraceDialog(obj_list_parent, tags=None, is_obj_list=True, tag_sets=SETS)
    try:
        assert dialog.tags_mixed
        assert dialog.pick_one_mixed == {"Protrusion type": True}
        (answer, sections), _ = dialog.exec()
        assert answer.tags is None
        assert dialog.tag_choices == {"Protrusion type": None}
    finally:
        dialog.deleteLater()


# --- the three callers hand the dialog the series' sets ------------------------

class _Recorder:
    """Stands in for TraceDialog and records what each caller passed."""

    calls = []
    tag_choices = {}

    def __init__(self, parent, *args, **kwargs):
        type(self).calls.append(kwargs)

    def exec(self):
        return None, False


@pytest.fixture
def recorded_dialog(monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_2_trace, field_widget_3_object
    from PyReconstruct.modules.gui.palette import buttons

    _Recorder.calls = []
    monkeypatch.setattr(field_widget_2_trace, "TraceDialog", _Recorder)
    monkeypatch.setattr(field_widget_3_object, "TraceDialog", _Recorder)
    monkeypatch.setattr(buttons, "TraceDialog", _Recorder)
    return _Recorder


def test_field_dialog_gets_the_series_tag_sets(main_window, recorded_dialog):
    field = main_window.field
    name = next(iter(field.section.contours))
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(field.section.contours[name][0])

    field.traceDialog()

    assert recorded_dialog.calls, "the field never opened the dialog"
    assert recorded_dialog.calls[-1]["tag_sets"] is main_window.series.tag_sets


def test_object_list_dialog_gets_the_series_tag_sets(main_window, recorded_dialog):
    field = main_window.field
    name = next(iter(field.section.contours))
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(field.section.contours[name][0])

    field.editAttributes()

    assert recorded_dialog.calls, "the object list never opened the dialog"
    call = recorded_dialog.calls[-1]
    assert call["is_obj_list"] is True
    assert call["tag_sets"] is main_window.series.tag_sets


def test_palette_dialog_gets_the_series_tag_sets(main_window, recorded_dialog):
    button = main_window.mouse_palette.palette_buttons[0]

    button.openDialog()

    assert recorded_dialog.calls, "the palette never opened the dialog"
    call = recorded_dialog.calls[-1]
    assert call["is_palette"] is True
    assert call["tag_sets"] is main_window.series.tag_sets


# --- the callers carry the pick-one answer through to the traces ---------------

class _Answering:
    """Stands in for TraceDialog and answers with a fixed free set and choices."""

    tags = None
    choices = {}
    obj_list = False

    def __init__(self, parent, *args, **kwargs):
        self.tag_choices = dict(type(self).choices)

    def exec(self):
        answer = Trace(None, None, None)
        answer.name = None
        answer.color = None
        answer.tags = type(self).tags
        answer.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
        answer.fill_mode = (None, None)
        if type(self).obj_list:
            # None means every section the object is on
            return (answer, None), True
        return answer, True


@pytest.fixture
def answering_dialog(monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_2_trace, field_widget_3_object
    from PyReconstruct.modules.gui.palette import buttons

    monkeypatch.setattr(field_widget_2_trace, "TraceDialog", _Answering)
    monkeypatch.setattr(field_widget_3_object, "TraceDialog", _Answering)
    monkeypatch.setattr(buttons, "TraceDialog", _Answering)
    return _Answering


@pytest.fixture
def sets_on_series(main_window):
    main_window.series.tag_sets = SETS.copy()
    return main_window.series.tag_sets


def test_field_edit_resolves_each_trace_from_its_own_tags(main_window, answering_dialog, sets_on_series):
    field = main_window.field
    name = next(iter(field.section.contours))
    a, b = _trace({"shaft", "checked"}), _trace({"spine", "checked"})
    a.name = b.name = name
    field.section.addTrace(a, log_event=False)
    field.section.addTrace(b, log_event=False)
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(a)
    field.section.addSelectedTrace(b)

    answering_dialog.tags = {"estimated"}
    answering_dialog.choices = {"Protrusion type": None}
    answering_dialog.obj_list = False
    field.traceDialog()

    edited = {frozenset(t.tags) for t in field.section.contours[name]}
    assert {"shaft", "estimated"} in edited
    assert {"spine", "estimated"} in edited


def test_object_list_edit_resolves_each_trace_from_its_own_tags(main_window, answering_dialog, sets_on_series):
    field = main_window.field
    name = next(iter(field.section.contours))
    a, b = _trace({"shaft"}), _trace({"spine"})
    a.name = b.name = name
    field.section.addTrace(a, log_event=False)
    field.section.addTrace(b, log_event=False)
    field.section.save()  # the object list edits the sections on disk
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(a)

    answering_dialog.tags = None
    answering_dialog.choices = {"Protrusion type": "branched"}
    answering_dialog.obj_list = True
    field.editAttributes()

    tags = [t.tags for t in field.section.contours[name]]
    assert all("branched" in t for t in tags)
    assert not any("shaft" in t or "spine" in t for t in tags)


def test_palette_edit_resolves_the_button_trace(main_window, answering_dialog, sets_on_series):
    button = main_window.mouse_palette.palette_buttons[0]
    button.trace.tags = {"shaft", "mine"}

    answering_dialog.tags = {"mine", "estimated"}
    answering_dialog.choices = {"Protrusion type": "spine"}
    answering_dialog.obj_list = False
    button.openDialog()

    assert button.trace.tags == {"spine", "mine", "estimated"}
