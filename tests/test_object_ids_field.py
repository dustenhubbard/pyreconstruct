"""Object ids through the field's own undo and redo (FieldWidgetBase.saveState
and undoState), and through an object list delete undone on one section."""
import pytest

from tests.test_undo_object_followups import (
    _delete,
    _draw,
    _object_list,
    _traces,
)

pytestmark = pytest.mark.gui

NAME = "ids_field_obj"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def _ids(window):
    return window.series.data.object_ids


def test_field_undo_and_redo_put_back_the_ids(window):
    snum = window.series.current_section
    ids = _ids(window)

    _draw(window, NAME)
    old = ids.peek(snum, NAME)
    assert old is not None
    _delete(window, _traces(window, NAME))
    assert ids.live(NAME) == set()
    _draw(window, NAME)
    new = ids.peek(snum, NAME)
    assert new not in (None, old)

    window.undo()
    assert ids.live(NAME) == set()
    window.undo()
    assert ids.peek(snum, NAME) == old
    window.undo(redo=True)
    assert ids.live(NAME) == set()
    window.undo(redo=True)
    assert ids.peek(snum, NAME) == new


def test_object_list_delete_undone_on_one_section(
        window, monkeypatch, main_window_dialogs):
    series = window.series
    s1, s2 = sorted(series.sections)[:2]
    window.changeSection(s2)
    _draw(window, NAME)
    window.changeSection(s1)
    _draw(window, NAME)
    old = _ids(window).peek(s1, NAME)
    assert _ids(window).peek(s2, NAME) == old

    _object_list(window, monkeypatch, [NAME])
    window.field.deleteObjects()
    assert _ids(window).live(NAME) == set()

    main_window_dialogs.linked_undo_responses.append("section")
    window.undo()
    assert _ids(window).peek(s1, NAME) == old
    assert _ids(window).peek(s2, NAME) is None


def _two_live_ids(window):
    """NAME on two sections under two ids: draw it on the first, delete it,
    draw a new one on the second, and undo the delete on the first."""
    series = window.series
    s1, s2 = sorted(series.sections)[1], sorted(series.sections)[3]
    window.changeSection(s1)
    _draw(window, NAME)
    old = _ids(window).peek(s1, NAME)
    _delete(window, _traces(window, NAME))
    window.changeSection(s2)
    _draw(window, NAME)
    new = _ids(window).peek(s2, NAME)
    window.changeSection(s1)
    window.undo()
    assert _ids(window).live(NAME) == {old, new} and old != new
    return s1, s2, old, new


def _unlock_sections(window):
    """The section list refuses to delete or reorder locked sections."""
    series = window.series
    for snum in sorted(series.sections):
        section = series.loadSection(snum)
        section.align_locked = False
        section.save()
    for section in (window.field.section, window.field.b_section):
        if section is not None:
            section.align_locked = False


def _section_list(window):
    window.field.table_manager.newTable("section")
    return window.field.table_manager.tables["section"][-1]


def _select(widget, snum):
    table = widget.table
    table.clearSelection()
    for r in range(table.rowCount()):
        if int(table.item(r, 0).text().split()[0]) == snum:
            table.selectRow(r)
            return
    raise AssertionError(f"row for section {snum} not found")


def test_section_list_insert_keeps_both_ids(window, gui_dialogs):
    s1, s2, old, new = _two_live_ids(window)
    top = min(window.series.sections)
    widget = _section_list(window)
    _select(widget, top)
    gui_dialogs.responses.append((["", top, 0.00254, 0.05], True))
    widget.insertSection(before=True)

    ids = _ids(window)
    assert ids.peek(s1 + 1, NAME) == old
    assert ids.peek(s2 + 1, NAME) == new
    assert ids.live(NAME) == {old, new}


def test_section_list_delete_and_reorder_keep_both_ids(window, gui_dialogs):
    s1, s2, old, new = _two_live_ids(window)
    _unlock_sections(window)
    top = min(window.series.sections)
    widget = _section_list(window)
    _select(widget, top)
    widget.deleteSections()
    assert top not in window.series.sections
    assert _ids(window).peek(s1, NAME) == old
    assert _ids(window).peek(s2, NAME) == new

    widget = _section_list(window)
    widget.reorderSections()
    ids = _ids(window)
    assert ids.peek(s1 - 1, NAME) == old
    assert ids.peek(s2 - 1, NAME) == new
    assert ids.live(NAME) == {old, new}


def test_section_list_delete_then_insert_on_the_same_number(window, gui_dialogs):
    """Delete the last section, insert a new one past the end (it takes the
    deleted number's file), and draw the same name there: a new object."""
    series = window.series
    last = max(series.sections)
    window.changeSection(last)
    _draw(window, NAME)
    old = _ids(window).peek(last, NAME)
    _unlock_sections(window)

    widget = _section_list(window)
    _select(widget, last)
    widget.deleteSections()
    assert last not in series.sections
    assert _ids(window).live(NAME) == set()

    widget = _section_list(window)
    _select(widget, min(series.sections))
    gui_dialogs.responses.append((["", last, 0.00254, 0.05], True))
    widget.insertSection(before=True)
    assert last in series.sections

    window.changeSection(last)
    _draw(window, NAME)
    assert _ids(window).peek(last, NAME) not in (None, old)
