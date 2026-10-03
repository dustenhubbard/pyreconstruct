"""Follow-ups to the undo that brings a deleted object back whole (#687).

Three gaps remained after it:

* The object list's `Alignment` cell showed the current alignment after the
  undo, not the pin the undo put back, until the row was refreshed.
* An object list action (delete, rename) saves each section before its undo
  state is added, so the copy of a deleted object was already empty. Undo
  with `Only this section` brought the trace back bare.
* A host link between two objects deleted on two sections was lost: the
  second delete's copy no longer had the link, and the first undo could not
  put it back while the other object was still gone.
"""
import pytest

from PyReconstruct.modules.datatypes.trace import Trace

pytestmark = pytest.mark.gui

NAME = "undofu_obj"
OTHER = "undofu_other"
GROUP = "undofu_group"


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


def _draw(window, name=NAME, defaults=None, offset=0.2):
    field = window.field
    item = Trace(name, (0, 255, 0), True)
    item.obj_defaults = defaults
    field.setTracingTrace(item)
    field.newTrace(_square(window.series, offset), field.tracing_trace,
                   points_as_pix=False, reduce_points=False)


def _traces(window, name=NAME):
    return [t for t in window.field.section.tracesAsList() if t.name == name]


def _delete(window, traces):
    window.field.section.selected_traces = list(traces)
    window.field.deleteTraces()


def _object(series, name=NAME):
    attrs = dict(series.obj_attrs.get(name) or {})
    attrs.pop("last_user", None)
    return {
        "attrs": attrs,
        "groups": sorted(series.object_groups.getObjectGroups(name)),
        "hosts": sorted(series.host_tree.getHosts(name)),
        "travelers": sorted(series.host_tree.getTravelers(name)),
    }


def _carry(window, name=NAME):
    """Give the object a comment, a group, an alignment pin other than the
    current one, and a host; return what it carries."""
    series = window.series
    series.setAttr(name, "comment", "keep me")
    series.object_groups.add(group=GROUP, obj=name)
    series.groups_visibility.setdefault(GROUP, True)
    pin = next(a for a in series.alignments if a != series.alignment)
    series.setAttr(name, "alignment", pin)
    host = sorted(n for n in series.data["objects"] if n != name)[0]
    series.host_tree.add(name, [host])
    return _object(series, name)


def _object_list(window, monkeypatch, selected):
    field = window.field
    field.openList("object")
    table = field.table_manager.tables["object"][0]
    monkeypatch.setattr(field.table_manager, "hasFocus", lambda: table)
    monkeypatch.setattr(table, "getSelected", lambda: list(selected))
    return table


def _alignment_cell(table, name):
    model = table.model
    row, exists = model.rowOf(name)
    assert exists, f"{name} has no row"
    col = list(model.headers).index("Alignment")
    return model.data(model.index(row, col))


def test_the_alignment_cell_shows_the_pin_after_undo(window, monkeypatch):
    series = window.series
    cols = [(k, True if k == "Alignment" else v)
            for k, v in series.getOption("object_columns")]
    series.setOption("object_columns", cols)
    _draw(window)
    pin = _carry(window)["attrs"]["alignment"]
    table = _object_list(window, monkeypatch, [])
    window.field.table_manager.updateObjects([NAME])
    assert _alignment_cell(table, NAME) == pin

    _delete(window, _traces(window))
    window.undo()
    assert series.getAttr(NAME, "alignment") == pin
    assert _alignment_cell(table, NAME) == pin

    window.undo(redo=True)
    window.undo()
    assert _alignment_cell(table, NAME) == pin


@pytest.mark.parametrize("undo_on", [0, 1])
def test_object_list_delete_undone_on_this_section_only(
        window, monkeypatch, main_window_dialogs, undo_on):
    """The object is on two sections. The delete saves the first section
    while the object is still on the second, and the second after it is
    gone; undo on either one brings it back whole."""
    series = window.series
    sections = sorted(series.sections)[:2]
    window.changeSection(sections[1])
    _draw(window)
    window.changeSection(sections[0])
    _draw(window)
    carried = _carry(window)

    _object_list(window, monkeypatch, [NAME])
    window.field.deleteObjects()
    assert NAME not in series.data["objects"]
    window.changeSection(sections[undo_on])

    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo()
    assert len(_traces(window)) == 1
    assert _object(series) == carried

    window.undo(redo=True)
    assert NAME not in series.data["objects"]
    assert _object(series)["groups"] == []

    window.undo()
    assert _object(series) == carried


