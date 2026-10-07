"""An untouched OK in the trace attributes dialog keeps every fill_mode.

The fill boxes can show three conditions, but a trace can hold more: a fill
whose condition is "none" (a palette edited in `Edit all palettes...`, where
fill and condition are picked apart, or a .jser), and any condition under the
None style. A ("solid", "none") trace opened with both boxes unticked, and an
untouched OK read them back as ("none", "none"), which took the fill off.
`TraceLayer.drawTrace` fills such a trace while it is unselected, so the
dialog now shows it as "unselected", and an OK with the fill rows as they
opened leaves each trace's condition alone.
"""

import itertools

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

pytestmark = pytest.mark.gui

STYLES = ("none", "transparent", "solid")
CONDITIONS = ("none", "selected", "unselected", "always")
EVERY_FILL_MODE = list(itertools.product(STYLES, CONDITIONS))


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


def _boxes(dialog):
    return (
        dialog.selected_input.checkState(),
        dialog.unselected_input.checkState(),
    )


@pytest.fixture
def ok_without_showing(monkeypatch):
    """Make `QDialog.exec` press OK at once."""
    monkeypatch.setattr(QDialog, "exec", lambda self: 1)


def _select(main_window, *fill_modes):
    """Give the first traces on the section these fill modes and select them."""
    series = main_window.series
    section = main_window.field.section
    traces = section.tracesAsList()[:len(fill_modes)]
    assert len(traces) == len(fill_modes)
    for trace, mode in zip(traces, fill_modes):
        series.setAttr(trace.name, "locked", False)
        trace.fill_mode = mode
    section.resyncColumnarStore()  # out-of-class trace write
    section.selected_traces = list(traces)


def _selected_fill_modes(main_window):
    return sorted(
        tuple(t.fill_mode) for t in main_window.field.section.selected_traces
    )


@pytest.mark.parametrize("fill_mode", EVERY_FILL_MODE)
def test_edit_attributes_untouched_ok_keeps_the_fill_mode(
    main_window, ok_without_showing, fill_mode
):
    """The whole path: select a trace, `Edit attributes...`, OK."""
    _select(main_window, fill_mode)

    main_window.editSelectedAttributes()

    assert _selected_fill_modes(main_window) == [fill_mode]


@pytest.mark.parametrize("style", ["transparent", "solid"])
def test_a_fill_with_no_condition_opens_as_unselected(main_window, style):
    """It draws only while unselected, so it shows the same boxes."""
    none_dialog = _dialog(main_window, (style, "none"))
    unselected_dialog = _dialog(main_window, (style, "unselected"))
    try:
        assert _boxes(none_dialog) == (Qt.Unchecked, Qt.Checked)
        assert _boxes(none_dialog) == _boxes(unselected_dialog)
    finally:
        none_dialog.deleteLater()
        unselected_dialog.deleteLater()


@pytest.mark.parametrize("other", ["selected", "unselected", "always", "none"])
def test_two_traces_one_with_no_condition_keep_their_own(
    main_window, ok_without_showing, other
):
    _select(main_window, ("solid", "none"), ("solid", other))

    main_window.editSelectedAttributes()

    assert _selected_fill_modes(main_window) == sorted(
        [("solid", "none"), ("solid", other)]
    )


def test_a_palette_button_keeps_a_fill_with_no_condition(
    main_window, ok_without_showing
):
    button = main_window.mouse_palette.palette_buttons[0]
    button.trace.fill_mode = ("solid", "none")

    button.openDialog()

    assert tuple(button.trace.fill_mode) == ("solid", "none")


def test_ticking_selected_on_a_fill_with_no_condition_fills_always(
    main_window, ok_without_showing
):
    """The boxes read as "unselected", so adding "selected" makes "always"."""
    dialog = _dialog(main_window, ("solid", "none"))
    try:
        dialog.selected_input.click()
        trace, _ = dialog.exec()
        assert trace.fill_mode == ("solid", "always")
    finally:
        dialog.deleteLater()


def test_unticking_unselected_on_a_fill_with_no_condition_removes_it(
    main_window, ok_without_showing
):
    dialog = _dialog(main_window, ("solid", "none"))
    try:
        dialog.unselected_input.click()
        trace, _ = dialog.exec()
        assert trace.fill_mode == ("none", "none")
    finally:
        dialog.deleteLater()


def test_choosing_the_none_style_still_clears_the_condition(
    main_window, ok_without_showing
):
    dialog = _dialog(main_window, ("solid", "unselected"))
    try:
        dialog.style_none.setChecked(True)
        trace, _ = dialog.exec()
        assert trace.fill_mode == ("none", "none")
    finally:
        dialog.deleteLater()


@pytest.mark.parametrize(
    ("fill_mode", "box", "expected"),
    [
        (("solid", "selected"), "selected_input", ("none", "none")),
        (("solid", "selected"), "unselected_input", ("solid", "always")),
        (("solid", "unselected"), "selected_input", ("solid", "always")),
        (("solid", "unselected"), "unselected_input", ("none", "none")),
        (("solid", "always"), "selected_input", ("solid", "unselected")),
        (("solid", "always"), "unselected_input", ("solid", "selected")),
        (("transparent", "selected"), "selected_input", ("none", "none")),
        (("transparent", "selected"), "unselected_input", ("transparent", "always")),
        (("transparent", "unselected"), "selected_input", ("transparent", "always")),
        (("transparent", "unselected"), "unselected_input", ("none", "none")),
        (("transparent", "always"), "selected_input", ("transparent", "unselected")),
        (("transparent", "always"), "unselected_input", ("transparent", "selected")),
    ],
)
def test_clicking_a_box_writes_what_the_dialog_shows(
    main_window, ok_without_showing, fill_mode, box, expected
):
    """A click on a fill the boxes can show writes what it did before."""
    dialog = _dialog(main_window, fill_mode)
    try:
        getattr(dialog, box).click()
        trace, _ = dialog.exec()
        assert trace.fill_mode == expected
    finally:
        dialog.deleteLater()


def test_a_box_clicked_and_clicked_back_keeps_the_fill_mode(
    main_window, ok_without_showing
):
    """The rows read as they opened again, so OK leaves the stored value."""
    dialog = _dialog(main_window, ("solid", "none"))
    try:
        dialog.unselected_input.click()
        dialog.unselected_input.click()
        trace, _ = dialog.exec()
        assert trace.fill_mode == ("solid", None)
    finally:
        dialog.deleteLater()
