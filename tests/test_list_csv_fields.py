"""List exports preserve field boundaries and the text displayed in each cell."""

import csv

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

from PyReconstruct.modules.gui.table.copy_table_widget import CopyTableWidget
from PyReconstruct.modules.gui.table.data_table import DataTable
from PyReconstruct.modules.gui.table.object import ObjectTableWidget
from PyReconstruct.modules.gui.table.object_model import ObjectTableModel

pytestmark = pytest.mark.gui


class _Rows:
    def __init__(self, headers, rows):
        self.headers = headers
        self.static_columns = [headers[0]]
        self.columns = [(header, True) for header in headers[1:]]
        self.rows = {row[0].text(): row for row in rows}

    def getHeaders(self):
        return self.headers

    def getFiltered(self):
        return list(self.rows)

    def getItems(self, name, key):
        return [self.rows[name][self.headers.index(key)]]


@pytest.fixture(params=["table", "object"])
def export_list(request, qtbot, monkeypatch):
    def export(headers, rows, path):
        cells = []
        for row in rows:
            items = []
            for value in row:
                item = QTableWidgetItem()
                if isinstance(value, Qt.CheckState):
                    item.setCheckState(value)
                else:
                    item.setText(value)
                items.append(item)
            cells.append(items)

        if request.param == "table":
            table = CopyTableWidget(None, len(cells), len(headers))
            qtbot.addWidget(table)
            table.setHorizontalHeaderLabels(headers)
            for r, row in enumerate(cells):
                for c, item in enumerate(row):
                    table.setItem(r, c, item)
            widget = DataTable.__new__(DataTable)
            widget.table = table
        else:
            widget = ObjectTableWidget.__new__(ObjectTableWidget)
            widget.model = ObjectTableModel(_Rows(headers, cells))
        widget.name = "objects"
        monkeypatch.setattr(
            "PyReconstruct.modules.gui.table.data_table.FileDialog.get",
            staticmethod(lambda *args, **kwargs: str(path) if path else ""),
        )
        widget.export()

    return export


def test_csv_preserves_text_and_checkbox_values(export_list, tmp_path):
    out = tmp_path / "list.csv"
    export_list(
        ["Name", 'Cell,"type"\nreview', "Locked", "CR", "Comment"],
        [
            ["axon1", "α,β", Qt.Checked, Qt.PartiallyChecked,
             'reviewed, keep "both"\nnext line'],
            ["axon2", "", Qt.Unchecked, Qt.Checked, "  keep spaces  "],
            ["axon3", "dendrite", Qt.Checked, 'text, not a checkbox',
             "first\rsecond\r\nthird"],
        ],
        out,
    )

    with out.open(encoding="utf-8", newline="") as stream:
        assert list(csv.reader(stream)) == [
            ["Name", 'Cell,"type"\nreview', "Locked", "CR", "Comment"],
            ["axon1", "α,β", "yes", "partial", 'reviewed, keep "both"\nnext line'],
            ["axon2", "", "no", "yes", "  keep spaces  "],
            ["axon3", "dendrite", "yes", 'text, not a checkbox',
             "first\rsecond\r\nthird"],
        ]


def test_empty_list_exports_a_quoted_header(export_list, tmp_path):
    out = tmp_path / "empty.csv"
    export_list(["Name", "Cell,type"], [], out)

    with out.open(encoding="utf-8", newline="") as stream:
        assert list(csv.reader(stream)) == [["Name", "Cell,type"]]


def test_canceling_export_leaves_existing_files_alone(export_list, tmp_path):
    existing = tmp_path / "objects.csv"
    existing.write_text("existing export", encoding="utf-8")

    export_list(["Name"], [["axon1"]], None)

    assert existing.read_text(encoding="utf-8") == "existing export"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["objects.csv"]
