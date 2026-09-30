"""The trace dialog on traces whose fill conditions disagree (fork #528).

Two transparent traces, one filled when selected and one filled always,
opened the dialog with `Transparent` checked and both fill boxes unticked,
and an untouched OK read the two unticked boxes as `("none", "none")`, so it
took the fill off both traces. A box the traces disagree on now opens
partially checked, and while it stays that way `exec()` returns no condition,
which `Section.editTraceAttributes` reads as "leave it alone".
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

pytestmark = pytest.mark.gui


def _trace(name, fill_mode):
    from PyReconstruct.modules.datatypes import Trace

    trace = Trace(name, (10, 20, 30), closed=True)
    trace.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    trace.fill_mode = fill_mode
    return trace


def _dialog(main_window, *fill_modes):
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    traces = [_trace(f"t{i}", mode) for i, mode in enumerate(fill_modes)]
    return TraceDialog(main_window, traces)


@pytest.fixture
def ok_without_showing(monkeypatch):
    """Make `QDialog.exec` press OK at once."""
    monkeypatch.setattr(QDialog, "exec", lambda self: 1)


def test_a_box_the_traces_disagree_on_opens_partial(main_window):
    dialog = _dialog(
        main_window, ("transparent", "selected"), ("transparent", "always")
    )
    try:
        assert dialog.style_transparent.isChecked()
        # both traces fill when selected; only one fills when unselected
        assert dialog.selected_input.checkState() == Qt.Checked
        assert dialog.unselected_input.checkState() == Qt.PartiallyChecked
    finally:
        dialog.deleteLater()


def test_an_untouched_ok_returns_no_condition(main_window, ok_without_showing):
    dialog = _dialog(
        main_window, ("transparent", "selected"), ("transparent", "unselected")
    )
    try:
        trace, confirmed = dialog.exec()
        assert confirmed
        assert trace.fill_mode == ("transparent", None)
    finally:
        dialog.deleteLater()


def test_clicking_the_partial_box_sets_one_condition(
    main_window, ok_without_showing
):
    dialog = _dialog(
        main_window, ("transparent", "selected"), ("transparent", "always")
    )
    try:
        dialog.unselected_input.click()
        assert dialog.unselected_input.checkState() == Qt.Checked
        trace, _ = dialog.exec()
        assert trace.fill_mode == ("transparent", "always")
    finally:
        dialog.deleteLater()


def test_clicking_the_other_box_clears_the_partial_one(
    main_window, ok_without_showing
):
    """What the dialog shows after a click is what OK writes."""
    dialog = _dialog(
        main_window, ("transparent", "unselected"), ("transparent", "selected")
    )
    try:
        assert dialog.selected_input.checkState() == Qt.PartiallyChecked
        assert dialog.unselected_input.checkState() == Qt.PartiallyChecked
        dialog.selected_input.click()
        assert dialog.selected_input.checkState() == Qt.Checked
        assert dialog.unselected_input.checkState() == Qt.Unchecked
        trace, _ = dialog.exec()
        assert trace.fill_mode == ("transparent", "selected")
    finally:
        dialog.deleteLater()


def test_a_style_switch_still_resets_a_mixed_condition(
    main_window, ok_without_showing
):
    dialog = _dialog(
        main_window, ("transparent", "selected"), ("transparent", "unselected")
    )
    try:
        dialog.style_solid.setChecked(True)
        assert dialog.selected_input.checkState() == Qt.Checked
        assert dialog.unselected_input.checkState() == Qt.Checked
        trace, _ = dialog.exec()
        assert trace.fill_mode == ("solid", "always")
    finally:
        dialog.deleteLater()


def test_edit_attributes_keeps_each_traces_condition(
    main_window, ok_without_showing
):
    """The whole path: select two traces, `Edit attributes...`, OK."""
    series = main_window.series
    section = main_window.field.section
    traces = section.tracesAsList()[:2]
    assert len(traces) == 2
    for trace in traces:
        series.setAttr(trace.name, "locked", False)
    traces[0].fill_mode = ("transparent", "selected")
    traces[1].fill_mode = ("transparent", "always")
    section.resyncColumnarStore()  # out-of-class trace write
    section.selected_traces = list(traces)

    main_window.editSelectedAttributes()

    after = main_window.field.section.selected_traces
    assert sorted(tuple(t.fill_mode) for t in after) == [
        ("transparent", "always"),
        ("transparent", "selected"),
    ]
