"""Object List Refresh recomputes only the objects shown by its filters."""
import pytest

from PyReconstruct.modules.datatypes import Series


pytestmark = pytest.mark.gui
TARGET = "Test1DenShaft"


@pytest.fixture
def object_list(main_window):
    series = main_window.series
    series.setOption("object_columns", [(name, shown or name == "Flat area")
                                       for name, shown in series.getOption("object_columns")])
    manager = main_window.field.table_manager
    manager.newTable("object")
    return manager.tables["object"][0]


def test_refresh_menu_preserves_unmatched_data_and_open_tables(object_list):
    widget = object_list
    target = "d03sp12"  # Shares section 44 with two unmatched objects.
    series = widget.series
    widget.re_filters = {target}
    widget.createTable()
    assert widget.model.names == [target]
    model = widget.model
    untouched = {
        name: data for name, data in series.data.objects.items() if name != target
    }
    untouched_traces = {
        name: {snum: tuple(traces) for snum, traces in data.traces.items()}
        for name, data in untouched.items()
    }
    before = series.data.getFlatArea(target)
    # Corrupt only the cached measurement; Refresh must read the saved traces.
    for traces in series.data.objects[target].traces.values():
        for trace in traces:
            trace.area = 0
            trace.length = 0
    assert series.data.getFlatArea(target) == 0

    widget.refresh_act.trigger()

    assert series.data.getFlatArea(target) == pytest.approx(before)
    assert widget.model is model
    assert all(series.data.objects[name] is data for name, data in untouched.items())
    for name, sections in untouched_traces.items():
        for snum, traces in sections.items():
            assert all(actual is expected for actual, expected in zip(
                series.data.objects[name].traces[snum], traces, strict=True))
    area_column = widget.horizontal_headers.index("Flat area")
    assert float(model.data(model.index(0, area_column))) == pytest.approx(before, abs=0.001)


@pytest.mark.parametrize("filter_kind", ["regex", "group", "selected", "empty"])
def test_refresh_loads_only_matching_sections(object_list, monkeypatch, filter_kind):
    widget = object_list
    series = widget.series
    if filter_kind == "regex":
        widget.re_filters = {TARGET}
    elif filter_kind == "group":
        series.object_groups.add("target", TARGET)
        widget.group_filters = {"target"}
    elif filter_kind == "selected":
        widget.selected_only = True
        widget.selected_names = {TARGET}
    else:
        widget.re_filters = {"no-such-object"}
    widget.createTable()
    expected = series.getObjectSections([TARGET]) if filter_kind != "empty" else set()
    visited = []
    original = Series.loadSection

    def load(self, snum):
        visited.append(snum)
        return original(self, snum)

    monkeypatch.setattr(Series, "loadSection", load)
    widget.refresh_act.trigger()
    assert set(visited) == expected
    assert len(visited) == len(expected)
    assert widget.model.names == ([TARGET] if expected else [])


def test_refresh_removes_deleted_traces_and_updates_other_lists(object_list):
    widget = object_list
    series = widget.series
    manager = widget.manager
    manager.newTable("object")
    other = manager.tables["object"][-1]
    manager.newTable("section")
    section_view = manager.tables["section"][0].table
    other_model = other.model
    widget.re_filters = {TARGET}
    widget.createTable()
    series.setAttr(TARGET, "comment", "retain this")
    for snum in series.getObjectSections([TARGET]):
        section = series.loadSection(snum)
        for trace in list(section.contours[TARGET]):
            section.removeTrace(trace, log_event=False)
        section.save(update_series_data=False)

    widget.refresh_act.trigger()

    assert TARGET not in series.data.objects
    assert widget.model.names == []
    assert TARGET not in other.model.names
    assert other.model is other_model
    assert manager.tables["section"][0].table is section_view
    assert not series.data.object_ids.live(TARGET)
    assert series.getAttr(TARGET, "comment") == "retain this"


def test_refresh_without_filter_reloads_all_objects(object_list):
    widget = object_list
    series = widget.series
    before = {name: series.data.getFlatArea(name) for name in series.data.objects}
    ids = dict(series.data.object_ids.placed)
    for obj in series.data.objects.values():
        for traces in obj.traces.values():
            for trace in traces:
                trace.area = 0

    widget.refresh_act.trigger()

    assert {name: series.data.getFlatArea(name) for name in before} == pytest.approx(before)
    assert series.data.object_ids.placed == ids


def test_one_object_edit_updates_only_its_row(object_list):
    widget = object_list
    model = widget.model
    changed = []
    model.dataChanged.connect(lambda first, last, roles: changed.append(
        (first.row(), last.row())))
    resets = []
    model.modelReset.connect(lambda: resets.append(True))
    widget.series.setAttr(TARGET, "comment", "edited")
    widget.manager.updateObjects([TARGET])
    row = model.rowOf(TARGET)[0]
    assert changed == [(row, row)]
    assert resets == []
    assert widget.model is model


def test_refresh_saves_pending_field_edits(object_list):
    widget = object_list
    section = widget.mainwindow.field.section
    trace = next(iter(section.contours.values()))[0]
    name = trace.name
    added = trace.copy()
    section.addTrace(added, log_event=False)
    widget.re_filters = {name}
    before = widget.series.data.getCount(name)

    widget.refresh_act.trigger()

    assert widget.series.data.getCount(name) == before + 1
    saved = widget.series.loadSection(section.n)
    assert len(saved.contours[name]) == len(section.contours[name])
