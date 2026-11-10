"""Export the real Object list through its List > Export action."""

import csv

import pytest

from test_data_lists_real_widget import list_mainwindow, object_table  # noqa: F401 (fixtures)

pytestmark = pytest.mark.gui


def _export(widget, tmp_path, monkeypatch):
    output = tmp_path / "objects.csv"
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.object.FileDialog.get",
        staticmethod(lambda *args, **kwargs: str(output)),
    )
    widget.export_act.trigger()
    with output.open(newline="") as stream:
        return list(csv.reader(stream))


@pytest.mark.parametrize(
    "comment",
    [
        "first\nsecond", "first\rsecond", "first\r\nsecond", "first, second",
        '"quoted"', 'first, "second"\nthird', "caf\u00e9 \u03bc", "",
    ],
)
def test_export_preserves_comments_and_columns(
    object_table, tmp_path, monkeypatch, comment,  # noqa: F811 (fixture)
):
    widget = object_table
    series = widget.series
    names = [widget.model.nameAt(row) for row in range(widget.model.rowCount())]
    assert len(names) == 8
    series.setAttr(names[0], "comment", comment)
    series.setAttr(names[0], "locked", True)
    series.setCuration([names[0]], "Curated")
    widget.columns = [
        (key, key in {"Comment", "Count", "Locked", "Curate"})
        for key, _ in widget.columns
    ]
    widget.createTable()

    headers, *rows = _export(widget, tmp_path, monkeypatch)

    assert len(rows) == 8
    assert [row[0] for row in rows] == names
    assert all(len(row) == len(headers) for row in rows)
    first = dict(zip(headers, rows[0]))
    assert first["Comment"] == comment
    assert first["Locked"] == "yes"
    assert first["CR"] == "yes"
    assert first["Status"] == "Curated"
    assert first["Count"] == str(series.data.getCount(names[0]))


@pytest.mark.parametrize(
    "header",
    ["Review,status", 'Review"status"', "Review\nstatus", "Review\rstatus"],
)
def test_export_preserves_user_columns_and_filtered_rows(
    object_table, tmp_path, monkeypatch, header,  # noqa: F811 (fixture)
):
    widget = object_table
    names = [widget.model.nameAt(row) for row in range(2)]
    value = 'checked,"again"\r\nnext'
    widget.series.addUserCol(header, [value], log_event=False)
    widget.series.setUserColAttr(names[0], header, value)
    widget.columns = [(key, False) for key, _ in widget.columns] + [(header, True)]
    widget.selected_only = True
    widget.selected_names = set(names)
    widget.createTable()

    assert _export(widget, tmp_path, monkeypatch) == [
        ["Name", header], [names[0], value], [names[1], ""],
    ]
