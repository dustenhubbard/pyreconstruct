"""A section undo that empties a group drops the group's visibility entry.

Undoing the draw of an object's only trace deletes the object, and its groups
go with it, but the group's visibility entry stayed. `View` > `Groups` lists
groups from those entries, so the empty group kept its row. Worse, a series
undo that later brought the group back found the stale entry and kept it: a
group hidden before `Remove from all groups` came back shown. The undo now
drops the entry and keeps its value on the redo state, so a redo brings the
group back with the visibility it had.
"""
import pytest

from conftest import submenu_at
from PyReconstruct.modules.datatypes.trace import Trace

pytestmark = pytest.mark.gui

GROUP = "undoviz_group"
OTHER = "undoviz_other"
DRAWN = "undoviz_drawn"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    # a second group keeps the Groups submenu in the menubar once GROUP is
    # gone, so the row checks look at a real menu
    series = main_window.series
    keeper = sorted(series.data["objects"].keys())[-1]
    series.object_groups.add(group=OTHER, obj=keeper)
    series.groups_visibility[OTHER] = True
    main_window.createMenuBar()
    yield main_window
    main_window.series.setProgressReporter(None)


def _square(series, offset):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


def _draw_into_group(window, name=DRAWN, offset=0.6):
    """Draw an object's first trace from a palette item that puts it in
    GROUP. newTrace is a field_interaction: it saves its own undo step."""
    field = window.field
    item = Trace(name, (0, 255, 0), True)
    item.obj_defaults = {"groups": [GROUP]}
    field.setTracingTrace(item)
    field.newTrace(_square(window.series, offset), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)


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
def test_undo_drops_the_row_and_redo_brings_it_back(window, visible):
    series = window.series
    _draw_into_group(window)
    series.groups_visibility[GROUP] = visible
    window.createMenuBar()
    assert GROUP in _menu_groups(window)

    window.undo()
    assert GROUP not in series.object_groups.getGroupList()
    assert GROUP not in series.groups_visibility
    assert GROUP not in _menu_groups(window)
    assert OTHER in _menu_groups(window)

    window.undo(redo=True)
    assert series.object_groups.getGroupObjects(GROUP) == {DRAWN}
    assert series.groups_visibility[GROUP] is visible
    assert GROUP in _menu_groups(window)

    # and the round again: the redo did not lose what the next undo keeps
    window.undo()
    assert GROUP not in series.groups_visibility
    window.undo(redo=True)
    assert series.groups_visibility[GROUP] is visible


def test_a_group_hidden_before_its_last_object_left_comes_back_hidden(
        window, monkeypatch):
    """Remove the last object from a hidden group, draw an object the palette
    puts in that group, undo the draw, undo the removal."""
    series = window.series
    first = sorted(series.data["objects"].keys())[0]
    series.object_groups.add(group=GROUP, obj=first)
    series.groups_visibility[GROUP] = False
    window.createMenuBar()

    field = _select(window, monkeypatch, [first])
    field.removeFromAllGroups()
    assert GROUP not in series.groups_visibility

    _draw_into_group(window)
    assert series.groups_visibility[GROUP] is True   # a new group is shown

    window.undo()                                    # the draw
    assert GROUP not in series.object_groups.getGroupList()
    assert GROUP not in series.groups_visibility
    assert GROUP not in _menu_groups(window)

    window.undo()                                    # the removal
    assert series.object_groups.getGroupObjects(GROUP) == {first}
    assert series.groups_visibility[GROUP] is False, (
        "the group came back shown"
    )
    assert GROUP in _menu_groups(window)

    window.undo(redo=True)                           # the removal again
    assert GROUP not in series.object_groups.getGroupList()
    assert GROUP not in series.groups_visibility

    window.undo(redo=True)                           # the draw again
    assert series.object_groups.getGroupObjects(GROUP) == {DRAWN}
    assert series.groups_visibility[GROUP] is True
    assert GROUP in _menu_groups(window)


def test_redo_keeps_the_visibility_the_group_had_at_the_undo(window):
    """Hidden after the draw, so the redo brings it back hidden."""
    series = window.series
    _draw_into_group(window)
    assert series.groups_visibility[GROUP] is True
    window.toggleGroupViz(GROUP)
    assert series.groups_visibility[GROUP] is False

    window.undo()
    window.undo(redo=True)
    assert series.groups_visibility[GROUP] is False


def test_an_undo_that_leaves_a_member_keeps_the_entry(window):
    """GROUP still holds another object after the undo, so it keeps its
    entry and its row."""
    series = window.series
    first = sorted(series.data["objects"].keys())[0]
    series.object_groups.add(group=GROUP, obj=first)
    series.groups_visibility[GROUP] = False
    window.createMenuBar()

    _draw_into_group(window)
    window.undo()
    assert series.object_groups.getGroupObjects(GROUP) == {first}
    assert GROUP in series.groups_visibility
    assert GROUP in _menu_groups(window)
