"""Group and 3D edits around series undo.

* A series undo that brings back a group removed with its last object now
  restores the group's visibility entry and rebuilds the Groups menu, so the
  group has its row again, hidden if it was hidden. The redo drops the entry
  and the row again.
* `removeFromAllGroups` no longer assumes an emptied group still has a
  visibility entry.
* `edit3D` adds no undo state when no object changes, so a dialog closed with
  the same values keeps the redo history.
"""
import types

import pytest

from conftest import submenu_at
from PyReconstruct.modules.gui.main import field_widget_3_object as fw3

GROUP = "groupundo_group"
OTHER = "groupundo_other"


def _select_in_list(main_window, monkeypatch, names):
    field = main_window.field
    field.openList("object")
    table = field.table_manager.tables["object"][0]
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: table)
    monkeypatch.setattr(table, "getSelected", lambda: list(names))
    return field


def _group_of_one(series, visible=True):
    names = sorted(series.data["objects"].keys())
    assert len(names) > 1, "fixture series has too few objects"
    a = names[0]
    assert GROUP not in series.object_groups.getGroupList()
    series.object_groups.add(group=GROUP, obj=a)
    series.groups_visibility[GROUP] = visible
    return a


def _menu_groups(main_window):
    """The rows of `View` > `Groups` in the live menubar. The submenu exists
    only while the series has a group, so none means no rows."""
    menu = submenu_at(main_window.menubar, "View > Groups")
    return [] if menu is None else [row.text() for row in menu.actions()]


def _count_rebuilds(main_window, monkeypatch):
    rebuilds = []
    real = main_window.createMenuBar

    def counting(*args, **kwargs):
        rebuilds.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(main_window, "createMenuBar", counting)
    return rebuilds


@pytest.mark.gui
def test_undo_brings_back_the_group_row_and_its_visibility(main_window, monkeypatch):
    series = main_window.series
    a = _group_of_one(series, visible=False)
    # a second group keeps the Groups submenu in the menubar once GROUP is
    # gone, so the row checks below look at a real menu
    b = sorted(series.data["objects"].keys())[1]
    assert OTHER not in series.object_groups.getGroupList()
    series.object_groups.add(group=OTHER, obj=b)
    series.groups_visibility[OTHER] = True
    main_window.createMenuBar()
    assert GROUP in _menu_groups(main_window)

    field = _select_in_list(main_window, monkeypatch, [a])
    field.removeFromAllGroups()
    assert GROUP not in series.groups_visibility
    assert GROUP not in _menu_groups(main_window)
    assert OTHER in _menu_groups(main_window)

    rebuilds = _count_rebuilds(main_window, monkeypatch)
    main_window.undo()

    assert series.object_groups.getGroupObjects(GROUP) == {a}
    assert series.groups_visibility[GROUP] is False
    assert GROUP in _menu_groups(main_window)
    assert len(rebuilds) == 1

    main_window.undo(redo=True)
    assert GROUP not in series.object_groups.getGroupList()
    assert GROUP not in series.groups_visibility
    assert GROUP not in _menu_groups(main_window)
    assert OTHER in _menu_groups(main_window)
    assert len(rebuilds) == 2

    # the entry the redo dropped comes back with the next undo
    main_window.undo()
    assert series.groups_visibility[GROUP] is False
    assert GROUP in _menu_groups(main_window)


@pytest.mark.gui
def test_undo_that_leaves_the_groups_alone_does_not_rebuild(main_window, monkeypatch):
    series = main_window.series
    a = _group_of_one(series)
    series.setAttr(a, "comment", "before")
    series_states = main_window.field.series_states
    series_states.addState()
    series.setAttr(a, "comment", "after")

    rebuilds = _count_rebuilds(main_window, monkeypatch)
    main_window.undo()

    assert series.getAttr(a, "comment") == "before"
    assert rebuilds == []


@pytest.mark.gui
def test_remove_from_all_groups_without_a_visibility_entry(main_window, monkeypatch):
    series = main_window.series
    a = _group_of_one(series)
    series.groups_visibility.pop(GROUP)

    field = _select_in_list(main_window, monkeypatch, [a])
    field.removeFromAllGroups()

    assert GROUP not in series.object_groups.getGroupList()
    assert GROUP not in series.groups_visibility


# ---------------------------------------------------------------------------
# edit3D, on a stub driven through object_function's wrapper
# ---------------------------------------------------------------------------

class _Series:
    def __init__(self, attrs):
        self.attrs = attrs
        self.jser_fp = "/tmp/stub.jser"

    def getAttr(self, name, attr_name, ztrace=False):
        defaults = {"3D_mode": "surface", "3D_opacity": 1, "locked": False}
        return self.attrs.get(name, {}).get(attr_name, defaults.get(attr_name))

    def setAttr(self, name, attr_name, value, ztrace=False):
        self.attrs.setdefault(name, {})[attr_name] = value


def _field(series, names):
    states = types.SimpleNamespace(calls=0)
    states.addState = lambda *a, **k: setattr(states, "calls", states.calls + 1)
    modified = []
    return types.SimpleNamespace(
        series=series,
        series_states=states,
        modified=modified,
        table_manager=types.SimpleNamespace(
            hasFocus=lambda: None,
            updateObjects=lambda names: None,
            refresh=lambda: None,
        ),
        section=types.SimpleNamespace(
            selected_traces=[types.SimpleNamespace(name=n) for n in names]
        ),
        mainwindow=types.SimpleNamespace(
            saveAllData=lambda: None,
            seriesModified=modified.append,
            viewer=None,
        ),
    )


def _answer(monkeypatch, response):
    monkeypatch.setattr(
        fw3, "QuickDialog",
        types.SimpleNamespace(get=lambda *a, **k: (response, True)),
    )


@pytest.mark.parametrize("response", [
    ["spheres", 0.5],    # the values both objects already have
    [None, None],        # mixed fields left blank
])
def test_edit3d_with_nothing_changed_adds_no_state(monkeypatch, response):
    series = _Series({
        "a": {"3D_mode": "spheres", "3D_opacity": 0.5},
        "b": {"3D_mode": "spheres", "3D_opacity": 0.5},
    })
    field = _field(series, ["a", "b"])
    _answer(monkeypatch, response)

    fw3.FieldWidgetObject.edit3D(field)

    assert field.series_states.calls == 0
    assert field.modified == []


def test_edit3d_that_changes_one_object_adds_a_state(monkeypatch):
    series = _Series({
        "a": {"3D_mode": "spheres", "3D_opacity": 0.5},
        "b": {"3D_mode": "spheres", "3D_opacity": 0.8},
    })
    field = _field(series, ["a", "b"])
    _answer(monkeypatch, ["spheres", 0.8])

    fw3.FieldWidgetObject.edit3D(field)

    assert field.series_states.calls == 1
    assert series.getAttr("a", "3D_opacity") == 0.8
    assert field.modified == [True]
