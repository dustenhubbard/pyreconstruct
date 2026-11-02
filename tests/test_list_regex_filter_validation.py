"""Invalid name filters preserve the trace and object lists' valid state."""

import pytest

pytestmark = pytest.mark.gui


def _names(widget):
    model = widget.table.model()
    return [model.index(row, 0).data() for row in range(model.rowCount())]


@pytest.fixture(params=["trace", "object"])
def regex_list(request, main_window, gui_dialogs, qapp):
    field = main_window.field
    field.changeSection(44)
    field.openList(list_type=request.param)
    widget = field.table_manager.tables[request.param][0]
    gui_dialogs.responses.append(([["d03"]], True))
    widget.setREFilter()
    qapp.processEvents()
    assert _names(widget) == ["d03"]
    assert not widget.table.isHidden()
    return widget


@pytest.mark.parametrize("filters", [["["], ["d03", "("]])
def test_invalid_regex_preserves_filter_and_rows(
    regex_list, gui_dialogs, filters, qapp
):
    widget = regex_list
    table = widget.table
    rows = _names(widget)
    gui_dialogs.responses.append(([filters], True))

    widget.setREFilter()

    assert widget.re_filters == {"d03"}
    assert widget.table is table
    assert not table.isHidden()
    assert _names(widget) == rows
    assert len(gui_dialogs.notices) == 1
    assert "Invalid regex filter" in gui_dialogs.notices[0]
    assert filters[-1] in gui_dialogs.notices[0]

    widget.manager.recreateTable(widget)
    qapp.processEvents()
    assert _names(widget) == rows
    assert not widget.table.isHidden()


@pytest.mark.parametrize("filters", [[], ["d##"], ["d03", "d03p12"]])
def test_valid_regex_rebuilds_filtered_rows(regex_list, gui_dialogs, filters, qapp):
    widget = regex_list
    gui_dialogs.responses.append(([filters], True))

    widget.setREFilter()

    qapp.processEvents()
    if not filters:
        assert widget.re_filters == {".*"}
        assert len(_names(widget)) == (5 if widget.name == "trace" else 8)
    elif filters == ["d##"]:
        assert widget.re_filters == {"d[0-9][0-9]"}
        assert _names(widget) == ["d03"]
    else:
        assert widget.re_filters == {"d03", "d03p12"}
        assert _names(widget) == ["d03", "d03p12"]
    assert not widget.table.isHidden()
    assert gui_dialogs.notices == []


def test_canceled_regex_preserves_filter_and_rows(regex_list, gui_dialogs):
    widget = regex_list
    table = widget.table
    rows = _names(widget)
    gui_dialogs.responses.append((None, False))

    widget.setREFilter()

    assert widget.re_filters == {"d03"}
    assert widget.table is table
    assert _names(widget) == rows
    assert gui_dialogs.notices == []


def test_invalid_regex_is_rejected_when_no_rows_match(regex_list, gui_dialogs, qapp):
    widget = regex_list
    gui_dialogs.responses.append(([["no_matching_object"]], True))
    widget.setREFilter()
    qapp.processEvents()
    assert _names(widget) == []
    table = widget.table
    gui_dialogs.responses.append(([["["]], True))

    widget.setREFilter()

    assert widget.re_filters == {"no_matching_object"}
    assert widget.table is table
    assert not table.isHidden()
    assert _names(widget) == []
    assert len(gui_dialogs.notices) == 1
    assert "Invalid regex filter" in gui_dialogs.notices[0]
