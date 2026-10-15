"""The field shows a label while focus mode is on.

`Toggle focus mode` recolors the field and hides z-traces and flags, and before
this label nothing on screen said focus mode was on, which object it was on, or
how to leave it. The label names the object and the live shortcut of
`focus_act`, so a rebind in the shortcuts dialog shows up in it.
"""

import pytest
from PySide6.QtGui import QKeySequence

pytestmark = pytest.mark.gui

# An object on section 52, the section the fixture series opens on, and on 53.
OBJ = "d03p14"
NEXT_SECTION = 53


def _native(key: str) -> str:
    return QKeySequence(key).toString(QKeySequence.NativeText)


@pytest.fixture
def window(main_window, main_window_dialogs, local_series_settings):
    """A window with one trace of `OBJ` selected and the default shortcuts."""
    local_series_settings(main_window)
    field = main_window.field
    assert field.section.n == 52
    field.section.selected_traces.clear()
    field.section.addSelectedTrace(field.section.contours[OBJ][0])
    return main_window


def _hint(window):
    return window.field.focus_hint


def test_no_label_before_focus_mode(window):
    assert not _hint(window).isVisibleTo(window.field)


def test_label_names_the_object_and_the_shortcut(window):
    window.field.toggleFocusMode()
    assert window.field.focus_mode == OBJ
    hint = _hint(window)
    assert hint.isVisibleTo(window.field)
    assert hint.text() == f"Focus: {OBJ}. Press {_native('X')} to exit."


def test_label_stays_through_a_section_change(window):
    window.field.toggleFocusMode()
    window.field.changeSection(NEXT_SECTION)
    assert window.field.section.n == NEXT_SECTION
    hint = _hint(window)
    assert hint.isVisibleTo(window.field)
    assert hint.text() == f"Focus: {OBJ}. Press {_native('X')} to exit."


def test_label_goes_away_when_focus_mode_turns_off(window):
    window.field.toggleFocusMode()
    window.field.toggleFocusMode()
    assert window.field.focus_mode is False
    assert not _hint(window).isVisibleTo(window.field)


def test_label_goes_away_when_the_field_is_rebuilt(window):
    """`createField` resets focus mode when a series is opened or reloaded."""
    window.field.toggleFocusMode()
    window.field.createField(window.series)
    assert window.field.focus_mode is False
    assert not _hint(window).isVisibleTo(window.field)


def test_label_follows_a_rebound_shortcut(window):
    window.field.toggleFocusMode()
    window.resetShortcuts({"focus_act": "Shift+F"})
    assert _hint(window).text() == f"Focus: {OBJ}. Press {_native('Shift+F')} to exit."


def test_label_with_no_shortcut_names_the_menu(window):
    window.resetShortcuts({"focus_act": ""})
    window.field.toggleFocusMode()
    assert _hint(window).text() == (
        f"Focus: {OBJ}. Use View > Toggle focus mode in the right-click menu to exit."
    )


def test_label_shows_a_name_as_plain_text(window):
    """An object name is never read as markup."""
    from PySide6.QtCore import Qt

    assert _hint(window).textFormat() == Qt.PlainText


def test_label_sits_inside_the_field_and_passes_clicks_through(window):
    from PySide6.QtCore import Qt

    field = window.field
    field.toggleFocusMode()
    hint = _hint(window)
    assert hint.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert field.rect().contains(hint.geometry())
    # centered horizontally, within a pixel
    assert abs(hint.geometry().center().x() - field.rect().center().x()) <= 1


def test_label_wraps_to_stay_inside_a_narrow_field(window):
    """A field narrower than the text wraps it rather than cutting it off."""
    field = window.field
    window.resetShortcuts({"focus_act": ""})  # the longest text
    field.toggleFocusMode()
    hint = _hint(window)
    one_line = hint.geometry().height()

    field.resize(220, field.height())
    assert field.width() == 220
    assert field.rect().contains(hint.geometry())
    assert hint.geometry().height() > one_line
    assert hint.text().endswith("to exit.")
