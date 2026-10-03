"""Undo with `Only this section` on the first section of an object list
rename brings the old object back with its hosts.

The rename moves the object's hosts to the new name before the first section
is changed. The object still has traces on the later sections when the first
section's state is added, so that state copied it from the series as it was
then, with no hosts. Each object the action took off a section now gets its
copy from before the action.
"""
import pytest

from test_undo_object_followups import (
    _carry, _draw, _object, NAME, OTHER,
)

pytestmark = pytest.mark.gui

NEW = "undofu_new"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def _rename(window, names, name, sections=None):
    window.saveAllData()
    window.series.editObjectAttributes(
        names, name=name, sections=sections,
        series_states=window.field.series_states,
    )
    window.field.reload()
    window.field.table_manager.recreateTables()


def _two_sections(window, traveler=False):
    series = window.series
    first, second = sorted(series.sections)[:2]
    window.changeSection(second)
    _draw(window)
    window.changeSection(first)
    _draw(window)
    if traveler:
        _draw(window, OTHER, offset=0.5)
        series.host_tree.add(OTHER, [NAME])
    return first, second


@pytest.mark.parametrize("undo_on", [0, 1])
def test_a_rename_undone_on_one_section_keeps_the_hosts(
        window, main_window_dialogs, undo_on):
    series = window.series
    sections = _two_sections(window)
    carried = _carry(window)
    assert carried["hosts"]

    _rename(window, [NAME], NEW)
    assert NAME not in series.data["objects"]
    window.changeSection(sections[undo_on])
    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo()
    assert NAME in series.data["objects"]
    assert _object(series) == carried


def test_a_rename_undone_on_one_section_keeps_the_travelers(
        window, main_window_dialogs):
    series = window.series
    first, second = _two_sections(window, traveler=True)

    _rename(window, [NAME], NEW)
    assert series.host_tree.getHosts(OTHER) == [NEW]
    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo()
    assert NAME in series.data["objects"]
    # the new name keeps its traces on the other section, and its link
    assert NAME in series.host_tree.getHosts(OTHER)

