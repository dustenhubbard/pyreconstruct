"""The trace attributes dialog tells the user only about a real name change.

A name is saved with its end spaces dropped and its inner spaces and commas
turned into underscores (`normalizeObjectName`). A name that differed only by
an end space used to raise a note reading `Invalid name "a " changed to "a".`,
two names that look the same. End spaces now go without a note, and the note
for an inner change says what the name became.
"""

import pytest
from PySide6.QtWidgets import QDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def ok_without_showing(monkeypatch):
    """Make `QDialog.exec` press OK at once."""
    monkeypatch.setattr(QDialog, "exec", lambda self: 1)


@pytest.fixture
def notes(monkeypatch):
    """Collect each note the dialog would show, instead of a modal box."""
    shown = []
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.dialog.trace.notify",
        lambda message, *args, **kwargs: shown.append(message),
    )
    return shown


def _ok_with_name(main_window, typed):
    from PyReconstruct.modules.datatypes import Trace
    from PyReconstruct.modules.gui.dialog.trace import TraceDialog

    trace = Trace("start", (10, 20, 30), closed=True)
    trace.points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    dialog = TraceDialog(main_window, [trace])
    try:
        dialog.name_input.setText(typed)
        result, confirmed = dialog.exec()
    finally:
        dialog.deleteLater()
    assert confirmed
    return result


@pytest.mark.parametrize(
    "typed", ["calibrate_y{1} ", " calibrate_y{1}", "  calibrate_y{1}\t"]
)
def test_end_spaces_are_dropped_without_a_note(
    main_window, ok_without_showing, notes, typed
):
    trace = _ok_with_name(main_window, typed)

    assert trace.name == "calibrate_y{1}"
    assert notes == []


def test_a_plain_name_shows_no_note(main_window, ok_without_showing, notes):
    trace = _ok_with_name(main_window, "dendrite")

    assert trace.name == "dendrite"
    assert notes == []


@pytest.mark.parametrize(
    ("typed", "saved"),
    [("spine head", "spine_head"), ("a,b", "a_b"), (" d 1 ", "d_1")],
)
def test_inner_spaces_and_commas_get_a_plain_note(
    main_window, ok_without_showing, notes, typed, saved
):
    trace = _ok_with_name(main_window, typed)

    assert trace.name == saved
    assert len(notes) == 1
    assert f'"{saved}"' in notes[0]
    assert "Invalid" not in notes[0]
