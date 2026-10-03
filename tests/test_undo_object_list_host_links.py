"""A host link an object list delete drops comes back on undo.

H hosts T. H is only on one section and T only on another. One of them is
deleted from the object list and the other on the field. Undoing the object
list delete with `Only this section` first brings that object back while the
other one is still gone, so its copy cannot put the link back. A field delete
keeps such a link until both objects are back (recordDroppedHostLinks); the
object list delete now keeps it too.
"""
import pytest

from test_undo_object_followups import (
    _delete, _draw, _object_list, _traces, NAME, OTHER,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


@pytest.mark.parametrize("listed", ["host", "traveler"])
def test_a_link_an_object_list_delete_dropped_comes_back(
        window, monkeypatch, main_window_dialogs, listed):
    series = window.series
    host, traveler = NAME, OTHER
    first, second = sorted(series.sections)[:2]
    where = {host: first, traveler: second}
    window.changeSection(first)
    _draw(window, host)
    window.changeSection(second)
    _draw(window, traveler)
    series.host_tree.add(traveler, [host])

    listed, other = (host, traveler) if listed == "host" else (traveler, host)
    window.changeSection(where[listed])
    _object_list(window, monkeypatch, [listed])
    window.field.deleteObjects()
    assert listed not in series.data["objects"]
    window.changeSection(where[other])
    _delete(window, _traces(window, other))
    assert other not in series.data["objects"]

    window.changeSection(where[listed])
    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo()
    assert listed in series.data["objects"]
    window.changeSection(where[other])
    window.undo()
    assert other in series.data["objects"]
    assert series.host_tree.getHosts(traveler) == [host]


def test_a_series_undo_of_an_object_list_delete_keeps_the_link(
        window, monkeypatch, main_window_dialogs):
    """The usual undo of the whole delete still brings the link back."""
    series = window.series
    host, traveler = NAME, OTHER
    first, second = sorted(series.sections)[:2]
    window.changeSection(first)
    _draw(window, host)
    window.changeSection(second)
    _draw(window, traveler)
    series.host_tree.add(traveler, [host])

    window.changeSection(first)
    _object_list(window, monkeypatch, [host])
    window.field.deleteObjects()
    main_window_dialogs.linked_undo_responses = ["all"]
    window.undo()
    assert host in series.data["objects"]
    assert series.host_tree.getHosts(traveler) == [host]


def test_a_redone_object_list_delete_keeps_the_link_too(
        window, monkeypatch, main_window_dialogs):
    """The same, after the object list delete was undone and redone."""
    series = window.series
    host, traveler = NAME, OTHER
    first, second = sorted(series.sections)[:2]
    window.changeSection(first)
    _draw(window, host)
    window.changeSection(second)
    _draw(window, traveler)
    series.host_tree.add(traveler, [host])

    window.changeSection(first)
    _object_list(window, monkeypatch, [host])
    window.field.deleteObjects()
    main_window_dialogs.linked_undo_responses = ["all", "all"]
    window.undo()
    window.undo(redo=True)
    assert host not in series.data["objects"]
    window.changeSection(second)
    _delete(window, _traces(window, traveler))

    window.changeSection(first)
    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo()
    assert host in series.data["objects"]
    window.changeSection(second)
    window.undo()
    assert traveler in series.data["objects"]
    assert series.host_tree.getHosts(traveler) == [host]
