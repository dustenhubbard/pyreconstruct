"""An object list that shows only the objects with a selected trace (fork #438).

The field shows the names of the selected traces in its corner and nothing
else. Lists > Object list of selected traces opens an object list limited to
those objects, with their usual columns, and it follows the selection. The
same filter is a checkbox in any object list's Filter menu.
"""
import pytest

pytestmark = pytest.mark.gui


def _traces_by_object(section):
    """The objects on the section, each with its traces."""
    by_name = {}
    for trace in section.tracesAsList():
        by_name.setdefault(trace.name, []).append(trace)
    names = sorted(by_name)
    assert len(names) >= 3, "fixture section has too few objects"
    return names, by_name


def _rows(table):
    return list(table.model.names)


def test_lists_menu_opens_a_list_of_the_selected_objects(main_window):
    field = main_window.field
    names, by_name = _traces_by_object(field.section)
    a, b = names[0], names[1]

    field.selectTraces(by_name[a][:1], [])
    main_window.selectedobjectlist_act.trigger()

    table = field.table_manager.tables["object"][-1]
    assert table.selected_only
    assert _rows(table) == [a]
    assert "selected traces" in table.windowTitle()
    assert table.selectedonlyfilter_act.isChecked()

    # the list follows the selection in the field
    field.selectTraces(by_name[b][:1], [])
    assert sorted(_rows(table)) == sorted([a, b])

    field.deselectAllTraces()
    assert _rows(table) == []


def test_plain_object_list_is_unchanged(main_window):
    field = main_window.field
    names, by_name = _traces_by_object(field.section)

    field.openList("object")
    table = field.table_manager.tables["object"][-1]
    everything = _rows(table)
    assert len(everything) == len(main_window.series.data["objects"])

    field.selectTraces(by_name[names[0]][:1], [])
    assert not table.selected_only
    assert _rows(table) == everything
    assert not table.selectedonlyfilter_act.isChecked()


def test_filter_menu_toggles_the_selected_traces_filter(main_window):
    field = main_window.field
    names, by_name = _traces_by_object(field.section)
    a = names[0]

    field.openList("object")
    table = field.table_manager.tables["object"][-1]
    everything = _rows(table)
    field.selectTraces(by_name[a][:1], [])

    table.selectedonlyfilter_act.trigger()
    assert _rows(table) == [a]

    table.selectedonlyfilter_act.trigger()
    assert not table.selected_only
    assert _rows(table) == everything
    assert "selected traces" not in table.windowTitle()
