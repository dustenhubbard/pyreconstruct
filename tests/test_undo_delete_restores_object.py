"""Undoing the delete of an object's last trace brings the whole object back.

Deleting an object's last trace deletes the object, and SeriesData clears its
attributes, groups, hosts and travelers (removeObjAttrs). Section undo states
hold only traces, so the undo brought the trace back bare: no groups, no
custom column values, no comment or 3D settings, no hosts. The state of the
delete already held a copy of all of it, taken before the clear, and only a
redo used it. The undo now puts it back too.

The delete also left the emptied group's visibility entry, so `View` >
`Groups` kept a row for it. The delete now drops the entry and the state keeps
its value, so the undo brings a hidden group back hidden.
"""
import pytest

from conftest import submenu_at
from PyReconstruct.modules.datatypes.trace import Trace

pytestmark = pytest.mark.gui

NAME = "undodel_obj"
GROUP = "undodel_group"
KEEP = "undodel_keep"


@pytest.fixture
def window(main_window):
    from PyReconstruct.modules.backend.progress import NullProgressReporter

    main_window.series.setProgressReporter(NullProgressReporter)
    yield main_window
    main_window.series.setProgressReporter(None)


def _square(series, offset):
    wx, wy, ww, wh = series.window
    side = min(ww, wh) * 0.1
    x0, y0 = wx + ww * offset, wy + wh * offset
    return [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]


def _draw(window, defaults=None, offset=0.2, name=NAME):
    field = window.field
    item = Trace(name, (0, 255, 0), True)
    item.obj_defaults = defaults
    field.setTracingTrace(item)
    # newTrace is a field_interaction: it saves its own undo step
    field.newTrace(_square(window.series, offset), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)


def _traces(window, name=NAME):
    return [t for t in window.field.section.tracesAsList() if t.name == name]


def _delete(window, traces):
    """Delete these traces the way the user does: select them, then delete.
    deleteTraces is a trace_function, so it acts on the selection."""
    window.field.section.selected_traces = list(traces)
    window.field.deleteTraces()


def _menu_groups(window):
    menu = submenu_at(window.menubar, "View > Groups")
    return [] if menu is None else [row.text() for row in menu.actions()]


def _object(series):
    """What the object carries, minus what any edit rewrites."""
    attrs = dict(series.obj_attrs.get(NAME) or {})
    attrs.pop("last_user", None)
    return {
        "attrs": attrs,
        "groups": sorted(series.object_groups.getObjectGroups(NAME)),
        "hosts": sorted(series.host_tree.getHosts(NAME)),
        "travelers": sorted(series.host_tree.getTravelers(NAME)),
    }


@pytest.fixture
def full_object(window):
    """An object with one trace, a group, a custom column value, a comment,
    a 3D opacity, an alignment pin, a host and a traveler."""
    series = window.series
    series.addUserCol("Reviewer", ["KH", "DH"], log_event=False)
    _draw(window, {"groups": [GROUP], "user_columns": {"Reviewer": "KH"}})
    series.setAttr(NAME, "comment", "keep me")
    series.setAttr(NAME, "3D_opacity", 0.3)
    # an alignment pin other than the current alignment
    pin = next(a for a in series.alignments if a != series.alignment)
    series.setAttr(NAME, "alignment", pin)
    others = sorted(n for n in series.data["objects"] if n != NAME)
    host, traveler = others[0], others[1]
    series.host_tree.add(NAME, [host])
    series.host_tree.add(traveler, [NAME])
    carried = _object(series)
    assert carried["groups"] == [GROUP]
    assert carried["attrs"]["user_columns"] == {"Reviewer": "KH"}
    assert carried["attrs"]["alignment"] == pin
    assert carried["hosts"] == [host] and carried["travelers"] == [traveler]
    return carried


def test_undo_of_the_delete_brings_the_object_back_whole(window, full_object):
    series = window.series
    _delete(window, _traces(window))
    assert NAME not in series.data["objects"]
    assert _object(series)["groups"] == []

    window.undo()
    assert len(_traces(window)) == 1
    assert NAME in series.data["objects"]
    assert _object(series) == full_object

    window.undo(redo=True)
    assert _traces(window) == []
    assert NAME not in series.data["objects"]
    assert _object(series) == {
        "attrs": {}, "groups": [], "hosts": [], "travelers": [],
    }

    window.undo()
    assert len(_traces(window)) == 1
    assert _object(series) == full_object


