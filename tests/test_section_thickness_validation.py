"""The Section List refuses thicknesses that would corrupt measurements."""

from pathlib import Path

import pytest

from tests.test_section_list_real_widget import select_rows

pytestmark = pytest.mark.gui


@pytest.fixture
def thickness_table(main_window, gui_dialogs):
    manager = main_window.field.table_manager
    manager.newTable("section")
    widget = manager.tables["section"][-1]
    numbers = [int(widget.table.item(row, 0).text().split()[0]) for row in (0, 1)]
    for number in numbers:
        section = main_window.series.loadSection(number)
        section.align_locked = False
        section.save()
    manager.updateSections(numbers)
    select_rows(widget.table, (0, 1))
    assert widget.getSelected() == numbers
    return widget, numbers


@pytest.mark.parametrize("text", ["0", "-1", "nan", "inf", "-inf", "1e309"])
def test_invalid_thickness_preserves_selected_sections(thickness_table, monkeypatch, gui_dialogs, text):
    widget, numbers = thickness_table
    series = widget.series
    sections = [series.loadSection(number) for number in numbers]
    before = {section.filepath: Path(section.filepath).read_bytes() for section in sections}
    thicknesses = {section.n: section.thickness for section in sections}
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.section.QInputDialog.getText",
        lambda *args, **kwargs: (text, True),
    )

    widget.editThickness()

    assert {path: Path(path).read_bytes() for path in before} == before
    for number in numbers:
        assert series.data["sections"][number]["thickness"] == thicknesses[number]
        assert series.loadSection(number).thickness == thicknesses[number]
    assert gui_dialogs.notices == ["Section thickness must be a positive, finite number."]


def test_positive_thickness_is_saved_for_all_selected_sections(thickness_table, monkeypatch):
    widget, numbers = thickness_table
    monkeypatch.setattr(
        "PyReconstruct.modules.gui.table.section.QInputDialog.getText",
        lambda *args, **kwargs: ("0.075", True),
    )

    widget.editThickness()

    for number in numbers:
        assert widget.series.loadSection(number).thickness == pytest.approx(0.075)
        assert widget.series.data["sections"][number]["thickness"] == pytest.approx(0.075)
