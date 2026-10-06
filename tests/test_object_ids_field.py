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
