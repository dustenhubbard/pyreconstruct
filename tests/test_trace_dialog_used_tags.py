"""The Trace Tags rows in Set Attributes offer the tags already used in the series.

The rows used to complete only from the series' tag sets, so a tag on traces
but in no set was never offered, and a series with no tag sets offered nothing
(fork #774). They now offer the tag set tags first, each with its description
as a tooltip, then every other tag on a trace anywhere in the series. A value
of a pick-one set has its own row and is still not offered here, and each tag
is offered once.

The used tags come from the series data, which the field keeps current after
every edit, so opening the dialog never reads a section file.
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
        "tags": ["spine", "shaft"],
        "descriptions": {"spine": "A protrusion with a head and a neck."},
    },
    "Qualifiers": {
        "mode": "many",
        "tags": ["estimated", "checked"],
        "descriptions": {"estimated": "Placed by eye, not measured."},
    },
})


def _trace(tags, name="probe"):
    t = Trace(name, (10, 20, 30), closed=True)
    t.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    t.tags = set(tags)
    return t


def _traced_sections(series, skip=None):
    """The numbers of the sections that have traces, `skip` left out."""
    out = []
    for snum in sorted(series.sections):
        if snum != skip and series.loadSection(snum).tracesAsList():
            out.append(snum)
    return out


def _tag_first_trace(series, snum, tag):
    """Add a tag to the first trace on a section and save the section."""
    section = series.loadSection(snum)
    trace = section.tracesAsList()[0]
    trace.tags = trace.tags | {tag}
    section.modified_contours.add(trace.name)
    section.save()


def _offered(dialog):
    row = dialog.tags_input.inputs[0]
    assert isinstance(row, CompleterBox), "the Trace Tags rows are dropdowns"
    return [row.itemText(i) for i in range(row.count())]


def _tips(dialog):
    row = dialog.tags_input.inputs[0]
    return {row.itemText(i): row.itemData(i, Qt.ToolTipRole) for i in range(row.count())}


# --- the dialog -----------------------------------------------------------------

def test_used_tags_are_offered_with_no_tag_sets(qapp):
    dialog = TraceDialog(
        None, traces=[_trace(set())], used_tags={"myelinated", "axon"}
    )
    try:
        assert _offered(dialog) == ["axon", "myelinated"]
    finally:
        dialog.deleteLater()


def test_used_tags_follow_the_tag_set_tags_once_each(qapp):
    used = {"zeta", "checked", "alpha", "spine", "shaft"}
    dialog = TraceDialog(
        None, traces=[_trace({"checked"})], tag_sets=SETS, used_tags=used
    )
    try:
        assert _offered(dialog) == ["checked", "estimated", "alpha", "zeta"], (
            "the tag set tags first, then the other used tags, each block "
            "sorted, each tag once, and "
            "no pick-one value even when a trace carries it"
        )
        tips = _tips(dialog)
        assert tips["estimated"] == "Placed by eye, not measured."
        assert not tips["alpha"], "a tag in no set has no description"
    finally:
        dialog.deleteLater()


def test_added_row_offers_the_used_tags_too(qapp):
    dialog = TraceDialog(None, traces=[_trace(set())], used_tags={"axon"})
    try:
        dialog.tags_input.add()
        new_row = dialog.tags_input.inputs[-1]
        assert isinstance(new_row, CompleterBox)
        assert [new_row.itemText(i) for i in range(new_row.count())] == ["axon"]
    finally:
        dialog.deleteLater()


def test_no_sets_and_no_used_tags_keep_plain_rows(qapp):
    dialog = TraceDialog(None, traces=[_trace(set())], used_tags=set())
    try:
        assert isinstance(dialog.tags_input.inputs[0], QLineEdit)
        assert not isinstance(dialog.tags_input.inputs[0], CompleterBox)
    finally:
        dialog.deleteLater()


# --- the series data ------------------------------------------------------------

def test_series_data_lists_every_tag_on_a_trace(real_series):
    snums = _traced_sections(real_series)
    assert len(snums) > 1
    _tag_first_trace(real_series, snums[0], "used_on_first")
    _tag_first_trace(real_series, snums[-1], "used_on_last")

    used = real_series.data.usedTags()
    assert {"used_on_first", "used_on_last"} <= used


# --- the dialogs PyReconstruct opens --------------------------------------------

class _Recording:
    """The real TraceDialog, cancelled, keeping what its Trace Tags rows offer."""

    offered = None

    def __new__(cls, parent, *args, **kwargs):
        dialog = TraceDialog(parent, *args, **kwargs)
        cls.offered = _offered(dialog)
        return dialog


@pytest.fixture
def recording(monkeypatch):
    monkeypatch.setattr(QDialog, "exec", lambda self: 0)
    _Recording.offered = None
    return _Recording


def _tag_a_trace_on_another_section(series, field, tag):
    """Put a tag on a trace on a section other than the one in the field."""
    _tag_first_trace(series, _traced_sections(series, skip=field.section.n)[0], tag)


def test_trace_dialog_offers_a_tag_used_on_another_section(main_window, recording, monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_2_trace

    monkeypatch.setattr(field_widget_2_trace, "TraceDialog", recording)
    field = main_window.field
    _tag_a_trace_on_another_section(main_window.series, field, "elsewhere")

    trace = field.section.tracesAsList()[0]
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(trace)
    field.traceDialog()

    assert recording.offered is not None
    assert "elsewhere" in recording.offered


def test_object_dialog_offers_a_tag_used_on_another_section(main_window, recording, monkeypatch):
    from PyReconstruct.modules.gui.main import field_widget_3_object

    monkeypatch.setattr(field_widget_3_object, "TraceDialog", recording)
    field = main_window.field
    _tag_a_trace_on_another_section(main_window.series, field, "elsewhere")

    name = field.section.tracesAsList()[0].name
    field.section.selected_traces.clear()
    for t in field.section.contours[name]:
        field.section.addSelectedTrace(t)
    field.editAttributes()

    assert recording.offered is not None
    assert "elsewhere" in recording.offered


def test_palette_dialog_offers_a_tag_used_in_the_series(real_series, recording, monkeypatch):
    from PyReconstruct.modules.gui.palette import buttons

    monkeypatch.setattr(buttons, "TraceDialog", recording)
    _tag_first_trace(real_series, _traced_sections(real_series)[0], "from_a_trace")

    class Manager:
        series = real_series

        def paletteButtonChanged(self, button):
            pass

    button = buttons.PaletteButton(None, Manager())
    pal_name, idx = real_series.palette_index
    button.setTrace(real_series.palette_traces[pal_name][idx])
    try:
        button.openDialog()
        assert recording.offered is not None
        assert "from_a_trace" in recording.offered
    finally:
        button.deleteLater()
