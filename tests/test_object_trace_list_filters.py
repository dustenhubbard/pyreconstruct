"""Filtering a real list preserves the identities used by row actions."""

import pytest

from PyReconstruct.modules.backend.settings_store import DictSettingsStore
from PyReconstruct.modules.datatypes import Series, Trace
from PyReconstruct.modules.gui.table.object import ObjectTableWidget
from PyReconstruct.modules.gui.table.trace import TraceTableWidget
from tests.test_data_lists_real_widget import (
    StubListManager,
    list_mainwindow,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.gui


@pytest.fixture
def real_series(tmp_path):
    series = Series.new([str(tmp_path / "image.tif")], "filters", 1, 0.05)
    series.setSettingsStore(DictSettingsStore())
    section = series.loadSection(0)
    for name, closed, hidden, tags in [
        ("cell2", True, False, {"keep"}),
        ("cell2", False, True, {"draft"}),
        ("cell10", True, True, {"keep"}),
        ("cell20", True, False, {"review"}),
        ("cell2_extra", False, False, {"keep"}),
    ]:
        trace = Trace(name, (10, 20, 30), closed=closed)
        trace.points = [(0, 0), (2, 0), (2, 2)]
        trace.hidden = hidden
        trace.tags = tags
        section.addTrace(trace)
    section.save()
    for name in ("cell2", "cell10"):
        series.object_groups.add("dendrite", name)
    series.object_groups.add("axon", "cell20")
    series.user_columns = {"Type": ["spine", "shaft"], "Quality": ["good", "bad"]}
    series.setAttr("cell2", "user_columns", {"Type": "spine", "Quality": "bad"})
    series.setAttr("cell10", "user_columns", {"Type": "shaft", "Quality": "good"})
    series.setAttr("cell20", "user_columns", {"Type": "spine"})
    series.setAttr("cell10", "curation", (False, "Lee", "2026-11-02"))
    series.setAttr("cell20", "curation", (True, "Sam", "2026-11-02"))
    series.setObjHosts(["cell10"], ["cell2"])
    series.setObjHosts(["cell20"], ["cell10"])
    yield series
    series.close()


@pytest.fixture(params=["object", "trace"])
def filtered_list(request, list_mainwindow, gui_dialogs):  # noqa: F811
    manager = StubListManager()
    series = list_mainwindow.series
    if request.param == "object":
        widget = ObjectTableWidget(series, list_mainwindow, manager)
        manager.recreateTable = lambda table: table.createTable()
    else:
        widget = TraceTableWidget(
            series, list_mainwindow.field.section, list_mainwindow, manager
        )
        manager.recreateTable = lambda table: table.createTable(table.section)
    yield widget
    widget.deleteLater()


def names(widget):
    model = widget.table.model()
    return [model.index(row, 0).data() for row in range(model.rowCount())]


def respond(widget, dialogs, method, response):
    dialogs.responses.append((response, True))
    getattr(widget, method)()


def test_regex_filter_fullmatches_and_clearing_restores_rows(filtered_list, gui_dialogs):
    respond(filtered_list, gui_dialogs, "setREFilter", (["cell#"],))
    expected = ["cell2"] if filtered_list.name == "object" else ["cell2", "cell2"]
    assert names(filtered_list) == expected

    respond(filtered_list, gui_dialogs, "setREFilter", (["cell10", "cell20"],))
    assert names(filtered_list) == ["cell10", "cell20"]
    filtered_list.table.selectRow(1)
    if filtered_list.name == "object":
        assert filtered_list.getSelected(single=True) == "cell20"
    else:
        assert filtered_list.getSelected(single=True) == ("cell20", 0)

    respond(filtered_list, gui_dialogs, "setREFilter", ([],))
    expected = ["cell10", "cell2", "cell20", "cell2_extra"]
    if filtered_list.name == "trace":
        expected.insert(expected.index("cell2"), "cell2")
    assert names(filtered_list) == expected


@pytest.mark.parametrize("method", ["setREFilter", "setGroupFilter", "setTagFilter"])
def test_canceling_a_filter_preserves_the_rows_and_selection(filtered_list, gui_dialogs, method):
    respond(filtered_list, gui_dialogs, "setREFilter", (["cell10"],))
    filtered_list.table.selectRow(0)
    gui_dialogs.responses.append((None, False))

    getattr(filtered_list, method)()

    assert names(filtered_list) == ["cell10"]
    expected = "cell10" if filtered_list.name == "object" else ("cell10", 0)
    assert filtered_list.getSelected(single=True) == expected


def test_group_and_tag_filters_intersect_but_each_accepts_any_value(filtered_list, gui_dialogs):
    respond(filtered_list, gui_dialogs, "setGroupFilter", (["dendrite", "axon"],))
    respond(filtered_list, gui_dialogs, "setTagFilter", (["keep", "draft"],))
    expected = ["cell10", "cell2"]
    if filtered_list.name == "trace":
        expected.insert(expected.index("cell2"), "cell2")
    assert names(filtered_list) == expected

    respond(filtered_list, gui_dialogs, "setTagFilter", (["review"],))
    assert names(filtered_list) == ["cell20"]
    filtered_list.table.selectRow(0)
    expected = "cell20" if filtered_list.name == "object" else ("cell20", 0)
    assert filtered_list.getSelected(single=True) == expected


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        pytest.param("[", "unterminated character set", id="syntax"),
        pytest.param("a{4294967295}", "the repetition number is too large", id="overflow"),
        pytest.param(
            "(" * 600 + "a" + ")" * 600,
            "maximum recursion depth exceeded",
            id="nesting",
        ),
    ],
)
def test_invalid_regex_preserves_the_last_working_filter(filtered_list, gui_dialogs, pattern, message):
    respond(filtered_list, gui_dialogs, "setREFilter", (["cell10"],))
    filtered_list.table.selectRow(0)

    respond(filtered_list, gui_dialogs, "setREFilter", (["cell#", pattern],))

    assert names(filtered_list) == ["cell10"]
    assert filtered_list.re_filters == {"cell10"}
    expected = "cell10" if filtered_list.name == "object" else ("cell10", 0)
    assert filtered_list.getSelected(single=True) == expected
    assert len(gui_dialogs.notices) == 1
    assert gui_dialogs.notices[0].startswith(f"Invalid regex filter: {message}")
    respond(filtered_list, gui_dialogs, "setREFilter", (["cell20"],))
    assert names(filtered_list) == ["cell20"]