def test_object_list_rename_undone_on_this_section_only(window, monkeypatch,
                                                        main_window_dialogs):
    """The object is on one section; the rename deletes it there."""
    series = window.series
    _draw(window)
    carried = _carry(window)

    window.saveAllData()
    series.editObjectAttributes([NAME], name=OTHER,
                                series_states=window.field.series_states)
    window.field.reload()
    window.field.table_manager.recreateTables()
    assert NAME not in series.data["objects"]
    assert OTHER in series.data["objects"]

    main_window_dialogs.linked_undo_responses = ["section"]
    window.undo()
    assert len(_traces(window)) == 1
    assert OTHER not in series.data["objects"]
    assert _object(series) == carried

    window.undo(redo=True)
    assert NAME not in series.data["objects"]
    assert _object(series, OTHER)["attrs"]["comment"] == "keep me"

    window.undo()
    assert _object(series) == carried


@pytest.mark.parametrize("delete_first", ["host", "traveler"])
@pytest.mark.parametrize("undo_first", ["host", "traveler"])
def test_a_host_link_comes_back_when_both_deletes_are_undone(
        window, delete_first, undo_first):
    """H is only on one section and T only on another; T is hosted by H.
    Delete each, undo each, in every order: T is hosted by H again."""
    series = window.series
    host, traveler = NAME, OTHER
    first, second = sorted(series.sections)[:2]
    where = {host: first, traveler: second}
    window.changeSection(first)
    _draw(window, host)
    window.changeSection(second)
    _draw(window, traveler)
    series.host_tree.add(traveler, [host])

    order = [host, traveler] if delete_first == "host" else [traveler, host]
    for name in order:
        window.changeSection(where[name])
        _delete(window, _traces(window, name))
    assert not series.host_tree.getHosts(traveler) or \
        traveler not in series.data["objects"]

    order = [host, traveler] if undo_first == "host" else [traveler, host]
    for name in order:
        window.changeSection(where[name])
        window.undo()
        assert name in series.data["objects"]
    assert series.host_tree.getHosts(traveler) == [host]

    # redo the second delete and undo it again
    window.undo(redo=True)
    assert order[-1] not in series.data["objects"]
    window.undo()
    assert series.host_tree.getHosts(traveler) == [host]


def test_a_new_object_with_the_old_name_does_not_take_the_link(window):
    """Delete H, then draw a new H. Deleting and undoing T must not make the
    new H its host."""
    series = window.series
    host, traveler = NAME, OTHER
    first, second, third = sorted(series.sections)[:3]
    window.changeSection(first)
    _draw(window, host)
    window.changeSection(second)
    _draw(window, traveler)
    series.host_tree.add(traveler, [host])

    window.changeSection(first)
    _delete(window, _traces(window, host))
    window.changeSection(third)
    _draw(window, host)

    window.changeSection(second)
    _delete(window, _traces(window, traveler))
    window.undo()
    assert traveler in series.data["objects"]
    assert series.host_tree.getHosts(traveler) == []


def test_an_object_renamed_to_the_old_name_does_not_take_the_link(window):
    """Delete T, then rename another object to T from the object list.
    Deleting and undoing the new T must not make H its host."""
    series = window.series
    host, traveler, other = NAME, OTHER, "undofu_x"
    first, second, third = sorted(series.sections)[:3]
    window.changeSection(first)
    _draw(window, host)
    window.changeSection(second)
    _draw(window, traveler)
    window.changeSection(third)
    _draw(window, other)
    series.host_tree.add(traveler, [host])

    window.changeSection(second)
    _delete(window, _traces(window, traveler))
    window.saveAllData()
    series.editObjectAttributes([other], name=traveler,
                                series_states=window.field.series_states)
    window.field.reload()

    window.changeSection(third)
    _delete(window, _traces(window, traveler))
    window.undo()
    assert traveler in series.data["objects"]
    assert series.host_tree.getHosts(traveler) == []
