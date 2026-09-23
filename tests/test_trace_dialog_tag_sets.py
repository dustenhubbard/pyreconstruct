"""The Set Attributes dialog offers the series' tag sets in its Tags rows.

With tag sets on the series, each Tags row is an editable dropdown that lists
every known tag with completion and shows a tag's description as a tooltip.
Typed text is still accepted (pick many allows user values, his word on
2026-08-16). Without tag sets the rows stay the plain line edits they were, so
no existing series changes shape.

The pin that matters most: an untouched OK on a trace returns the trace's own
tags, unchanged. This dialog has twice written a seeded value onto every
selected trace on an untouched OK (color, then fill condition); the tags rows
must not be the third.
"""
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit

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
    "Qualifiers": {"mode": "many", "tags": ["estimated"], "descriptions": {}},
})


def _trace(tags):
    t = Trace("probe", (10, 20, 30), closed=True)
    t.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    t.tags = set(tags)
    return t


def test_rows_offer_every_known_tag_and_accept_typed_text(qapp):
    dialog = TraceDialog(None, traces=[_trace({"shaft"})], tag_sets=SETS)
    try:
        row = dialog.tags_input.inputs[0]
        assert isinstance(row, CompleterBox)
        offered = [row.itemText(i) for i in range(row.count())]
        assert set(offered) == set(SETS.allTags())
        assert row.currentText() == "shaft", "the row opens on the trace's own tag"

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
        assert tips["spine"] == "A protrusion with a head and a neck."
        assert not tips["shaft"], "a tag without a description gets no tooltip"
    finally:
        dialog.deleteLater()


def test_added_row_is_a_dropdown_too(qapp):
    dialog = TraceDialog(None, traces=[_trace({"shaft"})], tag_sets=SETS)
    try:
        dialog.tags_input.add()
        new_row = dialog.tags_input.inputs[-1]
        assert isinstance(new_row, CompleterBox)
        assert new_row.currentText() == "", "a new row starts blank, not on the first option"
        new_row.setCurrentText("estimated")
        assert dialog.tags_input.getEntries() == ["shaft", "estimated"]
    finally:
        dialog.deleteLater()


def test_untouched_ok_returns_the_traces_own_tags(qapp, monkeypatch):
    monkeypatch.setattr(QDialog, "exec", lambda self: True)
    dialog = TraceDialog(None, traces=[_trace({"shaft", "estimated", "mine"})], tag_sets=SETS)
    try:
        trace, confirmed = dialog.exec()
        assert confirmed
        assert trace.tags == {"shaft", "estimated", "mine"}
    finally:
        dialog.deleteLater()


def test_mixed_selection_untouched_ok_still_returns_none(qapp, monkeypatch):
    """The dropdown rows must not break the mixed-selection guard: a blank the
    user did not touch means leave alone, and the consumer reads None."""
    monkeypatch.setattr(QDialog, "exec", lambda self: True)
    dialog = TraceDialog(
        None, traces=[_trace({"shaft"}), _trace({"spine"})], tag_sets=SETS
    )
    try:
        assert dialog.tags_mixed
        trace, confirmed = dialog.exec()
        assert confirmed
        assert trace.tags is None
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize("sets", [None, TagSets({})])
def test_without_tag_sets_the_rows_stay_line_edits(qapp, sets):
    dialog = TraceDialog(None, traces=[_trace({"shaft"})], tag_sets=sets)
    try:
        row = dialog.tags_input.inputs[0]
        assert type(row) is QLineEdit
        assert row.text() == "shaft"
    finally:
        dialog.deleteLater()


# --- the three callers hand the dialog the series' sets ------------------------

class _Recorder:
    """Stands in for TraceDialog and records what each caller passed."""

    calls = []

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
