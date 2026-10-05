"""Scratch repros for the undo follow-up items (not for commit)."""
import pytest

from tests.test_undo_object_followups import (
    window, _draw, _traces, _delete, _object, _carry, _object_list,
    NAME, OTHER,
)

pytestmark = pytest.mark.gui


def _setup_link(window):
    series = window.series
    host, traveler = NAME, OTHER
    s = sorted(series.sections)[:3]
    window.changeSection(s[0])
    _draw(window, host)
    window.changeSection(s[1])
    _draw(window, traveler)
    series.host_tree.add(traveler, [host])
    return host, traveler, s


def test_1a_undo_draw_that_reused_old_name(window):
    """T deleted, then H deleted, new H drawn and undone; undo T then H."""
    series = window.series
    host, traveler, s = _setup_link(window)
    window.changeSection(s[1])
    _delete(window, _traces(window, traveler))
    window.changeSection(s[0])
    _delete(window, _traces(window, host))
    window.changeSection(s[2])
    _draw(window, host)
    window.undo()
    assert host not in series.data["objects"]
    window.changeSection(s[1])
    window.undo()
    window.changeSection(s[0])
    window.undo()
    assert host in series.data["objects"] and traveler in series.data["objects"]
    assert series.host_tree.getHosts(traveler) == [host]


@pytest.mark.parametrize("which", ["host", "traveler"])
def test_1b_object_list_delete_records_link(window, monkeypatch,
                                            main_window_dialogs, which):
    """One of them deleted from the object list, the other on the field;
    undo the object list one on this section only first, then the other."""
    series = window.series
    host, traveler, s = _setup_link(window)
    where = {host: s[0], traveler: s[1]}
    listed = host if which == "host" else traveler
    other = traveler if listed == host else host
    _object_list(window, monkeypatch, [listed])
    window.changeSection(where[listed])
    window.field.deleteObjects()
    window.changeSection(where[other])
    _delete(window, _traces(window, other))
    window.changeSection(where[listed])
    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo()
    window.changeSection(where[other])
    window.undo()
    assert host in series.data["objects"] and traveler in series.data["objects"]
    assert series.host_tree.getHosts(traveler) == [host]


@pytest.mark.parametrize("undo_on", [0, 1])
def test_1c_multi_section_rename_this_section(window, main_window_dialogs,
                                              undo_on):
    series = window.series
    s = sorted(series.sections)[:2]
    window.changeSection(s[1])
    _draw(window)
    window.changeSection(s[0])
    _draw(window)
    carried = _carry(window)
    window.saveAllData()
    series.editObjectAttributes([NAME], name="undofu_new",
                                series_states=window.field.series_states)
    window.field.reload()
    window.field.table_manager.recreateTables()
    assert NAME not in series.data["objects"]
    window.changeSection(s[undo_on])
    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo()
    assert NAME in series.data["objects"]
    assert _object(series) == carried


def test_3_field_rename_one_section(window):
    series = window.series
    _draw(window)
    carried = _carry(window)
    field = window.field
    field.section.editTraceAttributes(
        traces=_traces(window), name=OTHER, color=None, tags=None, mode=None)
    field.saveState()
    assert NAME not in series.data["objects"]
    window.undo()
    assert NAME in series.data["objects"]
    assert _object(series) == carried
    window.undo(redo=True)
    window.undo()
    assert _object(series) == carried


def test_3_object_list_rename_one_section_series_undo(window, main_window_dialogs):
    series = window.series
    main_window_dialogs.linked_undo_responses = ["all", "all", "all"]
    _draw(window)
    carried = _carry(window)
    window.saveAllData()
    series.editObjectAttributes([NAME], name=OTHER,
                                series_states=window.field.series_states)
    window.field.reload()
    window.field.table_manager.recreateTables()
    window.undo()
    assert NAME in series.data["objects"]
    assert _object(series) == carried
    window.undo(redo=True)
    window.undo()
    assert _object(series) == carried


def test_3_partial_rename_one_section_this_section(window, main_window_dialogs):
    """A rename limited to one section of a two-section object."""
    series = window.series
    s = sorted(series.sections)[:2]
    window.changeSection(s[1])
    _draw(window)
    window.changeSection(s[0])
    _draw(window)
    carried = _carry(window)
    window.saveAllData()
    series.editObjectAttributes([NAME], name=OTHER, sections=[s[0]],
                                series_states=window.field.series_states)
    window.field.reload()
    window.field.table_manager.recreateTables()
    assert NAME in series.data["objects"]
    window.changeSection(s[1])
    _delete(window, _traces(window, NAME))
    assert NAME not in series.data["objects"]
    window.undo()
    assert _object(series) == carried
    window.changeSection(s[0])
    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo()
    assert _object(series) == carried
