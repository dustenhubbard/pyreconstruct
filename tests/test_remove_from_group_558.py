"""Removing objects from a group they do not all belong to (fork #558).

`removeFromGroup` deleted the group's visibility entry inside the per-object
loop. With group G holding only A, removing A and B from G emptied G on A and
then ran the delete again on B, which raised KeyError.
"""
import pytest

from PyReconstruct.modules.gui.main import field_widget_3_object as fw3

pytestmark = pytest.mark.gui

GROUP = "issue558_group"


def _remove(main_window, monkeypatch, names, group):
    class Dialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return group, True

    monkeypatch.setattr(fw3, "ObjectGroupDialog", Dialog)
    field = main_window.field
    field.openList("object")
    table = field.table_manager.tables["object"][0]
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: table)
    monkeypatch.setattr(table, "getSelected", lambda: list(names))

    rebuilds = []
    real = main_window.createMenuBar

    def counting(*args, **kwargs):
        rebuilds.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(main_window, "createMenuBar", counting)
    field.removeFromGroup()
    return len(rebuilds)


def _group_of_one(series):
    names = sorted(series.data["objects"].keys())
    assert len(names) > 2, "fixture series has too few objects"
    a, b = names[0], names[1]
    assert GROUP not in series.object_groups.getGroupList()
    series.object_groups.add(group=GROUP, obj=a)
    series.groups_visibility[GROUP] = True
    return a, b


def test_removing_a_selection_wider_than_the_group(main_window, monkeypatch):
    series = main_window.series
    a, b = _group_of_one(series)

    rebuilds = _remove(main_window, monkeypatch, [a, b], GROUP)

    assert rebuilds == 1
    assert GROUP not in series.object_groups.getGroupList()
    assert GROUP not in series.groups_visibility


def test_removing_part_of_a_group_keeps_it(main_window, monkeypatch):
    series = main_window.series
    a, b = _group_of_one(series)
    series.object_groups.add(group=GROUP, obj=b)

    rebuilds = _remove(main_window, monkeypatch, [a], GROUP)

    assert rebuilds == 0
    assert series.object_groups.getGroupObjects(GROUP) == {b}
    assert series.groups_visibility[GROUP] is True


def test_undo_redo_then_remove_again(main_window, monkeypatch):
    series = main_window.series
    a, b = _group_of_one(series)
    _remove(main_window, monkeypatch, [a, b], GROUP)

    main_window.undo()
    assert series.object_groups.getGroupObjects(GROUP) == {a}

    main_window.undo(redo=True)
    assert GROUP not in series.object_groups.getGroupList()

    # Undo brings the group back without its visibility entry, so removing
    # it again must not assume the entry is there.
    main_window.undo()
    assert series.object_groups.getGroupObjects(GROUP) == {a}
    _remove(main_window, monkeypatch, [a], GROUP)
    assert GROUP not in series.object_groups.getGroupList()
    assert GROUP not in series.groups_visibility
