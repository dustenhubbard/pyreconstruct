"""An Object List delete that empties a group drops the group's row.

Deleting an object through the Object List deletes it on every section, and
its groups go with it, but the group's visibility entry stayed. `View` >
`Groups` lists groups from those entries, so the empty group kept its row
until an undo and a redo of the delete removed it. The delete now drops the
entry and rebuilds the menu; a series undo brings the group back with the
visibility it had, and the redo drops it again.
"""
import pytest

from conftest import submenu_at

pytestmark = pytest.mark.gui

GROUP = "listdel_group"
OTHER = "listdel_other"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    # a second group keeps the Groups submenu in the menubar once GROUP is
    # gone, so the row checks look at a real menu
    series = main_window.series
    keeper = sorted(series.data["objects"].keys())[-1]
    series.object_groups.add(group=OTHER, obj=keeper)
    series.groups_visibility[OTHER] = False
    yield main_window
    main_window.series.setProgressReporter(None)


def _menu_groups(window):
    menu = submenu_at(window.menubar, "View > Groups")
    return [] if menu is None else [row.text() for row in menu.actions()]


def _select(window, monkeypatch, names):
    field = window.field
    field.openList("object")
    table = field.table_manager.tables["object"][0]
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: table)
    monkeypatch.setattr(table, "getSelected", lambda: list(names))
    return field


@pytest.mark.parametrize("visible", [True, False])
def test_object_list_delete_drops_the_row_of_the_group_it_empties(
        window, monkeypatch, visible):
    series = window.series
    victim = sorted(series.data["objects"].keys())[0]
    series.object_groups.add(group=GROUP, obj=victim)
    series.groups_visibility[GROUP] = visible
    window.createMenuBar()
    assert GROUP in _menu_groups(window)

    field = _select(window, monkeypatch, [victim])
    field.deleteObjects()
    assert victim not in series.data["objects"]
    assert GROUP not in series.object_groups.getGroupList()
    assert GROUP not in series.groups_visibility
    assert GROUP not in _menu_groups(window)
    assert series.groups_visibility[OTHER] is False
    assert OTHER in _menu_groups(window)

    for _ in range(2):
        field.seriesUndo()
        assert victim in series.data["objects"]
        assert series.object_groups.getGroupObjects(GROUP) == {victim}
        assert series.groups_visibility[GROUP] is visible
        assert GROUP in _menu_groups(window)

        field.seriesUndo(redo=True)
        assert victim not in series.data["objects"]
        assert GROUP not in series.groups_visibility
        assert GROUP not in _menu_groups(window)
        assert series.groups_visibility[OTHER] is False
