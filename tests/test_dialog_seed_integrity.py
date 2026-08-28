"""Two dialogs that changed real data before, or without, the user's OK.

Both found by the review fleet (2026-08-28), both the same disease: a dialog
is a PROPOSAL, and nothing it does before `accept()` may write into the
series or misstate what the user already had.

* The alignment dialog's Rename button wrote every matching object's
  alignment attribute at click time. Cancel then left those objects pinned
  to an alignment that existed nowhere, with no undo recorded. The accepted
  path (`Series.modifyAlignments` -> `remapStoredAlignments`) already
  carries the attributes across, so the early write was also redundant.

* The trace dialog seeded its fill-condition checkboxes, then seeded the
  fill-style radios, whose toggled handler force-checks both boxes (the
  reset a real style switch wants). So a trace filled "when selected"
  opened with both boxes ticked, and an untouched OK wrote "always".
"""

import pytest

pytestmark = pytest.mark.gui


# --- the alignment rename ------------------------------------------------------

def _alignment_list(main_window, names):
    from PyReconstruct.modules.gui.dialog.alignment import AlignmentDialog

    dialog = AlignmentDialog(main_window, names, names[0])
    return dialog, dialog.table


def test_rename_click_writes_nothing_into_the_series(main_window):
    series = main_window.series
    obj = sorted(series.data["objects"])[0]
    series.setAttr(obj, "alignment", "rough")
    dialog, table = _alignment_list(main_window, ["no-alignment", "rough"])
    try:
        table.renameAlignment("rough", "polished")

        # the PROPOSAL is recorded for the accepted path...
        assert table.adict["polished"] == "rough"
        assert table.adict["rough"] is None
        # ...but the series itself is untouched: Cancel must cost nothing
        assert series.getAttr(obj, "alignment") == "rough"
    finally:
        dialog.deleteLater()


def test_the_accepted_path_still_carries_the_attribute(main_window):
    """The rename the user confirms does reach the object, exactly once,
    through modifyAlignments' remap rather than through the dialog."""
    series = main_window.series
    obj = sorted(series.data["objects"])[0]
    # rename a REAL alignment: one with tforms behind it, as the dialog's
    # list only ever offers
    victim = next(a for a in series.getAlignments() if a != "no-alignment")
    series.setAttr(obj, "alignment", victim)
    # what modifyAlignments receives from an accepted dialog: every existing
    # alignment appears as a key (the dialog builds adict from all of them)
    adict = {a: a for a in series.getAlignments()}
    adict["no-alignment"] = "no-alignment"
    adict["polished"] = victim
    adict[victim] = None
    series.modifyAlignments(adict)

    assert series.getAttr(obj, "alignment") == "polished"


# --- the trace dialog's fill condition -----------------------------------------

def _trace_dialog(main_window, fill_mode):
    from PyReconstruct.modules.datatypes import Trace
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    trace = Trace("seed_probe", (10, 20, 30), closed=True)
    trace.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    trace.fill_mode = fill_mode
    return TraceDialog(main_window, [trace])


@pytest.mark.parametrize("condition, selected, unselected", [
    ("selected", True, False),
    ("unselected", False, True),
    ("always", True, True),
])
def test_the_dialog_opens_saying_what_the_trace_says(
    main_window, condition, selected, unselected
):
    dialog = _trace_dialog(main_window, ("transparent", condition))
    try:
        assert dialog.selected_input.isChecked() is selected
        assert dialog.unselected_input.isChecked() is unselected
    finally:
        dialog.deleteLater()


def test_a_style_switch_still_resets_the_condition(main_window):
    """The force-check is FOR the user's own style flip; only the
    construction-time firing was the bug."""
    dialog = _trace_dialog(main_window, ("transparent", "selected"))
    try:
        dialog.style_solid.setChecked(True)   # a real user gesture
        assert dialog.selected_input.isChecked()
        assert dialog.unselected_input.isChecked()
    finally:
        dialog.deleteLater()