@pytest.fixture
def object_list(list_mainwindow, gui_dialogs):  # noqa: F811
    manager = StubListManager()
    widget = ObjectTableWidget(list_mainwindow.series, list_mainwindow, manager)
    manager.recreateTable = lambda table: table.createTable()
    yield widget
    widget.deleteLater()


@pytest.mark.parametrize(
    ("statuses", "users", "expected"),
    [
        ([False, True, False], [], ["cell10"]),
        ([False, False, True], [], ["cell20"]),
        ([True, False, False], [], ["cell2", "cell2_extra"]),
        ([True, True, True], ["Lee"], ["cell10"]),
        ([True, True, True], ["Sam"], ["cell20"]),
    ],
)
def test_object_list_curation_filters_status_and_assignee(object_list, gui_dialogs, statuses, users, expected):
    columns = [(name, enabled or name == "Curate") for name, enabled in object_list.columns]
    object_list.columns = columns
    object_list.createTable()
    response = (list(zip(["Blank", "Needs curation", "Curated"], statuses)), users)

    respond(object_list, gui_dialogs, "setCRFilter", response)

    assert names(object_list) == expected


@pytest.mark.parametrize(
    ("configuration", "expected"),
    [("open", ["cell2_extra"]), ("closed", ["cell10", "cell20"]), ("mixed", ["cell2"])],
)
def test_object_list_configuration_filter(object_list, gui_dialogs, configuration, expected):
    columns = [(name, enabled or name == "Configuration") for name, enabled in object_list.columns]
    object_list.columns = columns
    object_list.createTable()
    response = ([(name, name == configuration) for name in ("closed", "open", "mixed")],)

    respond(object_list, gui_dialogs, "setConfigurationFilter", response)

    assert names(object_list) == expected