@pytest.mark.parametrize("visible", [True, False])
def test_the_group_row_goes_with_the_delete_and_comes_back(window, visible):
    series = window.series
    # a second group keeps the Groups submenu in the menubar once GROUP is
    # gone, so the row checks look at a real menu
    keeper = sorted(series.data["objects"].keys())[-1]
    series.object_groups.add(group=KEEP, obj=keeper)
    series.groups_visibility[KEEP] = True
    _draw(window, {"groups": [GROUP]})
    series.groups_visibility[GROUP] = visible
    window.createMenuBar()
    assert GROUP in _menu_groups(window)

    _delete(window, _traces(window))
    assert GROUP not in series.groups_visibility
    assert GROUP not in _menu_groups(window)
    assert KEEP in _menu_groups(window)

    window.undo()
    assert series.groups_visibility[GROUP] is visible
    assert GROUP in _menu_groups(window)

    window.undo(redo=True)
    assert GROUP not in series.groups_visibility
    assert GROUP not in _menu_groups(window)

    window.undo()
    assert series.groups_visibility[GROUP] is visible
    assert GROUP in _menu_groups(window)


def test_undo_that_leaves_the_object_alone_keeps_its_attributes(window):
    """The object keeps a trace through the delete, so the undo must not
    put old values over the ones it carries now."""
    series = window.series
    _draw(window, offset=0.2)
    _draw(window, offset=0.6)
    series.setAttr(NAME, "comment", "before")
    _delete(window, _traces(window)[:1])
    assert NAME in series.data["objects"]
    series.setAttr(NAME, "comment", "after")

    window.undo()
    assert len(_traces(window)) == 2
    assert series.getAttr(NAME, "comment") == "after"


def test_a_group_emptied_by_deletes_on_two_sections_comes_back_hidden(window):
    """A on one section and B on another, both in a hidden GROUP. Deleting
    A leaves B in the group; deleting B empties it. Undoing A's delete
    brings the group back, and it must come back hidden."""
    series = window.series
    other = NAME + "_b"
    first, second = sorted(series.sections)[:2]
    window.changeSection(first)
    _draw(window, {"groups": [GROUP]})
    window.changeSection(second)
    _draw(window, {"groups": [GROUP]}, name=other)
    # set directly: `View` > `Groups` reloads the field, which is not under
    # test here
    series.groups_visibility[GROUP] = False

    window.changeSection(first)
    _delete(window, _traces(window))
    assert series.groups_visibility[GROUP] is False
    window.changeSection(second)
    _delete(window, _traces(window, other))
    assert GROUP not in series.object_groups.getGroupList()
    assert GROUP not in series.groups_visibility

    window.changeSection(first)
    window.undo()
    assert series.object_groups.getGroupObjects(GROUP) == {NAME}
    assert series.groups_visibility[GROUP] is False, (
        "the group came back shown"
    )


def test_an_object_list_delete_undone_on_all_sections_keeps_it_hidden(
        window, main_window_dialogs, monkeypatch):
    """The object, on two sections, is alone in a hidden group. Delete it
    from the object list, undo on all sections, redo, undo: the group comes
    back hidden each time."""
    series = window.series
    first, second = sorted(series.sections)[:2]
    window.changeSection(first)
    _draw(window, {"groups": [GROUP]})
    window.changeSection(second)
    _draw(window, {"groups": [GROUP]})
    series.groups_visibility[GROUP] = False

    field = window.field
    field.openList("object")
    table = field.table_manager.tables["object"][0]
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: table)
    monkeypatch.setattr(table, "getSelected", lambda: [NAME])
    field.deleteObjects()
    assert NAME not in series.data["objects"]

    main_window_dialogs.linked_undo_responses = ["all"] * 4
    window.undo()
    assert series.object_groups.getGroupObjects(GROUP) == {NAME}
    assert series.groups_visibility[GROUP] is False

    window.undo(redo=True)
    assert NAME not in series.data["objects"]
    assert GROUP not in series.groups_visibility

    window.undo()
    assert series.object_groups.getGroupObjects(GROUP) == {NAME}
    assert series.groups_visibility[GROUP] is False, (
        "the group came back shown"
    )


def test_a_redo_that_empties_nothing_replaces_the_old_value(window):
    """Draw A into GROUP, hide it, delete A's last trace, undo the delete;
    draw B into GROUP on another section and show it; redo A's delete,
    delete B's last trace, undo A's delete. The redo emptied nothing, so the
    False the first delete kept no longer applies, and GROUP comes back
    shown."""
    series = window.series
    other = NAME + "_b"
    first, second = sorted(series.sections)[:2]
    window.changeSection(first)
    _draw(window, {"groups": [GROUP]})
    series.groups_visibility[GROUP] = False
    _delete(window, _traces(window))
    window.undo()
    assert series.groups_visibility[GROUP] is False

    window.changeSection(second)
    _draw(window, {"groups": [GROUP]}, name=other)
    series.groups_visibility[GROUP] = True

    window.changeSection(first)
    window.undo(redo=True)                           # A's delete; B keeps GROUP
    assert series.object_groups.getGroupObjects(GROUP) == {other}
    window.changeSection(second)
    _delete(window, _traces(window, other))          # GROUP empties
    assert GROUP not in series.groups_visibility

    window.changeSection(first)
    window.undo()                                    # A's delete
    assert series.object_groups.getGroupObjects(GROUP) == {NAME}
    assert series.groups_visibility[GROUP] is True, (
        "the group came back hidden"
    )


def test_an_import_that_moves_an_object_keeps_its_attributes(tmp_path,
                                                              monkeypatch):
    """A is only on one section and carries a comment. The imported copy
    deleted A there and drew it on another section. The import removes A
    from the first section before it adds A on the second, and A must come
    out of it with its comment."""
    import shutil
    from pathlib import Path

    from PyReconstruct.modules.backend.notifier import NullNotifier
    from PyReconstruct.modules.backend.progress import NullProgressReporter
    from PyReconstruct.modules.backend.settings_store import DictSettingsStore
    from PyReconstruct.modules.datatypes.series import Series

    fixture = (Path(__file__).resolve().parents[1] / "dev" / "assets" /
               "checker" / "files" / "shapes1.jser")
    if not fixture.exists():
        pytest.skip("fixture shapes1.jser not found")
    # the username is read from the settings; never set it on the series
    monkeypatch.setattr(Series, "user", property(lambda self: "tester"))

    def open_series(fp):
        series = Series.openJser(str(fp), progress=NullProgressReporter,
                                 notifier=NullNotifier())
        series.setSettingsStore(DictSettingsStore())
        return series

    def square(series, snum, offset):
        section = series.loadSection(snum)
        t = Trace(NAME, (0, 255, 0), True)
        x0 = y0 = offset
        t.points = [(x0, y0), (x0 + 1, y0), (x0 + 1, y0 + 1), (x0, y0 + 1)]
        section.addTrace(t)
        section.save()

    here_fp = tmp_path / "here" / "series.jser"
    here_fp.parent.mkdir()
    shutil.copyfile(fixture, here_fp)
    here = open_series(here_fp)
    first, second = sorted(here.sections)[:2]
    square(here, first, 1.0)
    here.setAttr(NAME, "comment", "keep me")
    here.saveJser()

    there_fp = tmp_path / "there" / "series.jser"
    there_fp.parent.mkdir()
    shutil.copyfile(here_fp, there_fp)
    there = open_series(there_fp)
    section = there.loadSection(first)
    for trace in list(section.contours[NAME]):
        section.removeTrace(trace)
    section.save()
    square(there, second, 3.0)
    there.save()

    try:
        here.importTraces(there)
        assert NAME not in here.loadSection(first).contours or \
            not len(here.loadSection(first).contours[NAME])
        assert len(here.loadSection(second).contours[NAME]) == 1
        assert here.getAttr(NAME, "comment") == "keep me"
    finally:
        for series in (here, there):
            series.leave_open = False
            series.close()