def test_object_list_host_filter_includes_self_and_optional_descendants(object_list, gui_dialogs):
    respond(object_list, gui_dialogs, "setHostFilter", (["cell2"], [("limit to direct hosts", False)]))
    assert names(object_list) == ["cell10", "cell2", "cell20"]
    respond(object_list, gui_dialogs, "setHostFilter", (["cell2"], [("limit to direct hosts", True)]))
    assert names(object_list) == ["cell10", "cell2"]


def test_object_list_categorical_filter_toggle_and_clear(object_list):
    object_list.toggleUserColFilter("Type", "spine")
    assert names(object_list) == ["cell2", "cell20"]
    object_list.toggleUserColFilter("Quality", "good")
    assert names(object_list) == ["cell10", "cell2", "cell20"]
    object_list.toggleUserColFilter("Type", "spine")
    assert names(object_list) == ["cell10"]
    object_list.clearUserColFilters()
    assert names(object_list) == ["cell10", "cell2", "cell20", "cell2_extra"]


def test_object_list_filtered_updates_preserve_the_selected_object(object_list):
    object_list.toggleUserColFilter("Type", "spine")
    object_list.table.selectRow(1)
    assert object_list.getSelected(single=True) == "cell20"

    object_list.series.setAttr("cell10", "user_columns", {"Type": "spine"})
    object_list.updateData(["cell10"])
    assert names(object_list) == ["cell10", "cell2", "cell20"]
    assert object_list.getSelected(single=True) == "cell20"

    object_list.series.setAttr("cell2", "user_columns", {"Type": "shaft"})
    object_list.updateData(["cell2"])
    assert names(object_list) == ["cell10", "cell20"]
    assert object_list.getSelected(single=True) == "cell20"

    object_list.series.setAttr("cell2", "user_columns", {"Type": "spine"})
    object_list.updateData(["cell2"])
    assert names(object_list) == ["cell10", "cell2", "cell20"]
    assert object_list.getSelected(single=True) == "cell20"


@pytest.fixture
def trace_list(list_mainwindow, gui_dialogs):  # noqa: F811
    manager = StubListManager()
    widget = TraceTableWidget(
        list_mainwindow.series, list_mainwindow.field.section, list_mainwindow, manager
    )
    manager.recreateTable = lambda table: table.createTable(table.section)
    yield widget
    widget.deleteLater()


def test_trace_list_hidden_filter_preserves_the_contour_index(trace_list, gui_dialogs):
    widget = trace_list
    respond(widget, gui_dialogs, "setREFilter", (["cell2"],))
    for selected, expected in [(1, ("cell2", 1)), (2, ("cell2", 0))]:
        choices = [
            ("all traces", selected == 0),
            ("only hidden traces", selected == 1),
            ("only unhidden traces", selected == 2),
        ]
        respond(widget, gui_dialogs, "setHideFilter", (choices,))
        assert names(widget) == ["cell2"]
        widget.table.selectRow(0)
        assert widget.getSelected(single=True) == expected
        assert widget.getTraces([expected]) == [widget.section.contours["cell2"][expected[1]]]
    respond(widget, gui_dialogs, "setHideFilter", ([("all traces", True), ("hidden", False), ("unhidden", False)],))
    assert names(widget) == ["cell2", "cell2"]


def test_trace_list_filtered_updates_keep_the_original_trace_index(trace_list):
    section = trace_list.section
    trace_list.hide_filter = "hidden"
    trace_list.createTable(section)
    assert names(trace_list) == ["cell10", "cell2"]

    section.removeTrace(section.contours["cell10"][0])
    added = Trace("cell1", (10, 20, 30))
    added.points = [(0, 0), (1, 0), (1, 1)]
    added.hidden = True
    section.addTrace(added)
    trace_list.series.data.updateSection(section, update_traces=True)
    trace_list.updateData(["cell10", "cell1"])

    assert names(trace_list) == ["cell1", "cell2"]
    trace_list.table.selectRow(1)
    assert trace_list.getSelected(single=True) == ("cell2", 1)
    trace = trace_list.getTraces([("cell2", 1)])[0]
    assert (trace.name, trace.hidden, trace.tags) == ("cell2", True, {"draft"})
